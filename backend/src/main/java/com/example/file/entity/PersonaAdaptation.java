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
 * 原型卡在某个世界观下的适配版本（persona_adaptation）。改它不会碰原型卡。
 */
@Data
@TableName(value = "persona_adaptation", autoResultMap = true)
public class PersonaAdaptation {

    public static final String DRAFT = "DRAFT";
    public static final String CONFIRMED = "CONFIRMED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long cardId;

    private Integer baseVersion;

    private String name;

    private String novelId;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> content;

    /** DRAFT / CONFIRMED */
    private String status;

    /** [{novelId, version, at}] */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> applied;

    /** 辨识度测试报告（最近 10 次，新的在前） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> tests;

    private String testStatus;

    private Integer testProgress;

    private String testMessage;

    private String testJobId;

    /** 列表：原型已有更新的版本（不是数据库列） */
    @TableField(exist = false)
    private Boolean prototypeUpdated;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
