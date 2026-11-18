package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.InspirationItem;
import com.example.file.entity.InspirationRun;
import com.example.file.entity.InspirationWall;
import com.example.file.entity.Material;
import com.example.file.mapper.InspirationItemMapper;
import com.example.file.mapper.InspirationRunMapper;
import com.example.file.mapper.InspirationWallMapper;
import com.example.file.mapper.MaterialMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * 灵感墙：多面墙（可关联工作区）、墙上的思路 / 素材、构思记录；构思三步 = 拆需求（模型）→ 检索素材（本地，不花 token）
 * → 生成思路（模型），另有细化、追问修改、逛素材。模型调用在 Python（/api/gen/inspire/**），这里负责素材检索、
 * 组装素材条目（含多版本，复用 {@link NovelGenService#materialItems}）和存储。
 */
@Service
public class InspirationService {

    private static final Logger log = LoggerFactory.getLogger(InspirationService.class);

    /** 一次构思最多用多少条素材 */
    static final int MAX_MATERIALS = 24;
    /** 同一条检索需求里，每本书最多几条（保证来源多样） */
    static final int PER_BOOK = 2;
    /** 没有重排模型时，每条需求按排名取前几条 */
    static final int UNRANKED_TAKE = 3;
    /** relaxEmpty：一条需求没有素材过相关度阈值时，退一步给几条 */
    static final int WEAK_TAKE = 2;
    /** 随机探索：每个分类抽几条 */
    static final int EXPLORE_PER_CATEGORY = 2;
    /** 逛素材 / 随机探索优先「内容充实」的素材：概括 + 详细的字数至少这么多 */
    static final int RICH_CHARS = 60;
    static final List<String> TARGETS = List.of("adventure", "plot", "location", "monster", "faction", "character",
            "world", "item", "free");

    private final InspirationWallMapper wallMapper;
    private final InspirationItemMapper itemMapper;
    private final InspirationRunMapper runMapper;
    private final MaterialMapper materialMapper;
    private final MaterialService materialService;
    private final NovelGenService genService;
    private final NovelExtractService extractService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;

