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
 * AI 解析地址学到的站点抓取规则（crawl_site_rule 表）：每个域名一行，
 * 抓取时规则选「按域名自动选择」即自动套用。
 */
@Data
@TableName(value = "crawl_site_rule", autoResultMap = true)
public class CrawlSiteRule {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 域名（小写） */
    private String host;
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

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
