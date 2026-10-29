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
 * 灵感墙上的一项：收藏的思路（type = idea）或钉的素材（type = material）。
 */
@Data
@TableName(value = "inspiration_item", autoResultMap = true)
public class InspirationItem {

    public static final String IDEA = "idea";
    public static final String MATERIAL = "material";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long wallId;

    /** idea / material */
    private String type;

    /** type = material：钉的素材 id */
    private Long materialId;

    private String title;

    /** 思路内容 {pitch, sections, elements, twist, questions, detail, history, target} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> content;

    /** 来源素材 [{materialId, title, book, variant?}] */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> sources;

    private String note;

    private Integer sort;

    /** type = material：素材本身（列表接口填充，不是数据库列） */
    @TableField(exist = false)
    private Material material;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