    public InspirationService(InspirationWallMapper wallMapper, InspirationItemMapper itemMapper, InspirationRunMapper runMapper,
                              MaterialMapper materialMapper, MaterialService materialService, NovelGenService genService,
                              NovelExtractService extractService, AiServiceClient aiClient, ObjectMapper objectMapper) {
        this.wallMapper = wallMapper;
        this.itemMapper = itemMapper;
        this.runMapper = runMapper;
        this.materialMapper = materialMapper;
        this.materialService = materialService;
        this.genService = genService;
        this.extractService = extractService;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    // ------------------------------------------------------------------ 墙

    public List<InspirationWall> walls() {
        List<InspirationWall> walls = wallMapper.selectList(new LambdaQueryWrapper<InspirationWall>()
                .orderByDesc(InspirationWall::getUpdateTime));
        Map<Long, long[]> counts = new HashMap<>();
        for (InspirationItem it : itemMapper.selectList(new LambdaQueryWrapper<InspirationItem>()
                .select(InspirationItem::getWallId, InspirationItem::getType))) {
            long[] c = counts.computeIfAbsent(it.getWallId(), k -> new long[2]);
            c[InspirationItem.IDEA.equals(it.getType()) ? 0 : 1]++;
        }
        walls.forEach(w -> {
            long[] c = counts.getOrDefault(w.getId(), new long[2]);
            w.setIdeaCount(c[0]);
            w.setMaterialCount(c[1]);
        });
        return walls;
    }

    public InspirationWall wall(Long id) {
        InspirationWall w = wallMapper.selectById(id);
        if (w == null) {
            throw new BizException(404, "灵感墙不存在：" + id);
        }
        return w;
    }

    /** 新建（无 id）或修改 {name, note, novelId（空串 = 取消关联）, excludeBooks} */
    public InspirationWall saveWall(Map<String, Object> req) {
        String name = trim(req.get("name"), 60);
        Long id = toLong(req.get("id"));
        InspirationWall w = id == null ? new InspirationWall() : wall(id);
        if (id == null && name.isEmpty()) {
            throw new BizException(400, "请给灵感墙起个名字");
        }
        if (!name.isEmpty()) {
            w.setName(name);
        }
        if (req.containsKey("note")) {
            w.setNote(trim(req.get("note"), 500));
        }
        if (req.containsKey("novelId")) {
            String novel = trim(req.get("novelId"), 64);
            w.setNovelId(novel.isEmpty() ? null : novel);
        }
        if (req.get("excludeBooks") instanceof List<?> list) {
            w.setExcludeBooks(list.stream().filter(Objects::nonNull).map(String::valueOf).map(String::trim)
                    .filter(s -> !s.isEmpty()).distinct().limit(100).toList());
        }
        LocalDateTime now = LocalDateTime.now();
        w.setUpdateTime(now);
        if (id == null) {
            w.setCreateTime(now);
            wallMapper.insert(w);
        } else {
            wallMapper.updateById(w);
            if (req.containsKey("novelId") && w.getNovelId() == null) {
                // updateById 跳过 null 字段：取消关联要显式更新
                wallMapper.update(null, new LambdaUpdateWrapper<InspirationWall>().eq(InspirationWall::getId, id)
                        .set(InspirationWall::getNovelId, null));
            }
        }
        return wall(w.getId());
    }

    /** 删除墙及其条目、构思记录（素材库里的素材不受影响） */
    @Transactional
    public void deleteWall(Long id) {
        wall(id);
        itemMapper.delete(new LambdaQueryWrapper<InspirationItem>().eq(InspirationItem::getWallId, id));
        runMapper.delete(new LambdaQueryWrapper<InspirationRun>().eq(InspirationRun::getWallId, id));
        wallMapper.deleteById(id);
    }

    // ------------------------------------------------------------------ 墙上的条目

    /** 墙上的条目：先按 sort 再按时间倒序；钉的素材附上素材本身（已删除的素材 material 为空） */
    public List<InspirationItem> items(Long wallId) {
        wall(wallId);
        List<InspirationItem> items = itemMapper.selectList(new LambdaQueryWrapper<InspirationItem>()
                .eq(InspirationItem::getWallId, wallId)
                .orderByDesc(InspirationItem::getSort).orderByDesc(InspirationItem::getCreateTime));
        List<Long> ids = items.stream().map(InspirationItem::getMaterialId).filter(Objects::nonNull).toList();
        Map<Long, Material> byId = ids.isEmpty() ? Map.of()
                : materialService.listByIds(ids).stream().collect(Collectors.toMap(Material::getId, m -> m));
        items.forEach(it -> it.setMaterial(it.getMaterialId() == null ? null : byId.get(it.getMaterialId())));
        return items;
    }

    /** 收藏思路 / 修改条目 {id?, wallId, type, title, content, sources, note, sort?} */
    public InspirationItem saveItem(Map<String, Object> req) {
        Long id = toLong(req.get("id"));
        InspirationItem it = id == null ? new InspirationItem() : item(id);
        if (id == null) {
            Long wallId = toLong(req.get("wallId"));
            wall(Objects.requireNonNull(wallId, "wallId"));
            it.setWallId(wallId);
            it.setType(InspirationItem.MATERIAL.equals(req.get("type")) ? InspirationItem.MATERIAL : InspirationItem.IDEA);
            it.setSort(0);
        }
        if (req.containsKey("title")) {
            it.setTitle(trim(req.get("title"), 100));
        }
        if (it.getTitle() == null || it.getTitle().isEmpty()) {
            throw new BizException(400, "缺少标题");
        }
        if (req.get("content") instanceof Map<?, ?> c) {
            it.setContent(objectMapper.convertValue(c, Map.class));
        }
        if (req.get("sources") instanceof List<?> s) {
            it.setSources(objectMapper.convertValue(s, List.class));
        }
        if (req.containsKey("note")) {
            it.setNote(trim(req.get("note"), 1000));
        }
        if (req.get("sort") instanceof Number n) {
            it.setSort(n.intValue());
        }
        LocalDateTime now = LocalDateTime.now();
        it.setUpdateTime(now);
        if (id == null) {
            it.setCreateTime(now);
            itemMapper.insert(it);
        } else {
            itemMapper.updateById(it);
        }
        touch(it.getWallId());
        return item(it.getId());
    }

    /** 钉素材到墙上（已钉过的直接返回那一条） */
    public InspirationItem pin(Long wallId, Long materialId) {
        wall(wallId);
        Material m = materialService.get(materialId);
        InspirationItem exist = itemMapper.selectOne(new LambdaQueryWrapper<InspirationItem>()
                .eq(InspirationItem::getWallId, wallId).eq(InspirationItem::getMaterialId, materialId).last("LIMIT 1"));
        if (exist != null) {
            return exist;
        }
        InspirationItem it = new InspirationItem();
        it.setWallId(wallId);
        it.setType(InspirationItem.MATERIAL);
        it.setMaterialId(materialId);
        it.setTitle(m.getTitle());
        it.setSort(0);
        it.setCreateTime(LocalDateTime.now());
        it.setUpdateTime(it.getCreateTime());
        itemMapper.insert(it);
        touch(wallId);
        return it;
    }

    public void deleteItem(Long id) {
        InspirationItem it = item(id);
        itemMapper.deleteById(id);
        touch(it.getWallId());
    }

    private InspirationItem item(Long id) {
        InspirationItem it = itemMapper.selectById(id);
        if (it == null) {
            throw new BizException(404, "灵感墙条目不存在：" + id);
        }
        return it;
    }

    private void touch(Long wallId) {
        wallMapper.update(null, new LambdaUpdateWrapper<InspirationWall>().eq(InspirationWall::getId, wallId)
                .set(InspirationWall::getUpdateTime, LocalDateTime.now()));
    }

    // ------------------------------------------------------------------ 构思：① 拆需求

    /** {request, target, conditions, model} → {summary, needs[{category, query, count, why}], explore, usage, model} */
    public Map<String, Object> plan(Long wallId, Map<String, Object> req) {
        InspirationWall w = wall(wallId);
        Map<String, Object> body = baseBody(w, req);
        return python("plan", body, req.get("model"));
    }

    // ------------------------------------------------------------------ ② 检索素材（本地）

    /**
     * {needs[{category, query, count, why, role?, ignoreStage?}], explore?, stage?{phase, tierMax}} →
     * {groups[{need, items[{material, score, variant, matchedLabel, from, tier, fit}], hidden, relaxed}], total, reranked, stage}。
     * <ul>
     *   <li>墙上钉的素材总在最前（from = wall），不受阶段限制；</li>
     *   <li>每条需求本地检索（向量 + BM25 + 重排）。有阶段时<b>先过滤再检索</b>：对手 / 场景 / 道具（role）
     *       挡掉超出量级上限两级以上的素材（hidden = 挡掉几条），超一级的排在正常项后面（relaxed = 用到了超一级的）；
     *       背景传说（lore）不限量级，但「远景」全次最多 {@link StageFit#FAR_QUOTA} 条。ignoreStage = 作者点了「也看看」；</li>
     *   <li>重排过取相关度 ≥ 30 的、没重排取前几条，每本书最多 2 条，跨组去重；</li>
     *   <li>explore = 每个分类再随机抽几条（from = explore），按量级分层抽，只抽上限以内的。</li>
     * </ul>
     */
    public Map<String, Object> retrieve(Long wallId, Map<String, Object> req) {
        InspirationWall w = wall(wallId);
        List<String> exclude = w.getExcludeBooks() == null ? List.of() : w.getExcludeBooks();
        List<Material> pinned = new ArrayList<>();
        for (InspirationItem it : items(wallId)) {
            if (InspirationItem.MATERIAL.equals(it.getType()) && it.getMaterial() != null) {
                pinned.add(it.getMaterial());
            }
        }
        return retrieveNeeds(exclude, pinned, req);
    }

    /**
     * 检索的核心（灵感墙和自动规划共用，见 {@link NovelPlanService}）：pinned = 总在最前的素材（墙上钉的；自动规划为空），
     * exclude = 屏蔽的来源书；req 同 {@link #retrieve}。
     */
    public Map<String, Object> retrieveNeeds(List<String> exclude, List<Material> pinned, Map<String, Object> req) {
        StageFit.Stage stage = StageFit.of(req.get("stage"));
        Set<Long> taken = new LinkedHashSet<>();
        List<Map<String, Object>> groups = new ArrayList<>();
        boolean anyReranked = false;
        int far = 0;

        List<Map<String, Object>> wallItems = new ArrayList<>();
        for (Material m : pinned) {
            if (m.getMergedInto() == null && taken.add(m.getId())) {
                wallItems.add(candidate(m, null, null, null, "wall", stage));
            }
        }
        if (!wallItems.isEmpty()) {
            groups.add(group(Map.of("category", "", "query", "", "why", "灵感墙上钉的素材"), wallItems, 0, false));
        }

        List<Map<String, Object>> needs = req.get("needs") instanceof List<?> l ? objectMapper.convertValue(l, List.class) : List.of();
        Set<String> needCats = new LinkedHashSet<>();
        for (Map<String, Object> raw : needs) {
            String cat = Objects.toString(raw.get("category"), "");
            String query = trim(raw.get("query"), 500);
            if (!MaterialService.CATEGORIES.containsKey(cat) || query.isEmpty()) {
                continue;
            }
            needCats.add(cat);
            Map<String, Object> need = new LinkedHashMap<>(raw);
            String role = StageFit.role(raw.get("role"), cat);
            need.put("role", role);
            boolean free = !stage.limited() || Boolean.TRUE.equals(raw.get("ignoreStage"));
            boolean lore = "lore".equals(role);
            int count = raw.get("count") instanceof Number n ? Math.max(1, Math.min(6, n.intValue())) : 3;
            java.util.function.Predicate<Material> keep = free || lore ? null
                    : m -> !StageFit.FAR.equals(StageFit.fit(m, stage));
            Map<String, Object> found = materialService.vectorSearch(query, cat, null, exclude, null, count * 6,
                    "hybrid", true, keep);
            boolean reranked = Boolean.TRUE.equals(found.get("reranked"));
            anyReranked |= reranked;
            int hidden = found.get("filtered") instanceof Number f ? f.intValue() : 0;
            // 先按相关度收候选，再把超一级 / 没信息的排到后面（稳定排序，同档内保持相关度顺序）
            List<Map<String, Object>> cands = new ArrayList<>();
            List<Map<String, Object>> weak = new ArrayList<>();   // 没过相关度阈值的前几条（relaxEmpty 时用）
            if (found.get("results") instanceof List<?> rs) {
                for (Object o : rs) {
                    if (!(o instanceof Map<?, ?> r) || !(r.get("material") instanceof Material m) || taken.contains(m.getId())) {
                        continue;
                    }
                    int score = r.get("score") instanceof Integer sc ? sc : 0;
                    if (reranked ? score < MaterialService.RERANK_MIN_SCORE : cands.size() >= UNRANKED_TAKE) {
                        if (weak.size() < WEAK_TAKE && !(!free && StageFit.FAR.equals(StageFit.fit(m, stage)))) {
                            Object v = r.get("matchedVariant");
                            weak.add(candidate(m, score, v == null ? null : String.valueOf(v),
                                    Objects.toString(r.get("matchedLabel"), null), "weak", free ? null : stage));
                        }
                        continue;
                    }
                    Object variant = r.get("matchedVariant");
                    cands.add(candidate(m, score, variant == null ? null : String.valueOf(variant),
                            Objects.toString(r.get("matchedLabel"), null), "search", free ? null : stage));
                }
            }
            if (!free) {
                cands.sort(java.util.Comparator.comparingInt(c -> StageFit.rank(String.valueOf(c.get("fit")))));
            }
            Map<String, Integer> perBook = new HashMap<>();
            List<Map<String, Object>> items = new ArrayList<>();
            boolean relaxed = false;
            for (Map<String, Object> c : cands) {
                if (items.size() >= count) {
                    break;
                }
                Material m = (Material) c.get("material");
                String book = Objects.toString(m.getSourceBook(), "");
                if (!book.isEmpty() && perBook.getOrDefault(book, 0) >= PER_BOOK) {
                    continue;
                }
                if (!free && StageFit.FAR.equals(c.get("fit"))) {
                    if (far >= StageFit.FAR_QUOTA) {
                        hidden++;
                        continue;
                    }
                    far++;
                }
                relaxed |= StageFit.STRETCH.equals(c.get("fit"));
                perBook.merge(book, 1, Integer::sum);
                taken.add(m.getId());
                items.add(c);
            }
            // 自动规划：一条都没过阈值时退一步给最相关的几条（from = weak，界面标「相关度低」，作者自己判断）
            if (items.isEmpty() && Boolean.TRUE.equals(req.get("relaxEmpty"))) {
                for (Map<String, Object> c : weak) {
                    taken.add(((Material) c.get("material")).getId());
                    items.add(c);
                }
            }
            groups.add(group(need, items, hidden, relaxed));
        }

        if (Boolean.TRUE.equals(req.get("explore"))) {
            List<String> cats = needCats.isEmpty()
                    ? MaterialService.CATEGORIES.keySet().stream().filter(c -> !"plot".equals(c)).toList()
                    : new ArrayList<>(needCats);
            List<Map<String, Object>> items = new ArrayList<>();
            for (String cat : cats) {
                for (Material m : sample(cat, exclude, EXPLORE_PER_CATEGORY, taken, stage)) {
                    taken.add(m.getId());
                    items.add(candidate(m, null, null, null, "explore", stage));
                }
            }
            if (!items.isEmpty()) {
                groups.add(group(Map.of("category", "", "query", "", "why", "随机探索：意想不到的组合"), items, 0, false));
            }
        }
        // 总数上限：靠后的组从末尾裁掉
        int total = 0;
        List<Map<String, Object>> capped = new ArrayList<>();
        for (Map<String, Object> g : groups) {
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> items = (List<Map<String, Object>>) g.get("items");
            List<Map<String, Object>> keep = items.subList(0, Math.min(items.size(), Math.max(0, MAX_MATERIALS - total)));
            total += keep.size();
            Map<String, Object> cg = new LinkedHashMap<>(g);
            cg.put("items", new ArrayList<>(keep));
            capped.add(cg);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("groups", capped);
        out.put("total", total);
        out.put("reranked", anyReranked);
        Map<String, Object> st = new LinkedHashMap<>();
        st.put("phase", stage.phase());
        st.put("tierMax", stage.tierMax());
        out.put("stage", st);
        return out;
    }

    private static Map<String, Object> group(Map<String, Object> need, List<Map<String, Object>> items, int hidden, boolean relaxed) {
        Map<String, Object> g = new LinkedHashMap<>();
        g.put("need", need);
        g.put("items", items);
        g.put("hidden", hidden);
        g.put("relaxed", relaxed);
        return g;
    }

    private Map<String, Object> candidate(Material m, Integer score, String variant, String matchedLabel, String from,
                                          StageFit.Stage stage) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("material", m);
        c.put("score", score);
        // 多版本素材：检索命中某个版本 = 只用这一版，否则让 AI 选
        c.put("variant", MaterialService.isMergeMaster(m) ? (variant != null ? variant : "auto") : null);
        c.put("matchedLabel", matchedLabel);
        c.put("from", from);
        c.put("tier", MaterialService.tierOf(m));
        c.put("fit", StageFit.fit(m, stage));
        return c;
    }

    // ------------------------------------------------------------------ 逛素材 / 随机探索

    /**
     * 随机抽素材：未合并、不在屏蔽书里的；先多取一批，再<b>按量级分层轮流取</b>（1 级一条、2 级一条……没标的算一层），
     * 每本书最多 {@link #PER_BOOK} 条。以前是「内容充实的优先」——神明 / 大势力在原书里事实最多、卡片最充实，
     * 一抽全是它们；现在内容充实只在同一层里排前面。有阶段时只抽上限以内的（和没信息的）。
     */
    List<Material> sample(String category, List<String> exclude, int count, Set<Long> skip, StageFit.Stage stage) {
        LambdaQueryWrapper<Material> q = new LambdaQueryWrapper<Material>().isNull(Material::getMergedInto);
        if (category != null && !category.isBlank()) {
            q.eq(Material::getCategory, category);
        }
        if (exclude != null && !exclude.isEmpty()) {
            q.and(w -> w.isNull(Material::getSourceBook).or().notIn(Material::getSourceBook, exclude)
                    .or().eq(Material::getPinned, true));
        }
        q.last("ORDER BY RANDOM() LIMIT " + Math.max(count * 12, 60));
        Map<Integer, List<Material>> layers = new java.util.TreeMap<>();
        for (Material m : materialMapper.selectList(q)) {
            String fit = StageFit.fit(m, stage);
            if (skip.contains(m.getId()) || StageFit.FAR.equals(fit) || StageFit.STRETCH.equals(fit)) {
                continue;
            }
            Integer tier = MaterialService.tierOf(m);
            layers.computeIfAbsent(tier == null ? 0 : tier, k -> new ArrayList<>()).add(m);
        }
        // SQL 已随机打乱：稳定排序把内容充实的放在本层前面
        layers.values().forEach(list -> list.sort(java.util.Comparator.comparingInt(m -> detailLen(m) >= RICH_CHARS ? 0 : 1)));
        List<java.util.Iterator<Material>> its = new ArrayList<>(layers.values().stream().map(List::iterator).toList());
        // 层的起点也随机，免得每次都从 1 级开始
        if (!its.isEmpty()) {
            java.util.Collections.rotate(its, java.util.concurrent.ThreadLocalRandom.current().nextInt(its.size()));
        }
        Map<String, Integer> perBook = new HashMap<>();
        List<Material> out = new ArrayList<>();
        boolean progress = true;
        while (out.size() < count && progress) {
            progress = false;
            for (java.util.Iterator<Material> it : its) {
                while (out.size() < count && it.hasNext()) {
                    Material m = it.next();
                    String book = Objects.toString(m.getSourceBook(), "");
                    if (!book.isEmpty() && perBook.getOrDefault(book, 0) >= PER_BOOK) {
                        continue;
                    }
                    perBook.merge(book, 1, Integer::sum);
                    out.add(m);
                    progress = true;
                    break; // 这一层取一条，轮到下一层
                }
            }
        }
        return out;
    }

    private static int detailLen(Material m) {
        return (m.getDetail() == null ? 0 : m.getDetail().length()) + (m.getSummary() == null ? 0 : m.getSummary().length());
    }

    /** 逛素材：某个分类（空 = 全部）跨书随机一批 */
    public List<Material> browse(Long wallId, String category, int count) {
        List<String> exclude = wallId == null ? List.of() : Objects.requireNonNullElse(wall(wallId).getExcludeBooks(), List.of());
        if (category != null && !category.isBlank() && !MaterialService.CATEGORIES.containsKey(category)) {
            throw new BizException(400, "素材分类无效：" + category);
        }
        return sample(category, exclude, Math.max(1, Math.min(40, count)), Set.of(), null);
    }

    // ------------------------------------------------------------------ ③ 生成思路 / 细化 / 修改

    /**
     * {request, target, conditions, plan{summary, needs, explore}, materialIds, materialVariants, count, model}
     * → 构思记录（含思路；思路里的 sources 已是素材 id，另附 sourceRefs 方便展示）
     */
    public InspirationRun ideas(Long wallId, Map<String, Object> req) {
        InspirationWall w = wall(wallId);
        List<Long> ids = longs(req.get("materialIds")).stream().distinct().limit(MAX_MATERIALS).toList();
        if (ids.isEmpty()) {
            throw new BizException(400, "没有选中任何素材");
        }
        Map<Long, String> variants = NovelGenService.parseVariants(req.get("materialVariants"));
        List<Map<String, Object>> items = withStage(genService.materialItems(ids, variants), req.get("stage"));
        Map<String, Object> body = baseBody(w, req);
        body.put("materials", items);
        body.put("count", req.get("count") instanceof Number n ? Math.max(1, Math.min(5, n.intValue())) : 3);
        Map<String, Object> data = python("ideas", body, req.get("model"));

        Map<Long, Map<String, Object>> refs = refsOf(ids, variants);
        List<Map<String, Object>> ideas = new ArrayList<>();
        if (data.get("ideas") instanceof List<?> list) {
            for (Object o : list) {
                @SuppressWarnings("unchecked")
                Map<String, Object> idea = new LinkedHashMap<>((Map<String, Object>) o);
                idea.put("target", target(req));
                idea.put("sourceRefs", sourceRefs(idea.get("sources"), refs));
                ideas.add(idea);
            }
        }
        InspirationRun run = new InspirationRun();
        run.setWallId(wallId);
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("request", trim(req.get("request"), 2000));
        request.put("target", target(req));
        request.put("conditions", trim(req.get("conditions"), 2000));
        request.put("count", body.get("count"));
        request.put("model", req.get("model"));
        run.setRequest(request);
        run.setPlan(req.get("plan") instanceof Map<?, ?> p ? objectMapper.convertValue(p, Map.class) : null);
        run.setMaterials(new ArrayList<>(refs.values()));
        run.setIdeas(ideas);
        @SuppressWarnings("unchecked")
        Map<String, Object> usage = data.get("usage") instanceof Map<?, ?> u ? (Map<String, Object>) u : Map.of();
        Map<String, Object> usageOut = new LinkedHashMap<>(usage);
        usageOut.put("model", data.get("model"));
        run.setUsage(usageOut);
        run.setCreateTime(LocalDateTime.now());
        runMapper.insert(run);
        touch(wallId);
        return run;
    }

    /** {wallId, idea, instruction?, materialIds, materialVariants, target, model} → {detail{sections}, usage, model} */
    public Map<String, Object> refine(Map<String, Object> req) {
        return ideaCall("refine", req);
    }

    /** {wallId, idea, instruction, history[], materialIds, materialVariants, target, model} → {idea, usage, model} */
    public Map<String, Object> revise(Map<String, Object> req) {
        Map<String, Object> out = ideaCall("revise", req);
        if (out.get("idea") instanceof Map<?, ?> idea) {
            List<Long> ids = longs(req.get("materialIds"));
            @SuppressWarnings("unchecked")
            Map<String, Object> copy = new LinkedHashMap<>((Map<String, Object>) idea);
            copy.put("target", target(req));
            copy.put("sourceRefs", sourceRefs(copy.get("sources"), refsOf(ids, NovelGenService.parseVariants(req.get("materialVariants")))));
            out.put("idea", copy);
        }
        return out;
    }

    private Map<String, Object> ideaCall(String action, Map<String, Object> req) {
        InspirationWall w = wall(Objects.requireNonNull(toLong(req.get("wallId")), "wallId"));
        if (!(req.get("idea") instanceof Map<?, ?> idea)) {
            throw new BizException(400, "缺少思路");
        }
        List<Long> ids = longs(req.get("materialIds")).stream().distinct().limit(MAX_MATERIALS).toList();
        Map<String, Object> body = baseBody(w, req);
        body.put("idea", idea);
        body.put("materials", withStage(genService.materialItems(ids, NovelGenService.parseVariants(req.get("materialVariants"))),
                req.get("stage")));
        body.put("instruction", trim(req.get("instruction"), 1000));
        if (req.get("history") instanceof List<?> h) {
            body.put("history", h.stream().map(String::valueOf).limit(20).toList());
        }
        return python(action, body, req.get("model"));
    }

    /** 构思记录（最近的在前） */
    public List<InspirationRun> runs(Long wallId) {
        wall(wallId);
        return runMapper.selectList(new LambdaQueryWrapper<InspirationRun>().eq(InspirationRun::getWallId, wallId)
                .orderByDesc(InspirationRun::getId).last("LIMIT 50"));
    }

    /** 细化 / 修改后，把构思记录里的思路列表整体更新 {ideas} */
    public InspirationRun updateRun(Long id, Map<String, Object> req) {
        InspirationRun run = runMapper.selectById(id);
        if (run == null) {
            throw new BizException(404, "构思记录不存在：" + id);
        }
        if (!(req.get("ideas") instanceof List<?> ideas)) {
            throw new BizException(400, "缺少思路");
        }
        run.setIdeas(objectMapper.convertValue(ideas, List.class));
        runMapper.updateById(run);
        return run;
    }

    // ------------------------------------------------------------------ 内部

    /** 素材条目带上量级和阶段适配（far = 远景，提示词里写明只能当背景 / 传说） */
    List<Map<String, Object>> withStage(List<Map<String, Object>> items, Object stageReq) {
        StageFit.Stage stage = StageFit.of(stageReq);
        Map<Long, Material> byId = new HashMap<>();
        materialService.listByIds(items.stream().map(i -> toLong(i.get("id"))).filter(Objects::nonNull).toList())
                .forEach(m -> byId.put(m.getId(), m));
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> it : items) {
            Map<String, Object> copy = new LinkedHashMap<>(it);
            Material m = byId.get(toLong(it.get("id")));
            if (m != null) {
                copy.put("tier", MaterialService.tierOf(m));
                copy.put("fit", StageFit.fit(m, stage));
            }
            out.add(copy);
        }
        return out;
    }

