package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 整站抓取任务下的一本书（novel_crawl_book 表）。整站任务按「一本一个 txt」逐本抓取，
 * 每本对应一行：进度、章节统计、失败的 Python job、成功后的 fileId。
 */
@Data
@TableName("novel_crawl_book")
public class NovelCrawlBook {

    public static final String QUEUED = "QUEUED";
    public static final String RUNNING = "RUNNING";
    public static final String SUCCEEDED = "SUCCEEDED";
    public static final String FAILED = "FAILED";
    public static final String CANCELLED = "CANCELLED";

    /** 主键（自增） */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 所属整站任务（novel_crawl.id） */
    private Long crawlId;

    private String bookName;
    private String author;
    private String category;

    /** 目录页地址（真正抓取的入口，来自书籍详情页的「开始阅读」链接或详情页本身） */
    private String tocUrl;

    /** 状态：QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELLED */
    private String status;

    /** 进度 0~100 */
    private Integer progress;

    /** 进度说明 / 失败原因 */
    private String message;

    /** Python 服务侧的任务 id（每本书一个新任务） */
    private String jobId;

    private Integer chapterTotal;
    private Integer chapterDone;
    private Integer chapterFailed;
    private Integer wordCount;

    /** 成功后生成的 txt 文件 id（file 表） */
    private Long fileId;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
