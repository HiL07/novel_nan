package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonRawValue;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 网络小说抓取任务，对应 SQLite novel_crawl 表。全文不入库：成功后存为文件管理中的 txt（fileId）。
 *
 * 两种采集模式（模式记在 options.mode，不额外占表列）：
 * - book：一本书的目录页 → 一个 txt；
 * - site：站点首页 / 分类页 → discover 出书籍清单 → 每本一个 txt（明细见 novel_crawl_book）。
 */
@Data
@TableName("novel_crawl")
public class NovelCrawl {

    public static final String QUEUED = "QUEUED";
    public static final String RUNNING = "RUNNING";
    public static final String SUCCEEDED = "SUCCEEDED";
    public static final String FAILED = "FAILED";
    public static final String CANCELLED = "CANCELLED";

    /** 采集模式：单本（目录页）/ 整站（copybook 式：分类 → 所有书） */
    public static final String MODE_BOOK = "book";
    public static final String MODE_SITE = "site";

    /** 主键（自增） */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 目录页地址 */
    private String url;

    /** 规则预设 key（Python 解析后的实际预设） */
    private String preset;

    /** 抓取参数 JSON（原样返回给前端，重新抓取时复用） */
    @JsonRawValue
    private String options;

    private String bookName;
    private String author;

    /** 状态：QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELLED */
    private String status;

    /** 进度 0~100 */
    private Integer progress;

    /** 进度说明 / 失败原因 */
    private String message;

    /** Python 服务侧的任务 id */
    private String jobId;

    /** 统计：范围内章节数 / 已处理 / 失败（留占位） / 正文字数 */
    private Integer chapterTotal;
    private Integer chapterDone;
    private Integer chapterFailed;
    private Integer wordCount;

    /** 成功后生成的 txt 文件 id（file 表）；整站模式见 novel_crawl_book.file_id */
    private Long fileId;

    // ---------------- 以下字段不入库，由 Service 填充（options.mode / novel_crawl_book 汇总） ----------------

    /** 采集模式：book / site */
    @TableField(exist = false)
    private String mode;

    /** 整站模式：书籍总数 / 已完成 / 失败 */
    @TableField(exist = false)
    private Integer bookTotal;
    @TableField(exist = false)
    private Integer bookDone;
    @TableField(exist = false)
    private Integer bookFailed;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
