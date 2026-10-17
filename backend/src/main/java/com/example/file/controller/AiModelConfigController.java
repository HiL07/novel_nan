package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.entity.AiModelConfig;
import com.example.file.service.AiModelConfigService;
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

/**
 * AI 模型配置接口（CORS 只放行 GET/POST，修改/删除也用 POST）。
 * 响应中 apiKey 永不返回明文，只有 apiKeyMasked。
 */
@RestController
@RequestMapping("/api/ai/model")
public class AiModelConfigController {

    private static final Logger log = LoggerFactory.getLogger(AiModelConfigController.class);

    private final AiModelConfigService modelService;

    public AiModelConfigController(AiModelConfigService modelService) {
        this.modelService = modelService;
    }

    /** GET /api/ai/model/list，启用的排最前 */
    @GetMapping("/list")
    public ResponseEntity<Result<List<AiModelConfig>>> list() {
        return ResultResponses.handle(modelService::list, log, "查询模型配置失败");
    }

    /** POST /api/ai/model/save，id 为空新增，否则修改（apiKey 留空保持原值）；改了地址/模型/Key 需重新验证 */
    @PostMapping("/save")
    public ResponseEntity<Result<AiModelConfig>> save(@RequestBody AiModelConfig req) {
        return ResultResponses.handle(() -> modelService.save(req), log, "保存模型配置失败");
    }

    /** POST /api/ai/model/{id}/verify，真实调用一次模型验证配置 */
    @PostMapping("/{id}/verify")
    public ResponseEntity<Result<AiModelConfig>> verify(@PathVariable Long id) {
        return ResultResponses.handle(() -> modelService.verify(id), log, "验证模型配置失败，id=" + id);
    }

    /** POST /api/ai/model/{id}/activate，启用（仅限已验证），其余自动停用 */
    @PostMapping("/{id}/activate")
    public ResponseEntity<Result<AiModelConfig>> activate(@PathVariable Long id) {
        return ResultResponses.handle(() -> modelService.activate(id), log, "启用模型配置失败，id=" + id);
    }

    /** POST /api/ai/model/{id}/delete */
    @PostMapping("/{id}/delete")
    public ResponseEntity<Result<Void>> delete(@PathVariable Long id) {
        return ResultResponses.handle(() -> {
            modelService.delete(id);
            return null;
        }, log, "删除模型配置失败，id=" + id);
    }
}
