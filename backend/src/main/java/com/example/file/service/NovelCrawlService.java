package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.FileInfo;
import com.example.file.entity.NovelCrawl;
import com.example.file.entity.NovelCrawlBook;
import com.example.file.mapper.NovelCrawlBookMapper;
import com.example.file.mapper.NovelCrawlMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Supplier;

/**
 * 网络小说抓取，两种采集模式：
 * <ul>
 *   <li>单本（mode=book）：一个目录页 → 一个 txt；</li>
 *   <li>整站（mode=site）：复刻 copybook 的跳转链——站点首页 → 分类 → 分类列表翻页 → 书籍详情 → 目录，
 *       先由 Python 的 /api/crawl/discover 有界采样出书籍清单，再<b>逐本</b>复用单本抓取流程，
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
            "categories", "verify", "books");
    /** 整站模式下每本书要保留的参数（其余上限参数只给 discover 用） */
    private static final List<String> BOOK_JOB_KEYS = List.of("preset", "rule", "delayMs", "respectRobots");

    private final NovelCrawlMapper crawlMapper;
    private final NovelCrawlBookMapper bookMapper;
    private final FileService fileService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "novel-crawl");
        t.setDaemon(true);
        return t;
    });
    /** 已被请求取消的整站任务（跨线程可见，抓完当前这本着循环检查） */
    private final Set<Long> siteCancels = ConcurrentHashMap.newKeySet();

    public NovelCrawlService(NovelCrawlMapper crawlMapper, NovelCrawlBookMapper bookMapper, FileService fileService,
                             AiServiceClient aiClient, ObjectMapper objectMapper) {
        this.crawlMapper = crawlMapper;
        this.bookMapper = bookMapper;
        this.fileService = fileService;
        this.aiClient = aiClient;
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
                .set(NovelCrawl::getMessage, "服务重启，任务中断，请重新抓取")
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

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    // ---------------------------------------------------------------- 规则 / 预览 / 发现

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
        return callPython(() -> aiClient.crawlPreview(body));
    }

    /**
     * 整站发现（copybook 式）：首页 → 分类 → 分类列表翻页 → 书籍详情 → 目录，
     * → {siteName, categoriesAll[], categories[], books[{bookName, author, category, tocUrl, sourceUrl, chapterCount, error}], truncated}
     */
    public JsonNode discover(Map<String, Object> options) {
        Map<String, Object> body = normalize(options);
        body.remove("startIndex");
        body.remove("endIndex");
        body.remove("books");
        body.remove("mode");
        return callPython(() -> aiClient.crawlDiscover(body));
    }

    // ---------------------------------------------------------------- 提交 / 查询 / 取消

    /** 提交抓取任务（按 options.mode 分派单本 / 整站），立即返回任务记录（QUEUED）。 */
    public NovelCrawl submit(Map<String, Object> options) {
        Map<String, Object> body = normalize(options);
        boolean site = isSite(body);
        List<Map<String, Object>> books = site ? booksOf(body) : List.of();
        if (site && books.isEmpty()) {
            throw new BizException(400, "整站抓取需要先「发现书籍」并勾选要抓的书");
        }
        NovelCrawl task = new NovelCrawl();
        task.setUrl((String) body.get("url"));
        task.setOptions(toJson(body));
        task.setStatus(NovelCrawl.QUEUED);
        task.setProgress(0);
        task.setMessage("排队中");
        task.setCreateTime(LocalDateTime.now());
        task.setUpdateTime(task.getCreateTime());
        crawlMapper.insert(task);
        if (site) {
            insertBooks(task.getId(), books);
        }
        Long taskId = task.getId();
        executor.submit(() -> {
            if (site) {
                runSite(taskId, body);
            } else {
                run(taskId, body);
            }
        });
        return decorate(task);
    }

    /** 整站抓取：强制 mode=site（不改调用方传入的 Map） */
    public NovelCrawl submitSite(Map<String, Object> options) {
        Map<String, Object> body = options == null ? new LinkedHashMap<>() : new LinkedHashMap<>(options);
        body.put("mode", NovelCrawl.MODE_SITE);
        return submit(body);
    }

    /** 用原参数重新抓取（新建任务）：整站任务按已存的书籍清单重跑，不重新发现（要换清单请重新「发现书籍」） */
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

    public List<NovelCrawl> list() {
        return decorate(crawlMapper.selectList(new LambdaQueryWrapper<NovelCrawl>()
                .orderByDesc(NovelCrawl::getCreateTime)));
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

    private void run(Long taskId, Map<String, Object> body) {
        if (NovelCrawl.CANCELLED.equals(crawlMapper.selectById(taskId).getStatus())) {
            return;
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
            poll(taskId, jobId);
        } catch (ResourceAccessException e) {
            log.error("AI 服务不可达，crawlId={}", taskId, e);
            update(taskId, NovelCrawl.FAILED, null, "AI 服务不可达，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            log.error("AI 服务拒绝抓取任务，crawlId={}，HTTP {}", taskId, e.getStatusCode().value());
            update(taskId, NovelCrawl.FAILED, null, "AI 服务拒绝任务：" + pythonMessage(e));
        } catch (Exception e) {
            log.error("小说抓取失败，crawlId={}", taskId, e);
            update(taskId, NovelCrawl.FAILED, null, "抓取失败：" + e.getMessage());
        }
    }

    private void poll(Long taskId, String jobId) throws Exception {
        int unreachable = 0;
        while (!Thread.currentThread().isInterrupted()) {
            Thread.sleep(POLL_INTERVAL_MS);
            JsonNode job;
            try {
                job = aiClient.getCrawlJob(jobId).path("data");
                unreachable = 0;
            } catch (HttpClientErrorException.NotFound e) {
                update(taskId, NovelCrawl.FAILED, null, "AI 服务已重启，任务丢失，请重新抓取");
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
                    finishSucceeded(taskId, jobId, job);
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

    /** 成功收尾：取全文 → 存为 txt（落盘 + file 表）→ 记 fileId → 通知 Python 释放内存。 */
    private void finishSucceeded(Long taskId, String jobId, JsonNode job) {
        byte[] text = aiClient.getCrawlText(jobId);
        String name = safeFileName(job.path("bookName").asText("")) + ".txt";
        FileInfo file = fileService.saveBytes(name, text, "text/plain; charset=UTF-8");
        NovelCrawl patch = patch(taskId, NovelCrawl.SUCCEEDED, 100,
                job.path("message").asText("抓取完成") + "，已保存为文件「" + name + "」");
        patch.setFileId(file.getId());
        crawlMapper.updateById(patch);
        releaseQuietly(jobId);
        log.info("抓取完成 crawlId={} fileId={} {} 字节", taskId, file.getId(), text.length);
    }

    // ---------------------------------------------------------------- 整站抓取（copybook 式）

    private void runSite(Long taskId, Map<String, Object> body) {
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
        Integer cap = intOrNull(body.get("maxChaptersPerBook"));
        int total = books.size();
        int done = 0, failed = 0, chapters = 0, chapterFailed = 0, words = 0;
        update(taskId, NovelCrawl.RUNNING, 0, "整站抓取：共 " + total + " 本，开始");
        log.info("整站抓取开始 crawlId={} 共 {} 本", taskId, total);
        try {
            for (NovelCrawlBook book : books) {
                if (siteCancels.contains(taskId)) {
                    patchBook(book.getId(), NovelCrawlBook.CANCELLED, null, "已取消");
                    break;
                }
                String label = book.getBookName() == null || book.getBookName().isBlank()
                        ? book.getTocUrl() : book.getBookName();
                patchBook(book.getId(), NovelCrawlBook.RUNNING, 0, "提交中…");
                Map<String, Object> jobBody = new LinkedHashMap<>(base);
                jobBody.put("url", book.getTocUrl());
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
                        patchBook(book.getId(), NovelCrawlBook.SUCCEEDED, 100, "已保存为文件「" + name + "」");
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
                    patchBook(book.getId(), NovelCrawlBook.FAILED, null, "AI 服务已重启，任务丢失");
                } catch (Exception e) {
                    failed++;
                    log.error("整站抓取《{}》失败，crawlId={}", label, taskId, e);
                    patchBook(book.getId(), NovelCrawlBook.FAILED, null, truncate("失败：" + e.getMessage()));
                }
                done++;
                NovelCrawl patch = patch(taskId, NovelCrawl.RUNNING, Math.min(99, done * 100 / total),
                        "第 " + done + "/" + total + " 本：" + label);
                patch.setChapterTotal(chapters);
                patch.setChapterFailed(chapterFailed);
                patch.setWordCount(words);
                crawlMapper.updateById(patch);
                if (siteCancels.contains(taskId)) {
                    break;
                }
            }

            if (siteCancels.contains(taskId)) {
                update(taskId, NovelCrawl.CANCELLED, null,
                        "已取消：完成 " + done + "/" + total + " 本（已抓到的书保留为文件）");
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
        } catch (Exception e) {
            log.error("整站抓取异常 crawlId={}", taskId, e);
            update(taskId, NovelCrawl.FAILED, null, "整站抓取异常：" + e.getMessage());
        } finally {
            siteCancels.remove(taskId);
        }
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

    /** 整站模式每本书要传给 Python 的参数（去掉上限 / 书籍清单 / 模式等只在前端和 discover 用的键） */
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
