package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.MaterialCompile;
import com.example.file.entity.NovelExtract;
import com.example.file.service.MaterialCompileService;
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
    private final MaterialCompileService compileService;

    public NovelExtractController(NovelExtractService extractService, MaterialCompileService compileService) {
        this.extractService = extractService;
        this.compileService = compileService;
    }

    /**
     * POST /api/novel/extract/{id}/compile {model, entityKeys?, categories?, topN?, plot?}：对提取成功的小说整理卡片
     * （素材卡 / 体系卡 / 剧情段 → 待确认候选）。
     */
    @PostMapping("/{id}/compile")
    public ResponseEntity<Result<MaterialCompile>> compile(@PathVariable Long id,
                                                           @RequestBody(required = false) Map<String, Object> options) {
        return ResultResponses.handle(() -> compileService.start(id, options), log, "发起整理卡片失败，extractId=" + id);
    }

    /** GET /api/novel/extract/{id}/compiles：这次提取的整理记录，最近的在前 */
    @GetMapping("/{id}/compiles")
    public ResponseEntity<Result<List<MaterialCompile>>> compiles(@PathVariable Long id) {
        return ResultResponses.handle(() -> compileService.list(id), log, "查询整理记录失败，extractId=" + id);
    }

    /** POST /api/novel/extract/compile/{cid}/pause：暂停整理（停下后为中断，可继续） */
    @PostMapping("/compile/{cid}/pause")
    public ResponseEntity<Result<MaterialCompile>> pauseCompile(@PathVariable Long cid) {
        return ResultResponses.handle(() -> compileService.pause(cid), log, "暂停整理失败，id=" + cid);
    }

    /** POST /api/novel/extract/compile/{cid}/resume：继续中断的整理（已整理的卡片不重做） */
    @PostMapping("/compile/{cid}/resume")
    public ResponseEntity<Result<MaterialCompile>> resumeCompile(@PathVariable Long cid) {
        return ResultResponses.handle(() -> compileService.resume(cid), log, "继续整理失败，id=" + cid);
    }

    /** POST /api/novel/extract/compile/{cid}/cancel：取消整理（记为失败，可重新发起） */
    @PostMapping("/compile/{cid}/cancel")
    public ResponseEntity<Result<MaterialCompile>> cancelCompile(@PathVariable Long cid) {
        return ResultResponses.handle(() -> compileService.cancel(cid), log, "取消整理失败，id=" + cid);
    }

    /**
     * POST /api/novel/extract/{fileId} [{materials?, model?}]，对指定文件发起提取，立即返回任务（异步执行）。
     * model：{source: api, configId?}（空 = 当前启用的配置）或 {source: local, baseId, chunkChars?} 或 {source: gguf}（llama.cpp 页运行中的 GGUF）。
     */
    @PostMapping("/{fileId}")
    public ResponseEntity<Result<NovelExtract>> submit(@PathVariable Long fileId,
                                                       @RequestBody(required = false) ExtractOptions options) {
        Map<String, Object> materials = options == null ? null : options.getMaterials();
        Map<String, Object> model = options == null ? null : options.getModel();
        return ResultResponses.handle(() -> extractService.submit(fileId, materials, model), log,
                "提交提取任务失败，fileId=" + fileId);
    }

    /**
     * POST /api/novel/extract/{id}/cancel，取消排队中 / 进行中 / 中断的任务（记为 FAILED「已取消」，进入提取失败）。
     */
    @PostMapping("/{id}/cancel")
    public ResponseEntity<Result<NovelExtract>> cancel(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.cancel(id), log, "取消提取任务失败，id=" + id);
    }

    /**
     * POST /api/novel/extract/{id}/pause，暂停排队中 / 进行中的任务：停下后为 INTERRUPTED（断点保留，可继续或取消）。
     */
    @PostMapping("/{id}/pause")
    public ResponseEntity<Result<NovelExtract>> pause(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.pause(id), log, "暂停提取任务失败，id=" + id);
    }

    /**
     * POST /api/novel/extract/delete {ids}，删除提取失败的任务（成功的 / 提取中的跳过）→ {deleted, skipped}。
     */
    @PostMapping("/delete")
    public ResponseEntity<Result<Map<String, Object>>> delete(@RequestBody Map<String, List<Long>> body) {
        return ResultResponses.handle(() -> extractService.delete(body == null ? null : body.get("ids")), log,
                "删除提取任务失败");
    }

    /**
     * POST /api/novel/extract/{id}/resume，继续中断的任务：AI 服务里还在跑就接着轮询，否则用提交时的参数
     * 重新提交，同一个断点键，已完成的分块 / 卡片不重做。
     */
    @PostMapping("/{id}/resume")
    public ResponseEntity<Result<NovelExtract>> resume(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.resume(id), log, "继续提取任务失败，id=" + id);
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

    /**
     * POST /api/novel/extract/{id}/result {chapters: [...], characters: [...], style, ...}：保存手动修改后的提取结果（整体替换）。
     */
    @PostMapping("/{id}/result")
    public ResponseEntity<Result<NovelExtract>> updateResult(@PathVariable Long id, @RequestBody Map<String, Object> result) {
        return ResultResponses.handle(() -> extractService.updateResult(id, result), log, "保存提取结果失败，id=" + id);
    }

    /**
     * 提取选项：materials = {enabled, categories: [world, monster, …], rounds, chunkChars, focus}（是否记录设定实体，
     * 原样交给 Python 校验；整理卡片是之后单独的一步）；
     * model = 提取用的模型（见 submit），字段由 service 白名单处理。
     */
    @Data
    public static class ExtractOptions {
        private Map<String, Object> materials;
        private Map<String, Object> model;
    }
}
