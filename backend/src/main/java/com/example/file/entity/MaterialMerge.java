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
 * 精炼 / 合并建议：本地向量模型找出的一组相似素材（同分类），可让 AI 写合并稿，用户确认后才合并，对应 material_merge 表。
 */
@Data
@TableName(value = "material_merge", autoResultMap = true)
public class MaterialMerge {

    public static final String FOUND = "FOUND";
    public static final String DRAFTING = "DRAFTING";
    public static final String DRAFTED = "DRAFTED";
    public static final String APPLIED = "APPLIED";
    public static final String IGNORED = "IGNORED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String category;

    /** 组内素材 id（升序）。JSON 列反序列化出来是 Integer，用 {@link #ids()} 取 Long */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Number> memberIds;

    /** 组内平均相似度（余弦） */
    private Double score;

    /** 成员来自不同的书 */
    private Boolean crossBook;

    /** FOUND / DRAFTING / DRAFTED / APPLIED / IGNORED */
    private String status;

    /** AI 合并稿 {same, title, subtype, summary, detail, attributes, tags, variants: {id: 写法}, model} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> draft;

    private String message;

    /** 合并后的主条目 id */
    private Long materialId;

    /** 列表：成员素材（不是数据库列；已删除的不在里面） */
    @TableField(exist = false)
    private List<Material> members;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;

    /** 成员 id（Long） */
    public List<Long> ids() {
        return memberIds == null ? List.of() : memberIds.stream().map(Number::longValue).toList();
    }
}
