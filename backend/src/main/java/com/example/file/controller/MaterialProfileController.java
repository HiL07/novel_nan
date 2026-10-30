package com.example.file.controller;

import com.example.file.common.Result;
import com.example.file.common.ResultResponses;
import com.example.file.service.MaterialProfileService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 素材量级（1–5，影响范围）的批量补全：/api/material/profile/**
 */
@RestController
@RequestMapping("/api/material/profile")
public class MaterialProfileController {

    private static final Logger log = LoggerFactory.getLogger(MaterialProfileController.class);

    private final MaterialProfileService profileService;

    public MaterialProfileController(MaterialProfileService profileService) {
        this.profileService = profileService;
    }

    /** GET /api/material/profile/status → {total, labeled, missing, byUser, running, batchTotal, done, failed, positions, lastError} */
    @GetMapping("/status")
    public ResponseEntity<Result<Map<String, Object>>> status() {
        return ResultResponses.handle(profileService::status, log, "查询量级补全进度失败");
    }

    /** POST /api/material/profile/start {model, onlyMissing?} */
    @PostMapping("/start")
    public ResponseEntity<Result<Map<String, Object>>> start(@RequestBody(required = false) Map<String, Object> body) {
        return ResultResponses.handle(() -> profileService.start(body), log, "开始补全量级失败");
    }

    /** POST /api/material/profile/stop：当前这批标完后停下 */
    @PostMapping("/stop")
    public ResponseEntity<Result<Map<String, Object>>> stop() {
        return ResultResponses.handle(profileService::stop, log, "暂停量级补全失败");
    }
}
