package com.example.file.service;

import com.example.file.entity.Material;

import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 素材和故事阶段合不合适（灵感墙检索、AI 构思自动匹配共用）。
 * <p>
 * 阶段 = {phase: opening|early|mid|late|any, tierMax 1–5}：主角现在能面对的对手量级上限。素材量级见 profile.tier
 * （1 个人 / 街头 … 5 神明 / 世界之外）。用途 role：opponent（对手 / 遭遇）/ scene / prop 受上限约束；
 * lore（背景传说）不限量级，但超出上限两级以上的算「远景」，一次检索最多 {@link #FAR_QUOTA} 条。
 * 没标量级的素材用原书出场位置（bookPos）兜底：开篇 / 前期时，原书后半段才出场的当作超一级。
 */
public final class StageFit {

    /** 一次检索里「远景」素材（超出上限 ≥2 级）最多几条 */
    public static final int FAR_QUOTA = 2;

    public static final String OK = "ok";            // 量级在上限内
    public static final String STRETCH = "stretch";  // 超一级：排在同组正常项后面
    public static final String FAR = "far";          // 超两级以上：只能作背景 / 传说
    public static final String UNKNOWN = "unknown";  // 没标量级、也没有出场位置

    public static final Set<String> ROLES = Set.of("opponent", "scene", "prop", "lore");
    private static final Set<String> EARLY = Set.of("opening", "early");

    private StageFit() {
    }

    /** 阶段；tierMax = null 表示不限（没关联工作区、作者也没选阶段） */
    public record Stage(String phase, Integer tierMax) {
        public boolean limited() {
            return tierMax != null;
        }
    }

    public static Stage of(Object stage) {
        if (!(stage instanceof Map<?, ?> m)) {
            return new Stage("any", null);
        }
        String phase = Objects.toString(m.get("phase"), "any");
        Integer max = MaterialService.tierValue(m.get("tierMax"));
        return new Stage(phase, "any".equals(phase) && max == null ? null : max);
    }

    public static String fit(Material m, Stage stage) {
        if (stage == null || !stage.limited()) {
            return OK;
        }
        Integer tier = MaterialService.tierOf(m);
        if (tier == null) {
            Double pos = MaterialService.bookPosOf(m);
            if (pos == null) {
                return UNKNOWN;
            }
            return EARLY.contains(stage.phase()) && pos > 0.5 ? STRETCH : OK;
        }
        if (tier <= stage.tierMax()) {
            return OK;
        }
        return tier == stage.tierMax() + 1 ? STRETCH : FAR;
    }

    /** 同组排序用：正常 < 没信息 < 超一级 < 远景 */
    public static int rank(String fit) {
        return switch (fit) {
            case OK -> 0;
            case UNKNOWN -> 1;
            case STRETCH -> 2;
            default -> 3;
        };
    }

    /** 这条需求的用途；没写时按分类猜：地点 = scene，物品功法 = prop，世界观 = lore，其余 = opponent（从严） */
    public static String role(Object v, String category) {
        String r = Objects.toString(v, "");
        if (ROLES.contains(r)) {
            return r;
        }
        return switch (Objects.toString(category, "")) {
            case "location" -> "scene";
            case "item" -> "prop";
            case "world" -> "lore";
            default -> "opponent";
        };
    }
}
