package com.example.file.controller;

import com.example.file.common.BizException;
import com.example.file.common.Result;
import com.example.file.entity.FileInfo;
import com.example.file.service.FileService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 文件接口：上传 + 列表 / 下载 / 预览。
 */
@RestController
@RequestMapping("/api/file")
public class FileController {

    private static final Logger log = LoggerFactory.getLogger(FileController.class);

    private final FileService fileService;

    public FileController(FileService fileService) {
        this.fileService = fileService;
    }

    /**
     * POST /api/file/upload，表单字段名固定为 file。
     */
    @PostMapping("/upload")
    public Result<FileInfo> upload(@RequestParam("file") MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return Result.error(400, "文件不能为空");
        }
        try {
            return Result.ok(fileService.upload(file));
        } catch (Exception e) {
            log.error("文件上传失败", e);
            return Result.error(500, "上传失败");
        }
    }

    /**
     * GET /api/file/list，返回全部文件，按上传时间倒序。
     */
    @GetMapping("/list")
    public Result<List<FileInfo>> list() {
        return Result.ok(fileService.list());
    }

    /**
     * GET /api/file/download/{id}，以附件形式下载。
     */
    @GetMapping("/download/{id}")
    public ResponseEntity<byte[]> download(@PathVariable Long id) {
        return stream(id, true);
    }

    /**
     * GET /api/file/preview/{id}，内联返回（图片/PDF/文本在浏览器内渲染）。
     */
    @GetMapping("/preview/{id}")
    public ResponseEntity<byte[]> preview(@PathVariable Long id) {
        return stream(id, false);
    }

    /**
     * 下载 / 预览共用：读磁盘字节 + 设置 Content-Type 与 Content-Disposition。
     */
    private ResponseEntity<byte[]> stream(Long id, boolean attachment) {
        try {
            FileInfo info = fileService.getById(id);
            byte[] bytes = fileService.read(id);

            String contentType = info.getContentType() != null
                    ? info.getContentType()
                    : MediaType.APPLICATION_OCTET_STREAM_VALUE;
            ContentDisposition disposition = ContentDisposition
                    .builder(attachment ? "attachment" : "inline")
                    .filename(info.getFileName(), StandardCharsets.UTF_8)
                    .build();

            return ResponseEntity.ok()
                    .header(HttpHeaders.CONTENT_TYPE, contentType)
                    .header(HttpHeaders.CONTENT_DISPOSITION, disposition.toString())
                    .body(bytes);
        } catch (BizException e) {
            log.warn("文件不存在：{}", e.getMessage());
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        } catch (Exception e) {
            log.error("文件读取失败，id={}", id, e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }
}
