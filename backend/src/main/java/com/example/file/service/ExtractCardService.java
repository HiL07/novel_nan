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

    public ExtractCardService(ExtractCardMapper cardMapper, NovelExtractMapper extractMapper, MaterialService materialService,
                              FileService fileService, ObjectMapper objectMapper) {
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
