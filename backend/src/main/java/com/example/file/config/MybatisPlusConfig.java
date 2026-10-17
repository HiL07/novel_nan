package com.example.file.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.autoconfigure.ConfigurationCustomizer;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.LocalDateTime;

/**
 * MyBatis-Plus 配置（SQLite）：
 * - 分页插件（selectPage 需要它才会生成 LIMIT 与 count 查询），方言为 SQLite
 * - LocalDateTime 全局以 "yyyy-MM-dd HH:mm:ss" 文本存取（见 LocalDateTimeTextTypeHandler）
 */
@Configuration
public class MybatisPlusConfig {

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.SQLITE));
        return interceptor;
    }

    @Bean
    public ConfigurationCustomizer localDateTimeAsText() {
        return configuration -> configuration.getTypeHandlerRegistry()
                .register(LocalDateTime.class, new LocalDateTimeTextTypeHandler());
    }
}
