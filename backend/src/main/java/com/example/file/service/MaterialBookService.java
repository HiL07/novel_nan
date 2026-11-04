package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.Material;
import com.example.file.entity.NovelExtract;
import com.example.file.mapper.MaterialMapper;
import com.example.file.mapper.NovelExtractMapper;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 书库（素材库工作区，2026-11-04）：一本书（MaterialService.bookOf 同名，同 material.source_book）一个，
 * 这本书各个提取工作区存进来的素材是共有的。列表 = 每本书的素材数 / 分类小计 / 来源工作区 / 待入库卡片；
 * 详情 = 全貌（素材，带来自哪个工作区）+ 来源（工作区）+ 关系（共鸣素材）。
 */
@Service
public class MaterialBookService {

    private final MaterialMapper materialMapper;
    private final NovelExtractMapper extractMapper;
    private final MaterialService materialService;
    private final ExtractCardService cardService;

    public MaterialBookService(MaterialMapper materialMapper, NovelExtractMapper extractMapper, MaterialService materialService,
                               ExtractCardService cardService) {
        this.materialMapper = materialMapper;
        this.extractMapper = extractMapper;
        this.materialService = materialService;
        this.cardService = cardService;
    }

    /** [{book, total, byCategory{code: n}, pinned, workspaces, pending, updateTime}]，最近更新的在前 */
    public List<Map<String, Object>> books() {
        Map<String, Map<String, Object>> out = new LinkedHashMap<>();
        for (Map<String, Object> row : materialMapper.selectMaps(new QueryWrapper<Material>()
                .select("source_book", "category", "COUNT(*) AS cnt", "SUM(CASE WHEN pinned = 1 THEN 1 ELSE 0 END) AS pinned_cnt",
                        "MAX(update_time) AS last_time")
                .isNotNull("source_book").isNull("merged_into").groupBy("source_book", "category"))) {
            String book = Objects.toString(row.get("source_book"), "");
            if (book.isBlank() || MaterialService.MANUAL_BOOK.equals(book)) {
                continue;
            }
            Map<String, Object> b = entry(out, book);
            long n = ((Number) row.get("cnt")).longValue();
            b.put("total", (long) b.get("total") + n);
            b.put("pinned", (long) b.get("pinned") + (row.get("pinned_cnt") == null ? 0 : ((Number) row.get("pinned_cnt")).longValue()));
            @SuppressWarnings("unchecked")
            Map<String, Object> cats = (Map<String, Object>) b.get("byCategory");
            cats.put(Objects.toString(row.get("category"), ""), n);
            later(b, Objects.toString(row.get("last_time"), ""));
        }
        Map<Long, Long> pending = cardService.newCountsByExtract();
        for (NovelExtract t : extractMapper.selectList(new LambdaQueryWrapper<NovelExtract>()
                .select(NovelExtract::getId, NovelExtract::getFileName, NovelExtract::getUpdateTime))) {
            String book = MaterialService.bookOf(t.getFileName());
            if (book == null) {
                continue;
            }
            Map<String, Object> b = entry(out, book);
            b.put("workspaces", (int) b.get("workspaces") + 1);
            b.put("pending", (long) b.get("pending") + pending.getOrDefault(t.getId(), 0L));
            later(b, t.getUpdateTime() == null ? "" : t.getUpdateTime().toString().replace('T', ' '));
        }
        List<Map<String, Object>> list = new ArrayList<>(out.values());
        list.sort((a, b) -> Objects.toString(b.get("updateTime"), "").compareTo(Objects.toString(a.get("updateTime"), "")));
        return list;
    }

