package com.example.file.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.Material;
import com.example.file.entity.MaterialCandidate;
import com.example.file.service.MaterialService;
import lombok.Data;
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
 * 创作素材库接口（CORS 只放行 GET/POST，修改 / 删除也用 POST）。
 */
@RestController
@RequestMapping("/api/material")
public class MaterialController {

    private static final Logger log = LoggerFactory.getLogger(MaterialController.class);

    private final MaterialService materialService;

    public MaterialController(MaterialService materialService) {
        this.materialService = materialService;
    }

    /** GET /api/material/categories：[{code, label, count}] */
    @GetMapping("/categories")
    public ResponseEntity<Result<List<Map<String, Object>>>> categories() {
        return ResultResponses.handle(materialService::categories, log, "查询素材分类失败");
    }

    /** GET /api/material/tags?category=：标签云 [{tag, count}] */
    @GetMapping("/tags")
    public ResponseEntity<Result<List<Map<String, Object>>>> tags(@RequestParam(required = false) String category) {
        return ResultResponses.handle(() -> materialService.tags(category), log, "查询标签失败");
    }

    /**
     * GET /api/material/list?category=&tags=a,b&tagMode=all|any&keyword=&sourceBook=&excludeBooks=a,b&pinned=&page=&size=
     * 关键词 + 标签检索；sourceBook = 只看某本书（__manual__ = 手动添加），excludeBooks = 屏蔽来源书（保留的素材除外），
     * pinned=true 只看保留的
     */
    @GetMapping("/list")
    public ResponseEntity<Result<Page<Material>>> list(@RequestParam(required = false) String category,
                                                       @RequestParam(required = false) List<String> tags,
                                                       @RequestParam(defaultValue = "all") String tagMode,
                                                       @RequestParam(required = false) String keyword,
                                                       @RequestParam(required = false) String sourceBook,
                                                       @RequestParam(required = false) List<String> excludeBooks,
                                                       @RequestParam(required = false) Boolean pinned,
                                                       @RequestParam(defaultValue = "1") int page,
                                                       @RequestParam(defaultValue = "20") int size) {
        return ResultResponses.handle(() -> materialService.search(category, tags, tagMode, keyword,
                sourceBook, excludeBooks, pinned, page, size), log, "检索素材失败");
    }

    /** GET /api/material/sources：来源书 [{book（null = 手动添加）, count, pinned, pending}] */
    @GetMapping("/sources")
    public ResponseEntity<Result<List<Map<String, Object>>>> sources() {
        return ResultResponses.handle(materialService::sources, log, "查询素材来源失败");
    }

    /** POST /api/material/sources/delete {book, withCandidates?}：删除该书未保留的素材 → {deleted, kept, candidatesIgnored} */
    @PostMapping("/sources/delete")
    public ResponseEntity<Result<Map<String, Object>>> deleteSource(@RequestBody SourceDeleteReq req) {
        return ResultResponses.handle(() -> materialService.deleteBySource(req.getBook(),
                Boolean.TRUE.equals(req.getWithCandidates())), log, "按来源删除素材失败");
    }

    /** POST /api/material/{id}/pin {pinned}：保留 / 取消保留 */
    @PostMapping("/{id}/pin")
    public ResponseEntity<Result<Material>> pin(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> materialService.setPinned(id, Boolean.TRUE.equals(body.get("pinned"))),
                log, "保留素材失败，id=" + id);
    }

    /** POST /api/material/semantic-search {query, category?, tags?, excludeBooks?, limit?}：AI 语义检索（使用启用的模型） */
    @PostMapping("/semantic-search")
    public ResponseEntity<Result<Map<String, Object>>> semantic(@RequestBody SemanticReq req) {
        return ResultResponses.handle(() -> materialService.semanticSearch(req.getQuery(), req.getCategory(), req.getTags(),
                req.getExcludeBooks(), req.getLimit() == null ? 20 : req.getLimit()), log, "语义检索失败");
    }

    @GetMapping("/{id}")
    public ResponseEntity<Result<Material>> get(@PathVariable Long id) {
        return ResultResponses.handle(() -> materialService.get(id), log, "查询素材失败，id=" + id);
    }

    /** POST /api/material/save：id 为空新增（来源记为 manual），否则修改 */
    @PostMapping("/save")
    public ResponseEntity<Result<Material>> save(@RequestBody Material req) {
        return ResultResponses.handle(() -> materialService.save(req), log, "保存素材失败");
    }

    @PostMapping("/{id}/delete")
    public ResponseEntity<Result<Void>> delete(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            materialService.delete(id);
            return null;
        }, log, "删除素材失败，id=" + id);
    }

    /** POST /api/material/use {ids}：素材被应用到写作设定后记一次使用 */
    @PostMapping("/use")
    public ResponseEntity<Result<Void>> use(@RequestBody IdsReq req) {
        return ResultResponses.handle(() -> {
            materialService.recordUse(req.getIds());
            return null;
        }, log, "记录素材使用失败");
    }

    /** GET /api/material/candidates?status=PENDING&extractId=：AI 提取的素材候选 */
    @GetMapping("/candidates")
    public ResponseEntity<Result<List<MaterialCandidate>>> candidates(@RequestParam(required = false) String status,
                                                                     @RequestParam(required = false) Long extractId) {
        return ResultResponses.handle(() -> materialService.candidates(status, extractId), log, "查询素材候选失败");
    }

    /** GET /api/material/candidates/count：待确认数量 */
    @GetMapping("/candidates/count")
    public ResponseEntity<Result<Long>> pendingCount() {
        return ResultResponses.handle(materialService::pendingCount, log, "查询素材候选失败");
    }

    /** POST /api/material/candidates/save {items: [{id, category?, title?, summary?, attributes?, tags?, detail?}]}：确认入库 */
    @PostMapping("/candidates/save")
    public ResponseEntity<Result<List<Material>>> saveCandidates(@RequestBody CandidateSaveReq req) {
        return ResultResponses.handle(() -> materialService.saveCandidates(req.getItems()), log, "保存素材候选失败");
    }

    /** POST /api/material/candidates/ignore {ids}：忽略候选 */
    @PostMapping("/candidates/ignore")
    public ResponseEntity<Result<Integer>> ignoreCandidates(@RequestBody IdsReq req) {
        return ResultResponses.handle(() -> materialService.ignoreCandidates(req.getIds()), log, "忽略素材候选失败");
    }

    @Data
    public static class SemanticReq {
        private String query;
        private String category;
        private List<String> tags;
        private List<String> excludeBooks;
        private Integer limit;
    }

    @Data
    public static class SourceDeleteReq {
        private String book;
        private Boolean withCandidates;
    }

    @Data
    public static class IdsReq {
        private List<Long> ids;
    }

    @Data
    public static class CandidateSaveReq {
        private List<Map<String, Object>> items;
    }
}
