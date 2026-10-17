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
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
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
        // 先写同目录临时文件再原子改名，避免中途失败留下半截文件
        Path tmpFile = targetDir.resolve(storedName + ".part");
        try {
            Files.createDirectories(targetDir);
            try (InputStream in = file.getInputStream()) {
                Files.copy(in, tmpFile, StandardCopyOption.REPLACE_EXISTING);
            }
            try {
                Files.move(tmpFile, targetFile, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException e) {
                Files.move(tmpFile, targetFile);
            }
        } catch (IOException e) {
            deleteQuietly(tmpFile);
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
        try {
            fileMapper.insert(info);
        } catch (RuntimeException e) {
            // 写库失败：删除已落盘的文件，避免出现没有记录的孤儿文件
            deleteQuietly(targetFile);
            throw e;
        }

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
        Path targetFile = rootPath.resolve(info.getStoragePath()).normalize();
        if (!targetFile.startsWith(rootPath)) {
            log.error("非法的存储路径，id={}：{}", id, info.getStoragePath());
            throw new BizException(404, "文件路径非法");
        }
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
     * 文本字节统一转成 UTF-8：中文 txt 常见 GBK 编码，按 UTF-8（严格）→ GB18030（严格）依次识别，
     * 都不合法时按 UTF-8 替换非法字节。带 BOM 的 UTF-8 / UTF-16 直接按 BOM 解码。
     */
    public byte[] toUtf8Text(byte[] bytes) {
        return decodeText(bytes).getBytes(StandardCharsets.UTF_8);
    }

    private String decodeText(byte[] bytes) {
        if (bytes.length >= 3 && (bytes[0] & 0xFF) == 0xEF && (bytes[1] & 0xFF) == 0xBB && (bytes[2] & 0xFF) == 0xBF) {
            return new String(bytes, 3, bytes.length - 3, StandardCharsets.UTF_8);
        }
        if (bytes.length >= 2 && (((bytes[0] & 0xFF) == 0xFF && (bytes[1] & 0xFF) == 0xFE)
                || ((bytes[0] & 0xFF) == 0xFE && (bytes[1] & 0xFF) == 0xFF))) {
            return new String(bytes, StandardCharsets.UTF_16);
        }
        for (Charset charset : new Charset[]{StandardCharsets.UTF_8, Charset.forName("GB18030")}) {
            try {
                return charset.newDecoder()
                        .onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT)
                        .decode(ByteBuffer.wrap(bytes))
                        .toString();
            } catch (CharacterCodingException ignored) {
                // 尝试下一种编码
            }
        }
        return new String(bytes, StandardCharsets.UTF_8);
    }

    private static void deleteQuietly(Path p) {
        try {
            Files.deleteIfExists(p);
        } catch (IOException e) {
            log.warn("清理文件失败：{}", p, e);
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