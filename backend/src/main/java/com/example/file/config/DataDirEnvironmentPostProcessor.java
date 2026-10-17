package com.example.file.config;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.context.config.ConfigDataEnvironmentPostProcessor;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;

/**
 * 在数据源等配置解析之前确定共享数据目录 app.data-dir：
 * 已配置（application.yml 或环境变量 DATA_DIR）则使用之，否则自动识别为 &lt;项目根&gt;/data
 * （从 backend/ 启动时项目根为上级目录，从项目根启动时为当前目录）。结果统一为绝对路径、"/" 分隔，并确保目录存在。
 * 注册于 META-INF/spring.factories。
 */
public class DataDirEnvironmentPostProcessor implements EnvironmentPostProcessor, Ordered {

    public static final String KEY = "app.data-dir";

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment env, SpringApplication application) {
        String configured = env.getProperty(KEY);
        Path dir = (configured == null || configured.isBlank() ? detect() : Paths.get(configured.trim()))
                .toAbsolutePath().normalize();
        try {
            Files.createDirectories(dir);
        } catch (IOException e) {
            throw new UncheckedIOException("无法创建共享数据目录：" + dir, e);
        }
        env.getPropertySources().addFirst(new MapPropertySource("resolvedDataDir",
                Map.of(KEY, dir.toString().replace('\\', '/'))));
    }

    static Path detect() {
        Path cwd = Paths.get("").toAbsolutePath().normalize();
        if (Files.isDirectory(cwd.resolve("python-service")) || Files.isDirectory(cwd.resolve("backend"))) {
            return cwd.resolve("data");
        }
        Path parent = cwd.getParent();
        if (parent != null && Files.isDirectory(parent.resolve("python-service"))) {
            return parent.resolve("data");
        }
        return cwd.resolve("data");
    }

    /** 须在 application.yml 等配置文件加载之后执行 */
    @Override
    public int getOrder() {
        return ConfigDataEnvironmentPostProcessor.ORDER + 1;
    }
}
