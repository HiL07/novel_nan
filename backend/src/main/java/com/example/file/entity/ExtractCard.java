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
 * 卡片（extract_card）：一个提取工作区的整理成果，属于工作区、不是素材；在「素材选择」里挑过才写进 material。
 */
@Data
@TableName(value = "extract_card", autoResultMap = true)
public class ExtractCard {

    public static final String NEW = "NEW";
    public static final String SAVED = "SAVED";
    public static final String SKIPPED = "SKIPPED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long extractId;

    /** 工作区内唯一（实体卡 = 实体键的哈希），重新整理时对上同一张 */
    private String cardKey;

    /** entity / system / arc / craft / world */
    private String kind;

    /** 素材分类码 */
    private String category;

    private String title;

    /** 卡片内容（summary / subtype / detail / attributes / tags / facts / chapters / tier / bookPos / entityKey …） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> data;

    /** 旧版本 [{version, by, time, data}]（最多 5 个） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> history;

    private Integer version;

    /** 手改过：重新整理不覆盖 */
    private Boolean edited;

    /** NEW / SAVED / SKIPPED */
    private String status;

    private Long materialId;

    private Integer savedVersion;

    private Long compileId;

    /** 素材库里这本书的同分类同名素材（查询时填充）：{id, title, fromThisCard} */
    @TableField(exist = false)
    private Map<String, Object> match;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
