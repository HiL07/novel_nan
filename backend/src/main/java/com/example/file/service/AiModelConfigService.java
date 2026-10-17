package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
import com.example.file.mapper.AiModelConfigMapper;
import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Objects;

/**
 * AI 模型配置：增删改查 + 验证 + 启用。
 * 规则：新增或修改了地址 / 模型 / Key 的配置变为「未验证」且停用；只有验证通过的配置能启用；
 * 同一时间只有一个启用配置，小说提取只使用它。
 */
@Service
public class AiModelConfigService {

    private static final Logger log = LoggerFactory.getLogger(AiModelConfigService.class);

    private final AiModelConfigMapper mapper;
    private final AiServiceClient aiClient;

    private final String defaultName;
    private final String defaultBaseUrl;
    private final String defaultModel;
    private final String defaultApiKey;

    public AiModelConfigService(AiModelConfigMapper mapper,
                                AiServiceClient aiClient,
                                @Value("${ai.default.name}") String defaultName,
                                @Value("${ai.default.base-url}") String defaultBaseUrl,
                                @Value("${ai.default.model}") String defaultModel,
                                @Value("${ai.default.api-key:}") String defaultApiKey) {
        this.mapper = mapper;
        this.aiClient = aiClient;
        this.defaultName = defaultName;
        this.defaultBaseUrl = defaultBaseUrl;
        this.defaultModel = defaultModel;
        this.defaultApiKey = defaultApiKey;
    }

    /**
     * 首次启动（表为空）且配置了默认 Key 时，写入默认 DeepSeek 配置，并在后台尝试验证（Python 服务可能稍后才启动）。
     */
    @EventListener(ApplicationReadyEvent.class)
    public void seedDefault() {
        if (mapper.selectCount(null) > 0 || defaultApiKey.isBlank()) {
            return;
        }
        AiModelConfig cfg = new AiModelConfig();
        cfg.setName(defaultName);
        cfg.setBaseUrl(defaultBaseUrl);
        cfg.setModel(defaultModel);
        cfg.setApiKey(defaultApiKey.trim());
        cfg.setConcurrency(4);
        cfg.setStatus(AiModelConfig.UNVERIFIED);
        cfg.setVerifyMessage("默认配置，等待验证");
        cfg.setActive(false);
        cfg.setCreateTime(LocalDateTime.now());
        cfg.setUpdateTime(cfg.getCreateTime());
        mapper.insert(cfg);
        log.info("已写入默认模型配置：{} / {}", defaultBaseUrl, defaultModel);

        Thread t = new Thread(() -> autoVerify(cfg.getId()), "model-auto-verify");
        t.setDaemon(true);
        t.start();
    }

