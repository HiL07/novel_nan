package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.Material;
import com.example.file.entity.MaterialCandidate;
import com.example.file.entity.MaterialTag;
import com.example.file.mapper.MaterialCandidateMapper;
import com.example.file.mapper.MaterialMapper;
import com.example.file.mapper.MaterialTagMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 创作素材库：分类 / 标签 / 关键词检索、AI 语义检索、素材增删改，以及 AI 提取候选的确认流程。
 * 分类代码与 python-service/app/materials.py、前端 api/material.js 保持一致。
 *
 * 来源书（source_book）与保留（pinned）：素材按来源书筛选、按书批量删除；AI 生成时可屏蔽某些来源书。
 * 保留的素材不受「按书删除」和「屏蔽来源书」影响。
 */
@Service
public class MaterialService {

    private static final Logger log = LoggerFactory.getLogger(MaterialService.class);

    /** 分类代码 → 名称（有序） */
    public static final Map<String, String> CATEGORIES = new LinkedHashMap<>();

    static {
        CATEGORIES.put("world", "世界观");
        CATEGORIES.put("faction", "势力");
        CATEGORIES.put("character", "角色");
        CATEGORIES.put("monster", "怪物");
        CATEGORIES.put("location", "地点");
        CATEGORIES.put("item", "物品功法");
        CATEGORIES.put("plot", "情节");
        CATEGORIES.put("craft", "写法"); // 卡片整理的写法卡（不是设定实体，提取时不读）
        CATEGORIES.put("resonance", "共鸣"); // 共鸣素材：同一主题的卡片关联成整体（节点 / 关系 / 联动规则 / 融入指南）
    }

    private static final int SEMANTIC_POOL = 150;
    /** 向量检索一次最多比较的素材数（超出按使用次数取前 N 条） */
    private static final int VECTOR_POOL = 20000;
    /** 按来源书筛选时代表「手动添加（无来源书）」 */
    public static final String MANUAL_BOOK = "__manual__";

    private final MaterialMapper materialMapper;
    private final MaterialTagMapper tagMapper;
    private final MaterialCandidateMapper candidateMapper;
    private final AiServiceClient aiClient;
    private final AiModelConfigService modelService;
    private final ObjectMapper objectMapper;

    public MaterialService(MaterialMapper materialMapper, MaterialTagMapper tagMapper,
                           MaterialCandidateMapper candidateMapper, AiServiceClient aiClient,
                           AiModelConfigService modelService, ObjectMapper objectMapper) {
        this.materialMapper = materialMapper;
        this.tagMapper = tagMapper;
        this.candidateMapper = candidateMapper;
        this.aiClient = aiClient;
        this.modelService = modelService;
        this.objectMapper = objectMapper;
    }

    // ------------------------------------------------------------------ 分类 / 标签

    /** [{code, label, count}]，含「全部」以外的每个分类 */
    public List<Map<String, Object>> categories() {
        Map<String, Long> counts = new LinkedHashMap<>();
        for (Map<String, Object> row : materialMapper.selectMaps(new QueryWrapper<Material>()
                .select("category", "COUNT(*) AS cnt").isNull("merged_into").groupBy("category"))) {
            counts.put(String.valueOf(row.get("category")), ((Number) row.get("cnt")).longValue());
        }
        List<Map<String, Object>> out = new ArrayList<>();
        CATEGORIES.forEach((code, label) -> out.add(Map.of("code", code, "label", label, "count", counts.getOrDefault(code, 0L))));
        return out;
    }

    /** 标签云 [{tag, count}]，按使用次数倒序；可按分类限定 */
    public List<Map<String, Object>> tags(String category) {
        QueryWrapper<MaterialTag> q = new QueryWrapper<MaterialTag>().select("tag", "COUNT(*) AS cnt").groupBy("tag")
                .orderByDesc("cnt").last("LIMIT 300");
        if (category != null && !category.isBlank()) {
            List<Object> ids = materialMapper.selectObjs(new LambdaQueryWrapper<Material>().select(Material::getId)
                    .eq(Material::getCategory, checkCategory(category)));
            if (ids.isEmpty()) {
                return List.of();
            }
            q.in("material_id", ids);
        }
        return tagMapper.selectMaps(q).stream()
                .map(r -> Map.<String, Object>of("tag", r.get("tag"), "count", ((Number) r.get("cnt")).longValue()))
                .toList();
    }

    // ------------------------------------------------------------------ 关键词检索

    /**
     * 关键词 + 标签检索。tagMode = all：须包含全部所选标签；any：包含任一。
     */
    public Page<Material> search(String category, List<String> tags, String tagMode, String keyword, int page, int size) {
        return search(category, tags, tagMode, keyword, null, null, null, page, size);
    }

    /**
     * @param sourceBook   只看某本书的素材（{@link #MANUAL_BOOK} = 手动添加的）；空 = 全部
     * @param excludeBooks 屏蔽这些来源书的素材（保留的素材除外）
     * @param pinnedOnly   true = 只看保留的素材
     */
    public Page<Material> search(String category, List<String> tags, String tagMode, String keyword,
                                 String sourceBook, List<String> excludeBooks, Boolean pinnedOnly, int page, int size) {
        Page<Material> pg = new Page<>(Math.max(page, 1), Math.min(Math.max(size, 1), 100));
        List<Long> tagIds = idsWithTags(tags, !"any".equalsIgnoreCase(tagMode));
        if (tagIds != null && tagIds.isEmpty()) {
            return pg;
        }
        LambdaQueryWrapper<Material> q = baseQuery(category, tagIds);
        applyBooks(q, sourceBook, excludeBooks);
        if (Boolean.TRUE.equals(pinnedOnly)) {
            q.eq(Material::getPinned, true);
        }
        if (keyword != null && !keyword.isBlank()) {
            for (String word : keyword.trim().split("\\s+")) {
                // 已并入主条目的成员命中关键词时，返回它的主条目（成员本身不单独出现）
                List<Long> masters = mastersOfMembersMatching(word);
                q.and(w -> {
                    w.like(Material::getTitle, word).or().like(Material::getSummary, word)
                            .or().like(Material::getSubtype, word).or().like(Material::getDetail, word)
                            .or().like(Material::getTags, word);
                    if (!masters.isEmpty()) {
                        w.or().in(Material::getId, masters);
                    }
                });
            }
        }
        q.orderByDesc(Material::getUpdateTime);
        return materialMapper.selectPage(pg, q);
    }

    /** 名称 / 概括 / 子类 / 详细 / 标签含 word 的已合并成员 → 它们的主条目 id（参数化 LIKE） */
    private List<Long> mastersOfMembersMatching(String word) {
        return materialMapper.selectObjs(new LambdaQueryWrapper<Material>().select(Material::getMergedInto)
                        .isNotNull(Material::getMergedInto)
                        .and(w -> w.like(Material::getTitle, word).or().like(Material::getSummary, word)
                                .or().like(Material::getSubtype, word).or().like(Material::getDetail, word)
                                .or().like(Material::getTags, word)))
                .stream().map(o -> ((Number) o).longValue()).distinct().toList();
    }

    /** 列表 / 检索 / AI 用的基础条件：已并入主条目的成员不出现（只在主条目的「各书写法」里看到） */
    private LambdaQueryWrapper<Material> baseQuery(String category, List<Long> ids) {
        LambdaQueryWrapper<Material> q = new LambdaQueryWrapper<Material>().isNull(Material::getMergedInto);
        if (category != null && !category.isBlank()) {
            q.eq(Material::getCategory, checkCategory(category));
        }
        if (ids != null) {
            q.in(Material::getId, ids);
        }
        return q;
    }

