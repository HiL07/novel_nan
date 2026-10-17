package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

/**
 * 素材标签索引（material_tag），保存 / 修改素材时与 Material.tags 同步。
 */
@Data
@TableName("material_tag")
public class MaterialTag {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long materialId;

    private String tag;
}
