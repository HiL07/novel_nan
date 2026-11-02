package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.service.NovelPlanService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 自动规划（故事优先）：写作参数 + 灵感 → 设定 → 全书骨架 + 人物 / 元素（只产出规划，不写正文）；
 * 素材点睛 / 10 章大纲 / 审稿的接口保留。写进工作区由前端直接调 Python /api/gen/novels/{id}/plan/apply。
 */
@RestController
@RequestMapping("/api/novel/plan/{novelId}")
public class NovelPlanController {

    private static final Logger log = LoggerFactory.getLogger(NovelPlanController.class);

    private final NovelPlanService service;

    public NovelPlanController(NovelPlanService service) {
        this.service = service;
    }

    /** POST /api/novel/plan/{novelId}/idea {premise?, directions?, bookConfig?, tone?, conditions?, count?, model}（故事优先 ① 灵感） */
    @PostMapping("/idea")
    public ResponseEntity<Result<Map<String, Object>>> idea(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.idea(novelId, body), log, "生成灵感失败");
    }

    /** POST /api/novel/plan/{novelId}/book {premise?, idea?, bookConfig?, tone?, conditions?, book?, model}（故事优先 ② 全书骨架） */
    @PostMapping("/book")
    public ResponseEntity<Result<Map<String, Object>>> book(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.book(novelId, body), log, "生成全书骨架失败");
    }

    /** POST /api/novel/plan/{novelId}/cast {settings, book, premise?, idea?, bookConfig?, model}（故事优先：按骨架配人物 / 元素） */
    @PostMapping("/cast")
    public ResponseEntity<Result<Map<String, Object>>> cast(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.cast(novelId, body), log, "生成人物和元素失败");
    }

    /** POST /api/novel/plan/{novelId}/assist {kind: direction|style|conditions|premise, text, premise?, bookConfig?, model}（参数这一步的小帮手） */
    @PostMapping("/assist")
    public ResponseEntity<Result<Map<String, Object>>> assist(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.assist(novelId, body), log, "AI 生成失败");
    }

    /** POST /api/novel/plan/{novelId}/settings-part {settings, module, category?, direction?, keep?, model}（设定单个模块重新生成） */
    @PostMapping("/settings-part")
    public ResponseEntity<Result<Map<String, Object>>> settingsPart(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.settingsPart(novelId, body), log, "重新生成设定失败");
    }

    /** POST /api/novel/plan/{novelId}/enrich {settings, idea?, bookConfig?, excludeBooks?, stage?, model}（故事优先 ④ 素材点睛） */
    @PostMapping("/enrich")
    public ResponseEntity<Result<Map<String, Object>>> enrich(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.enrich(novelId, body), log, "素材点睛失败");
    }

    /** POST /api/novel/plan/{novelId}/settings {premise?, idea?, bookConfig?, book?, tone?, conditions?, materialIds?, materialVariants?, model}（世界 + 主角） */
    @PostMapping("/settings")
    public ResponseEntity<Result<Map<String, Object>>> settings(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.settings(novelId, body), log, "生成设定草案失败");
    }

    /** POST /api/novel/plan/{novelId}/outline {premise, tone?, settings, materialIds?, stage?, count?, model} */
    @PostMapping("/outline")
    public ResponseEntity<Result<Map<String, Object>>> outline(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.outline(novelId, body), log, "生成大纲失败");
    }

    /** POST /api/novel/plan/{novelId}/review {premise, tone?, settings, outline, stage?, model} */
    @PostMapping("/review")
    public ResponseEntity<Result<Map<String, Object>>> review(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.review(novelId, body), log, "审稿失败");
    }
}
