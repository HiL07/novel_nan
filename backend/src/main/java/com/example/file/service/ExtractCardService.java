package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.ExtractCard;
import com.example.file.entity.FileInfo;
import com.example.file.entity.Material;
import com.example.file.entity.NovelExtract;
import com.example.file.mapper.ExtractCardMapper;
import com.example.file.mapper.NovelExtractMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 卡片（卡片整理工作区）：整理任务的产出写成这个工作区的卡片（不再直接生成素材候选）；可以手改、回退版本；
 * 「素材选择」里勾选后存进素材库 —— 这本书库里已有同分类同名素材时逐条选：更新已有 / 作为可选版本 / 跳过。
 */
@Service
public class ExtractCardService {

    private static final Logger log = LoggerFactory.getLogger(ExtractCardService.class);
    private static final int MAX_HISTORY = 5;
    private static final Set<String> KINDS = Set.of("entity", "system", "arc", "craft", "world", "resonance");
    /** 卡片内容里允许手改的字段（其余如 facts / chapters / entityKey 是依据，改不了） */
    private static final Set<String> EDITABLE = Set.of("title", "subtype", "summary", "detail", "attributes", "tags", "tier", "category");

    private final ExtractCardMapper cardMapper;
    private final NovelExtractMapper extractMapper;
    private final MaterialService materialService;
    private final FileService fileService;
    private final ObjectMapper objectMapper;
    private final AiServiceClient aiClient;

    public ExtractCardService(ExtractCardMapper cardMapper, NovelExtractMapper extractMapper, MaterialService materialService,
                              FileService fileService, ObjectMapper objectMapper, AiServiceClient aiClient) {
        this.aiClient = aiClient;
        this.cardMapper = cardMapper;
        this.extractMapper = extractMapper;
        this.materialService = materialService;
        this.fileService = fileService;
        this.objectMapper = objectMapper;
    }

    public record UpsertStats(int created, int updated, int keptEdited) {
    }

    /**
     * 整理任务的结果 {materials: [...]} → 卡片：新的建卡；已有且没手改过的换成新内容（旧的进 history）；
     * 手改过的保留，AI 新内容放进 history（可以在版本里换回来）。
     */
    @Transactional
    @SuppressWarnings("unchecked")
    public UpsertStats upsertFromCompile(Long extractId, Long compileId, JsonNode result) {
        JsonNode list = result.path("materials");
        if (!list.isArray()) {
            return new UpsertStats(0, 0, 0);
        }
        Map<String, ExtractCard> existing = new HashMap<>();
        for (ExtractCard c : cardMapper.selectList(new LambdaQueryWrapper<ExtractCard>().eq(ExtractCard::getExtractId, extractId))) {
            existing.put(c.getCardKey(), c);
        }
        int created = 0;
        int updated = 0;
        int kept = 0;
        LocalDateTime now = LocalDateTime.now();
        for (JsonNode item : list) {
            String key = item.path("candidateId").asText("");
            String cat = item.path("category").asText("");
            String title = item.path("title").asText("").trim();
            if (key.isEmpty() || !MaterialService.CATEGORIES.containsKey(cat) || title.isEmpty()) {
                continue;
            }
            Map<String, Object> data = objectMapper.convertValue(item, Map.class);
            data.remove("candidateId");
            String given = item.path("kind").asText("");
            String kind = KINDS.contains(given) ? given
                    : "plot".equals(cat) ? "arc" : "体系".equals(item.path("subtype").asText()) ? "system" : "entity";
            data.remove("kind");
            ExtractCard old = existing.get(key);
            if (old == null) {
                ExtractCard c = new ExtractCard();
                c.setExtractId(extractId);
                c.setCardKey(trim(key, 64));
                c.setKind(kind);
                c.setCategory(cat);
                c.setTitle(trim(title, 100));
                c.setData(data);
                c.setHistory(List.of());
                c.setVersion(1);
                c.setEdited(false);
                c.setStatus(ExtractCard.NEW);
                c.setCompileId(compileId);
                c.setCreateTime(now);
                c.setUpdateTime(now);
                cardMapper.insert(c);
                created++;
                continue;
            }
            List<Map<String, Object>> history = new ArrayList<>(old.getHistory() == null ? List.of() : old.getHistory());
            ExtractCard patch = new ExtractCard();
            patch.setId(old.getId());
            patch.setCompileId(compileId);
            patch.setUpdateTime(now);
            if (Boolean.TRUE.equals(old.getEdited())) {
                history.add(0, snapshot(old.getVersion() + 1, "ai", data)); // 手改的不动，AI 新版本放进历史
                patch.setVersion(old.getVersion() + 1);
                patch.setHistory(capped(history));
                kept++;
            } else {
                history.add(0, snapshot(old.getVersion(), "ai", old.getData()));
                patch.setData(data);
                patch.setTitle(trim(title, 100));
                patch.setCategory(cat);
                patch.setKind(kind);
                patch.setVersion(old.getVersion() + 1);
                patch.setHistory(capped(history));
                updated++;
            }
            cardMapper.updateById(patch);
        }
        log.info("工作区 {} 整理出卡片：新建 {}，更新 {}，手改过保留 {}", extractId, created, updated, kept);
        return new UpsertStats(created, updated, kept);
    }

