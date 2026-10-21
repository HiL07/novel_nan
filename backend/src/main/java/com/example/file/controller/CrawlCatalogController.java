package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.CrawlSiteCatalog;
import com.example.file.service.CrawlCatalogService;
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

import java.util.Arrays;
import java.util.List;
import java.util.Map;

/**
 * 全自动爬虫的站点书目：按 AI 学到的规律测试 / 扩充书目、决定是否使用、筛选（书名 / 作者模糊、类型、具体情节）、
 * 查看目录、AI 补标签。选中的书由前端提交给 /api/novel/crawl/site/submit 逐本抓取。
 */
@RestController
@RequestMapping("/api/novel/crawl/catalogs")
public class CrawlCatalogController {

    private static final Logger log = LoggerFactory.getLogger(CrawlCatalogController.class);

    private final CrawlCatalogService catalogService;

    public CrawlCatalogController(CrawlCatalogService catalogService) {
        this.catalogService = catalogService;
    }

    /** GET /api/novel/crawl/catalogs：全部站点书目，最近更新在前 */
    @GetMapping
    public ResponseEntity<Result<List<CrawlSiteCatalog>>> list() {
        return ResultResponses.handle(catalogService::list, log, "查询站点书目失败");
    }

    /** POST /api/novel/crawl/catalogs/start {ruleId, phase: test|scan, maxBooks?, maxCategories?, maxListPages?, contentSamples?, tocPages?, delayMs?, respectRobots?} */
    @PostMapping("/start")
    public ResponseEntity<Result<CrawlSiteCatalog>> start(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> catalogService.start(body), log, "开始书目采集失败");
    }

    /** GET /api/novel/crawl/catalogs/{id}：状态、进度、测试报告 */
    @GetMapping("/{id}")
    public ResponseEntity<Result<CrawlSiteCatalog>> detail(@PathVariable Long id) {
        return ResultResponses.handle(() -> catalogService.get(id), log, "查询站点书目失败，id=" + id);
    }

    /** POST /api/novel/crawl/catalogs/{id}/cancel */
    @PostMapping("/{id}/cancel")
    public ResponseEntity<Result<CrawlSiteCatalog>> cancel(@PathVariable Long id) {
        return ResultResponses.handle(() -> catalogService.cancel(id), log, "取消书目采集失败，id=" + id);
    }

    /** POST /api/novel/crawl/catalogs/{id}/decide {decision: USED|REJECTED|PENDING} */
    @PostMapping("/{id}/decide")
    public ResponseEntity<Result<CrawlSiteCatalog>> decide(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        Object decision = body == null ? null : body.get("decision");
        return ResultResponses.handle(() -> catalogService.decide(id, decision == null ? null : String.valueOf(decision)),
                log, "保存决定失败，id=" + id);
    }

    /** POST /api/novel/crawl/catalogs/{id}/delete：删除书目与 data/site-catalog/ 下的文件 */
    @PostMapping("/{id}/delete")
    public ResponseEntity<Result<Void>> delete(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            catalogService.delete(id);
            return null;
        }, log, "删除站点书目失败，id=" + id);
    }

    /** GET /api/novel/crawl/catalogs/{id}/books?keyword=&author=&tagKeyword=&category=&tags=a,b&tagMode=any|all&usable=&page=&size= */
    @GetMapping("/{id}/books")
    public ResponseEntity<Result<Map<String, Object>>> books(@PathVariable Long id,
                                                             @RequestParam(required = false) String keyword,
                                                             @RequestParam(required = false) String author,
                                                             @RequestParam(required = false) String tagKeyword,
                                                             @RequestParam(required = false) String category,
                                                             @RequestParam(required = false) String tags,
                                                             @RequestParam(required = false) String tagMode,
                                                             @RequestParam(required = false) Boolean usable,
                                                             @RequestParam(defaultValue = "1") int page,
                                                             @RequestParam(defaultValue = "50") int size) {
        List<String> tagList = tags == null || tags.isBlank() ? List.of() : Arrays.asList(tags.split(","));
        CrawlCatalogService.BookFilter filter = new CrawlCatalogService.BookFilter(keyword, author, tagKeyword, category,
                tagList, tagMode, usable);
        return ResultResponses.handle(() -> catalogService.books(id, filter, page, size), log, "查询书目失败，id=" + id);
    }

    /** GET /api/novel/crawl/catalogs/{id}/tags → {tags[{tag, count, site, ai}], categories[{name, count}], total} */
    @GetMapping("/{id}/tags")
    public ResponseEntity<Result<Map<String, Object>>> tags(@PathVariable Long id) {
        return ResultResponses.handle(() -> catalogService.tags(id), log, "查询书目标签失败，id=" + id);
    }

    /** GET /api/novel/crawl/catalogs/books/{bookId}/toc：采集时保存的完整目录 */
    @GetMapping("/books/{bookId}/toc")
    public ResponseEntity<Result<JsonNode>> toc(@PathVariable Long bookId) {
        return ResultResponses.handle(() -> catalogService.toc(bookId), log, "读取书目目录失败，bookId=" + bookId);
    }

    /** POST /api/novel/crawl/catalogs/{id}/plot-tags {query}：按情节找书 · AI 从已有标签里挑（省 token） */
    @PostMapping("/{id}/plot-tags")
    public ResponseEntity<Result<Map<String, Object>>> plotTags(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> catalogService.plotTags(id, body), log, "按情节选标签失败，id=" + id);
    }

    /** POST /api/novel/crawl/catalogs/{id}/intro-match {query, filter?, threshold?, estimate?}：按情节找书 · AI 逐本读简介（耗 token） */
    @PostMapping("/{id}/intro-match")
    public ResponseEntity<Result<Map<String, Object>>> introMatch(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> catalogService.introMatch(id, body), log, "AI 读简介失败，id=" + id);
    }

    /** POST /api/novel/crawl/catalogs/{id}/ai-tags {limit?, retag?}：AI 按书名 / 简介补标签 */
    @PostMapping("/{id}/ai-tags")
    public ResponseEntity<Result<Map<String, Object>>> aiTags(@PathVariable Long id,
                                                              @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> catalogService.aiTags(id, body), log, "AI 补标签失败，id=" + id);
    }
}
