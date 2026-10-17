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
 * 创作素材（只保存用户确认过的），对应 SQLite material 表。
 * attributes 的键与前端设定模板的字段名一致（如 外形 / 能力 / 弱点），便于应用到写作设定。
 */
@Data
@TableName(value = "material", autoResultMap = true)
public class Material {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 分类代码：world / faction / character / monster / location / item / plot */
    private String category;

    /** 细分类型（自由填写），如 势力 / 修炼体系 / 桥段 */
    private String subtype;

    private String title;

    /** 一句话概括（列表与检索展示） */
    private String summary;

    /** 结构化属性：{"外形": "…", "弱点": ["火"]} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> attributes;

    /** 详细描述 / 备注 */
    private String detail;

    /** 标签（检索走 material_tag 索引表） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> tags;

    /** 来源：{type: extract|manual, extractId, fileId, fileName, chapters, excerpt} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> source;

    /** 被应用到工作区的次数 */
    private Integer useCount;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