    /** 来源书筛选 + 屏蔽（屏蔽的书里「保留」的素材仍然可见 / 可用） */
    private void applyBooks(LambdaQueryWrapper<Material> q, String sourceBook, List<String> excludeBooks) {
        if (sourceBook != null && !sourceBook.isBlank()) {
            if (MANUAL_BOOK.equals(sourceBook)) {
                q.isNull(Material::getSourceBook);
            } else {
                q.eq(Material::getSourceBook, sourceBook.trim());
            }
        }
        List<String> excluded = cleanBooks(excludeBooks);
        if (!excluded.isEmpty()) {
            q.and(w -> w.isNull(Material::getSourceBook).or().notIn(Material::getSourceBook, excluded)
                    .or().eq(Material::getPinned, true));
        }
    }

    private static List<String> cleanBooks(List<String> books) {
        if (books == null) {
            return List.of();
        }
        return books.stream().filter(Objects::nonNull).map(String::trim).filter(s -> !s.isEmpty()).distinct().toList();
    }

    /** 去掉被屏蔽来源书的素材（保留的素材不去掉），保持顺序 */
    public List<Material> withoutBlocked(List<Material> materials, List<String> excludeBooks) {
        Set<String> excluded = new LinkedHashSet<>(cleanBooks(excludeBooks));
        if (excluded.isEmpty()) {
            return materials;
        }
        return materials.stream()
                .filter(m -> Boolean.TRUE.equals(m.getPinned()) || m.getSourceBook() == null || !excluded.contains(m.getSourceBook()))
                .toList();
    }

    /** 带有所选标签的素材 id（all = 必须全部包含）；未选标签返回 null 表示不按标签筛选。参数化查询，无拼接 SQL */
    private List<Long> idsWithTags(List<String> tags, boolean all) {
        List<String> clean = normalizeTags(tags);
        if (clean.isEmpty()) {
            return null;
        }
        QueryWrapper<MaterialTag> q = new QueryWrapper<MaterialTag>().select("material_id").in("tag", clean).groupBy("material_id");
        if (all) {
            q.having("COUNT(DISTINCT tag) = {0}", clean.size());
        }
        return tagMapper.selectObjs(q).stream().map(o -> ((Number) o).longValue()).toList();
    }

    // ------------------------------------------------------------------ AI 语义检索

    /**
     * 语义检索：① 模型把需求扩展成关键词 / 标签 / 分类 → ② 数据库初筛（最多 150 条，库小时直接全量）
     * → ③ 模型按需求打分排序并给出理由。使用「模型配置」中启用的模型。
     */
    public Map<String, Object> semanticSearch(String query, String category, List<String> tags, int limit) {
        return semanticSearch(query, category, tags, null, limit);
    }

