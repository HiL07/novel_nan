package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.InspirationItem;
import com.example.file.entity.InspirationRun;
import com.example.file.entity.InspirationWall;
import com.example.file.entity.Material;
import com.example.file.service.InspirationService;
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
 * 灵感墙：墙 / 条目 / 构思记录，以及构思三步（拆需求 → 检索素材 → 生成思路）、细化、追问修改、逛素材。
 */
@RestController
@RequestMapping("/api/inspire")
public class InspirationController {

    private static final Logger log = LoggerFactory.getLogger(InspirationController.class);

    private final InspirationService service;

    public InspirationController(InspirationService service) {
        this.service = service;
    }

    /** GET /api/inspire/walls：全部墙（最近更新的在前），带思路数 / 素材数 */
    @GetMapping("/walls")
    public ResponseEntity<Result<List<InspirationWall>>> walls() {
        return ResultResponses.handle(service::walls, log, "查询灵感墙失败");
    }

    /** POST /api/inspire/walls/save {id?, name, note?, novelId?（空串 = 取消关联）, excludeBooks?} */
    @PostMapping("/walls/save")
    public ResponseEntity<Result<InspirationWall>> saveWall(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.saveWall(body), log, "保存灵感墙失败");
    }

    /** POST /api/inspire/walls/{id}/delete：删除墙及其条目、构思记录 */
    @PostMapping("/walls/{id}/delete")
    public ResponseEntity<Result<Void>> deleteWall(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            service.deleteWall(id);
            return null;
        }, log, "删除灵感墙失败，id=" + id);
    }

    /** GET /api/inspire/walls/{id}/items：墙上的思路和钉的素材 */
    @GetMapping("/walls/{id}/items")
    public ResponseEntity<Result<List<InspirationItem>>> items(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.items(id), log, "查询灵感墙条目失败，id=" + id);
    }

    /** POST /api/inspire/items/save {id?, wallId, type: idea|material, title, content, sources, note, sort?} */
    @PostMapping("/items/save")
    public ResponseEntity<Result<InspirationItem>> saveItem(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.saveItem(body), log, "保存灵感墙条目失败");
    }

    /** POST /api/inspire/items/{id}/delete */
    @PostMapping("/items/{id}/delete")
    public ResponseEntity<Result<Void>> deleteItem(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            service.deleteItem(id);
            return null;
        }, log, "删除灵感墙条目失败，id=" + id);
    }

    /** POST /api/inspire/walls/{id}/pin {materialId}：把素材钉到墙上 */
    @PostMapping("/walls/{id}/pin")
    public ResponseEntity<Result<InspirationItem>> pin(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        Long materialId = body.get("materialId") instanceof Number n ? n.longValue() : null;
        return ResultResponses.handle(() -> service.pin(id, materialId), log, "钉素材失败，wallId=" + id);
    }

    /** POST /api/inspire/walls/{id}/plan {request, target, conditions, model}：① 拆需求 */
    @PostMapping("/walls/{id}/plan")
    public ResponseEntity<Result<Map<String, Object>>> plan(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.plan(id, body), log, "拆需求失败，wallId=" + id);
    }

    /** POST /api/inspire/walls/{id}/retrieve {needs, explore?}：② 检索素材（本地，不花 token） */
    @PostMapping("/walls/{id}/retrieve")
    public ResponseEntity<Result<Map<String, Object>>> retrieve(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.retrieve(id, body), log, "检索素材失败，wallId=" + id);
    }

    /** POST /api/inspire/walls/{id}/ideas {request, target, conditions, plan, materialIds, materialVariants, count, model}：③ 生成思路 */
    @PostMapping("/walls/{id}/ideas")
    public ResponseEntity<Result<InspirationRun>> ideas(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.ideas(id, body), log, "生成思路失败，wallId=" + id);
    }

    /** POST /api/inspire/ideas/refine {wallId, idea, instruction?, materialIds, materialVariants, target, model}：细化 */
    @PostMapping("/ideas/refine")
    public ResponseEntity<Result<Map<String, Object>>> refine(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.refine(body), log, "细化思路失败");
    }

    /** POST /api/inspire/ideas/revise {wallId, idea, instruction, history, materialIds, materialVariants, target, model}：追问修改 */
    @PostMapping("/ideas/revise")
    public ResponseEntity<Result<Map<String, Object>>> revise(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.revise(body), log, "修改思路失败");
    }

    /** GET /api/inspire/walls/{id}/runs：构思记录 */
    @GetMapping("/walls/{id}/runs")
    public ResponseEntity<Result<List<InspirationRun>>> runs(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.runs(id), log, "查询构思记录失败，wallId=" + id);
    }

    /** POST /api/inspire/runs/{id}/update {ideas}：细化 / 修改后更新记录里的思路 */
    @PostMapping("/runs/{id}/update")
    public ResponseEntity<Result<InspirationRun>> updateRun(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.updateRun(id, body), log, "更新构思记录失败，id=" + id);
    }

    /** GET /api/inspire/browse?wallId=&category=&count=：逛素材（跨书随机，每本书最多 2 条） */
    @GetMapping("/browse")
    public ResponseEntity<Result<List<Material>>> browse(@RequestParam(required = false) Long wallId,
                                                         @RequestParam(required = false) String category,
                                                         @RequestParam(defaultValue = "12") int count) {
        return ResultResponses.handle(() -> service.browse(wallId, category, count), log, "逛素材失败");
    }
}
