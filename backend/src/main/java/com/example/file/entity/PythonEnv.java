package com.example.file.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 检测通过的 Python 环境配置，对应 test10000.python_env 表；active 为当前使用的那一个。
 */
@Data
@TableName("python_env")
public class PythonEnv {

    public static final String TYPE_SYSTEM = "SYSTEM";
    public static final String TYPE_CONDA = "CONDA";
    public static final String TYPE_VENV = "VENV";
    public static final String TYPE_CUSTOM = "CUSTOM";

    @TableId(type = IdType.AUTO)
    private Long id;

    /** SYSTEM / CONDA / VENV / CUSTOM */
    private String envType;

    /** python.exe 绝对路径 */
    private String pythonPath;

    /** Conda 安装目录（CONDA 类型） */
    private String condaRoot;

    /** Conda 环境名（CONDA 类型） */
    private String condaEnv;

    private String pythonVersion;

    private Boolean cudaAvailable;

    private String gpuName;

    private String torchVersion;

    /** 检测结论：OK / WARN（ERROR 不会保存） */
    private String status;

    /** 完整检测结果 JSON（见 PythonEnvService#check） */
    private String checkResult;

    private Boolean active;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime checkedTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;
}
