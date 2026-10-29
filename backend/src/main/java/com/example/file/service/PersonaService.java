package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.FileInfo;
import com.example.file.entity.NovelExtract;
import com.example.file.entity.PersonaAdaptation;
import com.example.file.entity.PersonaCard;
import com.example.file.entity.PersonaCardVersion;
import com.example.file.entity.PersonaChat;
import com.example.file.mapper.NovelExtractMapper;
import com.example.file.mapper.PersonaAdaptationMapper;
import com.example.file.mapper.PersonaCardMapper;
import com.example.file.mapper.PersonaCardVersionMapper;
import com.example.file.mapper.PersonaChatMapper;
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
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 跨世界观角色卡：原型卡（提取任务、版本）、适配版本（生成、编辑、确认、用于工作区、辨识度测试）、试聊会话。
 * 模型调用都在 Python（app/persona.py）；这里负责存储、版本、出处规则和任务状态。
 * <ul>
 *   <li>原型版本只追加：编辑后保存 = 新版本；改过的特征 / 规则出处改为 user，保留 AI 原文（aiText）。</li>
 *   <li>适配版本单独一行：改它不碰原型；原型出了新版本时标 prototypeUpdated。</li>
 *   <li>用于工作区：把适配版本的快照写进 Python 的 novel.personas（生成时不依赖 Java）。</li>
 * </ul>
 */
@Service
public class PersonaService {

    private static final Logger log = LoggerFactory.getLogger(PersonaService.class);

    private static final long POLL_INTERVAL_MS = 3000;
    private static final int MAX_UNREACHABLE = 20;
    private static final int MAX_TEXT = 600_000;
    private static final int KEEP_TESTS = 10;
    private static final String RESUME_HINT = "：可点「继续」从断点接着提取，或删除";

