package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.FileInfo;
import com.example.file.entity.NovelExtract;
import com.example.file.mapper.NovelExtractMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 小说提取：建任务落库 → 后台提交给 Python AI 服务 → 轮询进度 → 结果写回数据库。
 * 本地千问只有 1 个并发槽，任务在单线程里串行执行。
 */
@Service
public class NovelExtractService {

    private static final Logger log = LoggerFactory.getLogger(NovelExtractService.class);

    private static final Set<String> SUPPORTED_EXTS = Set.of("txt", "md", "docx", "pdf");
    private static final long POLL_INTERVAL_MS = 3000;
    /** Python 服务连续不可达的最大次数（约 1 分钟）后判定失败 */
    private static final int MAX_UNREACHABLE = 20;

    private final NovelExtractMapper extractMapper;
    private final FileService fileService;
    private final ObjectMapper objectMapper;
    private final RestClient aiClient;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "novel-extract");
        t.setDaemon(true);
        return t;
    });

    public NovelExtractService(NovelExtractMapper extractMapper,
                               FileService fileService,
                               ObjectMapper objectMapper,
                               @Value("${ai.service.url}") String aiServiceUrl) {
        this.extractMapper = extractMapper;
        this.fileService = fileService;
        this.objectMapper = objectMapper;
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(30000);
        this.aiClient = RestClient.builder().baseUrl(aiServiceUrl).requestFactory(factory).build();
    }

    /**
     * 启动完成（建表脚本已执行）后，把上次未完成的任务标记为失败（执行线程已随进程退出）。
     */
    @EventListener(ApplicationReadyEvent.class)
    public void failInterrupted() {
        int n = extractMapper.update(null, new LambdaUpdateWrapper<NovelExtract>()
                .in(NovelExtract::getStatus, NovelExtract.QUEUED, NovelExtract.RUNNING)
                .set(NovelExtract::getStatus, NovelExtract.FAILED)
                .set(NovelExtract::getMessage, "服务重启，任务中断，请重新提取")
                .set(NovelExtract::getUpdateTime, LocalDateTime.now()));
        if (n > 0) {
            log.warn("已将 {} 个中断的提取任务标记为失败", n);
        }
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    /**
     * 提交提取任务，立即返回任务记录（QUEUED）。
     */
    public NovelExtract submit(Long fileId) {
        FileInfo file = fileService.getById(fileId);
        String ext = file.getFileExt() == null ? "" : file.getFileExt().toLowerCase();
        if (!SUPPORTED_EXTS.contains(ext)) {
            throw new BizException(400, "仅支持 txt / md / docx / pdf 文件提取");
        }

        NovelExtract task = new NovelExtract();
        task.setFileId(fileId);
        task.setFileName(file.getFileName());
        task.setStatus(NovelExtract.QUEUED);
        task.setProgress(0);
        task.setMessage("排队中");
        task.setCreateTime(LocalDateTime.now());
        task.setUpdateTime(task.getCreateTime());
        extractMapper.insert(task);

        executor.submit(() -> run(task.getId(), fileId, ext));
        return task;
    }

    /**
     * 任务列表（不含大字段 result），按创建时间倒序。
     */
    public List<NovelExtract> list() {
        return extractMapper.selectList(new LambdaQueryWrapper<NovelExtract>()
                .select(NovelExtract::getId, NovelExtract::getFileId, NovelExtract::getFileName,
                        NovelExtract::getStatus, NovelExtract::getProgress, NovelExtract::getMessage,
                        NovelExtract::getCreateTime, NovelExtract::getUpdateTime)
                .orderByDesc(NovelExtract::getCreateTime));
    }

    /**
     * 任务详情（含结果 JSON），不存在抛 404。
     */
    public NovelExtract getById(Long id) {
        NovelExtract task = extractMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "提取任务不存在：" + id);
        }
        return task;
    }

    private void run(Long taskId, Long fileId, String ext) {
        try {
            JsonNode job = aiClient.post()
                    .uri("/api/extract/jobs")
                    .body(Map.of("fileId", fileId, "fileExt", ext))
                    .retrieve()
                    .body(JsonNode.class);
            String jobId = job.path("jobId").asText();
            update(taskId, NovelExtract.RUNNING, 0, "已提交 AI 服务", jobId, null);
            poll(taskId, jobId);
        } catch (ResourceAccessException e) {
            log.error("AI 服务不可达，taskId={}", taskId, e);
            update(taskId, NovelExtract.FAILED, null, "AI 服务不可达，请确认 python-service 已启动", null, null);
        } catch (Exception e) {
            log.error("小说提取失败，taskId={}", taskId, e);
            update(taskId, NovelExtract.FAILED, null, "提取失败：" + e.getMessage(), null, null);
        }
    }

    private void poll(Long taskId, String jobId) throws Exception {
        int unreachable = 0;
        while (!Thread.currentThread().isInterrupted()) {
            Thread.sleep(POLL_INTERVAL_MS);
            JsonNode job;
            try {
                job = aiClient.get().uri("/api/extract/jobs/{id}", jobId).retrieve().body(JsonNode.class);
                unreachable = 0;
            } catch (HttpClientErrorException.NotFound e) {
                update(taskId, NovelExtract.FAILED, null, "AI 服务已重启，任务丢失，请重新提取", null, null);
                return;
            } catch (ResourceAccessException e) {
                if (++unreachable >= MAX_UNREACHABLE) {
                    throw e;
                }
                continue;
            }

            String status = job.path("status").asText();
            int progress = job.path("progress").asInt();
            switch (status) {
                case "succeeded" -> {
                    String result = objectMapper.writeValueAsString(job.path("result"));
                    update(taskId, NovelExtract.SUCCEEDED, 100, "提取完成", null, result);
                    return;
                }
                case "failed" -> {
                    update(taskId, NovelExtract.FAILED, progress, "提取失败：" + job.path("error").asText(), null, null);
                    return;
                }
                default -> update(taskId, NovelExtract.RUNNING, progress, job.path("message").asText(), null, null);
            }
        }
    }

    private void update(Long taskId, String status, Integer progress, String message, String jobId, String result) {
        NovelExtract patch = new NovelExtract();
        patch.setId(taskId);
        patch.setStatus(status);
        patch.setProgress(progress);
        patch.setMessage(message != null && message.length() > 1000 ? message.substring(0, 1000) : message);
        patch.setJobId(jobId);
        patch.setResult(result);
        patch.setUpdateTime(LocalDateTime.now());
        extractMapper.updateById(patch);
    }
}
