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
 * 全自动爬虫的站点书目（crawl_site_catalog 表），一个站点首页一行：按学到的规律测试 → 用户决定是否使用 →
 * 扩充书目、筛选、抓取。书目里的书在 crawl_catalog_book，目录文件在 data/&lt;catalogDir&gt;/toc/。
 */
@Data
@TableName(value = "crawl_site_catalog", autoResultMap = true)
public class CrawlSiteCatalog {

    public static final String PENDING = "PENDING";
    public static final String USED = "USED";
    public static final String REJECTED = "REJECTED";

    public static final String IDLE = "IDLE";
    public static final String RUNNING = "RUNNING";
    public static final String SUCCEEDED = "SUCCEEDED";
    public static final String FAILED = "FAILED";
    public static final String CANCELLED = "CANCELLED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String host;
    /** 站点首页（同一首页的书目保存在一起） */
    private String homeUrl;
    private String siteName;
    /** 使用的站点规则 crawl_site_rule.id */
    private Long ruleId;
    /** 相对 data/ 的目录，如 site-catalog/www.example.com */
    private String catalogDir;

    /** PENDING 待决定 / USED 使用 / REJECTED 不使用 */
    private String decision;
    /** 最近一次采集的状态 */
    private String status;
    /** test 测试 / scan 扩充书目 */
    private String phase;
    private String jobId;
    private Integer progress;
    private String message;

    /** 最近一次「测试」的报告（见 python-service/app/crawler/catalog.py#_report） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> report;
    /** 最近一次采集（测试或扩充）的报告 */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> lastReport;

    private Integer bookCount;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime lastScanTime;

    /** 规则概况（不入库）：{id, status, siteName, summary, bookUrlPattern}，规则已删除时为 null */
    @TableField(exist = false)
    private Map<String, Object> rule;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
