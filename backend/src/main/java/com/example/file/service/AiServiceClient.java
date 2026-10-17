package com.example.file.service;

import com.example.file.entity.AiModelConfig;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Python AI 服务（python-service）的 HTTP 客户端：模型验证、提交 / 查询提取任务。
 * 模型配置（含 API Key）随请求下发，Python 端不保存。
 */
@Component
public class AiServiceClient {

    private final RestClient client;

    public AiServiceClient(@Value("${ai.service.url}") String aiServiceUrl) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        // 验证会真实调用一次远程模型，留足时间
        factory.setReadTimeout(60000);
        this.client = RestClient.builder().baseUrl(aiServiceUrl).requestFactory(factory).build();
    }

    /** POST /api/models/verify → {ok, latencyMs, message, reply} */
    public JsonNode verifyModel(AiModelConfig cfg) {
        return client.post().uri("/api/models/verify").body(modelBody(cfg)).retrieve().body(JsonNode.class);
    }

    /** POST /api/extract/jobs → Job（含 jobId）。materials 为素材候选提取范围（null 表示不提取） */
    public JsonNode submitExtract(Long fileId, String fileExt, AiModelConfig cfg, Map<String, Object> materials) {
        Map<String, Object> body = new HashMap<>(Map.of("fileId", fileId, "fileExt", fileExt, "model", modelBody(cfg)));
        if (materials != null) {
            body.put("materials", materials);
        }
        return client.post().uri("/api/extract/jobs").body(body).retrieve().body(JsonNode.class);
    }

    /** POST /api/materials/expand：语义检索第 1 步，需求 → {ok, keywords, tags, categories} */
    public JsonNode expandMaterialQuery(String query, AiModelConfig cfg) {
        return client.post().uri("/api/materials/expand")
                .body(Map.of("query", query, "model", modelBody(cfg)))
                .retrieve().body(JsonNode.class);
    }

    /** POST /api/materials/rerank：语义检索第 2 步，对候选打分 → {ok, results: [{id, score, reason}]} */
    public JsonNode rerankMaterials(String query, List<Map<String, Object>> items, int limit, AiModelConfig cfg) {
        return client.post().uri("/api/materials/rerank")
                .body(Map.of("query", query, "items", items, "limit", limit, "model", modelBody(cfg)))
                .retrieve().body(JsonNode.class);
    }

    /** GET /api/extract/jobs/{jobId} → Job（状态、进度、结果） */
    public JsonNode getExtractJob(String jobId) {
        return client.get().uri("/api/extract/jobs/{id}", jobId).retrieve().body(JsonNode.class);
    }

    private Map<String, Object> modelBody(AiModelConfig cfg) {
        return Map.of(
                "baseUrl", cfg.getBaseUrl(),
                "apiKey", cfg.getApiKey() == null ? "" : cfg.getApiKey(),
                "model", cfg.getModel(),
                "concurrency", cfg.getConcurrency() == null ? 1 : cfg.getConcurrency());
    }
}