    /** 作者确认 / 修改过的故事阶段：{phase, tierMax, protagonist}（只收这几个字段） */
    static Map<String, Object> stageBody(Object v) {
        if (!(v instanceof Map<?, ?> m)) {
            return null;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("phase", Objects.toString(m.get("phase"), "any"));
        out.put("tierMax", MaterialService.tierValue(m.get("tierMax")));
        out.put("protagonist", trim(m.get("protagonist"), 200));
        out.put("source", Objects.toString(m.get("source"), "user"));
        return out;
    }

    /** 交给 Python 的公共部分：需求、生成什么、条件、故事阶段、关联工作区、墙上已收藏的思路 */
    private Map<String, Object> baseBody(InspirationWall w, Map<String, Object> req) {
        Map<String, Object> body = new LinkedHashMap<>();
        Map<String, Object> stage = stageBody(req.get("stage"));
        if (stage != null) {
            body.put("stage", stage);
        }
        body.put("request", trim(req.get("request"), 2000));
        body.put("target", target(req));
        body.put("conditions", trim(req.get("conditions"), 2000));
        if (w.getNovelId() != null) {
            body.put("novelId", w.getNovelId());
        }
        List<Map<String, Object>> wallIdeas = new ArrayList<>();
        for (InspirationItem it : itemMapper.selectList(new LambdaQueryWrapper<InspirationItem>()
                .eq(InspirationItem::getWallId, w.getId()).eq(InspirationItem::getType, InspirationItem.IDEA)
                .orderByDesc(InspirationItem::getUpdateTime).last("LIMIT 12"))) {
            Map<String, Object> c = it.getContent() == null ? Map.of() : it.getContent();
            wallIdeas.add(Map.of("title", it.getTitle(), "pitch", Objects.toString(c.get("pitch"), "")));
        }
        body.put("wallIdeas", wallIdeas);
        return body;
    }

    private static String target(Map<String, Object> req) {
        String t = Objects.toString(req.get("target"), "free");
        return TARGETS.contains(t) ? t : "free";
    }

    /** 素材 id → 展示用的来源 {materialId, title, book, category, variant} */
    private Map<Long, Map<String, Object>> refsOf(List<Long> ids, Map<Long, String> variants) {
        Map<Long, Map<String, Object>> refs = new LinkedHashMap<>();
        Map<Long, Material> byId = ids.isEmpty() ? Map.of()
                : materialService.listByIds(ids).stream().collect(Collectors.toMap(Material::getId, m -> m));
        for (Long id : ids) {
            Material m = byId.get(id);
            if (m != null) {
                Map<String, Object> r = new LinkedHashMap<>();
                r.put("materialId", id);
                r.put("title", m.getTitle());
                r.put("book", Objects.toString(m.getSourceBook(), ""));
                r.put("category", m.getCategory());
                r.put("variant", variants.get(id));
                refs.put(id, r);
            }
        }
        return refs;
    }

    private static List<Map<String, Object>> sourceRefs(Object sources, Map<Long, Map<String, Object>> refs) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Long id : longs(sources)) {
            if (refs.containsKey(id)) {
                out.add(refs.get(id));
            }
        }
        return out;
    }

    /** 调 Python 的灵感墙接口：模型按 {source: api, configId?} / {source: gguf} / {source: local, baseId} 解析 */
    private Map<String, Object> python(String action, Map<String, Object> body, Object model) {
        return callGen("/api/gen/inspire/" + action, body, model);
    }

    /** 调 Python 生成接口（灵感墙 / 自动规划共用）：解析模型、转换错误（不记录响应体） */
    @SuppressWarnings("unchecked")
    Map<String, Object> callGen(String path, Map<String, Object> body, Object model) {
        Map<String, Object> modelOpts = model instanceof Map<?, ?> m ? (Map<String, Object>) m : null;
        NovelExtractService.ModelChoice choice = extractService.resolveModel(modelOpts);
        JsonNode res = call(() -> aiClient.genModelCall(path, body, choice.config(), choice.local()));
        return objectMapper.convertValue(res.path("data"), LinkedHashMap.class);
    }

    private JsonNode call(Supplier<JsonNode> fn) {
        JsonNode res;
        try {
            res = fn.get();
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达或响应超时，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            // 不记录响应体：FastAPI 的 422 会回显请求（含 API Key）
            log.warn("AI 服务拒绝灵感墙请求，HTTP {}", e.getStatusCode().value());
            throw new BizException(400, pythonMessage(e));
        }
        if (res == null || res.path("code").asInt(-1) != 0) {
            throw new BizException(400, res == null ? "AI 服务无响应" : res.path("message").asText("构思失败"));
        }
        return res;
    }

    private String pythonMessage(RestClientResponseException e) {
        if (e.getStatusCode().value() != 422) {
            try {
                JsonNode b = objectMapper.readTree(e.getResponseBodyAsString(StandardCharsets.UTF_8));
                if (b.hasNonNull("message")) {
                    return b.get("message").asText();
                }
            } catch (Exception ignored) {
                // 非 JSON 响应
            }
        }
        return "AI 服务拒绝请求（HTTP " + e.getStatusCode().value() + "）";
    }

    private static String trim(Object v, int max) {
        String s = v == null ? "" : String.valueOf(v).trim();
        return s.length() > max ? s.substring(0, max) : s;
    }

    private static Long toLong(Object v) {
        if (v instanceof Number n) {
            return n.longValue();
        }
        if (v instanceof String s && s.matches("\\d+")) {
            return Long.parseLong(s);
        }
        return null;
    }

    private static List<Long> longs(Object v) {
        List<Long> out = new ArrayList<>();
        if (v instanceof List<?> list) {
            for (Object o : list) {
                Long l = toLong(o);
                if (l != null) {
                    out.add(l);
                }
            }
        }
        return out;
    }
}
