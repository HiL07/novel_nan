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

/**
 * 一面灵感墙：收藏的思路和钉的素材放在墙上；可关联一个写作工作区（构思时带上它的设定 / 大纲 / 章节）。
 */
@Data
@TableName(value = "inspiration_wall", autoResultMap = true)
public class InspirationWall {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;

    private String note;

    /** 关联的工作区（Python novel id），可空 */
    private String novelId;

    /** 构思时屏蔽的来源书 */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> excludeBooks;

    /** 列表：墙上的思路数 / 素材数（不是数据库列） */
    @TableField(exist = false)
    private Long ideaCount;

    @TableField(exist = false)
    private Long materialCount;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
