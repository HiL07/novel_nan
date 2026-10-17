package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 模型配置（OpenAI 兼容接口），对应 SQLite ai_model_config 表。
 * 只有验证通过（VERIFIED）的配置才能启用；同一时间只有一个启用（active）的配置用于小说提取。
 */
@Data
@TableName("ai_model_config")
public class AiModelConfig {

    public static final String UNVERIFIED = "UNVERIFIED";
    public static final String VERIFIED = "VERIFIED";
    public static final String FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 显示名称，如「DeepSeek（默认）」 */
    private String name;

    /** OpenAI 兼容根地址，请求 {baseUrl}/chat/completions，如 https://api.deepseek.com */
    private String baseUrl;

    /** 模型名，如 deepseek-chat */
    private String model;

    /** API Key：只写不读，接口永不返回明文（见 getApiKeyMasked） */
    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    private String apiKey;

    /** 单个提取任务内的并发请求数（1~8，本地模型用 1） */
    private Integer concurrency;

    /** 验证状态：UNVERIFIED / VERIFIED / FAILED */
    private String status;

    /** 最近一次验证结果说明 */
    private String verifyMessage;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime verifiedTime;

    /** 是否为当前启用的配置 */
    private Boolean active;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;

    /** 脱敏后的 Key，如 sk-1****caf9（仅用于展示） */
    @JsonProperty(access = JsonProperty.Access.READ_ONLY)
    public String getApiKeyMasked() {
        if (apiKey == null || apiKey.isEmpty()) {
            return "";
        }
        if (apiKey.length() <= 8) {
            return "****";
        }
        return apiKey.substring(0, 4) + "****" + apiKey.substring(apiKey.length() - 4);
    }
}
