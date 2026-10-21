package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 小说抓取页「常用地址」（crawl_saved_url 表）：用户收藏的可抓取网址，一个地址一行。
 */
@Data
@TableName("crawl_saved_url")
public class CrawlSavedUrl {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String url;
    /** 显示名（书名 / 站点名），可空 */
    private String name;
    /** book 单本 / site 整站：选用时切到对应模式 */
    private String mode;
    private String note;
    private Integer useCount;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime lastUsedTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
}
