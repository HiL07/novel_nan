package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文件实体，对应 test10000.file 表。
 */
@Data
@TableName("file")
public class FileInfo {

    /** 主键（自增） */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 原始文件名（用户上传时的名字） */
    private String fileName;

    /** 存储路径（相对存储根目录） */
    private String storagePath;

    /** 文件大小（字节） */
    private Long fileSize;

    /** MIME 类型，如 image/png */
    private String contentType;

    /** 扩展名（不含点），如 png */
    private String fileExt;

    /** 上传时间 */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;
}