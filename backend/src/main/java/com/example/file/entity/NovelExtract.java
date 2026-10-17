package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 小说提取任务 + 结果，对应 SQLite novel_extract 表。
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

    /** 完整结果 JSON 文件相对 data/ 的路径（如 extract-results/12.json），结果本身不入库 */
    private String resultPath;

    /** 结果文件字节数 */
    private Long resultSize;

    /** 结果文件 SHA-256（读取时校验） */
    @JsonIgnore
    private String resultSha256;

    /** 统计：总字数 / 章节数 / 素材候选数 */
    private Integer wordCount;
    private Integer chapterCount;
    private Integer candidateCount;

    /** 提取结果 JSON 字符串：详情接口从 resultPath 文件读出后填入（不是数据库列），保持原接口结构 */
    @TableField(exist = false)
    private String result;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
