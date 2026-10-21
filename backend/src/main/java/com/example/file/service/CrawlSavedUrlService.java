package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.file.common.BizException;
import com.example.file.common.DataPaths;
import com.example.file.entity.CrawlSavedUrl;
import com.example.file.mapper.CrawlSavedUrlMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/**
 * 小说抓取页「常用地址」：用户收藏的可抓取网址（目录页 / 书籍详情页 / 站点首页）。
 * 同一地址只存一行，重复收藏 = 更新名称 / 模式 / 备注。
 * 内置几个默认地址（{@link #DEFAULTS}），每个数据目录只自动加一次：新用户直接就有，用户删掉后不会再加回来。
 */
@Service
public class CrawlSavedUrlService {

    private static final Logger log = LoggerFactory.getLogger(CrawlSavedUrlService.class);

    private static final int MAX_URL = 2000;
    private static final int MAX_NAME = 100;
    private static final int MAX_NOTE = 500;

    /** 内置的默认地址：{url, name, mode}（书籍目录页，可直接解析目录或用「AI 解析」学该站规律） */
    static final List<String[]> DEFAULTS = List.of(
            new String[]{"https://www.biquh.com/678_678189/", "biquh.com 示例书（默认）", "book"},
            new String[]{"https://www.xinbiqug.com/book/770375/", "xinbiqug.com 示例书（默认）", "book"});
    /** 默认地址已经加过的标记（data/.defaults-applied 里的一行）；默认地址有变化时换版本号 */
    private static final String DEFAULTS_MARK = "crawl-saved-urls-v1";

    private final CrawlSavedUrlMapper mapper;
    private final DataPaths dataPaths;

    public CrawlSavedUrlService(CrawlSavedUrlMapper mapper, DataPaths dataPaths) {
        this.mapper = mapper;
        this.dataPaths = dataPaths;
    }

    /** 启动后把默认地址加进常用地址（已存在的跳过）；每个数据目录只做一次，之后用户删掉的不再恢复 */
    @EventListener(ApplicationReadyEvent.class)
    public void seedDefaults() {
        Path mark = dataPaths.root().resolve(".defaults-applied");
        try {
            if (Files.exists(mark) && Files.readAllLines(mark, StandardCharsets.UTF_8).contains(DEFAULTS_MARK)) {
                return;
            }
            LocalDateTime now = LocalDateTime.now();
            int added = 0;
            for (String[] d : DEFAULTS) {
                if (findByUrl(d[0]) != null) {
                    continue;
                }
                CrawlSavedUrl row = new CrawlSavedUrl();
                row.setUrl(d[0]);
                row.setName(d[1]);
                row.setMode(d[2]);
                row.setNote("内置默认地址");
                row.setUseCount(0);
                row.setCreateTime(now);
                row.setUpdateTime(now);
                mapper.insert(row);
                added++;
            }
            Files.writeString(mark, DEFAULTS_MARK + System.lineSeparator(), StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            if (added > 0) {
                log.info("已添加 {} 个默认常用抓取地址", added);
            }
        } catch (IOException | RuntimeException e) {
            log.warn("添加默认常用地址失败（不影响使用）：{}", e.getMessage());
        }
    }

    /** 最近用过的在前，没用过的按收藏时间倒序 */
    public List<CrawlSavedUrl> list() {
        List<CrawlSavedUrl> rows = mapper.selectList(new LambdaQueryWrapper<CrawlSavedUrl>()
                .orderByDesc(CrawlSavedUrl::getUpdateTime));
        rows.sort(Comparator.comparing(CrawlSavedUrl::getLastUsedTime,
                Comparator.nullsLast(Comparator.reverseOrder())));
        return rows;
    }

    /** {id?, url, name?, mode?, note?}：有 id 改该行；无 id 时同地址已存在则更新它，否则新增 */
    public CrawlSavedUrl save(Map<String, Object> body) {
        if (body == null) {
            throw new BizException(400, "缺少参数");
        }
        String url = trim(body.get("url"), MAX_URL);
        if (url == null || !isHttpUrl(url)) {
            throw new BizException(400, "请输入 http:// 或 https:// 开头的地址");
        }
        String mode = "site".equals(body.get("mode")) ? "site" : "book";
        Long id = body.get("id") instanceof Number n ? n.longValue() : null;

        CrawlSavedUrl same = findByUrl(url);
        CrawlSavedUrl row;
        if (id != null) {
            row = getById(id);
            if (same != null && !same.getId().equals(id)) {
                throw new BizException(400, "这个地址已经收藏过了（「" + label(same) + "」）");
            }
        } else {
            row = same;
        }
        LocalDateTime now = LocalDateTime.now();
        boolean insert = row == null;
        if (insert) {
            row = new CrawlSavedUrl();
            row.setUseCount(0);
            row.setCreateTime(now);
        }
        row.setUrl(url);
        row.setName(trim(body.get("name"), MAX_NAME));
        row.setMode(mode);
        row.setNote(trim(body.get("note"), MAX_NOTE));
        row.setUpdateTime(now);
        if (insert) {
            mapper.insert(row);
            log.info("收藏抓取地址 id={} url={}", row.getId(), url);
        } else {
            mapper.updateById(row);
        }
        return row;
    }

    /** 选用一次：计数 + 最近使用时间（排序用） */
    public CrawlSavedUrl use(Long id) {
        CrawlSavedUrl row = getById(id);
        row.setUseCount((row.getUseCount() == null ? 0 : row.getUseCount()) + 1);
        row.setLastUsedTime(LocalDateTime.now());
        mapper.updateById(row);
        return row;
    }

    public void delete(Long id) {
        getById(id);
        mapper.deleteById(id);
    }

    private CrawlSavedUrl getById(Long id) {
        CrawlSavedUrl row = mapper.selectById(id);
        if (row == null) {
            throw new BizException(404, "该常用地址不存在（可能已删除）");
        }
        return row;
    }

    private CrawlSavedUrl findByUrl(String url) {
        return mapper.selectOne(new LambdaQueryWrapper<CrawlSavedUrl>().eq(CrawlSavedUrl::getUrl, url).last("LIMIT 1"));
    }

    private static String label(CrawlSavedUrl row) {
        return row.getName() == null || row.getName().isEmpty() ? row.getUrl() : row.getName();
    }

    private static boolean isHttpUrl(String url) {
        try {
            URI uri = URI.create(url);
            return ("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme()))
                    && uri.getHost() != null;
        } catch (IllegalArgumentException e) {
            return false;
        }
    }

    private static String trim(Object value, int max) {
        if (value == null) {
            return null;
        }
        String s = value.toString().trim();
        if (s.isEmpty()) {
            return null;
        }
        return s.length() > max ? s.substring(0, max) : s;
    }
}
