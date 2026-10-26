package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.file.common.BizException;
import com.example.file.common.DataPaths;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.CrawlCatalogBook;
import com.example.file.entity.CrawlSiteCatalog;
import com.example.file.entity.CrawlSiteRule;
import com.example.file.entity.NovelCrawlBook;
import com.example.file.mapper.CrawlCatalogBookMapper;
import com.example.file.mapper.CrawlSiteCatalogMapper;
import com.example.file.mapper.NovelCrawlBookMapper;
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

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Supplier;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * 全自动爬虫：基于 AI 解析学到的站点规律（crawl_site_rule）采集站点书目。
 * <ol>
 *   <li>测试（phase=test）：Python /api/crawl/catalog/jobs 从站点首页按规律找几本书，取书名 / 作者 / 简介 / 标签 / 目录，
 *       抽几本试抓首章正文，给出测试报告（规律可用 / 部分可用 / 不可用）；</li>
 *   <li>用户看报告决定是否使用（decision）；</li>
 *   <li>使用：可扩充书目（phase=scan，跳过已采集的书），按书名 / 作者模糊匹配、类型（标签模糊）、
 *       具体情节（AI 选标签，或 AI 逐本读简介）筛选，
 *       选中的书由前端提交为普通整站抓取任务（{@link NovelCrawlService#submitSite}），每本一个 txt。</li>
 * </ol>
 * 书目元数据（简介 / 标签 / 目录概况）存 crawl_catalog_book；每本书的完整目录由 Python 写到
 * data/&lt;catalogDir&gt;/toc/，同一首页的书目另导出一份 data/&lt;catalogDir&gt;/catalog.json（数据库为准）。正文不保存。
 * Java 在后台线程轮询采集任务，书目边采边入库，浏览器关掉也不影响。
 */
@Service
public class CrawlCatalogService {

    private static final Logger log = LoggerFactory.getLogger(CrawlCatalogService.class);

    private static final long POLL_INTERVAL_MS = 2000;
    /** 最长跟踪 6 小时（500 本 × 详情 + 目录分页，按 1 秒间隔约 30~60 分钟） */
    private static final long WATCH_LIMIT_MS = 6 * 3600 * 1000L;
    private static final int TAG_BATCH = 20;
    /** test 测试 / scan 扩充书目 / toc 给书目里还没目录的书补目录 */
    private static final Set<String> PHASES = Set.of("test", "scan", "toc");

    private final CrawlSiteCatalogMapper catalogMapper;
    private final CrawlCatalogBookMapper bookMapper;
    private final NovelCrawlBookMapper crawlBookMapper;
    private final CrawlRuleService ruleService;
    private final AiServiceClient aiClient;
    private final AiModelConfigService modelService;
    private final ObjectMapper objectMapper;
    private final DataPaths dataPaths;
    private final ExecutorService watcher = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "crawl-catalog-watch");
        t.setDaemon(true);
        return t;
    });

    public CrawlCatalogService(CrawlSiteCatalogMapper catalogMapper, CrawlCatalogBookMapper bookMapper,
                               NovelCrawlBookMapper crawlBookMapper, CrawlRuleService ruleService,
                               AiServiceClient aiClient, AiModelConfigService modelService,
                               ObjectMapper objectMapper, DataPaths dataPaths) {
        this.catalogMapper = catalogMapper;
        this.bookMapper = bookMapper;
        this.crawlBookMapper = crawlBookMapper;
        this.ruleService = ruleService;
        this.aiClient = aiClient;
        this.modelService = modelService;
        this.objectMapper = objectMapper;
        this.dataPaths = dataPaths;
    }

    @PreDestroy
    public void shutdown() {
        watcher.shutdownNow();
    }

    /** 启动后：上次没跑完的采集已随进程中断（已入库的书目保留） */
    @EventListener(ApplicationReadyEvent.class)
    public void failInterrupted() {
        int n = catalogMapper.update(null, new LambdaUpdateWrapper<CrawlSiteCatalog>()
                .eq(CrawlSiteCatalog::getStatus, CrawlSiteCatalog.RUNNING)
                .set(CrawlSiteCatalog::getStatus, CrawlSiteCatalog.FAILED)
                .set(CrawlSiteCatalog::getMessage, "服务重启，采集中断（已采集的书目已保存，可重新测试 / 扩充）")
                .set(CrawlSiteCatalog::getUpdateTime, LocalDateTime.now()));
        if (n > 0) {
            log.warn("已将 {} 个中断的书目采集标记为失败", n);
        }
    }

    // ---------------------------------------------------------------- 书目列表 / 测试 / 扩充

    /** 全部站点书目，最近更新的在前 */
    public List<CrawlSiteCatalog> list() {
        List<CrawlSiteCatalog> rows = catalogMapper.selectList(new LambdaQueryWrapper<CrawlSiteCatalog>()
                .orderByDesc(CrawlSiteCatalog::getUpdateTime));
        rows.forEach(this::decorate);
        return rows;
    }

    public CrawlSiteCatalog get(Long id) {
        return decorate(require(id));
    }

    /**
     * 开始测试 / 扩充：{ruleId, phase: test|scan, maxBooks?, maxCategories?, maxListPages?, contentSamples?, tocPages?,
     * delayMs?, respectRobots?}。站点首页取规则的 homeUrl；同一首页只有一份书目（没有就新建）。
     */
    public CrawlSiteCatalog start(Map<String, Object> body) {
        if (body == null || intOrNull(body.get("ruleId")) == null) {
            throw new BizException(400, "请选择一条 AI 解析出的站点规则");
        }
        CrawlSiteRule rule = ruleService.getById(intOrNull(body.get("ruleId")).longValue());
        if (CrawlSiteRule.FAILED.equals(rule.getStatus())) {
            throw new BizException(400, "这条是解析失败的记录，没有可用的站点规律；请先重新 AI 解析");
        }
        String homeUrl = homeUrlOf(rule);
        if (homeUrl == null) {
            throw new BizException(400, "这条规则没有站点首页地址，请重新 AI 解析一次该站点的书");
        }
        String phase = PHASES.contains(str(body.get("phase"))) ? str(body.get("phase")) : "test";
        boolean test = "test".equals(phase);

        CrawlSiteCatalog catalog;
        synchronized (this) {
            catalog = catalogMapper.selectOne(new LambdaQueryWrapper<CrawlSiteCatalog>()
                    .eq(CrawlSiteCatalog::getHomeUrl, homeUrl).last("LIMIT 1"));
            if (catalog != null && CrawlSiteCatalog.RUNNING.equals(catalog.getStatus())) {
                throw new BizException(400, "该站点正在采集书目，请等它结束或先取消");
            }
            if (catalog == null) {
                catalog = new CrawlSiteCatalog();
                catalog.setHost(CrawlRuleService.hostOf(homeUrl));
                catalog.setHomeUrl(homeUrl);
                catalog.setCatalogDir(DataPaths.SITE_CATALOG + "/" + dirName(homeUrl));
                catalog.setDecision(CrawlSiteCatalog.PENDING);
                catalog.setProgress(0);
                catalog.setBookCount(0);
                catalog.setCreateTime(LocalDateTime.now());
                catalog.setUpdateTime(catalog.getCreateTime());
                catalog.setStatus(CrawlSiteCatalog.IDLE);
                catalogMapper.insert(catalog);
            }
        }

        Map<String, Object> req = new LinkedHashMap<>();
        req.put("homeUrl", homeUrl);
        req.put("preset", "auto");
        if (rule.getRule() != null && !rule.getRule().isEmpty()) {
            req.put("rule", rule.getRule());
        }
        if (rule.getSampleUrl() != null) {
            req.put("sampleUrl", rule.getSampleUrl());
        }
        if (rule.getSiteMap() != null && rule.getSiteMap().get("categories") instanceof List<?> cats) {
            req.put("categories", cats);
        }
        req.put("phase", phase);
        // refresh = 已采集过的书也重新采（书名 / 作者 / 分类按最新规则更新，AI 标签保留）
        boolean refresh = Boolean.TRUE.equals(body.get("refresh"));
        req.put("knownUrls", test || refresh ? List.of() : bookUrls(catalog.getId()));
        req.put("maxBooks", test ? clamp(body.get("maxBooks"), 2, 30, 8) : clamp(body.get("maxBooks"), 1, 500, 50));
        req.put("maxCategories", clamp(body.get("maxCategories"), 1, 50, 10));
        req.put("maxListPages", clamp(body.get("maxListPages"), 1, 50, test ? 3 : 5));
        req.put("contentSamples", clamp(body.get("contentSamples"), 0, 10, test ? 3 : 0));
        // 扩充时的目录：tocMode = async（默认，书先出来、同一任务里接着补目录）/ sync（每本当场开目录页）/
        // skip（不取目录，抓取时再取）；老前端传 tocPages=0 视为 skip。测试要验证目录，总是当场取
        String tocMode = str(body.get("tocMode"));
        if (tocMode == null || tocMode.isEmpty()) {
            tocMode = Integer.valueOf(0).equals(intOrNull(body.get("tocPages"))) ? "skip" : "async";
        }
        boolean skipToc = !test && "skip".equals(tocMode);
        req.put("tocPages", skipToc ? 0 : clamp(body.get("tocPages"), 1, 30, 10));
        req.put("tocAsync", !test && "async".equals(tocMode));
        if ("toc".equals(phase)) {
            List<Map<String, Object>> targets = tocTargets(catalog.getId(), body.get("bookIds"));
            if (targets.isEmpty()) {
                throw new BizException(400, "没有需要补目录的书（都已经有目录了）");
            }
            req.put("tocTargets", targets);
            req.put("tocAsync", false);
            req.put("knownUrls", List.of());
        }
        req.put("delayMs", clamp(body.get("delayMs"), 300, 30000, 1000));
        req.put("respectRobots", !Boolean.FALSE.equals(body.get("respectRobots")));
        req.put("catalogDir", catalog.getCatalogDir());

        JsonNode job = callPython(() -> aiClient.submitCatalog(req));
        String jobId = job.path("jobId").asText();
        catalog.setRuleId(rule.getId());
        if (catalog.getSiteName() == null || catalog.getSiteName().isBlank()) {
            catalog.setSiteName(rule.getSiteName());
        }
        if (test && CrawlSiteCatalog.REJECTED.equals(catalog.getDecision())) {
            catalog.setDecision(CrawlSiteCatalog.PENDING);   // 重新测试 = 重新决定
        }
        catalog.setStatus(CrawlSiteCatalog.RUNNING);
        catalog.setPhase(phase);
        catalog.setJobId(jobId);
        catalog.setProgress(0);
        catalog.setMessage(test ? "测试规律：排队中" : "toc".equals(phase) ? "补全目录：排队中" : "扩充书目：排队中");
        catalog.setUpdateTime(LocalDateTime.now());
        catalogMapper.updateById(catalog);
        Long catalogId = catalog.getId();
        watcher.submit(() -> watch(catalogId, jobId));
        log.info("书目采集已提交 catalogId={} {} phase={} 上限 {} 本", catalogId, homeUrl, phase, req.get("maxBooks"));
        return decorate(catalog);
    }

    /** 取消采集：已采集的书目保留 */
    public CrawlSiteCatalog cancel(Long id) {
        CrawlSiteCatalog catalog = require(id);
        if (!CrawlSiteCatalog.RUNNING.equals(catalog.getStatus())) {
            return decorate(catalog);
        }
        try {
            aiClient.cancelCatalogJob(catalog.getJobId());
            catalog.setMessage("正在取消（当前这本处理完后停止）…");
        } catch (ResourceAccessException | HttpClientErrorException.NotFound e) {
            // AI 服务已停 / 重启：任务不在了，直接结束
            catalog.setStatus(CrawlSiteCatalog.CANCELLED);
            catalog.setMessage("已取消（AI 服务不可达）");
        }
        catalog.setUpdateTime(LocalDateTime.now());
        catalogMapper.updateById(catalog);
        return decorate(catalog);
    }

    /** 用户决定：USED 使用（之后可扩充 / 筛选 / 抓取）/ REJECTED 不使用 / PENDING 重新待定 */
    public CrawlSiteCatalog decide(Long id, String decision) {
        CrawlSiteCatalog catalog = require(id);
        String d = decision == null ? "" : decision.trim().toUpperCase(Locale.ROOT);
        if (!Set.of(CrawlSiteCatalog.USED, CrawlSiteCatalog.REJECTED, CrawlSiteCatalog.PENDING).contains(d)) {
            throw new BizException(400, "decision 只能是 USED / REJECTED / PENDING");
        }
        catalog.setDecision(d);
        catalog.setUpdateTime(LocalDateTime.now());
        catalogMapper.updateById(catalog);
        exportCatalog(catalog);
        return decorate(catalog);
    }

    /** 删除书目（书目行 + 目录文件夹）；已抓取的 txt 在文件管理里，不受影响 */
    public void delete(Long id) {
        CrawlSiteCatalog catalog = require(id);
        if (CrawlSiteCatalog.RUNNING.equals(catalog.getStatus())) {
            throw new BizException(400, "正在采集书目，请先取消");
        }
        bookMapper.delete(new LambdaQueryWrapper<CrawlCatalogBook>().eq(CrawlCatalogBook::getCatalogId, id));
        catalogMapper.deleteById(id);
        Path dir = catalogPath(catalog);
        if (dir != null && Files.isDirectory(dir)) {
            try (Stream<Path> walk = Files.walk(dir)) {
                walk.sorted(Comparator.reverseOrder()).forEach(p -> {
                    try {
                        Files.deleteIfExists(p);
                    } catch (IOException e) {
                        log.warn("删除书目文件失败 {}：{}", p, e.getMessage());
                    }
                });
            } catch (IOException e) {
                log.warn("删除书目目录失败 {}：{}", dir, e.getMessage());
            }
        }
        log.info("已删除站点书目 id={} {}", id, catalog.getHomeUrl());
    }

    // ---------------------------------------------------------------- 后台跟踪采集任务

    private void watch(Long catalogId, String jobId) {
        long deadline = System.currentTimeMillis() + WATCH_LIMIT_MS;
        int unreachable = 0;
        int saved = 0;
        int tocSaved = 0;
        try {
            while (!Thread.currentThread().isInterrupted()) {
                Thread.sleep(POLL_INTERVAL_MS);
                if (System.currentTimeMillis() > deadline) {
                    finish(catalogId, jobId, CrawlSiteCatalog.FAILED, "跟踪超时（超过 6 小时），已采集的书目已保存", null);
                    return;
                }
                JsonNode job;
                try {
                    job = aiClient.getCatalogJob(jobId, saved, tocSaved).path("data");
                    unreachable = 0;
                } catch (HttpClientErrorException.NotFound e) {
                    finish(catalogId, jobId, CrawlSiteCatalog.FAILED, "AI 服务已重启，采集中断（已采集的书目已保存）", null);
                    return;
                } catch (ResourceAccessException e) {
                    if (++unreachable >= 30) {
                        finish(catalogId, jobId, CrawlSiteCatalog.FAILED, "AI 服务不可达，采集中断（已采集的书目已保存）", null);
                        return;
                    }
                    continue;
                }
                saved += saveBooks(catalogId, job.path("books"));
                tocSaved += saveTocUpdates(catalogId, job.path("tocUpdates"));
                String status = job.path("status").asText();
                if ("queued".equals(status) || "running".equals(status)) {
                    progress(catalogId, jobId, job);
                    continue;
                }
                String finalStatus = switch (status) {
                    case "succeeded" -> CrawlSiteCatalog.SUCCEEDED;
                    case "cancelled" -> CrawlSiteCatalog.CANCELLED;
                    default -> CrawlSiteCatalog.FAILED;
                };
                String message = job.hasNonNull("error") ? job.path("error").asText() : job.path("message").asText("");
                finish(catalogId, jobId, finalStatus, message, job);
                return;
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (Exception e) {
            log.error("跟踪书目采集失败 catalogId={} jobId={}", catalogId, jobId, e);
            finish(catalogId, jobId, CrawlSiteCatalog.FAILED, "采集结果保存失败：" + e.getMessage(), null);
        }
    }

    private void progress(Long catalogId, String jobId, JsonNode job) {
        catalogMapper.update(null, new LambdaUpdateWrapper<CrawlSiteCatalog>()
                .eq(CrawlSiteCatalog::getId, catalogId).eq(CrawlSiteCatalog::getJobId, jobId)
                .set(CrawlSiteCatalog::getProgress, job.path("progress").asInt())
                .set(CrawlSiteCatalog::getMessage, truncate(job.path("message").asText("")))
                .set(CrawlSiteCatalog::getBookCount, countBooks(catalogId))
                .set(CrawlSiteCatalog::getUpdateTime, LocalDateTime.now()));
    }

    @SuppressWarnings("unchecked")
    private void finish(Long catalogId, String jobId, String status, String message, JsonNode job) {
        CrawlSiteCatalog catalog = catalogMapper.selectById(catalogId);
        if (catalog == null || !jobId.equals(catalog.getJobId())) {
            return;   // 书目已删除，或又开始了新的采集
        }
        LocalDateTime now = LocalDateTime.now();
        catalog.setStatus(status);
        catalog.setMessage(truncate(message));
        catalog.setProgress(CrawlSiteCatalog.SUCCEEDED.equals(status) ? 100 : catalog.getProgress());
        catalog.setBookCount(countBooks(catalogId));
        catalog.setLastScanTime(now);
        catalog.setUpdateTime(now);
        if (job != null) {
            String siteName = job.path("siteName").asText("");
            if (!siteName.isBlank() && (catalog.getSiteName() == null || catalog.getSiteName().isBlank())) {
                catalog.setSiteName(siteName);
            }
            if (job.path("report").isObject()) {
                Map<String, Object> report = objectMapper.convertValue(job.path("report"), Map.class);
                catalog.setLastReport(report);
                if ("test".equals(catalog.getPhase())) {
                    catalog.setReport(report);
                }
            }
        }
        catalogMapper.updateById(catalog);
        exportCatalog(catalog);
        log.info("书目采集结束 catalogId={} {}：{}，共 {} 本", catalogId, status, message, catalog.getBookCount());
    }

    /** 新采集到的书入库：同一书目按书籍地址去重（再次采集时更新，AI 补的标签保留）→ 本次处理的条数 */
    /** 补全目录的结果写回书目（按书籍地址找到那本书）→ 本次处理的条数 */
    private int saveTocUpdates(Long catalogId, JsonNode updates) {
        if (!updates.isArray()) {
            return 0;
        }
        LocalDateTime now = LocalDateTime.now();
        int n = 0;
        for (JsonNode u : updates) {
            n++;
            LambdaUpdateWrapper<CrawlCatalogBook> w = new LambdaUpdateWrapper<CrawlCatalogBook>()
                    .eq(CrawlCatalogBook::getCatalogId, catalogId).eq(CrawlCatalogBook::getBookUrl, u.path("bookUrl").asText())
                    .set(CrawlCatalogBook::getUpdateTime, now);
            if (u.path("tocOk").asBoolean()) {
                w.set(CrawlCatalogBook::getTocUrl, text(u, "tocUrl"))
                        .set(CrawlCatalogBook::getChapterCount, u.path("chapterCount").asInt())
                        .set(CrawlCatalogBook::getFirstChapter, text(u, "firstChapter"))
                        .set(CrawlCatalogBook::getLatestChapter, text(u, "latestChapter"))
                        .set(CrawlCatalogBook::getTocPath, text(u, "tocPath"))
                        .set(CrawlCatalogBook::getTocOk, true)
                        .set(CrawlCatalogBook::getError, null);
            } else {
                w.set(CrawlCatalogBook::getError, truncate(text(u, "error")));
            }
            bookMapper.update(null, w);
        }
        return n;
    }

    /** 要补目录的书：没取到目录、有目录页地址的；bookIds 非空时只补这几本 */
    private List<Map<String, Object>> tocTargets(Long catalogId, Object bookIds) {
        LambdaQueryWrapper<CrawlCatalogBook> q = new LambdaQueryWrapper<CrawlCatalogBook>()
                .select(CrawlCatalogBook::getId, CrawlCatalogBook::getBookUrl, CrawlCatalogBook::getTocUrl, CrawlCatalogBook::getBookName)
                .eq(CrawlCatalogBook::getCatalogId, catalogId).eq(CrawlCatalogBook::getTocOk, false)
                .isNotNull(CrawlCatalogBook::getTocUrl).orderByAsc(CrawlCatalogBook::getId);
        if (bookIds instanceof List<?> ids && !ids.isEmpty()) {
            q.in(CrawlCatalogBook::getId, ids.stream().filter(Number.class::isInstance)
                    .map(x -> ((Number) x).longValue()).toList());
        }
        return bookMapper.selectList(q).stream().limit(5000).map(b -> {
            Map<String, Object> t = new LinkedHashMap<>();
            t.put("bookUrl", b.getBookUrl());
            t.put("tocUrl", b.getTocUrl());
            t.put("bookName", Objects.requireNonNullElse(b.getBookName(), ""));
            return t;
        }).toList();
    }

    private int saveBooks(Long catalogId, JsonNode books) {
        if (!books.isArray()) {
            return 0;
        }
        LocalDateTime now = LocalDateTime.now();
        int n = 0;
        for (JsonNode b : books) {
            n++;
            String bookUrl = b.path("bookUrl").asText("");
            if (bookUrl.isEmpty()) {
                continue;
            }
            CrawlCatalogBook row = bookMapper.selectOne(new LambdaQueryWrapper<CrawlCatalogBook>()
                    .eq(CrawlCatalogBook::getCatalogId, catalogId).eq(CrawlCatalogBook::getBookUrl, bookUrl).last("LIMIT 1"));
            boolean insert = row == null;
            if (insert) {
                row = new CrawlCatalogBook();
                row.setCatalogId(catalogId);
                row.setBookUrl(bookUrl);
                row.setCreateTime(now);
            }
            row.setBookName(text(b, "bookName"));
            row.setAuthor(text(b, "author"));
            row.setCategory(text(b, "category"));
            List<String> tags = new ArrayList<>();
            b.path("tags").forEach(t -> tags.add(t.asText()));
            row.setTags(tags);
            row.setIntro(text(b, "intro"));
            // 这次没打开目录页（快速 / 后台补全，目录稍后单独写回）时，已有的目录原样保留
            boolean keepToc = !insert && b.path("tocSkipped").asBoolean() && Boolean.TRUE.equals(row.getTocOk());
            if (!keepToc) {
                row.setTocUrl(text(b, "tocUrl"));
                row.setChapterCount(b.path("chapterCount").asInt());
                row.setFirstChapter(text(b, "firstChapter"));
                row.setLatestChapter(text(b, "latestChapter"));
                // 这次没解析出目录时保留上次的目录文件
                if (text(b, "tocPath") != null || insert) {
                    row.setTocPath(text(b, "tocPath"));
                }
                row.setTocOk(b.path("tocOk").asBoolean());
            }
            if (b.path("contentChecked").asBoolean()) {
                row.setContentOk(b.path("contentOk").asBoolean());
                row.setContentChars(b.path("contentChars").asInt());
            }
            row.setError(text(b, "error"));
            row.setUpdateTime(now);
            if (insert) {
                bookMapper.insert(row);
            } else {
                bookMapper.updateById(row);
            }
        }
        return n;
    }

    // ---------------------------------------------------------------- 书目查询 / 筛选

    /**
     * 书目筛选条件：keyword 书名模糊匹配（空格分隔多个词，都要包含）、author 作者模糊匹配、
     * tagKeyword 类型（标签模糊匹配：站点标签或 AI 标签里含这个词即可，如「修仙」也匹配「修仙流」）、category 分类、
     * tags 精确标签（站点或 AI 标签，tagMode=any 任一 / all 全部）、usable=true 只要目录可用的。
     */
    public record BookFilter(String keyword, String author, String tagKeyword, String category, List<String> tags,
                             String tagMode, Boolean usable) {

        /** AI 读简介时随请求带来的当前筛选 {keyword, author, tagKeyword, category, tags[], tagMode, usable} */
        static BookFilter of(Object raw) {
            if (!(raw instanceof Map<?, ?> m)) {
                return new BookFilter(null, null, null, null, List.of(), null, null);
            }
            List<String> tags = m.get("tags") instanceof List<?> l ? l.stream().map(String::valueOf).toList() : List.of();
            return new BookFilter(str(m.get("keyword")), str(m.get("author")), str(m.get("tagKeyword")),
                    str(m.get("category")), tags, str(m.get("tagMode")), Boolean.TRUE.equals(m.get("usable")));
        }
    }

    public Map<String, Object> books(Long catalogId, BookFilter filter, int page, int size) {
        require(catalogId);
        LambdaQueryWrapper<CrawlCatalogBook> q = bookQuery(catalogId, filter);
        q.orderByAsc(CrawlCatalogBook::getId);
        Page<CrawlCatalogBook> p = bookMapper.selectPage(
                new Page<>(Math.max(page, 1), Math.max(1, Math.min(size, 500))), q);
        decorateCrawl(p.getRecords());
        // 书目正在采集 / 补目录时，还没目录、没出错的书标「补全中」
        boolean running = CrawlSiteCatalog.RUNNING.equals(catalogMapper.selectById(catalogId).getStatus());
        p.getRecords().forEach(b -> b.setTocPending(running && !Boolean.TRUE.equals(b.getTocOk())
                && b.getTocUrl() != null && (b.getError() == null || b.getError().isEmpty())));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("records", p.getRecords());
        out.put("total", p.getTotal());
        out.put("page", p.getCurrent());
        out.put("size", p.getSize());
        return out;
    }

    private LambdaQueryWrapper<CrawlCatalogBook> bookQuery(Long catalogId, BookFilter f) {
        LambdaQueryWrapper<CrawlCatalogBook> q = new LambdaQueryWrapper<CrawlCatalogBook>()
                .eq(CrawlCatalogBook::getCatalogId, catalogId);
        if (f == null) {
            return q;
        }
        if (f.keyword() != null && !f.keyword().isBlank()) {
            for (String word : f.keyword().trim().split("\\s+")) {
                q.like(CrawlCatalogBook::getBookName, word);
            }
        }
        if (f.author() != null && !f.author().isBlank()) {
            q.like(CrawlCatalogBook::getAuthor, f.author().trim());
        }
        if (f.tagKeyword() != null && !f.tagKeyword().isBlank()) {
            // 类型：任一个词出现在站点标签 / AI 标签 / 分类里（模糊，「修仙」匹配「修仙流」）
            List<String> words = List.of(f.tagKeyword().trim().split("[\\s,，、]+"));
            q.and(w -> {
                for (String word : words) {
                    w.or(x -> x.like(CrawlCatalogBook::getTags, word).or().like(CrawlCatalogBook::getAiTags, word)
                            .or().like(CrawlCatalogBook::getCategory, word));
                }
            });
        }
        if (f.category() != null && !f.category().isBlank()) {
            q.eq(CrawlCatalogBook::getCategory, f.category().trim());
        }
        List<String> wanted = f.tags() == null ? List.of()
                : f.tags().stream().map(String::trim).filter(t -> !t.isEmpty()).toList();
        if (!wanted.isEmpty()) {
            boolean all = "all".equalsIgnoreCase(f.tagMode());
            q.and(w -> {
                for (String tag : wanted) {
                    // JSON 数组里的元素带引号："玄幻"，避免「玄幻」匹配到「玄幻言情」
                    String quoted = "\"" + tag + "\"";
                    if (all) {
                        w.and(x -> x.like(CrawlCatalogBook::getTags, quoted).or().like(CrawlCatalogBook::getAiTags, quoted));
                    } else {
                        w.or(x -> x.like(CrawlCatalogBook::getTags, quoted).or().like(CrawlCatalogBook::getAiTags, quoted));
                    }
                }
            });
        }
        if (Boolean.TRUE.equals(f.usable())) {
            q.eq(CrawlCatalogBook::getTocOk, true);
        }
        return q;
    }

    /** 标签云与分类：{tags:[{tag, count, site, ai}], categories:[{name, count}], total, aiTagged（有 AI 标签的本数）, tocMissing（还没目录的本数）} */
    public Map<String, Object> tags(Long catalogId) {
        require(catalogId);
        List<CrawlCatalogBook> rows = bookMapper.selectList(new LambdaQueryWrapper<CrawlCatalogBook>()
                .select(CrawlCatalogBook::getId, CrawlCatalogBook::getTags, CrawlCatalogBook::getAiTags,
                        CrawlCatalogBook::getCategory)
                .eq(CrawlCatalogBook::getCatalogId, catalogId));
        Map<String, int[]> counts = new HashMap<>();   // tag → [总数, 站点, AI]
        Map<String, Integer> cats = new HashMap<>();
        int aiTagged = 0;
        for (CrawlCatalogBook b : rows) {
            Set<String> site = new LinkedHashSet<>(Objects.requireNonNullElse(b.getTags(), List.of()));
            Set<String> ai = new LinkedHashSet<>(Objects.requireNonNullElse(b.getAiTags(), List.of()));
            Set<String> all = new LinkedHashSet<>(site);
            all.addAll(ai);
            aiTagged += ai.isEmpty() ? 0 : 1;
            for (String t : all) {
                int[] c = counts.computeIfAbsent(t, k -> new int[3]);
                c[0]++;
                c[1] += site.contains(t) ? 1 : 0;
                c[2] += ai.contains(t) ? 1 : 0;
            }
            if (b.getCategory() != null && !b.getCategory().isBlank()) {
                cats.merge(b.getCategory(), 1, Integer::sum);
            }
        }
        List<Map<String, Object>> tagList = counts.entrySet().stream()
                .sorted((a, b) -> b.getValue()[0] - a.getValue()[0])
                .map(e -> Map.<String, Object>of("tag", e.getKey(), "count", e.getValue()[0],
                        "site", e.getValue()[1], "ai", e.getValue()[2]))
                .toList();
        List<Map<String, Object>> catList = cats.entrySet().stream()
                .sorted((a, b) -> b.getValue() - a.getValue())
                .map(e -> Map.<String, Object>of("name", e.getKey(), "count", e.getValue()))
                .toList();
        long tocMissing = bookMapper.selectCount(new LambdaQueryWrapper<CrawlCatalogBook>()
                .eq(CrawlCatalogBook::getCatalogId, catalogId).eq(CrawlCatalogBook::getTocOk, false)
                .isNotNull(CrawlCatalogBook::getTocUrl));
        return Map.of("tags", tagList, "categories", catList, "total", rows.size(), "aiTagged", aiTagged,
                "tocMissing", tocMissing);
    }

    /** 一本书的完整目录（采集时保存的 JSON）：{bookName, tocUrl, chapterCount, chapters[{title, url}], savedAt} */
    public JsonNode toc(Long bookId) {
        CrawlCatalogBook book = bookMapper.selectById(bookId);
        if (book == null) {
            throw new BizException(404, "这本书不在书目里（可能已删除）");
        }
        if (book.getTocPath() == null || book.getTocPath().isBlank()) {
            throw new BizException(404, "这本书没有采集到目录");
        }
        Path file = dataPaths.resolve(DataPaths.SITE_CATALOG, book.getTocPath());
        try {
            return objectMapper.readTree(Files.readString(file, StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new BizException(404, "目录文件不存在或已损坏，请重新扩充书目");
        }
    }

    // ---------------------------------------------------------------- 按情节找书 / AI 补标签（当前激活的大模型）

    /**
     * 按情节找书 · 标签匹配（省 token，一次调用）：大模型理解描述后，只从书目已有的标签里挑出相关的；
     * 前端再用这些标签（任一）筛书，标签可以再手动增删。→ {tags, suggested（书目里没有的标签）, reason, usage, model}
     */
    public Map<String, Object> plotTags(Long catalogId, Map<String, Object> body) {
        require(catalogId);
        String query = query(body);
        AiModelConfig model = modelService.requireActive();
        List<String> vocabulary = vocabulary(catalogId, 600);
        if (vocabulary.isEmpty()) {
            throw new BizException(400, "书目里还没有任何标签：先点「AI 补标签」，或改用「AI 读简介」");
        }
        JsonNode res = callPython(() -> aiClient.catalogPlotTags(query, vocabulary, model));
        @SuppressWarnings("unchecked")
        Map<String, Object> out = new LinkedHashMap<>(objectMapper.convertValue(res, Map.class));
        out.put("model", model.getName());
        return out;
    }

    /** AI 读简介：一次最多分析这么多本 */
    private static final int INTRO_MAX = 1000;
    /** 估算 token：中文约 1.3 字 / token，每批（25 本）另有提示词约 250 + 输出约 25×45 */
    private static final int INTRO_BATCH = 25;

    /**
     * 按情节找书 · AI 读简介（耗 token）：大模型分批逐本阅读简介打分。filter = 当前筛选（只分析筛选出的书，省 token），
     * 为空则整个书目。estimate=true 只返回本数 / 批数 / 预计 token，不调用模型。
     * → {results[书 + score + reason]（≥ threshold，高分在前）, analyzed, scored, batches, failedBatches, errors, usage, model}
     */
    public Map<String, Object> introMatch(Long catalogId, Map<String, Object> body) {
        require(catalogId);
        if (body == null) {
            throw new BizException(400, "缺少参数");
        }
        BookFilter filter = BookFilter.of(body.get("filter"));
        LambdaQueryWrapper<CrawlCatalogBook> q = bookQuery(catalogId, filter).orderByAsc(CrawlCatalogBook::getId);
        long matched = bookMapper.selectCount(bookQuery(catalogId, filter));
        if (Boolean.TRUE.equals(body.get("estimate"))) {
            List<CrawlCatalogBook> books = bookMapper.selectList(q.last("LIMIT " + INTRO_MAX));
            long chars = books.stream().mapToLong(b -> {
                String intro = Objects.requireNonNullElse(b.getIntro(), "");
                return Math.min(intro.length(), 300) + Objects.requireNonNullElse(b.getBookName(), "").length() + 20;
            }).sum();
            int batches = (books.size() + INTRO_BATCH - 1) / INTRO_BATCH;
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("books", books.size());
            out.put("matched", matched);
            out.put("truncated", matched > INTRO_MAX);
            out.put("batches", batches);
            out.put("promptTokens", Math.round(chars / 1.3) + batches * 250L);
            out.put("completionTokens", (long) books.size() * 45 + batches * 60L);
            AiModelConfig cfg = modelService.requireActive();
            out.put("model", cfg.getName());
            out.put("modelId", cfg.getModel());   // 前端按模型名查单价估算费用
            return out;
        }
        String query = query(body);
        AiModelConfig model = modelService.requireActive();
        List<CrawlCatalogBook> books = bookMapper.selectList(q.last("LIMIT " + INTRO_MAX));
        if (books.isEmpty()) {
            throw new BizException(400, "当前筛选下没有书可以分析");
        }
        int threshold = clamp(body.get("threshold"), 0, 100, 50);
        List<Map<String, Object>> items = books.stream().map(this::aiItem).toList();
        JsonNode res = callPython(() -> aiClient.catalogIntroMatch(query, items, threshold, model));
        Map<Long, CrawlCatalogBook> byId = books.stream().collect(Collectors.toMap(CrawlCatalogBook::getId, b -> b));
        List<CrawlCatalogBook> results = new ArrayList<>();
        for (JsonNode r : res.path("results")) {
            CrawlCatalogBook b = byId.remove(r.path("id").asLong());
            if (b != null) {
                b.setScore(r.path("score").asInt());
                b.setReason(r.path("reason").asText(""));
                results.add(b);
            }
        }
        decorateCrawl(results);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("results", results);
        out.put("analyzed", res.path("analyzed").asInt());
        out.put("scored", res.path("scored").asInt());
        out.put("matched", matched);
        out.put("truncated", matched > INTRO_MAX);
        out.put("batches", res.path("batches").asInt());
        out.put("failedBatches", res.path("failedBatches").asInt());
        out.put("errors", objectMapper.convertValue(res.path("errors"), List.class));
        out.put("usage", objectMapper.convertValue(res.path("usage"), Map.class));
        out.put("model", model.getName());
        log.info("AI 读简介 catalogId={}：分析 {} 本，相关 {} 本，token {}", catalogId, res.path("analyzed").asInt(),
                results.size(), res.path("usage"));
        return out;
    }

    private static String query(Map<String, Object> body) {
        String query = body == null ? null : str(body.get("query"));
        if (query == null || query.isEmpty()) {
            throw new BizException(400, "请描述想找什么样的情节");
        }
        return query.length() > 500 ? query.substring(0, 500) : query;
    }

    /**
     * AI 补标签：按书名 / 简介给书打 3~6 个题材标签（存 ai_tags，筛选时与站点标签同等使用）。
     * {limit?(1~100, 默认 40), retag?(true = 已有 AI 标签的也重打)} → {tagged, remaining, model}
     */
    public Map<String, Object> aiTags(Long catalogId, Map<String, Object> body) {
        require(catalogId);
        int limit = clamp(body == null ? null : body.get("limit"), 1, 100, 40);
        boolean retag = body != null && Boolean.TRUE.equals(body.get("retag"));
        AiModelConfig model = modelService.requireActive();
        LambdaQueryWrapper<CrawlCatalogBook> q = new LambdaQueryWrapper<CrawlCatalogBook>()
                .eq(CrawlCatalogBook::getCatalogId, catalogId);
        if (!retag) {
            q.and(w -> w.isNull(CrawlCatalogBook::getAiTags).or().eq(CrawlCatalogBook::getAiTags, "[]"));
        }
        q.orderByAsc(CrawlCatalogBook::getId).last("LIMIT " + limit);
        List<CrawlCatalogBook> todo = bookMapper.selectList(q);
        List<String> vocabulary = vocabulary(catalogId, 300);
        int tagged = 0;
        for (int i = 0; i < todo.size(); i += TAG_BATCH) {
            List<CrawlCatalogBook> batch = todo.subList(i, Math.min(i + TAG_BATCH, todo.size()));
            List<Map<String, Object>> items = batch.stream().map(this::aiItem).toList();
            JsonNode res = callPython(() -> aiClient.catalogTag(items, vocabulary, model));
            Map<Long, CrawlCatalogBook> byId = batch.stream().collect(Collectors.toMap(CrawlCatalogBook::getId, b -> b));
            for (JsonNode r : res) {
                CrawlCatalogBook b = byId.get(r.path("id").asLong());
                if (b == null) {
                    continue;
                }
                List<String> tags = new ArrayList<>();
                r.path("tags").forEach(t -> tags.add(t.asText()));
                bookMapper.update(null, new LambdaUpdateWrapper<CrawlCatalogBook>()
                        .eq(CrawlCatalogBook::getId, b.getId())
                        .set(CrawlCatalogBook::getAiTags, toJson(tags))
                        .set(CrawlCatalogBook::getUpdateTime, LocalDateTime.now()));
                tagged++;
            }
        }
        long remaining = bookMapper.selectCount(new LambdaQueryWrapper<CrawlCatalogBook>()
                .eq(CrawlCatalogBook::getCatalogId, catalogId)
                .and(w -> w.isNull(CrawlCatalogBook::getAiTags).or().eq(CrawlCatalogBook::getAiTags, "[]")));
        CrawlSiteCatalog catalog = require(catalogId);
        exportCatalog(catalog);
        log.info("AI 补标签 catalogId={}：{} 本，剩余 {} 本没有 AI 标签", catalogId, tagged, remaining);
        return Map.of("tagged", tagged, "remaining", remaining, "model", model.getName());
    }

    private Map<String, Object> aiItem(CrawlCatalogBook b) {
        List<String> tags = new ArrayList<>(Objects.requireNonNullElse(b.getTags(), List.of()));
        Objects.requireNonNullElse(b.getAiTags(), List.<String>of()).forEach(t -> {
            if (!tags.contains(t)) {
                tags.add(t);
            }
        });
        String intro = Objects.requireNonNullElse(b.getIntro(), "");
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", b.getId());
        item.put("bookName", Objects.requireNonNullElse(b.getBookName(), ""));
        item.put("author", Objects.requireNonNullElse(b.getAuthor(), ""));
        item.put("category", Objects.requireNonNullElse(b.getCategory(), ""));
        item.put("tags", tags.size() > 10 ? tags.subList(0, 10) : tags);
        item.put("intro", intro.length() > 300 ? intro.substring(0, 300) : intro);
        return item;
    }

    /** 书目已有的标签 + 分类（按出现次数，≤ max 个），让模型尽量沿用 / 从中挑选 */
    @SuppressWarnings("unchecked")
    private List<String> vocabulary(Long catalogId, int max) {
        Map<String, Object> t = tags(catalogId);
        Set<String> out = new LinkedHashSet<>();
        ((List<Map<String, Object>>) t.get("tags")).forEach(m -> out.add(String.valueOf(m.get("tag"))));
        ((List<Map<String, Object>>) t.get("categories")).forEach(m -> out.add(String.valueOf(m.get("name"))));
        return out.stream().limit(max).toList();
    }

    // ---------------------------------------------------------------- 装饰 / 导出 / 工具

    private CrawlSiteCatalog require(Long id) {
        CrawlSiteCatalog catalog = catalogMapper.selectById(id);
        if (catalog == null) {
            throw new BizException(404, "站点书目不存在（可能已删除）");
        }
        return catalog;
    }

    private CrawlSiteCatalog decorate(CrawlSiteCatalog catalog) {
        if (catalog.getRuleId() != null) {
            try {
                CrawlSiteRule rule = ruleService.getById(catalog.getRuleId());
                Map<String, Object> info = new LinkedHashMap<>();
                info.put("id", rule.getId());
                info.put("status", rule.getStatus());
                info.put("siteName", rule.getSiteName());
                info.put("summary", rule.getSummary());
                info.put("bookUrlPattern", rule.getBookUrlPattern());
                catalog.setRule(info);
            } catch (BizException e) {
                catalog.setRule(null);   // 规则已删除
            }
        }
        return catalog;
    }

    /** 按目录页地址关联最近一次抓取（novel_crawl_book），列表里标出「已抓取 / 抓取中 / 失败」 */
    private void decorateCrawl(List<CrawlCatalogBook> books) {
        List<String> urls = books.stream().map(CrawlCatalogBook::getTocUrl).filter(Objects::nonNull).distinct().toList();
        if (urls.isEmpty()) {
            return;
        }
        Map<String, NovelCrawlBook> latest = new HashMap<>();
        for (NovelCrawlBook row : crawlBookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                .in(NovelCrawlBook::getTocUrl, urls).orderByDesc(NovelCrawlBook::getId))) {
            latest.putIfAbsent(row.getTocUrl(), row);
        }
        for (CrawlCatalogBook b : books) {
            NovelCrawlBook row = b.getTocUrl() == null ? null : latest.get(b.getTocUrl());
            if (row != null) {
                Map<String, Object> info = new LinkedHashMap<>();
                info.put("status", row.getStatus());
                info.put("fileId", row.getFileId());
                info.put("crawlId", row.getCrawlId());
                info.put("message", row.getMessage());
                b.setCrawl(info);
            }
        }
    }

    /** 同一首页的书目导出到 data/&lt;catalogDir&gt;/catalog.json（临时文件 → 原子改名）；失败只记日志，数据库为准 */
    private void exportCatalog(CrawlSiteCatalog catalog) {
        Path dir = catalogPath(catalog);
        if (dir == null) {
            return;
        }
        Path target = dir.resolve("catalog.json");
        Path tmp = dir.resolve("catalog.json.part");
        try {
            List<CrawlCatalogBook> books = bookMapper.selectList(new LambdaQueryWrapper<CrawlCatalogBook>()
                    .eq(CrawlCatalogBook::getCatalogId, catalog.getId()).orderByAsc(CrawlCatalogBook::getId));
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("homeUrl", catalog.getHomeUrl());
            data.put("host", catalog.getHost());
            data.put("siteName", catalog.getSiteName());
            data.put("ruleId", catalog.getRuleId());
            data.put("decision", catalog.getDecision());
            data.put("report", catalog.getReport());
            data.put("lastReport", catalog.getLastReport());
            data.put("bookCount", books.size());
            data.put("exportTime", LocalDateTime.now().toString());
            data.put("books", books);
            Files.createDirectories(dir);
            Files.write(tmp, objectMapper.writerWithDefaultPrettyPrinter().writeValueAsBytes(data));
            try {
                Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException e) {
                Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException e) {
            log.warn("导出书目失败 {}：{}", target, e.getMessage());
        }
    }

    private Path catalogPath(CrawlSiteCatalog catalog) {
        try {
            return dataPaths.resolve(DataPaths.SITE_CATALOG, catalog.getCatalogDir());
        } catch (BizException e) {
            log.warn("书目目录不合法：{}", catalog.getCatalogDir());
            return null;
        }
    }

    private List<String> bookUrls(Long catalogId) {
        return bookMapper.selectList(new LambdaQueryWrapper<CrawlCatalogBook>()
                        .select(CrawlCatalogBook::getBookUrl).eq(CrawlCatalogBook::getCatalogId, catalogId))
                .stream().map(CrawlCatalogBook::getBookUrl).filter(Objects::nonNull).limit(5000).toList();
    }

    private int countBooks(Long catalogId) {
        return Math.toIntExact(bookMapper.selectCount(new LambdaQueryWrapper<CrawlCatalogBook>()
                .eq(CrawlCatalogBook::getCatalogId, catalogId)));
    }

    /** 规则的站点首页；老规则没有 homeUrl 时用学习样例的 scheme://host[:port]/ */
    private static String homeUrlOf(CrawlSiteRule rule) {
        String home = rule.getHomeUrl();
        if (home == null || home.isBlank()) {
            home = rule.getSampleUrl();
        }
        if (home == null || CrawlRuleService.hostOf(home) == null) {
            return null;
        }
        try {
            URI uri = new URI(home.trim());
            return uri.getScheme().toLowerCase(Locale.ROOT) + "://" + uri.getRawAuthority() + "/";
        } catch (Exception e) {
            return null;
        }
    }

    /** data/site-catalog/ 下的目录名：域名（含非默认端口），只留安全字符 */
    private static String dirName(String homeUrl) {
        try {
            URI uri = new URI(homeUrl);
            String name = uri.getHost().toLowerCase(Locale.ROOT) + (uri.getPort() > 0 ? "_" + uri.getPort() : "");
            name = name.replaceAll("[^A-Za-z0-9._-]", "_");
            return name.length() > 120 ? name.substring(0, 120) : name;
        } catch (Exception e) {
            return "unknown";
        }
    }

    /** Python 不可达 → 503；4xx 只透传我们自己的 {message}（AI 请求体带 API Key，校验错误的回显不外传） */
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
                if (body.hasNonNull("message") && status != 422) {
                    message = body.get("message").asText();
                }
            } catch (Exception ignored) {
                // 非 JSON 响应
            }
            throw new BizException(status == 404 ? 404 : 400, message);
        }
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return "[]";
        }
    }

    private static String text(JsonNode node, String key) {
        String value = node.path(key).asText("");
        return value.isEmpty() ? null : value;
    }

    private static String truncate(String message) {
        return message != null && message.length() > 500 ? message.substring(0, 500) : message;
    }

    private static int clamp(Object value, int min, int max, int fallback) {
        Integer n = intOrNull(value);
        return Math.max(min, Math.min(max, n == null ? fallback : n));
    }

    private static Integer intOrNull(Object value) {
        if (value instanceof Number num) {
            return num.intValue();
        }
        if (value instanceof String s && s.trim().matches("\\d{1,9}")) {
            return Integer.parseInt(s.trim());
        }
        return null;
    }

    private static String str(Object value) {
        return value == null ? null : String.valueOf(value).trim();
    }
}
