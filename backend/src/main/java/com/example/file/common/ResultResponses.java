package com.example.file.common;

import org.slf4j.Logger;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.function.Supplier;

/**
 * JSON 接口统一包装：成功 → 200 + Result.ok；BizException → 对应 HTTP 状态 + Result.error；
 * 其他异常 → 记录日志后 500，不向客户端暴露堆栈。
 */
public final class ResultResponses {

    private ResultResponses() {
    }

    public static <T> ResponseEntity<Result<T>> handle(Supplier<T> action, Logger log, String errorLog) {
        try {
            return ResponseEntity.ok(Result.ok(action.get()));
        } catch (BizException e) {
            HttpStatus status = HttpStatus.resolve(e.getCode());
            return ResponseEntity.status(status != null ? status : HttpStatus.BAD_REQUEST)
                    .body(Result.error(e.getCode(), e.getMessage()));
        } catch (Exception e) {
            log.error(errorLog, e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Result.error(500, "服务器内部错误"));
        }
    }
}
