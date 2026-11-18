package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.PersonaAdaptation;
import com.example.file.entity.PersonaCard;
import com.example.file.entity.PersonaCardVersion;
import com.example.file.entity.PersonaChat;
import com.example.file.service.PersonaService;
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
import java.util.Objects;

/**
 * 跨世界观角色卡：原型卡（提取、版本）、适配版本（生成、编辑、确认、用于工作区、辨识度测试）、试聊会话。
 */
@RestController
@RequestMapping("/api/persona")
public class PersonaController {

    private static final Logger log = LoggerFactory.getLogger(PersonaController.class);

    private final PersonaService service;

    public PersonaController(PersonaService service) {
        this.service = service;
    }

    // ------------------------------------------------------------------ 原型卡

    @GetMapping("/cards")
    public ResponseEntity<Result<List<PersonaCard>>> list(@RequestParam(required = false) String keyword,
                                                          @RequestParam(required = false) String tag) {
        return ResultResponses.handle(() -> service.list(keyword, tag), log, "查询角色卡失败");
    }

    @GetMapping("/cards/{id}")
    public ResponseEntity<Result<PersonaCard>> get(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.get(id), log, "查询角色卡失败");
    }

    /** {name, aliases?, kind?, tags?, source{type: text|file|extract, text?, fileIds?, extractId?, entityKey?, whole?}, maxBlocks?, chunkChars?, model} */
    @PostMapping("/cards/extract")
    public ResponseEntity<Result<PersonaCard>> extract(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.startExtract(body), log, "提取角色卡失败");
    }

    @PostMapping("/cards/create")
    public ResponseEntity<Result<PersonaCard>> create(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.createBlank(body), log, "新建角色卡失败");
    }

    @PostMapping("/cards/{id}/resume")
    public ResponseEntity<Result<PersonaCard>> resume(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.resumeExtract(id), log, "继续提取失败");
    }

    @PostMapping("/cards/{id}/stop")
    public ResponseEntity<Result<PersonaCard>> stop(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.stopExtract(id), log, "停止提取失败");
    }

    @PostMapping("/cards/{id}/meta")
    public ResponseEntity<Result<PersonaCard>> meta(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.updateMeta(id, body), log, "修改角色卡失败");
    }

    @PostMapping("/cards/{id}/delete")
    public ResponseEntity<Result<Boolean>> delete(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            service.deleteCard(id);
            return true;
        }, log, "删除角色卡失败");
    }

    // ------------------------------------------------------------------ 版本

    @GetMapping("/cards/{id}/versions")
    public ResponseEntity<Result<List<PersonaCardVersion>>> versions(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.versions(id), log, "查询版本失败");
    }

    @GetMapping("/cards/{id}/versions/{no}")
    public ResponseEntity<Result<PersonaCardVersion>> version(@PathVariable Long id, @PathVariable int no) {
        return ResultResponses.handle(() -> service.version(id, no), log, "查询版本失败");
    }

    /** {content, note?} → 新版本 */
    @SuppressWarnings("unchecked")
    @PostMapping("/cards/{id}/versions/save")
    public ResponseEntity<Result<PersonaCard>> saveVersion(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.saveVersion(id,
                body.get("content") instanceof Map<?, ?> m ? (Map<String, Object>) m : null,
                Objects.toString(body.get("note"), "")), log, "保存版本失败");
    }

    @PostMapping("/cards/{id}/versions/{no}/restore")
    public ResponseEntity<Result<PersonaCard>> restore(@PathVariable Long id, @PathVariable int no) {
        return ResultResponses.handle(() -> service.restoreVersion(id, no), log, "恢复版本失败");
    }

    // ------------------------------------------------------------------ 适配版本

    @GetMapping("/cards/{id}/adaptations")
    public ResponseEntity<Result<List<PersonaAdaptation>>> adaptations(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.adaptations(id), log, "查询适配版本失败");
    }

    /** {version?, novelId?, world?, wish?, model} */
    @PostMapping("/cards/{id}/adapt")
    public ResponseEntity<Result<PersonaAdaptation>> adapt(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.adapt(id, body), log, "生成适配版本失败");
    }

    @GetMapping("/adaptations/{id}")
    public ResponseEntity<Result<PersonaAdaptation>> adaptation(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.adaptation(id), log, "查询适配版本失败");
    }

    /** {content} */
    @SuppressWarnings("unchecked")
    @PostMapping("/adaptations/{id}/save")
    public ResponseEntity<Result<PersonaAdaptation>> saveAdaptation(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.saveAdaptation(id,
                body.get("content") instanceof Map<?, ?> m ? (Map<String, Object>) m : null), log, "保存适配版本失败");
    }

    @PostMapping("/adaptations/{id}/confirm")
    public ResponseEntity<Result<PersonaAdaptation>> confirm(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.confirm(id), log, "确认适配版本失败");
    }

    @PostMapping("/adaptations/{id}/delete")
    public ResponseEntity<Result<Boolean>> deleteAdaptation(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            service.deleteAdaptation(id);
            return true;
        }, log, "删除适配版本失败");
    }

    /** {novelId?, role?} → 写进工作区的人物内核 */
    @PostMapping("/adaptations/{id}/apply")
    public ResponseEntity<Result<Map<String, Object>>> apply(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> service.apply(id, body == null ? Map.of() : body), log, "用于工作区失败");
    }

    /** {model, judgeConfigId?} */
    @PostMapping("/adaptations/{id}/test")
    public ResponseEntity<Result<PersonaAdaptation>> test(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> service.startTest(id, body == null ? Map.of() : body), log, "开始辨识度测试失败");
    }

    @PostMapping("/adaptations/{id}/test/cancel")
    public ResponseEntity<Result<PersonaAdaptation>> cancelTest(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.cancelTest(id), log, "取消测试失败");
    }

    // ------------------------------------------------------------------ 工作区

    @GetMapping("/novels/{novelId}")
    public ResponseEntity<Result<List<Map<String, Object>>>> novelPersonas(@PathVariable String novelId) {
        return ResultResponses.handle(() -> service.novelPersonas(novelId), log, "查询工作区人物内核失败");
    }

    /** {name} */
    @PostMapping("/novels/{novelId}/remove")
    public ResponseEntity<Result<Map<String, Object>>> unapply(@PathVariable String novelId, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.unapply(novelId, Objects.toString(body.get("name"), "")), log, "移除人物内核失败");
    }

    // ------------------------------------------------------------------ 试聊

    @GetMapping("/chats")
    public ResponseEntity<Result<List<PersonaChat>>> chats(@RequestParam(required = false) Long cardId,
                                                           @RequestParam(required = false) Long adaptationId,
                                                           @RequestParam(required = false) String novelId,
                                                           @RequestParam(required = false) String name) {
        return ResultResponses.handle(() -> service.chats(cardId, adaptationId, novelId, name), log, "查询会话失败");
    }

    /** {cardId? | adaptationId? | novelId + character, mode?, scene?, inner?} */
    @PostMapping("/chats/start")
    public ResponseEntity<Result<PersonaChat>> startChat(@RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.startChat(body), log, "新建会话失败");
    }

    @GetMapping("/chats/{id}")
    public ResponseEntity<Result<PersonaChat>> chat(@PathVariable Long id) {
        return ResultResponses.handle(() -> service.chat(id), log, "查询会话失败");
    }

    @PostMapping("/chats/{id}/update")
    public ResponseEntity<Result<PersonaChat>> updateChat(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.updateChat(id, body), log, "修改会话失败");
    }

    /** {message, model, boost?} */
    @PostMapping("/chats/{id}/send")
    public ResponseEntity<Result<PersonaChat>> send(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.send(id, body), log, "试聊失败");
    }

    @PostMapping("/chats/{id}/regenerate")
    public ResponseEntity<Result<PersonaChat>> regenerate(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.regenerate(id, body), log, "重新回复失败");
    }

    /** {index, rating: good|bad|null, reason?} */
    @PostMapping("/chats/{id}/feedback")
    public ResponseEntity<Result<PersonaChat>> feedback(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        return ResultResponses.handle(() -> service.feedback(id, body), log, "保存反馈失败");
    }

    @PostMapping("/chats/{id}/delete")
    public ResponseEntity<Result<Boolean>> deleteChat(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            service.deleteChat(id);
            return true;
        }, log, "删除会话失败");
    }

    @GetMapping("/feedback")
    public ResponseEntity<Result<Map<String, Object>>> feedbackSummary(@RequestParam(required = false) Long cardId,
                                                                       @RequestParam(required = false) Long adaptationId) {
        return ResultResponses.handle(() -> service.feedbackSummary(cardId, adaptationId), log, "查询反馈失败");
    }
}
