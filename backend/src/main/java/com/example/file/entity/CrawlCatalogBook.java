package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 站点书目里的一本书（crawl_catalog_book 表）：简介 / 标签 / 目录概况，完整目录在 data/&lt;tocPath&gt;，正文不保存。
 */
@Data
@TableName(value = "crawl_catalog_book", autoResultMap = true)
public class CrawlCatalogBook {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long catalogId;
    private String bookName;
    private String author;
    /** 在哪个分类页找到的 */
    private String category;

    /** 站点上的标签（含分类） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> tags;
    /** AI 补的标签 */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> aiTags;

    private String intro;
    private String bookUrl;
    private String tocUrl;
    private Integer chapterCount;
    private String firstChapter;
    private String latestChapter;
    /** 目录 JSON，相对 data/ */
    private String tocPath;
    private Boolean tocOk;
    /** 首章正文抽检：true 合格 / false 不合格 / null 未抽检 */
    private Boolean contentOk;
    private Integer contentChars;
    private String error;

    /** 最近一次抓取（不入库，列表时按目录页地址关联 novel_crawl_book）：{status, fileId, crawlId, message} */
    @TableField(exist = false)
    private Map<String, Object> crawl;

    /** 目录还在后台补全中（不入库）：书目正在采集 / 补目录，且这本书还没取到目录、没出错 */
    @TableField(exist = false)
    private Boolean tocPending;

    /** AI 检索的相关度与理由（不入库） */
    @TableField(exist = false)
    private Integer score;
    @TableField(exist = false)
    private String reason;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
