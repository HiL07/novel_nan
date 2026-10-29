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
 * 一次构思记录：需求、拆解结果、用到的素材、生成的思路（细化 / 修改后可以更新）。
 */
@Data
@TableName(value = "inspiration_run", autoResultMap = true)
public class InspirationRun {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long wallId;

    /** {request, target, conditions, count, model} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> request;

    /** {summary, needs, explore} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> plan;

    /** [{materialId, title, book, category, variant, need}] */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> materials;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> ideas;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> usage;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;
}
