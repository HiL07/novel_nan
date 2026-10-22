package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
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
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 小说提取：建任务落库 → 后台提交给 Python AI 服务 → 轮询进度 → 结果写回数据库。
 * 使用「模型配置」中启用且已验证的模型；任务之间单线程串行，任务内由 Python 按配置的并发数调用模型。
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
    private final AiServiceClient aiClient;
    private final AiModelConfigService modelService;
    private final MaterialService materialService;
    private final ExtractResultStore resultStore;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "novel-extract");
        t.setDaemon(true);
        return t;
    });

    public NovelExtractService(NovelExtractMapper extractMapper,
                               FileService fileService,
                               ObjectMapper objectMapper,
                               AiServiceClient aiClient,
                               AiModelConfigService modelService,
                               MaterialService materialService,
                               ExtractResultStore resultStore) {
        this.extractMapper = extractMapper;
        this.fileService = fileService;
        this.objectMapper = objectMapper;
        this.aiClient = aiClient;
        this.modelService = modelService;
        this.materialService = materialService;
        this.resultStore = resultStore;
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
     * materials：素材候选提取范围 {enabled, categories, maxPerChunk, focus, maxCandidates}，null 或 enabled=false 表示不提取素材。
     */
    public NovelExtract submit(Long fileId, Map<String, Object> materials) {
        FileInfo file = fileService.getById(fileId);
        String ext = file.getFileExt() == null ? "" : file.getFileExt().toLowerCase();
        if (!SUPPORTED_EXTS.contains(ext)) {
            throw new BizException(400, "仅支持 txt / md / docx / pdf 文件提取");
        }
        // 提交时锁定模型配置快照，执行期间修改配置不影响本任务
        AiModelConfig model = modelService.requireActive();

        NovelExtract task = new NovelExtract();
        task.setFileId(fileId);
        task.setFileName(file.getFileName());
        task.setStatus(NovelExtract.QUEUED);
        task.setProgress(0);
        boolean withMaterials = materials != null && Boolean.TRUE.equals(materials.get("enabled"));
        task.setMessage("排队中（模型：" + model.getName() + (withMaterials ? "，含素材提取" : "") + "）");
        task.setCreateTime(LocalDateTime.now());
        task.setUpdateTime(task.getCreateTime());
        extractMapper.insert(task);

        Map<String, Object> materialOpts = withMaterials ? materials : null;
        executor.submit(() -> run(task.getId(), file, ext, model, materialOpts));
        return task;
    }

    /**
     * 任务列表（不含大字段 result），按创建时间倒序。
     */
    public List<NovelExtract> list() {
        return extractMapper.selectList(new LambdaQueryWrapper<NovelExtract>()
                .select(NovelExtract::getId, NovelExtract::getFileId, NovelExtract::getFileName,
                        NovelExtract::getStatus, NovelExtract::getProgress, NovelExtract::getMessage,
                        NovelExtract::getWordCount, NovelExtract::getChapterCount, NovelExtract::getCandidateCount,
                        NovelExtract::getCreateTime, NovelExtract::getUpdateTime)
                .orderByDesc(NovelExtract::getCreateTime));
    }

    /**
     * 任务详情，不存在抛 404。result 从 data/ 下的结果文件读出（保持原接口结构）；
     * 文件缺失 / 校验失败时 result 为 null，并在 message 中说明，任务状态不变。
     */
    public NovelExtract getById(Long id) {
        NovelExtract task = extractMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "提取任务不存在：" + id);
        }
        if (task.getResultPath() != null) {
            ExtractResultStore.Loaded loaded = resultStore.read(task.getResultPath(), task.getResultSha256());
            task.setResult(loaded.json());
            if (loaded.problem() != null) {
                task.setMessage(Objects.requireNonNullElse(task.getMessage(), "") + "（" + loaded.problem() + "）");
            }
        }
        return task;
    }

    /**
     * 手动修改提取结果（AI 生成的章节摘要 / 人物 / 事件等都可以改）：整体替换结果 JSON（须为对象且含 chapters 数组），
     * 重写结果文件并更新 SHA-256 / 大小 / 章节数，结果里记 editedAt。数据库更新失败时把原文件写回。
     */
    public NovelExtract updateResult(Long id, Map<String, Object> result) {
        NovelExtract task = extractMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "提取任务不存在：" + id);
        }
        if (!NovelExtract.SUCCEEDED.equals(task.getStatus()) || task.getResultPath() == null) {
            throw new BizException(400, "只能修改已完成的提取结果");
        }
        if (result == null || !(result.get("chapters") instanceof List<?> chapters)) {
            throw new BizException(400, "提取结果格式不正确（缺少 chapters）");
        }
        ExtractResultStore.Loaded old = resultStore.read(task.getResultPath(), task.getResultSha256());
        if (old.json() == null) {
            throw new BizException(400, "原提取结果无法读取：" + old.problem());
        }
        result.put("editedAt", LocalDateTime.now().withNano(0).toString().replace('T', ' '));
        ExtractResultStore.Stored stored;
        try {
            stored = resultStore.write(id, objectMapper.writeValueAsString(result));
        } catch (Exception e) {
            log.error("保存修改后的提取结果失败，taskId={}", id, e);
            throw new BizException(500, "保存失败：" + e.getMessage());
        }
        NovelExtract patch = new NovelExtract();
        patch.setId(id);
        patch.setResultPath(stored.relativePath());
        patch.setResultSize(stored.size());
        patch.setResultSha256(stored.sha256());
        patch.setChapterCount(chapters.size());
        patch.setUpdateTime(LocalDateTime.now());
        try {
            extractMapper.updateById(patch);
        } catch (RuntimeException e) {
            try {
                resultStore.write(id, old.json()); // 与数据库里的 SHA-256 保持一致
            } catch (Exception restoreError) {
                log.error("回写原提取结果失败，taskId={}", id, restoreError);
            }
            throw e;
        }
        return getById(id);
    }

    private void run(Long taskId, FileInfo file, String ext, AiModelConfig model, Map<String, Object> materials) {
        try {
            JsonNode job = aiClient.submitExtract(file.getId(), ext, model, materials);
            String jobId = job.path("jobId").asText();
            update(taskId, NovelExtract.RUNNING, 0, "已提交 AI 服务", jobId);
            poll(taskId, jobId, file);
        } catch (ResourceAccessException e) {
            log.error("AI 服务不可达，taskId={}", taskId, e);
            update(taskId, NovelExtract.FAILED, null, "AI 服务不可达，请确认 python-service 已启动", null);
        } catch (RestClientResponseException e) {
            // 不记录响应体：校验错误的回显里可能带有 API Key
            log.error("AI 服务拒绝提取任务，taskId={}，HTTP {}", taskId, e.getStatusCode().value());
            update(taskId, NovelExtract.FAILED, null, "AI 服务拒绝任务（HTTP " + e.getStatusCode().value() + "）", null);
        } catch (Exception e) {
            log.error("小说提取失败，taskId={}", taskId, e);
            update(taskId, NovelExtract.FAILED, null, "提取失败：" + e.getMessage(), null);
        }
    }

    private void poll(Long taskId, String jobId, FileInfo file) throws Exception {
        int unreachable = 0;
        while (!Thread.currentThread().isInterrupted()) {
            Thread.sleep(POLL_INTERVAL_MS);
            JsonNode job;
            try {
                job = aiClient.getExtractJob(jobId);
                unreachable = 0;
            } catch (HttpClientErrorException.NotFound e) {
                update(taskId, NovelExtract.FAILED, null, "AI 服务已重启，任务丢失，请重新提取", null);
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
                    finishSucceeded(taskId, file, job.path("result"));
                    return;
                }
                case "failed" -> {
                    update(taskId, NovelExtract.FAILED, progress, "提取失败：" + job.path("error").asText(), null);
                    return;
                }
                default -> update(taskId, NovelExtract.RUNNING, progress, job.path("message").asText(), null);
            }
        }
    }

    /**
     * 成功收尾：① 结果写入 data/extract-results/（失败则任务记为 FAILED，不留路径）→ ② 生成素材候选
     * → ③ 写入结果元数据并置为 SUCCEEDED（失败则删除刚写的文件，避免孤儿文件）。
     */
    private void finishSucceeded(Long taskId, FileInfo file, JsonNode result) throws Exception {
        ExtractResultStore.Stored stored;
        try {
            stored = resultStore.write(taskId, objectMapper.writeValueAsString(result));
        } catch (Exception e) {
            log.error("保存提取结果文件失败，taskId={}", taskId, e);
            update(taskId, NovelExtract.FAILED, 100, "提取完成但结果保存失败：" + e.getMessage()
                    + "（请检查 data/extract-results 目录的磁盘空间与写权限后重新提取）", null);
            return;
        }
        // 素材只生成「待确认候选」，由用户在提取结果 / 素材库页确认后才入库
        MaterialService.CandidateStats stats = new MaterialService.CandidateStats(0, 0);
        try {
            stats = materialService.createCandidates(taskId, file.getId(), file.getFileName(), result);
        } catch (Exception e) {
            log.error("保存素材候选失败，taskId={}", taskId, e);
        }
        NovelExtract patch = new NovelExtract();
        patch.setId(taskId);
        patch.setStatus(NovelExtract.SUCCEEDED);
        patch.setProgress(100);
        patch.setMessage(extractMessage(result, stats));
        patch.setResultPath(stored.relativePath());
        patch.setResultSize(stored.size());
        patch.setResultSha256(stored.sha256());
        patch.setWordCount(result.path("wordCount").isNumber() ? result.path("wordCount").asInt() : null);
        patch.setChapterCount(result.path("chapterCount").isNumber() ? result.path("chapterCount").asInt() : null);
        // 实际进入候选箱的条数（重复跳过的不算）
        patch.setCandidateCount(result.path("materials").isArray() ? stats.created() : null);
        patch.setUpdateTime(LocalDateTime.now());
        try {
            extractMapper.updateById(patch);
        } catch (RuntimeException e) {
            resultStore.deleteQuietly(stored.relativePath());
            throw e;
        }
    }

    /** 「提取完成，发现 N 条素材候选待确认；跳过与本书已有候选 / 素材重复的 D 条；共识别 T 条，超过上限只保留出现最多的 M 条」 */
    private static String extractMessage(JsonNode result, MaterialService.CandidateStats stats) {
        StringBuilder sb = new StringBuilder("提取完成");
        if (stats.created() > 0) {
            sb.append("，发现 ").append(stats.created()).append(" 条素材候选待确认");
        }
        if (stats.duplicates() > 0) {
            sb.append("；跳过与本书已有候选 / 素材重复的 ").append(stats.duplicates()).append(" 条");
        }
        int kept = result.path("materials").size();
        int total = result.path("materialsTotal").asInt(kept);
        if (total > kept) {
            sb.append("；共识别 ").append(total).append(" 条，超过上限只保留出现章节最多的 ").append(kept)
                    .append(" 条（可在提取选项里调高「候选上限」）");
        }
        return sb.toString();
    }

    private void update(Long taskId, String status, Integer progress, String message, String jobId) {
        NovelExtract patch = new NovelExtract();
        patch.setId(taskId);
        patch.setStatus(status);
        patch.setProgress(progress);
        patch.setMessage(message != null && message.length() > 1000 ? message.substring(0, 1000) : message);
        patch.setJobId(jobId);
        patch.setUpdateTime(LocalDateTime.now());
        extractMapper.updateById(patch);
    }
}
