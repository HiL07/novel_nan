package com.example.file.config;

import com.example.file.service.MaterialService;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 已有数据库的增量迁移（建表脚本用 CREATE TABLE IF NOT EXISTS，无法给旧表加列）。
 * 在 spring.sql.init 建表之后运行；每一步都先检查再执行，可重复启动。新库的建表脚本已含这些列，直接跳过。
 */
@Component
@DependsOnDatabaseInitialization
public class SchemaMigrations {

    private static final Logger log = LoggerFactory.getLogger(SchemaMigrations.class);

    private final JdbcTemplate jdbc;

    public SchemaMigrations(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @PostConstruct
    public void migrate() {
        // 素材来源书 + 保留标记（按书删除 / 屏蔽来源书时，保留的素材不受影响）
        boolean addedBook = addColumn("material", "source_book", "TEXT");
        addColumn("material", "pinned", "INTEGER NOT NULL DEFAULT 0");
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_material_source_book ON material (source_book)");
        // 精炼 / 合并：成员指向主条目
        addColumn("material", "merged_into", "INTEGER");
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_material_merged_into ON material (merged_into)");
        if (addedBook) {
            backfillSourceBook();
        }
        // 站点规则加「待确认 / 已确认」：老规则当时已直接生效，迁移为已确认；一个域名可同时有已确认 + 待确认两条
        addColumn("crawl_site_rule", "status", "TEXT NOT NULL DEFAULT 'CONFIRMED'");
        addColumn("crawl_site_rule", "confirm_time", "TEXT");
        // 站点根地址 + 站点结构实测（每层跳转规律是否掌握）
        addColumn("crawl_site_rule", "home_url", "TEXT");
        addColumn("crawl_site_rule", "site_map", "TEXT");
        jdbc.execute("DROP INDEX IF EXISTS uk_crawl_site_rule_host");
        // 解析过程（每次尝试成败）+ 失败记录的原因：解析管理里直接查看
        addColumn("crawl_site_rule", "error", "TEXT");
        addColumn("crawl_site_rule", "attempt_log", "TEXT");
        // 文件管理显示小说章节数（老文件由 FileService 启动后在后台补数）
        addColumn("file", "chapter_count", "INTEGER");
        addColumn("novel_extract", "options", "TEXT");
    }

    /** 列不存在时添加，返回是否新加 */
    private boolean addColumn(String table, String column, String definition) {
        Set<String> columns = new HashSet<>();
        for (Map<String, Object> row : jdbc.queryForList("PRAGMA table_info(" + table + ")")) {
            columns.add(String.valueOf(row.get("name")).toLowerCase());
        }
        if (columns.contains(column)) {
            return false;
        }
        jdbc.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + definition);
        log.info("数据库迁移：{} 新增列 {}", table, column);
        return true;
    }

    /** 老素材的来源书 = source.fileName 去掉扩展名（如「三体.txt」→「三体」） */
    private void backfillSourceBook() {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, json_extract(source, '$.fileName') AS file_name FROM material WHERE source_book IS NULL");
        int n = 0;
        for (Map<String, Object> row : rows) {
            String book = MaterialService.bookOf(row.get("file_name") == null ? null : String.valueOf(row.get("file_name")));
            if (book != null) {
                n += jdbc.update("UPDATE material SET source_book = ? WHERE id = ?", book, row.get("id"));
            }
        }
        log.info("数据库迁移：回填素材来源书 {} 条", n);
    }
}
