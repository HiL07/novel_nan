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
    private final RestClient longClient;

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
        // 书目「AI 读简介」：最多 1000 本分批调用模型，按并发数可能要几分钟
        SimpleClientHttpRequestFactory longFactory = new SimpleClientHttpRequestFactory();
        longFactory.setConnectTimeout(5000);
        longFactory.setReadTimeout(900000);
        this.longClient = RestClient.builder().baseUrl(aiServiceUrl).requestFactory(longFactory).build();
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

    /** GET /api/crawl/checkpoints/{key} → {code, data: {exists, url, bookName, chapterTotal, chapterSaved}} */
    public JsonNode crawlCheckpoint(String key) {
        return client.get().uri("/api/crawl/checkpoints/{key}", key).retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/ai/jobs：AI 解析地址（反复写规则 + 试抓），附带模型配置 → {code, data: AnalyzeJob} */
    public JsonNode submitCrawlAi(Map<String, Object> body, AiModelConfig cfg) {
        Map<String, Object> req = new HashMap<>(body);
        req.put("model", modelBody(cfg));
        return client.post().uri("/api/crawl/ai/jobs").body(req).retrieve().body(JsonNode.class);
    }

    /** GET /api/crawl/ai/jobs/{jobId} → {code, data: AnalyzeJob（attempts[], result）} */
    public JsonNode getCrawlAiJob(String jobId) {
        return client.get().uri("/api/crawl/ai/jobs/{id}", jobId).retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/ai/jobs/{jobId}/cancel */
    public JsonNode cancelCrawlAiJob(String jobId) {
        return client.post().uri("/api/crawl/ai/jobs/{id}/cancel", jobId).retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/catalog/jobs：全自动爬虫书目采集（按学到的规律找书、取简介 / 标签 / 目录、抽检正文）→ {code, data: CatalogJob} */
    public JsonNode submitCatalog(Map<String, Object> body) {
        return client.post().uri("/api/crawl/catalog/jobs").body(body).retrieve().body(JsonNode.class);
    }

    /** GET /api/crawl/catalog/jobs/{jobId}?since=N → {code, data: 状态 + 第 N 本之后的书目 + report} */
    public JsonNode getCatalogJob(String jobId, int since) {
        return client.get().uri("/api/crawl/catalog/jobs/{id}?since={since}", jobId, since).retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/catalog/jobs/{jobId}/cancel */
    public void cancelCatalogJob(String jobId) {
        client.post().uri("/api/crawl/catalog/jobs/{id}/cancel", jobId).retrieve().toBodilessEntity();
    }

    /** POST /api/crawl/catalog/plot-tags：按情节找书（省 token），从已有标签里挑 → {code, data: {tags, suggested, reason, usage}} */
    public JsonNode catalogPlotTags(String query, List<String> vocabulary, AiModelConfig cfg) {
        return slowClient.post().uri("/api/crawl/catalog/plot-tags")
                .body(Map.of("query", query, "vocabulary", vocabulary, "model", modelBody(cfg)))
                .retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/catalog/intro-match：按情节找书（耗 token），分批逐本读简介打分，最多 1000 本，单独放宽到 15 分钟 */
    public JsonNode catalogIntroMatch(String query, List<Map<String, Object>> items, int threshold, AiModelConfig cfg) {
        return longClient.post().uri("/api/crawl/catalog/intro-match")
                .body(Map.of("query", query, "items", items, "threshold", threshold, "model", modelBody(cfg)))
                .retrieve().body(JsonNode.class);
    }

    /** POST /api/crawl/catalog/tag：AI 补标签 → {code, data: [{id, tags[]}]} */
    public JsonNode catalogTag(List<Map<String, Object>> items, List<String> vocabulary, AiModelConfig cfg) {
        return slowClient.post().uri("/api/crawl/catalog/tag")
                .body(Map.of("items", items, "vocabulary", vocabulary, "model", modelBody(cfg)))
                .retrieve().body(JsonNode.class);
    }

    /** POST /api/gen/novels/{id}/chapters：大模型工作区开始生成下一章，附带 api（模型配置） */
    public JsonNode startGenChapter(String novelId, Map<String, Object> body, AiModelConfig cfg) {
        Map<String, Object> req = new HashMap<>(body);
        req.put("api", modelBody(cfg));
        return client.post().uri("/api/gen/novels/{id}/chapters", novelId).body(req).retrieve().body(JsonNode.class);
    }

    /** POST /api/gen/novels/{id}/ideas：AI 构思（书名 / 大纲 / 下一章），一次长输出，用慢客户端。
     *  cfg 为 null 时 body 应含 local（本地模型），不附带大模型配置 */
    public JsonNode genIdeas(String novelId, Map<String, Object> body, AiModelConfig cfg) {
        Map<String, Object> req = new HashMap<>(body);
        if (cfg != null) {
            req.put("api", modelBody(cfg));
        }
        return slowClient.post().uri("/api/gen/novels/{id}/ideas", novelId).body(req).retrieve().body(JsonNode.class);
    }

    private Map<String, Object> modelBody(AiModelConfig cfg) {
        return Map.of(
                "baseUrl", cfg.getBaseUrl(),
                "apiKey", cfg.getApiKey() == null ? "" : cfg.getApiKey(),
                "model", cfg.getModel(),
                "concurrency", cfg.getConcurrency() == null ? 1 : cfg.getConcurrency());
    }
}