    /** 这个工作区的卡片（不含 history 正文之外的大字段都要：卡片本来就小），带「库里同书同名素材」的匹配 */
    public List<ExtractCard> list(Long extractId) {
        NovelExtract task = requireTask(extractId);
        List<ExtractCard> cards = cardMapper.selectList(new LambdaQueryWrapper<ExtractCard>()
                .eq(ExtractCard::getExtractId, extractId).orderByAsc(ExtractCard::getId));
        Map<String, Material> index = materialService.titleIndexOfBook(MaterialService.bookOf(task.getFileName()));
        for (ExtractCard c : cards) {
            Material m = index.get(c.getCategory() + "|" + MaterialService.normTitle(c.getTitle()));
            if (m != null) {
                Long shown = m.getMergedInto() != null ? m.getMergedInto() : m.getId();
                Map<String, Object> match = new LinkedHashMap<>();
                match.put("id", shown);
                match.put("title", m.getTitle());
                match.put("fromThisCard", Objects.equals(c.getMaterialId(), m.getId()) || Objects.equals(c.getMaterialId(), shown));
                c.setMatch(match);
            }
        }
        return cards;
    }

    /**
     * 入库比对的阈值。重排分（bge-reranker，2026-11-04《奥术神座》实测）：同一东西的不同写法 0.58–0.999，拿不准的 ≈0.4，
     * 不同的人 ≈0.003，一部分 ↔ 整体 ≈0.03；重排不可用时退回 bge-small 余弦（分不开，阈值从严）。
     */
    static final double SAME = 0.85;      // 「一部分 ↔ 整体」重排也常有 0.7–0.93（骑士侍从 ↔ 骑士体系），所以补充进已有要 ≥0.85
    static final double VERSION = 0.40;
    static final double SAME_CHAR = 0.95; // 角色：父女 / 同姓也有 0.7（海恩伯爵 ↔ 菲丽丝·海恩），只有很高才建议
    static final double VERSION_CHAR = 0.85;
    static final double NOISE = 0.10;
    static final double SAME_VEC = 0.88;
    static final double VERSION_VEC = 0.80;

