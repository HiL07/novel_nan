package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.service.NovelGenService;
import com.fasterxml.jackson.databind.JsonNode;
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
 * 小说生成（大模型）：章节生成与 AI 构思，附带启用的模型配置（构思另附素材库素材）后转发给 Python。
 * 本地模型工作区的章节生成由前端直接调用 Python。
 */
@RestController
@RequestMapping("/api/novel/gen")
public class NovelGenController {

    private static final Logger log = LoggerFactory.getLogger(NovelGenController.class);

    private final NovelGenService genService;

    public NovelGenController(NovelGenService genService) {
        this.genService = genService;
    }

    /** POST /api/novel/gen/{novelId}/chapters {goal, title?, targetChars?, polish?{enabled, baseId, adapterId}} → Python 任务 */
    @PostMapping("/{novelId}/chapters")
    public ResponseEntity<Result<JsonNode>> startChapter(@PathVariable String novelId, @RequestBody Map<String, Object> req) {
        return ResultResponses.handle(() -> genService.startChapter(novelId, req), log, "启动章节生成失败");
    }

    /**
     * POST /api/novel/gen/{novelId}/ideas {kind: title|outline|chapter|fill|direction|chat, source?: api|local, baseId?,
     *                                      adapterId?, hint?, count?, purpose?, materialIds?[], autoMaterials?, query?,
     *                                      excludeBooks?[], fill?, chat?, spec?}
     * → {kind, nextIndex, result, usage, model, usedMaterials, blockedMaterials}（只是建议，不保存）
     */
    @PostMapping("/{novelId}/ideas")
    public ResponseEntity<Result<Map<String, Object>>> ideas(@PathVariable String novelId, @RequestBody Map<String, Object> req) {
        return ResultResponses.handle(() -> genService.ideas(novelId, req), log, "AI 构思失败");
    }
}
