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
 * 试聊会话（persona_chat）：和原型卡 / 适配版本 / 工作区角色卡的一段对话，可以回看、继续。
 */
@Data
@TableName(value = "persona_chat", autoResultMap = true)
public class PersonaChat {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long cardId;

    private Long adaptationId;

    private String novelId;

    private String characterName;

    /** 工作区角色卡字段 {name, card{...}, userRole?} */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> character;

    /** free / scene / interview */
    private String mode;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> scene;

    private Boolean innerOn;

    /** [{role, content, inner?, at, rating?, reason?}] */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Map<String, Object>> messages;

    private String summary;

    private Integer summarizedUpto;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> drift;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
