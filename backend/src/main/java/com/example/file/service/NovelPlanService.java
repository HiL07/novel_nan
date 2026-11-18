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
 * 自动规划（设计见 docs/自动规划.md），故事优先（不依赖素材库）：写作参数 + 灵感（模型）→ 设定（世界 + 主角）
 * → 全书骨架 + 按骨架配人物 / 元素 → 写进工作区；素材点睛（按设定里的人物 / 元素本地检索 + 模型给建议）、
 * 10 章大纲、审稿的接口保留，暂不在界面流程里。原来的「素材优先」路线 2026-11-02 删掉了。
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

    /** 故事优先 ① {premise?, directions?, bookConfig?, tone?, conditions?, count?, materialIds?（架空版）, model} → {ideas[], usage, model} */
    public Map<String, Object> idea(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, false);
        body.put("directions", strings(req.get("directions")).stream().limit(12).toList());
        if (req.get("count") instanceof Number n) {
            body.put("count", Math.max(1, Math.min(5, n.intValue())));
        }
        // 「重新生成」：作者对之前几批灵感的反馈 {dislike, want, rejected[]}，全部带上（最多 10 条）
        List<Map<String, Object>> feedback = new ArrayList<>();
        if (req.get("feedback") instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map<?, ?> f && feedback.size() < 10) {
                    Map<String, Object> x = new LinkedHashMap<>();
                    x.put("dislike", trim(f.get("dislike"), 300));
                    x.put("want", trim(f.get("want"), 300));
                    x.put("rejected", strings(f.get("rejected")).stream().limit(10).map(s -> trim(s, 80)).toList());
                    feedback.add(x);
                }
            }
        }
        body.put("feedback", feedback);
        body.put("materials", portableMaterials(req));
        return python("idea", novelId, body, req.get("model"));
    }

    /** 参数这一步的小帮手 {kind: direction|style|conditions|premise|sellingPoint, text, premise?, conditions?, directions?, bookConfig?, materialIds?（架空版）, model} → {kind, value} */
    public Map<String, Object> assist(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, false);
        body.put("kind", trim(req.get("kind"), 20));
        body.put("text", trim(req.get("text"), 1000));
        body.put("directions", strings(req.get("directions")).stream().limit(12).toList());
        body.put("materials", portableMaterials(req));
        return python("assist", novelId, body, req.get("model"));
    }

    /**
     * 故事优先 ③ 全书骨架 {premise?, idea?, bookConfig?, settings?, volumePlan?[], volumeCount?, pace?, tone?, conditions?,
     * book?（有 = 往后追加卷）, regen?{index, instruction?}（= 只重新生成这一卷）, model} → {book, issues, stages, extended, regenerated, …}
     */
    public Map<String, Object> book(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, true);
        if (req.get("settings") instanceof Map<?, ?> m && !m.isEmpty()) {
            body.put("settings", m);
        }
        body.put("volumePlan", strings(req.get("volumePlan")).stream().limit(8).map(s -> trim(s, 200)).toList());
        if (req.get("volumeCount") instanceof Number n) {
            body.put("volumeCount", Math.max(0, Math.min(8, n.intValue())));
        }
        if (List.of("slow", "normal", "fast").contains(String.valueOf(req.get("pace")))) {
            body.put("pace", req.get("pace"));
        }
        if (req.get("regen") instanceof Map<?, ?> r && r.get("index") instanceof Number i) {
            body.put("regen", Map.of("index", i.intValue(), "instruction", trim(r.get("instruction"), 500)));
        }
        return python("book", novelId, body, req.get("model"));
    }

    /**
     * 故事优先 · 骨架这一步的人物与元素 {settings（世界 + 主角）, book（全书骨架）, premise?, idea?, bookConfig?, model}
     * → {characters（配角）, elements, stages, issues, usage, model}：登场章节和对手量级按骨架各阶段安排
     */
    public Map<String, Object> cast(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, false);
        body.put("settings", requireMap(req.get("settings"), "缺少设定"));
        if (!(body.get("book") instanceof Map)) {
            throw new BizException(400, "先生成全书骨架");
        }
        return python("cast", novelId, body, req.get("model"));
    }

    /**
     * 设定的单个模块重新生成 {settings, module, category?, direction?, keep?, premise?, idea?, bookConfig?, book?, model}
     * → {module, category, value, keep, usage, model}（四种方式：给不给方向 × 参考不参考已有）
     */
    public Map<String, Object> settingsPart(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, false);
        body.put("settings", requireMap(req.get("settings"), "缺少设定草案"));
        body.put("module", trim(req.get("module"), 20));
        body.put("category", trim(req.get("category"), 20));
        body.put("direction", trim(req.get("direction"), 500));
        body.put("keep", Boolean.TRUE.equals(req.get("keep")));
        return python("settings-part", novelId, body, req.get("model"));
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

    /** 设定（世界 + 主角）{premise?, idea?, bookConfig?, book?, tone?, conditions?, materialIds?, materialVariants?, model} → {draft, issues, …} */
    public Map<String, Object> settings(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, true);
        body.put("materials", materials(req));
        return python("settings", novelId, body, req.get("model"));
    }

    /** 10 章大纲 {premise?, idea?, bookConfig?, book?, settings, materialIds?, count?, model} → {outline, issues, bookStage, …} */
    public Map<String, Object> outline(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, true);
        body.put("settings", requireMap(req.get("settings"), "缺少设定草案"));
        body.put("materials", materials(req));
        if (req.get("count") instanceof Number n) {
            body.put("count", Math.max(3, Math.min(10, n.intValue())));
        }
        return python("outline", novelId, body, req.get("model"));
    }

    /** 审稿 {premise?, idea?, bookConfig?, book?, settings, outline, model} → {chapters[{index, problems, revised}], overall, codeIssues, …} */
    public Map<String, Object> review(String novelId, Map<String, Object> req) {
        Map<String, Object> body = story(req, true);
        body.put("settings", requireMap(req.get("settings"), "缺少设定草案"));
        body.put("outline", requireMap(req.get("outline"), "缺少大纲"));
        return python("review", novelId, body, req.get("model"));
    }

    private Map<String, Object> python(String action, String novelId, Map<String, Object> body, Object model) {
        NovelGenService.checkNovelId(novelId);
        body.put("novelId", novelId);
        return inspireService.callGen("/api/gen/plan/" + action, body, model);
    }

    /** 写作参数 / 选定的灵感 / 全书骨架原样转给 Python，Python 端清洗 */
    private static void storyFields(Map<String, Object> req, Map<String, Object> body) {
        for (String k : List.of("bookConfig", "idea", "book")) {
            if (req.get(k) instanceof Map<?, ?> m && !m.isEmpty()) {
                body.put(k, m);
            }
        }
    }

    /** 构思可以为空；requirePremise = 构思、选定的灵感、全书骨架（续规划）至少有一个 */
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

    /** 参数 · 灵感这一步只用架空版（原素材带着原作的人名地名） */
    private List<Map<String, Object>> portableMaterials(Map<String, Object> req) {
        return materials(req).stream().filter(m -> m.get("portable") != null).toList();
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
