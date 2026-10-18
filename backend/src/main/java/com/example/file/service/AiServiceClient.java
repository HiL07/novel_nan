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
 * Python AI 服务（python-service）的 HTTP 客户端：模型验证、提交 / 查询提取任务、网络小说抓取。
 * 模型配置（含 API Key）随请求下发，Python 端不保存。
 */
@Component
public class AiServiceClient {

    private final RestClient client;
    private final RestClient slowClient;
    private final RestClient discoverClient;

    public AiServiceClient(@Value("${ai.service.url}") String aiServiceUrl) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        // 验证会真实调用一次远程模型，留足时间
        factory.setReadTimeout(60000);
        this.client = RestClient.builder().baseUrl(aiServiceUrl).requestFactory(factory).build();
        // 抓取预览要访问外部站点（目录可能分多页），取全文可能数 MB
        SimpleClientHttpRequestFactory slowFactory = new SimpleClientHttpRequestFactory();
        slowFactory.setConnectTimeout(5000);
        slowFactory.setReadTimeout(180000);
        this.slowClient = RestClient.builder().baseUrl(aiServiceUrl).requestFactory(slowFactory).build();
        // 整站发现要逐页访问分类列表 + 每本书的详情 / 目录（最多 120 本），单独放宽到 5 分钟
        SimpleClientHttpRequestFactory discoverFactory = new SimpleClientHttpRequestFactory();
        discoverFactory.setConnectTimeout(5000);
        discoverFactory.setReadTimeout(300000);
        this.discoverClient = RestClient.builder().baseUrl(aiServiceUrl).requestFactory(discoverFactory).build();
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

    /** GET /api/crawl/presets → {code, data: [{key, name, description, domains, rule}]} */
    public JsonNode crawlPresets() {
        return client.get().uri("/api/crawl/presets").retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/preview：解析目录（含分页）+ 试抓第一章，目录分页多时较慢 → {code, data} */
    public JsonNode crawlPreview(Map<String, Object> options) {
        return slowClient.post().uri("/api/crawl/preview").body(options).retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/discover：整站发现（首页 → 分类 → 列表翻页 → 书籍 → 目录），逐页抓取较慢 → {code, data} */
    public JsonNode crawlDiscover(Map<String, Object> options) {
        return discoverClient.post().uri("/api/crawl/discover").body(options).retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/jobs → {code, data: CrawlJob（含 jobId）} */
    public JsonNode submitCrawl(Map<String, Object> request) {
        return client.post().uri("/api/crawl/jobs").body(request).retrieve().body(JsonNode.class);
    }

    /** GET /api/crawl/jobs/{jobId} → {code, data: CrawlJob} */
    public JsonNode getCrawlJob(String jobId) {
        return client.get().uri("/api/crawl/jobs/{id}", jobId).retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/jobs/{jobId}/cancel */
    public void cancelCrawl(String jobId) {
        client.post().uri("/api/crawl/jobs/{id}/cancel", jobId).retrieve().toBodilessEntity();
    }

    /** GET /api/crawl/jobs/{jobId}/text → UTF-8 全文字节 */
    public byte[] getCrawlText(String jobId) {
        return slowClient.get().uri("/api/crawl/jobs/{id}/text", jobId).retrieve().body(byte[].class);
    }

    /** POST /api/crawl/jobs/{jobId}/release：全文已保存，释放 Python 内存 */
    public void releaseCrawl(String jobId) {
        client.post().uri("/api/crawl/jobs/{id}/release", jobId).retrieve().toBodilessEntity();
    }

    private Map<String, Object> modelBody(AiModelConfig cfg) {
        return Map.of(
                "baseUrl", cfg.getBaseUrl(),
                "apiKey", cfg.getApiKey() == null ? "" : cfg.getApiKey(),
                "model", cfg.getModel(),
                "concurrency", cfg.getConcurrency() == null ? 1 : cfg.getConcurrency());
    }
}
