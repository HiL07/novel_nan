package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.Material;
import com.example.file.entity.NovelExtract;
import com.example.file.mapper.MaterialMapper;
import com.example.file.mapper.NovelExtractMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 素材量级（profile.tier 1–5，影响范围）的批量补全：灵感墙 / AI 构思按故事进度过滤素材时用。
 * <ul>
 *   <li>bookPos（首次出现在原书的位置）：代码从提取结果的章节列表算，不用模型；</li>
 *   <li>tier：每 {@value #BATCH} 条一次模型调用（大模型或 GGUF），后台单批、可暂停；作者手改过的（tierBy = user）不送、不覆盖。</li>
 * </ul>
 * 每批标完立刻落库，暂停 / 重启后再点一次只补还没标的。
 */
@Service
public class MaterialProfileService {

    private static final Logger log = LoggerFactory.getLogger(MaterialProfileService.class);

    static final int BATCH = 20;

    private final MaterialMapper materialMapper;
    private final NovelExtractMapper extractMapper;
    private final ExtractResultStore resultStore;
    private final NovelExtractService extractService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "material-profile");
        t.setDaemon(true);
        return t;
    });

    private volatile boolean running;
    private volatile boolean stopRequested;
    private volatile int total;
    private volatile int done;
    private volatile int failed;
    private volatile int positions;
    private volatile String lastError;

    public MaterialProfileService(MaterialMapper materialMapper, NovelExtractMapper extractMapper, ExtractResultStore resultStore,
                                  NovelExtractService extractService, AiServiceClient aiClient, ObjectMapper objectMapper) {
        this.materialMapper = materialMapper;
        this.extractMapper = extractMapper;
        this.resultStore = resultStore;
        this.extractService = extractService;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    /** {total, labeled, missing, byUser, running, …进度} */
    public Map<String, Object> status() {
        int all = 0, labeled = 0, byUser = 0;
        for (Material m : alive()) {
            all++;
            if (MaterialService.tierOf(m) != null) {
                labeled++;
            }
            if (m.getProfile() != null && "user".equals(m.getProfile().get("tierBy"))) {
                byUser++;
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", all);
        out.put("labeled", labeled);
        out.put("missing", all - labeled);
        out.put("byUser", byUser);
        out.put("running", running);
        out.put("batchTotal", total);
        out.put("done", done);
        out.put("failed", failed);
        out.put("positions", positions);
        out.put("lastError", lastError);
        return out;
    }

    /**
     * 开始补全。opts：{model: {source: api, configId?} | {source: gguf}, onlyMissing?（默认 true；false = AI 标的也重标，
     * 作者手改的永远不动）}
     */
    public synchronized Map<String, Object> start(Map<String, Object> opts) {
        if (running) {
            throw new BizException(400, "量级正在补全，请等它结束或先暂停");
        }
        Object model = opts == null ? null : opts.get("model");
        if (model instanceof Map<?, ?> mm && "local".equals(mm.get("source"))) {
            throw new BizException(400, "量级标注请用大模型或 GGUF（llama.cpp）");
        }
        @SuppressWarnings("unchecked")
        NovelExtractService.ModelChoice choice = extractService.resolveModel((Map<String, Object>) model);
        boolean onlyMissing = opts == null || !Boolean.FALSE.equals(opts.get("onlyMissing"));
        List<Material> todo = alive().stream()
                .filter(m -> m.getProfile() == null || !"user".equals(m.getProfile().get("tierBy")))
                .filter(m -> !onlyMissing || MaterialService.tierOf(m) == null)
                .toList();
        running = true;
        stopRequested = false;
        total = todo.size();
        done = 0;
        failed = 0;
        positions = 0;
        lastError = null;
        executor.submit(() -> run(todo, choice.config()));
        return status();
    }

    /** 暂停：当前这批标完后停下 */
    public Map<String, Object> stop() {
        stopRequested = true;
        return status();
    }

    private List<Material> alive() {
        return materialMapper.selectList(new LambdaQueryWrapper<Material>().isNull(Material::getMergedInto));
    }

    private void run(List<Material> todo, AiModelConfig cfg) {
        try {
            positions = backfillPositions();
            for (int i = 0; i < todo.size(); i += BATCH) {
                if (stopRequested || Thread.currentThread().isInterrupted()) {
                    break;
                }
                List<Material> batch = todo.subList(i, Math.min(todo.size(), i + BATCH));
                try {
                    JsonNode res = aiClient.materialProfile(batch.stream().map(MaterialProfileService::payload).toList(), cfg);
                    if (!res.path("ok").asBoolean()) {
                        lastError = res.path("message").asText();
                        failed += batch.size();
                        if (res.path("fatal").asBoolean()) {
                            break; // Key 无效 / 余额不足：后面的也不会成功
                        }
                        continue;
                    }
                    JsonNode tiers = res.path("tiers");
                    for (Material m : batch) {
                        JsonNode t = tiers.path(String.valueOf(m.getId()));
                        Integer tier = MaterialService.tierValue(t.path("tier").asInt(0));
                        if (tier == null) {
                            failed++;
                            continue;
                        }
                        Map<String, Object> p = new LinkedHashMap<>(m.getProfile() == null ? Map.of() : m.getProfile());
                        p.put("tier", tier);
                        p.put("tierReason", t.path("reason").asText(""));
                        p.put("tierBy", "ai");
                        if (writeProfile(m.getId(), p, true)) {
                            done++;
                        }
                    }
                } catch (ResourceAccessException e) {
                    lastError = "AI 服务不可达";
                    break;
                } catch (Exception e) {
                    log.warn("量级标注失败（第 {} 批）：{}", i / BATCH + 1, e.getMessage());
                    lastError = e.getMessage();
                    failed += batch.size();
                }
            }
        } finally {
            running = false;
        }
    }

    private static Map<String, Object> payload(Material m) {
        Map<String, Object> p = new HashMap<>();
        p.put("id", m.getId());
        p.put("category", m.getCategory());
        p.put("title", m.getTitle());
        p.put("summary", Objects.toString(m.getSummary(), ""));
        p.put("detail", Objects.toString(m.getDetail(), ""));
        p.put("attributes", m.getAttributes() == null ? Map.of() : m.getAttributes());
        return p;
    }

    /**
     * 写 profile。skipUser = 写之前再读一次：作者在标注过程中手改了量级（tierBy = user）就不覆盖。
     */
    private boolean writeProfile(Long id, Map<String, Object> profile, boolean skipUser) {
        if (skipUser) {
            Material now = materialMapper.selectById(id);
            if (now == null || now.getProfile() != null && "user".equals(now.getProfile().get("tierBy"))) {
                return false;
            }
        }
        try {
            materialMapper.update(null, new UpdateWrapper<Material>().eq("id", id)
                    .set("profile", objectMapper.writeValueAsString(profile)));
            return true;
        } catch (Exception e) {
            log.warn("保存素材 {} 的量级失败：{}", id, e.getMessage());
            return false;
        }
    }

    /**
     * 补 bookPos：来自提取的素材，最早一条事实（或 source.chapters 的第一章）在原书章节列表里的位置 ÷ 总章数。
     * 只算还没有 bookPos 的；提取结果读不到就跳过。→ 补了几条
     */
    int backfillPositions() {
        Map<Long, Map<String, Integer>> chapterIndex = new HashMap<>();
        int n = 0;
        for (Material m : alive()) {
            if (MaterialService.bookPosOf(m) != null || m.getSource() == null
                    || !(m.getSource().get("extractId") instanceof Number eid)) {
                continue;
            }
            Map<String, Integer> index = chapterIndex.computeIfAbsent(eid.longValue(), this::chapterIndex);
            if (index.isEmpty()) {
                continue;
            }
            Integer first = null;
            for (String title : chapterTitles(m)) {
                Integer ci = index.get(title);
                if (ci != null && (first == null || ci < first)) {
                    first = ci;
                }
            }
            if (first == null) {
                continue;
            }
            Map<String, Object> p = new LinkedHashMap<>(m.getProfile() == null ? Map.of() : m.getProfile());
            int last = index.values().stream().mapToInt(Integer::intValue).max().orElse(1);
            p.put("bookPos", Math.round(first * 1000.0 / Math.max(1, last)) / 1000.0);
            if (writeProfile(m.getId(), p, false)) {
                n++;
            }
        }
        return n;
    }

    private static List<String> chapterTitles(Material m) {
        List<String> out = new ArrayList<>();
        if (m.getSource().get("facts") instanceof List<?> facts) {
            for (Object f : facts) {
                if (f instanceof Map<?, ?> fm && fm.get("chapter") != null) {
                    out.add(String.valueOf(fm.get("chapter")));
                }
            }
        }
        if (m.getSource().get("chapters") instanceof List<?> chs) {
            chs.forEach(c -> out.add(String.valueOf(c)));
        }
        return out;
    }

    /** 提取结果的 章节标题 → 章号（同名取第一次） */
    private Map<String, Integer> chapterIndex(Long extractId) {
        NovelExtract task = extractMapper.selectById(extractId);
        if (task == null || task.getResultPath() == null) {
            return Map.of();
        }
        ExtractResultStore.Loaded loaded = resultStore.read(task.getResultPath(), task.getResultSha256());
        if (loaded.json() == null) {
            return Map.of();
        }
        try {
            JsonNode chapters = objectMapper.readTree(loaded.json()).path("chapters");
            Map<String, Integer> index = new HashMap<>();
            for (int i = 0; i < chapters.size(); i++) {
                index.putIfAbsent(chapters.get(i).path("title").asText(""), i);
            }
            return index;
        } catch (Exception e) {
            return Map.of();
        }
    }
}