    /**
     * 入库前比对：这个工作区还没入库（NEW）和入库后又改过的卡片，在这本书已有的素材里找「可能是同一条」的
     * （名称 / 别名包含 + 同分类向量相似度，Python material_match），每张卡最多 3 条，并给建议动作：
     * 名称命中或 ≥ SAME = update（补充进已有）；≥ VERSION = version（作为可选版本）；其余 new。合并成员显示成它的主条目。
     * → {matches: {卡片id: [{id, title, category, score, reason, extractId, workspace}]}, suggest: {卡片id: {action, targetId}}, vector, message?}
     */
    public Map<String, Object> matches(Long extractId) {
        NovelExtract task = requireTask(extractId);
        String book = MaterialService.bookOf(task.getFileName());
        List<Material> mats = materialService.materialsOfBook(book);
        Map<String, Object> out = new LinkedHashMap<>();
        Map<String, Object> matches = new LinkedHashMap<>();
        Map<String, Object> suggest = new LinkedHashMap<>();
        out.put("matches", matches);
        out.put("suggest", suggest);
        out.put("vector", false);
        List<ExtractCard> cards = cardMapper.selectList(new LambdaQueryWrapper<ExtractCard>()
                        .eq(ExtractCard::getExtractId, extractId).ne(ExtractCard::getStatus, ExtractCard.SKIPPED))
                .stream().filter(c -> ExtractCard.NEW.equals(c.getStatus()) || c.getMaterialId() == null).toList();
        if (cards.isEmpty() || mats.isEmpty()) {
            return out;
        }
        Map<Long, Material> byId = new HashMap<>();
        mats.forEach(m -> byId.put(m.getId(), m));
        List<Map<String, Object>> items = new ArrayList<>();
        for (Material m : mats) {
            Map<String, Object> it = new LinkedHashMap<>();
            it.put("id", m.getId());
            it.put("category", m.getCategory());
            it.put("title", m.getTitle());
            Object aliases = m.getSource() == null ? null : m.getSource().get("aliases");
            if (aliases instanceof List<?> l) {
                it.put("aliases", l.stream().map(String::valueOf).limit(20).toList());
            }
            it.put("text", trim(m.getTitle() + "：" + Objects.toString(m.getSummary(), ""), 600));
            items.add(it);
        }
        List<Map<String, Object>> queries = new ArrayList<>();
        for (ExtractCard c : cards) {
            Map<String, Object> d = c.getData() == null ? Map.of() : c.getData();
            Map<String, Object> q = new LinkedHashMap<>();
            q.put("id", c.getId());
            q.put("category", c.getCategory());
            q.put("title", c.getTitle());
            if (d.get("aliases") instanceof List<?> l) {
                q.put("aliases", l.stream().map(String::valueOf).limit(20).toList());
            }
            q.put("text", trim(c.getTitle() + "：" + Objects.toString(d.get("summary"), ""), 600));
            queries.add(q);
        }
        JsonNode res = aiClientMatch(queries, items);
        if (res == null) {
            out.put("message", "AI 服务未启动，没法比对");
            return out;
        }
        out.put("vector", res.path("vector").asBoolean(false));
        boolean reranked = res.path("reranked").asBoolean(false);
        out.put("reranked", reranked);
        if (res.hasNonNull("message")) {
            out.put("message", res.path("message").asText());
        }
        Map<Long, String> workspaceTitle = new HashMap<>();
        res.path("matches").fields().forEachRemaining(en -> {
            List<Map<String, Object>> list = new ArrayList<>();
            java.util.Set<Long> seen = new java.util.HashSet<>();
            for (JsonNode h : en.getValue()) {
                Material m = byId.get(h.path("id").asLong());
                if (m == null || (reranked && !"name".equals(h.path("reason").asText()) && h.path("score").asDouble() < NOISE)) {
                    continue; // 重排后分数很低的向量候选是噪音（描述相似的另一个东西），不列
                }
                Material shown = m.getMergedInto() != null && byId.containsKey(m.getMergedInto()) ? byId.get(m.getMergedInto()) : m;
                if (!seen.add(shown.getId())) {
                    continue;
                }
                Map<String, Object> x = new LinkedHashMap<>();
                x.put("id", shown.getId());
                x.put("title", shown.getTitle());
                x.put("category", shown.getCategory());
                x.put("summary", shown.getSummary());
                x.put("score", h.path("score").asDouble());
                x.put("reason", h.path("reason").asText());
                x.put("sameCategory", Objects.equals(m.getCategory(), cardCategory(cards, en.getKey())));
                Object eid = shown.getSource() == null ? null : shown.getSource().get("extractId");
                if (eid instanceof Number n) {
                    x.put("extractId", n.longValue());
                    x.put("workspace", workspaceTitle.computeIfAbsent(n.longValue(), this::workspaceTitleOf));
                }
                list.add(x);
            }
            matches.put(en.getKey(), list);
            Map<String, Object> s = new LinkedHashMap<>();
            if (list.isEmpty()) {
                s.put("action", "new");
            } else {
                Map<String, Object> best = list.get(0);
                double score = ((Number) best.get("score")).doubleValue();
                String reason = String.valueOf(best.get("reason"));
                boolean sameCat = !Boolean.FALSE.equals(best.get("sameCategory"));
                boolean character = "character".equals(cardCategory(cards, en.getKey()));
                double same = !reranked ? SAME_VEC : character ? SAME_CHAR : SAME;
                double version = !reranked ? VERSION_VEC : character ? VERSION_CHAR : VERSION;
                String action;
                if ("name".equals(reason)) {
                    action = sameCat ? "update" : "new"; // 跨分类同名（地点「音乐家协会」↔ 势力）只列出来，不建议合
                } else if (!sameCat) {
                    action = "new";                      // 跨分类的名称包含（「维克托的琴房」⊃「维克托」）不建议
                } else {
                    action = score >= same ? "update" : score >= version ? "version" : "new";
                }
                s.put("action", action);
                if (!"new".equals(s.get("action"))) {
                    s.put("targetId", best.get("id"));
                }
            }
            suggest.put(en.getKey(), s);
        });
        return out;
    }

