package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.FileInfo;
import com.example.file.entity.MaterialCompile;
import com.example.file.entity.NovelExtract;
import com.example.file.mapper.MaterialCompileMapper;
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

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
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
    /** 本地模型默认分块字数（小模型上下文 / 输出有限，比大模型的 6000 字小） */
    private static final long DEFAULT_LOCAL_CHUNK = 2500;

    private final NovelExtractMapper extractMapper;
    private final FileService fileService;
    private final ObjectMapper objectMapper;
    private final AiServiceClient aiClient;
    private final AiModelConfigService modelService;
    private final MaterialService materialService;
    private final ExtractResultStore resultStore;
    private final MaterialCompileMapper compileMapper;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "novel-extract");
        t.setDaemon(true);
        return t;
    });
    /** 用户请求取消的任务 id（排队中的在轮到时跳过） */
    private final Set<Long> cancelRequested = ConcurrentHashMap.newKeySet();
    /** 用户请求暂停的任务 id：Python 停下后记为 INTERRUPTED（断点保留，可继续） */
    private final Set<Long> pauseRequested = ConcurrentHashMap.newKeySet();

    public NovelExtractService(NovelExtractMapper extractMapper,
                               FileService fileService,
                               ObjectMapper objectMapper,
                               AiServiceClient aiClient,
                               AiModelConfigService modelService,
                               MaterialService materialService,
                               ExtractResultStore resultStore,
                               MaterialCompileMapper compileMapper) {
        this.extractMapper = extractMapper;
        this.fileService = fileService;
        this.objectMapper = objectMapper;
        this.aiClient = aiClient;
        this.modelService = modelService;
        this.materialService = materialService;
        this.resultStore = resultStore;
        this.compileMapper = compileMapper;
    }

    /**
     * 启动完成（建表脚本已执行）后，上次未完成的任务记为「中断」（执行线程已随进程退出）：可从断点继续或取消。
     * 没保存提交参数的旧任务无法继续，仍记为失败。
     */
    @EventListener(ApplicationReadyEvent.class)
    public void failInterrupted() {
        int n = extractMapper.update(null, new LambdaUpdateWrapper<NovelExtract>()
                .in(NovelExtract::getStatus, NovelExtract.QUEUED, NovelExtract.RUNNING)
                .isNotNull(NovelExtract::getOptions)
                .set(NovelExtract::getStatus, NovelExtract.INTERRUPTED)
                .set(NovelExtract::getMessage, "服务重启，提取中断" + RESUME_HINT)
                .set(NovelExtract::getUpdateTime, LocalDateTime.now()));
        int m = extractMapper.update(null, new LambdaUpdateWrapper<NovelExtract>()
                .in(NovelExtract::getStatus, NovelExtract.QUEUED, NovelExtract.RUNNING)
                .set(NovelExtract::getStatus, NovelExtract.FAILED)
                .set(NovelExtract::getMessage, "服务重启，任务中断，请重新提取")
                .set(NovelExtract::getUpdateTime, LocalDateTime.now()));
        if (n + m > 0) {
            log.warn("服务重启：{} 个提取任务记为中断（可继续），{} 个旧任务记为失败", n, m);
        }
    }

    private static final String RESUME_HINT = "：可点「继续」从断点接着提取，或「取消」";

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    /**
     * 提交提取任务，立即返回任务记录（QUEUED）。
     * materials：素材候选提取范围 {enabled, categories, maxPerChunk, focus, maxCandidates}，null 或 enabled=false 表示不提取素材。
     */
    public NovelExtract submit(Long fileId, Map<String, Object> materials) {
        return submit(fileId, materials, null);
    }

    /**
     * modelOpts：{source: api, configId?}（configId 为空 = 当前启用的配置；指定时只用于本任务，不改变启用状态）
     * 或 {source: local, baseId, chunkChars?}（应用内本地模型，默认按 2500 字分块）
     * 或 {source: gguf}（Python「llama.cpp」页正在运行的 GGUF 模型）；null 同 api + 启用的配置。
     */
    public NovelExtract submit(Long fileId, Map<String, Object> materials, Map<String, Object> modelOpts) {
        FileInfo file = fileService.getById(fileId);
        String ext = extOf(file);
        // 提交时锁定模型配置快照，执行期间修改配置不影响本任务
        ModelChoice choice = resolveModel(modelOpts);
        boolean withMaterials = materials != null && Boolean.TRUE.equals(materials.get("enabled"));

        NovelExtract task = new NovelExtract();
        task.setFileId(fileId);
        task.setFileName(file.getFileName());
        task.setStatus(NovelExtract.QUEUED);
        task.setProgress(0);
        task.setMessage("排队中（" + choice.label() + (withMaterials ? "，记录设定实体" : "") + "）");
        task.setOptions(optionsJson(modelOpts, withMaterials ? materials : null));
        task.setCreateTime(LocalDateTime.now());
        task.setUpdateTime(task.getCreateTime());
        extractMapper.insert(task);

        Map<String, Object> materialOpts = withMaterials ? materials : null;
        executor.submit(() -> run(task.getId(), file, ext, choice.config(), choice.local(), materialOpts));
        return task;
    }

    /**
     * 继续提取（INTERRUPTED 的任务）：Python 里这个任务还在跑（只是 Java 重启了）→ 接着轮询它；
     * 否则用提交时的参数重新提交，同一个断点键（e&lt;任务id&gt;）：已读完的块、整理好的卡片不再重做。
     */
    public NovelExtract resume(Long id) {
        NovelExtract task = extractMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "提取任务不存在：" + id);
        }
        if (!NovelExtract.INTERRUPTED.equals(task.getStatus())) {
            throw new BizException(400, "只有中断的任务可以继续");
        }
        if (adopt(task)) {
            return extractMapper.selectById(id);
        }
        if (task.getOptions() == null || task.getOptions().isBlank()) {
            throw new BizException(400, "这个任务没有保存提交参数（旧版本创建），请重新提取");
        }
        JsonNode opts;
        try {
            opts = objectMapper.readTree(task.getOptions());
        } catch (Exception e) {
            throw new BizException(400, "提交参数无法读取，请重新提取");
        }
        Map<String, Object> modelOpts = opts.path("model").isObject() ? objectMapper.convertValue(opts.path("model"), Map.class) : null;
        Map<String, Object> materials = opts.path("materials").isObject()
                ? objectMapper.convertValue(opts.path("materials"), Map.class) : null;
        FileInfo file = fileService.getById(task.getFileId());
        String ext = extOf(file);
        ModelChoice choice = resolveModel(modelOpts);
        extractMapper.update(null, new LambdaUpdateWrapper<NovelExtract>().eq(NovelExtract::getId, id)
                .set(NovelExtract::getStatus, NovelExtract.QUEUED)
                .set(NovelExtract::getMessage, "排队中（继续提取，" + choice.label() + "）")
                .set(NovelExtract::getJobId, null)
                .set(NovelExtract::getUpdateTime, LocalDateTime.now()));
        executor.submit(() -> run(id, file, ext, choice.config(), choice.local(), materials));
        return extractMapper.selectById(id);
    }

    /** Python 里同一个任务还在排队 / 运行（Java 重启过）：不重复提交，接着轮询；返回是否已接管 */
    private boolean adopt(NovelExtract task) {
        String jobId = task.getJobId();
        if (jobId == null || jobId.isBlank()) {
            return false;
        }
        JsonNode job;
        try {
            job = aiClient.getExtractJob(jobId);
        } catch (Exception e) {
            return false; // 404（Python 重启过）/ 不可达：重新提交
        }
        String status = job.path("status").asText();
        if (!"queued".equals(status) && !"running".equals(status) && !"succeeded".equals(status)) {
            return false;
        }
        FileInfo file = fileService.getById(task.getFileId());
        update(task.getId(), NovelExtract.RUNNING, null, "接上 AI 服务里还在运行的任务", jobId);
        executor.submit(() -> guarded(task.getId(), () -> poll(task.getId(), jobId, file)));
        return true;
    }

    private static String extOf(FileInfo file) {
        String ext = file.getFileExt() == null ? "" : file.getFileExt().toLowerCase();
        if (!SUPPORTED_EXTS.contains(ext)) {
            throw new BizException(400, "仅支持 txt / md / docx / pdf 文件提取");
        }
        return ext;
    }

    /** 提取 / 整理卡片用的模型：config = 大模型配置（api），local = 应用内本地模型 / {source: gguf}，label 用于任务说明 */
    record ModelChoice(AiModelConfig config, Map<String, Object> local, String label) {
    }

    /** modelOpts：{source: api, configId?} / {source: local, baseId, chunkChars?} / {source: gguf}；null 同 api + 启用的配置 */
    ModelChoice resolveModel(Map<String, Object> modelOpts) {
        if (modelOpts != null && "local".equals(modelOpts.get("source"))) {
            Map<String, Object> local = localOptions(modelOpts);
            return new ModelChoice(null, local, "本地模型：" + local.get("baseId"));
        }
        if (modelOpts != null && "gguf".equals(modelOpts.get("source"))) {
            return new ModelChoice(null, Map.of("source", "gguf"), "GGUF（llama.cpp）");
        }
        Long configId = modelOpts == null ? null : toLong(modelOpts.get("configId"));
        AiModelConfig model = configId == null ? modelService.requireActive() : modelService.requireVerified(configId);
        return new ModelChoice(model, null, "模型：" + model.getName());
    }

    /** {model, materials} → JSON（model 只有 source / configId / baseId / chunkChars，不含密钥） */
    private String optionsJson(Map<String, Object> modelOpts, Map<String, Object> materials) {
        Map<String, Object> opts = new java.util.LinkedHashMap<>();
        opts.put("model", modelOpts);
        opts.put("materials", materials);
        try {
            return objectMapper.writeValueAsString(opts);
        } catch (Exception e) {
            return null;
        }
    }

    /** 白名单：{baseId, chunkChars}，chunkChars 限制在 1000–6000（默认 2500） */
    private static Map<String, Object> localOptions(Map<String, Object> opts) {
        Object baseId = opts.get("baseId");
        String id = baseId == null ? "" : baseId.toString().trim();
        if (id.isEmpty() || id.length() > 120) {
            throw new BizException(400, "请选择本地模型");
        }
        Long chunk = toLong(opts.get("chunkChars"));
        long chunkChars = chunk == null ? DEFAULT_LOCAL_CHUNK : Math.max(1000, Math.min(6000, chunk));
        return Map.of("baseId", id, "chunkChars", chunkChars);
    }

    private static Long toLong(Object v) {
        if (v instanceof Number n) {
            return n.longValue();
        }
        if (v instanceof String s && !s.isBlank()) {
            try {
                return Long.parseLong(s.trim());
            } catch (NumberFormatException e) {
                throw new BizException(400, "参数格式不正确：" + s);
            }
        }
        return null;
    }

    /**
     * 取消：中断的任务直接记为 FAILED「已取消」；排队中的在轮到时结束；已提交给 Python 的通知其取消
     * （本地模型在下一个 token 处停止），停下后记为 FAILED。断点保留到删除任务时。
     */
    public NovelExtract cancel(Long id) {
        NovelExtract task = extractMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "提取任务不存在：" + id);
        }
        if (NovelExtract.INTERRUPTED.equals(task.getStatus())) {
            update(id, NovelExtract.FAILED, null, "已取消", null);
            return extractMapper.selectById(id);
        }
        return stop(task, cancelRequested, "正在取消…", NovelExtract.FAILED, "已取消");
    }

    /** 暂停排队中 / 进行中的任务：停下后记为 INTERRUPTED（留在「提取中」，断点保留，可继续或取消） */
    public NovelExtract pause(Long id) {
        NovelExtract task = extractMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "提取任务不存在：" + id);
        }
        return stop(task, pauseRequested, "正在暂停…", NovelExtract.INTERRUPTED, "已暂停" + RESUME_HINT);
    }

    private NovelExtract stop(NovelExtract task, Set<Long> flags, String pending, String goneStatus, String goneMessage) {
        Long id = task.getId();
        if (!NovelExtract.QUEUED.equals(task.getStatus()) && !NovelExtract.RUNNING.equals(task.getStatus())) {
            throw new BizException(400, "任务不在运行");
        }
        flags.add(id);
        if (task.getJobId() != null && !task.getJobId().isBlank() && NovelExtract.RUNNING.equals(task.getStatus())) {
            try {
                aiClient.cancelExtractJob(task.getJobId());
            } catch (HttpClientErrorException.NotFound e) {
                flags.remove(id);
                update(id, goneStatus, null, goneMessage, null); // Python 已重启，任务不在了
                return extractMapper.selectById(id);
            } catch (ResourceAccessException e) {
                flags.remove(id);
                throw new BizException(503, "AI 服务不可达，操作失败");
            }
        }
        update(id, task.getStatus(), null, pending, null);
        return extractMapper.selectById(id);
    }

    /**
     * 删除提取失败的任务（成功的、提取中的不能删）：删记录和 Python 断点（AI 服务不可达时断点留着，不影响删除）。
     * → {deleted, skipped}
     */
    public Map<String, Object> delete(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            throw new BizException(400, "请选择要删除的任务");
        }
        int deleted = 0;
        int skipped = 0;
        for (Long id : ids) {
            NovelExtract task = id == null ? null : extractMapper.selectById(id);
            if (task == null || !NovelExtract.FAILED.equals(task.getStatus())) {
                skipped++;
                continue;
            }
            extractMapper.deleteById(id);
            deleted++;
            try {
                aiClient.deleteExtractCheckpoint(checkpointKey(id));
            } catch (Exception e) {
                log.warn("删除提取断点失败，taskId={}：{}", id, e.getMessage());
            }
        }
        return Map.of("deleted", deleted, "skipped", skipped);
    }

    /**
     * 任务列表（不含大字段 result），按创建时间倒序。
     */
    public List<NovelExtract> list() {
        List<NovelExtract> list = extractMapper.selectList(new LambdaQueryWrapper<NovelExtract>()
                .select(NovelExtract::getId, NovelExtract::getFileId, NovelExtract::getFileName,
                        NovelExtract::getStatus, NovelExtract::getProgress, NovelExtract::getMessage,
                        NovelExtract::getWordCount, NovelExtract::getChapterCount, NovelExtract::getCandidateCount,
                        NovelExtract::getOptions, NovelExtract::getCreateTime, NovelExtract::getUpdateTime)
                .orderByDesc(NovelExtract::getCreateTime));
        Map<Long, Long> pending = materialService.pendingCountsByExtract();
        Map<Long, MaterialCompile> compiles = latestCompiles();
        list.forEach(t -> {
            t.setPendingCount(pending.getOrDefault(t.getId(), 0L));
            t.setLatestCompile(compiles.get(t.getId()));
        });
        return list;
    }

    /** 每次提取最近一次的整理卡片任务（不含 options） */
    private Map<Long, MaterialCompile> latestCompiles() {
        Map<Long, MaterialCompile> out = new java.util.HashMap<>();
        for (MaterialCompile c : compileMapper.selectList(new LambdaQueryWrapper<MaterialCompile>()
                .select(MaterialCompile::getId, MaterialCompile::getExtractId, MaterialCompile::getStatus,
                        MaterialCompile::getProgress, MaterialCompile::getMessage, MaterialCompile::getEntityCount,
                        MaterialCompile::getCardCount, MaterialCompile::getArcCount, MaterialCompile::getCandidateCount,
                        MaterialCompile::getCreateTime, MaterialCompile::getUpdateTime)
                .orderByAsc(MaterialCompile::getId))) {
            out.put(c.getExtractId(), c); // id 递增：后面的覆盖前面的
        }
        return out;
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
        } else {
            try {
                task.setCheckpoint(aiClient.extractCheckpoint(checkpointKey(id))); // 已完成多少（失败 / 中断时查看）
            } catch (Exception e) {
                task.setCheckpoint(null);
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

    private void run(Long taskId, FileInfo file, String ext, AiModelConfig model, Map<String, Object> local,
                     Map<String, Object> materials) {
        guarded(taskId, () -> {
            if (cancelRequested.remove(taskId)) {
                update(taskId, NovelExtract.FAILED, null, "已取消", null);
                return;
            }
            if (pauseRequested.remove(taskId)) {
                update(taskId, NovelExtract.INTERRUPTED, null, "已暂停" + RESUME_HINT, null);
                return;
            }
            JsonNode job = aiClient.submitExtract(file.getId(), ext, model, local, materials, checkpointKey(taskId));
            String jobId = job.path("jobId").asText();
            update(taskId, NovelExtract.RUNNING, null, "已提交 AI 服务", jobId);
            if (cancelRequested.contains(taskId) || pauseRequested.contains(taskId)) {
                aiClient.cancelExtractJob(jobId); // 提交的同时用户点了取消 / 暂停
            }
            poll(taskId, jobId, file);
        });
    }

    private interface Step {
        void run() throws Exception;
    }

    /** 执行 / 轮询出错一律记为「中断」（留在提取中，可修好后继续或取消），只有保存结果失败等由各处自己记 FAILED */
    private void guarded(Long taskId, Step step) {
        try {
            step.run();
        } catch (ResourceAccessException e) {
            log.error("AI 服务不可达，taskId={}", taskId, e);
            interrupt(taskId, "AI 服务不可达（请确认 python-service 已启动）");
        } catch (RestClientResponseException e) {
            // 不记录响应体：校验错误（422）的回显里可能带有 API Key；400 是本服务自己的说明（如 GPU 被训练占用），可以展示
            log.error("AI 服务拒绝提取任务，taskId={}，HTTP {}", taskId, e.getStatusCode().value());
            interrupt(taskId, "AI 服务拒绝任务：" + rejectReason(e));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (Exception e) {
            log.error("小说提取失败，taskId={}", taskId, e);
            interrupt(taskId, "提取出错：" + e.getMessage());
        } finally {
            cancelRequested.remove(taskId);
            pauseRequested.remove(taskId);
        }
    }

    private void interrupt(Long taskId, String reason) {
        update(taskId, NovelExtract.INTERRUPTED, null, reason + RESUME_HINT, null);
    }

    /** 400 取 FastAPI 的 {detail: "..."}（本服务自己的提示）；其他状态码只给状态码 */
    private String rejectReason(RestClientResponseException e) {
        if (e.getStatusCode().value() == 400) {
            try {
                JsonNode detail = objectMapper.readTree(e.getResponseBodyAsString(StandardCharsets.UTF_8)).path("detail");
                if (detail.isTextual()) {
                    return detail.asText();
                }
            } catch (Exception ignored) {
                // 不是 JSON：只给状态码
            }
        }
        return "HTTP " + e.getStatusCode().value();
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
                interrupt(taskId, "AI 服务已重启，提取中断");
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
                    update(taskId, NovelExtract.INTERRUPTED, progress, "提取出错：" + job.path("error").asText() + RESUME_HINT, null);
                    return;
                }
                case "cancelled" -> {
                    if (pauseRequested.remove(taskId)) {
                        update(taskId, NovelExtract.INTERRUPTED, progress, "已暂停" + RESUME_HINT, null);
                    } else {
                        update(taskId, NovelExtract.FAILED, progress, "已取消", null);
                    }
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
        try {
            aiClient.deleteExtractCheckpoint(checkpointKey(taskId)); // 结果已保存，断点没用了
        } catch (Exception e) {
            log.warn("删除提取断点失败，taskId={}：{}", taskId, e.getMessage());
        }
    }

    /** Python 断点键：data/extract-cache/e&lt;任务id&gt;/ */
    private static String checkpointKey(Long taskId) {
        return "e" + taskId;
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
        JsonNode st = result.path("factStats");
        if (st.isObject()) {
            return "提取完成：" + st.path("entities").asInt() + " 个实体、" + st.path("factsVerified").asInt()
                    + " 条事实（丢弃 " + st.path("factsUnverified").asInt() + " 条对不上原文的），可以「整理卡片」";
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
