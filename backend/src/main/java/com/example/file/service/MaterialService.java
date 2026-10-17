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
    }

    private static final int SEMANTIC_POOL = 150;

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
                .select("category", "COUNT(*) AS cnt").groupBy("category"))) {
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
        Page<Material> pg = new Page<>(Math.max(page, 1), Math.min(Math.max(size, 1), 100));
        List<Long> tagIds = idsWithTags(tags, !"any".equalsIgnoreCase(tagMode));
        if (tagIds != null && tagIds.isEmpty()) {
            return pg;
        }
        LambdaQueryWrapper<Material> q = baseQuery(category, tagIds);
        if (keyword != null && !keyword.isBlank()) {
            for (String word : keyword.trim().split("\\s+")) {
                q.and(w -> w.like(Material::getTitle, word).or().like(Material::getSummary, word)
                        .or().like(Material::getSubtype, word).or().like(Material::getDetail, word)
                        .or().like(Material::getTags, word));
            }
        }
        q.orderByDesc(Material::getUpdateTime);
        return materialMapper.selectPage(pg, q);
    }

    private LambdaQueryWrapper<Material> baseQuery(String category, List<Long> ids) {
        LambdaQueryWrapper<Material> q = new LambdaQueryWrapper<>();
        if (category != null && !category.isBlank()) {
            q.eq(Material::getCategory, checkCategory(category));
        }
        if (ids != null) {
            q.in(Material::getId, ids);
        }
        return q;
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
        long total = tagIds != null && tagIds.isEmpty() ? 0 : materialMapper.selectCount(baseQuery(category, tagIds));
        List<Material> pool;
        if (total == 0) {
            pool = List.of();
        } else if (total <= SEMANTIC_POOL) {
            pool = materialMapper.selectList(baseQuery(category, tagIds));
        } else {
            LambdaQueryWrapper<Material> q = baseQuery(category, tagIds);
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

    private interface AiCall {
        JsonNode run();
    }

    private JsonNode callAi(AiCall call) {
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
            throw new BizException(502, "AI 语义检索失败：" + (res == null ? "无响应" : res.path("message").asText()));
        }
        return res;
    }

    // ------------------------------------------------------------------ 素材增删改

    public Material get(Long id) {
        Material m = materialMapper.selectById(id);
        if (m == null) {
            throw new BizException(404, "素材不存在：" + id);
        }
        return m;
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
        if (req.getId() == null) {
            m.setSource(req.getSource() == null ? Map.of("type", "manual") : req.getSource());
            m.setUseCount(0);
            m.setCreateTime(now);
            m.setUpdateTime(now);
            materialMapper.insert(m);
        } else {
            m.setUpdateTime(now);
            materialMapper.updateById(m);
        }
        syncTags(m.getId(), m.getTags());
        return m;
    }

    @Transactional
    public void delete(Long id) {
        get(id);
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
    public int createCandidates(Long extractId, Long fileId, String fileName, JsonNode result) {
        JsonNode list = result.path("materials");
        if (!list.isArray() || list.isEmpty()) {
            return 0;
        }
        int n = 0;
        LocalDateTime now = LocalDateTime.now();
        for (JsonNode item : list) {
            String key = item.path("candidateId").asText("");
            String cat = item.path("category").asText("");
            String title = item.path("title").asText("").trim();
            if (key.isEmpty() || !CATEGORIES.containsKey(cat) || title.isEmpty()) {
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
        log.info("提取任务 {} 生成素材候选 {} 条", extractId, n);
        return n;
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
            m.setSource(source);
            Material created = save(m);
            candidateMapper.update(null, new LambdaUpdateWrapper<MaterialCandidate>().eq(MaterialCandidate::getId, id)
                    .set(MaterialCandidate::getStatus, MaterialCandidate.SAVED)
                    .set(MaterialCandidate::getMaterialId, created.getId())
                    .set(MaterialCandidate::getUpdateTime, LocalDateTime.now()));
            saved.add(created);
        }
        return saved;
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
