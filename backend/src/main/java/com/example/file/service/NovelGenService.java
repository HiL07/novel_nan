package com.example.file.service;

import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.Material;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Supplier;
import java.util.regex.Pattern;

/**
 * 小说生成（大模型工作区）：前端把「开始生成」发到这里，附上「模型配置」中启用且已验证的模型（含 API Key）后转发给
 * Python /api/gen/novels/{id}/chapters。Key 只经过 Java → Python，Python 只在本次任务内存中使用。
 * AI 构思（书名 / 大纲 / 下一章）也经这里：Java 另外附上从素材库取出的素材（选中的 + 可选的 AI 语义匹配）。
 * 其余生成接口（工作区、预览、任务进度、润色）不涉及 Key，前端直接调用 Python。
 */
@Service
public class NovelGenService {

    private static final Logger log = LoggerFactory.getLogger(NovelGenService.class);
    private static final Pattern NOVEL_ID = Pattern.compile("[A-Za-z0-9-]{1,64}");
    private static final List<String> CHAPTER_FIELDS = List.of("goal", "title", "targetChars");
    private static final List<String> POLISH_FIELDS = List.of("enabled", "baseId", "adapterId");
    private static final List<String> IDEA_KINDS = List.of("title", "outline", "chapter", "fill", "direction", "hint_polish", "chat");
    private static final int MAX_MATERIALS = 20;
    private static final int AUTO_MATERIALS = 8;
    /** 没有重排模型时，自动匹配只取最相关的几条（余弦相似度没有可比的阈值） */
    private static final int AUTO_UNRANKED = 3;
    private static final int DETAIL_CHARS = 300;
    private static final int TONE_CHARS = 200;
    private static final int MAX_REJECTED = 30;
    private static final int MAX_CHOSEN = 10;
    private static final int DIRECTION_CHARS = 300;
    private static final int QUERY_CHARS = 500;

    private final AiModelConfigService modelService;
    private final MaterialService materialService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;

