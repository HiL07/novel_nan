package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.ExtractCard;
import com.example.file.entity.MaterialCompile;
import com.example.file.entity.NovelExtract;
import com.example.file.service.ExtractCardService;
import com.example.file.service.MaterialCompileService;
import com.example.file.service.NovelExtractService;
import com.fasterxml.jackson.databind.JsonNode;
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
 * 小说提取接口：提交任务 / 任务列表 / 任务详情（含结果）。
 */
@RestController
@RequestMapping("/api/novel/extract")
public class NovelExtractController {

    private static final Logger log = LoggerFactory.getLogger(NovelExtractController.class);

    private final NovelExtractService extractService;
    private final MaterialCompileService compileService;
    private final ExtractCardService cardService;

    public NovelExtractController(NovelExtractService extractService, MaterialCompileService compileService,
                                  ExtractCardService cardService) {
        this.extractService = extractService;
        this.compileService = compileService;
        this.cardService = cardService;
    }

    /** GET /api/novel/extract/{id}/cards：这个工作区的卡片（带 match = 素材库里这本书的同分类同名素材） */
    @GetMapping("/{id}/cards")
    public ResponseEntity<Result<List<ExtractCard>>> cards(@PathVariable Long id) {
        return ResultResponses.handle(() -> cardService.list(id), log, "查询卡片失败，extractId=" + id);
    }

