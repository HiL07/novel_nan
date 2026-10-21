package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.CrawlSiteRule;
import com.example.file.entity.NovelCrawl;
import com.example.file.entity.NovelCrawlBook;
import com.example.file.service.CrawlRuleService;
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

    public NovelCrawlController(NovelCrawlService crawlService, CrawlRuleService ruleService) {
        this.crawlService = crawlService;
        this.ruleService = ruleService;
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

    /** POST /api/novel/crawl/discover：整站发现（首页 → 分类 → 列表翻页 → 书籍 → 目录，同步） */
    @PostMapping("/discover")
    public ResponseEntity<Result<JsonNode>> discover(@RequestBody Map<String, Object> options) {
        return ResultResponses.handle(() -> crawlService.discover(options), log, "整站发现失败");
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

    /** GET /api/novel/crawl/list，按创建时间倒序 */
    @GetMapping("/list")
    public ResponseEntity<Result<List<NovelCrawl>>> list() {
        return ResultResponses.handle(crawlService::list, log, "查询抓取任务失败");
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

    /** GET /api/novel/crawl/rules：学到的站点规则（最近更新在前） */
    @GetMapping("/rules")
    public ResponseEntity<Result<List<CrawlSiteRule>>> rules() {
        return ResultResponses.handle(ruleService::list, log, "查询站点规则失败");
    }

    /** POST /api/novel/crawl/rules/{id}/delete */
    @PostMapping("/rules/{id}/delete")
    public ResponseEntity<Result<Void>> deleteRule(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            ruleService.delete(id);
            return null;
        }, log, "删除站点规则失败，id=" + id);
    }
}