    public NovelGenService(AiModelConfigService modelService, MaterialService materialService,
                           AiServiceClient aiClient, ObjectMapper objectMapper) {
        this.modelService = modelService;
        this.materialService = materialService;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    /** 返回 Python 的任务对象（data）。只转发白名单字段。 */
    public JsonNode startChapter(String novelId, Map<String, Object> req) {
        checkNovelId(novelId);
        AiModelConfig cfg = modelService.requireActive();
        Map<String, Object> body = new HashMap<>();
        for (String k : CHAPTER_FIELDS) {
            if (req.get(k) != null) {
                body.put(k, req.get(k));
            }
        }
        if (req.get("polish") instanceof Map<?, ?> polish) {
            Map<String, Object> p = new HashMap<>();
            for (String k : POLISH_FIELDS) {
                if (polish.get(k) != null) {
                    p.put(k, polish.get(k));
                }
            }
            body.put("polish", p);
        }
        return callPython(() -> aiClient.startGenChapter(novelId, body, cfg), "章节生成");
    }

    /** 大模型工作区：已完成章节重新提取故事事实（digest）/ 重新检查一致性（review）。返回 Python 的任务对象。 */
    public JsonNode recheckChapter(String novelId, int index, Map<String, Object> req) {
        checkNovelId(novelId);
        if (index < 1) {
            throw new BizException(400, "章节序号无效");
        }
        AiModelConfig cfg = modelService.requireActive();
        Map<String, Object> body = new HashMap<>();
        body.put("digest", Boolean.TRUE.equals(req.get("digest")));
        body.put("review", Boolean.TRUE.equals(req.get("review")));
        return callPython(() -> aiClient.recheckGenChapter(novelId, index, body, cfg), "重新提取");
    }

    /**
     * AI 构思 / AI 填写设定 / 构思方向建议 / 角色试聊。
     * req: {kind: title|outline|chapter|fill|direction|hint_polish|chat, source?: api|local, baseId?, adapterId?, hint?, tone?,
     *       rejected?[], chosenDirections?[], chapterContext?{current, past}, count?, purpose?,
     *       materialIds?[], autoMaterials?, query?, excludeBooks?[], fill?{mode, path, fields, current, itemLabel, count, existing},
     *       chat?{character:{name, card}, messages[], scene?, userRole?}, spec?}
     * source=api（默认）用「模型配置」中启用的大模型；local 用本地基础模型 + 可选适配器（Python 按需加载）；
     * gguf 用 Python「llama.cpp」页正在运行的 GGUF 模型（本机、无 Key，Python 自己取地址）。
     * autoMaterials：用 query（为空时用 hint）在素材库做 AI 语义检索（总是用大模型），取相关度 ≥ 50 的前 8 条，与选中的合并。
     * tone：作者定下的基调（≤200 字，所有构思都围绕它）；rejected：已给过 / 被拒绝的走向（≤30 条，生成走向时避开）；
     * chosenDirections：作者选定的后续走向（≤10 条，书名 / 大纲 / 章节沿着它们展开）；hint_polish：只按 hint 扩写构思。
     * excludeBooks：屏蔽这些来源书的素材（选中的和自动匹配的都去掉；「保留」的素材不受影响）。
     * 返回 Python 的结果 + usedMaterials（实际提供给模型的素材）+ blockedMaterials（因屏蔽被去掉的选中素材数）。
     */
    public Map<String, Object> ideas(String novelId, Map<String, Object> req) {
        checkNovelId(novelId);
        String kind = Objects.toString(req.get("kind"), "");
        if (!IDEA_KINDS.contains(kind)) {
            throw new BizException(400, "kind 只能是 " + IDEA_KINDS);
        }
        String source = Objects.toString(req.get("source"), "api");
        if ("remote".equals(source)) {
            throw new BizException(400, "远程模型（远程 GPU 上的模型 + 适配器）暂未接入");
        }
        boolean local = "local".equals(source);
        boolean gguf = "gguf".equals(source);
        String baseId = Objects.toString(req.get("baseId"), "");
        if (local && baseId.isBlank()) {
            throw new BizException(400, "请选择本地基础模型");
        }
        AiModelConfig cfg = local || gguf ? null : modelService.requireActive();
        String hint = Objects.toString(req.get("hint"), "").trim();

        List<String> excludeBooks = new ArrayList<>();
        if (req.get("excludeBooks") instanceof List<?> list) {
            for (Object o : list) {
                if (o != null && !String.valueOf(o).isBlank()) {
                    excludeBooks.add(String.valueOf(o).trim());
                }
            }
        }
        Map<Long, Map<String, Object>> used = new LinkedHashMap<>();
        List<Long> ids = new ArrayList<>();
        if (req.get("materialIds") instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Number n) {
                    ids.add(n.longValue());
                }
            }
        }
        List<Material> picked = materialService.listByIds(ids.stream().limit(MAX_MATERIALS).toList());
        List<Material> allowed = materialService.withoutBlocked(picked, excludeBooks);
        for (Material m : allowed) {
            used.put(m.getId(), usedEntry(m, null, "", false));
        }
        // 多版本素材（合并而来的主条目）怎么用：auto = 让 AI 选一个版本（默认）、blend = 融合、成员 id = 只用这个版本
        Map<Long, String> variantChoice = new HashMap<>();
        if (req.get("materialVariants") instanceof Map<?, ?> mv) {
            mv.forEach((k, v) -> {
                try {
                    variantChoice.put(Long.parseLong(String.valueOf(k)), String.valueOf(v));
                } catch (NumberFormatException ignored) {
                    // 不是素材 id：忽略
                }
            });
        }
        if (Boolean.TRUE.equals(req.get("autoMaterials"))) {
            String query = Objects.toString(req.get("query"), "").trim();
            if (query.isEmpty()) {
                query = hint;
            }
            if (query.length() > QUERY_CHARS) {  // 构思方向可能很长，语义检索只取开头
                query = query.substring(0, QUERY_CHARS);
            }
            if (query.isEmpty()) {
                throw new BizException(400, "自动匹配素材需要填写构思方向（用它在素材库中检索）");
            }
            // 本地检索（向量 + 关键词融合 + 重排），不用大模型。重排过：相关度 ≥ RERANK_MIN_SCORE 的才用；
            // 没有重排模型时分数没有可比的阈值，只取最相关的 AUTO_UNRANKED 条
            Map<String, Object> found = materialService.vectorSearch(query, null, null, excludeBooks, null, AUTO_MATERIALS);
            boolean reranked = Boolean.TRUE.equals(found.get("reranked"));
            String how = reranked ? "本地检索 · 重排相关度 " : "本地检索 · 未重排，按排名取前 " + AUTO_UNRANKED + " 条，相似度 ";
            int taken = 0;
            if (found.get("results") instanceof List<?> list) {
                for (Object o : list) {
                    if (o instanceof Map<?, ?> r && r.get("material") instanceof Material m && used.size() < MAX_MATERIALS
                            && r.get("score") instanceof Integer score
                            && (reranked ? score >= MaterialService.RERANK_MIN_SCORE : taken < AUTO_UNRANKED)) {
                        taken++;
                        if (used.putIfAbsent(m.getId(), usedEntry(m, score, how + score, true)) == null
                                && r.get("matchedVariant") instanceof Number variant) {
                            variantChoice.putIfAbsent(m.getId(), String.valueOf(variant.longValue()));
                            used.get(m.getId()).put("variant", r.get("matchedLabel"));
                        }
                    }
                }
            }
        }
        List<Map<String, Object>> materials = new ArrayList<>();
        for (Material m : materialService.listByIds(new ArrayList<>(used.keySet()))) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", m.getId());
            item.put("category", m.getCategory());
            item.put("subtype", Objects.requireNonNullElse(m.getSubtype(), ""));
            item.put("title", m.getTitle());
            String summary = Objects.requireNonNullElse(m.getSummary(), "");
            String detail = Objects.requireNonNullElse(m.getDetail(), "");
            item.put("summary", detail.isBlank() ? summary
                    : summary + "。" + (detail.length() > DETAIL_CHARS ? detail.substring(0, DETAIL_CHARS) : detail));
            item.put("attributes", Objects.requireNonNullElse(m.getAttributes(), Map.of()));
            item.put("tags", Objects.requireNonNullElse(m.getTags(), List.of()));
            if (MaterialService.isMergeMaster(m)) {
                addVariants(item, m, variantChoice.getOrDefault(m.getId(), "auto"));
            }
            materials.add(item);
        }

        Map<String, Object> body = new HashMap<>();
        body.put("kind", kind);
        body.put("hint", hint);
        if (req.get("count") instanceof Number n) {
            body.put("count", n.intValue());
        }
        body.put("materials", materials);
        if (req.get("tone") instanceof String tone && !tone.isBlank()) {
            String t = tone.trim();
            body.put("tone", t.length() > TONE_CHARS ? t.substring(0, TONE_CHARS) : t);
        }
        List<String> rejected = strings(req.get("rejected"), MAX_REJECTED, TONE_CHARS);
        if (!rejected.isEmpty()) {
            body.put("rejected", rejected);
        }
        List<String> chosen = strings(req.get("chosenDirections"), MAX_CHOSEN, DIRECTION_CHARS);
        if (!chosen.isEmpty()) {
            body.put("chosenDirections", chosen);
        }
        // 构思时带哪些已写章节：{current: 最近一章, past: 更早章节 + 前情概要}；不传则 Python 默认都带
        if (req.get("chapterContext") instanceof Map<?, ?> ctx) {
            body.put("chapterContext", Map.of("current", Boolean.TRUE.equals(ctx.get("current")),
                    "past", Boolean.TRUE.equals(ctx.get("past"))));
        }
        if (req.get("purpose") instanceof String purpose && !purpose.isBlank()) {
            body.put("purpose", purpose.length() > 60 ? purpose.substring(0, 60) : purpose);
        }
        // 设定编辑器当前（可能未保存的）设定，原样交给 Python 校验
        if (req.get("spec") instanceof List<?> spec) {
            body.put("spec", spec);
        }
        if ("fill".equals(kind)) {
            // 要填写的字段结构与位置
            if (!(req.get("fill") instanceof Map<?, ?> fill)) {
                throw new BizException(400, "缺少要填写的字段");
            }
            body.put("fill", fill);
        }
        if ("chat".equals(kind)) {
            if (!(req.get("chat") instanceof Map<?, ?> chat)) {
                throw new BizException(400, "缺少试聊内容");
            }
            body.put("chat", chat);
        }
        if (gguf) {
            body.put("gguf", true);
        }
        if (local) {
            Map<String, Object> localModel = new HashMap<>();
            localModel.put("baseId", baseId);
            localModel.put("adapterId", req.get("adapterId") instanceof String a && !a.isBlank() ? a : null);
            body.put("local", localModel);
        }
        JsonNode data = callPython(() -> aiClient.genIdeas(novelId, body, cfg), "AI 构思");
        @SuppressWarnings("unchecked")
        Map<String, Object> out = objectMapper.convertValue(data, LinkedHashMap.class);
        out.put("usedMaterials", new ArrayList<>(used.values()));
        out.put("blockedMaterials", picked.size() - allowed.size());
        return out;
    }

    /**
     * 多版本素材：附上各版本 {label, book, note, summary, attributes}（来自成员素材）和 variantMode：
     * auto（全部版本，让模型选一个）/ blend（全部版本，融合成新设定）/ fixed（只给选定的那一个版本）。
     */
    private void addVariants(Map<String, Object> item, Material master, String choice) {
        List<Material> members = materialService.membersOf(master.getId());
        String mode = "blend".equals(choice) ? "blend" : "auto";
        if (choice.matches("\\d+")) {
            long id = Long.parseLong(choice);
            List<Material> one = members.stream().filter(x -> x.getId() == id).toList();
            if (!one.isEmpty()) {
                members = one;
                mode = "fixed";
            }
        }
        List<Map<String, Object>> variants = new ArrayList<>();
        for (Material member : members) {
            Map<String, Object> v = new LinkedHashMap<>();
            v.put("label", MaterialService.variantLabel(master, member));
            v.put("book", Objects.requireNonNullElse(member.getSourceBook(), ""));
            v.put("note", Objects.toString(MaterialService.variantOf(master, member.getId()).get("note"), ""));
            v.put("summary", Objects.requireNonNullElse(member.getSummary(), ""));
            v.put("attributes", Objects.requireNonNullElse(member.getAttributes(), Map.of()));
            variants.add(v);
        }
        if (!variants.isEmpty()) {
            item.put("variants", variants);
            item.put("variantMode", mode);
        }
    }

    private static Map<String, Object> usedEntry(Material m, Integer score, String reason, boolean auto) {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("id", m.getId());
        e.put("category", m.getCategory());
        e.put("title", m.getTitle());
        e.put("score", score);
        e.put("reason", reason);
        e.put("auto", auto);
        return e;
    }

    private static void checkNovelId(String novelId) {
        if (novelId == null || !NOVEL_ID.matcher(novelId).matches()) {
            throw new BizException(400, "非法的工作区 id");
        }
    }

    /** 调 Python 生成接口：连接失败 → 503；Python 拒绝 → 400 + 它的 message；返回 data */
    private JsonNode callPython(Supplier<JsonNode> call, String what) {
        JsonNode res;
        try {
            res = call.get();
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达或响应超时，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            // 不记录响应体：FastAPI 的 422 会回显请求（含 API Key）
            log.warn("AI 服务拒绝{}请求，HTTP {}", what, e.getStatusCode().value());
            throw new BizException(400, pythonMessage(e));
        }
        if (res == null || res.path("code").asInt(-1) != 0) {
            throw new BizException(400, res == null ? "AI 服务无响应" : res.path("message").asText(what + "失败"));
        }
        return res.path("data");
    }

    /** 只取我们自己的 {message}；校验错误（422）的 detail 可能回显 Key，不透传 */
    private String pythonMessage(RestClientResponseException e) {
        if (e.getStatusCode().value() != 422) {
            try {
                JsonNode body = objectMapper.readTree(e.getResponseBodyAsString(StandardCharsets.UTF_8));
                if (body.hasNonNull("message")) {
                    return body.get("message").asText();
                }
            } catch (Exception ignored) {
                // 非 JSON 响应
            }
        }
        return "AI 服务拒绝请求（HTTP " + e.getStatusCode().value() + "）";
    }

    /** 请求里的字符串列表：去空白，最多 max 条，每条截到 chars 字 */
    private static List<String> strings(Object value, int max, int chars) {
        List<String> out = new ArrayList<>();
        if (value instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof String str && !str.isBlank() && out.size() < max) {
                    String t = str.trim();
                    out.add(t.length() > chars ? t.substring(0, chars) : t);
                }
            }
        }
        return out;
    }
}