    /** POST /api/novel/extract/card/{cid} {title?, subtype?, summary?, detail?, attributes?, tags?, tier?, category?}：手改卡片 */
    @PostMapping("/card/{cid}")
    public ResponseEntity<Result<ExtractCard>> updateCard(@PathVariable Long cid, @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> cardService.update(cid, body), log, "保存卡片失败，cardId=" + cid);
    }

    /** POST /api/novel/extract/card/{cid}/restore {version}：换回历史版本 */
    @PostMapping("/card/{cid}/restore")
    public ResponseEntity<Result<ExtractCard>> restoreCard(@PathVariable Long cid, @RequestBody Map<String, Object> body) {
        Object v = body == null ? null : body.get("version");
        int version = v instanceof Number n ? n.intValue() : -1;
        return ResultResponses.handle(() -> cardService.restore(cid, version), log, "换回卡片版本失败，cardId=" + cid);
    }

    /**
     * POST /api/novel/extract/{id}/cards/save {items: [{cardId, action: new|update|version|skip|reset, targetId?}]}：
     * 素材选择 → 存进素材库 → {saved, updated, versions, skipped, errors[]}
     */
    @PostMapping("/{id}/cards/save")
    @SuppressWarnings("unchecked")
    public ResponseEntity<Result<Map<String, Object>>> saveCards(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        List<Map<String, Object>> items = body != null && body.get("items") instanceof List<?> l ? (List<Map<String, Object>>) l : List.of();
        return ResultResponses.handle(() -> cardService.saveToLibrary(id, items), log, "存入素材库失败，extractId=" + id);
    }

    /**
     * POST /api/novel/extract/{id}/compile {model, entityKeys?, categories?, topN?, plot?}：对提取成功的小说整理卡片
     * （实体卡 / 体系卡 / 剧情段 → 这个工作区的卡片，见 ExtractCardService）。
     */
    @PostMapping("/{id}/compile")
    public ResponseEntity<Result<MaterialCompile>> compile(@PathVariable Long id,
                                                           @RequestBody(required = false) Map<String, Object> options) {
        return ResultResponses.handle(() -> compileService.start(id, options), log, "发起整理卡片失败，extractId=" + id);
    }

    /**
     * POST /api/novel/extract/{id}/world-groups {model?}：世界观分组提议（只是建议）→ {groups[{name, members[实体键], reason}], usage}；
     * 作者改过之后用 compile {mode: world, groups} 整理世界观卡
     */
    @PostMapping("/{id}/world-groups")
    public ResponseEntity<Result<JsonNode>> worldGroups(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> compileService.proposeWorldGroups(id, body), log, "世界观分组失败，extractId=" + id);
    }

    /**
     * POST /api/novel/extract/{id}/resonance-groups {model?}：共鸣素材分组提议（只是建议）→ {groups[{name, cardIds, reason}], usage}；
     * 作者改过之后用 compile {mode: resonance, groups: [{name, cardIds}]} 生成
     */
    @PostMapping("/{id}/resonance-groups")
    public ResponseEntity<Result<JsonNode>> resonanceGroups(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> compileService.proposeResonanceGroups(id, body), log, "共鸣分组失败，extractId=" + id);
    }

    /** GET /api/novel/extract/{id}/compiles：这次提取的整理记录，最近的在前 */
    @GetMapping("/{id}/compiles")
    public ResponseEntity<Result<List<MaterialCompile>>> compiles(@PathVariable Long id) {
        return ResultResponses.handle(() -> compileService.list(id), log, "查询整理记录失败，extractId=" + id);
    }

    /** POST /api/novel/extract/compile/{cid}/pause：暂停整理（停下后为中断，可继续） */
    @PostMapping("/compile/{cid}/pause")
    public ResponseEntity<Result<MaterialCompile>> pauseCompile(@PathVariable Long cid) {
        return ResultResponses.handle(() -> compileService.pause(cid), log, "暂停整理失败，id=" + cid);
    }

    /** POST /api/novel/extract/compile/{cid}/resume：继续中断的整理（已整理的卡片不重做） */
    @PostMapping("/compile/{cid}/resume")
    public ResponseEntity<Result<MaterialCompile>> resumeCompile(@PathVariable Long cid) {
        return ResultResponses.handle(() -> compileService.resume(cid), log, "继续整理失败，id=" + cid);
    }

    /** POST /api/novel/extract/compile/{cid}/cancel：取消整理（记为失败，可重新发起） */
    @PostMapping("/compile/{cid}/cancel")
    public ResponseEntity<Result<MaterialCompile>> cancelCompile(@PathVariable Long cid) {
        return ResultResponses.handle(() -> compileService.cancel(cid), log, "取消整理失败，id=" + cid);
    }

    /**
     * POST /api/novel/extract/{fileId} [{materials?, model?}]，对指定文件发起提取，立即返回任务（异步执行）。
     * model：{source: api, configId?}（空 = 当前启用的配置）或 {source: local, baseId, chunkChars?} 或 {source: gguf}（llama.cpp 页运行中的 GGUF）。
     */
    @PostMapping("/{fileId}")
    public ResponseEntity<Result<NovelExtract>> submit(@PathVariable Long fileId,
                                                       @RequestBody(required = false) ExtractOptions options) {
        Map<String, Object> materials = options == null ? null : options.getMaterials();
        Map<String, Object> model = options == null ? null : options.getModel();
        return ResultResponses.handle(() -> extractService.submit(fileId, materials, model), log,
                "提交提取任务失败，fileId=" + fileId);
    }

    /** POST /api/novel/extract/draft/{fileId}：打开提取工作区 → 这个文件「未开始」（DRAFT）的提取（没有就新建） */
    @PostMapping("/draft/{fileId}")
    public ResponseEntity<Result<NovelExtract>> draft(@PathVariable Long fileId) {
        return ResultResponses.handle(() -> extractService.draft(fileId), log, "新建提取失败，fileId=" + fileId);
    }

    /** POST /api/novel/extract/{id}/draft {model?, materials?}：保存未开始提取的草稿设置（含章节范围） */
    @PostMapping("/{id}/draft")
    public ResponseEntity<Result<NovelExtract>> saveDraft(@PathVariable Long id,
                                                          @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> extractService.saveDraft(id, body), log, "保存提取设置失败，id=" + id);
    }

    /** POST /api/novel/extract/{id}/start {materials?, model?}：开始未开始的提取（参数同提交） */
    @PostMapping("/{id}/start")
    public ResponseEntity<Result<NovelExtract>> start(@PathVariable Long id,
                                                      @RequestBody(required = false) ExtractOptions options) {
        Map<String, Object> materials = options == null ? null : options.getMaterials();
        Map<String, Object> model = options == null ? null : options.getModel();
        return ResultResponses.handle(() -> extractService.start(id, materials, model), log, "开始提取失败，id=" + id);
    }

    /**
     * POST /api/novel/extract/{id}/cancel，取消排队中 / 进行中 / 中断的任务（记为 FAILED「已取消」，进入提取失败）。
     */
    @PostMapping("/{id}/cancel")
    public ResponseEntity<Result<NovelExtract>> cancel(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.cancel(id), log, "取消提取任务失败，id=" + id);
    }

    /**
     * POST /api/novel/extract/{id}/pause，暂停排队中 / 进行中的任务：停下后为 INTERRUPTED（断点保留，可继续或取消）。
     */
    @PostMapping("/{id}/pause")
    public ResponseEntity<Result<NovelExtract>> pause(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.pause(id), log, "暂停提取任务失败，id=" + id);
    }

    /**
     * POST /api/novel/extract/delete {ids}，删除提取工作区（正在提取 / 整理的跳过）：记录、断点、结果文件、整理记录、素材候选；
     * 是这本书最后一个工作区时连同这本书的素材（保留的除外）→ {deleted, skipped, materialsDeleted, reasons[]}。
     */
    @PostMapping("/delete")
    public ResponseEntity<Result<Map<String, Object>>> delete(@RequestBody Map<String, List<Long>> body) {
        return ResultResponses.handle(() -> extractService.delete(body == null ? null : body.get("ids")), log,
                "删除提取工作区失败");
    }

    /** GET /api/novel/extract/{id}/delete-preview → 删除会清掉什么（确认框用），见 NovelExtractService.deletePreview */
    @GetMapping("/{id}/delete-preview")
    public ResponseEntity<Result<Map<String, Object>>> deletePreview(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.deletePreview(id), log, "读取删除预览失败，id=" + id);
    }

    /** POST /api/novel/extract/{id}/title {title}：改工作区名（空 = 清掉） */
    @PostMapping("/{id}/title")
    public ResponseEntity<Result<NovelExtract>> rename(@PathVariable Long id, @RequestBody(required = false) Map<String, String> body) {
        return ResultResponses.handle(() -> extractService.rename(id, body == null ? null : body.get("title")), log,
                "修改工作区名失败，id=" + id);
    }

    /**
     * POST /api/novel/extract/{id}/resume，继续中断的任务：AI 服务里还在跑就接着轮询，否则用提交时的参数
     * 重新提交，同一个断点键，已完成的分块 / 卡片不重做。
     */
    @PostMapping("/{id}/resume")
    public ResponseEntity<Result<NovelExtract>> resume(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.resume(id), log, "继续提取任务失败，id=" + id);
    }

    /**
     * GET /api/novel/extract/list，任务列表（不含结果），按创建时间倒序。
     */
    @GetMapping("/list")
    public ResponseEntity<Result<List<NovelExtract>>> list() {
        return ResultResponses.handle(extractService::list, log, "查询提取任务失败");
    }

    /**
     * GET /api/novel/extract/{id}，任务详情，result 为提取结果 JSON 字符串。
     */
    @GetMapping("/{id}")
    public ResponseEntity<Result<NovelExtract>> detail(@PathVariable Long id) {
        return ResultResponses.handle(() -> extractService.getById(id), log, "查询提取任务失败，id=" + id);
    }

    /** GET /api/novel/extract/{id}/live?since=N：逐章查看（提取中）→ {status, progress, message, live | finished} */
    @GetMapping("/{id}/live")
    public ResponseEntity<Result<Map<String, Object>>> live(@PathVariable Long id,
                                                            @RequestParam(defaultValue = "0") int since) {
        return ResultResponses.handle(() -> extractService.live(id, since), log, "读取逐章进度失败，id=" + id);
    }

    /** GET /api/novel/extract/file/{fileId}/chapters/{index}/text：按文件取全书第 index 章（从 0 数）的原文（提取工作区） */
    @GetMapping("/file/{fileId}/chapters/{index}/text")
    public ResponseEntity<Result<JsonNode>> fileChapterText(@PathVariable Long fileId, @PathVariable int index) {
        return ResultResponses.handle(() -> extractService.fileChapterText(fileId, index), log,
                "读取章节原文失败，fileId=" + fileId + " index=" + index);
    }

    /** POST /api/novel/extract/{id}/extend {toChapter}：接着读到第 N 章（0 = 最后），前面的章不重读 */
    @PostMapping("/{id}/extend")
    public ResponseEntity<Result<NovelExtract>> extend(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        Integer to = body == null || !(body.get("toChapter") instanceof Number n) ? null : n.intValue();
        return ResultResponses.handle(() -> extractService.extend(id, to), log, "接着读失败，id=" + id);
    }

    /** POST /api/novel/extract/{id}/reread {cis}：重读这几章（范围内序号，0 起） */
    @PostMapping("/{id}/reread")
    public ResponseEntity<Result<NovelExtract>> reread(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        List<Integer> cis = body == null || !(body.get("cis") instanceof List<?> l) ? null
                : l.stream().filter(x -> x instanceof Number).map(x -> ((Number) x).intValue()).toList();
        return ResultResponses.handle(() -> extractService.reread(id, cis), log, "重读失败，id=" + id);
    }

    /** POST /api/novel/extract/entity-groups {entities, model}：全书实体的 AI 归并建议（不改数据，作者逐组采用） */
    @PostMapping("/entity-groups")
    public ResponseEntity<Result<JsonNode>> entityGroups(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> extractService.entityGroups(body), log, "AI 归并失败");
    }

    /** GET /api/novel/extract/split/{fileId}：提取前预览分章（选章节范围用） */
    @GetMapping("/split/{fileId}")
    public ResponseEntity<Result<JsonNode>> split(@PathVariable Long fileId) {
        return ResultResponses.handle(() -> extractService.splitPreview(fileId), log, "分章预览失败，fileId=" + fileId);
    }

    /**
     * POST /api/novel/extract/{id}/result {chapters: [...], characters: [...], style, ...}：保存手动修改后的提取结果（整体替换）。
     */
    @PostMapping("/{id}/result")
    public ResponseEntity<Result<NovelExtract>> updateResult(@PathVariable Long id, @RequestBody Map<String, Object> result) {
        return ResultResponses.handle(() -> extractService.updateResult(id, result), log, "保存提取结果失败，id=" + id);
    }

    /**
     * 提取选项：materials = {enabled, categories: [world, monster, …], rounds, chunkChars, focus}（是否记录设定实体，
     * 原样交给 Python 校验；整理卡片是之后单独的一步）；
     * model = 提取用的模型（见 submit），字段由 service 白名单处理。
     */
    @Data
    public static class ExtractOptions {
        private Map<String, Object> materials;
        private Map<String, Object> model;
    }
}
