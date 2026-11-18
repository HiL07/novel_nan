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

/** 架空工作区（portable_workspace）：每次架空一个，勾选原素材加入待加工，逐条生成架空版 */
@Data
@TableName(value = "portable_workspace", autoResultMap = true)
public class PortableWorkspace {

    public static final String IDLE = "IDLE";
    public static final String RUNNING = "RUNNING";
    public static final String PAUSED = "PAUSED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String title;

    /** 示例世界（空 = 每条由 AI 选） */
    private String targetWorld;

    /** {source: api|gguf} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> model;

    /** 上次用的筛选条件 {category, sourceBook, keyword, tags} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> filter;

    private String status;

    private String message;

    /** 各状态条目数 {QUEUED, RUNNING, DONE, FAILED}（查询时填充） */
    @TableField(exist = false)
    private Map<String, Long> counts;

    /** 正在加工的原素材名（查询时填充） */
    @TableField(exist = false)
    private java.util.List<String> current;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
