package com.example.file.controller;

import com.example.file.common.BizException;
import com.example.file.common.Result;
import com.example.file.entity.NovelExtract;
import com.example.file.service.NovelExtractService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.function.Supplier;

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
     * POST /api/novel/extract/{fileId}，对指定文件发起提取，立即返回任务（异步执行）。
     */
    @PostMapping("/{fileId}")
    public ResponseEntity<Result<NovelExtract>> submit(@PathVariable Long fileId) {
        return handle(() -> extractService.submit(fileId), "提交提取任务失败，fileId=" + fileId);
    }

    /**
     * GET /api/novel/extract/list，任务列表（不含结果），按创建时间倒序。
     */
    @GetMapping("/list")
    public ResponseEntity<Result<List<NovelExtract>>> list() {
        return handle(extractService::list, "查询提取任务失败");
    }

    /**
     * GET /api/novel/extract/{id}，任务详情，result 为提取结果 JSON 字符串。
     */
    @GetMapping("/{id}")
    public ResponseEntity<Result<NovelExtract>> detail(@PathVariable Long id) {
        return handle(() -> extractService.getById(id), "查询提取任务失败，id=" + id);
    }

    /**
     * BizException → 对应 HTTP 状态 + Result.error；其他异常 → 500，不暴露堆栈。
     */
    private <T> ResponseEntity<Result<T>> handle(Supplier<T> action, String errorLog) {
        try {
            return ResponseEntity.ok(Result.ok(action.get()));
        } catch (BizException e) {
            HttpStatus status = HttpStatus.resolve(e.getCode());
            return ResponseEntity.status(status != null ? status : HttpStatus.BAD_REQUEST)
                    .body(Result.error(e.getCode(), e.getMessage()));
        } catch (Exception e) {
            log.error(errorLog, e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Result.error(500, "服务器内部错误"));
        }
    }
}
