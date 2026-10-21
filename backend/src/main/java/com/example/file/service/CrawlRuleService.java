package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.file.common.BizException;
import com.example.file.common.DataPaths;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.CrawlSiteRule;
import com.example.file.mapper.CrawlSiteRuleMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.io.IOException;
import java.net.URI;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Supplier;

/**
 * AI 解析地址 + 学到的站点规则（crawl_site_rule）。
 * <p>
 * 用户给一本书的地址 → Python /api/crawl/ai/jobs 反复「写规则 → 试抓」直到成功或达到上限（模型配置用当前激活的大模型，
 * 随请求下发、不落库）。Java 在后台线程轮询该任务，成功后把规则存入 crawl_site_rule，状态为<b>待确认</b>
 * （同域名已有待确认的则覆盖它）；用户在「解析管理」里确认后才生效（替换该域名原来已确认的规则），
 * 之后抓取选「按域名自动选择」时 {@link NovelCrawlService} 会自动套用。浏览器关掉也不影响规则入库。
 * 每条规则另存一份 JSON 到 data/crawl-rules/&lt;host&gt;_&lt;id&gt;.json，方便查找 / 备份（数据库为准）。
 */
@Service
public class CrawlRuleService {

    private static final Logger log = LoggerFactory.getLogger(CrawlRuleService.class);

    private static final long POLL_INTERVAL_MS = 2000;
    /** 最长跟踪 30 分钟（10 次尝试 × 模型 + 试抓，正常几分钟内结束） */
    private static final long WATCH_LIMIT_MS = 30 * 60 * 1000L;
    /** 规则里允许保存 / 下发的字段（与 python-service/app/crawler/rules.py 的 CrawlRule 一致） */
    private static final Set<String> RULE_KEYS = Set.of("categoryLinks", "bookLinks", "listNext", "tocLink",
            "bookName", "author", "intro", "tags", "chapterLinks", "tocNext", "content", "contentNext", "encoding",
            "removePatterns");

