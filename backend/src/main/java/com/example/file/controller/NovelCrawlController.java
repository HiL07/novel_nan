package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.CrawlSavedUrl;
import com.example.file.entity.CrawlSite;
import com.example.file.entity.CrawlSiteRule;
import com.example.file.entity.NovelCrawl;
import com.example.file.entity.NovelCrawlBook;
import com.example.file.service.CrawlRuleService;
import com.example.file.service.CrawlSavedUrlService;
import com.example.file.service.CrawlSiteService;
import com.example.file.service.NovelCrawlService;
import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 网络小说抓取接口：规则预设 / 目录预览 / 整站发现 / 提交任务 / 任务列表 / 详情 / 书籍明细 / 取消 / 断点续抓 / 重新抓取。
 *
 * 两种采集模式：
 * - 单本（mode=book，默认）：参数 {url（目录页）, preset?, rule?, delayMs?, respectRobots?, startIndex?, endIndex?}；
 * - 整站（mode=site，copybook 式）：参数 {url（站点首页 / 分类页）, maxCategories?, maxListPages?, maxBooks?,
 *   categories?[], verify?, maxChaptersPerBook?, books:[{tocUrl, bookName?, author?, category?}]}，
 *   先调 /discover 拿到书籍清单，再把勾选的书提交给 /site/submit，Java 逐本抓取、每本一个 txt。
 * 参数统一转发给 Python /api/crawl/**。
 */
@RestController
@RequestMapping("/api/novel/crawl")
public class NovelCrawlController {

    private static final Logger log = LoggerFactory.getLogger(NovelCrawlController.class);

    private final NovelCrawlService crawlService;
    private final CrawlRuleService ruleService;
    private final CrawlSavedUrlService savedUrlService;
    private final CrawlSiteService siteService;

    public NovelCrawlController(NovelCrawlService crawlService, CrawlRuleService ruleService,
                                CrawlSavedUrlService savedUrlService, CrawlSiteService siteService) {
        this.crawlService = crawlService;
        this.ruleService = ruleService;
        this.savedUrlService = savedUrlService;
        this.siteService = siteService;
    }

    /** GET /api/novel/crawl/presets */
    @GetMapping("/presets")
    public ResponseEntity<Result<JsonNode>> presets() {
        return ResultResponses.handle(crawlService::presets, log, "查询抓取规则预设失败");
    }

    /** POST /api/novel/crawl/preview：单本，解析目录 + 试抓第一章（同步） */
    @PostMapping("/preview")
    public ResponseEntity<Result<JsonNode>> preview(@RequestBody Map<String, Object> options) {
        return ResultResponses.handle(() -> crawlService.preview(options), log, "抓取预览失败");
    }

    /** POST /api/novel/crawl/submit：提交抓取任务（异步，按 options.mode 分派单本 / 整站），立即返回任务 */
    @PostMapping("/submit")
    public ResponseEntity<Result<NovelCrawl>> submit(@RequestBody Map<String, Object> options) {
        return ResultResponses.handle(() -> crawlService.submit(options), log, "提交抓取任务失败");
    }

    /** POST /api/novel/crawl/site/submit：提交整站抓取任务（异步，逐本抓取） */
    @PostMapping("/site/submit")
    public ResponseEntity<Result<NovelCrawl>> submitSite(@RequestBody Map<String, Object> options) {
        return ResultResponses.handle(() -> crawlService.submitSite(options), log, "提交整站抓取任务失败");
    }

    /** GET /api/novel/crawl/list?page=&size=&status=（空 = 全部，ACTIVE = 排队 + 抓取中）&mode=（book 整本 / site 整站）→ {records, total, page, size, active} */
    @GetMapping("/list")
    public ResponseEntity<Result<Map<String, Object>>> list(@RequestParam(defaultValue = "1") int page,
                                                            @RequestParam(defaultValue = "20") int size,
                                                            @RequestParam(required = false) String status,
                                                            @RequestParam(required = false) String mode) {
        return ResultResponses.handle(() -> crawlService.page(page, size, status, mode), log, "查询抓取任务失败");
    }

    // ---------------------------------------------------------------- 整站工作区（一个首页一个工作区）

    /** GET /api/novel/crawl/workspaces：抓取进度，按首页归组的工作区（单本 + 整站），进行中的在前 */
    @GetMapping("/workspaces")
    public ResponseEntity<Result<List<Map<String, Object>>>> workspaces() {
        return ResultResponses.handle(crawlService::workspaces, log, "查询整站工作区失败");
    }

    /** GET /api/novel/crawl/workspaces/books?home=&status=&keyword=&source=book|site&page=&size=：工作区里每本小说的进度（抓取中的置顶） */
    @GetMapping("/workspaces/books")
    public ResponseEntity<Result<Map<String, Object>>> workspaceBooks(@RequestParam String home,
                                                                      @RequestParam(required = false) String source,
                                                                      @RequestParam(required = false) String status,
                                                                      @RequestParam(required = false) String keyword,
                                                                      @RequestParam(defaultValue = "1") int page,
                                                                      @RequestParam(defaultValue = "20") int size) {
        return ResultResponses.handle(() -> crawlService.workspaceBooks(home, status, keyword, source, page, size), log, "查询工作区书籍失败");
    }

