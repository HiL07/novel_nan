package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * AI 解析地址的记录（crawl_site_rule 表）：AI 解析成功先存为待确认，
 * 用户确认后，抓取时规则选「按域名自动选择」即自动套用。每个域名最多一条已确认 + 一条待确认；
 * 解析失败的也存一条 FAILED（只作记录，不能确认、不会套用），解析管理里可以看失败原因与每次尝试。
 */
@Data
@TableName(value = "crawl_site_rule", autoResultMap = true)
public class CrawlSiteRule {

    public static final String PENDING = "PENDING";
    public static final String CONFIRMED = "CONFIRMED";
    public static final String FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 域名（小写） */
    private String host;
    /** 站点根地址（首页），如 https://www.example.com/ */
    private String homeUrl;
    private String siteName;
    /** 规则基于的内置预设 key */
    private String preset;

    /** XPath 规则（Python CrawlRule 的非空字段），空 Map = 内置规则即可 */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> rule;

    /** 大模型总结的地址规律与规则说明 */
    private String summary;
    private String bookUrlPattern;
    private String tocUrlPattern;
    private String chapterUrlPattern;

    /** 学习时输入的书籍地址 / 实际使用的目录页 */
    private String sampleUrl;
    private String tocUrl;
    private String bookName;

    /** 哪种尝试成功：learned / preset / ai */
    private String strategy;
    /** 第几次尝试成功 */
    private Integer attempts;
    private Integer chapterCount;

    /**
     * 站点结构实测：{homeUrl, siteName, items:[{key, label, status: ok|partial|failed|na|skipped, pattern, example, detail}],
     * mastered, failed, total, otherBooks[], categories[]}（见 python-service/app/crawler/ai_rules.py#_explore）
     */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> siteMap;

    /** PENDING 待确认 / CONFIRMED 已确认（只有已确认的规则会按域名自动套用）/ FAILED 解析失败 */
    private String status;

    /** 解析失败的原因（FAILED） */
    private String error;

    /**
     * 解析过程：{attempts:[{index, strategy, reason, tocUrl, rule, ok, chapterCount, sampleChars, error, seconds,
     * promptTokens, completionTokens}], usage, message, sample{title, chars, text}, chapterTitles[]}；老记录为 null
     */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> attemptLog;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime confirmTime;

    /** 规则 JSON 文件（相对 data/，不入库） */
    @TableField(exist = false)
    private String ruleFile;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
