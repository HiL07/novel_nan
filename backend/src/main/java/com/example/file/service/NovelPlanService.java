package com.example.file.service;

import com.example.file.common.BizException;
import com.example.file.entity.Material;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 自动规划（设计见 docs/自动规划.md），两条路线：
 * <ul>
 *   <li>故事优先（mode = story，不依赖素材库）：写作参数 + 灵感（模型）→ 全书骨架（模型）→ 设定（模型，从骨架推出）
 *       → 素材点睛（可选：按设定里的人物 / 元素本地检索 + 模型给建议）→ 10 章大纲 → 审稿；</li>
 *   <li>素材优先：一句构思 → 拆需求（模型）→ 选素材（本地检索，不花 token）→ 设定草案（模型，素材改编）
 *       → 10 章大纲 + 伏笔计划（模型）→ 审稿（模型）。</li>
 * </ul>
 * 只产出设定 / 大纲 / 计划伏笔，不写正文。
 * 模型调用在 Python（/api/gen/plan/**）；这里负责带模型配置、检索素材（复用灵感墙 {@link InspirationService#retrieveNeeds}）、
 * 组装素材条目（含多版本与量级，复用 {@link NovelGenService#materialItems}）。写进工作区的那一步不用模型，前端直接调 Python。
 */
@Service
public class NovelPlanService {

    /** 一次规划最多用多少条素材 */
    static final int MAX_MATERIALS = 24;
    static final int PREMISE_CHARS = 500;
    /** 点睛：最多检索多少个人物 / 元素，每个取几条素材 */
    static final int ENRICH_TARGETS = 12;
    static final int ENRICH_PER_TARGET = 2;
    /** 设定草案里能点睛的元素类别（顺序与 Python planner.enrich_targets 一致：人物在前，元素在后） */
    static final List<String> ELEMENT_KINDS = List.of("faction", "location", "item", "monster");

    private final InspirationService inspireService;
    private final NovelGenService genService;

    public NovelPlanService(InspirationService inspireService, NovelGenService genService) {
        this.inspireService = inspireService;
        this.genService = genService;
    }

    /** ① {premise, tone?, conditions?, stage?, model} → {summary, needs[], stage, opening, startIndex, usage, model} */
    public Map<String, Object> needs(String novelId, Map<String, Object> req) {
        return python("needs", novelId, base(req), req.get("model"));
    }