    /** @param excludeBooks 不参与检索的来源书（其中保留的素材仍参与） */
    public Map<String, Object> semanticSearch(String query, String category, List<String> tags,
                                              List<String> excludeBooks, int limit) {
        if (query == null || query.isBlank()) {
            throw new BizException(400, "请输入要查找的内容");
        }
        AiModelConfig model = modelService.requireActive();
        JsonNode expansion = callAi(() -> aiClient.expandMaterialQuery(query.trim(), model));
        Set<String> words = new LinkedHashSet<>();
        words.add(query.trim());
        expansion.path("keywords").forEach(n -> words.add(n.asText()));
        Set<String> expTags = new LinkedHashSet<>();
        expansion.path("tags").forEach(n -> expTags.add(n.asText()));

        List<Long> tagIds = idsWithTags(tags, false);
        LambdaQueryWrapper<Material> countQ = baseQuery(category, tagIds);
        applyBooks(countQ, null, excludeBooks);
        long total = tagIds != null && tagIds.isEmpty() ? 0 : materialMapper.selectCount(countQ);
        List<Material> pool;
        if (total == 0) {
            pool = List.of();
        } else if (total <= SEMANTIC_POOL) {
            LambdaQueryWrapper<Material> q = baseQuery(category, tagIds);
            applyBooks(q, null, excludeBooks);
            pool = materialMapper.selectList(q);
        } else {
            LambdaQueryWrapper<Material> q = baseQuery(category, tagIds);
            applyBooks(q, null, excludeBooks);
            List<String> all = new ArrayList<>(words);
            all.addAll(expTags);
            q.and(w -> {
                for (String word : all) {
                    w.or().like(Material::getTitle, word).or().like(Material::getSummary, word).or().like(Material::getTags, word);
                }
            });
            q.orderByDesc(Material::getUseCount).last("LIMIT " + SEMANTIC_POOL);
            pool = materialMapper.selectList(q);
        }

        List<Map<String, Object>> items = pool.stream().map(m -> Map.<String, Object>of(
                "id", m.getId(), "category", m.getCategory(), "title", m.getTitle(),
                "summary", Objects.requireNonNullElse(m.getSummary(), ""),
                "tags", Objects.requireNonNullElse(m.getTags(), List.of()))).toList();
        List<Map<String, Object>> results = new ArrayList<>();
        if (!items.isEmpty()) {
            JsonNode ranked = callAi(() -> aiClient.rerankMaterials(query.trim(), items, Math.min(Math.max(limit, 1), 50), model));
            Map<Long, Material> byId = pool.stream().collect(Collectors.toMap(Material::getId, m -> m));
            for (JsonNode r : ranked.path("results")) {
                Material m = byId.get(r.path("id").asLong());
                if (m != null) {
                    results.add(Map.of("material", m, "score", r.path("score").asInt(), "reason", r.path("reason").asText("")));
                }
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("expansion", Map.of("keywords", words, "tags", expTags,
                "categories", objectMapper.convertValue(expansion.path("categories"), List.class)));
        out.put("considered", items.size());
        out.put("results", results);
        out.put("model", model.getName());
        return out;
    }

    // ------------------------------------------------------------------ 向量检索（本地 embedding 模型）

    public Map<String, Object> vectorSearch(String query, String category, List<String> tags,
                                            List<String> excludeBooks, String modelId, int limit) {
        return vectorSearch(query, category, tags, excludeBooks, modelId, limit, "hybrid", true);
    }

    /**
     * 本地检索（RAG 的召回 + 精排）：按分类 / 标签 / 屏蔽来源书筛出素材（不做关键词初筛，最多 {@link #VECTOR_POOL} 条），
     * 交给 Python：向量（bge-small-zh）+ 关键词（BM25，jieba 分词，素材标签作词表）各召回、倒数排名融合，
     * 再用重排模型（bge-reranker-v2-m3）重排前 30 条。不用大模型、不花 token；还没向量化的素材顺便编码。
     * score：重排过 = 相关度 × 100（可当阈值，见 {@link #RERANK_MIN_SCORE}），没重排 = 余弦相似度 × 100（只看相对高低）。
     *
     * @param modelId python-service 登记的向量模型 id；空 = Python 的默认向量模型
     * @param mode    vector = 只用向量；hybrid = 向量 + 关键词
     * @param rerank  有重排模型时重排（没有 / 显存不够时自动跳过，结果 reranked = false）
     */
    public Map<String, Object> vectorSearch(String query, String category, List<String> tags, List<String> excludeBooks,
                                            String modelId, int limit, String mode, boolean rerank) {
        return vectorSearch(query, category, tags, excludeBooks, modelId, limit, mode, rerank, null);
    }

    /**
     * 同上，另外：keep = 先过滤再检索（灵感墙按故事阶段挡掉超量级的素材；先检索后过滤会把结果筛光），
     * 被挡掉的条数记在 filtered。
     */
    public Map<String, Object> vectorSearch(String query, String category, List<String> tags, List<String> excludeBooks,
                                            String modelId, int limit, String mode, boolean rerank,
                                            java.util.function.Predicate<Material> keep) {
        if (query == null || query.isBlank()) {
            throw new BizException(400, "请输入要查找的内容");
        }
        List<Long> tagIds = idsWithTags(tags, false);
        List<Material> pool = List.of();
        long total = 0;
        if (tagIds == null || !tagIds.isEmpty()) {
            LambdaQueryWrapper<Material> q = baseQuery(category, tagIds);
            applyBooks(q, null, excludeBooks);
            total = materialMapper.selectCount(q);
            if (total > 0) {
                LambdaQueryWrapper<Material> lq = baseQuery(category, tagIds);
                applyBooks(lq, null, excludeBooks);
                lq.orderByDesc(Material::getUseCount).orderByDesc(Material::getUpdateTime).last("LIMIT " + VECTOR_POOL);
                pool = materialMapper.selectList(lq);
            }
        }
        int filtered = 0;
        if (keep != null && !pool.isEmpty()) {
            List<Material> kept = pool.stream().filter(keep).toList();
            filtered = pool.size() - kept.size();
            pool = kept;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", total);
        out.put("considered", pool.size());
        out.put("filtered", filtered);
        List<Map<String, Object>> results = new ArrayList<>();
        out.put("results", results);
        if (pool.isEmpty()) {
            return out;
        }
        String q = query.trim();
        // 多版本主条目：共性一条 + 每个版本（成员）各一条参与召回，命中任一版本都返回主条目（不把版本拼成一个向量：
        // 写法差别大时拼出来的向量落在中间，哪个版本都搜不准）
        List<Map<String, Object>> items = new ArrayList<>(vectorItems(pool));
        Map<Long, Material> masterOf = new HashMap<>();   // 成员 id → 主条目
        Map<Long, Material> memberById = new HashMap<>();
        Map<Long, Material> masters = pool.stream().filter(MaterialService::isMergeMaster)
                .collect(Collectors.toMap(Material::getId, x -> x));
        if (!masters.isEmpty()) {
            for (Material member : materialMapper.selectList(new LambdaQueryWrapper<Material>()
                    .in(Material::getMergedInto, masters.keySet()))) {
                Material master = masters.get(member.getMergedInto());
                masterOf.put(member.getId(), master);
                memberById.put(member.getId(), member);
                items.add(Map.of("id", member.getId(), "text", variantText(master, member)));
            }
        }
        int want = Math.min(Math.max(limit, 1), 200);
        String m0 = "vector".equals(mode) ? "vector" : "hybrid";
        List<String> vocab = "hybrid".equals(m0) ? tagVocabulary() : List.of();
        JsonNode res = callAi(() -> aiClient.vectorSearchMaterials(modelId, q.substring(0, Math.min(q.length(), 2000)),
                items, masterOf.isEmpty() ? want : Math.min(want * 2, 200), m0, rerank, vocab), "向量检索失败");
        Map<Long, Material> byId = pool.stream().collect(Collectors.toMap(Material::getId, m -> m));
        Set<Long> seen = new java.util.HashSet<>();
        for (JsonNode r : res.path("results")) {
            long hit = r.path("id").asLong();
            Material member = memberById.get(hit);
            Material m = member != null ? masterOf.get(hit) : byId.get(hit);
            // 结果已按分数从高到低：同一主条目只留第一次出现（= 各版本里分数最高的）
            if (m != null && results.size() < want && seen.add(m.getId())) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("material", m);
                if (member != null) {
                    row.put("matchedVariant", member.getId());
                    row.put("matchedLabel", variantLabel(m, member));
                }
                row.put("score", (int) Math.round(r.path("score").asDouble() * 100));
                row.put("similarity", r.path("similarity").asDouble());
                row.put("vecRank", r.path("vecRank").isNumber() ? r.path("vecRank").asInt() : null);
                row.put("lexRank", r.path("lexRank").isNumber() ? r.path("lexRank").asInt() : null);
                results.add(row);
            }
        }
        for (String k : List.of("model", "modelId", "device", "encoded", "cached", "ms", "mode", "reranked", "rerankSkipped",
                "rerankModel", "rerankDevice", "rerankMs", "queryTokens")) {
            out.put(k, objectMapper.convertValue(res.path(k), Object.class));
        }
        return out;
    }

    /** 主条目某个版本的检索文本：主条目名称 + 版本名 / 独有设定 + 成员原文（搜「神水」时各版本都能召回） */
    private static String variantText(Material master, Material member) {
        Map<String, Object> v = variantOf(master, member.getId());
        return String.join("\n", master.getTitle(), Objects.toString(v.get("label"), ""),
                Objects.toString(v.get("note"), ""), vectorText(member)).trim();
    }

    /** 主条目 source.variants 里这个成员的那一项（没有返回空 Map） */
    @SuppressWarnings("unchecked")
    static Map<String, Object> variantOf(Material master, Long memberId) {
        if (master.getSource() != null && master.getSource().get("variants") instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map<?, ?> v && v.get("id") instanceof Number n && n.longValue() == memberId) {
                    return (Map<String, Object>) v;
                }
            }
        }
        return Map.of();
    }

    /** 版本名：合并时写的 label，没有就用成员名称 */
    static String variantLabel(Material master, Material member) {
        String label = Objects.toString(variantOf(master, member.getId()).get("label"), "").trim();
        return label.isEmpty() ? member.getTitle() : label;
    }

    /**
     * 工作区的故事阶段（Python 按阶段表 / 已写章数推算）；没有工作区 / Python 不可达 = 不限
     */
    public StageFit.Stage novelStage(String novelId) {
        if (novelId == null || novelId.isBlank()) {
            return StageFit.of(null);
        }
        try {
            return StageFit.of(objectMapper.convertValue(aiClient.getNovelStage(novelId.trim()).path("data"), Map.class));
        } catch (Exception e) {
            log.debug("读取工作区 {} 的故事阶段失败：{}", novelId, e.getMessage());
            return StageFit.of(null);
        }
    }