    /** POST /api/novel/crawl/workspaces/cancel {home}：取消工作区里正在进行的抓取 */
    @PostMapping("/workspaces/cancel")
    public ResponseEntity<Result<Map<String, Object>>> workspaceCancel(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> crawlService.workspaceCancel(homeParam(body)), log, "取消工作区抓取失败");
    }

    /** POST /api/novel/crawl/workspaces/resume {home}：继续没抓完的书（断点续抓） */
    @PostMapping("/workspaces/resume")
    public ResponseEntity<Result<Map<String, Object>>> workspaceResume(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> crawlService.workspaceResume(homeParam(body)), log, "继续工作区抓取失败");
    }

    /** POST /api/novel/crawl/workspaces/delete {home}：删除工作区（任务 / 书籍明细 / 断点；txt 保留） */
    @PostMapping("/workspaces/delete")
    public ResponseEntity<Result<Map<String, Object>>> workspaceDelete(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> crawlService.workspaceDelete(homeParam(body)), log, "删除工作区失败");
    }

    private static String homeParam(Map<String, Object> body) {
        Object home = body == null ? null : body.get("home");
        return home == null ? null : String.valueOf(home);
    }

    /** POST /api/novel/crawl/delete {ids:[...]}：删除已结束的任务（含书籍明细与断点；进行中的跳过，txt 不删）→ {deleted, skipped, checkpointErrors} */
    @PostMapping("/delete")
    public ResponseEntity<Result<Map<String, Object>>> delete(@RequestBody Map<String, Object> body) {
        Object raw = body == null ? null : body.get("ids");
        List<Long> ids = raw instanceof List<?> l
                ? l.stream().filter(Number.class::isInstance).map(n -> ((Number) n).longValue()).toList() : List.of();
        return ResultResponses.handle(() -> crawlService.delete(ids), log, "删除抓取任务失败");
    }

    /** GET /api/novel/crawl/{id} */
    @GetMapping("/{id}")
    public ResponseEntity<Result<NovelCrawl>> detail(@PathVariable Long id) {
        return ResultResponses.handle(() -> crawlService.getById(id), log, "查询抓取任务失败，id=" + id);
    }

    /** GET /api/novel/crawl/{id}/books：整站任务的书籍明细（单本任务返回空列表） */
    @GetMapping("/{id}/books")
    public ResponseEntity<Result<List<NovelCrawlBook>>> books(@PathVariable Long id) {
        return ResultResponses.handle(() -> crawlService.listBooks(id), log, "查询抓取书籍明细失败，id=" + id);
    }

    /** POST /api/novel/crawl/{id}/cancel */
    @PostMapping("/{id}/cancel")
    public ResponseEntity<Result<NovelCrawl>> cancel(@PathVariable Long id) {
        return ResultResponses.handle(() -> crawlService.cancel(id), log, "取消抓取任务失败，id=" + id);
    }

    /** POST /api/novel/crawl/{id}/resume {newOrigin?}：从断点继续（同一任务；整站跳过已完成的书） */
    @PostMapping("/{id}/resume")
    public ResponseEntity<Result<NovelCrawl>> resume(@PathVariable Long id,
                                                     @RequestBody(required = false) Map<String, Object> body) {
        Object origin = body == null ? null : body.get("newOrigin");
        return ResultResponses.handle(() -> crawlService.resume(id, origin == null ? null : String.valueOf(origin)),
                log, "继续抓取失败，id=" + id);
    }

    /** GET /api/novel/crawl/{id}/checkpoint：断点概况 {chapterSaved, chapterTotal, booksWithCheckpoint, booksPending, url} */
    @GetMapping("/{id}/checkpoint")
    public ResponseEntity<Result<Map<String, Object>>> checkpoint(@PathVariable Long id) {
        return ResultResponses.handle(() -> crawlService.checkpoint(id), log, "查询抓取断点失败，id=" + id);
    }

    /** POST /api/novel/crawl/{id}/retry：按原参数新建任务 */
    @PostMapping("/{id}/retry")
    public ResponseEntity<Result<NovelCrawl>> retry(@PathVariable Long id) {
        return ResultResponses.handle(() -> crawlService.retry(id), log, "重新抓取失败，id=" + id);
    }

    // ---------------------------------------------------------------- AI 解析地址 / 学到的站点规则

    /** POST /api/novel/crawl/ai/analyze {url, maxAttempts?, delayMs?, respectRobots?, hint?, useKnown?}：后台任务，立即返回 */
    @PostMapping("/ai/analyze")
    public ResponseEntity<Result<JsonNode>> aiAnalyze(@RequestBody Map<String, Object> options) {
        return ResultResponses.handle(() -> ruleService.analyze(options), log, "提交 AI 解析地址失败");
    }

    /** GET /api/novel/crawl/ai/jobs/{jobId}：状态、每次尝试、成功结果（savedRuleId = 已存入的规则） */
    @GetMapping("/ai/jobs/{jobId}")
    public ResponseEntity<Result<JsonNode>> aiJob(@PathVariable String jobId) {
        return ResultResponses.handle(() -> ruleService.getJob(jobId), log, "查询 AI 解析任务失败");
    }

    /** POST /api/novel/crawl/ai/jobs/{jobId}/cancel */
    @PostMapping("/ai/jobs/{jobId}/cancel")
    public ResponseEntity<Result<JsonNode>> aiCancel(@PathVariable String jobId) {
        return ResultResponses.handle(() -> ruleService.cancel(jobId), log, "取消 AI 解析任务失败");
    }

    /** GET /api/novel/crawl/rules?status=PENDING|CONFIRMED（空 = 全部）：AI 解析出的站点规则，待确认在前 */
    @GetMapping("/rules")
    public ResponseEntity<Result<List<CrawlSiteRule>>> rules(@RequestParam(required = false) String status) {
        return ResultResponses.handle(() -> ruleService.list(status), log, "查询站点规则失败");
    }

    /** POST /api/novel/crawl/rules/{id}/confirm：确认待确认的规则（替换该域名原来已确认的） */
    @PostMapping("/rules/{id}/confirm")
    public ResponseEntity<Result<CrawlSiteRule>> confirmRule(@PathVariable Long id) {
        return ResultResponses.handle(() -> ruleService.confirm(id), log, "确认站点规则失败，id=" + id);
    }

    /** POST /api/novel/crawl/rules/{id}/reject：不确认（丢弃待确认的规则） */
    @PostMapping("/rules/{id}/reject")
    public ResponseEntity<Result<Void>> rejectRule(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            ruleService.reject(id);
            return null;
        }, log, "丢弃站点规则失败，id=" + id);
    }

    /** POST /api/novel/crawl/rules/{id}/delete */
    @PostMapping("/rules/{id}/delete")
    public ResponseEntity<Result<Void>> deleteRule(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            ruleService.delete(id);
            return null;
        }, log, "删除站点规则失败，id=" + id);
    }

    // ---------------------------------------------------------------- 常用地址（用户收藏的可抓取网址）

    /** GET /api/novel/crawl/saved-urls：最近用过的在前 */
    @GetMapping("/saved-urls")
    public ResponseEntity<Result<List<CrawlSavedUrl>>> savedUrls() {
        return ResultResponses.handle(savedUrlService::list, log, "查询常用地址失败");
    }

    /** POST /api/novel/crawl/saved-urls/save {id?, url, name?, mode?: book|site, note?}：同地址已存在则更新 */
    @PostMapping("/saved-urls/save")
    public ResponseEntity<Result<CrawlSavedUrl>> saveUrl(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> savedUrlService.save(body), log, "保存常用地址失败");
    }

    /** POST /api/novel/crawl/saved-urls/{id}/use：选用计数（排序用） */
    @PostMapping("/saved-urls/{id}/use")
    public ResponseEntity<Result<CrawlSavedUrl>> useUrl(@PathVariable Long id) {
        return ResultResponses.handle(() -> savedUrlService.use(id), log, "更新常用地址失败，id=" + id);
    }

    /** POST /api/novel/crawl/saved-urls/{id}/delete */
    @PostMapping("/saved-urls/{id}/delete")
    public ResponseEntity<Result<Void>> deleteUrl(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            savedUrlService.delete(id);
            return null;
        }, log, "删除常用地址失败，id=" + id);
    }

    // ---------------------------------------------------------------- 小说网站爬取（用户指定的网站，按首页归一）

    /** GET /api/novel/crawl/sites：全部网站（附 AI 解析规则状态与书目概况），先加的在前 */
    @GetMapping("/sites")
    public ResponseEntity<Result<List<CrawlSite>>> sites() {
        return ResultResponses.handle(siteService::list, log, "查询小说网站失败");
    }

    /** POST /api/novel/crawl/sites/save {id?, url, name?, note?}：url 为站内任意地址，存为首页；同一首页已存在则更新 */
    @PostMapping("/sites/save")
    public ResponseEntity<Result<CrawlSite>> saveSite(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> siteService.save(body), log, "保存小说网站失败");
    }

    /** POST /api/novel/crawl/sites/{id}/delete（只删这条网站记录，规则 / 书目不动） */
    @PostMapping("/sites/{id}/delete")
    public ResponseEntity<Result<Void>> deleteSite(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            siteService.delete(id);
            return null;
        }, log, "删除小说网站失败，id=" + id);
    }
}