    private final PersonaCardMapper cardMapper;
    private final PersonaCardVersionMapper versionMapper;
    private final PersonaAdaptationMapper adaptationMapper;
    private final PersonaChatMapper chatMapper;
    private final NovelExtractMapper extractMapper;
    private final NovelExtractService extractService;
    private final ExtractResultStore resultStore;
    private final FileService fileService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "persona");
        t.setDaemon(true);
        return t;
    });
    private final Set<Long> stopRequested = ConcurrentHashMap.newKeySet();

    public PersonaService(PersonaCardMapper cardMapper, PersonaCardVersionMapper versionMapper,
                          PersonaAdaptationMapper adaptationMapper, PersonaChatMapper chatMapper,
                          NovelExtractMapper extractMapper, NovelExtractService extractService,
                          ExtractResultStore resultStore, FileService fileService, AiServiceClient aiClient,
                          ObjectMapper objectMapper) {
        this.cardMapper = cardMapper;
        this.versionMapper = versionMapper;
        this.adaptationMapper = adaptationMapper;
        this.chatMapper = chatMapper;
        this.extractMapper = extractMapper;
        this.extractService = extractService;
        this.resultStore = resultStore;
        this.fileService = fileService;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    /** 重启：没跑完的提取记为中断（可继续），没跑完的测试记为失败（重跑即可） */
    @EventListener(ApplicationReadyEvent.class)
    public void markInterrupted() {
        cardMapper.update(null, new LambdaUpdateWrapper<PersonaCard>().eq(PersonaCard::getStatus, PersonaCard.EXTRACTING)
                .set(PersonaCard::getStatus, PersonaCard.INTERRUPTED)
                .set(PersonaCard::getMessage, "服务重启，提取中断" + RESUME_HINT)
                .set(PersonaCard::getUpdateTime, LocalDateTime.now()));
        adaptationMapper.update(null, new LambdaUpdateWrapper<PersonaAdaptation>()
                .eq(PersonaAdaptation::getTestStatus, "RUNNING")
                .set(PersonaAdaptation::getTestStatus, "FAILED").set(PersonaAdaptation::getTestMessage, "服务重启，测试中断"));
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    // ================================================================== 原型卡

    public List<PersonaCard> list(String keyword, String tag) {
        LambdaQueryWrapper<PersonaCard> q = new LambdaQueryWrapper<PersonaCard>().orderByDesc(PersonaCard::getUpdateTime);
        if (keyword != null && !keyword.isBlank()) {
            String k = keyword.trim();
            q.and(w -> w.like(PersonaCard::getName, k).or().like(PersonaCard::getSummary, k).or().like(PersonaCard::getAliases, k));
        }
        if (tag != null && !tag.isBlank()) {
            q.like(PersonaCard::getTags, "\"" + tag.trim() + "\"");
        }
        List<PersonaCard> cards = cardMapper.selectList(q);
        cards.forEach(this::decorateCounts);
        return cards;
    }

    private void decorateCounts(PersonaCard c) {
        c.setVersionCount(versionMapper.selectCount(new LambdaQueryWrapper<PersonaCardVersion>().eq(PersonaCardVersion::getCardId, c.getId())));
        c.setAdaptationCount(adaptationMapper.selectCount(new LambdaQueryWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getCardId, c.getId())));
    }

    /** 详情：当前版本内容 + 计数 */
    public PersonaCard get(Long id) {
        PersonaCard c = requireCard(id);
        decorateCounts(c);
        if (c.getCurrentVersion() != null) {
            PersonaCardVersion v = version(id, c.getCurrentVersion());
            c.setContent(v.getContent());
        }
        return c;
    }

    private PersonaCard requireCard(Long id) {
        PersonaCard c = cardMapper.selectById(id);
        if (c == null) {
            throw new BizException(404, "角色卡不存在：" + id);
        }
        return c;
    }

    /**
     * 从资料提取原型。req：{name, aliases?, kind?, tags?, source: {type: text|file|extract, text?, fileIds?, extractId?, entityKey?,
     * whole?}, maxBlocks?, chunkChars?, model}。立即返回 EXTRACTING 的卡，后台跑 Python 任务。
     */
    public PersonaCard startExtract(Map<String, Object> req) {
        Map<String, Object> src = asMap(req.get("source"));
        String type = Objects.toString(src.get("type"), "text");
        String name = trim(req.get("name"), 60);
        List<String> aliases = strings(req.get("aliases"), 20, 40);
        if ("extract".equals(type) && name.isEmpty()) {
            Map<String, Object> ent = extractEntity(src);
            name = trim(ent.get("name"), 60);
            aliases = strings(ent.get("aliases"), 20, 40);
        }
        if (name.isEmpty()) {
            throw new BizException(400, "请填写人物名字");
        }
        if ("text".equals(type) && trim(src.get("text"), MAX_TEXT).isEmpty()) {
            throw new BizException(400, "请粘贴关于这个人物的资料");
        }
        if ("file".equals(type) && longs(src.get("fileIds")).isEmpty()) {
            throw new BizException(400, "请选择文件");
        }
        extractService.resolveModel(asMap(req.get("model")).isEmpty() ? null : asMap(req.get("model"))); // 先校验模型
        Map<String, Object> source = new LinkedHashMap<>(src);
        String text = trim(src.get("text"), MAX_TEXT);
        source.remove("text");
        source.put("textChars", text.length());
        Map<String, Object> options = new LinkedHashMap<>();
        options.put("model", req.get("model"));
        options.put("maxBlocks", req.get("maxBlocks"));
        options.put("chunkChars", req.get("chunkChars"));
        options.put("text", text); // 继续时复用（只存在本机数据库里）
        PersonaCard c = new PersonaCard();
        c.setName(name);
        c.setAliases(aliases);
        c.setSource(source);
        c.setTags(strings(req.get("tags"), 20, 20));
        c.setKind(trim(req.get("kind"), 20));
        c.setStatus(PersonaCard.EXTRACTING);
        c.setProgress(0);
        c.setMessage("排队中");
        c.setOptions(json(options));
        c.setCreateTime(LocalDateTime.now());
        c.setUpdateTime(c.getCreateTime());
        cardMapper.insert(c);
        executor.submit(() -> runExtract(c.getId()));
        return c;
    }

    /** 新建一张空白原型卡（手写） */
    public PersonaCard createBlank(Map<String, Object> req) {
        String name = trim(req.get("name"), 60);
        if (name.isEmpty()) {
            throw new BizException(400, "请填写人物名字");
        }
        PersonaCard c = new PersonaCard();
        c.setName(name);
        c.setAliases(strings(req.get("aliases"), 20, 40));
        c.setSource(Map.of("type", "manual"));
        c.setTags(strings(req.get("tags"), 20, 20));
        c.setKind(trim(req.get("kind"), 20));
        c.setStatus(PersonaCard.READY);
        c.setProgress(100);
        c.setCreateTime(LocalDateTime.now());
        c.setUpdateTime(c.getCreateTime());
        cardMapper.insert(c);
        Map<String, Object> content = new LinkedHashMap<>();
        content.put("name", name);
        content.put("aliases", c.getAliases());
        content.put("traits", List.of());
        content.put("rules", List.of());
        content.put("coreConfirmed", false);
        addVersion(c, content, "user", "手动新建");
        return get(c.getId());
    }

    private Map<String, Object> extractEntity(Map<String, Object> src) {
        Long extractId = toLong(src.get("extractId"));
        String key = trim(src.get("entityKey"), 200);
        NovelExtract task = extractId == null ? null : extractMapper.selectById(extractId);
        if (task == null || task.getResultPath() == null) {
            throw new BizException(400, "提取任务不存在或还没完成");
        }
        ExtractResultStore.Loaded loaded = resultStore.read(task.getResultPath(), task.getResultSha256());
        if (loaded.json() == null) {
            throw new BizException(400, "提取结果无法读取：" + loaded.problem());
        }
        try {
            JsonNode result = objectMapper.readTree(loaded.json());
            for (JsonNode e : result.path("entities")) {
                if (key.equals(e.path("key").asText())) {
                    Map<String, Object> ent = objectMapper.convertValue(e, Map.class);
                    ent.put("fileId", task.getFileId());
                    return ent;
                }
            }
        } catch (Exception e) {
            throw new BizException(400, "提取结果无法读取");
        }
        throw new BizException(404, "提取结果里没有这个人物：" + key);
    }

    /** 继续中断 / 失败的提取：同一断点键 p<id>，已读完的块不重做 */
    public PersonaCard resumeExtract(Long id) {
        PersonaCard c = requireCard(id);
        if (!PersonaCard.INTERRUPTED.equals(c.getStatus()) && !PersonaCard.FAILED.equals(c.getStatus())) {
            throw new BizException(400, "只有中断 / 失败的提取可以继续");
        }
        updateCard(id, PersonaCard.EXTRACTING, null, "排队中（继续提取）", null);
        executor.submit(() -> runExtract(id));
        return get(id);
    }

    /** 停止提取：Python 停在当前块之后，记为中断（断点保留） */
    public PersonaCard stopExtract(Long id) {
        PersonaCard c = requireCard(id);
        if (!PersonaCard.EXTRACTING.equals(c.getStatus())) {
            throw new BizException(400, "这张卡没有在提取");
        }
        stopRequested.add(id);
        if (c.getJobId() != null && !c.getJobId().isBlank()) {
            try {
                aiClient.cancelExtractJob(c.getJobId());
            } catch (Exception e) {
                stopRequested.remove(id);
                updateCard(id, PersonaCard.INTERRUPTED, null, "已停止" + RESUME_HINT, null);
            }
        }
        return get(id);
    }

    public void deleteCard(Long id) {
        PersonaCard c = requireCard(id);
        if (PersonaCard.EXTRACTING.equals(c.getStatus())) {
            throw new BizException(400, "正在提取，先停止再删除");
        }
        List<Long> adaptationIds = adaptationMapper.selectList(new LambdaQueryWrapper<PersonaAdaptation>()
                .select(PersonaAdaptation::getId).eq(PersonaAdaptation::getCardId, id)).stream().map(PersonaAdaptation::getId).toList();
        if (!adaptationIds.isEmpty()) {
            chatMapper.delete(new LambdaQueryWrapper<PersonaChat>().in(PersonaChat::getAdaptationId, adaptationIds));
        }
        cardMapper.deleteById(id);
        versionMapper.delete(new LambdaQueryWrapper<PersonaCardVersion>().eq(PersonaCardVersion::getCardId, id));
        adaptationMapper.delete(new LambdaQueryWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getCardId, id));
        chatMapper.delete(new LambdaQueryWrapper<PersonaChat>().eq(PersonaChat::getCardId, id));
        try {
            aiClient.deleteExtractCheckpoint("p" + id);
        } catch (Exception ignored) {
            // 断点删不掉不影响
        }
    }

    /** 改名称 / 别名 / 分类 / 标签（不产生新版本） */
    public PersonaCard updateMeta(Long id, Map<String, Object> req) {
        PersonaCard c = requireCard(id);
        if (req.containsKey("name") && !trim(req.get("name"), 60).isEmpty()) {
            c.setName(trim(req.get("name"), 60));
        }
        if (req.containsKey("aliases")) {
            c.setAliases(strings(req.get("aliases"), 20, 40));
        }
        if (req.containsKey("tags")) {
            c.setTags(strings(req.get("tags"), 20, 20));
        }
        if (req.containsKey("kind")) {
            c.setKind(trim(req.get("kind"), 20));
        }
        c.setUpdateTime(LocalDateTime.now());
        c.setCurrentVersion(null); // 不写回（null 字段不更新）：避免和并发保存的新版本打架
        c.setStatus(null);
        c.setProgress(null);
        c.setMessage(null);
        c.setJobId(null);
        cardMapper.updateById(c);
        return get(id);
    }

    private void runExtract(Long id) {
        try {
            PersonaCard c = requireCard(id);
            if (stopRequested.remove(id)) {
                updateCard(id, PersonaCard.INTERRUPTED, null, "已停止" + RESUME_HINT, null);
                return;
            }
            JsonNode opts = objectMapper.readTree(Objects.requireNonNullElse(c.getOptions(), "{}"));
            Map<String, Object> src = c.getSource() == null ? Map.of() : c.getSource();
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("kind", "extract");
            body.put("name", c.getName());
            body.put("aliases", c.getAliases() == null ? List.of() : c.getAliases());
            body.put("whole", Boolean.TRUE.equals(src.get("whole")));
            body.put("text", opts.path("text").asText(""));
            List<Map<String, Object>> files = new ArrayList<>();
            List<Long> fileIds = new ArrayList<>(longs(src.get("fileIds")));
            if ("extract".equals(src.get("type"))) {
                Map<String, Object> ent = extractEntity(src);
                body.put("seedFacts", ent.get("facts") == null ? List.of() : ent.get("facts"));
                if (ent.get("fileId") instanceof Number n && !fileIds.contains(n.longValue())) {
                    fileIds.add(n.longValue());
                }
            }
            for (Long fid : fileIds) {
                FileInfo f = fileService.getById(fid);
                files.add(Map.of("id", fid, "ext", Objects.requireNonNullElse(f.getFileExt(), "txt")));
            }
            body.put("files", files);
            if (opts.path("maxBlocks").isNumber()) {
                body.put("maxBlocks", opts.path("maxBlocks").asInt());
            }
            if (opts.path("chunkChars").isNumber()) {
                body.put("chunkChars", opts.path("chunkChars").asInt());
            }
            body.put("resumeKey", "p" + id);
            @SuppressWarnings("unchecked")
            Map<String, Object> model = opts.path("model").isObject() ? objectMapper.convertValue(opts.path("model"), Map.class) : null;
            NovelExtractService.ModelChoice choice = extractService.resolveModel(model);
            JsonNode job = aiClient.submitPersonaJob(body, choice.config(), choice.local(), null);
            String jobId = job.path("jobId").asText();
            updateCard(id, PersonaCard.EXTRACTING, 0, "已提交 AI 服务（" + choice.label() + "）", jobId);
            if (stopRequested.contains(id)) {
                aiClient.cancelExtractJob(jobId);
            }
            JsonNode result = poll(jobId, (p, m) -> updateCard(id, PersonaCard.EXTRACTING, p, m, null),
                    () -> stopRequested.remove(id));
            if (result == null) {
                return; // poll 已经处理（取消 / 中断）
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> proto = objectMapper.convertValue(result.path("prototype"), Map.class);
            JsonNode st = result.path("stats");
            PersonaCard fresh = requireCard(id);
            addVersion(fresh, proto, "ai", "AI 提取"); // 先写版本再标「就绪」：不会出现就绪了却没有内容
            fresh = requireCard(id);
            fresh.setSummary(trim(proto.get("summary"), 200));
            if ((fresh.getKind() == null || fresh.getKind().isBlank()) && proto.get("kind") != null) {
                fresh.setKind(trim(proto.get("kind"), 20));
            }
            fresh.setStatus(PersonaCard.READY);
            fresh.setProgress(100);
            fresh.setMessage("提取完成：" + st.path("traits").asInt() + " 条特征、" + st.path("rules").asInt() + " 条行为规则；核实通过 "
                    + st.path("verified").asInt() + " 条证据，丢弃 " + st.path("dropped").asInt() + " 条对不上原文的"
                    + (st.path("sampled").asBoolean() ? "（提及太多，按开头 / 中段 / 结尾抽样读了 " + st.path("blocks").asInt() + " 块）" : ""));
            fresh.setUpdateTime(LocalDateTime.now());
            cardMapper.updateById(fresh);
            try {
                aiClient.deleteExtractCheckpoint("p" + id);
            } catch (Exception ignored) {
                // 断点留着不影响
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (ResourceAccessException e) {
            updateCard(id, PersonaCard.INTERRUPTED, null, "AI 服务不可达" + RESUME_HINT, null);
        } catch (RestClientResponseException e) {
            log.error("AI 服务拒绝角色卡提取，cardId={}，HTTP {}", id, e.getStatusCode().value());
            updateCard(id, PersonaCard.INTERRUPTED, null, "AI 服务拒绝任务：" + rejectReason(e) + RESUME_HINT, null);
        } catch (BizException e) {
            updateCard(id, PersonaCard.FAILED, null, e.getMessage(), null);
        } catch (JobFailed e) {
            updateCard(id, PersonaCard.INTERRUPTED, null, "提取出错：" + e.getMessage() + RESUME_HINT, null);
        } catch (Exception e) {
            log.error("角色卡提取失败，cardId={}", id, e);
            updateCard(id, PersonaCard.INTERRUPTED, null, "提取出错：" + e.getMessage() + RESUME_HINT, null);
        } finally {
            stopRequested.remove(id);
        }
    }

    private static class JobFailed extends RuntimeException {
        JobFailed(String m) {
            super(m);
        }
    }

    private interface Progress {
        void on(int progress, String message);
    }

    private interface StopCheck {
        boolean stopped();
    }

    /** 轮询 Python 任务：成功返回 result；被取消返回 null（调用方已标状态）；失败抛 JobFailed */
    private JsonNode poll(String jobId, Progress progress, StopCheck cancelled) throws InterruptedException {
        int unreachable = 0;
        while (!Thread.currentThread().isInterrupted()) {
            Thread.sleep(POLL_INTERVAL_MS);
            JsonNode job;
            try {
                job = aiClient.getExtractJob(jobId);
                unreachable = 0;
            } catch (HttpClientErrorException.NotFound e) {
                throw new JobFailed("AI 服务已重启，任务中断");
            } catch (ResourceAccessException e) {
                if (++unreachable >= MAX_UNREACHABLE) {
                    throw e;
                }
                continue;
            }
            switch (job.path("status").asText()) {
                case "succeeded" -> {
                    return job.path("result");
                }
                case "failed" -> throw new JobFailed(job.path("error").asText());
                case "cancelled" -> {
                    cancelled.stopped();
                    throw new JobFailed("已停止");
                }
                default -> progress.on(job.path("progress").asInt(), job.path("message").asText());
            }
        }
        throw new InterruptedException();
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

    private void updateCard(Long id, String status, Integer progress, String message, String jobId) {
        PersonaCard patch = new PersonaCard();
        patch.setId(id);
        patch.setStatus(status);
        patch.setProgress(progress);
        patch.setMessage(message != null && message.length() > 1000 ? message.substring(0, 1000) : message);
        patch.setJobId(jobId);
        patch.setUpdateTime(LocalDateTime.now());
        cardMapper.updateById(patch);
    }

    // ------------------------------------------------------------------ 版本

    public List<PersonaCardVersion> versions(Long cardId) {
        requireCard(cardId);
        return versionMapper.selectList(new LambdaQueryWrapper<PersonaCardVersion>()
                .select(PersonaCardVersion::getId, PersonaCardVersion::getCardId, PersonaCardVersion::getVersionNo,
                        PersonaCardVersion::getAuthor, PersonaCardVersion::getNote, PersonaCardVersion::getCreateTime)
                .eq(PersonaCardVersion::getCardId, cardId).orderByDesc(PersonaCardVersion::getVersionNo));
    }

    public PersonaCardVersion version(Long cardId, int no) {
        PersonaCardVersion v = versionMapper.selectOne(new LambdaQueryWrapper<PersonaCardVersion>()
                .eq(PersonaCardVersion::getCardId, cardId).eq(PersonaCardVersion::getVersionNo, no));
        if (v == null) {
            throw new BizException(404, "版本不存在：v" + no);
        }
        return v;
    }

    /**
     * 保存编辑 = 新版本。和当前版本相比：文字改过的特征 / 规则出处改为 user（保留 AI 原文 aiText），新增的也是 user。
     * 出处由这里判定，前端传什么都以这里为准。
     */
    @SuppressWarnings("unchecked")
    public PersonaCard saveVersion(Long cardId, Map<String, Object> content, String note) {
        PersonaCard c = requireCard(cardId);
        if (content == null || !(content.get("traits") instanceof List<?>)) {
            throw new BizException(400, "角色卡内容不正确（缺少 traits）");
        }
        Map<String, Object> prev = c.getCurrentVersion() == null ? Map.of() : version(cardId, c.getCurrentVersion()).getContent();
        Map<String, Map<String, Object>> prevTraits = byId(prev.get("traits"));
        for (Object o : (List<Object>) content.get("traits")) {
            if (o instanceof Map<?, ?> m) {
                markEdited((Map<String, Object>) m, prevTraits.get(String.valueOf(m.get("id"))), "text");
            }
        }
        Map<String, Map<String, Object>> prevRules = byId(prev.get("rules"));
        if (content.get("rules") instanceof List<?> rules) {
            for (Object o : rules) {
                if (o instanceof Map<?, ?> m) {
                    markEdited((Map<String, Object>) m, prevRules.get(String.valueOf(m.get("id"))), "reaction", "situation");
                }
            }
        }
        content.put("name", c.getName());
        addVersion(c, content, "user", trim(note, 200));
        if (content.get("summary") != null) { // 只改简介：c 里的 currentVersion 已经过期，不能整行写回
            cardMapper.update(null, new LambdaUpdateWrapper<PersonaCard>().eq(PersonaCard::getId, cardId)
                    .set(PersonaCard::getSummary, trim(content.get("summary"), 200)));
        }
        return get(cardId);
    }

    /** 恢复旧版本：把它的内容另存为最新版本（旧版本本身不变） */
    public PersonaCard restoreVersion(Long cardId, int no) {
        PersonaCard c = requireCard(cardId);
        addVersion(c, new LinkedHashMap<>(version(cardId, no).getContent()), "user", "恢复自 v" + no);
        return get(cardId);
    }

    private static Map<String, Map<String, Object>> byId(Object list) {
        Map<String, Map<String, Object>> out = new HashMap<>();
        if (list instanceof List<?> l) {
            for (Object o : l) {
                if (o instanceof Map<?, ?> m && m.get("id") != null) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> mm = (Map<String, Object>) m;
                    out.put(String.valueOf(m.get("id")), mm);
                }
            }
        }
        return out;
    }

    private static void markEdited(Map<String, Object> item, Map<String, Object> prev, String... fields) {
        if (prev == null) { // 新增的：一律是作者写的
            item.put("provenance", "user");
            item.put("editedBy", "user");
            item.remove("evidence");
            return;
        }
        boolean changed = false;
        for (String f : fields) {
            changed |= !Objects.equals(Objects.toString(item.get(f), ""), Objects.toString(prev.get(f), ""));
        }
        if (changed) {
            if ("ai".equals(prev.get("editedBy")) && Objects.toString(prev.get("aiText"), "").isEmpty()) {
                item.put("aiText", prev.get(fields[0]));
            }
            item.put("provenance", "user");
            item.put("editedBy", "user");
        } else {
            item.put("provenance", prev.get("provenance")); // 没改：出处不能由前端改
            item.put("evidence", prev.get("evidence"));
        }
    }

    private void addVersion(PersonaCard c, Map<String, Object> content, String author, String note) {
        Integer max = versionMapper.selectList(new LambdaQueryWrapper<PersonaCardVersion>()
                        .select(PersonaCardVersion::getVersionNo).eq(PersonaCardVersion::getCardId, c.getId()))
                .stream().map(PersonaCardVersion::getVersionNo).max(Integer::compare).orElse(0);
        PersonaCardVersion v = new PersonaCardVersion();
        v.setCardId(c.getId());
        v.setVersionNo(max + 1);
        v.setContent(content);
        v.setAuthor(author);
        v.setNote(note);
        v.setCreateTime(LocalDateTime.now());
        versionMapper.insert(v);
        cardMapper.update(null, new LambdaUpdateWrapper<PersonaCard>().eq(PersonaCard::getId, c.getId())
                .set(PersonaCard::getCurrentVersion, max + 1).set(PersonaCard::getUpdateTime, LocalDateTime.now()));
    }

    // ================================================================== 适配版本

    public List<PersonaAdaptation> adaptations(Long cardId) {
        PersonaCard c = requireCard(cardId);
        List<PersonaAdaptation> list = adaptationMapper.selectList(new LambdaQueryWrapper<PersonaAdaptation>()
                .eq(PersonaAdaptation::getCardId, cardId).orderByDesc(PersonaAdaptation::getUpdateTime));
        list.forEach(a -> a.setPrototypeUpdated(c.getCurrentVersion() != null && a.getBaseVersion() < c.getCurrentVersion()));
        return list;
    }

    public PersonaAdaptation adaptation(Long id) {
        PersonaAdaptation a = adaptationMapper.selectById(id);
        if (a == null) {
            throw new BizException(404, "适配版本不存在：" + id);
        }
        PersonaCard c = cardMapper.selectById(a.getCardId());
        a.setPrototypeUpdated(c != null && c.getCurrentVersion() != null && a.getBaseVersion() < c.getCurrentVersion());
        return a;
    }

    /**
     * 生成适配版本。req：{version?（默认当前版本）, novelId?（目标世界观 = 这个工作区的设定）, world?（手写世界观）, wish?, model}。
     * 原型的「核心 / 可变」必须先由作者确认（content.coreConfirmed）。
     */
    public PersonaAdaptation adapt(Long cardId, Map<String, Object> req) {
        PersonaCard c = requireCard(cardId);
        if (c.getCurrentVersion() == null) {
            throw new BizException(400, "这张卡还没有内容");
        }
        int no = req.get("version") instanceof Number n ? n.intValue() : c.getCurrentVersion();
        Map<String, Object> proto = version(cardId, no).getContent();
        if (!Boolean.TRUE.equals(proto.get("coreConfirmed"))) {
            throw new BizException(400, "请先在原型卡里确认哪些是核心特征、哪些可以改变（保存时勾选「已确认核心 / 可变」）");
        }
        String novelId = trim(req.get("novelId"), 64);
        String world = trim(req.get("world"), 8000);
        if (novelId.isEmpty() && world.isEmpty()) {
            throw new BizException(400, "请选择目标工作区，或写一段目标世界观");
        }
        NovelExtractService.ModelChoice choice = extractService.resolveModel(asMap(req.get("model")).isEmpty() ? null : asMap(req.get("model")));
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("prototype", proto);
        body.put("world", world);
        body.put("wish", trim(req.get("wish"), 500));
        if (!novelId.isEmpty()) {
            body.put("novelId", novelId);
        }
        JsonNode res = callPython(() -> aiClient.personaAdapt(body, choice.config(), choice.local()), "生成适配版本失败");
        @SuppressWarnings("unchecked")
        Map<String, Object> content = objectMapper.convertValue(res.path("adaptation"), Map.class);
        content.put("wish", trim(req.get("wish"), 500));
        content.put("history", List.of(Map.of("at", now(), "action", "AI 生成（" + choice.label() + "）")));
        PersonaAdaptation a = new PersonaAdaptation();
        a.setCardId(cardId);
        a.setBaseVersion(no);
        a.setName(trim(content.get("name"), 40).isEmpty() ? c.getName() : trim(content.get("name"), 40));
        a.setNovelId(novelId.isEmpty() ? null : novelId);
        a.setContent(content);
        a.setStatus(PersonaAdaptation.DRAFT);
        a.setCreateTime(LocalDateTime.now());
        a.setUpdateTime(a.getCreateTime());
        adaptationMapper.insert(a);
        return adaptation(a.getId());
    }

    /** 保存编辑：重新跑代码检查、重新拼 brief；改过之后回到草稿（需要重新确认） */
    @SuppressWarnings("unchecked")
    public PersonaAdaptation saveAdaptation(Long id, Map<String, Object> content) {
        PersonaAdaptation a = adaptation(id);
        if (content == null || !(content.get("core") instanceof List<?>)) {
            throw new BizException(400, "适配版本内容不正确");
        }
        Map<String, Object> proto = version(a.getCardId(), a.getBaseVersion()).getContent();
        JsonNode res = callPython(() -> aiClient.personaCheck(proto, content), "检查适配版本失败");
        Map<String, Object> checked = objectMapper.convertValue(res.path("adaptation"), Map.class);
        List<Object> history = new ArrayList<>(a.getContent().get("history") instanceof List<?> h ? (List<Object>) h : List.of());
        history.add(Map.of("at", now(), "action", "作者修改"));
        checked.put("history", history);
        a.setContent(checked);
        // 只改这几列：整行写回会覆盖正在跑的测试状态
        adaptationMapper.update(null, new LambdaUpdateWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getId, id)
                .set(PersonaAdaptation::getContent, json(checked))
                .set(PersonaAdaptation::getName, trim(checked.get("name"), 40).isEmpty() ? a.getName() : trim(checked.get("name"), 40))
                .set(PersonaAdaptation::getStatus, PersonaAdaptation.DRAFT)
                .set(PersonaAdaptation::getUpdateTime, LocalDateTime.now()));
        return adaptation(id);
    }

    public PersonaAdaptation confirm(Long id) {
        adaptation(id);
        adaptationMapper.update(null, new LambdaUpdateWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getId, id)
                .set(PersonaAdaptation::getStatus, PersonaAdaptation.CONFIRMED)
                .set(PersonaAdaptation::getUpdateTime, LocalDateTime.now()));
        return adaptation(id);
    }

    public void deleteAdaptation(Long id) {
        adaptation(id);
        adaptationMapper.deleteById(id);
        chatMapper.delete(new LambdaQueryWrapper<PersonaChat>().eq(PersonaChat::getAdaptationId, id));
    }

    /**
     * 用于工作区：把快照写进 Python 的 novel.personas（同一适配版本或同名人物替换），记录 applied。
     * 只有确认过的适配版本可以用。→ {personas, card（给前端加进设定编辑器的角色卡）}
     */
    public Map<String, Object> apply(Long id, Map<String, Object> req) {
        PersonaAdaptation a = adaptation(id);
        if (!PersonaAdaptation.CONFIRMED.equals(a.getStatus())) {
            throw new BizException(400, "请先确认适配版本，再用于工作区");
        }
        String novelId = trim(req.get("novelId"), 64);
        if (novelId.isEmpty()) {
            novelId = Objects.requireNonNullElse(a.getNovelId(), "");
        }
        if (novelId.isEmpty()) {
            throw new BizException(400, "请选择工作区");
        }
        Map<String, Object> ct = a.getContent();
        String role = trim(req.get("role"), 40);
        if (role.isEmpty()) {
            role = trim(asMap(ct.get("card")).get("role"), 40);
        }
        String version = a.getUpdateTime() == null ? now() : a.getUpdateTime().withNano(0).toString().replace('T', ' ');
        Map<String, Object> snap = new LinkedHashMap<>();
        for (String k : List.of("name", "aliases", "identity", "core", "rules", "voice", "forbidden", "unknowns", "examples",
                "memories", "brief")) {
            snap.put(k, ct.get(k));
        }
        snap.put("name", a.getName());
        snap.put("adaptationId", a.getId());
        snap.put("version", version);
        snap.put("role", role);
        String nid = novelId;
        JsonNode current = callPython(() -> aiClient.getNovelPersonas(nid), "读取工作区的人物内核失败");
        List<Map<String, Object>> personas = new ArrayList<>();
        for (JsonNode p : current.path("data")) {
            if (p.path("adaptationId").asLong(-1) == a.getId() || a.getName().equals(p.path("name").asText())) {
                continue;
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> m = objectMapper.convertValue(p, Map.class);
            personas.add(m);
        }
        personas.add(snap);
        callPython(() -> aiClient.setNovelPersonas(nid, personas), "写入工作区失败");
        List<Map<String, Object>> applied = new ArrayList<>();
        for (Map<String, Object> x : a.getApplied() == null ? List.<Map<String, Object>>of() : a.getApplied()) {
            if (!nid.equals(x.get("novelId"))) {
                applied.add(x);
            }
        }
        applied.add(Map.of("novelId", nid, "version", version, "at", now(), "role", role));
        adaptationMapper.update(null, new LambdaUpdateWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getId, id)
                .set(PersonaAdaptation::getApplied, json(applied)));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("novelId", nid);
        out.put("personas", personas.size());
        out.put("card", ct.get("card"));
        out.put("name", a.getName());
        out.put("role", role);
        return out;
    }

    /** 从工作区移除人物内核快照 */
    public Map<String, Object> unapply(String novelId, String name) {
        JsonNode current = callPython(() -> aiClient.getNovelPersonas(novelId), "读取工作区的人物内核失败");
        List<Map<String, Object>> personas = new ArrayList<>();
        for (JsonNode p : current.path("data")) {
            if (!name.equals(p.path("name").asText())) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = objectMapper.convertValue(p, Map.class);
                personas.add(m);
            }
        }
        callPython(() -> aiClient.setNovelPersonas(novelId, personas), "写入工作区失败");
        return Map.of("personas", personas.size());
    }

    /** 工作区里用着的人物内核（附带是否落后于角色卡库里的适配版本） */
    public List<Map<String, Object>> novelPersonas(String novelId) {
        JsonNode current = callPython(() -> aiClient.getNovelPersonas(novelId), "读取工作区的人物内核失败");
        List<Map<String, Object>> out = new ArrayList<>();
        for (JsonNode p : current.path("data")) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", p.path("name").asText());
            m.put("role", p.path("role").asText());
            m.put("adaptationId", p.path("adaptationId").isNumber() ? p.path("adaptationId").asLong() : null);
            m.put("version", p.path("version").asText());
            PersonaAdaptation a = p.path("adaptationId").isNumber() ? adaptationMapper.selectById(p.path("adaptationId").asLong()) : null;
            String latest = a == null || a.getUpdateTime() == null ? null : a.getUpdateTime().withNano(0).toString().replace('T', ' ');
            m.put("outdated", latest != null && !latest.equals(p.path("version").asText()));
            m.put("cardId", a == null ? null : a.getCardId());
            out.add(m);
        }
        return out;
    }

    // ------------------------------------------------------------------ 辨识度测试

    /** 开始辨识度测试（后台）。req：{model, judgeConfigId?（评委改用这个大模型配置）} */
    public PersonaAdaptation startTest(Long id, Map<String, Object> req) {
        PersonaAdaptation a = adaptation(id);
        if ("RUNNING".equals(a.getTestStatus())) {
            throw new BizException(400, "测试已经在跑");
        }
        NovelExtractService.ModelChoice choice = extractService.resolveModel(asMap(req.get("model")).isEmpty() ? null : asMap(req.get("model")));
        Long judgeId = toLong(req.get("judgeConfigId"));
        com.example.file.entity.AiModelConfig judge = judgeId == null ? null
                : extractService.resolveModel(Map.of("source", "api", "configId", judgeId)).config();
        Map<String, Object> proto = version(a.getCardId(), a.getBaseVersion()).getContent();
        adaptationMapper.update(null, new LambdaUpdateWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getId, id)
                .set(PersonaAdaptation::getTestStatus, "RUNNING").set(PersonaAdaptation::getTestProgress, 0)
                .set(PersonaAdaptation::getTestMessage, "排队中（" + choice.label() + (judge != null ? "，评委 " + judge.getName() : "") + "）"));
        executor.submit(() -> runTest(id, proto, a.getContent(), choice, judge));
        return adaptation(id);
    }

    public PersonaAdaptation cancelTest(Long id) {
        PersonaAdaptation a = adaptation(id);
        if (a.getTestJobId() != null) {
            try {
                aiClient.cancelExtractJob(a.getTestJobId());
            } catch (Exception ignored) {
                // Python 那边已经没有了
            }
        }
        setTest(id, "FAILED", null, "已取消", null);
        return adaptation(id);
    }

    @SuppressWarnings("unchecked")
    private void runTest(Long id, Map<String, Object> proto, Map<String, Object> ad, NovelExtractService.ModelChoice choice,
                         com.example.file.entity.AiModelConfig judge) {
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("kind", "test");
            body.put("prototype", proto);
            body.put("adaptation", ad);
            JsonNode job = aiClient.submitPersonaJob(body, choice.config(), choice.local(), judge);
            String jobId = job.path("jobId").asText();
            setTest(id, "RUNNING", 0, "已提交 AI 服务", jobId);
            JsonNode result = poll(jobId, (p, m) -> setTest(id, "RUNNING", p, m, null), () -> true);
            Map<String, Object> report = objectMapper.convertValue(result, Map.class);
            report.put("at", now());
            report.put("model", choice.label());
            report.put("judge", judge == null ? choice.label() : judge.getName());
            PersonaAdaptation a = adaptationMapper.selectById(id);
            List<Map<String, Object>> tests = new ArrayList<>();
            tests.add(report);
            if (a.getTests() != null) {
                tests.addAll(a.getTests().subList(0, Math.min(KEEP_TESTS - 1, a.getTests().size())));
            }
            adaptationMapper.update(null, new LambdaUpdateWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getId, id)
                    .set(PersonaAdaptation::getTests, json(tests)));
            Map<String, Object> s = asMap(report.get("summary"));
            setTest(id, "SUCCEEDED", 100, "测试完成：A " + s.get("scoreA") + " 分 / 对照 " + s.get("scoreB") + " 分，评委选中 A "
                    + s.get("pickedA") + "，泄漏 " + s.get("leaks"), null);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (RestClientResponseException e) {
            setTest(id, "FAILED", null, "AI 服务拒绝任务：" + rejectReason(e), null);
        } catch (Exception e) {
            log.warn("辨识度测试失败，adaptationId={}：{}", id, e.getMessage());
            setTest(id, "FAILED", null, "测试失败：" + e.getMessage(), null);
        }
    }

    private void setTest(Long id, String status, Integer progress, String message, String jobId) {
        LambdaUpdateWrapper<PersonaAdaptation> u = new LambdaUpdateWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getId, id)
                .set(PersonaAdaptation::getTestStatus, status).set(PersonaAdaptation::getTestMessage, message);
        if (progress != null) {
            u.set(PersonaAdaptation::getTestProgress, progress);
        }
        if (jobId != null) {
            u.set(PersonaAdaptation::getTestJobId, jobId);
        }
        adaptationMapper.update(null, u);
    }

    // ================================================================== 试聊

    /**
     * 新建会话。req：{cardId? | adaptationId? | novelId + character{name, card, userRole?}, mode?, scene?, inner?}。
     */
    public PersonaChat startChat(Map<String, Object> req) {
        Long cardId = toLong(req.get("cardId"));
        Long adaptationId = toLong(req.get("adaptationId"));
        String novelId = trim(req.get("novelId"), 64);
        Map<String, Object> character = asMap(req.get("character"));
        String name = trim(character.get("name"), 40);
        if (adaptationId != null) {
            PersonaAdaptation a = adaptation(adaptationId);
            cardId = a.getCardId();
            name = a.getName();
        } else if (cardId != null) {
            name = requireCard(cardId).getName();
        } else if (novelId.isEmpty() || name.isEmpty()) {
            throw new BizException(400, "请指定原型卡、适配版本，或工作区里的角色");
        }
        PersonaChat s = new PersonaChat();
        s.setCardId(adaptationId != null ? null : cardId);
        s.setAdaptationId(adaptationId);
        s.setNovelId(novelId.isEmpty() ? null : novelId);
        s.setCharacterName(name);
        s.setCharacter(character);
        s.setMode(mode(req.get("mode")));
        s.setScene(asMap(req.get("scene")));
        s.setInnerOn(!Boolean.FALSE.equals(req.get("inner")));
        s.setMessages(new ArrayList<>());
        s.setSummarizedUpto(0);
        s.setCreateTime(LocalDateTime.now());
        s.setUpdateTime(s.getCreateTime());
        chatMapper.insert(s);
        String greeting = trim(character.get("greeting"), 1000);
        if (!greeting.isEmpty() && "free".equals(s.getMode())) {
            List<Map<String, Object>> msgs = new ArrayList<>();
            msgs.add(msg("assistant", greeting, ""));
            s.setMessages(msgs);
            chatMapper.updateById(s);
        }
        return chatMapper.selectById(s.getId());
    }

    public List<PersonaChat> chats(Long cardId, Long adaptationId, String novelId, String characterName) {
        LambdaQueryWrapper<PersonaChat> q = new LambdaQueryWrapper<PersonaChat>()
                .select(PersonaChat::getId, PersonaChat::getCardId, PersonaChat::getAdaptationId, PersonaChat::getNovelId,
                        PersonaChat::getCharacterName, PersonaChat::getMode, PersonaChat::getCreateTime, PersonaChat::getUpdateTime)
                .eq(cardId != null, PersonaChat::getCardId, cardId)
                .eq(adaptationId != null, PersonaChat::getAdaptationId, adaptationId)
                .eq(novelId != null && !novelId.isBlank(), PersonaChat::getNovelId, novelId)
                .eq(characterName != null && !characterName.isBlank(), PersonaChat::getCharacterName, characterName)
                .orderByDesc(PersonaChat::getUpdateTime).last("LIMIT 50");
        return chatMapper.selectList(q);
    }

    public PersonaChat chat(Long id) {
        PersonaChat s = chatMapper.selectById(id);
        if (s == null) {
            throw new BizException(404, "会话不存在：" + id);
        }
        return s;
    }

    public void deleteChat(Long id) {
        chat(id);
        chatMapper.deleteById(id);
    }

    /** 改模式 / 场景 / 内心开关 / 对方身份 */
    public PersonaChat updateChat(Long id, Map<String, Object> req) {
        PersonaChat s = chat(id);
        if (req.containsKey("mode")) {
            s.setMode(mode(req.get("mode")));
        }
        if (req.containsKey("scene")) {
            s.setScene(asMap(req.get("scene")));
        }
        if (req.containsKey("inner")) {
            s.setInnerOn(!Boolean.FALSE.equals(req.get("inner")));
        }
        if (req.containsKey("character")) {
            s.setCharacter(asMap(req.get("character")));
        }
        s.setUpdateTime(LocalDateTime.now());
        chatMapper.updateById(s);
        return chat(id);
    }

    /** 发一句话。req：{message, model, boost?（上次检查走偏了：这一轮加强锚点）} */
    public PersonaChat send(Long id, Map<String, Object> req) {
        PersonaChat s = chat(id);
        String text = trim(req.get("message"), 1000);
        if (text.isEmpty()) {
            throw new BizException(400, "请输入要说的话");
        }
        List<Map<String, Object>> msgs = new ArrayList<>(s.getMessages() == null ? List.of() : s.getMessages());
        msgs.add(msg("user", text, ""));
        return reply(s, msgs, req);
    }

    /** 换个回复：去掉最后一条角色回复重新生成 */
    public PersonaChat regenerate(Long id, Map<String, Object> req) {
        PersonaChat s = chat(id);
        List<Map<String, Object>> msgs = new ArrayList<>(s.getMessages() == null ? List.of() : s.getMessages());
        if (!msgs.isEmpty() && "assistant".equals(msgs.get(msgs.size() - 1).get("role"))) {
            msgs.remove(msgs.size() - 1);
        }
        if (msgs.isEmpty() || !"user".equals(msgs.get(msgs.size() - 1).get("role"))) {
            throw new BizException(400, "没有可以重新回复的话");
        }
        return reply(s, msgs, req);
    }

    @SuppressWarnings("unchecked")
    private PersonaChat reply(PersonaChat s, List<Map<String, Object>> msgs, Map<String, Object> req) {
        NovelExtractService.ModelChoice choice = extractService.resolveModel(asMap(req.get("model")).isEmpty() ? null : asMap(req.get("model")));
        Map<String, Object> body = new LinkedHashMap<>();
        Map<String, Object> character = new LinkedHashMap<>(s.getCharacter() == null ? Map.of() : s.getCharacter());
        character.putIfAbsent("name", s.getCharacterName());
        body.put("character", character);
        if (s.getAdaptationId() != null) {
            PersonaAdaptation a = adaptation(s.getAdaptationId());
            body.put("persona", a.getContent());
            body.put("world", Objects.toString(a.getContent().get("world"), ""));
        } else if (s.getCardId() != null) {
            PersonaCard c = get(s.getCardId());
            body.put("persona", c.getContent());
        }
        if (s.getNovelId() != null) {
            body.put("novelId", s.getNovelId());
        }
        body.put("mode", s.getMode());
        body.put("scene", s.getScene() == null ? Map.of() : s.getScene());
        body.put("inner", !Boolean.FALSE.equals(s.getInnerOn()));
        // 只发还没压进摘要的部分（前 summarizedUpto 条在 summary 里）
        int upto = s.getSummary() == null || s.getSummary().isBlank() || s.getSummarizedUpto() == null ? 0
                : Math.max(0, Math.min(s.getSummarizedUpto(), msgs.size() - 1));
        List<Map<String, Object>> history = new ArrayList<>();
        int pad = 0;
        if ("assistant".equals(msgs.get(upto).get("role"))) {
            history.add(Map.of("role", "user", "content", upto == 0 ? "（对话开始）" : "（接着之前的对话）")); // 兼容要求 user 先说话的接口
            pad = 1;
        }
        msgs.subList(upto, msgs.size()).forEach(m -> history.add(Map.of("role", m.get("role"), "content", Objects.toString(m.get("content"), ""))));
        body.put("messages", history);
        body.put("summary", Objects.toString(s.getSummary(), ""));
        body.put("boost", Boolean.TRUE.equals(req.get("boost")));
        JsonNode res = callPython(() -> aiClient.personaChat(body, choice.config(), choice.local()), "试聊失败");
        msgs.add(msg("assistant", res.path("reply").asText(), res.path("inner").asText("")));
        s.setMessages(msgs);
        if (res.path("summary").isTextual()) {
            s.setSummary(res.path("summary").asText());
            s.setSummarizedUpto(upto + Math.max(0, res.path("summarizedUpTo").asInt() - pad));
        }
        if (res.path("drift").isObject()) {
            Map<String, Object> drift = objectMapper.convertValue(res.path("drift"), Map.class);
            drift.put("at", now());
            drift.put("turn", msgs.size());
            s.setDrift(drift);
        }
        s.setUpdateTime(LocalDateTime.now());
        chatMapper.updateById(s);
        return chat(s.getId());
    }

    /**
     * 对一条回复打分。req：{index, rating: good|bad|null, reason?}。good 且会话属于适配版本：存为示例台词（context = 上一句）。
     */
    @SuppressWarnings("unchecked")
    public PersonaChat feedback(Long id, Map<String, Object> req) {
        PersonaChat s = chat(id);
        int index = req.get("index") instanceof Number n ? n.intValue() : -1;
        List<Map<String, Object>> msgs = new ArrayList<>(s.getMessages() == null ? List.of() : s.getMessages());
        if (index < 0 || index >= msgs.size() || !"assistant".equals(msgs.get(index).get("role"))) {
            throw new BizException(400, "只能给角色的回复打分");
        }
        Map<String, Object> m = new LinkedHashMap<>(msgs.get(index));
        String rating = trim(req.get("rating"), 10);
        m.put("rating", rating.isEmpty() ? null : rating);
        m.put("reason", trim(req.get("reason"), 200));
        msgs.set(index, m);
        s.setMessages(msgs);
        s.setUpdateTime(LocalDateTime.now());
        chatMapper.updateById(s);
        if ("good".equals(rating) && s.getAdaptationId() != null) {
            PersonaAdaptation a = adaptation(s.getAdaptationId());
            Map<String, Object> ct = new LinkedHashMap<>(a.getContent());
            List<Object> examples = new ArrayList<>(ct.get("examples") instanceof List<?> l ? (List<Object>) l : List.of());
            String context = index > 0 ? trim(msgs.get(index - 1).get("content"), 80) : "";
            String line = trim(m.get("content"), 200);
            if (examples.stream().noneMatch(e -> e instanceof Map<?, ?> em && line.equals(em.get("line")))) {
                examples.add(Map.of("context", context, "line", line, "fromChat", true));
                ct.put("examples", examples);
                adaptationMapper.update(null, new LambdaUpdateWrapper<PersonaAdaptation>().eq(PersonaAdaptation::getId, a.getId())
                        .set(PersonaAdaptation::getContent, json(ct)));
            }
        }
        return chat(id);
    }

    /** 试聊反馈汇总（某适配版本 / 原型卡所有会话里点了「不像他」的）：原因计数 + 例子，供作者补行为规则 */
    public Map<String, Object> feedbackSummary(Long cardId, Long adaptationId) {
        List<PersonaChat> sessions = chatMapper.selectList(new LambdaQueryWrapper<PersonaChat>()
                .eq(adaptationId != null, PersonaChat::getAdaptationId, adaptationId)
                .eq(adaptationId == null && cardId != null, PersonaChat::getCardId, cardId));
        Map<String, Integer> reasons = new LinkedHashMap<>();
        List<Map<String, Object>> examples = new ArrayList<>();
        int good = 0;
        for (PersonaChat s : sessions) {
            List<Map<String, Object>> msgs = s.getMessages() == null ? List.of() : s.getMessages();
            for (int i = 0; i < msgs.size(); i++) {
                Map<String, Object> m = msgs.get(i);
                if ("good".equals(m.get("rating"))) {
                    good++;
                } else if ("bad".equals(m.get("rating"))) {
                    String r = trim(m.get("reason"), 200);
                    reasons.merge(r.isEmpty() ? "不像他" : r, 1, Integer::sum);
                    if (examples.size() < 20) {
                        examples.add(Map.of("reason", r, "user", i > 0 ? trim(msgs.get(i - 1).get("content"), 120) : "",
                                "reply", trim(m.get("content"), 200), "chatId", s.getId()));
                    }
                }
            }
        }
        return Map.of("good", good, "reasons", reasons, "examples", examples);
    }

    // ================================================================== 工具

    private interface PythonCall {
        JsonNode call();
    }

    private JsonNode callPython(PythonCall fn, String what) {
        try {
            return fn.call();
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            // 不记录响应体：校验错误的回显里可能带有 API Key
            log.warn("{}：AI 服务返回 HTTP {}", what, e.getStatusCode().value());
            throw new BizException(400, what + "：" + rejectReason(e));
        }
    }

    private static Map<String, Object> msg(String role, String content, String inner) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("role", role);
        m.put("content", content);
        if (inner != null && !inner.isEmpty()) {
            m.put("inner", inner);
        }
        m.put("at", now());
        return m;
    }

    private static String mode(Object v) {
        String m = Objects.toString(v, "free");
        return Set.of("free", "scene", "interview").contains(m) ? m : "free";
    }

    private static String now() {
        return LocalDateTime.now().withNano(0).toString().replace('T', ' ');
    }

    private String json(Object v) {
        try {
            return objectMapper.writeValueAsString(v);
        } catch (Exception e) {
            throw new BizException(500, "数据无法保存");
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object v) {
        return v instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
    }

    private static String trim(Object v, int max) {
        String s = v == null ? "" : String.valueOf(v).trim();
        return s.length() > max ? s.substring(0, max) : s;
    }

    private static List<String> strings(Object v, int maxItems, int maxLen) {
        if (!(v instanceof List<?> list)) {
            return new ArrayList<>();
        }
        Set<String> seen = new HashSet<>();
        List<String> out = new ArrayList<>();
        for (Object o : list) {
            String s = trim(o, maxLen);
            if (!s.isEmpty() && seen.add(s) && out.size() < maxItems) {
                out.add(s);
            }
        }
        return out;
    }

    private static List<Long> longs(Object v) {
        List<Long> out = new ArrayList<>();
        if (v instanceof List<?> list) {
            for (Object o : list) {
                Long n = toLong(o);
                if (n != null) {
                    out.add(n);
                }
            }
        }
        return out;
    }

    private static Long toLong(Object v) {
        if (v instanceof Number n) {
            return n.longValue();
        }
        if (v instanceof String s && s.matches("\\d+")) {
            return Long.parseLong(s);
        }
        return null;
    }
}
