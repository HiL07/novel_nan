package com.example.file.common;

import lombok.Getter;

/**
 * 业务异常：携带业务 code（非 0 表示失败，如 404 资源不存在），由上层转成对应响应。
 */
@Getter
public class BizException extends RuntimeException {

    private final int code;

    public BizException(int code, String message) {
        super(message);
        this.code = code;
    }
}
