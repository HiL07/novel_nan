package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.CrawlSite;
import com.example.file.entity.CrawlSiteRule;
import com.example.file.entity.FileInfo;
import com.example.file.entity.NovelCrawl;
import com.example.file.entity.NovelCrawlBook;
import com.example.file.mapper.CrawlSiteMapper;
import com.example.file.mapper.NovelCrawlBookMapper;
import com.example.file.mapper.NovelCrawlMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
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
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Supplier;

/**
 * 网络小说抓取，两种采集模式：
 * <ul>
 *   <li>单本（mode=book）：一个目录页 → 一个 txt；</li>
 *   <li>整站 / 全自动（mode=site）：书籍清单来自全自动爬虫的站点书目（{@link CrawlCatalogService}：按 AI 学到的
 *       规律找书、取简介 / 标签 / 目录，用户筛选后提交），再<b>逐本</b>复用单本抓取流程，
 *       每本存为一个 txt（明细见 novel_crawl_book）。</li>
 * </ul>
 * Python 只负责抓取与解析，Java 是唯一写库 / 写文件的一方。任务之间单线程串行（Python 端也只跑一个）。
 */
@Service
public class NovelCrawlService {

    private static final Logger log = LoggerFactory.getLogger(NovelCrawlService.class);

    private static final long POLL_INTERVAL_MS = 3000;
    /** Python 服务连续不可达的最大次数（约 1 分钟）后判定失败 */
    private static final int MAX_UNREACHABLE = 20;
    /** 转发给 Python 的参数白名单（与 python-service/app/crawler/service.py 的 CrawlRequest / SiteOptions 一致） */
    private static final Set<String> OPTION_KEYS = Set.of("url", "preset", "rule", "delayMs", "respectRobots",
            "startIndex", "endIndex", "mode", "maxCategories", "maxListPages", "maxBooks", "maxChaptersPerBook",
            "categories", "verify", "books", "saveDir");
    /** 只在 Java 用、不转发给 Python 的参数：另存目录、套用的已学规则 id */
    private static final List<String> JAVA_ONLY_KEYS = List.of("saveDir", "learnedRuleId");
    /** 学到的规则在规则下拉框里的值：learned:&lt;id&gt; */
    private static final String LEARNED_PREFIX = "learned:";
    /** 整站模式下每本书要保留的参数（其余是旧版整站发现的上限参数，留在 options 里不再使用） */
    private static final List<String> BOOK_JOB_KEYS = List.of("preset", "rule", "delayMs", "respectRobots");

