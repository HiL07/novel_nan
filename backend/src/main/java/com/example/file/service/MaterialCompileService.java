package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.FileInfo;
import com.example.file.entity.MaterialCompile;
import com.example.file.entity.NovelExtract;
import com.example.file.mapper.MaterialCompileMapper;
import com.example.file.mapper.NovelExtractMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 整理卡片：素材流程的第 ② 步。对一次成功的小说提取（结果里有实体档案 entities）单独发起：
 * 按用户选的范围取实体 + 章节摘要交给 Python（/api/extract/compile/jobs）→ 素材卡 / 体系卡 / 剧情段 → 待确认候选。
 * 一次提取可以整理多次（换模型 / 换范围），同一次提取同时只能有一个未结束的整理任务。
 * 状态规则与提取任务相同：出错 / 重启 / 暂停 = INTERRUPTED（可继续或取消），取消 = FAILED。断点键 k&lt;id&gt;。
 */
@Service
public class MaterialCompileService {

    private static final Logger log = LoggerFactory.getLogger(MaterialCompileService.class);

    private static final long POLL_INTERVAL_MS = 3000;
    private static final int MAX_UNREACHABLE = 20;
    private static final int MAX_ENTITIES = 5000;
    private static final int SUMMARY_CHARS = 2000;
    private static final String RESUME_HINT = "：可点「继续」从断点接着整理，或「取消」";
    private static final List<String> OPEN = List.of(NovelExtract.QUEUED, NovelExtract.RUNNING, NovelExtract.INTERRUPTED);

