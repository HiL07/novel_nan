package com.example.file.service;

import com.example.file.common.DataPaths;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * 完整提取结果的文件存储：data/extract-results/&lt;taskId&gt;.json（UTF-8，无 BOM）。
 * <p>
 * 写入：同目录临时文件 → 刷盘 → 原子改名，返回相对路径 / 大小 / SHA-256；数据库只保存这些元数据。
 * 读取：校验路径（防穿越）、存在性与 SHA-256，不一致时返回带原因的结果而不是抛异常。
 * 每个任务写各自独立的文件，提取任务又在单线程中执行，因此不存在同一文件的并发写。
 */
@Service
public class ExtractResultStore {

    private static final Logger log = LoggerFactory.getLogger(ExtractResultStore.class);

    private final DataPaths dataPaths;

    public ExtractResultStore(DataPaths dataPaths) {
        this.dataPaths = dataPaths;
    }

    /** 写入结果的元数据 */
    public record Stored(String relativePath, long size, String sha256) {
    }

    /** 读取结果：json 为 null 时 problem 说明原因（文件缺失 / 校验失败 / 读取失败） */
    public record Loaded(String json, String problem) {
    }

    public Stored write(long taskId, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        Path dir = dataPaths.root().resolve(DataPaths.EXTRACT_RESULTS);
        Files.createDirectories(dir);
        Path target = dir.resolve(taskId + ".json");
        Path tmp = dir.resolve(taskId + ".json.tmp");
        try (FileChannel ch = FileChannel.open(tmp, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE)) {
            ch.write(java.nio.ByteBuffer.wrap(bytes));
            ch.force(true);
        } catch (IOException e) {
            Files.deleteIfExists(tmp);
            throw e;
        }
        try {
            Files.move(tmp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException e) {
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            Files.deleteIfExists(tmp);
            throw e;
        }
        return new Stored(dataPaths.relativize(target), bytes.length, sha256(bytes));
    }

    public Loaded read(String relativePath, String expectedSha256) {
        Path file;
        try {
            file = dataPaths.resolve(DataPaths.EXTRACT_RESULTS, relativePath);
        } catch (RuntimeException e) {
            return new Loaded(null, "结果文件路径非法");
        }
        try {
            byte[] bytes = Files.readAllBytes(file);
            if (expectedSha256 != null && !expectedSha256.equalsIgnoreCase(sha256(bytes))) {
                log.error("提取结果校验失败：{}", file);
                return new Loaded(null, "结果文件校验失败（内容已损坏或被修改）");
            }
            return new Loaded(new String(bytes, StandardCharsets.UTF_8), null);
        } catch (NoSuchFileException e) {
            log.warn("提取结果文件缺失：{}", file);
            return new Loaded(null, "结果文件缺失：" + relativePath);
        } catch (IOException e) {
            log.error("读取提取结果失败：{}", file, e);
            return new Loaded(null, "读取结果文件失败");
        }
    }

    /** 写入后数据库更新失败时回收文件，避免留下无记录的文件 */
    public void deleteQuietly(String relativePath) {
        try {
            Files.deleteIfExists(dataPaths.resolve(DataPaths.EXTRACT_RESULTS, relativePath));
        } catch (IOException | RuntimeException e) {
            log.warn("删除提取结果文件失败：{}", relativePath, e);
        }
    }

    static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
