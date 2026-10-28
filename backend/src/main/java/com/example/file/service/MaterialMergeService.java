package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.file.common.BizException;
import com.example.file.entity.Material;
import com.example.file.entity.MaterialMerge;
import com.example.file.mapper.MaterialMapper;
import com.example.file.mapper.MaterialMergeMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.ResourceAccessException;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;

/**
 * 素材精炼 / 合并（素材流程第 ③ 步，在素材库上做，每一步都由用户确认）：
 * <ol>
 *   <li>查找：本地向量模型找出同分类里互相很像的素材组（跨书的「狼人」、同书近似重复），存为 FOUND 建议，不花 token；</li>
 *   <li>写合并稿（可选）：对选中的建议逐组让大模型 / GGUF 判断哪些是同一种东西、写主条目共性和每条的「这本书的写法」，
 *       一组写完立刻落库（天然断点：暂停 / 重启后没写的回到 FOUND，再点一次接着写）；</li>
 *   <li>合并：用户确认（可改主条目、去掉不该合的成员）→ 新建主条目（source = {type: merge, members, variants}），
 *       成员的 merged_into 指向它，不再出现在列表 / 检索 / AI 里；拆分 = 删主条目、成员还原。</li>
 * </ol>
 */
@Service
public class MaterialMergeService {

    private static final Logger log = LoggerFactory.getLogger(MaterialMergeService.class);

    private static final int POOL = 20000;
    private static final int MAX_GROUP = 12;
    private static final List<String> OPEN = List.of(MaterialMerge.FOUND, MaterialMerge.DRAFTING, MaterialMerge.DRAFTED);