    private final MaterialCompileMapper compileMapper;
    private final NovelExtractMapper extractMapper;
    private final NovelExtractService extractService;
    private final ExtractResultStore resultStore;
    private final FileService fileService;
    private final MaterialService materialService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "material-compile");
        t.setDaemon(true);
        return t;
    });
    private final Set<Long> cancelRequested = ConcurrentHashMap.newKeySet();
    private final Set<Long> pauseRequested = ConcurrentHashMap.newKeySet();

    public MaterialCompileService(MaterialCompileMapper compileMapper, NovelExtractMapper extractMapper,
                                  NovelExtractService extractService, ExtractResultStore resultStore,
                                  FileService fileService, MaterialService materialService,
                                  AiServiceClient aiClient, ObjectMapper objectMapper) {
        this.compileMapper = compileMapper;
        this.extractMapper = extractMapper;
        this.extractService = extractService;
        this.resultStore = resultStore;
        this.fileService = fileService;
        this.materialService = materialService;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    /** 启动时把上次没结束的整理任务记为中断（执行线程已随进程退出），可继续或取消 */
    @EventListener(ApplicationReadyEvent.class)
    public void markInterrupted() {
        int n = compileMapper.update(null, new LambdaUpdateWrapper<MaterialCompile>()
                .in(MaterialCompile::getStatus, NovelExtract.QUEUED, NovelExtract.RUNNING)
                .set(MaterialCompile::getStatus, NovelExtract.INTERRUPTED)
                .set(MaterialCompile::getMessage, "服务重启，整理中断" + RESUME_HINT)
                .set(MaterialCompile::getUpdateTime, LocalDateTime.now()));
        if (n > 0) {
            log.warn("服务重启：{} 个整理卡片任务记为中断", n);
        }
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    /**
     * 发起整理卡片。opts：{model: {source: api, configId?} | {source: gguf} | {source: local, baseId},
     * entityKeys?: [实体键]（实体档案里勾选的）, categories?: [分类], topN?: 事实最多的前 N 个, plot?: 是否整理剧情段（默认是）}。
     */
    public MaterialCompile start(Long extractId, Map<String, Object> opts) {
        NovelExtract task = extractMapper.selectById(extractId);
        if (task == null) {
            throw new BizException(404, "提取任务不存在：" + extractId);
        }
        if (!NovelExtract.SUCCEEDED.equals(task.getStatus())) {
            throw new BizException(400, "只有提取成功的小说可以整理卡片");
        }
        if (compileMapper.selectCount(new LambdaQueryWrapper<MaterialCompile>()
                .eq(MaterialCompile::getExtractId, extractId).in(MaterialCompile::getStatus, OPEN)) > 0) {
            throw new BizException(400, "这本小说已有未结束的整理任务，请等它结束、继续或取消");
        }
        Map<String, Object> clean = cleanOptions(opts == null ? Map.of() : opts);
        @SuppressWarnings("unchecked")
        Map<String, Object> model = (Map<String, Object>) clean.get("model");
        NovelExtractService.ModelChoice choice = extractService.resolveModel(model); // 先校验模型，避免建了任务才发现没配置
        int entities = selectEntities(loadResult(task), clean).size();
        if (entities == 0) {
            throw new BizException(400, "所选范围内没有实体");
        }

        MaterialCompile c = new MaterialCompile();
        c.setExtractId(extractId);
        c.setStatus(NovelExtract.QUEUED);
        c.setProgress(0);
        c.setMessage("排队中（" + choice.label() + "，" + entities + " 个实体）");
        c.setEntityCount(entities);
        c.setOptions(writeJson(clean));
        c.setCreateTime(LocalDateTime.now());
        c.setUpdateTime(c.getCreateTime());
        compileMapper.insert(c);
        executor.submit(() -> run(c.getId()));
        return c;
    }

    /** 一次提取的全部整理记录，最近的在前 */
    public List<MaterialCompile> list(Long extractId) {
        return compileMapper.selectList(new LambdaQueryWrapper<MaterialCompile>()
                .eq(MaterialCompile::getExtractId, extractId).orderByDesc(MaterialCompile::getId));
    }

    /** 继续中断的整理：Python 里还在跑就接着轮询，否则用保存的参数重新提交（同一断点键，已整理的卡片不重做） */
    public MaterialCompile resume(Long id) {
        MaterialCompile c = require(id);
        if (!NovelExtract.INTERRUPTED.equals(c.getStatus())) {
            throw new BizException(400, "只有中断的整理任务可以继续");
        }
        if (c.getJobId() != null && !c.getJobId().isBlank()) {
            try {
                String st = aiClient.getExtractJob(c.getJobId()).path("status").asText();
                if ("queued".equals(st) || "running".equals(st) || "succeeded".equals(st)) {
                    update(id, NovelExtract.RUNNING, null, "接上 AI 服务里还在运行的任务", c.getJobId());
                    executor.submit(() -> guarded(id, () -> poll(id, c.getJobId())));
                    return compileMapper.selectById(id);
                }
            } catch (Exception e) {
                // 404（Python 重启过）/ 不可达：重新提交
            }
        }
        update(id, NovelExtract.QUEUED, null, "排队中（继续整理）", null);
        compileMapper.update(null, new LambdaUpdateWrapper<MaterialCompile>().eq(MaterialCompile::getId, id)
                .set(MaterialCompile::getJobId, null));
        executor.submit(() -> run(id));
        return compileMapper.selectById(id);
    }

    /** 暂停排队中 / 进行中的整理：停下后为 INTERRUPTED（断点保留） */
    public MaterialCompile pause(Long id) {
        return stop(require(id), pauseRequested, "正在暂停…", NovelExtract.INTERRUPTED, "已暂停" + RESUME_HINT);
    }

    /** 取消：中断的直接记为 FAILED；进行中的通知 Python 停下后记为 FAILED。可以重新发起整理 */
    public MaterialCompile cancel(Long id) {
        MaterialCompile c = require(id);
        if (NovelExtract.INTERRUPTED.equals(c.getStatus())) {
            update(id, NovelExtract.FAILED, null, "已取消", null);
            deleteCheckpoint(id);
            return compileMapper.selectById(id);
        }
        return stop(c, cancelRequested, "正在取消…", NovelExtract.FAILED, "已取消");
    }

    // ------------------------------------------------------------------ 内部

    private MaterialCompile require(Long id) {
        MaterialCompile c = compileMapper.selectById(id);
        if (c == null) {
            throw new BizException(404, "整理任务不存在：" + id);
        }
        return c;
    }

    private MaterialCompile stop(MaterialCompile c, Set<Long> flags, String pending, String goneStatus, String goneMessage) {
        Long id = c.getId();
        if (!NovelExtract.QUEUED.equals(c.getStatus()) && !NovelExtract.RUNNING.equals(c.getStatus())) {
            throw new BizException(400, "整理任务不在运行");
        }
        flags.add(id);
        if (c.getJobId() != null && !c.getJobId().isBlank() && NovelExtract.RUNNING.equals(c.getStatus())) {
            try {
                aiClient.cancelExtractJob(c.getJobId());
            } catch (HttpClientErrorException.NotFound e) {
                flags.remove(id);
                update(id, goneStatus, null, goneMessage, null); // Python 已重启，任务不在了
                return compileMapper.selectById(id);
            } catch (ResourceAccessException e) {
                flags.remove(id);
                throw new BizException(503, "AI 服务不可达，操作失败");
            }
        }
        update(id, c.getStatus(), null, pending, null);
        return compileMapper.selectById(id);
    }

    /** 白名单：model、entityKeys（≤5000）、categories、topN（≥1）、plot */
    private Map<String, Object> cleanOptions(Map<String, Object> opts) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("model", opts.get("model") instanceof Map<?, ?> m ? new LinkedHashMap<>(m) : null);
        if (opts.get("entityKeys") instanceof List<?> keys && !keys.isEmpty()) {
            out.put("entityKeys", keys.stream().filter(k -> k != null).map(String::valueOf).limit(MAX_ENTITIES).toList());
        }
        if (opts.get("categories") instanceof List<?> cats && !cats.isEmpty()) {
            out.put("categories", cats.stream().map(String::valueOf).filter(MaterialService.CATEGORIES::containsKey).toList());
        }
        if (opts.get("topN") instanceof Number n && n.intValue() > 0) {
            out.put("topN", Math.min(n.intValue(), MAX_ENTITIES));
        }
        out.put("plot", !Boolean.FALSE.equals(opts.get("plot")));
        return out;
    }

    private JsonNode loadResult(NovelExtract task) {
        ExtractResultStore.Loaded loaded = resultStore.read(task.getResultPath(), task.getResultSha256());
        if (loaded.json() == null) {
            throw new BizException(400, "提取结果无法读取：" + loaded.problem());
        }
        try {
            JsonNode result = objectMapper.readTree(loaded.json());
            if (!result.path("entities").isArray()) {
                throw new BizException(400, "这次提取没有记录实体（旧版提取或没开「提取创作素材」），请重新提取");
            }
            return result;
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            throw new BizException(400, "提取结果格式不正确");
        }
    }

    /** 按 entityKeys / categories 过滤，再取前 topN（实体档案已按事实数排序） */
    private List<JsonNode> selectEntities(JsonNode result, Map<String, Object> opts) {
        Set<String> keys = opts.get("entityKeys") instanceof List<?> l ? new HashSet<>(l.stream().map(String::valueOf).toList()) : null;
        Set<String> cats = opts.get("categories") instanceof List<?> l ? new HashSet<>(l.stream().map(String::valueOf).toList()) : null;
        int top = opts.get("topN") instanceof Number n ? n.intValue() : MAX_ENTITIES;
        List<JsonNode> out = new ArrayList<>();
        for (JsonNode e : result.path("entities")) {
            if (out.size() >= top) {
                break;
            }
            if (keys != null && !keys.contains(e.path("key").asText())) {
                continue;
            }
            if (cats != null && !cats.contains(e.path("category").asText())) {
                continue;
            }
            out.add(e);
        }
        return out;
    }

    private void run(Long id) {
        guarded(id, () -> {
            if (cancelRequested.remove(id)) {
                update(id, NovelExtract.FAILED, null, "已取消", null);
                return;
            }
            if (pauseRequested.remove(id)) {
                update(id, NovelExtract.INTERRUPTED, null, "已暂停" + RESUME_HINT, null);
                return;
            }
            MaterialCompile c = require(id);
            NovelExtract task = extractMapper.selectById(c.getExtractId());
            if (task == null || !NovelExtract.SUCCEEDED.equals(task.getStatus())) {
                update(id, NovelExtract.FAILED, null, "来源提取任务不存在或不是成功状态", null);
                return;
            }
            JsonNode opts = objectMapper.readTree(c.getOptions());
            @SuppressWarnings("unchecked")
            Map<String, Object> optMap = objectMapper.convertValue(opts, Map.class);
            @SuppressWarnings("unchecked")
            Map<String, Object> model = opts.path("model").isObject() ? objectMapper.convertValue(opts.path("model"), Map.class) : null;
            NovelExtractService.ModelChoice choice = extractService.resolveModel(model);
            JsonNode result = loadResult(task);
            List<JsonNode> entities = selectEntities(result, optMap);
            List<Map<String, Object>> chapters = new ArrayList<>();
            for (JsonNode ch : result.path("chapters")) {
                String summary = ch.path("summary").asText("");
                chapters.add(Map.of("title", ch.path("title").asText(""),
                        "summary", summary.length() > SUMMARY_CHARS ? summary.substring(0, SUMMARY_CHARS) : summary));
            }
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("fileId", task.getFileId());
            body.put("entities", entities);
            body.put("chapters", chapters);
            body.put("plot", opts.path("plot").asBoolean(true));
            JsonNode job = aiClient.submitCompile(body, choice.config(), choice.local(), checkpointKey(id));
            String jobId = job.path("jobId").asText();
            update(id, NovelExtract.RUNNING, null, "已提交 AI 服务（" + choice.label() + "）", jobId);
            if (cancelRequested.contains(id) || pauseRequested.contains(id)) {
                aiClient.cancelExtractJob(jobId); // 提交的同时用户点了取消 / 暂停
            }
            poll(id, jobId);
        });
    }

    private interface Step {
        void run() throws Exception;
    }

    private void guarded(Long id, Step step) {
        try {
            step.run();
        } catch (ResourceAccessException e) {
            log.error("AI 服务不可达，compileId={}", id, e);
            interrupt(id, "AI 服务不可达（请确认 python-service 已启动）");
        } catch (RestClientResponseException e) {
            // 不记录响应体（422 回显里可能有 API Key）；400 是本服务自己的说明
            log.error("AI 服务拒绝整理任务，compileId={}，HTTP {}", id, e.getStatusCode().value());
            interrupt(id, "AI 服务拒绝任务：" + rejectReason(e));
        } catch (BizException e) {
            update(id, NovelExtract.FAILED, null, e.getMessage(), null);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (Exception e) {
            log.error("整理卡片失败，compileId={}", id, e);
            interrupt(id, "整理出错：" + e.getMessage());
        } finally {
            cancelRequested.remove(id);
            pauseRequested.remove(id);
        }
    }

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

    private void poll(Long id, String jobId) throws Exception {
        int unreachable = 0;
        while (!Thread.currentThread().isInterrupted()) {
            Thread.sleep(POLL_INTERVAL_MS);
            JsonNode job;
            try {
                job = aiClient.getExtractJob(jobId);
                unreachable = 0;
            } catch (HttpClientErrorException.NotFound e) {
                interrupt(id, "AI 服务已重启，整理中断");
                return;
            } catch (ResourceAccessException e) {
                if (++unreachable >= MAX_UNREACHABLE) {
                    throw e;
                }
                continue;
            }
            int progress = job.path("progress").asInt();
            switch (job.path("status").asText()) {
                case "succeeded" -> {
                    finish(id, job.path("result"));
                    return;
                }
                case "failed" -> {
                    update(id, NovelExtract.INTERRUPTED, progress, "整理出错：" + job.path("error").asText() + RESUME_HINT, null);
                    return;
                }
                case "cancelled" -> {
                    if (pauseRequested.remove(id)) {
                        update(id, NovelExtract.INTERRUPTED, progress, "已暂停" + RESUME_HINT, null);
                    } else {
                        update(id, NovelExtract.FAILED, progress, "已取消", null);
                        deleteCheckpoint(id);
                    }
                    return;
                }
                default -> update(id, NovelExtract.RUNNING, progress, job.path("message").asText(), null);
            }
        }
    }

    /** 成功：卡片 → 待确认候选（同书已有的跳过）→ 记统计 → 删断点 */
    private void finish(Long id, JsonNode result) {
        MaterialCompile c = require(id);
        NovelExtract task = extractMapper.selectById(c.getExtractId());
        FileInfo file = task == null ? null : fileService.getById(task.getFileId());
        MaterialService.CandidateStats stats = materialService.createCandidates(c.getExtractId(), task == null ? null : task.getFileId(),
                file == null ? (task == null ? null : task.getFileName()) : file.getFileName(), result);
        JsonNode st = result.path("stats");
        int cards = st.path("cards").asInt() + st.path("systems").asInt();
        int arcs = st.path("arcs").asInt();
        StringBuilder msg = new StringBuilder("整理完成：").append(cards).append(" 张素材卡、").append(arcs).append(" 个剧情段");
        if (stats.created() > 0) {
            msg.append("，").append(stats.created()).append(" 条待确认");
        }
        if (stats.duplicates() > 0) {
            msg.append("；跳过与本书已有候选 / 素材重复的 ").append(stats.duplicates()).append(" 条");
        }
        if (st.path("notUseful").asInt() > 0) {
            msg.append("；").append(st.path("notUseful").asInt()).append(" 个实体信息太空泛未放入");
        }
        if (st.path("failedCards").asInt() > 0) {
            msg.append("；").append(st.path("failedCards").asInt()).append(" 批整理失败已跳过");
        }
        MaterialCompile patch = new MaterialCompile();
        patch.setId(id);
        patch.setStatus(NovelExtract.SUCCEEDED);
        patch.setProgress(100);
        patch.setMessage(msg.toString());
        patch.setCardCount(cards);
        patch.setArcCount(arcs);
        patch.setCandidateCount(stats.created());
        patch.setUpdateTime(LocalDateTime.now());
        compileMapper.updateById(patch);
        deleteCheckpoint(id);
    }

    private void deleteCheckpoint(Long id) {
        try {
            aiClient.deleteExtractCheckpoint(checkpointKey(id));
        } catch (Exception e) {
            log.warn("删除整理断点失败，compileId={}：{}", id, e.getMessage());
        }
    }

    private static String checkpointKey(Long id) {
        return "k" + id;
    }

    private void interrupt(Long id, String reason) {
        update(id, NovelExtract.INTERRUPTED, null, reason + RESUME_HINT, null);
    }

    private void update(Long id, String status, Integer progress, String message, String jobId) {
        MaterialCompile patch = new MaterialCompile();
        patch.setId(id);
        patch.setStatus(status);
        patch.setProgress(progress);
        patch.setMessage(message != null && message.length() > 1000 ? message.substring(0, 1000) : message);
        patch.setJobId(jobId);
        patch.setUpdateTime(LocalDateTime.now());
        compileMapper.updateById(patch);
    }

    private String writeJson(Object v) {
        try {
            return objectMapper.writeValueAsString(v);
        } catch (Exception e) {
            throw new BizException(500, "参数无法保存");
        }
    }
}
