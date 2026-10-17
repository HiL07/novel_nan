package com.example.file.config;

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

/**
 * SQLite 没有日期类型；sqlite-jdbc 默认把时间存成毫秒数，与 MySQL 迁移数据和人工查看都不一致。
 * 统一存为本地时间文本 "yyyy-MM-dd HH:mm:ss"（可排序、与接口返回格式一致）。读取时兼容带 T / 小数秒 / 毫秒数的旧值。
 */
public class LocalDateTimeTextTypeHandler extends BaseTypeHandler<LocalDateTime> {

    public static final DateTimeFormatter FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, LocalDateTime v, JdbcType jdbcType) throws SQLException {
        ps.setString(i, v.format(FORMAT));
    }

    @Override
    public LocalDateTime getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return parse(rs.getString(columnName));
    }

    @Override
    public LocalDateTime getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return parse(rs.getString(columnIndex));
    }

    @Override
    public LocalDateTime getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return parse(cs.getString(columnIndex));
    }

    static LocalDateTime parse(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        String t = s.trim();
        if (t.chars().allMatch(Character::isDigit)) {
            return LocalDateTime.ofInstant(Instant.ofEpochMilli(Long.parseLong(t)), ZoneId.systemDefault());
        }
        t = t.replace('T', ' ');
        int dot = t.indexOf('.');
        if (dot > 0) {
            t = t.substring(0, dot);
        }
        return LocalDateTime.parse(t.length() == 16 ? t + ":00" : t, FORMAT);
    }
}