    private final MaterialMergeMapper mergeMapper;
    private final MaterialMapper materialMapper;
    private final MaterialService materialService;
    private final NovelExtractService extractService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "material-merge");
        t.setDaemon(true);
        return t;
    });

    /** 写合并稿的进度（一次只跑一批） */
    private volatile boolean running;
    private volatile boolean stopRequested;
    private volatile int total;
    private volatile int done;
    private volatile int failed;
    private volatile Long currentId;
    private volatile String lastError;

    public MaterialMergeService(MaterialMergeMapper mergeMapper, MaterialMapper materialMapper, MaterialService materialService,
                                NovelExtractService extractService, AiServiceClient aiClient, ObjectMapper objectMapper) {
        this.mergeMapper = mergeMapper;
        this.materialMapper = materialMapper;
        this.materialService = materialService;
        this.extractService = extractService;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    /** 重启时，上次没写完的合并稿回到 FOUND（再点「AI 写合并稿」接着写） */
    @EventListener(ApplicationReadyEvent.class)
    public void resetDrafting() {
        mergeMapper.update(null, new LambdaUpdateWrapper<MaterialMerge>().eq(MaterialMerge::getStatus, MaterialMerge.DRAFTING)
                .set(MaterialMerge::getStatus, MaterialMerge.FOUND).set(MaterialMerge::getUpdateTime, LocalDateTime.now()));
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    // ------------------------------------------------------------------ ① 查找

    /**
     * 查找相似素材组。opts：{categories?（默认除情节外全部）, books?（来源书，{@link MaterialService#MANUAL_BOOK} = 手动添加）,
     * crossBookOnly?, threshold?（0.6–0.99，默认 0.82）, maxGroup?（2–12，默认 6）, modelId?}。
     * 旧的 FOUND 建议先清掉；已写好合并稿 / 已合并 / 已忽略的同一组不再重复建议。→ {found, skipped, groups, considered, model, ms}
     */
    @Transactional
    public Map<String, Object> find(Map<String, Object> opts) {
        Map<String, Object> o = opts == null ? Map.of() : opts;
        List<String> cats = strings(o.get("categories")).stream().filter(MaterialService.CATEGORIES::containsKey).toList();
        if (cats.isEmpty()) {
            cats = MaterialService.CATEGORIES.keySet().stream().filter(c -> !"plot".equals(c)).toList();
        }
        List<String> books = strings(o.get("books"));
        double threshold = o.get("threshold") instanceof Number n ? Math.max(0.6, Math.min(0.99, n.doubleValue())) : 0.82;
        int maxGroup = o.get("maxGroup") instanceof Number n ? Math.max(2, Math.min(MAX_GROUP, n.intValue())) : 6;
        boolean crossOnly = Boolean.TRUE.equals(o.get("crossBookOnly"));

        LambdaQueryWrapper<Material> q = new LambdaQueryWrapper<Material>().isNull(Material::getMergedInto)
                .in(Material::getCategory, cats);
        if (!books.isEmpty()) {
            List<String> named = books.stream().filter(b -> !MaterialService.MANUAL_BOOK.equals(b)).toList();
            boolean manual = books.contains(MaterialService.MANUAL_BOOK);
            q.and(w -> {
                if (!named.isEmpty()) {
                    w.in(Material::getSourceBook, named);
                }
                if (manual) {
                    if (!named.isEmpty()) {
                        w.or();
                    }
                    w.isNull(Material::getSourceBook);
                }
            });
        }
        q.orderByAsc(Material::getId).last("LIMIT " + POOL);
        List<Material> pool = materialMapper.selectList(q);
        Map<Long, Material> byId = pool.stream().collect(Collectors.toMap(Material::getId, m -> m));
        List<Map<String, Object>> items = pool.stream().map(m -> Map.<String, Object>of("id", m.getId(),
                "category", m.getCategory(), "title", m.getTitle(), "text", MaterialService.vectorText(m))).toList();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("considered", pool.size());
        if (pool.size() < 2) {
            out.put("found", 0);
            out.put("skipped", 0);
            return out;
        }
        JsonNode res;
        try {
            res = aiClient.mergeGroups(Objects.toString(o.get("modelId"), ""), items, threshold, maxGroup);
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达，请确认 python-service 已启动");
        }
        if (!res.path("ok").asBoolean()) {
            throw new BizException(400, "查找相似素材失败：" + res.path("message").asText("向量模型不可用"));
        }

        Map<String, String> known = new HashMap<>(); // 成员集合 → 状态（FOUND 之外的）
        for (MaterialMerge m : mergeMapper.selectList(new LambdaQueryWrapper<MaterialMerge>()
                .select(MaterialMerge::getId, MaterialMerge::getMemberIds, MaterialMerge::getStatus)
                .ne(MaterialMerge::getStatus, MaterialMerge.FOUND))) {
            known.put(keyOf(m.ids()), m.getStatus());
        }
        mergeMapper.delete(new LambdaQueryWrapper<MaterialMerge>().eq(MaterialMerge::getStatus, MaterialMerge.FOUND));

        int found = 0;
        int skipped = 0;
        LocalDateTime now = LocalDateTime.now();
        for (JsonNode g : res.path("groups")) {
            List<Long> ids = new ArrayList<>();
            g.path("ids").forEach(x -> ids.add(x.asLong()));
            ids.sort(Long::compare);
            Set<String> groupBooks = ids.stream().map(byId::get).filter(Objects::nonNull)
                    .map(m -> Objects.toString(m.getSourceBook(), "")).collect(Collectors.toSet());
            boolean cross = groupBooks.size() > 1;
            if (ids.size() < 2 || known.containsKey(keyOf(ids)) || (crossOnly && !cross)) {
                skipped++;
                continue;
            }
            MaterialMerge m = new MaterialMerge();
            m.setCategory(byId.get(ids.get(0)).getCategory());
            m.setMemberIds(new ArrayList<>(ids));
            m.setScore(g.path("score").asDouble());
            m.setCrossBook(cross);
            m.setStatus(MaterialMerge.FOUND);
            m.setCreateTime(now);
            m.setUpdateTime(now);
            mergeMapper.insert(m);
            found++;
        }
        out.put("found", found);
        out.put("skipped", skipped);
        out.put("groups", res.path("total").asInt(found + skipped));
        out.put("model", res.path("model").asText(""));
        out.put("ms", res.path("ms").asLong());
        log.info("查找相似素材：比较 {} 条，新建议 {} 组，跳过 {} 组（门槛 {}）", pool.size(), found, skipped, threshold);
        return out;
    }

    private static String keyOf(List<Long> ids) {
        return ids == null ? "" : ids.stream().sorted().map(String::valueOf).collect(Collectors.joining(","));
    }

    private static List<String> strings(Object v) {
        if (!(v instanceof List<?> list)) {
            return List.of();
        }
        return list.stream().filter(Objects::nonNull).map(String::valueOf).map(String::trim).filter(s -> !s.isEmpty()).toList();
    }

    // ------------------------------------------------------------------ 列表

    /**
     * 建议列表。status：open（FOUND / DRAFTING / DRAFTED，默认）/ APPLIED / IGNORED；crossBook：true / false / null；
     * 跨书的、相似度高的在前。每条带成员素材（已删除的不在里面）。
     */
    public Page<MaterialMerge> list(String status, String category, Boolean crossBook, int page, int size) {
        LambdaQueryWrapper<MaterialMerge> q = new LambdaQueryWrapper<>();
        if (status == null || status.isBlank() || "open".equalsIgnoreCase(status)) {
            q.in(MaterialMerge::getStatus, OPEN);
        } else {
            q.eq(MaterialMerge::getStatus, status.toUpperCase());
        }
        q.eq(category != null && !category.isBlank(), MaterialMerge::getCategory, category);
        q.eq(crossBook != null, MaterialMerge::getCrossBook, crossBook);
        q.orderByDesc(MaterialMerge::getCrossBook).orderByDesc(MaterialMerge::getScore).orderByAsc(MaterialMerge::getId);
        Page<MaterialMerge> pg = mergeMapper.selectPage(new Page<>(Math.max(page, 1), Math.min(Math.max(size, 1), 50)), q);
        Set<Long> ids = new LinkedHashSet<>();
        pg.getRecords().forEach(m -> ids.addAll(m.ids()));
        Map<Long, Material> byId = ids.isEmpty() ? Map.of()
                : materialMapper.selectBatchIds(ids).stream().collect(Collectors.toMap(Material::getId, m -> m));
        pg.getRecords().forEach(m -> m.setMembers(m.ids().stream().map(byId::get).filter(Objects::nonNull).toList()));
        return pg;
    }

    /** 各状态数量 {open, drafted, APPLIED, IGNORED, cross}（open 含 DRAFTED） */
    public Map<String, Long> counts() {
        Map<String, Long> out = new LinkedHashMap<>();
        out.put("open", mergeMapper.selectCount(new LambdaQueryWrapper<MaterialMerge>().in(MaterialMerge::getStatus, OPEN)));
        out.put("drafted", mergeMapper.selectCount(new LambdaQueryWrapper<MaterialMerge>().eq(MaterialMerge::getStatus, MaterialMerge.DRAFTED)));
        out.put("cross", mergeMapper.selectCount(new LambdaQueryWrapper<MaterialMerge>().in(MaterialMerge::getStatus, OPEN)
                .eq(MaterialMerge::getCrossBook, true)));
        out.put("APPLIED", mergeMapper.selectCount(new LambdaQueryWrapper<MaterialMerge>().eq(MaterialMerge::getStatus, MaterialMerge.APPLIED)));
        out.put("IGNORED", mergeMapper.selectCount(new LambdaQueryWrapper<MaterialMerge>().eq(MaterialMerge::getStatus, MaterialMerge.IGNORED)));
        return out;
    }

    // ------------------------------------------------------------------ ② AI 写合并稿

    /**
     * 对选中的建议写合并稿（FOUND / DRAFTED 都可，DRAFTED 会重写）。model：{source: api, configId?} 或 {source: gguf}。
     * 一次只跑一批；每组写完立刻落库。
     */
    public synchronized Map<String, Object> startDraft(List<Long> ids, Map<String, Object> model) {
        if (running) {
            throw new BizException(400, "已有一批合并稿在写，请等它结束或先暂停");
        }
        if (ids == null || ids.isEmpty()) {
            throw new BizException(400, "请选择要写合并稿的建议");
        }
        if (model != null && "local".equals(model.get("source"))) {
            throw new BizException(400, "合并稿请用大模型或 GGUF（llama.cpp）");
        }
        NovelExtractService.ModelChoice choice = extractService.resolveModel(model);
        List<MaterialMerge> todo = mergeMapper.selectList(new LambdaQueryWrapper<MaterialMerge>().in(MaterialMerge::getId, ids)
                .in(MaterialMerge::getStatus, MaterialMerge.FOUND, MaterialMerge.DRAFTED));
        if (todo.isEmpty()) {
            throw new BizException(400, "所选建议都已处理");
        }
        List<Long> todoIds = todo.stream().map(MaterialMerge::getId).toList();
        mergeMapper.update(null, new LambdaUpdateWrapper<MaterialMerge>().in(MaterialMerge::getId, todoIds)
                .set(MaterialMerge::getStatus, MaterialMerge.DRAFTING).set(MaterialMerge::getUpdateTime, LocalDateTime.now()));
        running = true;
        stopRequested = false;
        total = todoIds.size();
        done = 0;
        failed = 0;
        lastError = null;
        executor.submit(() -> drafts(todoIds, choice.config()));
        return draftStatus();
    }

    /** {running, total, done, failed, currentId, lastError} */
    public Map<String, Object> draftStatus() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("running", running);
        out.put("total", total);
        out.put("done", done);
        out.put("failed", failed);
        out.put("currentId", currentId);
        out.put("lastError", lastError);
        return out;
    }

    /** 暂停：当前这组写完后停下，没写的回到 FOUND */
    public Map<String, Object> stopDraft() {
        stopRequested = true;
        return draftStatus();
    }

    private void drafts(List<Long> ids, com.example.file.entity.AiModelConfig cfg) {
        try {
            for (Long id : ids) {
                if (stopRequested || Thread.currentThread().isInterrupted()) {
                    break;
                }
                currentId = id;
                MaterialMerge s = mergeMapper.selectById(id);
                if (s == null || !MaterialMerge.DRAFTING.equals(s.getStatus())) {
                    continue;
                }
                List<Material> members = alive(s);
                if (members.size() < 2) {
                    setStatus(id, MaterialMerge.FOUND, null, "成员已删除或已并入其他条目，不足两条");
                    failed++;
                    continue;
                }
                try {
                    JsonNode res = aiClient.mergeDraft(s.getCategory(), members.stream().map(this::memberPayload).toList(), cfg);
                    if (!res.path("ok").asBoolean()) {
                        setStatus(id, MaterialMerge.FOUND, null, "写合并稿失败：" + res.path("message").asText());
                        failed++;
                        lastError = res.path("message").asText();
                        if (res.path("fatal").asBoolean()) {
                            break; // Key 无效 / 余额不足等：后面的也不会成功
                        }
                        continue;
                    }
                    @SuppressWarnings("unchecked")
                    Map<String, Object> draft = objectMapper.convertValue(res, Map.class);
                    draft.remove("ok");
                    setStatus(id, MaterialMerge.DRAFTED, draft, null);
                    done++;
                } catch (ResourceAccessException e) {
                    lastError = "AI 服务不可达";
                    break;
                } catch (Exception e) {
                    log.warn("写合并稿失败，mergeId={}：{}", id, e.getMessage());
                    setStatus(id, MaterialMerge.FOUND, null, "写合并稿失败：" + e.getMessage());
                    failed++;
                }
            }
        } finally {
            // 没轮到的回到 FOUND
            mergeMapper.update(null, new LambdaUpdateWrapper<MaterialMerge>().in(MaterialMerge::getId, ids)
                    .eq(MaterialMerge::getStatus, MaterialMerge.DRAFTING)
                    .set(MaterialMerge::getStatus, MaterialMerge.FOUND).set(MaterialMerge::getUpdateTime, LocalDateTime.now()));
            currentId = null;
            running = false;
        }
    }

    private Map<String, Object> memberPayload(Material m) {
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", m.getId());
        p.put("book", Objects.toString(m.getSourceBook(), ""));
        p.put("title", m.getTitle());
        p.put("subtype", Objects.toString(m.getSubtype(), ""));
        p.put("summary", Objects.toString(m.getSummary(), ""));
        p.put("attributes", m.getAttributes() == null ? Map.of() : m.getAttributes());
        p.put("detail", Objects.toString(m.getDetail(), ""));
        return p;
    }

    private List<Material> alive(MaterialMerge s) {
        if (s.ids().isEmpty()) {
            return List.of();
        }
        return materialMapper.selectBatchIds(s.ids()).stream().filter(m -> m.getMergedInto() == null)
                .sorted((a, b) -> Long.compare(a.getId(), b.getId())).toList();
    }

    private void setStatus(Long id, String status, Map<String, Object> draft, String message) {
        LambdaUpdateWrapper<MaterialMerge> u = new LambdaUpdateWrapper<MaterialMerge>().eq(MaterialMerge::getId, id)
                .set(MaterialMerge::getStatus, status).set(MaterialMerge::getMessage, message)
                .set(MaterialMerge::getUpdateTime, LocalDateTime.now());
        if (draft != null) {
            MaterialMerge patch = new MaterialMerge();
            patch.setId(id);
            patch.setDraft(draft); // JSON 列走实体更新（类型处理器）
            mergeMapper.updateById(patch);
        }
        mergeMapper.update(null, u);
    }

    // ------------------------------------------------------------------ ③ 合并 / 忽略 / 拆分

    /**
     * 确认合并。edits：{memberIds（≥2，默认 = 合并稿的 same，没有合并稿 = 全部）, title, subtype, summary, detail, attributes, tags,
     * variants: {成员 id: {label: 版本名, note: 这一版独有的设定}}}；没给的字段用合并稿（名称 / 概括再没有用第一条成员）。
     * 主条目只放共性，每个成员是一个「可选版本」（source.variants），版本名自动加进标签。→ 新建的主条目
     */
    @Transactional
    public Material apply(Long id, Map<String, Object> edits) {
        MaterialMerge s = mergeMapper.selectById(id);
        if (s == null) {
            throw new BizException(404, "合并建议不存在：" + id);
        }
        if (!MaterialMerge.FOUND.equals(s.getStatus()) && !MaterialMerge.DRAFTED.equals(s.getStatus())) {
            throw new BizException(400, "这条建议已处理或正在写合并稿");
        }
        Map<String, Object> e = edits == null ? Map.of() : edits;
        Map<String, Object> d = s.getDraft() == null ? Map.of() : s.getDraft();
        List<Long> chosen = longs(e.get("memberIds"));
        if (chosen.isEmpty()) {
            chosen = longs(d.get("same"));
        }
        if (chosen.isEmpty()) {
            chosen = s.ids();
        }
        Set<Long> picked = new LinkedHashSet<>(chosen);
        List<Material> members = alive(s).stream().filter(m -> picked.contains(m.getId())).toList();
        if (members.size() < 2) {
            throw new BizException(400, "至少要选两条还在素材库里的素材才能合并");
        }
        Material first = members.get(0);
        // 版本：合并稿的在前，页面上改过的覆盖；旧格式（只有一句写法的字符串）当作 note
        Map<String, Map<String, Object>> versionOf = new HashMap<>();
        for (Map<String, Object> src : List.of(asMap(d.get("variants")), asMap(e.get("variants")))) {
            src.forEach((k, v) -> versionOf.put(String.valueOf(k), v instanceof Map<?, ?> ? asMap(v) : Map.of("note", v)));
        }
        List<Map<String, Object>> variants = new ArrayList<>();
        List<String> labels = new ArrayList<>();
        for (Material m : members) {
            Map<String, Object> ver = versionOf.getOrDefault(String.valueOf(m.getId()), Map.of());
            String label = trim(ver.get("label"), 20);
            Map<String, Object> v = new LinkedHashMap<>();
            v.put("id", m.getId());
            v.put("book", Objects.toString(m.getSourceBook(), ""));
            v.put("title", m.getTitle());
            v.put("label", label);
            v.put("note", trim(ver.get("note"), 300));
            variants.add(v);
            if (!label.isEmpty() && !labels.contains(label)) {
                labels.add(label);
            }
        }
        Set<String> books = members.stream().map(m -> Objects.toString(m.getSourceBook(), "")).collect(Collectors.toSet());

        Material master = new Material();
        master.setCategory(s.getCategory());
        master.setTitle(pick(e, d, "title", first.getTitle()));
        master.setSubtype(pick(e, d, "subtype", "")); // 不拿某条成员的细分类型：那是它那个版本的
        master.setSummary(pick(e, d, "summary", first.getSummary()));
        // 详细 / 属性只放共性：不拿某一条成员的来充数（那是某个版本的设定，成员本身原样保留）
        master.setDetail(pick(e, d, "detail", ""));
        master.setAttributes(asMap(e.containsKey("attributes") ? e.get("attributes") : d.get("attributes")));
        List<String> tags = new ArrayList<>(strings(e.containsKey("tags") ? e.get("tags") : d.get("tags")));
        if (tags.isEmpty()) {
            tags.addAll(members.stream().flatMap(m -> m.getTags() == null ? java.util.stream.Stream.empty() : m.getTags().stream())
                    .distinct().limit(8).toList());
        }
        labels.stream().filter(l -> !tags.contains(l)).forEach(tags::add); // 关键词检索能搜到「狂信药剂」
        master.setTags(tags);
        // 同一本书里的近似重复：主条目仍属于这本书；跨书：不属于任何一本（按书删除 / 屏蔽不影响它）
        String book = books.size() == 1 ? first.getSourceBook() : null;
        master.setSourceBook(book == null ? MaterialService.MANUAL_BOOK : book);
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("type", "merge");
        source.put("mergeId", s.getId());
        source.put("members", members.stream().map(Material::getId).toList());
        source.put("books", books.stream().filter(b -> !b.isEmpty()).sorted().toList());
        source.put("variants", variants);
        master.setSource(source);
        Material saved = materialService.save(master);

        materialMapper.update(null, new LambdaUpdateWrapper<Material>().in(Material::getId, members.stream().map(Material::getId).toList())
                .set(Material::getMergedInto, saved.getId()));
        mergeMapper.update(null, new LambdaUpdateWrapper<MaterialMerge>().eq(MaterialMerge::getId, id)
                .set(MaterialMerge::getStatus, MaterialMerge.APPLIED).set(MaterialMerge::getMaterialId, saved.getId())
                .set(MaterialMerge::getUpdateTime, LocalDateTime.now()));
        log.info("合并素材 {} → 主条目 {}（{}）", members.stream().map(Material::getId).toList(), saved.getId(), saved.getTitle());
        return materialService.detail(saved.getId());
    }

    /** 忽略：以后查找时同一组不再建议 */
    public int ignore(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return 0;
        }
        return mergeMapper.update(null, new LambdaUpdateWrapper<MaterialMerge>().in(MaterialMerge::getId, ids)
                .in(MaterialMerge::getStatus, MaterialMerge.FOUND, MaterialMerge.DRAFTED)
                .set(MaterialMerge::getStatus, MaterialMerge.IGNORED).set(MaterialMerge::getUpdateTime, LocalDateTime.now()));
    }

    /** 恢复忽略的建议（回到待处理） */
    public int restore(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return 0;
        }
        int n = 0;
        for (MaterialMerge m : mergeMapper.selectBatchIds(ids)) {
            if (MaterialMerge.IGNORED.equals(m.getStatus())) {
                setStatus(m.getId(), m.getDraft() == null ? MaterialMerge.FOUND : MaterialMerge.DRAFTED, null, null);
                n++;
            }
        }
        return n;
    }

    /** 拆分：删掉主条目，成员回到素材库；对应的建议回到待处理（合并稿保留） */
    @Transactional
    public Map<String, Object> unmerge(Long materialId) {
        Material master = materialService.get(materialId);
        if (!MaterialService.isMergeMaster(master)) {
            throw new BizException(400, "这条素材不是合并而来的");
        }
        long members = materialMapper.selectCount(new LambdaQueryWrapper<Material>().eq(Material::getMergedInto, materialId));
        materialService.delete(materialId); // 删除主条目时成员的 merged_into 一并清空
        for (MaterialMerge m : mergeMapper.selectList(new LambdaQueryWrapper<MaterialMerge>().eq(MaterialMerge::getMaterialId, materialId))) {
            mergeMapper.update(null, new LambdaUpdateWrapper<MaterialMerge>().eq(MaterialMerge::getId, m.getId())
                    .set(MaterialMerge::getStatus, m.getDraft() == null ? MaterialMerge.FOUND : MaterialMerge.DRAFTED)
                    .set(MaterialMerge::getMaterialId, null).set(MaterialMerge::getUpdateTime, LocalDateTime.now()));
        }
        return Map.of("restored", members);
    }

    private static String trim(Object v, int max) {
        String s = v == null ? "" : String.valueOf(v).trim();
        return s.length() > max ? s.substring(0, max) : s;
    }

    private static String pick(Map<String, Object> edits, Map<String, Object> draft, String key, String fallback) {
        for (Map<String, Object> src : List.of(edits, draft)) {
            Object v = src.get(key);
            if (v != null && !String.valueOf(v).isBlank()) {
                return String.valueOf(v).trim();
            }
        }
        return fallback;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object v) {
        return v instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
    }

    private static List<Long> longs(Object v) {
        if (!(v instanceof List<?> list)) {
            return List.of();
        }
        List<Long> out = new ArrayList<>();
        for (Object o : list) {
            if (o instanceof Number n) {
                out.add(n.longValue());
            } else if (o != null && String.valueOf(o).matches("\\d+")) {
                out.add(Long.parseLong(String.valueOf(o)));
            }
        }
        return out;
    }
}
