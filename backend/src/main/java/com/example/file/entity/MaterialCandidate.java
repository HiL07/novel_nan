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
 * AI 提取出的素材候选（material_candidate），用户确认后才转为 Material。
 */
@Data
@TableName(value = "material_candidate", autoResultMap = true)
public class MaterialCandidate {

    public static final String PENDING = "PENDING";
    public static final String SAVED = "SAVED";
    public static final String IGNORED = "IGNORED";

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 来源提取任务 id（novel_extract） */
    private Long extractId;

    private Long fileId;

    private String fileName;

    /** 提取结果中的 candidateId（同一任务内唯一） */
    private String candidateKey;

    private String category;

    private String title;

    /** 候选内容：{category, subtype, title, summary, attributes, tags, excerpt, chapters} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> payload;

    /** PENDING / SAVED / IGNORED */
    private String status;

    /** 保存后对应的素材 id */
    private Long materialId;

    /** 库中已有同分类同名素材时的 id（仅查询时填充，提示可能重复） */
    @TableField(exist = false)
    private Long duplicateOf;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