    private static String cardCategory(List<ExtractCard> cards, String id) {
        return cards.stream().filter(c -> String.valueOf(c.getId()).equals(id)).map(ExtractCard::getCategory).findFirst().orElse("");
    }

    private JsonNode aiClientMatch(List<Map<String, Object>> queries, List<Map<String, Object>> items) {
        try {
            return aiClient.materialMatch(queries, items, 3);
        } catch (Exception e) {
            log.warn("入库比对调用 AI 服务失败：{}", e.getMessage());
            return null;
        }
    }

    /**
     * 素材库「待确认」用：有还没入库（NEW）卡片的工作区 [{extractId, title, book, count}]，按卡片数从多到少
     */
    public List<Map<String, Object>> pendingWorkspaces() {
        List<Map<String, Object>> out = new ArrayList<>();
        newCountsByExtract().forEach((id, n) -> {
            NovelExtract t = extractMapper.selectById(id);
            if (t == null) {
                return;
            }
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("extractId", id);
            m.put("title", workspaceTitleOf(id));
            m.put("book", MaterialService.bookOf(t.getFileName()));
            m.put("count", n);
            out.add(m);
        });
        out.sort((a, b) -> Long.compare((Long) b.get("count"), (Long) a.get("count")));
        return out;
    }

    private String workspaceTitleOf(Long extractId) {
        NovelExtract t = extractMapper.selectById(extractId);
        if (t == null) {
            return "已删除的工作区";
        }
        return t.getTitle() != null && !t.getTitle().isBlank() ? t.getTitle() : "工作区 #" + t.getId();
    }

    /** 手改卡片（只收可改的字段）→ 旧内容进历史，标为手改过 */
    @Transactional
    public ExtractCard update(Long id, Map<String, Object> edits) {
        ExtractCard c = require(id);
        Map<String, Object> data = new LinkedHashMap<>(c.getData() == null ? Map.of() : c.getData());
        if (edits != null) {
            edits.forEach((k, v) -> {
                if (EDITABLE.contains(k)) {
                    data.put(k, v);
                }
            });
        }
        String title = String.valueOf(data.getOrDefault("title", c.getTitle())).trim();
        if (title.isEmpty()) {
            throw new BizException(400, "卡片名称不能为空");
        }
        String cat = String.valueOf(data.getOrDefault("category", c.getCategory()));
        if (!MaterialService.CATEGORIES.containsKey(cat)) {
            throw new BizException(400, "分类不对：" + cat);
        }
        List<Map<String, Object>> history = new ArrayList<>(c.getHistory() == null ? List.of() : c.getHistory());
        history.add(0, snapshot(c.getVersion(), Boolean.TRUE.equals(c.getEdited()) ? "user" : "ai", c.getData()));
        ExtractCard patch = new ExtractCard();
        patch.setId(id);
        patch.setData(data);
        patch.setTitle(trim(title, 100));
        patch.setCategory(cat);
        patch.setHistory(capped(history));
        patch.setVersion(c.getVersion() + 1);
        patch.setEdited(true);
        patch.setUpdateTime(LocalDateTime.now());
        cardMapper.updateById(patch);
        return cardMapper.selectById(id);
    }

