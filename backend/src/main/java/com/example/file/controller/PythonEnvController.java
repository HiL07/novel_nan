package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.service.PythonEnvService;
import lombok.Data;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Python 环境选择与检测（由 Java 执行所选 python.exe，后端本身不依赖该 Python）。
 */
@RestController
@RequestMapping("/api/python-env")
public class PythonEnvController {

    private static final Logger log = LoggerFactory.getLogger(PythonEnvController.class);

    private final PythonEnvService envService;

    public PythonEnvController(PythonEnvService envService) {
        this.envService = envService;
    }

    /** GET /api/python-env/discover：PATH 上的 python、Conda 环境、项目 venv、当前配置、Miniconda 指引 */
    @GetMapping("/discover")
    public ResponseEntity<Result<Map<String, Object>>> discover() {
        return ResultResponses.handle(envService::discover, log, "发现 Python 环境失败");
    }

    /** GET /api/python-env/conda/envs?condaPath=：列出 Conda 环境（condaPath 为空时自动查找） */
    @GetMapping("/conda/envs")
    public ResponseEntity<Result<Map<String, Object>>> condaEnvs(@RequestParam(required = false) String condaPath) {
        return ResultResponses.handle(() -> envService.condaEnvs(condaPath), log, "查询 Conda 环境失败");
    }

    /** GET /api/python-env/browse?path=：浏览目录（子目录 + python 可执行文件）；path 为空返回盘符 */
    @GetMapping("/browse")
    public ResponseEntity<Result<Map<String, Object>>> browse(@RequestParam(required = false) String path) {
        return ResultResponses.handle(() -> envService.browse(path), log, "浏览目录失败");
    }

    /** POST /api/python-env/check：执行所选 python.exe 检测；通过（OK/WARN）则保存为当前配置 */
    @PostMapping("/check")
    public ResponseEntity<Result<Map<String, Object>>> check(@RequestBody CheckReq req) {
        return ResultResponses.handle(
                () -> envService.check(req.getEnvType(), req.getPythonPath(), req.getCondaRoot(), req.getCondaEnv()),
                log, "检测 Python 环境失败");
    }

    /** GET /api/python-env/current：当前生效的配置（无则 data 为 null） */
    @GetMapping("/current")
    public ResponseEntity<Result<Map<String, Object>>> current() {
        return ResultResponses.handle(envService::current, log, "查询 Python 环境失败");
    }

    @Data
    public static class CheckReq {
        /** SYSTEM / CONDA / VENV / CUSTOM */
        private String envType;
        private String pythonPath;
        private String condaRoot;
        private String condaEnv;
    }
}
