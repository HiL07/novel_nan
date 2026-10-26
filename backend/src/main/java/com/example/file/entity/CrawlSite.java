package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 小说抓取页「小说网站爬取」里用户指定的网站（crawl_site 表），一个首页一行。
 */
@Data
@TableName("crawl_site")
public class CrawlSite {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 首页（新增时由任意站内地址归一而来） */
    private String homeUrl;
    private String host;
    private String name;
    /** 新增时填的原地址，可作为 AI 解析的样例书 */
    private String sampleUrl;
    private String note;

    /** 该站的 AI 解析规则概况（不入库）：{id, status, siteName, mastered, total, error}，没有解析过为 null */
    @TableField(exist = false)
    private Map<String, Object> rule;

    /** 该站的书目概况（不入库）：{id, decision, status, bookCount}，没有书目为 null */
    @TableField(exist = false)
    private Map<String, Object> catalog;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