    /**
     * 单本书：{book, materials（不含合并成员；每条带 extractId / workspace）, workspaces [{id, title, fileName, status, options,
     * chapterCount, updateTime, saved, pending}], resonance（共鸣素材，含 source.resonance 关系图）}
     */
    public Map<String, Object> detail(String book) {
        String name = book == null ? "" : book.trim();
        if (name.isEmpty()) {
            throw new BizException(400, "请指定书名");
        }
        List<NovelExtract> tasks = extractMapper.selectList(new LambdaQueryWrapper<NovelExtract>()
                        .select(NovelExtract::getId, NovelExtract::getFileName, NovelExtract::getTitle, NovelExtract::getStatus,
                                NovelExtract::getOptions, NovelExtract::getChapterCount, NovelExtract::getUpdateTime)
                        .orderByDesc(NovelExtract::getUpdateTime))
                .stream().filter(t -> name.equals(MaterialService.bookOf(t.getFileName()))).toList();
        Map<Long, String> titles = new HashMap<>();
        tasks.forEach(t -> titles.put(t.getId(), t.getTitle() != null && !t.getTitle().isBlank() ? t.getTitle() : "工作区 #" + t.getId()));
        List<Map<String, Object>> materials = new ArrayList<>();
        List<Map<String, Object>> resonance = new ArrayList<>();
        Map<Long, Integer> savedBy = new HashMap<>();
        for (Material m : materialService.materialsOfBook(name)) {
            if (m.getMergedInto() != null) {
                continue; // 合并成员：看主条目
            }
            Map<String, Object> x = new LinkedHashMap<>();
            x.put("id", m.getId());
            x.put("category", m.getCategory());
            x.put("subtype", m.getSubtype());
            x.put("title", m.getTitle());
            x.put("summary", m.getSummary());
            x.put("tags", m.getTags());
            x.put("pinned", m.getPinned());
            x.put("profile", m.getProfile());
            x.put("updateTime", m.getUpdateTime());
            Object eid = m.getSource() == null ? null : m.getSource().get("extractId");
            if (eid instanceof Number n) {
                x.put("extractId", n.longValue());
                x.put("workspace", titles.getOrDefault(n.longValue(), "已删除的工作区"));
                savedBy.merge(n.longValue(), 1, Integer::sum);
            }
            boolean multi = MaterialService.isMergeMaster(m);
            x.put("multiVersion", multi);
            materials.add(x);
            if ("resonance".equals(m.getCategory()) && m.getSource() != null && m.getSource().get("resonance") != null) {
                Map<String, Object> r = new LinkedHashMap<>(x);
                r.put("graph", m.getSource().get("resonance"));
                resonance.add(r);
            }
        }
        Map<Long, Long> pending = cardService.newCountsByExtract();
        List<Map<String, Object>> workspaces = new ArrayList<>();
        for (NovelExtract t : tasks) {
            Map<String, Object> w = new LinkedHashMap<>();
            w.put("id", t.getId());
            w.put("title", t.getTitle());
            w.put("fileName", t.getFileName());
            w.put("status", t.getStatus());
            w.put("options", t.getOptions());
            w.put("chapterCount", t.getChapterCount());
            w.put("updateTime", t.getUpdateTime());
            w.put("saved", savedBy.getOrDefault(t.getId(), 0));
            w.put("pending", pending.getOrDefault(t.getId(), 0L));
            workspaces.add(w);
        }
        if (materials.isEmpty() && workspaces.isEmpty()) {
            throw new BizException(404, "书库里没有这本书：" + name);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("book", name);
        out.put("materials", materials);
        out.put("workspaces", workspaces);
        out.put("resonance", resonance);
        return out;
    }

    private static Map<String, Object> entry(Map<String, Map<String, Object>> out, String book) {
        return out.computeIfAbsent(book, k -> {
            Map<String, Object> b = new LinkedHashMap<>();
            b.put("book", k);
            b.put("total", 0L);
            b.put("byCategory", new LinkedHashMap<String, Object>());
            b.put("pinned", 0L);
            b.put("workspaces", 0);
            b.put("pending", 0L);
            b.put("updateTime", "");
            return b;
        });
    }

    private static void later(Map<String, Object> b, String time) {
        if (time != null && time.compareTo(Objects.toString(b.get("updateTime"), "")) > 0) {
            b.put("updateTime", time.length() > 19 ? time.substring(0, 19) : time);
        }
    }
}