    /** 故事优先 ① {premise?, directions?, bookConfig?, tone?, conditions?, count?, model} → {ideas[], usage, model} */
    public Map<String, Object> idea(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, false);
        body.put("directions", strings(req.get("directions")).stream().limit(12).toList());
        if (req.get("count") instanceof Number n) {
            body.put("count", Math.max(1, Math.min(5, n.intValue())));
        }
        return python("idea", novelId, body, req.get("model"));
    }

    /** 故事优先 ② {premise?, idea?, bookConfig?, tone?, conditions?, book?（有 = 往后追加卷）, model} → {book, issues, extended, …} */
    public Map<String, Object> book(String novelId, Map<String, Object> req) {
        return python("book", novelId, story(req, true), req.get("model"));
    }

    /**
     * 故事优先 ④ 素材点睛 {settings, premise?, idea?, bookConfig?, excludeBooks?, stage?, model}：
     * 设定草案里的每个人物 / 元素当一条检索需求（本地检索，只要过相关度线的，每个最多 2 条），
     * 再让模型给逐条「补细节」建议 → {suggestions[], materials[{id, title, book, category}], searched, usage, model}。
     * 一条都没检索到时不调模型。
     */
    public Map<String, Object> enrich(String novelId, Map<String, Object> req) {
        NovelGenService.checkNovelId(novelId);
        Map<String, Object> draft = requireMap(req.get("settings"), "缺少设定草案");
        List<Map<String, Object>> needs = new ArrayList<>();
        int t = 0;
        if (draft.get("characters") instanceof List<?> cs) {
            for (Object o : cs) {
                if (o instanceof Map<?, ?> c && !trim(c.get("name"), 40).isEmpty()) {
                    t++;
                    String query = String.join(" ", trim(c.get("tagline"), 80), joined(c.get("abilities")), trim(c.get("goal"), 80)).trim();
                    needs.add(need("character", query.isEmpty() ? trim(c.get("name"), 40) : query, "T" + t));
                }
            }
        }
        if (draft.get("elements") instanceof List<?> es) {
            for (Object o : es) {
                if (o instanceof Map<?, ?> e && !trim(e.get("name"), 40).isEmpty()
                        && ELEMENT_KINDS.contains(String.valueOf(e.get("category")))) {
                    t++;
                    StringBuilder q = new StringBuilder(trim(e.get("name"), 40));
                    if (e.get("fields") instanceof Map<?, ?> f) {
                        for (Object v : f.values()) {
                            q.append(' ').append(joined(v));
                        }
                    }
                    needs.add(need(String.valueOf(e.get("category")), trim(q.toString(), 300), "T" + t));
                }
            }
        }
        if (needs.isEmpty()) {
            throw new BizException(400, "设定草案里没有人物或元素");
        }
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("needs", needs.stream().limit(ENRICH_TARGETS).toList());
        r.put("stage", req.get("stage"));
        r.put("explore", false);
        Map<String, Object> found = inspireService.retrieveNeeds(strings(req.get("excludeBooks")), List.of(), r);
        Map<String, List<String>> links = new LinkedHashMap<>();
        List<Long> ids = new ArrayList<>();
        if (found.get("groups") instanceof List<?> groups) {
            for (Object g : groups) {
                if (!(g instanceof Map<?, ?> gm) || !(gm.get("need") instanceof Map<?, ?> nm) || !(gm.get("items") instanceof List<?> items)) {
                    continue;
                }
                String target = String.valueOf(nm.get("target"));
                int taken = 0;
                for (Object it : items) {
                    if (taken >= ENRICH_PER_TARGET || !(it instanceof Map<?, ?> im) || !"search".equals(im.get("from"))
                            || !(im.get("material") instanceof Material m)) {
                        continue;
                    }
                    taken++;
                    if (!ids.contains(m.getId())) {
                        ids.add(m.getId());
                    }
                    links.computeIfAbsent(String.valueOf(m.getId()), k -> new ArrayList<>()).add(target);
                }
            }
        }
        if (ids.isEmpty()) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("suggestions", List.of());
            out.put("materials", List.of());
            out.put("searched", needs.size());
            return out;
        }
        List<Map<String, Object>> materials = inspireService.withStage(
                genService.materialItems(ids.stream().limit(MAX_MATERIALS).toList(), Map.of()), req.get("stage"));
        Map<String, Object> body = story(req, false);
        body.put("settings", draft);
        body.put("materials", materials);
        body.put("links", links);
        Map<String, Object> res = new LinkedHashMap<>(python("enrich", novelId, body, req.get("model")));
        List<Map<String, Object>> brief = new ArrayList<>();
        for (Map<String, Object> m : materials) {
            Map<String, Object> b = new LinkedHashMap<>();
            for (String k : List.of("id", "title", "book", "category")) {
                b.put(k, m.get(k));
            }
            brief.add(b);
        }
        res.put("materials", brief);
        res.put("searched", needs.size());
        return res;
    }

    private static Map<String, Object> need(String category, String query, String target) {
        Map<String, Object> n = new LinkedHashMap<>();
        n.put("category", category);
        n.put("query", query);
        n.put("count", ENRICH_PER_TARGET);
        n.put("target", target);
        n.put("why", "点睛");
        return n;
    }

    /** ② {needs, excludeBooks?, stage?} → 同灵感墙 retrieve 的 {groups, total, reranked, stage}（本地，不花 token） */
    public Map<String, Object> retrieve(String novelId, Map<String, Object> req) {
        NovelGenService.checkNovelId(novelId);
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("needs", req.get("needs"));
        r.put("stage", req.get("stage"));
        r.put("explore", false);
        r.put("relaxEmpty", true);   // 规划时一条需求没素材过阈值，就给最相关的 2 条（标「相关度低」）
        return inspireService.retrieveNeeds(strings(req.get("excludeBooks")), List.of(), r);
    }

    /** ③ {premise, tone?, conditions?, stage?, materialIds, materialVariants?, model} → {draft, issues, …} */
    public Map<String, Object> settings(String novelId, Map<String, Object> req) {
        Map<String, Object> body = base(req);
        storyFields(req, body);
        body.put("materials", materials(req));
        return python("settings", novelId, body, req.get("model"));
    }

    /** ④ {premise, tone?, settings, materialIds?, stage?, count?, model} → {outline, issues, …} */
    public Map<String, Object> outline(String novelId, Map<String, Object> req) {
        Map<String, Object> body = base(req);
        storyFields(req, body);
        body.put("settings", requireMap(req.get("settings"), "缺少设定草案"));
        body.put("materials", materials(req));
        if (req.get("count") instanceof Number n) {
            body.put("count", Math.max(3, Math.min(10, n.intValue())));
        }
        return python("outline", novelId, body, req.get("model"));
    }

    /** ⑤ {premise, tone?, settings, outline, stage?, model} → {chapters[{index, problems, revised}], overall, codeIssues, …} */
    public Map<String, Object> review(String novelId, Map<String, Object> req) {
        Map<String, Object> body = base(req);
        storyFields(req, body);
        body.put("settings", requireMap(req.get("settings"), "缺少设定草案"));
        body.put("outline", requireMap(req.get("outline"), "缺少大纲"));
        return python("review", novelId, body, req.get("model"));
    }

    private Map<String, Object> python(String action, String novelId, Map<String, Object> body, Object model) {
        NovelGenService.checkNovelId(novelId);
        body.put("novelId", novelId);
        return inspireService.callGen("/api/gen/plan/" + action, body, model);
    }

    /** 故事优先的字段（mode / 写作参数 / 选定的灵感 / 全书骨架）原样转给 Python，Python 端清洗 */
    private static void storyFields(Map<String, Object> req, Map<String, Object> body) {
        if ("story".equals(req.get("mode"))) {
            body.put("mode", "story");
        }
        for (String k : List.of("bookConfig", "idea", "book")) {
            if (req.get(k) instanceof Map<?, ?> m && !m.isEmpty()) {
                body.put(k, m);
            }
        }
    }

    /** 故事优先：构思可以为空；requirePremise = 要么有构思、要么有选定的灵感 */
    private static Map<String, Object> story(Map<String, Object> req, boolean requirePremise) {
        Map<String, Object> body = new LinkedHashMap<>();
        String premise = trim(req.get("premise"), PREMISE_CHARS);
        body.put("premise", premise);
        body.put("tone", trim(req.get("tone"), 200));
        body.put("conditions", trim(req.get("conditions"), PREMISE_CHARS));
        body.put("mode", "story");
        storyFields(req, body);
        if (requirePremise && premise.isEmpty() && !body.containsKey("idea") && !body.containsKey("book")) {
            throw new BizException(400, "先写一句构思，或者选一个灵感");
        }
        Map<String, Object> stage = InspirationService.stageBody(req.get("stage"));
        if (stage != null) {
            body.put("stage", stage);
        }
        return body;
    }

    private static String joined(Object v) {
        return v instanceof List<?> l ? String.join("、", l.stream().map(String::valueOf).toList()) : trim(v, 120);
    }

    /** 构思 / 基调 / 补充要求 / 阶段 + 故事优先字段；故事优先且选了灵感时构思可以为空 */
    private static Map<String, Object> base(Map<String, Object> req) {
        String premise = trim(req.get("premise"), PREMISE_CHARS);
        // 故事优先：选了灵感或已有全书骨架（续规划）时可以不写构思
        boolean storyBase = "story".equals(req.get("mode"))
                && (req.get("idea") instanceof Map<?, ?> i && !i.isEmpty() || req.get("book") instanceof Map<?, ?> b && !b.isEmpty());
        if (premise.isEmpty() && !storyBase) {
            throw new BizException(400, "请先写一句构思，比如「法师喜欢冒险」");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("premise", premise);
        body.put("tone", trim(req.get("tone"), 200));
        body.put("conditions", trim(req.get("conditions"), PREMISE_CHARS));
        Map<String, Object> stage = InspirationService.stageBody(req.get("stage"));
        if (stage != null) {
            body.put("stage", stage);
        }
        return body;
    }

    /** 选中的素材 → Python 素材条目（多版本 + 量级 / 阶段适配） */
    private List<Map<String, Object>> materials(Map<String, Object> req) {
        List<Long> ids = new ArrayList<>();
        if (req.get("materialIds") instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Number n && !ids.contains(n.longValue())) {
                    ids.add(n.longValue());
                }
            }
        }
        if (ids.isEmpty()) {
            return List.of();
        }
        Map<Long, String> variants = NovelGenService.parseVariants(req.get("materialVariants"));
        return inspireService.withStage(genService.materialItems(ids.stream().limit(MAX_MATERIALS).toList(), variants),
                req.get("stage"));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> requireMap(Object v, String message) {
        if (!(v instanceof Map<?, ?> m) || m.isEmpty()) {
            throw new BizException(400, message);
        }
        return (Map<String, Object>) m;
    }

    private static List<String> strings(Object v) {
        List<String> out = new ArrayList<>();
        if (v instanceof List<?> list) {
            for (Object o : list) {
                if (o != null && !String.valueOf(o).isBlank()) {
                    out.add(String.valueOf(o).trim());
                }
            }
        }
        return out;
    }

    private static String trim(Object v, int max) {
        String s = Objects.toString(v, "").trim();
        return s.length() > max ? s.substring(0, max) : s;
    }
}
