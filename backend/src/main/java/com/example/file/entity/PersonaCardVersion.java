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

/**
 * 原型卡的一个版本（persona_card_version）：只追加，不修改。编辑后保存 = 新版本。
 */
@Data
@TableName(value = "persona_card_version", autoResultMap = true)
public class PersonaCardVersion {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long cardId;

    private Integer versionNo;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> content;

    /** ai / user */
    private String author;

    private String note;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;
}