    private void autoVerify(Long id) {
        for (int i = 0; i < 12; i++) {
            try {
                AiModelConfig result = verify(id);
                log.info("默认模型配置自动验证：{} {}", result.getStatus(), result.getVerifyMessage());
                return;
            } catch (BizException e) {
                // AI 服务尚未启动，稍后重试
            }
            try {
                Thread.sleep(10_000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        log.warn("默认模型配置自动验证未完成（AI 服务不可达），请在「模型配置」页手动验证");
    }

    public List<AiModelConfig> list() {
        return mapper.selectList(new LambdaQueryWrapper<AiModelConfig>()
                .orderByDesc(AiModelConfig::getActive)
                .orderByDesc(AiModelConfig::getCreateTime));
    }

    public AiModelConfig getById(Long id) {
        AiModelConfig cfg = mapper.selectById(id);
        if (cfg == null) {
            throw new BizException(404, "模型配置不存在：" + id);
        }
        return cfg;
    }

    /**
     * 新增（id 为空）或修改。修改时 apiKey 留空表示保持原值。
     */
    public AiModelConfig save(AiModelConfig req) {
        String name = trim(req.getName());
        String baseUrl = trim(req.getBaseUrl());
        String model = trim(req.getModel());
        String apiKey = trim(req.getApiKey());
        int concurrency = req.getConcurrency() == null ? 1 : req.getConcurrency();
        if (name.isEmpty() || model.isEmpty()) {
            throw new BizException(400, "名称和模型名不能为空");
        }
        if (!baseUrl.matches("(?i)https?://\\S+")) {
            throw new BizException(400, "接口地址需以 http:// 或 https:// 开头");
        }
        if (concurrency < 1 || concurrency > 8) {
            throw new BizException(400, "并发数需在 1~8 之间");
        }
        baseUrl = baseUrl.replaceAll("/+$", "");
        LocalDateTime now = LocalDateTime.now();

        if (req.getId() == null) {
            AiModelConfig cfg = new AiModelConfig();
            cfg.setName(name);
            cfg.setBaseUrl(baseUrl);
            cfg.setModel(model);
            cfg.setApiKey(apiKey);
            cfg.setConcurrency(concurrency);
            cfg.setStatus(AiModelConfig.UNVERIFIED);
            cfg.setVerifyMessage("新配置，需验证后才能启用");
            cfg.setActive(false);
            cfg.setCreateTime(now);
            cfg.setUpdateTime(now);
            mapper.insert(cfg);
            return cfg;
        }

        AiModelConfig cfg = getById(req.getId());
        boolean keyChanged = !apiKey.isEmpty() && !apiKey.equals(cfg.getApiKey());
        boolean needVerify = keyChanged
                || !baseUrl.equals(cfg.getBaseUrl())
                || !model.equals(cfg.getModel());
        cfg.setName(name);
        cfg.setBaseUrl(baseUrl);
        cfg.setModel(model);
        if (keyChanged) {
            cfg.setApiKey(apiKey);
        }
        cfg.setConcurrency(concurrency);
        if (needVerify) {
            cfg.setStatus(AiModelConfig.UNVERIFIED);
            cfg.setVerifyMessage("配置已修改，需重新验证后才能启用");
            cfg.setActive(false);
        }
        cfg.setUpdateTime(now);
        mapper.updateById(cfg);
        return cfg;
    }

    /**
     * 验证：由 Python 服务向模型真实发送一次极小请求。通过则 VERIFIED（若当前没有启用的配置则自动启用），
     * 失败则 FAILED 并停用。AI 服务不可达时抛 503，不改变配置状态。
     */
    public AiModelConfig verify(Long id) {
        AiModelConfig cfg = getById(id);
        boolean ok;
        String message;
        try {
            JsonNode res = aiClient.verifyModel(cfg);
            ok = res != null && res.path("ok").asBoolean(false);
            message = res == null ? "AI 服务无响应" : res.path("message").asText("");
        } catch (ResourceAccessException e) {
            throw new BizException(503, "AI 服务不可达，请确认 python-service 已启动");
        } catch (RestClientResponseException e) {
            // 不记录响应体：校验错误的回显里可能带有 API Key
            log.warn("模型验证请求被 AI 服务拒绝，id={}，HTTP {}", id, e.getStatusCode().value());
            ok = false;
            message = "配置格式不正确，AI 服务拒绝验证（HTTP " + e.getStatusCode().value() + "）";
        }
        LocalDateTime now = LocalDateTime.now();

        LambdaUpdateWrapper<AiModelConfig> update = new LambdaUpdateWrapper<AiModelConfig>()
                .eq(AiModelConfig::getId, id)
                .set(AiModelConfig::getStatus, ok ? AiModelConfig.VERIFIED : AiModelConfig.FAILED)
                .set(AiModelConfig::getVerifyMessage, truncate(message, 1000))
                .set(AiModelConfig::getUpdateTime, now);
        if (ok) {
            update.set(AiModelConfig::getVerifiedTime, now);
        } else {
            update.set(AiModelConfig::getActive, false);
        }
        mapper.update(null, update);

        if (ok && findActive() == null) {
            activate(id);
        }
        return getById(id);
    }

    /**
     * 启用：仅限验证通过的配置；其余配置全部停用。
     */
    @Transactional
    public AiModelConfig activate(Long id) {
        AiModelConfig cfg = getById(id);
        if (!AiModelConfig.VERIFIED.equals(cfg.getStatus())) {
            throw new BizException(400, "该模型配置尚未通过验证，不能启用");
        }
        mapper.update(null, new LambdaUpdateWrapper<AiModelConfig>()
                .ne(AiModelConfig::getId, id)
                .set(AiModelConfig::getActive, false));
        mapper.update(null, new LambdaUpdateWrapper<AiModelConfig>()
                .eq(AiModelConfig::getId, id)
                .set(AiModelConfig::getActive, true)
                .set(AiModelConfig::getUpdateTime, LocalDateTime.now()));
        return getById(id);
    }

    public void delete(Long id) {
        getById(id);
        mapper.deleteById(id);
    }

    /**
     * 小说提取使用的配置：启用且已验证；没有则抛业务异常提示去配置。
     */
    public AiModelConfig requireActive() {
        AiModelConfig cfg = findActive();
        if (cfg == null) {
            throw new BizException(400, "没有可用的模型：请先在「模型配置」中添加模型并验证通过");
        }
        return cfg;
    }

    private AiModelConfig findActive() {
        return mapper.selectOne(new LambdaQueryWrapper<AiModelConfig>()
                .eq(AiModelConfig::getActive, true)
                .eq(AiModelConfig::getStatus, AiModelConfig.VERIFIED)
                .last("LIMIT 1"));
    }

    private static String trim(String s) {
        return s == null ? "" : s.trim();
    }

    private static String truncate(String s, int max) {
        return Objects.requireNonNullElse(s, "").length() > max ? s.substring(0, max) : s;
    }
}
