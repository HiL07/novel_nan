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
 * 跨世界观角色卡的原型卡（persona_card）。内容在版本表里（只追加），这里只有元数据和提取任务状态。
 */
@Data
@TableName(value = "persona_card", autoResultMap = true)
public class PersonaCard {

    public static final String EXTRACTING = "EXTRACTING";
    public static final String INTERRUPTED = "INTERRUPTED";
    public static final String READY = "READY";
    public static final String FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> aliases;

    /** {type: text|file|extract, fileIds?, extractId?, entityKey?, whole, textChars} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> source;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> tags;

    private String kind;

    private String summary;

    private Integer currentVersion;

    /** EXTRACTING / INTERRUPTED / READY / FAILED */
    private String status;

    private Integer progress;

    private String message;

    private String jobId;

    /** 提取参数 JSON（继续时复用，不含密钥） */
    private String options;

    /** 详情：当前版本内容（不是数据库列） */
    @TableField(exist = false)
    private Map<String, Object> content;

    /** 列表 / 详情：版本数、适配版本数（不是数据库列） */
    @TableField(exist = false)
    private Long versionCount;

    @TableField(exist = false)
    private Long adaptationCount;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