    /** 换回历史里的某个版本（当前内容进历史）；换回 AI 版本 = 不再算手改 */
    @Transactional
    @SuppressWarnings("unchecked")
    public ExtractCard restore(Long id, int version) {
        ExtractCard c = require(id);
        List<Map<String, Object>> history = new ArrayList<>(c.getHistory() == null ? List.of() : c.getHistory());
        Map<String, Object> hit = history.stream().filter(h -> h.get("version") instanceof Number n && n.intValue() == version)
                .findFirst().orElseThrow(() -> new BizException(404, "没有这个版本：" + version));
        history.remove(hit);
        history.add(0, snapshot(c.getVersion(), Boolean.TRUE.equals(c.getEdited()) ? "user" : "ai", c.getData()));
        Map<String, Object> data = (Map<String, Object>) hit.get("data");
        ExtractCard patch = new ExtractCard();
        patch.setId(id);
        patch.setData(data);
        patch.setTitle(trim(String.valueOf(data.getOrDefault("title", c.getTitle())), 100));
        patch.setCategory(String.valueOf(data.getOrDefault("category", c.getCategory())));
        patch.setHistory(capped(history));
        patch.setVersion(c.getVersion() + 1);
        patch.setEdited("user".equals(hit.get("by")));
        patch.setUpdateTime(LocalDateTime.now());
        cardMapper.updateById(patch);
        return cardMapper.selectById(id);
    }

