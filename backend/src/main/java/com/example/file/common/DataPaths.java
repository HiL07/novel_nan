package com.example.file.common;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * 共享数据目录（data/）下各子目录的定位与路径安全校验。约定见 data/README.md。
 */
@Component
public class DataPaths {

    /** 完整提取结果 JSON：data/extract-results/&lt;taskId&gt;.json */
    public static final String EXTRACT_RESULTS = "extract-results";
    /** AI 学到的站点抓取规则（数据库之外另存一份，方便查找 / 备份）：data/crawl-rules/&lt;host&gt;_&lt;id&gt;.json */
    public static final String CRAWL_RULES = "crawl-rules";
    /** 全自动爬虫的站点书目（同一首页一个目录）：data/site-catalog/&lt;host&gt;/toc/&lt;key&gt;.json（Python 写）、catalog.json（Java 导出） */
    public static final String SITE_CATALOG = "site-catalog";

    private final Path root;

    public DataPaths(@Value("${app.data-dir}") String dataDir) {
        this.root = Paths.get(dataDir).toAbsolutePath().normalize();
    }

    public Path root() {
        return root;
    }

    /**
     * 把数据库中保存的相对路径（"/" 分隔）解析为绝对路径，并校验必须落在 data/&lt;subDir&gt;/ 之内（防路径穿越）。
     */
    public Path resolve(String subDir, String relativePath) {
        if (relativePath == null || relativePath.isBlank()) {
            throw new BizException(400, "文件路径为空");
        }
        Path base = root.resolve(subDir).normalize();
        Path p = root.resolve(relativePath.replace('\\', '/')).normalize();
        if (!p.startsWith(base) || p.equals(base)) {
            throw new BizException(400, "非法的文件路径：" + relativePath);
        }
        return p;
    }

    /** 绝对路径 → 相对 data/ 的路径（"/" 分隔），用于写入数据库 */
    public String relativize(Path absolute) {
        return root.relativize(absolute.toAbsolutePath().normalize()).toString().replace('\\', '/');
    }
}
