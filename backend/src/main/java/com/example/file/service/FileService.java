package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.FileInfo;
import com.example.file.mapper.FileMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 文件存储服务：落盘到 Spring Boot 管理的存储目录 + 生成存储路径 + 写库。
 */
@Service
public class FileService {

    private static final Logger log = LoggerFactory.getLogger(FileService.class);

    /** 存储根目录（application.yml 的 file.storage.path） */
    @Value("${file.storage.path}")
    private String storagePath;

    private final FileMapper fileMapper;

    public FileService(FileMapper fileMapper) {
        this.fileMapper = fileMapper;
    }

    /**
     * 上传文件：落盘 + 写库，返回含自增 id 的 FileInfo。
     */
    public FileInfo upload(MultipartFile file) {
        // 1. 校验
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("文件不能为空");
        }

        // 2. 取扩展名（小写、不含点）
        String originalName = file.getOriginalFilename();
        String fileExt = getExtension(originalName);

        // 3. 生成唯一文件名（防重名 + 防路径穿越）
        String storedName = UUID.randomUUID().toString().replace("-", "")
                + (fileExt.isEmpty() ? "" : "." + fileExt);

        // 4. 按日期建子目录 yyyy/MM/dd
        LocalDate today = LocalDate.now();
        String dateDir = String.format("%04d/%02d/%02d",
                today.getYear(), today.getMonthValue(), today.getDayOfMonth());

        // 5. 落盘
        Path rootPath = Paths.get(storagePath).toAbsolutePath().normalize();
        Path targetDir = rootPath.resolve(dateDir);
        Path targetFile = targetDir.resolve(storedName);
        try {
            Files.createDirectories(targetDir);
            try (InputStream in = file.getInputStream()) {
                Files.copy(in, targetFile);
            }
        } catch (IOException e) {
            log.error("文件落盘失败，目标路径：{}", targetFile, e);
            throw new RuntimeException("文件落盘失败", e);
        }

        // 6~8. 组装 FileInfo 并写库
        FileInfo info = new FileInfo();
        info.setFileName(originalName);
        info.setStoragePath(dateDir + "/" + storedName);
        info.setFileSize(file.getSize());
        info.setContentType(file.getContentType());
        info.setFileExt(fileExt);
        info.setCreateTime(LocalDateTime.now());
        fileMapper.insert(info);

        // 9. 返回（含自增 id）
        return info;
    }

    /**
     * 查全部文件，按创建时间倒序。
     */
    public List<FileInfo> list() {
        return fileMapper.selectList(
                new LambdaQueryWrapper<FileInfo>().orderByDesc(FileInfo::getCreateTime));
    }

    /**
     * 按主键查文件信息，不存在抛业务异常（404）。
     */
    public FileInfo getById(Long id) {
        FileInfo info = fileMapper.selectById(id);
        if (info == null) {
            throw new BizException(404, "文件记录不存在：" + id);
        }
        return info;
    }

    /**
     * 读取磁盘字节，下载/预览共用。
     */
    public byte[] read(Long id) {
        FileInfo info = getById(id);
        Path rootPath = Paths.get(storagePath).toAbsolutePath().normalize();
        Path targetFile = rootPath.resolve(info.getStoragePath());
        try {
            return Files.readAllBytes(targetFile);
        } catch (NoSuchFileException e) {
            log.error("磁盘文件不存在：{}", targetFile);
            throw new BizException(404, "磁盘文件不存在");
        } catch (IOException e) {
            log.error("读取文件失败：{}", targetFile, e);
            throw new RuntimeException("读取文件失败", e);
        }
    }

    /**
     * 截取扩展名：小写、不含点；无扩展名返回空串。
     */
    private String getExtension(String originalName) {
        if (originalName == null) {
            return "";
        }
        int dotIndex = originalName.lastIndexOf('.');
        if (dotIndex < 0 || dotIndex == originalName.length() - 1) {
            return "";
        }
        return originalName.substring(dotIndex + 1).toLowerCase();
    }
}