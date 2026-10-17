package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 小说提取任务 + 结果，对应 test10000.novel_extract 表。
 */
@Data
@TableName("novel_extract")
public class NovelExtract {

    public static final String QUEUED = "QUEUED";
    public static final String RUNNING = "RUNNING";
    public static final String SUCCEEDED = "SUCCEEDED";
    public static final String FAILED = "FAILED";

    /** 主键（自增） */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 源文件 id（file 表） */
    private Long fileId;

    /** 源文件名（冗余，便于列表展示） */
    private String fileName;

    /** 状态：QUEUED / RUNNING / SUCCEEDED / FAILED */
    private String status;

    /** 进度 0~100 */
    private Integer progress;

    /** 进度说明 / 失败原因 */
    private String message;

    /** Python 服务侧的任务 id */
    private String jobId;

    /** 提取结果 JSON（章节、人物、文风） */
    private String result;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
