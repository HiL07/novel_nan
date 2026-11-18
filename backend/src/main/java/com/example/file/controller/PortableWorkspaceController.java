package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.PortableWorkspace;
import com.example.file.service.PortableWorkspaceService;
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

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** 架空工作区（2026-11-06）：每次架空一个工作区，勾选素材库的原素材加入待加工，后台逐条生成架空版 */
@RestController
@RequestMapping("/api/material/portable-ws")
public class PortableWorkspaceController {

    private static final Logger log = LoggerFactory.getLogger(PortableWorkspaceController.class);

    private final PortableWorkspaceService service;

    public PortableWorkspaceController(PortableWorkspaceService service) {
        this.service = service;
    }

    /** GET /list：工作区列表（带 counts {QUEUED, RUNNING, DONE, FAILED} 和 current = 正在加工的原素材名） */
    @GetMapping("/list")
    public ResponseEntity<Result<List<PortableWorkspace>>> list() {
        return ResultResponses.handle(service::list, log, "查询架空工作区失败");
    }

    /** POST /create {title?, targetWorld?, model?: {source: api|gguf}} */
    @PostMapping("/create")
    public ResponseEntity<Result<PortableWorkspace>> create(@RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> service.create(body), log, "新建架空工作区失败");
    }

    /** GET /{id}：详情 + counts + current */
    @GetMapping("/{id}")
    public ResponseEntity<Result<PortableWorkspace>> detail(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.detail(id), log, "查询架空工作区失败，id=" + id);
    }

    /** POST /{id}/update {title?, targetWorld?, model?, filter?} */
    @PostMapping("/{id}/update")
    public ResponseEntity<Result<PortableWorkspace>> update(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.update(id, body), log, "修改架空工作区失败，id=" + id);
    }

    /** GET /{id}/delete-preview → {portables: 它产出的架空版条数, blocked: 不能删的原因（空 = 可以）} */
    @GetMapping("/{id}/delete-preview")
    public ResponseEntity<Result<Map<String, Object>>> deletePreview(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.deletePreview(id), log, "查询失败，id=" + id);
    }

    /** POST /{id}/delete {withMaterials}：true = 它产出的架空版一并删除 → {deletedMaterials} */
    @PostMapping("/{id}/delete")
    public ResponseEntity<Result<Map<String, Object>>> delete(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> service.delete(id, body), log, "删除架空工作区失败，id=" + id);
    }

    /**
     * GET /{id}/materials?category&sourceBook&keyword&tags（逗号分隔）&tagMode&state=all|none|QUEUED|RUNNING|DONE|FAILED&page&size
     * → 全库原素材 + 在这个工作区的状态 {total, records: [{id, title, category, subtype, sourceBook, summary, state, error, leaks,
     * portable?: {id, title, portability}, otherPortables}]}
     */
    @GetMapping("/{id}/materials")
    public ResponseEntity<Result<Map<String, Object>>> materials(@PathVariable Long id, @RequestParam Map<String, String> query) {
        return ResultResponses.handle(() -> service.materials(id, new HashMap<>(query)), log, "查询素材失败，id=" + id);
    }

    /** POST /{id}/enqueue {ids} | {all: true, filter}，redo? → {added, requeued, skipped} */
    @PostMapping("/{id}/enqueue")
    public ResponseEntity<Result<Map<String, Object>>> enqueue(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.enqueue(id, body), log, "加入待加工失败，id=" + id);
    }

    /** POST /{id}/dequeue {ids}：移出待加工 / 失败的 → {removed} */
    @PostMapping("/{id}/dequeue")
    public ResponseEntity<Result<Map<String, Object>>> dequeue(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.dequeue(id, body), log, "移出失败，id=" + id);
    }

    /** POST /{id}/start：开始 / 继续（同一时间只跑一个工作区） */
    @PostMapping("/{id}/start")
    public ResponseEntity<Result<PortableWorkspace>> start(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.start(id), log, "开始架空加工失败，id=" + id);
    }

    /** POST /{id}/pause：正在加工的几条做完后停下 */
    @PostMapping("/{id}/pause")
    public ResponseEntity<Result<PortableWorkspace>> pause(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.pause(id), log, "暂停失败，id=" + id);
    }
}