    private final NovelCrawlMapper crawlMapper;
    private final NovelCrawlBookMapper bookMapper;
    private final FileService fileService;
    private final AiServiceClient aiClient;
    private final CrawlRuleService ruleService;
    private final ObjectMapper objectMapper;
    private final CrawlSiteMapper siteMapper;
    /** 整站工作区：「同一首页加入进行中的任务」与「任务收尾」互斥，避免刚加入的书没人抓 */
    private final Object workspaceLock = new Object();
    /**
     * 按首页分队列：同一首页（scheme://host[:port]/）的任务依次执行（照顾站点限速，整站工作区与单本共用一条队），
     * 不同首页互不影响、并行执行。lanes 存每个首页队尾的 Future，新任务接在它后面。
     */
    private final ExecutorService executor = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "novel-crawl");
        t.setDaemon(true);
        return t;
    });
    private final Map<String, CompletableFuture<Void>> lanes = new ConcurrentHashMap<>();
    /** 已被请求取消的整站任务（跨线程可见，抓完当前这本着循环检查） */
    private final Set<Long> siteCancels = ConcurrentHashMap.newKeySet();

    public NovelCrawlService(NovelCrawlMapper crawlMapper, NovelCrawlBookMapper bookMapper, FileService fileService,
                             AiServiceClient aiClient, CrawlRuleService ruleService, ObjectMapper objectMapper,
                             CrawlSiteMapper siteMapper) {
        this.siteMapper = siteMapper;
        this.crawlMapper = crawlMapper;
        this.bookMapper = bookMapper;
        this.fileService = fileService;
        this.aiClient = aiClient;
        this.ruleService = ruleService;
        this.objectMapper = objectMapper;
    }

    /**
     * 启动完成后，把上次未完成的任务（含整站任务的书籍明细）标记为失败（执行线程已随进程退出）。
     */
    @EventListener(ApplicationReadyEvent.class)
    public void failInterrupted() {
        LocalDateTime now = LocalDateTime.now();
        int n = crawlMapper.update(null, new LambdaUpdateWrapper<NovelCrawl>()
                .in(NovelCrawl::getStatus, NovelCrawl.QUEUED, NovelCrawl.RUNNING)
                .set(NovelCrawl::getStatus, NovelCrawl.FAILED)
                .set(NovelCrawl::getMessage, "服务重启，任务中断；已抓的章节已保存，可点「继续抓取」从断点接着抓")
                .set(NovelCrawl::getUpdateTime, now));
        int books = bookMapper.update(null, new LambdaUpdateWrapper<NovelCrawlBook>()
                .in(NovelCrawlBook::getStatus, NovelCrawlBook.QUEUED, NovelCrawlBook.RUNNING)
                .set(NovelCrawlBook::getStatus, NovelCrawlBook.FAILED)
                .set(NovelCrawlBook::getMessage, "服务重启，任务中断")
                .set(NovelCrawlBook::getUpdateTime, now));
        if (n > 0 || books > 0) {
            log.warn("已将 {} 个中断的抓取任务、{} 本书籍标记为失败", n, books);
        }
    }

    /** 同一首页是否已有任务在排队 / 执行 */
    private boolean laneBusy(String url) {
        CompletableFuture<Void> tail = lanes.get(laneKey(url));
        return tail != null && !tail.isDone();
    }

    private static String laneKey(String url) {
        String home = homeOf(url);
        return home == null ? "" : home;
    }

    /** 放进该首页的队列：等同一首页前面的任务结束（成功失败都算）再执行 */
    private void enqueue(String url, Runnable job) {
        String key = laneKey(url);
        lanes.compute(key, (k, prev) -> {
            CompletableFuture<Void> start = prev == null ? CompletableFuture.completedFuture(null)
                    : prev.handle((v, e) -> null);
            CompletableFuture<Void> next = start.thenRunAsync(() -> {
                try {
                    job.run();
                } catch (RuntimeException e) {
                    log.error("抓取任务异常退出（{}）", k, e);
                }
            }, executor);
            // 队尾执行完且仍是队尾时移除，避免首页越积越多
            next.whenComplete((v, e) -> lanes.remove(k, next));
            return next;
        });
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    // ---------------------------------------------------------------- 规则 / 预览

    /** 规则预设列表（自动识别 / 笔趣阁式 / 维基文库 / 全书网原规则…） */
    public JsonNode presets() {
        return callPython(aiClient::crawlPresets);
    }

    /** 单本：解析目录 + 试抓第一章 → {bookName, author, intro, chapters[{title,url}], chapterCount, preset, rule, sample} */
    public JsonNode preview(Map<String, Object> options) {
        Map<String, Object> body = normalize(options);
        body.remove("startIndex");
        body.remove("endIndex");
        body.remove("books");
        body.remove("mode");
        CrawlSiteRule learned = applyLearnedRule(body);
        Map<String, Object> req = pythonBody(body);
        return withLearned(callPython(() -> aiClient.crawlPreview(req)), learned);
    }

    // ---------------------------------------------------------------- 提交 / 查询 / 取消

    /** 提交抓取任务（按 options.mode 分派单本 / 整站），立即返回任务记录（QUEUED）。 */
    public NovelCrawl submit(Map<String, Object> options) {
        Map<String, Object> body = normalize(options);
        checkSaveDir(body);
        // 学到的规则在提交时合并进 options 存档，之后重抓 / 续抓不受规则后续变化影响
        applyLearnedRule(body);
        boolean site = isSite(body);
        List<Map<String, Object>> books = site ? booksOf(body) : List.of();
        if (site && books.isEmpty()) {
            throw new BizException(400, "整站抓取需要先在站点书目里勾选要抓的书");
        }
        if (site) {
            NovelCrawl joined = joinActiveWorkspace(body, books);
            if (joined != null) {
                return joined;
            }
        }
        NovelCrawl task = new NovelCrawl();
        task.setUrl((String) body.get("url"));
        task.setOptions(toJson(body));
        task.setStatus(NovelCrawl.QUEUED);
        task.setProgress(0);
        String waitHost = laneBusy(task.getUrl()) ? CrawlRuleService.hostOf(task.getUrl()) : null;
        task.setMessage(waitHost == null ? "排队中" : "排队中：同一网站（" + waitHost + "）还有任务在抓，抓完接着抓这个");
        task.setCreateTime(LocalDateTime.now());
        task.setUpdateTime(task.getCreateTime());
        crawlMapper.insert(task);
        if (site) {
            insertBooks(task.getId(), books);
        }
        Long taskId = task.getId();
        enqueue(task.getUrl(), () -> {
            if (site) {
                runSite(taskId, body, null);
            } else {
                run(taskId, body, null);
            }
        });
        return decorate(task);
    }

    /**
     * 一个首页只有一个工作区：该首页已有排队 / 抓取中的整站任务时，新勾选的书直接加入它（已在里面且没失败的跳过），
     * 不再另开任务；runSite 会在抓完手头的书后接着抓新加入的。→ 加入的任务（message 说明加入了几本），没有进行中的返回 null
     */
    private NovelCrawl joinActiveWorkspace(Map<String, Object> body, List<Map<String, Object>> books) {
        String home = homeOf(str(body.get("url")));
        if (home == null) {
            return null;
        }
        synchronized (workspaceLock) {
            NovelCrawl active = crawlMapper.selectList(new LambdaQueryWrapper<NovelCrawl>()
                            .in(NovelCrawl::getStatus, NovelCrawl.QUEUED, NovelCrawl.RUNNING)
                            .like(NovelCrawl::getOptions, SITE_MARK).orderByAsc(NovelCrawl::getId))
                    .stream().filter(t -> home.equals(homeOf(t.getUrl()))).findFirst().orElse(null);
            if (active == null) {
                return null;
            }
            Map<String, String> existing = new HashMap<>();
            for (NovelCrawlBook b : bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                    .select(NovelCrawlBook::getTocUrl, NovelCrawlBook::getStatus).eq(NovelCrawlBook::getCrawlId, active.getId()))) {
                existing.put(b.getTocUrl(), b.getStatus());
            }
            List<Map<String, Object>> fresh = books.stream()
                    .filter(b -> !existing.containsKey((String) b.get("tocUrl"))).toList();
            insertBooks(active.getId(), fresh);
            NovelCrawl out = decorate(crawlMapper.selectById(active.getId()));
            out.setMessage("已加入该网站正在进行的工作区：新增 " + fresh.size() + " 本"
                    + (books.size() > fresh.size() ? "，" + (books.size() - fresh.size()) + " 本已在队列里" : ""));
            log.info("整站工作区 {} 加入 {} 本（任务 {}）", home, fresh.size(), active.getId());
            return out;
        }
    }

    /** 整站抓取：强制 mode=site（不改调用方传入的 Map） */
    public NovelCrawl submitSite(Map<String, Object> options) {
        Map<String, Object> body = options == null ? new LinkedHashMap<>() : new LinkedHashMap<>(options);
        body.put("mode", NovelCrawl.MODE_SITE);
        return submit(body);
    }

    /** 用原参数重新抓取（新建任务）：整站任务按已存的书籍清单重跑（要换书请在站点书目里重新勾选） */
    public NovelCrawl retry(Long id) {
        NovelCrawl old = getById(id);
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> options = objectMapper.readValue(old.getOptions(), Map.class);
            return submit(options);
        } catch (JsonProcessingException e) {
            throw new BizException(400, "任务参数损坏，无法重新抓取");
        }
    }

    /**
     * 从断点继续（同一任务，不新建）：失败 / 取消 / 服务重启中断的任务都可以继续。
     * 每次抓取都带 resumeKey，Python 逐章把正文写入 data/crawl-cache/&lt;key&gt;/，所以已抓的章节不会重抓，
     * 目录页失效也能用断点里的章节清单抓完剩下的；整站任务跳过已成功的书，其余逐本续抓。
     *
     * @param newOrigin 站点换了域名 / IP（路径不变）时填新的 http(s)://host[:port]，旧站点下的地址整体替换；可空
     */
    public NovelCrawl resume(Long id, String newOrigin) {
        NovelCrawl task = getById(id);
        boolean site = NovelCrawl.MODE_SITE.equals(task.getMode());
        if (NovelCrawl.QUEUED.equals(task.getStatus()) || NovelCrawl.RUNNING.equals(task.getStatus())) {
            throw new BizException(400, "任务正在进行中");
        }
        if (NovelCrawl.SUCCEEDED.equals(task.getStatus()) && (!site || task.getBookDone() >= task.getBookTotal())) {
            throw new BizException(400, "任务已完成，无需继续");
        }
        String origin = normalizeOrigin(newOrigin);
        Map<String, Object> body;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> options = objectMapper.readValue(task.getOptions(), Map.class);
            body = options;
        } catch (JsonProcessingException e) {
            throw new BizException(400, "任务参数损坏，无法继续，请改参数后重新抓取");
        }
        if (origin != null) {
            String oldOrigin = originOf(task.getUrl());
            String url = replaceOrigin(task.getUrl(), oldOrigin, origin);
            body.put("url", url);
            if (body.get("books") instanceof List<?> list) {
                for (Object item : list) {
                    if (item instanceof Map<?, ?> m && m.get("tocUrl") instanceof String toc) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> book = (Map<String, Object>) m;
                        book.put("tocUrl", replaceOrigin(toc, oldOrigin, origin));
                    }
                }
            }
            NovelCrawl patch = patch(id, null, null, null);
            patch.setUrl(url);
            patch.setOptions(toJson(body));
            crawlMapper.updateById(patch);
            for (NovelCrawlBook book : listBooks(id)) {
                if (!NovelCrawlBook.SUCCEEDED.equals(book.getStatus())) {
                    NovelCrawlBook bp = new NovelCrawlBook();
                    bp.setId(book.getId());
                    bp.setTocUrl(replaceOrigin(book.getTocUrl(), oldOrigin, origin));
                    bookMapper.updateById(bp);
                }
            }
            log.info("抓取任务 {} 换站点地址续抓：{} → {}", id, oldOrigin, origin);
        }
        if (site) {
            bookMapper.update(null, new LambdaUpdateWrapper<NovelCrawlBook>()
                    .eq(NovelCrawlBook::getCrawlId, id)
                    .ne(NovelCrawlBook::getStatus, NovelCrawlBook.SUCCEEDED)
                    .set(NovelCrawlBook::getStatus, NovelCrawlBook.QUEUED)
                    .set(NovelCrawlBook::getMessage, "排队中（继续抓取）")
                    .set(NovelCrawlBook::getUpdateTime, LocalDateTime.now()));
        }
        String resumeUrl = str(body.get("url"));
        update(id, NovelCrawl.QUEUED, null, laneBusy(resumeUrl)
                ? "排队中（从断点继续）：同一网站还有任务在抓，抓完接着抓这个" : "排队中（从断点继续）");
        enqueue(resumeUrl, () -> {
            if (site) {
                runSite(id, body, origin);
            } else {
                run(id, body, origin);
            }
        });
        return getById(id);
    }

    /**
     * 断点概况：单本 → 该任务的断点；整站 → 未完成的书的断点汇总。
     * → {chapterSaved, chapterTotal, booksWithCheckpoint, booksPending, url}
     */
    public Map<String, Object> checkpoint(Long id) {
        NovelCrawl task = getById(id);
        Map<String, Object> out = new LinkedHashMap<>();
        int saved = 0, total = 0, withCp = 0, pending = 0;
        List<String> keys = new ArrayList<>();
        if (NovelCrawl.MODE_SITE.equals(task.getMode())) {
            for (NovelCrawlBook book : listBooks(id)) {
                if (!NovelCrawlBook.SUCCEEDED.equals(book.getStatus())) {
                    pending++;
                    keys.add(resumeKey(id, book.getId()));
                }
            }
        } else {
            keys.add(resumeKey(id, null));
        }
        for (String key : keys) {
            JsonNode info = callPython(() -> aiClient.crawlCheckpoint(key));
            if (info != null && info.path("exists").asBoolean()) {
                withCp++;
                saved += info.path("chapterSaved").asInt();
                total += info.path("chapterTotal").asInt();
                out.putIfAbsent("url", info.path("url").asText());
            }
        }
        out.put("chapterSaved", saved);
        out.put("chapterTotal", total);
        out.put("booksWithCheckpoint", withCp);
        out.put("booksPending", pending);
        return out;
    }

    /** 断点 key：单本 c&lt;任务id&gt;，整站每本 c&lt;任务id&gt;b&lt;书籍id&gt;（Python 校验 [A-Za-z0-9_-]） */
    private static String resumeKey(Long taskId, Long bookId) {
        return bookId == null ? "c" + taskId : "c" + taskId + "b" + bookId;
    }

    /** 取消进行中的任务（Python 在当前章节结束后停止；已保存的 txt 保留） */
    public NovelCrawl cancel(Long id) {
        NovelCrawl task = getById(id);
        if (!NovelCrawl.QUEUED.equals(task.getStatus()) && !NovelCrawl.RUNNING.equals(task.getStatus())) {
            throw new BizException(400, "任务已结束，无需取消");
        }
        if (NovelCrawl.MODE_SITE.equals(modeOf(task))) {
            siteCancels.add(id);
            update(id, null, null, "正在取消…");
            // 取消当前正在抓的那一本（还没提交的书由 runSite 的循环检查标记跳过）
            for (NovelCrawlBook book : runningBooks(id)) {
                if (book.getJobId() != null) {
                    try {
                        aiClient.cancelCrawl(book.getJobId());
                    } catch (Exception e) {
                        log.warn("通知 AI 服务取消《{}》失败：{}", book.getBookName(), e.getMessage());
                    }
                }
            }
            if (NovelCrawl.QUEUED.equals(task.getStatus())) {
                update(id, NovelCrawl.CANCELLED, null, "已取消");
            }
            return getById(id);
        }
        if (task.getJobId() == null) {
            // 还没提交到 Python：直接标记，run() 开始前会检查
            update(id, NovelCrawl.CANCELLED, null, "已取消");
        } else {
            callPython(() -> {
                aiClient.cancelCrawl(task.getJobId());
                return null;
            });
            update(id, null, null, "正在取消…");
        }
        return getById(id);
    }

    /**
     * 抓取进度分页：status 为空 = 全部，ACTIVE = 排队中 + 抓取中，其余按状态精确匹配；新的在前。
     * → {records, total, page, size, active（全部任务里还在排队 / 抓取的个数，前端据此决定是否轮询）}
     */
    public Map<String, Object> page(int page, int size, String status, String mode) {
        LambdaQueryWrapper<NovelCrawl> q = new LambdaQueryWrapper<NovelCrawl>().orderByDesc(NovelCrawl::getId);
        if (NovelCrawl.MODE_SITE.equals(mode)) {
            q.like(NovelCrawl::getOptions, SITE_MARK);
        } else if (NovelCrawl.MODE_BOOK.equals(mode)) {
            q.and(w -> w.isNull(NovelCrawl::getOptions).or().notLike(NovelCrawl::getOptions, SITE_MARK));
        }
        if ("ACTIVE".equalsIgnoreCase(status)) {
            q.in(NovelCrawl::getStatus, NovelCrawl.QUEUED, NovelCrawl.RUNNING);
        } else if (status != null && !status.isBlank()) {
            q.eq(NovelCrawl::getStatus, status.trim().toUpperCase(java.util.Locale.ROOT));
        }
        com.baomidou.mybatisplus.extension.plugins.pagination.Page<NovelCrawl> p = crawlMapper.selectPage(
                new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(Math.max(page, 1), Math.max(1, Math.min(size, 100))), q);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("records", decorate(p.getRecords()));
        out.put("total", p.getTotal());
        out.put("page", p.getCurrent());
        out.put("size", p.getSize());
        LambdaQueryWrapper<NovelCrawl> activeQ = new LambdaQueryWrapper<NovelCrawl>()
                .in(NovelCrawl::getStatus, NovelCrawl.QUEUED, NovelCrawl.RUNNING);
        if (NovelCrawl.MODE_SITE.equals(mode)) {
            activeQ.like(NovelCrawl::getOptions, SITE_MARK);
        } else if (NovelCrawl.MODE_BOOK.equals(mode)) {
            activeQ.and(w -> w.isNull(NovelCrawl::getOptions).or().notLike(NovelCrawl::getOptions, SITE_MARK));
        }
        out.put("active", crawlMapper.selectCount(activeQ));
        return out;
    }

    // ---------------------------------------------------------------- 整站工作区（一个首页一个工作区）

    /** options JSON 里整站任务的标记（toJson 不加空格） */
    private static final String SITE_MARK = "\"mode\":\"site\"";

    /** 首页：scheme://host[:port]/，与小说网站 / 站点书目同口径 */
    static String homeOf(String url) {
        String origin = url == null ? null : originOf(url.trim());
        return origin == null ? null : origin.toLowerCase(java.util.Locale.ROOT) + "/";
    }

    private List<NovelCrawl> siteTasks() {
        return crawlMapper.selectList(new LambdaQueryWrapper<NovelCrawl>()
                .like(NovelCrawl::getOptions, SITE_MARK).orderByDesc(NovelCrawl::getId));
    }

    /** 该首页的全部抓取任务（单本 + 整站），新的在前 */
    private List<NovelCrawl> tasksOf(String home) {
        String h = homeOf(home);
        if (h == null) {
            throw new BizException(400, "首页地址不合法");
        }
        return decorate(crawlMapper.selectList(new LambdaQueryWrapper<NovelCrawl>().orderByDesc(NovelCrawl::getId))
                .stream().filter(t -> h.equals(homeOf(t.getUrl()))).toList());
    }

    private static boolean isSiteTask(NovelCrawl t) {
        return t.getOptions() != null && t.getOptions().contains(SITE_MARK);
    }

    /**
     * 抓取进度的工作区列表（按首页归组：单本抓取 + 整站抓取都在里面，进行中的在前）：
     * [{homeUrl, host, siteName, status: RUNNING|IDLE, activeTaskId, taskCount, sources{book, site},
     *   books{total, queued, running, succeeded, failed, cancelled}, words, current{bookName, source, message, chapterDone,
     *   chapterTotal, progress}, lastTime, resumable}]
     */
    public List<Map<String, Object>> workspaces() {
        Map<String, List<NovelCrawl>> groups = new LinkedHashMap<>();
        for (NovelCrawl t : decorate(crawlMapper.selectList(new LambdaQueryWrapper<NovelCrawl>().orderByDesc(NovelCrawl::getId)))) {
            String home = homeOf(t.getUrl());
            if (home != null) {
                groups.computeIfAbsent(home, k -> new ArrayList<>()).add(t);
            }
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map.Entry<String, List<NovelCrawl>> e : groups.entrySet()) {
            List<NovelCrawl> tasks = e.getValue();
            List<Map<String, Object>> rows = progressRows(tasks);
            NovelCrawl active = tasks.stream().filter(this::isActiveTask).findFirst().orElse(null);
            Map<String, Integer> counts = new LinkedHashMap<>();
            for (String st : List.of("total", "queued", "running", "succeeded", "failed", "cancelled")) {
                counts.put(st, 0);
            }
            int words = 0;
            Map<String, Object> current = null;
            for (Map<String, Object> r : rows) {
                String st = (String) r.get("status");
                counts.merge("total", 1, Integer::sum);
                counts.merge(st == null ? "queued" : st.toLowerCase(java.util.Locale.ROOT), 1, Integer::sum);
                words += NovelCrawl.SUCCEEDED.equals(st) ? (Integer) r.get("wordCount") : 0;
                if (NovelCrawl.RUNNING.equals(st) && current == null) {
                    current = new LinkedHashMap<>();
                    for (String k : List.of("bookName", "source", "message", "chapterDone", "chapterTotal", "progress")) {
                        current.put(k, r.get(k));
                    }
                }
            }
            Map<String, Integer> sources = new LinkedHashMap<>();
            sources.put("book", (int) tasks.stream().filter(t -> !isSiteTask(t)).count());
            sources.put("site", (int) tasks.stream().filter(NovelCrawlService::isSiteTask).count());
            Map<String, Object> ws = new LinkedHashMap<>();
            ws.put("homeUrl", e.getKey());
            ws.put("host", CrawlRuleService.hostOf(e.getKey()));
            ws.put("siteName", siteNameOf(e.getKey()));
            ws.put("status", active != null ? "RUNNING" : "IDLE");
            ws.put("activeTaskId", active == null ? null : active.getId());
            ws.put("taskCount", tasks.size());
            ws.put("sources", sources);
            ws.put("books", counts);
            ws.put("words", words);
            if (current != null) {
                ws.put("current", current);
            }
            ws.put("lastTime", tasks.get(0).getUpdateTime());
            ws.put("resumable", tasks.stream().anyMatch(this::canResume));
            out.add(ws);
        }
        out.sort((x, y) -> Boolean.compare("IDLE".equals(x.get("status")), "IDLE".equals(y.get("status"))));
        return out;
    }

    /**
     * 统一的进度行：整站任务的每本书一行（source=site），单本任务一行（source=book，带 task 供继续 / 重抓 / 改参数）。
     * 每行 {key, source, crawlId, bookId, bookName, author, category, url, status, progress, message, chapterDone,
     * chapterTotal, chapterFailed, wordCount, fileId, createTime, updateTime, task?}
     */
    private List<Map<String, Object>> progressRows(List<NovelCrawl> tasks) {
        List<Map<String, Object>> rows = new ArrayList<>();
        List<Long> siteIds = tasks.stream().filter(NovelCrawlService::isSiteTask).map(NovelCrawl::getId).toList();
        if (!siteIds.isEmpty()) {
            for (NovelCrawlBook b : bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>().in(NovelCrawlBook::getCrawlId, siteIds))) {
                Map<String, Object> r = new LinkedHashMap<>();
                r.put("key", "b" + b.getId());
                r.put("source", NovelCrawl.MODE_SITE);
                r.put("crawlId", b.getCrawlId());
                r.put("bookId", b.getId());
                r.put("bookName", b.getBookName());
                r.put("author", b.getAuthor());
                r.put("category", b.getCategory());
                r.put("url", b.getTocUrl());
                r.put("status", b.getStatus());
                r.put("progress", nz(b.getProgress()));
                r.put("message", b.getMessage());
                r.put("chapterDone", nz(b.getChapterDone()));
                r.put("chapterTotal", nz(b.getChapterTotal()));
                r.put("chapterFailed", nz(b.getChapterFailed()));
                r.put("wordCount", nz(b.getWordCount()));
                r.put("fileId", b.getFileId());
                r.put("createTime", b.getCreateTime());
                r.put("updateTime", b.getUpdateTime());
                rows.add(r);
            }
        }
        for (NovelCrawl t : tasks) {
            if (isSiteTask(t)) {
                continue;
            }
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("key", "t" + t.getId());
            r.put("source", NovelCrawl.MODE_BOOK);
            r.put("crawlId", t.getId());
            r.put("bookId", null);
            r.put("bookName", t.getBookName());
            r.put("author", t.getAuthor());
            r.put("category", null);
            r.put("url", t.getUrl());
            r.put("status", t.getStatus());
            r.put("progress", nz(t.getProgress()));
            r.put("message", t.getMessage());
            r.put("chapterDone", nz(t.getChapterDone()));
            r.put("chapterTotal", nz(t.getChapterTotal()));
            r.put("chapterFailed", nz(t.getChapterFailed()));
            r.put("wordCount", nz(t.getWordCount()));
            r.put("fileId", t.getFileId());
            r.put("createTime", t.getCreateTime());
            r.put("updateTime", t.getUpdateTime());
            r.put("task", t);
            rows.add(r);
        }
        return rows;
    }

    /**
     * 工作区里的每本小说（该首页的单本抓取 + 整站抓取的每本书）：抓取中的置顶，其余新的在前。
     * status 空 = 全部，ACTIVE = 排队 + 抓取中；source = book（单本抓取）/ site（整站抓取）/ 空；keyword 书名模糊。
     * → {records, total, page, size}
     */
    public Map<String, Object> workspaceBooks(String home, String status, String keyword, String source, int page, int size) {
        String st = status == null ? "" : status.trim().toUpperCase(java.util.Locale.ROOT);
        String kw = keyword == null ? "" : keyword.trim();
        String src = source == null ? "" : source.trim();
        List<Map<String, Object>> rows = progressRows(tasksOf(home)).stream()
                .filter(r -> st.isEmpty() || ("ACTIVE".equals(st)
                        ? NovelCrawl.QUEUED.equals(r.get("status")) || NovelCrawl.RUNNING.equals(r.get("status"))
                        : st.equals(r.get("status"))))
                .filter(r -> src.isEmpty() || src.equals(r.get("source")))
                .filter(r -> kw.isEmpty() || (r.get("bookName") != null && ((String) r.get("bookName")).contains(kw)))
                .sorted(java.util.Comparator
                        .comparing((Map<String, Object> r) -> NovelCrawl.RUNNING.equals(r.get("status")) ? 0 : 1)
                        .thenComparing(r -> (LocalDateTime) r.get("createTime"),
                                java.util.Comparator.nullsLast(java.util.Comparator.reverseOrder())))
                .toList();
        int sz = Math.max(1, Math.min(size, 100));
        int pg = Math.max(page, 1);
        int from = Math.min((pg - 1) * sz, rows.size());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("records", rows.subList(from, Math.min(from + sz, rows.size())));
        out.put("total", rows.size());
        out.put("page", pg);
        out.put("size", sz);
        return out;
    }

    /** 取消工作区里所有排队 / 抓取中的任务（单本 + 整站）→ {cancelled} */
    public Map<String, Object> workspaceCancel(String home) {
        List<NovelCrawl> active = tasksOf(home).stream().filter(this::isActiveTask).toList();
        if (active.isEmpty()) {
            throw new BizException(400, "这个工作区没有正在进行的抓取");
        }
        active.forEach(t -> cancel(t.getId()));
        return Map.of("cancelled", active.size());
    }

    /** 继续工作区里所有没抓完的：失败 / 取消的单本、还有书没成功的整站任务，都从断点接着抓（同一网站依次排队）→ {resumed} */
    public Map<String, Object> workspaceResume(String home) {
        List<NovelCrawl> targets = tasksOf(home).stream().filter(this::canResume).toList();
        if (targets.isEmpty()) {
            throw new BizException(400, tasksOf(home).stream().anyMatch(this::isActiveTask)
                    ? "这个工作区正在抓取中" : "这个工作区的小说都抓完了");
        }
        // 先旧后新，排队顺序与提交顺序一致
        List<NovelCrawl> ordered = new ArrayList<>(targets);
        java.util.Collections.reverse(ordered);
        ordered.forEach(t -> resume(t.getId(), null));
        return Map.of("resumed", ordered.size());
    }

    /** 删除工作区（该首页的全部单本 / 整站任务、书籍明细和断点；进行中的不能删；已存的 txt 保留） */
    public Map<String, Object> workspaceDelete(String home) {
        List<NovelCrawl> tasks = tasksOf(home);
        if (tasks.stream().anyMatch(this::isActiveTask)) {
            throw new BizException(400, "这个工作区正在抓取中，请先取消");
        }
        return delete(tasks.stream().map(NovelCrawl::getId).toList());
    }

    /** 能从断点继续：不在进行中，且（单本）失败 / 取消，或（整站）还有书没成功 */
    private boolean canResume(NovelCrawl t) {
        if (isActiveTask(t)) {
            return false;
        }
        if (isSiteTask(t)) {
            return countBooks(t.getId(), NovelCrawlBook.SUCCEEDED) < countAllBooks(t.getId());
        }
        return NovelCrawl.FAILED.equals(t.getStatus()) || NovelCrawl.CANCELLED.equals(t.getStatus());
    }

    private boolean isActiveTask(NovelCrawl t) {
        return NovelCrawl.QUEUED.equals(t.getStatus()) || NovelCrawl.RUNNING.equals(t.getStatus());
    }

    private int countAllBooks(Long crawlId) {
        return Math.toIntExact(bookMapper.selectCount(new LambdaQueryWrapper<NovelCrawlBook>().eq(NovelCrawlBook::getCrawlId, crawlId)));
    }

    /** 工作区显示名：小说网站里填的名称 → 该站 AI 解析规则的站点名 → 域名 */
    private String siteNameOf(String home) {
        CrawlSite site = siteMapper.selectOne(new LambdaQueryWrapper<CrawlSite>().eq(CrawlSite::getHomeUrl, home).last("LIMIT 1"));
        if (site != null && site.getName() != null && !site.getName().isBlank()) {
            return site.getName();
        }
        CrawlSiteRule rule = ruleService.findForUrl(home);
        if (rule != null && rule.getSiteName() != null && !rule.getSiteName().isBlank()) {
            return rule.getSiteName();
        }
        return CrawlRuleService.hostOf(home);
    }

    /**
     * 删除抓取任务（可多选）：只删已结束的（排队 / 抓取中的要先取消），连同整站任务的书籍明细和 AI 服务里的断点
     * （data/crawl-cache/&lt;key&gt;/）；已保存到文件管理的 txt 不删。→ {deleted, skipped（进行中跳过的）, checkpointErrors}
     */
    public Map<String, Object> delete(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            throw new BizException(400, "请选择要删除的任务");
        }
        int deleted = 0;
        int skipped = 0;
        int checkpointErrors = 0;
        for (Long id : ids) {
            NovelCrawl task = crawlMapper.selectById(id);
            if (task == null) {
                continue;
            }
            if (NovelCrawl.QUEUED.equals(task.getStatus()) || NovelCrawl.RUNNING.equals(task.getStatus())) {
                skipped++;
                continue;
            }
            List<String> keys = new ArrayList<>();
            keys.add(resumeKey(id, null));
            for (NovelCrawlBook book : bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                    .select(NovelCrawlBook::getId).eq(NovelCrawlBook::getCrawlId, id))) {
                keys.add(resumeKey(id, book.getId()));
            }
            for (String key : keys) {
                try {
                    aiClient.deleteCrawlCheckpoint(key);
                } catch (Exception e) {
                    // AI 服务没开 / 断点正被使用：数据库照删，断点文件留着（不影响以后的任务，key 不会重复）
                    checkpointErrors++;
                    log.warn("删除抓取断点 {} 失败：{}", key, e.getMessage());
                }
            }
            bookMapper.delete(new LambdaQueryWrapper<NovelCrawlBook>().eq(NovelCrawlBook::getCrawlId, id));
            crawlMapper.deleteById(id);
            deleted++;
        }
        log.info("删除抓取任务 {} 个，跳过进行中的 {} 个", deleted, skipped);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("deleted", deleted);
        out.put("skipped", skipped);
        out.put("checkpointErrors", checkpointErrors);
        return out;
    }

    public NovelCrawl getById(Long id) {
        NovelCrawl task = crawlMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "抓取任务不存在：" + id);
        }
        return decorate(task);
    }

    /** 整站任务的书籍明细（按发现顺序），单本任务返回空列表 */
    public List<NovelCrawlBook> listBooks(Long id) {
        getById(id);
        return bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                .eq(NovelCrawlBook::getCrawlId, id).orderByAsc(NovelCrawlBook::getId));
    }

    // ---------------------------------------------------------------- 单本抓取

    private void run(Long taskId, Map<String, Object> options, String newOrigin) {
        if (NovelCrawl.CANCELLED.equals(crawlMapper.selectById(taskId).getStatus())) {
            return;
        }
        Map<String, Object> body = pythonBody(options);
        body.remove("mode");
        body.put("resumeKey", resumeKey(taskId, null));
        if (newOrigin != null) {
            body.put("newOrigin", newOrigin);
        }
        try {
            JsonNode job = aiClient.submitCrawl(body).path("data");
            String jobId = job.path("jobId").asText();
            // 提交期间用户点了取消：转告 Python，轮询会拿到 cancelled
            boolean cancelled = NovelCrawl.CANCELLED.equals(crawlMapper.selectById(taskId).getStatus());
            NovelCrawl patch = patch(taskId, cancelled ? null : NovelCrawl.RUNNING, 0, cancelled ? "正在取消…" : "已提交 AI 服务");
            patch.setJobId(jobId);
            patch.setPreset(job.path("preset").asText(null));
            crawlMapper.updateById(patch);
            if (cancelled) {
                aiClient.cancelCrawl(jobId);
            }
            poll(taskId, jobId, str(options.get("saveDir")));
        } catch (ResourceAccessException e) {
            log.error("AI 服务不可达，crawlId={}", taskId, e);
            update(taskId, NovelCrawl.FAILED, null, "AI 服务不可达，请确认 python-service 已启动后「继续抓取」");
        } catch (RestClientResponseException e) {
            log.error("AI 服务拒绝抓取任务，crawlId={}，HTTP {}", taskId, e.getStatusCode().value());
            update(taskId, NovelCrawl.FAILED, null, "AI 服务拒绝任务：" + pythonMessage(e));
        } catch (Exception e) {
            log.error("小说抓取失败，crawlId={}", taskId, e);
            update(taskId, NovelCrawl.FAILED, null, "抓取失败：" + e.getMessage());
        }
    }

    private void poll(Long taskId, String jobId, String saveDir) throws Exception {
        int unreachable = 0;
        while (!Thread.currentThread().isInterrupted()) {
            Thread.sleep(POLL_INTERVAL_MS);
            JsonNode job;
            try {
                job = aiClient.getCrawlJob(jobId).path("data");
                unreachable = 0;
            } catch (HttpClientErrorException.NotFound e) {
                update(taskId, NovelCrawl.FAILED, null, "AI 服务已重启，任务中断；已抓的章节已保存，可「继续抓取」");
                return;
            } catch (ResourceAccessException e) {
                if (++unreachable >= MAX_UNREACHABLE) {
                    throw e;
                }
                continue;
            }

            String status = job.path("status").asText();
            NovelCrawl patch = patch(taskId, null, job.path("progress").asInt(), job.path("message").asText());
            patch.setBookName(job.path("bookName").asText(null));
            patch.setAuthor(job.path("author").asText(null));
            patch.setChapterTotal(job.path("chapterTotal").asInt());
            patch.setChapterDone(job.path("chapterDone").asInt());
            patch.setChapterFailed(job.path("chapterFailed").asInt());
            patch.setWordCount(job.path("wordCount").asInt());
            switch (status) {
                case "succeeded" -> {
                    crawlMapper.updateById(patch);
                    finishSucceeded(taskId, jobId, job, saveDir);
                    return;
                }
                case "failed" -> {
                    patch.setStatus(NovelCrawl.FAILED);
                    patch.setMessage(truncate("抓取失败：" + job.path("error").asText()));
                    crawlMapper.updateById(patch);
                    return;
                }
                case "cancelled" -> {
                    patch.setStatus(NovelCrawl.CANCELLED);
                    crawlMapper.updateById(patch);
                    return;
                }
                default -> {
                    patch.setStatus(NovelCrawl.RUNNING);
                    crawlMapper.updateById(patch);
                }
            }
        }
    }

    /** 成功收尾：取全文 → 存为 txt（落盘 + file 表）→（可选）另存到用户目录 → 记 fileId → 通知 Python 释放内存。 */
    private void finishSucceeded(Long taskId, String jobId, JsonNode job, String saveDir) {
        byte[] text = aiClient.getCrawlText(jobId);
        String name = safeFileName(job.path("bookName").asText("")) + ".txt";
        FileInfo file = fileService.saveBytes(name, text, "text/plain; charset=UTF-8");
        NovelCrawl patch = patch(taskId, NovelCrawl.SUCCEEDED, 100,
                job.path("message").asText("抓取完成") + "，已保存为文件「" + name + "」" + exportCopy(saveDir, name, text));
        patch.setFileId(file.getId());
        crawlMapper.updateById(patch);
        releaseQuietly(jobId);
        log.info("抓取完成 crawlId={} fileId={} {} 字节", taskId, file.getId(), text.length);
    }

    // ---------------------------------------------------------------- 整站抓取（逐本，书单来自站点书目）

    private void runSite(Long taskId, Map<String, Object> body, String newOrigin) {
        NovelCrawl task = crawlMapper.selectById(taskId);
        if (task == null || NovelCrawl.CANCELLED.equals(task.getStatus())) {
            return;
        }
        List<NovelCrawlBook> books = bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                .eq(NovelCrawlBook::getCrawlId, taskId).orderByAsc(NovelCrawlBook::getId));
        if (books.isEmpty()) {
            update(taskId, NovelCrawl.FAILED, null, "任务没有书籍明细，请重新「发现书籍」后提交");
            return;
        }
        Map<String, Object> base = singleBookBody(body);
        String saveDir = str(body.get("saveDir"));
        Integer cap = intOrNull(body.get("maxChaptersPerBook"));
        int done = 0, failed = 0, chapters = 0, chapterFailed = 0, words = 0;
        // 继续抓取：已成功的书不再抓，统计直接计入
        for (NovelCrawlBook book : books) {
            if (NovelCrawlBook.SUCCEEDED.equals(book.getStatus())) {
                done++;
                chapters += nz(book.getChapterTotal());
                chapterFailed += nz(book.getChapterFailed());
                words += nz(book.getWordCount());
            }
        }
        // 这次要抓的：开始时没成功的（含上次失败 / 取消的），加上抓的过程中新加入工作区的（QUEUED）
        Set<Long> initial = new java.util.HashSet<>();
        books.stream().filter(bk -> !NovelCrawlBook.SUCCEEDED.equals(bk.getStatus())).forEach(bk -> initial.add(bk.getId()));
        Set<Long> handled = new java.util.HashSet<>();
        int total = books.size();
        update(taskId, NovelCrawl.RUNNING, done * 100 / Math.max(total, 1), done > 0
                ? "整站抓取：从断点继续，已完成 " + done + "/" + total + " 本"
                : "整站抓取：共 " + total + " 本，开始");
        log.info("整站抓取开始 crawlId={} 共 {} 本，已完成 {} 本", taskId, total, done);
        try {
            while (true) {
                NovelCrawlBook book;
                synchronized (workspaceLock) {
                    book = siteCancels.contains(taskId) ? null : nextSiteBook(taskId, initial, handled);
                    total = Math.toIntExact(bookMapper.selectCount(new LambdaQueryWrapper<NovelCrawlBook>()
                            .eq(NovelCrawlBook::getCrawlId, taskId)));
                    if (book == null) {
                        // 收尾在锁里写状态：之后再提交的同首页书会另开任务，不会加进一个已经结束的任务
                        finishSite(taskId, done, total, failed, chapters, chapterFailed, words);
                        return;
                    }
                }
                handled.add(book.getId());
                String label = book.getBookName() == null || book.getBookName().isBlank()
                        ? book.getTocUrl() : book.getBookName();
                patchBook(book.getId(), NovelCrawlBook.RUNNING, 0, "提交中…");
                Map<String, Object> jobBody = new LinkedHashMap<>(base);
                jobBody.put("url", book.getTocUrl());
                jobBody.put("resumeKey", resumeKey(taskId, book.getId()));
                if (newOrigin != null) {
                    jobBody.put("newOrigin", newOrigin);
                }
                jobBody.put("startIndex", 1);
                if (cap != null && cap > 0) {
                    jobBody.put("endIndex", cap);
                }
                String jobId = null;
                try {
                    jobId = aiClient.submitCrawl(jobBody).path("data").path("jobId").asText();
                    patchBookJob(book.getId(), jobId);
                    JsonNode job = pollBook(book.getId(), jobId);
                    String status = job.path("status").asText();
                    chapters += job.path("chapterTotal").asInt();
                    chapterFailed += job.path("chapterFailed").asInt();
                    words += job.path("wordCount").asInt();
                    if ("succeeded".equals(status)) {
                        byte[] text = aiClient.getCrawlText(jobId);
                        String name = safeFileName(book.getBookName()) + ".txt";
                        FileInfo file = fileService.saveBytes(name, text, "text/plain; charset=UTF-8");
                        patchBook(book.getId(), NovelCrawlBook.SUCCEEDED, 100,
                                "已保存为文件「" + name + "」" + exportCopy(saveDir, name, text));
                        patchBookFile(book.getId(), file.getId());
                        log.info("整站抓取《{}》完成，fileId={} {} 字节", label, file.getId(), text.length);
                    } else if ("cancelled".equals(status)) {
                        patchBook(book.getId(), NovelCrawlBook.CANCELLED, null, "已取消（未保存）");
                        siteCancels.add(taskId);
                    } else {
                        failed++;
                        patchBook(book.getId(), NovelCrawlBook.FAILED, null,
                                truncate("抓取失败：" + job.path("error").asText()));
                    }
                    releaseQuietly(jobId);
                } catch (HttpClientErrorException.NotFound e) {
                    failed++;
                    patchBook(book.getId(), NovelCrawlBook.FAILED, null, "AI 服务已重启，任务中断（进度已保存，可继续抓取）");
                } catch (Exception e) {
                    failed++;
                    log.error("整站抓取《{}》失败，crawlId={}", label, taskId, e);
                    patchBook(book.getId(), NovelCrawlBook.FAILED, null, truncate("失败：" + e.getMessage()));
                }
                done++;
                NovelCrawl patch = patch(taskId, NovelCrawl.RUNNING, Math.min(99, done * 100 / Math.max(total, 1)),
                        "第 " + done + "/" + total + " 本：" + label);
                patch.setChapterTotal(chapters);
                patch.setChapterFailed(chapterFailed);
                patch.setWordCount(words);
                crawlMapper.updateById(patch);
            }
        } catch (Exception e) {
            log.error("整站抓取异常 crawlId={}", taskId, e);
            update(taskId, NovelCrawl.FAILED, null, "整站抓取异常：" + e.getMessage());
        } finally {
            // 收尾：取消 / 异常中断时把还没轮到的书一并落状态，避免留下永远「排队中」的明细
            boolean cancelled = siteCancels.contains(taskId);
            bookMapper.update(null, new LambdaUpdateWrapper<NovelCrawlBook>()
                    .eq(NovelCrawlBook::getCrawlId, taskId)
                    .in(NovelCrawlBook::getStatus, NovelCrawlBook.QUEUED, NovelCrawlBook.RUNNING)
                    .set(NovelCrawlBook::getStatus, cancelled ? NovelCrawlBook.CANCELLED : NovelCrawlBook.FAILED)
                    .set(NovelCrawlBook::getMessage, cancelled ? "已取消" : "任务异常中断")
                    .set(NovelCrawlBook::getUpdateTime, LocalDateTime.now()));
            siteCancels.remove(taskId);
        }
    }

    /** 下一本要抓的书：这次开始时没成功的，或抓的过程中新加入的（QUEUED），按加入顺序；抓过的不再抓 */
    private NovelCrawlBook nextSiteBook(Long taskId, Set<Long> initial, Set<Long> handled) {
        return bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                        .eq(NovelCrawlBook::getCrawlId, taskId).ne(NovelCrawlBook::getStatus, NovelCrawlBook.SUCCEEDED)
                        .orderByAsc(NovelCrawlBook::getId))
                .stream()
                .filter(bk -> !handled.contains(bk.getId())
                        && (NovelCrawlBook.QUEUED.equals(bk.getStatus()) || initial.contains(bk.getId())))
                .findFirst().orElse(null);
    }

    /** 整站任务收尾：取消 / 完成 / 全部失败 */
    private void finishSite(Long taskId, int done, int total, int failed, int chapters, int chapterFailed, int words) {
        if (siteCancels.contains(taskId)) {
            update(taskId, NovelCrawl.CANCELLED, null,
                    "已取消：完成 " + done + "/" + total + " 本（已抓到的书保留为文件，进度已保存，可继续抓取）");
            return;
        }
        int ok = countBooks(taskId, NovelCrawlBook.SUCCEEDED);
        String message = "整站抓取完成：成功 " + ok + "/" + total + " 本"
                + (failed > 0 ? "，失败 " + failed + " 本" : "")
                + (words > 0 ? "，共 " + words + " 字" : "");
        NovelCrawl patch = patch(taskId, ok == 0 ? NovelCrawl.FAILED : NovelCrawl.SUCCEEDED, 100, message);
        patch.setChapterTotal(chapters);
        patch.setChapterFailed(chapterFailed);
        patch.setWordCount(words);
        crawlMapper.updateById(patch);
        log.info("整站抓取结束 crawlId={} {}", taskId, message);
    }

    /** 轮询一本书的 Python 任务直到终态，过程中持续更新子行。 */
    private JsonNode pollBook(Long bookId, String jobId) throws InterruptedException {
        int unreachable = 0;
        while (!Thread.currentThread().isInterrupted()) {
            Thread.sleep(POLL_INTERVAL_MS);
            JsonNode job;
            try {
                job = aiClient.getCrawlJob(jobId).path("data");
                unreachable = 0;
            } catch (ResourceAccessException e) {
                if (++unreachable >= MAX_UNREACHABLE) {
                    throw e;
                }
                continue;
            }
            String status = job.path("status").asText();
            NovelCrawlBook patch = new NovelCrawlBook();
            patch.setId(bookId);
            patch.setJobId(jobId);
            patch.setProgress(job.path("progress").asInt());
            patch.setMessage(truncate(job.path("message").asText()));
            patch.setChapterTotal(job.path("chapterTotal").asInt());
            patch.setChapterDone(job.path("chapterDone").asInt());
            patch.setChapterFailed(job.path("chapterFailed").asInt());
            patch.setWordCount(job.path("wordCount").asInt());
            patch.setUpdateTime(LocalDateTime.now());
            bookMapper.updateById(patch);
            if (!"queued".equals(status) && !"running".equals(status)) {
                return job;
            }
        }
        throw new BizException(400, "任务已中断");
    }

    /** 整站模式每本书要传给 Python 的参数（去掉上限 / 书籍清单 / 模式等不属于单本抓取的键） */
    private Map<String, Object> singleBookBody(Map<String, Object> body) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (String key : BOOK_JOB_KEYS) {
            if (body.get(key) != null && !"".equals(body.get(key))) {
                out.put(key, body.get(key));
            }
        }
        return out;
    }

    private List<NovelCrawlBook> runningBooks(Long crawlId) {
        return bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                .eq(NovelCrawlBook::getCrawlId, crawlId).eq(NovelCrawlBook::getStatus, NovelCrawlBook.RUNNING));
    }

    private int countBooks(Long crawlId, String status) {
        return Math.toIntExact(bookMapper.selectCount(new LambdaQueryWrapper<NovelCrawlBook>()
                .eq(NovelCrawlBook::getCrawlId, crawlId).eq(NovelCrawlBook::getStatus, status)));
    }

    /** 提交时把勾选的书籍写入子表（QUEUED），任务进度按这些行的状态汇总 */
    private void insertBooks(Long crawlId, List<Map<String, Object>> books) {
        LocalDateTime now = LocalDateTime.now();
        for (Map<String, Object> book : books) {
            NovelCrawlBook row = new NovelCrawlBook();
            row.setCrawlId(crawlId);
            row.setBookName(str(book.get("bookName")));
            row.setAuthor(str(book.get("author")));
            row.setCategory(str(book.get("category")));
            row.setTocUrl((String) book.get("tocUrl"));
            row.setStatus(NovelCrawlBook.QUEUED);
            row.setProgress(0);
            row.setMessage("排队中");
            row.setCreateTime(now);
            row.setUpdateTime(now);
            bookMapper.insert(row);
        }
    }

    // ---------------------------------------------------------------- 参数校验 / 装饰 / 工具

    /** 转发给 Python 的参数：去掉只在 Java 用的键 */
    private static Map<String, Object> pythonBody(Map<String, Object> body) {
        Map<String, Object> out = new LinkedHashMap<>(body);
        JAVA_ONLY_KEYS.forEach(out::remove);
        return out;
    }

    /**
     * 套用 AI 学到的站点规则：规则选了「learned:&lt;id&gt;」，或选「按域名自动选择」且该域名学过规则时，
     * 把学到的 XPath 合并进 rule（用户在高级选项里填的字段优先），preset 改为 auto。→ 套用的规则或 null
     */
    @SuppressWarnings("unchecked")
    private CrawlSiteRule applyLearnedRule(Map<String, Object> body) {
        String preset = str(body.get("preset"));
        CrawlSiteRule learned;
        if (preset != null && preset.startsWith(LEARNED_PREFIX)) {
            Integer id = intOrNull(preset.substring(LEARNED_PREFIX.length()));
            if (id == null) {
                throw new BizException(400, "规则选择无效：" + preset);
            }
            learned = ruleService.getById(id.longValue());
            if (CrawlSiteRule.FAILED.equals(learned.getStatus())) {
                throw new BizException(400, "这条是解析失败的记录，没有可用的规则");
            }
        } else if (preset == null || preset.isEmpty()) {
            learned = ruleService.findForUrl(str(body.get("url")));
        } else {
            return null;
        }
        if (learned == null) {
            return null;
        }
        Map<String, Object> merged = new LinkedHashMap<>(learned.getRule() == null ? Map.of() : learned.getRule());
        if (body.get("rule") instanceof Map<?, ?> custom) {
            ((Map<String, Object>) custom).forEach((k, v) -> {
                if (v != null && !"".equals(v) && !(v instanceof List<?> l && l.isEmpty())) {
                    merged.put(k, v);
                }
            });
        }
        if (merged.isEmpty()) {
            body.remove("rule");
        } else {
            body.put("rule", merged);
        }
        body.put("preset", "auto");
        body.put("learnedRuleId", learned.getId());
        return learned;
    }

    /** 预览 / 发现结果里标明套用了哪条学到的规则（前端展示「使用规则」） */
    private static JsonNode withLearned(JsonNode data, CrawlSiteRule learned) {
        if (learned != null && data instanceof ObjectNode node) {
            ObjectNode info = node.putObject("learnedRule");
            info.put("id", learned.getId());
            info.put("host", learned.getHost());
            info.put("siteName", learned.getSiteName());
        }
        return data;
    }

    /** 另存目录（可空）：必须是绝对路径、不在 Windows 系统目录下；不存在则创建，并确认可写。规范化后写回 body。 */
    private static void checkSaveDir(Map<String, Object> body) {
        String raw = str(body.get("saveDir"));
        if (raw == null || raw.isEmpty()) {
            body.remove("saveDir");
            return;
        }
        Path dir;
        try {
            dir = Paths.get(raw);
        } catch (InvalidPathException e) {
            throw new BizException(400, "保存目录不合法：" + raw);
        }
        if (!dir.isAbsolute()) {
            throw new BizException(400, "保存目录请填写完整路径，如 D:\\小说");
        }
        dir = dir.toAbsolutePath().normalize();
        String sysRoot = System.getenv("SystemRoot");
        if (sysRoot != null && dir.toString().toLowerCase().startsWith(sysRoot.toLowerCase())) {
            throw new BizException(400, "不能保存到系统目录：" + dir);
        }
        try {
            Files.createDirectories(dir);
        } catch (IOException e) {
            throw new BizException(400, "无法创建保存目录：" + dir + "（" + e.getMessage() + "）");
        }
        if (!Files.isWritable(dir)) {
            throw new BizException(400, "保存目录不可写：" + dir);
        }
        body.put("saveDir", dir.toString());
    }

    /**
     * 把 txt 另存一份到用户选的目录（文件管理里那份照常保留，供小说提取使用）。
     * 重名时加「 (2)」等后缀，先写 .part 再改名。失败不影响任务成功，只在说明里提示。→ 附加到说明的文字
     */
    private static String exportCopy(String saveDir, String name, byte[] text) {
        if (saveDir == null || saveDir.isEmpty()) {
            return "";
        }
        try {
            Path dir = Paths.get(saveDir);
            Files.createDirectories(dir);
            String stem = name.endsWith(".txt") ? name.substring(0, name.length() - 4) : name;
            Path target = dir.resolve(name);
            for (int i = 2; Files.exists(target); i++) {
                target = dir.resolve(stem + " (" + i + ").txt");
            }
            Path tmp = dir.resolve(target.getFileName() + ".part");
            Files.write(tmp, text);
            try {
                Files.move(tmp, target, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException e) {
                Files.move(tmp, target);
            }
            return "，另存到 " + target;
        } catch (IOException | InvalidPathException e) {
            log.warn("另存抓取结果失败，目录 {}：{}", saveDir, e.getMessage());
            return "；另存到 " + saveDir + " 失败：" + e.getMessage();
        }
    }

    /** 只保留白名单参数，并校验地址（详细校验由 Python 完成，其错误信息会原样返回） */
    private Map<String, Object> normalize(Map<String, Object> options) {
        if (options == null) {
            throw new BizException(400, "缺少抓取参数");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        options.forEach((k, v) -> {
            if (OPTION_KEYS.contains(k) && v != null && !"".equals(v)) {
                body.put(k, v);
            }
        });
        Object url = body.get("url");
        if (!(url instanceof String s) || !(s.trim().startsWith("http://") || s.trim().startsWith("https://"))) {
            throw new BizException(400, "请输入 http:// 或 https:// 开头的地址");
        }
        body.put("url", ((String) url).trim());
        return body;
    }

    /** 前端勾选的书籍：[{bookName, author, category, tocUrl}]，没有可用地址的条目丢弃 */
    private List<Map<String, Object>> booksOf(Map<String, Object> body) {
        Object raw = body.get("books");
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object item : list) {
            if (!(item instanceof Map<?, ?> map)) {
                continue;
            }
            Object toc = map.get("tocUrl");
            String url = toc instanceof String s ? s.trim() : "";
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                continue;
            }
            Map<String, Object> book = new LinkedHashMap<>();
            book.put("tocUrl", url);
            book.put("bookName", str(map.get("bookName")));
            book.put("author", str(map.get("author")));
            book.put("category", str(map.get("category")));
            out.add(book);
        }
        return out;
    }

    private boolean isSite(Map<String, Object> body) {
        return NovelCrawl.MODE_SITE.equals(str(body.get("mode")));
    }

    /** 采集模式记在 options.mode，不额外占表列 */
    private String modeOf(NovelCrawl task) {
        String mode = parseOptions(task.getOptions()).path("mode").asText("");
        return NovelCrawl.MODE_SITE.equals(mode) ? NovelCrawl.MODE_SITE : NovelCrawl.MODE_BOOK;
    }

    private JsonNode parseOptions(String json) {
        if (json == null || json.isBlank()) {
            return objectMapper.createObjectNode();
        }
        try {
            return objectMapper.readTree(json);
        } catch (JsonProcessingException e) {
            return objectMapper.createObjectNode();
        }
    }

    /** 补上不入库的展示字段：mode + 整站书籍统计（一次查询汇总所有整站任务） */
    private List<NovelCrawl> decorate(List<NovelCrawl> tasks) {
        List<Long> siteIds = new ArrayList<>();
        for (NovelCrawl task : tasks) {
            String mode = modeOf(task);
            task.setMode(mode);
            task.setBookTotal(0);
            task.setBookDone(0);
            task.setBookFailed(0);
            if (NovelCrawl.MODE_SITE.equals(mode)) {
                siteIds.add(task.getId());
            }
        }
        if (siteIds.isEmpty()) {
            return tasks;
        }
        List<NovelCrawlBook> rows = bookMapper.selectList(new LambdaQueryWrapper<NovelCrawlBook>()
                .select(NovelCrawlBook::getCrawlId, NovelCrawlBook::getStatus)
                .in(NovelCrawlBook::getCrawlId, siteIds));
        Map<Long, int[]> stats = new HashMap<>();
        for (NovelCrawlBook row : rows) {
            int[] s = stats.computeIfAbsent(row.getCrawlId(), k -> new int[3]);
            s[0]++;
            if (NovelCrawlBook.SUCCEEDED.equals(row.getStatus())) {
                s[1]++;
            } else if (NovelCrawlBook.FAILED.equals(row.getStatus())) {
                s[2]++;
            }
        }
        for (NovelCrawl task : tasks) {
            int[] s = stats.get(task.getId());
            if (s != null) {
                task.setBookTotal(s[0]);
                task.setBookDone(s[1]);
                task.setBookFailed(s[2]);
            }
        }
        return tasks;
    }

    private NovelCrawl decorate(NovelCrawl task) {
        decorate(List.of(task));
        return task;
    }

    /** 同步调用 Python：不可达 → 503；Python 的 4xx 业务错误（如「没有识别到章节链接」）→ 400 + 原因 */
    private JsonNode callPython(Supplier<JsonNode> call) {
        try {
            JsonNode res = call.get();
            return res == null ? null : res.path("data");
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            int status = e.getStatusCode().value();
            throw new BizException(status == 404 ? 404 : 400, pythonMessage(e));
        }
    }

    /** 抓取接口不涉及 API Key，可以解析 Python 的错误体：{message} 或 FastAPI 校验错误 {detail: [{loc, msg}]} */
    private String pythonMessage(RestClientResponseException e) {
        try {
            JsonNode body = objectMapper.readTree(e.getResponseBodyAsString(StandardCharsets.UTF_8));
            if (body.hasNonNull("message")) {
                return body.get("message").asText();
            }
            JsonNode detail = body.path("detail").path(0);
            if (!detail.isMissingNode()) {
                JsonNode loc = detail.path("loc");
                return "参数不合法：" + loc.path(loc.size() - 1).asText() + " " + detail.path("msg").asText();
            }
        } catch (Exception ignored) {
            // 非 JSON 响应
        }
        return "HTTP " + e.getStatusCode().value();
    }

    private static String safeFileName(String bookName) {
        String name = bookName == null ? "" : bookName.replaceAll("[\\\\/:*?\"<>|\\r\\n\\t]", "").trim();
        if (name.isEmpty()) {
            name = "抓取小说";
        }
        return name.length() > 80 ? name.substring(0, 80) : name;
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new BizException(400, "抓取参数无法序列化");
        }
    }

    private static int nz(Integer value) {
        return value == null ? 0 : value;
    }

    /** 新站点地址 → scheme://host[:port]（小写 scheme），空 → null */
    private static String normalizeOrigin(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String origin = originOf(value.trim());
        if (origin == null) {
            throw new BizException(400, "新站点地址请填 http(s)://域名[:端口]，如 https://www.example.net");
        }
        return origin;
    }

    private static String originOf(String url) {
        try {
            java.net.URI uri = new java.net.URI(url);
            String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
            if (!("http".equals(scheme) || "https".equals(scheme)) || uri.getRawAuthority() == null) {
                return null;
            }
            return scheme + "://" + uri.getRawAuthority();
        } catch (java.net.URISyntaxException e) {
            return null;
        }
    }

    /** url 在 oldOrigin 下时换成 newOrigin（路径、参数不变），否则原样返回 */
    private static String replaceOrigin(String url, String oldOrigin, String newOrigin) {
        if (url == null || oldOrigin == null || !oldOrigin.equalsIgnoreCase(originOf(url))) {
            return url;
        }
        return newOrigin + url.substring(oldOrigin.length());
    }

    private static Integer intOrNull(Object value) {
        if (value instanceof Number n) {
            return n.intValue();
        }
        if (value instanceof String s && s.matches("\\d+")) {
            return Integer.parseInt(s);
        }
        return null;
    }

    private static String str(Object value) {
        return value == null ? null : String.valueOf(value).trim();
    }

    private static String truncate(String message) {
        return message != null && message.length() > 1000 ? message.substring(0, 1000) : message;
    }

    private void releaseQuietly(String jobId) {
        try {
            aiClient.releaseCrawl(jobId);
        } catch (Exception e) {
            log.warn("通知 AI 服务释放抓取全文失败，jobId={}：{}", jobId, e.getMessage());
        }
    }

    private static NovelCrawl patch(Long taskId, String status, Integer progress, String message) {
        NovelCrawl patch = new NovelCrawl();
        patch.setId(taskId);
        patch.setStatus(status);
        patch.setProgress(progress);
        patch.setMessage(truncate(message));
        patch.setUpdateTime(LocalDateTime.now());
        return patch;
    }

    private void update(Long taskId, String status, Integer progress, String message) {
        crawlMapper.updateById(patch(taskId, status, progress, message));
    }

    private void patchBook(Long id, String status, Integer progress, String message) {
        NovelCrawlBook patch = new NovelCrawlBook();
        patch.setId(id);
        patch.setStatus(status);
        patch.setProgress(progress);
        patch.setMessage(truncate(message));
        patch.setUpdateTime(LocalDateTime.now());
        bookMapper.updateById(patch);
    }

    private void patchBookJob(Long id, String jobId) {
        NovelCrawlBook patch = new NovelCrawlBook();
        patch.setId(id);
        patch.setJobId(jobId);
        patch.setStatus(NovelCrawlBook.RUNNING);
        patch.setMessage("已提交 AI 服务");
        patch.setUpdateTime(LocalDateTime.now());
        bookMapper.updateById(patch);
    }

    private void patchBookFile(Long id, Long fileId) {
        NovelCrawlBook patch = new NovelCrawlBook();
        patch.setId(id);
        patch.setFileId(fileId);
        patch.setUpdateTime(LocalDateTime.now());
        bookMapper.updateById(patch);
    }
}
