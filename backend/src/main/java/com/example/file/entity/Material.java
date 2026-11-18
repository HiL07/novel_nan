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

    /** 来源书名（提取素材 = 文件名去扩展名；手动添加可自填，空 = 手动）。用于按书筛选 / 屏蔽 / 删除 */
    private String sourceBook;

    /** 保留：按来源书删除、在 AI 生成中屏蔽来源书时，保留的素材都不受影响 */
    private Boolean pinned;

    /** 已并入的主条目 id（精炼 / 合并）；非空 = 不出现在列表 / 检索 / AI 里，拆分时清空 */
    private Long mergedInto;

    /**
     * 量级等画像：{tier 1–5（1 个人 / 街头，2 地方，3 一国 / 大宗门，4 大陆 / 天下，5 神明 / 世界之外）, tierReason,
     * tierBy ai|user（user = 作者手改过，AI 重新标注不覆盖）, bookPos 0–1（首次出现在原书的位置，代码算）}
     */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> profile;

    /** 主条目（source.type = merge）的成员素材：详情接口填充（不是数据库列） */
    @TableField(exist = false)
    private List<Material> members;

    /**
     * 架空版（2026-11-06）：原素材 → 它在各架空工作区的架空版 [{id, title, workspaceId, workspaceTitle}]；
     * 架空版（source.type = portable）→ originState 原素材是否还在 / 之后改过。列表 / 详情填充
     */
    @TableField(exist = false)
    private List<Map<String, Object>> portables;

    @TableField(exist = false)
    private String originState;

    /** 被应用到工作区的次数 */
    private Integer useCount;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
