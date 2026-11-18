package com.example.file.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.Material;
import com.example.file.entity.MaterialMerge;
import com.example.file.service.MaterialMergeService;
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

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 素材精炼 / 合并：查找相似素材 → （可选）AI 写合并稿 → 逐条确认合并；可忽略、恢复、拆分。
 */
@RestController
@RequestMapping("/api/material/merge")
public class MaterialMergeController {

    private static final Logger log = LoggerFactory.getLogger(MaterialMergeController.class);

    private final MaterialMergeService mergeService;

    public MaterialMergeController(MaterialMergeService mergeService) {
        this.mergeService = mergeService;
    }

    /** POST /api/material/merge/find {categories?, books?, crossBookOnly?, threshold?, maxGroup?, modelId?} → {found, skipped, …} */
    @PostMapping("/find")
    public ResponseEntity<Result<Map<String, Object>>> find(@RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> mergeService.find(body), log, "查找相似素材失败");
    }

    /** GET /api/material/merge/list?status=open|APPLIED|IGNORED&category=&crossBook=&page=&size= */
    @GetMapping("/list")
    public ResponseEntity<Result<Page<MaterialMerge>>> list(@RequestParam(required = false) String status,
                                                            @RequestParam(required = false) String category,
                                                            @RequestParam(required = false) Boolean crossBook,
                                                            @RequestParam(defaultValue = "1") int page,
                                                            @RequestParam(defaultValue = "10") int size) {
        return ResultResponses.handle(() -> mergeService.list(status, category, crossBook, page, size), log, "查询合并建议失败");
    }

    /** GET /api/material/merge/counts → {open, drafted, cross, APPLIED, IGNORED} */
    @GetMapping("/counts")
    public ResponseEntity<Result<Map<String, Long>>> counts() {
        return ResultResponses.handle(mergeService::counts, log, "查询合并建议数量失败");
    }

    /** POST /api/material/merge/draft {ids, model: {source: api, configId?} | {source: gguf}}：AI 写合并稿（后台逐组） */
    @PostMapping("/draft")
    public ResponseEntity<Result<Map<String, Object>>> draft(@RequestBody Map<String, Object> body) {
        @SuppressWarnings("unchecked")
        Map<String, Object> model = body.get("model") instanceof Map<?, ?> m ? (Map<String, Object>) m : null;
        return ResultResponses.handle(() -> mergeService.startDraft(ids(body), model), log, "开始写合并稿失败");
    }

    /** GET /api/material/merge/draft/status → {running, total, done, failed, currentId, lastError} */
    @GetMapping("/draft/status")
    public ResponseEntity<Result<Map<String, Object>>> draftStatus() {
        return ResultResponses.handle(mergeService::draftStatus, log, "查询合并稿进度失败");
    }

    /** POST /api/material/merge/draft/stop：当前这组写完后停下 */
    @PostMapping("/draft/stop")
    public ResponseEntity<Result<Map<String, Object>>> stopDraft() {
        return ResultResponses.handle(mergeService::stopDraft, log, "暂停写合并稿失败");
    }

    /** POST /api/material/merge/{id}/apply {memberIds?, title?, subtype?, summary?, detail?, attributes?, tags?, variants?} → 主条目 */
    @PostMapping("/{id}/apply")
    public ResponseEntity<Result<Material>> apply(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> mergeService.apply(id, body), log, "合并素材失败，mergeId=" + id);
    }

    /** POST /api/material/merge/ignore {ids}：忽略（以后查找不再建议同一组） */
    @PostMapping("/ignore")
    public ResponseEntity<Result<Integer>> ignore(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> mergeService.ignore(ids(body)), log, "忽略合并建议失败");
    }

    /** POST /api/material/merge/restore {ids}：恢复忽略的建议 */
    @PostMapping("/restore")
    public ResponseEntity<Result<Integer>> restore(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> mergeService.restore(ids(body)), log, "恢复合并建议失败");
    }

    /** POST /api/material/merge/unmerge/{materialId}：拆分主条目，成员回到素材库 → {restored} */
    @PostMapping("/unmerge/{materialId}")
    public ResponseEntity<Result<Map<String, Object>>> unmerge(@PathVariable Long materialId) {
        return ResultResponses.handle(() -> mergeService.unmerge(materialId), log, "拆分合并失败，id=" + materialId);
    }

    private static List<Long> ids(Map<String, Object> body) {
        List<Long> out = new ArrayList<>();
        if (body != null && body.get("ids") instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Number n) {
                    out.add(n.longValue());
                }
            }
        }
        return out;
    }
}
