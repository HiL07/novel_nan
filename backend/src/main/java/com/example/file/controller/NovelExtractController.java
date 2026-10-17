package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.NovelExtract;
import com.example.file.service.NovelExtractService;
import lombok.Data;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 小说提取接口：提交任务 / 任务列表 / 任务详情（含结果）。
 */
@RestController
@RequestMapping("/api/novel/extract")
public class NovelExtractController {

    private static final Logger log = LoggerFactory.getLogger(NovelExtractController.class);

    private final NovelExtractService extractService;

    public NovelExtractController(NovelExtractService extractService) {
        this.extractService = extractService;
    }

    /**
     * POST /api/novel/extract/{fileId} [{materials?}]，用当前启用的模型对指定文件发起提取，立即返回任务（异步执行）。
     */
    @PostMapping("/{fileId}")
    public ResponseEntity<Result<NovelExtract>> submit(@PathVariable Long fileId,
                                                       @RequestBody(required = false) ExtractOptions options) {
        Map<String, Object> materials = options == null ? null : options.getMaterials();
        return ResultResponses.handle(() -> extractService.submit(fileId, materials), log, "提交提取任务失败，fileId=" + fileId);
    }

    /**
     * GET /api/novel/extract/list，任务列表（不含结果），按创建时间倒序。
     */
    @GetMapping("/list")
    public ResponseEntity<Result<List<NovelExtract>>> list() {
        return ResultResponses.handle(extractService::list, log, "查询提取任务失败");
    }

    /**
     * GET /api/novel/extract/{id}，任务详情，result 为提取结果 JSON 字符串。
     */
    @GetMapping("/{id}")
    public ResponseEntity<Result<NovelExtract>> detail(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.getById(id), log, "查询提取任务失败，id=" + id);
    }

    /** 提取选项：materials = {enabled, categories: [world, monster, …], maxPerChunk, focus}（素材候选的提取范围） */
    @Data
    public static class ExtractOptions {
        private Map<String, Object> materials;
    }
}