    /**
     * 素材选择：items = [{cardId, action: new|update|version|skip|reset, targetId?}]。
     * new = 存成新素材；update = 并进 targetId（库里同名那条）；version = 作为 targetId 的可选版本；skip = 跳过；reset = 取消跳过。
     * → {saved, updated, versions, skipped, errors[]}
     */
    @Transactional
    public Map<String, Object> saveToLibrary(Long extractId, List<Map<String, Object>> items) {
        NovelExtract task = requireTask(extractId);
        FileInfo file = null;
        try {
            file = fileService.getById(task.getFileId());
        } catch (Exception e) {
            // 文件删了：来源只记任务里的文件名
        }
        String fileName = file != null ? file.getFileName() : task.getFileName();
        int saved = 0;
        int updated = 0;
        int versions = 0;
        int skipped = 0;
        List<String> errors = new ArrayList<>();
        for (Map<String, Object> it : items == null ? List.<Map<String, Object>>of() : items) {
            Long cardId = toLong(it.get("cardId"));
            String action = String.valueOf(it.getOrDefault("action", "new"));
            ExtractCard c = cardId == null ? null : cardMapper.selectById(cardId);
            if (c == null || !Objects.equals(c.getExtractId(), extractId)) {
                errors.add("卡片不存在：" + cardId);
                continue;
            }
            if ("skip".equals(action) || "reset".equals(action)) {
                setStatus(c.getId(), "skip".equals(action) ? ExtractCard.SKIPPED : (c.getMaterialId() == null ? ExtractCard.NEW : ExtractCard.SAVED));
                skipped += "skip".equals(action) ? 1 : 0;
                continue;
            }
            Map<String, Object> p = new LinkedHashMap<>(c.getData());
            p.put("title", c.getTitle());
            p.put("category", c.getCategory());
            Material m = materialService.fromCard(p, extractId, task.getFileId(), fileName);
            m.getSource().put("cardId", c.getId());
            if ("resonance".equals(c.getKind())) {
                m.getSource().put("resonance", resonanceSource(c));
            }
            Long targetId = toLong(it.get("targetId"));
            Material result;
            try {
                switch (action) {
                    case "update" -> {
                        if (targetId == null) {
                            throw new BizException(400, "「更新已有」要指定库里的素材");
                        }
                        result = materialService.mergeInto(targetId, m);
                        updated++;
                    }
                    case "version" -> {
                        if (targetId == null) {
                            throw new BizException(400, "「作为可选版本」要指定库里的素材");
                        }
                        result = materialService.attachVersion(targetId, m);
                        versions++;
                    }
                    default -> {
                        result = materialService.save(m);
                        saved++;
                    }
                }
            } catch (BizException e) {
                errors.add(c.getTitle() + "：" + e.getMessage());
                continue;
            }
            cardMapper.update(null, new LambdaUpdateWrapper<ExtractCard>().eq(ExtractCard::getId, c.getId())
                    .set(ExtractCard::getStatus, ExtractCard.SAVED)
                    .set(ExtractCard::getMaterialId, result.getId())
                    .set(ExtractCard::getSavedVersion, c.getVersion())
                    .set(ExtractCard::getUpdateTime, LocalDateTime.now()));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("saved", saved);
        out.put("updated", updated);
        out.put("versions", versions);
        out.put("skipped", skipped);
        out.put("errors", errors);
        return out;
    }

    /** 每个工作区还没处理（NEW）的卡片数：列表上的「N 张卡片待选择」 */
    public Map<Long, Long> newCountsByExtract() {
        Map<Long, Long> out = new HashMap<>();
        for (ExtractCard c : cardMapper.selectList(new LambdaQueryWrapper<ExtractCard>()
                .select(ExtractCard::getId, ExtractCard::getExtractId).eq(ExtractCard::getStatus, ExtractCard.NEW))) {
            out.merge(c.getExtractId(), 1L, Long::sum);
        }
        return out;
    }

    /** 共鸣素材分组提议用：这个工作区的世界观卡 / 体系卡 / 实体卡 [{id, kind, category, title, summary}] */
    public List<Map<String, Object>> resonanceCandidates(Long extractId) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (ExtractCard c : cardMapper.selectList(new LambdaQueryWrapper<ExtractCard>()
                .eq(ExtractCard::getExtractId, extractId).in(ExtractCard::getKind, "world", "system", "entity")
                .orderByAsc(ExtractCard::getId))) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", c.getId());
            m.put("kind", c.getKind());
            m.put("category", c.getCategory());
            m.put("title", c.getTitle());
            m.put("summary", c.getData() == null ? "" : Objects.toString(c.getData().get("summary"), ""));
            out.add(m);
        }
        return out;
    }

    /** 共鸣素材生成用：成员卡的内容 [{id, kind, category, title, summary, detail, attributes, facts}]（只取这个工作区的） */
    public List<Map<String, Object>> resonanceInputs(Long extractId, java.util.Collection<Long> ids) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (ids == null || ids.isEmpty()) {
            return out;
        }
        for (ExtractCard c : cardMapper.selectList(new LambdaQueryWrapper<ExtractCard>()
                .eq(ExtractCard::getExtractId, extractId).in(ExtractCard::getId, ids))) {
            Map<String, Object> d = c.getData() == null ? Map.of() : c.getData();
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", c.getId());
            m.put("kind", c.getKind());
            m.put("category", c.getCategory());
            m.put("title", c.getTitle());
            for (String k : List.of("summary", "detail", "attributes")) {
                if (d.get(k) != null) {
                    m.put(k, d.get(k));
                }
            }
            if (d.get("facts") instanceof List<?> fs) {
                m.put("facts", fs.size() > 6 ? fs.subList(0, 6) : fs);
            }
            out.add(m);
        }
        return out;
    }

    /** 世界观卡整理用：这些实体已有实体卡的概括 {实体键: 概括} */
    public Map<String, String> entitySummaries(Long extractId, Set<String> entityKeys) {
        Map<String, String> out = new HashMap<>();
        for (ExtractCard c : cardMapper.selectList(new LambdaQueryWrapper<ExtractCard>()
                .eq(ExtractCard::getExtractId, extractId).eq(ExtractCard::getKind, "entity"))) {
            Object key = c.getData() == null ? null : c.getData().get("entityKey");
            Object summary = c.getData() == null ? null : c.getData().get("summary");
            if (key != null && entityKeys.contains(String.valueOf(key)) && summary != null && !String.valueOf(summary).isBlank()) {
                out.put(String.valueOf(key), String.valueOf(summary));
            }
        }
        return out;
    }

    public long countOfExtract(Long extractId) {
        return cardMapper.selectCount(new LambdaQueryWrapper<ExtractCard>().eq(ExtractCard::getExtractId, extractId));
    }

    /** 删除工作区：它的卡片一起删（已存进素材库的素材不动） */
    public int deleteOfExtract(Long extractId) {
        return cardMapper.delete(new LambdaQueryWrapper<ExtractCard>().eq(ExtractCard::getExtractId, extractId));
    }

    /**
     * 共鸣素材入库时一并存整张图：{theme, nodes（每个节点带对应的已入库素材 materialId，成员卡还没入库的为 null，以后跨书关联用）,
     * edges, rules, fusion, gaps}
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> resonanceSource(ExtractCard c) {
        Map<String, Object> d = c.getData() == null ? Map.of() : c.getData();
        List<Map<String, Object>> nodes = new ArrayList<>();
        List<Long> cardIds = new ArrayList<>();
        if (d.get("nodes") instanceof List<?> ns) {
            for (Object o : ns) {
                if (o instanceof Map<?, ?> n && n.get("cardId") instanceof Number id) {
                    cardIds.add(id.longValue());
                }
            }
        }
        Map<Long, Long> materialOf = new HashMap<>();
        if (!cardIds.isEmpty()) {
            cardMapper.selectBatchIds(cardIds).forEach(x -> materialOf.put(x.getId(), x.getMaterialId()));
        }
        if (d.get("nodes") instanceof List<?> ns) {
            for (Object o : ns) {
                if (o instanceof Map<?, ?> n) {
                    Map<String, Object> node = new LinkedHashMap<>((Map<String, Object>) n);
                    Object id = n.get("cardId");
                    node.put("materialId", id instanceof Number num ? materialOf.get(num.longValue()) : null);
                    nodes.add(node);
                }
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("theme", d.get("theme"));
        out.put("nodes", nodes);
        for (String k : List.of("edges", "rules", "fusion", "gaps")) {
            out.put(k, d.get(k));
        }
        return out;
    }

    // ------------------------------------------------------------------ 工具

    private void setStatus(Long id, String status) {
        cardMapper.update(null, new LambdaUpdateWrapper<ExtractCard>().eq(ExtractCard::getId, id)
                .set(ExtractCard::getStatus, status).set(ExtractCard::getUpdateTime, LocalDateTime.now()));
    }

    private ExtractCard require(Long id) {
        ExtractCard c = id == null ? null : cardMapper.selectById(id);
        if (c == null) {
            throw new BizException(404, "卡片不存在：" + id);
        }
        return c;
    }

    private NovelExtract requireTask(Long extractId) {
        NovelExtract t = extractId == null ? null : extractMapper.selectById(extractId);
        if (t == null) {
            throw new BizException(404, "提取工作区不存在：" + extractId);
        }
        return t;
    }

    private static Map<String, Object> snapshot(int version, String by, Map<String, Object> data) {
        Map<String, Object> h = new LinkedHashMap<>();
        h.put("version", version);
        h.put("by", by);
        h.put("time", LocalDateTime.now().withNano(0).toString().replace('T', ' '));
        h.put("data", data == null ? Map.of() : data);
        return h;
    }

    private static List<Map<String, Object>> capped(List<Map<String, Object>> history) {
        return history.size() > MAX_HISTORY ? new ArrayList<>(history.subList(0, MAX_HISTORY)) : history;
    }

    private static String trim(String s, int max) {
        if (s == null) {
            return null;
        }
        String t = s.trim();
        return t.length() > max ? t.substring(0, max) : t;
    }

    private static Long toLong(Object v) {
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return v == null ? null : Long.valueOf(String.valueOf(v));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    static boolean validKind(String kind) {
        return KINDS.contains(kind);
    }
}
