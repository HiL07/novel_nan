package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 整理卡片任务：对一次小说提取的实体档案单独发起，产出的素材卡 / 剧情段进入待确认候选，对应 SQLite material_compile 表。
 * 状态与提取任务相同（见 {@link NovelExtract}）：出错 / 重启 / 暂停 = INTERRUPTED（可继续或取消），取消 = FAILED。
 */
@Data
@TableName("material_compile")
public class MaterialCompile {

    /** 主键（自增） */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 来源提取任务 id（novel_extract） */
    private Long extractId;

    /** 状态：QUEUED / RUNNING / INTERRUPTED / SUCCEEDED / FAILED */
    private String status;

    /** 进度 0~100 */
    private Integer progress;

    /** 进度说明 / 失败原因 */
    private String message;

    /** Python 服务侧的任务 id */
    private String jobId;

    /** 参数 JSON {model, entityKeys?, categories?, topN?, plot}（不含密钥），继续时复用 */
    private String options;

    /** 交给模型整理的实体数 / 素材卡（含体系卡）/ 剧情段 / 实际进入待确认的条数 */
    private Integer entityCount;
    private Integer cardCount;
    private Integer arcCount;
    private Integer candidateCount;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
