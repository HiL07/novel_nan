package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.CrawlSiteRule;
import com.example.file.mapper.CrawlSiteRuleMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.net.URI;
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
 * 随请求下发、不落库）。Java 在后台线程轮询该任务，成功后把规则按域名存入 crawl_site_rule（同域名覆盖），
 * 之后抓取选「按域名自动选择」时 {@link NovelCrawlService} 会自动套用。浏览器关掉也不影响规则入库。
 */
@Service
public class CrawlRuleService {

    private static final Logger log = LoggerFactory.getLogger(CrawlRuleService.class);

    private static final long POLL_INTERVAL_MS = 2000;
    /** 最长跟踪 30 分钟（10 次尝试 × 模型 + 试抓，正常几分钟内结束） */
    private static final long WATCH_LIMIT_MS = 30 * 60 * 1000L;
    /** 规则里允许保存 / 下发的字段（与 python-service/app/crawler/rules.py 的 CrawlRule 一致） */
    private static final Set<String> RULE_KEYS = Set.of("categoryLinks", "bookLinks", "listNext", "tocLink",
            "bookName", "author", "intro", "chapterLinks", "tocNext", "content", "contentNext", "encoding",
            "removePatterns");

    private final CrawlSiteRuleMapper mapper;
    private final AiServiceClient aiClient;
    private final AiModelConfigService modelService;
    private final ObjectMapper objectMapper;
    private final ExecutorService watcher = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "crawl-ai-watch");
        t.setDaemon(true);
        return t;
    });
    /** jobId → 已保存的规则 id（防止轮询线程与前端查询重复保存） */
    private final Map<String, Long> savedJobs = new ConcurrentHashMap<>();

    public CrawlRuleService(CrawlSiteRuleMapper mapper, AiServiceClient aiClient, AiModelConfigService modelService,
                            ObjectMapper objectMapper) {
        this.mapper = mapper;
        this.aiClient = aiClient;
        this.modelService = modelService;
        this.objectMapper = objectMapper;
    }

    @PreDestroy
    public void shutdown() {
        watcher.shutdownNow();
    }

    // ---------------------------------------------------------------- AI 解析任务

    /**
     * 提交 AI 解析：{url, maxAttempts?(1~10, 默认 5), delayMs?, respectRobots?, hint?, useKnown?(默认 true)}。
     * 同域名已有学到的规则时先试它（useKnown=false 则从头学）。
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

    /** 任务状态（含每次尝试与成功结果）；成功且已入库时附 savedRuleId */
    public JsonNode getJob(String jobId) {
        JsonNode job = callPython(() -> aiClient.getCrawlAiJob(jobId));
        if ("succeeded".equals(job.path("status").asText()) && job instanceof ObjectNode node) {
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

    /** 后台跟踪：成功即保存规则，失败 / 取消 / 超时退出 */
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
                if ("succeeded".equals(status)) {
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
        JsonNode result = job.path("result");
        if (!result.isObject()) {
            return null;
        }
        CrawlSiteRule rule = save(result, job.path("url").asText(), job.path("attempts").size());
        savedJobs.put(jobId, rule.getId());
        return rule.getId();
    }

    /** 按域名保存（同域名覆盖）：规则 + 地址规律 + 学习时的样例 */
    private CrawlSiteRule save(JsonNode result, String sampleUrl, int attempts) {
        String host = result.path("host").asText("");
        if (host.isEmpty()) {
            host = hostOf(sampleUrl);
        }
        host = host.toLowerCase(Locale.ROOT);
        CrawlSiteRule row = mapper.selectOne(new LambdaQueryWrapper<CrawlSiteRule>()
                .eq(CrawlSiteRule::getHost, host).last("LIMIT 1"));
        boolean insert = row == null;
        LocalDateTime now = LocalDateTime.now();
        if (insert) {
            row = new CrawlSiteRule();
            row.setHost(host);
            row.setCreateTime(now);
        }
        row.setSiteName(text(result, "siteName"));
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
        row.setChapterCount(result.path("preview").path("chapterCount").asInt());
        row.setUpdateTime(now);
        if (insert) {
            mapper.insert(row);
        } else {
            mapper.updateById(row);
        }
        log.info("已保存站点规则 host={} id={}（{}，第 {} 次尝试成功）", host, row.getId(), row.getStrategy(), attempts);
        return row;
    }

    // ---------------------------------------------------------------- 已学规则

    public List<CrawlSiteRule> list() {
        return mapper.selectList(new LambdaQueryWrapper<CrawlSiteRule>().orderByDesc(CrawlSiteRule::getUpdateTime));
    }

    public CrawlSiteRule getById(Long id) {
        CrawlSiteRule rule = mapper.selectById(id);
        if (rule == null) {
            throw new BizException(404, "该站点规则不存在（可能已删除）");
        }
        return rule;
    }

    public void delete(Long id) {
        getById(id);
        mapper.deleteById(id);
    }

    /** 按地址的域名找学到的规则：先精确匹配，再忽略 www. / m. 前缀 */
    public CrawlSiteRule findForUrl(String url) {
        String host = hostOf(url);
        if (host == null) {
            return null;
        }
        String bare = host.replaceFirst("^(www|m|wap)\\.", "");
        List<CrawlSiteRule> rows = mapper.selectList(new LambdaQueryWrapper<CrawlSiteRule>()
                .in(CrawlSiteRule::getHost, host, bare, "www." + bare, "m." + bare));
        return rows.stream().filter(r -> host.equals(r.getHost())).findFirst()
                .orElse(rows.isEmpty() ? null : rows.get(0));
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