    /** 检索结果每条加上 tier / fit（和工作区当前阶段合不合适），结果里另附 stage */
    public Map<String, Object> withStageFit(Map<String, Object> found, String novelId) {
        if (novelId == null || novelId.isBlank()) {
            return found;
        }
        StageFit.Stage stage = novelStage(novelId);
        if (found.get("results") instanceof List<?> rs) {
            for (Object o : rs) {
                if (o instanceof Map<?, ?> r && r.get("material") instanceof Material m) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> row = (Map<String, Object>) r;
                    row.put("tier", tierOf(m));
                    row.put("fit", StageFit.fit(m, stage));
                }
            }
        }
        Map<String, Object> st = new LinkedHashMap<>();
        st.put("phase", stage.phase());
        st.put("tierMax", stage.tierMax());
        found.put("stage", st);
        return found;
    }

    /** 重排后的相关度达到这个分（0–100）才算「相关」：用于 AI 构思的自动匹配、选择弹窗的预勾选 */
    public static final int RERANK_MIN_SCORE = 30;

    /** 全部素材标签（去重）：作为 jieba 的领域词表，让「退婚」「扮猪吃虎」这类网文用语不被切碎 */
    private List<String> tagVocabulary() {
        return tagMapper.selectObjs(new QueryWrapper<MaterialTag>().select("DISTINCT tag")).stream()
                .map(String::valueOf).filter(t -> t.length() >= 2 && t.length() <= 8).toList();
    }

    /** 全部素材的向量化情况（encode=false）或把还没向量化的全部编码（encode=true） */
    public Map<String, Object> vectorIndex(String modelId, boolean encode) {
        List<Material> all = materialMapper.selectList(new LambdaQueryWrapper<Material>()
                .select(Material::getId, Material::getTitle, Material::getSubtype, Material::getSummary,
                        Material::getAttributes, Material::getTags));
        if (all.isEmpty()) {
            return Map.of("total", 0, "cached", 0, "encoded", 0, "pending", 0);
        }
        JsonNode res = callAi(() -> aiClient.vectorIndexMaterials(modelId, vectorItems(all), encode), "素材向量化失败");
        Map<String, Object> out = new LinkedHashMap<>();
        for (String k : List.of("total", "cached", "encoded", "pending", "model", "modelId", "device", "ms")) {
            out.put(k, objectMapper.convertValue(res.path(k), Object.class));
        }
        return out;
    }

    private static List<Map<String, Object>> vectorItems(List<Material> list) {
        return list.stream().map(m -> Map.<String, Object>of("id", m.getId(), "text", vectorText(m))).toList();
    }

    /**
     * 素材 → 向量化文本：只拼有内容的部分（名称 / 子类 / 标签 / 概括 / 属性值）。分类名、属性键名每条都差不多，
     * 写进去会把向量互相拉近，所以不写（分类用作过滤条件）。素材都在 512 token 以内，不需要切块
     */
    static String vectorText(Material m) {
        List<String> parts = new ArrayList<>();
        parts.add(m.getTitle());
        parts.add(m.getSubtype());
        if (m.getTags() != null && !m.getTags().isEmpty()) {
            parts.add(String.join("、", m.getTags()));
        }
        parts.add(m.getSummary());
        if (m.getAttributes() != null) {
            m.getAttributes().values().forEach(v -> parts.add(v instanceof List<?> l
                    ? l.stream().map(String::valueOf).collect(Collectors.joining("、")) : v == null ? null : String.valueOf(v)));
        }
        return parts.stream().filter(s -> s != null && !s.isBlank()).map(String::trim).collect(Collectors.joining("\n"));
    }

    /** 向量检索后勾选 / 没勾选的素材：转给 Python 记入 feedback.jsonl（失败只记日志，不影响页面） */
    public void vectorFeedback(Map<String, Object> body) {
        Map<String, Object> clean = new LinkedHashMap<>();
        for (String k : List.of("query", "modelId", "shownIds", "pickedIds", "context")) {
            if (body.get(k) != null) {
                clean.put(k, body.get(k));
            }
        }
        if (!(clean.get("query") instanceof String q) || q.isBlank()) {
            throw new BizException(400, "缺少 query");
        }
        try {
            aiClient.vectorFeedback(clean);
        } catch (RuntimeException e) {
            log.warn("记录向量检索反馈失败：{}", e.getMessage());
        }
    }

    private interface AiCall {
        JsonNode run();
    }

    private JsonNode callAi(AiCall call) {
        return callAi(call, "AI 语义检索失败");
    }

    private JsonNode callAi(AiCall call, String failure) {
        JsonNode res;
        try {
            res = call.run();
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            log.warn("AI 语义检索请求被拒绝，HTTP {}", e.getStatusCode().value());
            throw new BizException(502, "AI 服务拒绝请求（HTTP " + e.getStatusCode().value() + "）");
        }
        if (res == null || !res.path("ok").asBoolean(false)) {
            throw new BizException(502, failure + "：" + (res == null ? "无响应" : res.path("message").asText()));
        }
        return res;
    }

    // ------------------------------------------------------------------ 素材增删改

    /** 按 id 批量取素材（不存在的 id 忽略），保持传入顺序 */
    public List<Material> listByIds(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        Map<Long, Material> byId = materialMapper.selectBatchIds(ids).stream()
                .collect(Collectors.toMap(Material::getId, m -> m));
        return ids.stream().distinct().map(byId::get).filter(Objects::nonNull).toList();
    }

    public Material get(Long id) {
        Material m = materialMapper.selectById(id);
        if (m == null) {
            throw new BizException(404, "素材不存在：" + id);
        }
        return m;
    }

    /** 详情：主条目（合并而来）附带成员素材，供「各书写法」展示 */
    public Material detail(Long id) {
        Material m = get(id);
        if (isMergeMaster(m)) {
            m.setMembers(membersOf(id));
        }
        return m;
    }

    /** 主条目的成员（各版本），按 id 升序 */
    public List<Material> membersOf(Long masterId) {
        return materialMapper.selectList(new LambdaQueryWrapper<Material>().eq(Material::getMergedInto, masterId)
                .orderByAsc(Material::getId));
    }

    public static boolean isMergeMaster(Material m) {
        return m.getSource() != null && "merge".equals(m.getSource().get("type"));
    }

    /** 新增（id 为空）或修改；标签同步写入 material_tag */
    @Transactional
    public Material save(Material req) {
        String title = req.getTitle() == null ? "" : req.getTitle().trim();
        if (title.isEmpty()) {
            throw new BizException(400, "素材名称不能为空");
        }
        LocalDateTime now = LocalDateTime.now();
        Material m = req.getId() == null ? new Material() : get(req.getId());
        m.setCategory(checkCategory(req.getCategory()));
        m.setSubtype(trimTo(req.getSubtype(), 32));
        m.setTitle(trimTo(title, 100));
        m.setSummary(trimTo(req.getSummary(), 300));
        m.setAttributes(req.getAttributes() == null ? Map.of() : req.getAttributes());
        m.setDetail(req.getDetail());
        m.setTags(normalizeTags(req.getTags()));
        if (req.getSourceBook() != null) {
            String book = req.getSourceBook().trim();
            m.setSourceBook(book.isEmpty() || MANUAL_BOOK.equals(book) ? null : trimTo(book, 100));
        }
        if (req.getPinned() != null) {
            m.setPinned(req.getPinned());
        }
        if (req.getProfile() != null) {
            m.setProfile(mergeProfile(req.getId() == null ? null : m.getProfile(), req.getProfile(), req.getId() != null));
        }
        if (req.getId() == null) {
            m.setSource(req.getSource() == null ? Map.of("type", "manual") : req.getSource());
            if (m.getSourceBook() == null && m.getSource().get("fileName") != null) {
                m.setSourceBook(bookOf(String.valueOf(m.getSource().get("fileName"))));
            }
            if (m.getPinned() == null) {
                m.setPinned(false);
            }
            m.setUseCount(0);
            m.setCreateTime(now);
            m.setUpdateTime(now);
            materialMapper.insert(m);
        } else {
            m.setUpdateTime(now);
            materialMapper.updateById(m);
            if (req.getSourceBook() != null && m.getSourceBook() == null) {
                // updateById 跳过 null 字段：清空来源书（改为手动）要显式更新
                materialMapper.update(null, new LambdaUpdateWrapper<Material>().eq(Material::getId, m.getId())
                        .set(Material::getSourceBook, null));
            }
        }
        syncTags(m.getId(), m.getTags());
        return m;
    }

    /**
     * 量级画像的合并：新建时照收（整理卡片给的 tier / bookPos，tierBy = ai）；修改时只看 tier —— 和原来不同 = 作者手改，
     * 记 tierBy = user（之后 AI 批量标注不再覆盖），bookPos 等代码算的字段保留原值。
     */
    static Map<String, Object> mergeProfile(Map<String, Object> old, Map<String, Object> req, boolean edit) {
        Map<String, Object> out = new LinkedHashMap<>(old == null ? Map.of() : old);
        Integer tier = tierValue(req.get("tier"));
        if (!edit) {
            if (tier != null) {
                out.put("tier", tier);
                out.put("tierBy", "user".equals(req.get("tierBy")) ? "user" : "ai");
                if (req.get("tierReason") != null) {
                    out.put("tierReason", trimTo(String.valueOf(req.get("tierReason")), 60));
                }
            }
            if (req.get("bookPos") instanceof Number n) {
                out.put("bookPos", Math.max(0, Math.min(1, n.doubleValue())));
            }
        } else if (req.containsKey("tier") && !Objects.equals(tier, tierValue(out.get("tier")))) {
            if (tier == null) {
                out.remove("tier");
                out.remove("tierReason");
                out.remove("tierBy");
            } else {
                out.put("tier", tier);
                out.put("tierBy", "user");
                out.put("tierReason", "作者手改");
            }
        }
        return out;
    }

    /** 1–5 的量级，其他值 = null */
    public static Integer tierValue(Object v) {
        int t;
        if (v instanceof Number n) {
            t = n.intValue();
        } else {
            try {
                t = Integer.parseInt(Objects.toString(v, "").trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return t >= 1 && t <= 5 ? t : null;
    }

    /** 素材的量级（没标 = null） */
    public static Integer tierOf(Material m) {
        return m.getProfile() == null ? null : tierValue(m.getProfile().get("tier"));
    }

    /** 素材首次出现在原书的位置 0–1（没有 = null） */
    public static Double bookPosOf(Material m) {
        return m.getProfile() != null && m.getProfile().get("bookPos") instanceof Number n ? n.doubleValue() : null;
    }

    /** 保留 / 取消保留 */
    public Material setPinned(Long id, boolean pinned) {
        get(id);
        materialMapper.update(null, new LambdaUpdateWrapper<Material>().eq(Material::getId, id)
                .set(Material::getPinned, pinned).set(Material::getUpdateTime, LocalDateTime.now()));
        return get(id);
    }

    /**
     * 来源书列表 [{book, count, pinned}]：book 为 null 表示手动添加；按素材数倒序。
     * 待确认候选也按书统计（pending），方便看到「这本书还有多少候选没处理」。
     */
    public List<Map<String, Object>> sources() {
        Map<String, long[]> stats = new LinkedHashMap<>();
        for (Map<String, Object> row : materialMapper.selectMaps(new QueryWrapper<Material>()
                .select("source_book", "COUNT(*) AS cnt", "SUM(CASE WHEN pinned = 1 THEN 1 ELSE 0 END) AS pinned_cnt")
                .groupBy("source_book").orderByDesc("cnt"))) {
            Object book = row.get("source_book");
            stats.put(book == null ? null : String.valueOf(book),
                    new long[]{((Number) row.get("cnt")).longValue(), row.get("pinned_cnt") == null ? 0 : ((Number) row.get("pinned_cnt")).longValue(), 0});
        }
        for (MaterialCandidate c : candidateMapper.selectList(new LambdaQueryWrapper<MaterialCandidate>()
                .select(MaterialCandidate::getFileName).eq(MaterialCandidate::getStatus, MaterialCandidate.PENDING))) {
            String book = bookOf(c.getFileName());
            if (book != null) {
                stats.computeIfAbsent(book, k -> new long[3])[2]++;
            }
        }
        List<Map<String, Object>> out = new ArrayList<>();
        stats.forEach((book, s) -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("book", book);
            item.put("count", s[0]);
            item.put("pinned", s[1]);
            item.put("pending", s[2]);
            out.add(item);
        });
        return out;
    }

    /**
     * 按来源书删除：删除该书所有<b>未保留</b>的素材；withCandidates = true 时同时忽略该书的待确认候选。
     * → {deleted, kept（保留而未删的）, candidatesIgnored}
     */
    /** 删除提取工作区用：这次提取的素材候选数（不分状态） */
    public long countCandidatesOfExtract(Long extractId) {
        return candidateMapper.selectCount(new LambdaQueryWrapper<MaterialCandidate>().eq(MaterialCandidate::getExtractId, extractId));
    }

    /** 删除提取工作区：删掉这次提取的全部素材候选（已保存进素材库的素材不动），返回删除条数 */
    @Transactional
    public int deleteCandidatesOfExtract(Long extractId) {
        return candidateMapper.delete(new LambdaQueryWrapper<MaterialCandidate>().eq(MaterialCandidate::getExtractId, extractId));
    }

    /** 某本来源书的素材数 → [全部, 其中标记保留的] */
    public long[] countBySource(String book) {
        if (book == null || book.isBlank()) {
            return new long[]{0, 0};
        }
        long total = materialMapper.selectCount(new LambdaQueryWrapper<Material>().eq(Material::getSourceBook, book));
        long pinned = materialMapper.selectCount(new LambdaQueryWrapper<Material>().eq(Material::getSourceBook, book)
                .eq(Material::getPinned, true));
        return new long[]{total, pinned};
    }

    @Transactional
    public Map<String, Object> deleteBySource(String book, boolean withCandidates) {
        String name = book == null ? "" : book.trim();
        if (name.isEmpty() || MANUAL_BOOK.equals(name)) {
            throw new BizException(400, "请选择要删除的来源书（手动添加的素材请逐条删除）");
        }
        List<Long> ids = materialMapper.selectObjs(new LambdaQueryWrapper<Material>().select(Material::getId)
                        .eq(Material::getSourceBook, name).and(w -> w.isNull(Material::getPinned).or().eq(Material::getPinned, false)))
                .stream().map(o -> ((Number) o).longValue()).toList();
        if (!ids.isEmpty()) {
            materialMapper.deleteBatchIds(ids);
            tagMapper.delete(new LambdaQueryWrapper<MaterialTag>().in(MaterialTag::getMaterialId, ids));
            candidateMapper.update(null, new LambdaUpdateWrapper<MaterialCandidate>()
                    .in(MaterialCandidate::getMaterialId, ids).set(MaterialCandidate::getMaterialId, null));
        }
        long kept = materialMapper.selectCount(new LambdaQueryWrapper<Material>().eq(Material::getSourceBook, name));
        int ignored = 0;
        if (withCandidates) {
            List<Long> pending = candidateMapper.selectList(new LambdaQueryWrapper<MaterialCandidate>()
                            .select(MaterialCandidate::getId, MaterialCandidate::getFileName)
                            .eq(MaterialCandidate::getStatus, MaterialCandidate.PENDING))
                    .stream().filter(c -> name.equals(bookOf(c.getFileName()))).map(MaterialCandidate::getId).toList();
            ignored = ignoreCandidates(pending);
        }
        log.info("按来源书《{}》删除素材 {} 条，保留 {} 条，忽略候选 {} 条", name, ids.size(), kept, ignored);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("deleted", ids.size());
        out.put("kept", kept);
        out.put("candidatesIgnored", ignored);
        return out;
    }

    @Transactional
    public void delete(Long id) {
        get(id);
        // 删除主条目 = 拆分：成员重新出现在素材库
        materialMapper.update(null, new LambdaUpdateWrapper<Material>().eq(Material::getMergedInto, id)
                .set(Material::getMergedInto, null));
        materialMapper.deleteById(id);
        tagMapper.delete(new LambdaQueryWrapper<MaterialTag>().eq(MaterialTag::getMaterialId, id));
        candidateMapper.update(null, new LambdaUpdateWrapper<MaterialCandidate>()
                .eq(MaterialCandidate::getMaterialId, id).set(MaterialCandidate::getMaterialId, null));
    }

    /** 素材被应用到写作设定后调用：使用次数 +1 */
    public void recordUse(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return;
        }
        materialMapper.update(null, new LambdaUpdateWrapper<Material>().in(Material::getId, ids)
                .setSql("use_count = use_count + 1"));
    }

    private void syncTags(Long materialId, List<String> tags) {
        tagMapper.delete(new LambdaQueryWrapper<MaterialTag>().eq(MaterialTag::getMaterialId, materialId));
        for (String t : tags) {
            MaterialTag mt = new MaterialTag();
            mt.setMaterialId(materialId);
            mt.setTag(t);
            tagMapper.insert(mt);
        }
    }

    // ------------------------------------------------------------------ 提取候选（待确认）

    /**
     * 提取任务成功后由 NovelExtractService 调用：把结果中的 materials 存为 PENDING 候选（同一任务内按 candidateId 去重）。
     */
    /** 候选生成结果：新增条数、因与同一本书已有候选 / 素材重复而跳过的条数 */
    public record CandidateStats(int created, int duplicates) {
    }

    /**
     * 提取结果里的素材 → 待确认候选。同一本书（{@link #bookOf} 归一后的来源书名）重复提取时，
     * 与这本书<b>还没处理的候选</b>或<b>已存的素材</b>同分类、同标题（去掉空白和标点后比较）的条目跳过，不再重复进候选箱。
     */
    public CandidateStats createCandidates(Long extractId, Long fileId, String fileName, JsonNode result) {
        JsonNode list = result.path("materials");
        if (!list.isArray() || list.isEmpty()) {
            return new CandidateStats(0, 0);
        }
        Set<String> seen = existingKeysOfBook(bookOf(fileName));
        int n = 0;
        int duplicates = 0;
        LocalDateTime now = LocalDateTime.now();
        for (JsonNode item : list) {
            String key = item.path("candidateId").asText("");
            String cat = item.path("category").asText("");
            String title = item.path("title").asText("").trim();
            if (key.isEmpty() || !CATEGORIES.containsKey(cat) || title.isEmpty()) {
                continue;
            }
            if (!seen.add(cat + "|" + normTitle(title))) {
                duplicates++;
                continue;
            }
            boolean exists = candidateMapper.selectCount(new LambdaQueryWrapper<MaterialCandidate>()
                    .eq(MaterialCandidate::getExtractId, extractId).eq(MaterialCandidate::getCandidateKey, key)) > 0;
            if (exists) {
                continue;
            }
            MaterialCandidate c = new MaterialCandidate();
            c.setExtractId(extractId);
            c.setFileId(fileId);
            c.setFileName(fileName);
            c.setCandidateKey(trimTo(key, 32));
            c.setCategory(cat);
            c.setTitle(trimTo(title, 100));
            c.setPayload(objectMapper.convertValue(item, Map.class));
            c.setStatus(MaterialCandidate.PENDING);
            c.setCreateTime(now);
            c.setUpdateTime(now);
            candidateMapper.insert(c);
            n++;
        }
        log.info("提取任务 {} 生成素材候选 {} 条，跳过与本书已有候选 / 素材重复的 {} 条", extractId, n, duplicates);
        return new CandidateStats(n, duplicates);
    }

    /** 这本书已有的「分类|归一化标题」：未处理的候选 + 已存素材（book 为空时只能精确到文件名，返回空集合） */
    private Set<String> existingKeysOfBook(String book) {
        Set<String> keys = new java.util.HashSet<>();
        if (book == null) {
            return keys;
        }
        for (MaterialCandidate c : candidateMapper.selectList(new LambdaQueryWrapper<MaterialCandidate>()
                .select(MaterialCandidate::getId, MaterialCandidate::getFileName, MaterialCandidate::getCategory,
                        MaterialCandidate::getTitle)
                .eq(MaterialCandidate::getStatus, MaterialCandidate.PENDING))) {
            if (book.equals(bookOf(c.getFileName()))) {
                keys.add(c.getCategory() + "|" + normTitle(c.getTitle()));
            }
        }
        for (Material m : materialMapper.selectList(new LambdaQueryWrapper<Material>()
                .select(Material::getId, Material::getCategory, Material::getTitle)
                .eq(Material::getSourceBook, book))) {
            keys.add(m.getCategory() + "|" + normTitle(m.getTitle()));
        }
        return keys;
    }

    /** 与 python-service/app/materials.py#_norm_title 同口径：去空白和常见标点、小写 */
    private static final java.util.regex.Pattern TITLE_NOISE =
            java.util.regex.Pattern.compile("[\\s·・,，。、:：\"'“”《》（）()]+");

    static String normTitle(String title) {
        return title == null ? "" : TITLE_NOISE.matcher(title).replaceAll("").toLowerCase(java.util.Locale.ROOT);
    }

    /** 候选列表；库中已有同分类同名素材时填充 duplicateOf 提示可能重复 */
    public List<MaterialCandidate> candidates(String status, Long extractId) {
        LambdaQueryWrapper<MaterialCandidate> q = new LambdaQueryWrapper<MaterialCandidate>()
                .eq(MaterialCandidate::getStatus, status == null || status.isBlank() ? MaterialCandidate.PENDING : status)
                .eq(extractId != null, MaterialCandidate::getExtractId, extractId)
                .orderByDesc(MaterialCandidate::getCreateTime).orderByAsc(MaterialCandidate::getId)
                .last("LIMIT 500");
        List<MaterialCandidate> list = candidateMapper.selectList(q);
        if (!list.isEmpty()) {
            Set<String> titles = list.stream().map(MaterialCandidate::getTitle).collect(Collectors.toSet());
            Map<String, Long> existing = new LinkedHashMap<>();
            for (Material m : materialMapper.selectList(new LambdaQueryWrapper<Material>()
                    .select(Material::getId, Material::getCategory, Material::getTitle).in(Material::getTitle, titles))) {
                existing.put(m.getCategory() + "|" + m.getTitle(), m.getId());
            }
            list.forEach(c -> c.setDuplicateOf(existing.get(c.getCategory() + "|" + c.getTitle())));
        }
        return list;
    }

    /** 各提取任务还没确认的候选数 {extractId: n}（没有待确认候选的任务不在里面） */
    public Map<Long, Long> pendingCountsByExtract() {
        Map<Long, Long> out = new LinkedHashMap<>();
        for (Map<String, Object> row : candidateMapper.selectMaps(new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<MaterialCandidate>()
                .select("extract_id AS eid", "COUNT(*) AS n").eq("status", MaterialCandidate.PENDING).groupBy("extract_id"))) {
            if (row.get("eid") instanceof Number eid && row.get("n") instanceof Number n) {
                out.put(eid.longValue(), n.longValue());
            }
        }
        return out;
    }

    public long pendingCount() {
        return candidateMapper.selectCount(new LambdaQueryWrapper<MaterialCandidate>()
                .eq(MaterialCandidate::getStatus, MaterialCandidate.PENDING));
    }

    /**
     * 确认保存：每项可带用户修改后的内容（分类 / 名称 / 概括 / 属性 / 标签 / 备注），未提供的字段沿用候选。
     */
    @Transactional
    public List<Material> saveCandidates(List<Map<String, Object>> items) {
        List<Material> saved = new ArrayList<>();
        for (Map<String, Object> edit : items) {
            Long id = ((Number) edit.get("id")).longValue();
            MaterialCandidate c = candidateMapper.selectById(id);
            if (c == null || !MaterialCandidate.PENDING.equals(c.getStatus())) {
                continue;
            }
            Map<String, Object> p = new LinkedHashMap<>(c.getPayload());
            p.putAll(edit);
            Material m = new Material();
            m.setCategory(String.valueOf(p.getOrDefault("category", c.getCategory())));
            m.setSubtype(str(p.get("subtype")));
            m.setTitle(str(p.getOrDefault("title", c.getTitle())));
            m.setSummary(str(p.get("summary")));
            m.setAttributes(p.get("attributes") instanceof Map<?, ?> a ? objectMapper.convertValue(a, Map.class) : Map.of());
            m.setDetail(str(p.get("detail")));
            m.setTags(p.get("tags") instanceof List<?> t ? t.stream().map(String::valueOf).toList() : List.of());
            Map<String, Object> source = new LinkedHashMap<>();
            source.put("type", "extract");
            source.put("extractId", c.getExtractId());
            source.put("fileId", c.getFileId());
            source.put("fileName", c.getFileName());
            source.put("chapters", p.getOrDefault("chapters", List.of()));
            source.put("excerpt", str(p.get("excerpt")));
            if (p.get("facts") instanceof List<?> facts && !facts.isEmpty()) {
                source.put("facts", facts); // 新版提取：每条事实 + 原文依据 + 章节
            }
            m.setSource(source);
            Map<String, Object> profile = new LinkedHashMap<>();
            if (tierValue(p.get("tier")) != null) {
                profile.put("tier", tierValue(p.get("tier")));
                profile.put("tierReason", "整理卡片时标注");
            }
            if (p.get("bookPos") instanceof Number pos) {
                profile.put("bookPos", pos.doubleValue());
            }
            if (!profile.isEmpty()) {
                m.setProfile(profile);
            }
            Material created = save(m);
            candidateMapper.update(null, new LambdaUpdateWrapper<MaterialCandidate>().eq(MaterialCandidate::getId, id)
                    .set(MaterialCandidate::getStatus, MaterialCandidate.SAVED)
                    .set(MaterialCandidate::getMaterialId, created.getId())
                    .set(MaterialCandidate::getUpdateTime, LocalDateTime.now()));
            saved.add(created);
        }
        return saved;
    }

    /**
     * 卡片内容 → 还没保存的素材（来源 = 这次提取；事实、章节、原文摘录进 source，量级 / 书中位置进 profile）。
     */
    public Material fromCard(Map<String, Object> p, Long extractId, Long fileId, String fileName) {
        Material m = new Material();
        m.setCategory(String.valueOf(p.get("category")));
        m.setSubtype(str(p.get("subtype")));
        m.setTitle(str(p.get("title")));
        m.setSummary(str(p.get("summary")));
        m.setAttributes(p.get("attributes") instanceof Map<?, ?> a ? objectMapper.convertValue(a, Map.class) : Map.of());
        m.setDetail(str(p.get("detail")));
        m.setTags(p.get("tags") instanceof List<?> t ? t.stream().map(String::valueOf).toList() : List.of());
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("type", "extract");
        source.put("extractId", extractId);
        source.put("fileId", fileId);
        source.put("fileName", fileName);
        source.put("chapters", p.getOrDefault("chapters", List.of()));
        source.put("excerpt", str(p.get("excerpt")));
        if (p.get("facts") instanceof List<?> facts && !facts.isEmpty()) {
            source.put("facts", facts);
        }
        m.setSource(source);
        Map<String, Object> profile = new LinkedHashMap<>();
        if (tierValue(p.get("tier")) != null) {
            profile.put("tier", tierValue(p.get("tier")));
            profile.put("tierReason", "整理卡片时标注");
        }
        if (p.get("bookPos") instanceof Number pos) {
            profile.put("bookPos", pos.doubleValue());
        }
        if (!profile.isEmpty()) {
            m.setProfile(profile);
        }
        return m;
    }

    /**
     * 「更新已有」：把新卡片并进库里已有的素材 —— 属性只补没有的 / 空的键，概括 / 详细 / 细分类型只在原来为空时填，
     * 标签取并集（≤12），事实和章节追加没有的（事实按原文依据去重，≤40）。名称、分类、量级不动。
     */
    @Transactional
    @SuppressWarnings("unchecked")
    public Material mergeInto(Long targetId, Material incoming) {
        Material t = get(targetId);
        Map<String, Object> attrs = new LinkedHashMap<>(t.getAttributes() == null ? Map.of() : t.getAttributes());
        if (incoming.getAttributes() != null) {
            incoming.getAttributes().forEach((k, v) -> {
                Object old = attrs.get(k);
                if (old == null || String.valueOf(old).isBlank()) {
                    attrs.put(k, v);
                }
            });
        }
        Material req = new Material();
        req.setId(t.getId());
        req.setCategory(t.getCategory());
        req.setSubtype(isBlank(t.getSubtype()) ? incoming.getSubtype() : t.getSubtype());
        req.setTitle(t.getTitle());
        req.setSummary(isBlank(t.getSummary()) ? incoming.getSummary() : t.getSummary());
        req.setDetail(isBlank(t.getDetail()) ? incoming.getDetail() : t.getDetail());
        req.setAttributes(attrs);
        List<String> tags = new ArrayList<>(t.getTags() == null ? List.of() : t.getTags());
        if (incoming.getTags() != null) {
            incoming.getTags().stream().filter(x -> !tags.contains(x)).forEach(tags::add);
        }
        req.setTags(tags.size() > 12 ? new ArrayList<>(tags.subList(0, 12)) : tags);
        Material saved = save(req);
        // 来源：补事实 / 章节（save 不改 source，单独更新）
        Map<String, Object> src = new LinkedHashMap<>(t.getSource() == null ? Map.of() : t.getSource());
        Map<String, Object> in = incoming.getSource() == null ? Map.of() : incoming.getSource();
        List<Object> facts = new ArrayList<>(src.get("facts") instanceof List<?> l ? (List<Object>) l : List.of());
        Set<String> quotes = new java.util.HashSet<>();
        facts.forEach(f -> quotes.add(f instanceof Map<?, ?> fm ? String.valueOf(fm.get("quote")) : String.valueOf(f)));
        if (in.get("facts") instanceof List<?> nf) {
            for (Object f : nf) {
                String q = f instanceof Map<?, ?> fm ? String.valueOf(fm.get("quote")) : String.valueOf(f);
                if (facts.size() < 40 && quotes.add(q)) {
                    facts.add(f);
                }
            }
        }
        if (!facts.isEmpty()) {
            src.put("facts", facts);
        }
        List<Object> chapters = new ArrayList<>(src.get("chapters") instanceof List<?> l ? (List<Object>) l : List.of());
        if (in.get("chapters") instanceof List<?> nc) {
            nc.stream().filter(ch -> !chapters.contains(ch)).forEach(chapters::add);
        }
        src.put("chapters", chapters.size() > 80 ? new ArrayList<>(chapters.subList(0, 80)) : chapters);
        updateSource(t.getId(), src);
        return saved;
    }

    /**
     * 「作为可选版本」：新卡片存成一条素材，挂到库里已有的那条下面 —— 已有的是合并主条目（或它的成员）就加进主条目的版本；
     * 否则新建一个同书的主条目（共性 = 已有那条的名称 / 概括），已有的和新的都成为它的可选版本（同精炼合并）。→ 主条目
     */
    @Transactional
    @SuppressWarnings("unchecked")
    public Material attachVersion(Long targetId, Material incoming) {
        Material target = get(targetId);
        if (target.getMergedInto() != null) {
            target = get(target.getMergedInto());
        }
        Material created = save(incoming);
        if (isMergeMaster(target)) {
            Map<String, Object> src = new LinkedHashMap<>(target.getSource());
            List<Object> members = new ArrayList<>(src.get("members") instanceof List<?> l ? (List<Object>) l : List.of());
            members.add(created.getId());
            List<Object> variants = new ArrayList<>(src.get("variants") instanceof List<?> l ? (List<Object>) l : List.of());
            variants.add(variantOf(created));
            src.put("members", members);
            src.put("variants", variants);
            updateSource(target.getId(), src);
            materialMapper.update(null, new LambdaUpdateWrapper<Material>().eq(Material::getId, created.getId())
                    .set(Material::getMergedInto, target.getId()));
            return get(target.getId());
        }
        Material master = new Material();
        master.setCategory(target.getCategory());
        master.setTitle(target.getTitle());
        master.setSubtype("");
        master.setSummary(target.getSummary());
        master.setDetail("");
        master.setAttributes(Map.of());
        List<String> tags = new ArrayList<>(target.getTags() == null ? List.of() : target.getTags());
        master.setTags(tags.size() > 8 ? new ArrayList<>(tags.subList(0, 8)) : tags);
        master.setSourceBook(target.getSourceBook() == null ? MANUAL_BOOK : target.getSourceBook());
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("type", "merge");
        source.put("members", List.of(target.getId(), created.getId()));
        source.put("books", target.getSourceBook() == null ? List.of() : List.of(target.getSourceBook()));
        source.put("variants", List.of(variantOf(target), variantOf(created)));
        master.setSource(source);
        Material saved = save(master);
        materialMapper.update(null, new LambdaUpdateWrapper<Material>().in(Material::getId, target.getId(), created.getId())
                .set(Material::getMergedInto, saved.getId()));
        return get(saved.getId());
    }

    private void updateSource(Long id, Map<String, Object> source) {
        Material patch = new Material();
        patch.setId(id);
        patch.setSource(source);
        patch.setUpdateTime(LocalDateTime.now());
        materialMapper.updateById(patch);
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private static Map<String, Object> variantOf(Material m) {
        Map<String, Object> v = new LinkedHashMap<>();
        v.put("id", m.getId());
        v.put("book", Objects.toString(m.getSourceBook(), ""));
        v.put("title", m.getTitle());
        v.put("label", "");
        v.put("note", "");
        return v;
    }

    /** 这本书（来源书）的素材：「分类|归一化标题」→ 那条素材（id / 标题 / mergedInto） */
    public Map<String, Material> titleIndexOfBook(String book) {
        Map<String, Material> out = new LinkedHashMap<>();
        if (book == null) {
            return out;
        }
        for (Material m : materialMapper.selectList(new LambdaQueryWrapper<Material>()
                .select(Material::getId, Material::getCategory, Material::getTitle, Material::getMergedInto)
                .eq(Material::getSourceBook, book).orderByAsc(Material::getId))) {
            out.putIfAbsent(m.getCategory() + "|" + normTitle(m.getTitle()), m);
        }
        return out;
    }

    public int ignoreCandidates(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return 0;
        }
        return candidateMapper.update(null, new LambdaUpdateWrapper<MaterialCandidate>()
                .in(MaterialCandidate::getId, ids).eq(MaterialCandidate::getStatus, MaterialCandidate.PENDING)
                .set(MaterialCandidate::getStatus, MaterialCandidate.IGNORED)
                .set(MaterialCandidate::getUpdateTime, LocalDateTime.now()));
    }

    // ------------------------------------------------------------------ 工具

    /** 文件名里的网站标记，如「[lunarora.com]」「【www.xx.net】」 */
    private static final java.util.regex.Pattern SITE_TAG =
            java.util.regex.Pattern.compile("[\\[【(（][^\\]】)）]*\\.[A-Za-z]{2,}[^\\]】)）]*[\\]】)）]");
    /** 重复上传 / 下载产生的副本后缀，如「 (1)」「（2）」「 - 副本」 */
    private static final java.util.regex.Pattern COPY_SUFFIX =
            java.util.regex.Pattern.compile("(\\s*[(（]\\d{1,3}[)）]|\\s*-\\s*副本)+$");

    /**
     * 文件名 → 来源书名：去掉目录、扩展名、书名号、网站标记与副本后缀，空白返回 null。
     * 如「三体.txt」→「三体」、「三体全集[lunarora.com].txt」→「三体全集」、「谋杀案 (1) (1).txt」→「谋杀案」。
     */
    public static String bookOf(String fileName) {
        if (fileName == null || fileName.isBlank()) {
            return null;
        }
        String name = fileName.replace('\\', '/');
        name = name.substring(name.lastIndexOf('/') + 1);
        int dot = name.lastIndexOf('.');
        if (dot > 0) {
            name = name.substring(0, dot);
        }
        String cleaned = COPY_SUFFIX.matcher(SITE_TAG.matcher(name).replaceAll("")).replaceAll("").trim();
        name = cleaned.isEmpty() ? name.trim() : cleaned;
        if (name.startsWith("《") && name.endsWith("》") && name.length() > 2) {
            name = name.substring(1, name.length() - 1).trim();
        }
        return name.isEmpty() ? null : trimTo(name, 100);
    }

    private static String checkCategory(String category) {
        if (category == null || !CATEGORIES.containsKey(category)) {
            throw new BizException(400, "素材分类无效：" + category + "（可选 " + String.join(" / ", CATEGORIES.keySet()) + "）");
        }
        return category;
    }

    /** 去空白、全角转半角、去重，最多 12 个、每个 ≤ 32 字 */
    private static List<String> normalizeTags(List<String> tags) {
        if (tags == null) {
            return List.of();
        }
        Set<String> out = new LinkedHashSet<>();
        for (String t : tags) {
            if (t == null) {
                continue;
            }
            StringBuilder sb = new StringBuilder();
            for (char ch : t.trim().toCharArray()) {
                sb.append(ch >= 0xFF01 && ch <= 0xFF5E ? (char) (ch - 0xFEE0) : ch == 0x3000 ? ' ' : ch);
            }
            String v = sb.toString().trim();
            if (!v.isEmpty()) {
                out.add(v.length() > 32 ? v.substring(0, 32) : v);
            }
            if (out.size() >= 12) {
                break;
            }
        }
        return new ArrayList<>(out);
    }

    private static String trimTo(String s, int max) {
        if (s == null) {
            return null;
        }
        String t = s.trim();
        return t.length() > max ? t.substring(0, max) : t;
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }
}