    private final CrawlSiteRuleMapper mapper;
    private final AiServiceClient aiClient;
    private final AiModelConfigService modelService;
    private final ObjectMapper objectMapper;
    private final DataPaths dataPaths;
    private final ExecutorService watcher = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "crawl-ai-watch");
        t.setDaemon(true);
        return t;
    });
    /** jobId → 已保存的规则 id（防止轮询线程与前端查询重复保存） */
    private final Map<String, Long> savedJobs = new ConcurrentHashMap<>();

    public CrawlRuleService(CrawlSiteRuleMapper mapper, AiServiceClient aiClient, AiModelConfigService modelService,
                            ObjectMapper objectMapper, DataPaths dataPaths) {
        this.mapper = mapper;
        this.dataPaths = dataPaths;
        this.aiClient = aiClient;
        this.modelService = modelService;
        this.objectMapper = objectMapper;
    }

    @PreDestroy
    public void shutdown() {
        watcher.shutdownNow();
    }

    /** 启动后补齐规则文件（老数据 / 文件被删时），以数据库为准 */
    @EventListener(ApplicationReadyEvent.class)
    public void syncRuleFiles() {
        int n = 0;
        for (CrawlSiteRule rule : mapper.selectList(null)) {
            if (!CrawlSiteRule.FAILED.equals(rule.getStatus()) && !Files.exists(ruleFilePath(rule))) {
                writeRuleFile(rule);
                n++;
            }
        }
        if (n > 0) {
            log.info("已补写 {} 个站点规则文件到 data/{}/", n, DataPaths.CRAWL_RULES);
        }
    }

    // ---------------------------------------------------------------- AI 解析任务

    /**
     * 提交 AI 解析：{url, maxAttempts?(1~10, 默认 5), delayMs?, respectRobots?, hint?, useKnown?(默认 true)}。
     * 同域名已有<b>已确认</b>的规则时先试它（useKnown=false 则从头学）。
     */
    public JsonNode analyze(Map<String, Object> options) {
        if (options == null) {
            throw new BizException(400, "缺少参数");
        }
        String url = str(options.get("url"));
        if (url == null || hostOf(url) == null) {
            throw new BizException(400, "请输入 http:// 或 https:// 开头的书籍地址");
        }
        AiModelConfig cfg = modelService.requireActive();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("url", url);
        body.put("maxAttempts", clamp(options.get("maxAttempts"), 1, 10, 5));
        body.put("delayMs", clamp(options.get("delayMs"), 300, 30000, 1000));
        body.put("respectRobots", !Boolean.FALSE.equals(options.get("respectRobots")));
        String hint = str(options.get("hint"));
        if (hint != null && !hint.isEmpty()) {
            body.put("hint", hint.length() > 500 ? hint.substring(0, 500) : hint);
        }
        if (!Boolean.FALSE.equals(options.get("useKnown"))) {
            CrawlSiteRule known = findForUrl(url);
            if (known != null && known.getRule() != null && !known.getRule().isEmpty()) {
                body.put("knownRule", known.getRule());
            }
        }
        JsonNode job = callPython(() -> aiClient.submitCrawlAi(body, cfg));
        String jobId = job.path("jobId").asText();
        watcher.submit(() -> watch(jobId));
        log.info("AI 解析地址已提交 jobId={} url={} 上限 {} 次", jobId, url, body.get("maxAttempts"));
        return job;
    }

    /** 任务状态（含每次尝试与成功结果）；已入库时附 savedRuleId（成功 = 待确认的规则，失败 = 失败记录） */
    public JsonNode getJob(String jobId) {
        JsonNode job = callPython(() -> aiClient.getCrawlAiJob(jobId));
        String status = job.path("status").asText();
        if (("succeeded".equals(status) || "failed".equals(status)) && job instanceof ObjectNode node) {
            Long ruleId = saveOnce(jobId, job);
            if (ruleId != null) {
                node.put("savedRuleId", ruleId);
            }
        }
        return job;
    }

    public JsonNode cancel(String jobId) {
        return callPython(() -> aiClient.cancelCrawlAiJob(jobId));
    }

    /** 后台跟踪：成功即保存规则，失败存一条失败记录，取消 / 超时退出 */
    private void watch(String jobId) {
        long deadline = System.currentTimeMillis() + WATCH_LIMIT_MS;
        int unreachable = 0;
        try {
            while (System.currentTimeMillis() < deadline && !Thread.currentThread().isInterrupted()) {
                Thread.sleep(POLL_INTERVAL_MS);
                JsonNode job;
                try {
                    job = aiClient.getCrawlAiJob(jobId).path("data");
                    unreachable = 0;
                } catch (HttpClientErrorException.NotFound e) {
                    return;
                } catch (ResourceAccessException e) {
                    if (++unreachable >= 30) {
                        return;
                    }
                    continue;
                }
                String status = job.path("status").asText();
                if ("succeeded".equals(status) || "failed".equals(status)) {
                    saveOnce(jobId, job);
                    return;
                }
                if (!"queued".equals(status) && !"running".equals(status)) {
                    return;
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (Exception e) {
            log.error("跟踪 AI 解析任务失败 jobId={}", jobId, e);
        }
    }

    private synchronized Long saveOnce(String jobId, JsonNode job) {
        Long saved = savedJobs.get(jobId);
        if (saved != null) {
            return saved;
        }
        CrawlSiteRule rule;
        if ("failed".equals(job.path("status").asText())) {
            rule = saveFailure(job);
        } else {
            JsonNode result = job.path("result");
            if (!result.isObject()) {
                return null;
            }
            rule = save(result, job.path("url").asText(), job.path("attempts").size(), attemptLog(job));
        }
        savedJobs.put(jobId, rule.getId());
        return rule.getId();
    }

    /** 解析过程（每次尝试 + token + 样本），存进记录供解析管理查看；不含 API Key（任务状态里本来就没有） */
    @SuppressWarnings("unchecked")
    private Map<String, Object> attemptLog(JsonNode job) {
        Map<String, Object> log = new LinkedHashMap<>();
        log.put("attempts", objectMapper.convertValue(job.path("attempts"), List.class));
        if (job.path("usage").isObject()) {
            log.put("usage", objectMapper.convertValue(job.path("usage"), Map.class));
        }
        log.put("message", job.path("message").asText(""));
        JsonNode preview = job.path("result").path("preview");
        if (preview.path("sample").isObject()) {
            log.put("sample", objectMapper.convertValue(preview.path("sample"), Map.class));
        }
        List<String> titles = new java.util.ArrayList<>();
        JsonNode chapters = preview.path("chapters");
        for (int i = 0; i < chapters.size() && titles.size() < 8; i++) {
            titles.add(chapters.get(i).path("title").asText());
        }
        if (chapters.size() > 8) {
            titles.add("…");
            titles.add(chapters.get(chapters.size() - 1).path("title").asText());
        }
        if (!titles.isEmpty()) {
            log.put("chapterTitles", titles);
        }
        return log;
    }

    /** 解析失败：存一条 FAILED 记录（只作记录：不能确认、不会被自动套用，没有规则文件） */
    private CrawlSiteRule saveFailure(JsonNode job) {
        String url = job.path("url").asText("");
        String host = hostOf(url);
        LocalDateTime now = LocalDateTime.now();
        CrawlSiteRule row = new CrawlSiteRule();
        row.setHost(host == null ? "unknown" : host);
        row.setStatus(CrawlSiteRule.FAILED);
        row.setSampleUrl(url);
        row.setError(truncate(job.path("error").asText("")));
        row.setAttempts(job.path("attempts").size());
        row.setAttemptLog(attemptLog(job));
        row.setRule(new LinkedHashMap<>());
        // 最后一次尝试识别到的目录，方便判断是「没找到目录」还是「正文不对」
        JsonNode last = job.path("attempts").path(job.path("attempts").size() - 1);
        row.setTocUrl(text(last, "tocUrl"));
        row.setChapterCount(last.path("chapterCount").asInt());
        row.setCreateTime(now);
        row.setUpdateTime(now);
        mapper.insert(row);
        log.info("已记录失败的 AI 解析 host={} id={}（尝试 {} 次）", row.getHost(), row.getId(), row.getAttempts());
        return row;
    }

    private static String truncate(String s) {
        return s != null && s.length() > 2000 ? s.substring(0, 2000) : s;
    }

    /** 存为待确认（同域名已有待确认的就覆盖它，已确认的不动）：规则 + 地址规律 + 学习时的样例 */
    private CrawlSiteRule save(JsonNode result, String sampleUrl, int attempts, Map<String, Object> attemptLog) {
        String host = result.path("host").asText("");
        if (host.isEmpty()) {
            host = hostOf(sampleUrl);
        }
        host = host.toLowerCase(Locale.ROOT);
        CrawlSiteRule row = mapper.selectOne(new LambdaQueryWrapper<CrawlSiteRule>()
                .eq(CrawlSiteRule::getHost, host).eq(CrawlSiteRule::getStatus, CrawlSiteRule.PENDING).last("LIMIT 1"));
        boolean insert = row == null;
        LocalDateTime now = LocalDateTime.now();
        if (insert) {
            row = new CrawlSiteRule();
            row.setHost(host);
            row.setStatus(CrawlSiteRule.PENDING);
            row.setCreateTime(now);
        }
        row.setSiteName(text(result, "siteName"));
        row.setHomeUrl(text(result, "homeUrl"));
        @SuppressWarnings("unchecked")
        Map<String, Object> siteMap = result.path("siteMap").isObject()
                ? objectMapper.convertValue(result.path("siteMap"), Map.class) : null;
        row.setSiteMap(siteMap);
        row.setPreset(text(result, "preset"));
        row.setRule(cleanRule(result.path("rule")));
        row.setSummary(text(result, "summary"));
        row.setBookUrlPattern(text(result, "bookUrlPattern"));
        row.setTocUrlPattern(text(result, "tocUrlPattern"));
        row.setChapterUrlPattern(text(result, "chapterUrlPattern"));
        row.setSampleUrl(sampleUrl);
        row.setTocUrl(text(result, "tocUrl"));
        row.setBookName(text(result.path("preview"), "bookName"));
        row.setStrategy(text(result, "strategy"));
        row.setAttempts(attempts);
        row.setAttemptLog(attemptLog);
        row.setError(null);
        row.setChapterCount(result.path("preview").path("chapterCount").asInt());
        row.setUpdateTime(now);
        if (insert) {
            mapper.insert(row);
        } else {
            mapper.updateById(row);
        }
        writeRuleFile(row);
        log.info("已保存待确认的站点规则 host={} id={}（{}，第 {} 次尝试成功）", host, row.getId(), row.getStrategy(), attempts);
        return row;
    }

    // ---------------------------------------------------------------- 解析管理（待确认 / 已确认）

    /** status 为空 = 全部；待确认在前，其次已确认、失败，同组按更新时间倒序 */
    public List<CrawlSiteRule> list(String status) {
        LambdaQueryWrapper<CrawlSiteRule> q = new LambdaQueryWrapper<CrawlSiteRule>()
                .orderByDesc(CrawlSiteRule::getUpdateTime);
        if (status != null && !status.isBlank()) {
            q.eq(CrawlSiteRule::getStatus, status.trim().toUpperCase(Locale.ROOT));
        }
        List<CrawlSiteRule> rows = mapper.selectList(q);
        List<String> order = List.of(CrawlSiteRule.PENDING, CrawlSiteRule.CONFIRMED, CrawlSiteRule.FAILED);
        rows.sort((a, b) -> Integer.compare(order.indexOf(a.getStatus()), order.indexOf(b.getStatus())));
        rows.forEach(this::decorate);
        return rows;
    }

    public CrawlSiteRule getById(Long id) {
        CrawlSiteRule rule = mapper.selectById(id);
        if (rule == null) {
            throw new BizException(404, "该站点规则不存在（可能已删除）");
        }
        return decorate(rule);
    }

    /** 确认待确认的规则：生效，并替换该域名原来已确认的规则 */
    public synchronized CrawlSiteRule confirm(Long id) {
        CrawlSiteRule rule = getById(id);
        if (CrawlSiteRule.CONFIRMED.equals(rule.getStatus())) {
            return rule;
        }
        if (CrawlSiteRule.FAILED.equals(rule.getStatus())) {
            throw new BizException(400, "这次解析失败了，没有可用的规则；请重新解析");
        }
        for (CrawlSiteRule old : mapper.selectList(new LambdaQueryWrapper<CrawlSiteRule>()
                .eq(CrawlSiteRule::getHost, rule.getHost()).eq(CrawlSiteRule::getStatus, CrawlSiteRule.CONFIRMED))) {
            mapper.deleteById(old.getId());
            deleteRuleFile(old);
        }
        LocalDateTime now = LocalDateTime.now();
        rule.setStatus(CrawlSiteRule.CONFIRMED);
        rule.setConfirmTime(now);
        rule.setUpdateTime(now);
        mapper.updateById(rule);
        writeRuleFile(rule);
        log.info("已确认站点规则 host={} id={}", rule.getHost(), id);
        return decorate(rule);
    }

    /** 不确认：丢弃待确认的规则 / 失败记录（已确认的规则请用删除） */
    public void reject(Long id) {
        CrawlSiteRule rule = getById(id);
        if (CrawlSiteRule.CONFIRMED.equals(rule.getStatus())) {
            throw new BizException(400, "这条规则已确认，如不再需要请删除");
        }
        mapper.deleteById(id);
        deleteRuleFile(rule);
    }

    public void delete(Long id) {
        CrawlSiteRule rule = getById(id);
        mapper.deleteById(id);
        deleteRuleFile(rule);
    }

    /** 按地址的域名找<b>已确认</b>的规则：先精确匹配，再忽略 www. / m. 前缀 */
    public CrawlSiteRule findForUrl(String url) {
        String host = hostOf(url);
        if (host == null) {
            return null;
        }
        String bare = host.replaceFirst("^(www|m|wap)\\.", "");
        List<CrawlSiteRule> rows = mapper.selectList(new LambdaQueryWrapper<CrawlSiteRule>()
                .eq(CrawlSiteRule::getStatus, CrawlSiteRule.CONFIRMED)
                .in(CrawlSiteRule::getHost, host, bare, "www." + bare, "m." + bare));
        return rows.stream().filter(r -> host.equals(r.getHost())).findFirst()
                .orElse(rows.isEmpty() ? null : rows.get(0));
    }

    // ---------------------------------------------------------------- 规则文件 data/crawl-rules/

    private Path ruleFilePath(CrawlSiteRule rule) {
        String host = rule.getHost() == null ? "unknown" : rule.getHost().replaceAll("[^A-Za-z0-9.-]", "_");
        return dataPaths.root().resolve(DataPaths.CRAWL_RULES).resolve(host + "_" + rule.getId() + ".json");
    }

    private CrawlSiteRule decorate(CrawlSiteRule rule) {
        rule.setRuleFile(CrawlSiteRule.FAILED.equals(rule.getStatus()) ? null
                : DataPaths.CRAWL_RULES + "/" + ruleFilePath(rule).getFileName());
        return rule;
    }

    /** 整条记录写成 JSON（临时文件 → 原子改名）；写失败只记日志，数据库为准 */
    private void writeRuleFile(CrawlSiteRule rule) {
        Path target = ruleFilePath(rule);
        Path tmp = target.resolveSibling(target.getFileName() + ".part");
        try {
            Files.createDirectories(target.getParent());
            Files.write(tmp, objectMapper.writerWithDefaultPrettyPrinter().writeValueAsBytes(decorate(rule)));
            try {
                Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException e) {
                Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException e) {
            log.warn("写站点规则文件失败 {}：{}", target, e.getMessage());
        }
    }

    private void deleteRuleFile(CrawlSiteRule rule) {
        try {
            Files.deleteIfExists(ruleFilePath(rule));
        } catch (IOException e) {
            log.warn("删除站点规则文件失败 {}：{}", ruleFilePath(rule), e.getMessage());
        }
    }

    // ---------------------------------------------------------------- 工具

    private Map<String, Object> cleanRule(JsonNode node) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (node == null || !node.isObject()) {
            return out;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> raw = objectMapper.convertValue(node, Map.class);
        raw.forEach((k, v) -> {
            if (RULE_KEYS.contains(k) && v != null && !"".equals(v) && !(v instanceof List<?> l && l.isEmpty())) {
                out.put(k, v);
            }
        });
        return out;
    }

    /** Python 不可达 → 503；4xx 只透传我们自己的 {message}（请求体带 API Key，校验错误的回显不外传） */
    private JsonNode callPython(Supplier<JsonNode> call) {
        try {
            JsonNode res = call.get();
            return res == null ? objectMapper.createObjectNode() : res.path("data");
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            int status = e.getStatusCode().value();
            String message = "AI 服务拒绝请求（HTTP " + status + "）";
            try {
                JsonNode body = objectMapper.readTree(e.getResponseBodyAsString(StandardCharsets.UTF_8));
                if (body.hasNonNull("message")) {
                    message = body.get("message").asText();
                }
            } catch (Exception ignored) {
                // 非 JSON 响应
            }
            throw new BizException(status == 404 ? 404 : 400, message);
        }
    }

    static String hostOf(String url) {
        try {
            URI uri = new URI(url.trim());
            String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            if (!("http".equals(scheme) || "https".equals(scheme)) || uri.getHost() == null) {
                return null;
            }
            return uri.getHost().toLowerCase(Locale.ROOT);
        } catch (Exception e) {
            return null;
        }
    }

    private static String text(JsonNode node, String key) {
        String value = node.path(key).asText("");
        return value.isEmpty() ? null : value;
    }

    private static int clamp(Object value, int min, int max, int fallback) {
        int n = value instanceof Number num ? num.intValue()
                : value instanceof String s && s.matches("\\d+") ? Integer.parseInt(s) : fallback;
        return Math.max(min, Math.min(max, n));
    }

    private static String str(Object value) {
        return value == null ? null : String.valueOf(value).trim();
    }
}
