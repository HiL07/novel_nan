package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.file.common.BizException;
import com.example.file.entity.AiModelConfig;
import com.example.file.entity.Material;
import com.example.file.entity.PortableItem;
import com.example.file.entity.PortableWorkspace;
import com.example.file.mapper.MaterialMapper;
import com.example.file.mapper.PortableItemMapper;
import com.example.file.mapper.PortableWorkspaceMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * 架空工作区（2026-11-06）：每次架空是一个独立的工作区。工作区里展示素材库的全部原素材，勾选（或当前筛选的全部）加入待加工，
 * 开始后后台逐条调用 Python material_portable 生成架空版（material，source.type = portable，带 workspaceId / workspaceTitle）。
 * 同一条原素材在不同工作区的架空版互相独立；在同一个工作区里重做会更新那一条。原素材不动。
 * 全局同一时间只跑一个工作区；工作区内并发 = 模型配置的并发数（≤8）；Key 无效 / 余额不足 / AI 服务不可达时停下（PAUSED）。
 */
@Service
public class PortableWorkspaceService {

    private static final Logger log = LoggerFactory.getLogger(PortableWorkspaceService.class);
    static final int MAX_ENQUEUE = 5000;
    static final List<String> STATES = List.of(PortableItem.QUEUED, PortableItem.RUNNING, PortableItem.DONE, PortableItem.FAILED);

    private final PortableWorkspaceMapper wsMapper;
    private final PortableItemMapper itemMapper;
    private final MaterialMapper materialMapper;
    private final MaterialService materialService;
    private final NovelExtractService extractService;
    private final AiServiceClient aiClient;
    private final ObjectMapper objectMapper;
    private final ExecutorService runner = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "portable-workspace");
        t.setDaemon(true);
        return t;
    });

    private volatile Long runningWs;
    private volatile boolean stopRequested;
    private volatile String stopReason;

    public PortableWorkspaceService(PortableWorkspaceMapper wsMapper, PortableItemMapper itemMapper, MaterialMapper materialMapper,
                                    MaterialService materialService, NovelExtractService extractService, AiServiceClient aiClient,
                                    ObjectMapper objectMapper) {
        this.wsMapper = wsMapper;
        this.itemMapper = itemMapper;
        this.materialMapper = materialMapper;
        this.materialService = materialService;
        this.extractService = extractService;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    @PreDestroy
    public void shutdown() {
        runner.shutdownNow();
    }

    /** 启动时：上次没跑完的工作区记为暂停，加工中的条目退回待加工（执行线程已随进程退出） */
    @EventListener(ApplicationReadyEvent.class)
    public void markInterrupted() {
        itemMapper.update(null, new LambdaUpdateWrapper<PortableItem>().eq(PortableItem::getStatus, PortableItem.RUNNING)
                .set(PortableItem::getStatus, PortableItem.QUEUED));
        int n = wsMapper.update(null, new LambdaUpdateWrapper<PortableWorkspace>().eq(PortableWorkspace::getStatus, PortableWorkspace.RUNNING)
                .set(PortableWorkspace::getStatus, PortableWorkspace.PAUSED)
                .set(PortableWorkspace::getMessage, "服务重启，已暂停：点「继续」接着加工")
                .set(PortableWorkspace::getUpdateTime, LocalDateTime.now()));
        if (n > 0) {
            log.warn("服务重启：{} 个架空工作区记为暂停", n);
        }
        migrateLegacy();
    }

    /**
     * 架空工作区之前（2026-11-06 上午的版本）直接在素材库批量生成的架空版没有 workspaceId：归进一个「早期架空（迁移）」工作区，
     * 记为已加工，之后能在那里查看 / 重做。只在有这种架空版时做一次。
     */
    @SuppressWarnings("unchecked")
    void migrateLegacy() {
        List<Material> legacy = materialMapper.selectList(new LambdaQueryWrapper<Material>().select(Material::getId, Material::getSource)
                .apply("json_extract(source, '$.type') = 'portable' AND json_extract(source, '$.workspaceId') IS NULL"));
        if (legacy.isEmpty()) {
            return;
        }
        PortableWorkspace w = new PortableWorkspace();
        w.setTitle("早期架空（迁移）");
        w.setTargetWorld("");
        w.setModel(Map.of("source", "api"));
        w.setFilter(Map.of());
        w.setStatus(PortableWorkspace.IDLE);
        w.setMessage("架空工作区之前在素材库批量生成的 " + legacy.size() + " 条架空版");
        w.setCreateTime(LocalDateTime.now());
        w.setUpdateTime(w.getCreateTime());
        wsMapper.insert(w);
        int n = 0;
        for (Material p : legacy) {
            Map<String, Object> src = new LinkedHashMap<>(p.getSource());
            Long origin = asLong(src.get("originId"));
            src.put("workspaceId", w.getId());
            src.put("workspaceTitle", w.getTitle());
            materialService.updateSourceOf(p.getId(), src);
            if (origin == null || itemMapper.selectCount(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, w.getId())
                    .eq(PortableItem::getOriginId, origin)) > 0) {
                continue;
            }
            PortableItem it = new PortableItem();
            it.setWorkspaceId(w.getId());
            it.setOriginId(origin);
            it.setStatus(PortableItem.DONE);
            it.setPortableId(p.getId());
            it.setLeaks(0);
            it.setUpdateTime(LocalDateTime.now());
            itemMapper.insert(it);
            n++;
        }
        log.info("早期架空版 {} 条归入工作区「{}」（{} 个条目）", legacy.size(), w.getTitle(), n);
    }

    // ------------------------------------------------------------------ 工作区

    public List<PortableWorkspace> list() {
        List<PortableWorkspace> list = wsMapper.selectList(new LambdaQueryWrapper<PortableWorkspace>().orderByDesc(PortableWorkspace::getUpdateTime));
        Map<Long, Map<String, Long>> counts = countsByWorkspace();
        for (PortableWorkspace w : list) {
            w.setCounts(counts.getOrDefault(w.getId(), emptyCounts()));
            w.setCurrent(currentTitles(w.getId()));
        }
        return list;
    }

    public PortableWorkspace detail(Long id) {
        PortableWorkspace w = require(id);
        w.setCounts(countsByWorkspace().getOrDefault(id, emptyCounts()));
        w.setCurrent(currentTitles(id));
        return w;
    }

    /** body {title?, targetWorld?, model?} */
    public PortableWorkspace create(Map<String, Object> body) {
        Map<String, Object> b = body == null ? Map.of() : body;
        PortableWorkspace w = new PortableWorkspace();
        long n = wsMapper.selectCount(null) + 1;
        String title = str(b.get("title"));
        w.setTitle(title == null ? "架空工作区 " + n : trim(title, 60));
        w.setTargetWorld(trim(Objects.toString(b.get("targetWorld"), "").trim(), 200));
        w.setModel(model(b.get("model")));
        w.setFilter(Map.of());
        w.setStatus(PortableWorkspace.IDLE);
        w.setCreateTime(LocalDateTime.now());
        w.setUpdateTime(w.getCreateTime());
        wsMapper.insert(w);
        return detail(w.getId());
    }

    /** body {title?, targetWorld?, model?, filter?}：改名时同步它产出的架空版里记的工作区名 */
    @SuppressWarnings("unchecked")
    public PortableWorkspace update(Long id, Map<String, Object> body) {
        PortableWorkspace w = require(id);
        Map<String, Object> b = body == null ? Map.of() : body;
        PortableWorkspace patch = new PortableWorkspace();
        patch.setId(id);
        String title = str(b.get("title"));
        boolean renamed = title != null && !title.trim().equals(w.getTitle());
        if (title != null) {
            patch.setTitle(trim(title.trim(), 60));
        }
        if (b.containsKey("targetWorld")) {
            if (Objects.equals(runningWs, id)) {
                throw new BizException(400, "正在加工，先暂停再改示例世界");
            }
            patch.setTargetWorld(trim(Objects.toString(b.get("targetWorld"), "").trim(), 200));
        }
        if (b.get("model") instanceof Map<?, ?>) {
            patch.setModel(model(b.get("model")));
        }
        if (b.get("filter") instanceof Map<?, ?> f) {
            patch.setFilter(cleanFilter((Map<String, Object>) f));
        }
        patch.setUpdateTime(LocalDateTime.now());
        wsMapper.updateById(patch);
        if (renamed) {
            for (PortableItem it : items(id)) {
                Material p = it.getPortableId() == null ? null : materialMapper.selectById(it.getPortableId());
                if (p != null && p.getSource() != null) {
                    Map<String, Object> src = new LinkedHashMap<>(p.getSource());
                    src.put("workspaceTitle", patch.getTitle());
                    materialService.updateSourceOf(p.getId(), src);
                }
            }
        }
        return detail(id);
    }

    /** 删除前：它产出了多少条架空版 */
    public Map<String, Object> deletePreview(Long id) {
        require(id);
        long portables = itemMapper.selectCount(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, id)
                .isNotNull(PortableItem::getPortableId));
        return Map.of("portables", portables, "blocked", Objects.equals(runningWs, id) ? "正在加工，先暂停再删除" : "");
    }

    /** body {withMaterials}：true = 它产出的架空版一并删掉；false = 架空版留在素材库 */
    public Map<String, Object> delete(Long id, Map<String, Object> body) {
        require(id);
        if (Objects.equals(runningWs, id)) {
            throw new BizException(400, "正在加工，先暂停再删除");
        }
        int removed = 0;
        if (body != null && Boolean.TRUE.equals(body.get("withMaterials"))) {
            for (PortableItem it : items(id)) {
                if (it.getPortableId() != null && materialMapper.selectById(it.getPortableId()) != null) {
                    materialService.delete(it.getPortableId());
                    removed++;
                }
            }
        }
        itemMapper.delete(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, id));
        wsMapper.deleteById(id);
        return Map.of("deletedMaterials", removed);
    }

    // ------------------------------------------------------------------ 工作区里的素材

    /**
     * 全库原素材（排除架空版和已并入主条目的成员），带它在这个工作区的状态。
     * q：{category, sourceBook, keyword, tags, tagMode, state: all|none|QUEUED|RUNNING|DONE|FAILED, page, size}
     * → {total, records: [{id, title, category, subtype, sourceBook, summary, state, error, leaks, portable?: {id, title, portability}}]}
     */
    public Map<String, Object> materials(Long id, Map<String, Object> q) {
        require(id);
        String state = Objects.toString(q.get("state"), "all");
        int page = q.get("page") instanceof Number n ? n.intValue() : parseInt(q.get("page"), 1);
        int size = q.get("size") instanceof Number n ? n.intValue() : parseInt(q.get("size"), 50);
        Page<Material> pg = materialService.search(str(q.get("category")), tags(q.get("tags")), str(q.get("tagMode")),
                str(q.get("keyword")), str(q.get("sourceBook")), null, null, "origin", null, stateFilter(id, state), page, Math.min(size, 100));
        Map<Long, PortableItem> byOrigin = new HashMap<>();
        List<Long> ids = pg.getRecords().stream().map(Material::getId).toList();
        if (!ids.isEmpty()) {
            itemMapper.selectList(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, id).in(PortableItem::getOriginId, ids))
                    .forEach(it -> byOrigin.put(it.getOriginId(), it));
        }
        Set<Long> pids = new HashSet<>();
        byOrigin.values().forEach(it -> {
            if (it.getPortableId() != null) {
                pids.add(it.getPortableId());
            }
        });
        Map<Long, Material> portables = new HashMap<>();
        if (!pids.isEmpty()) {
            materialMapper.selectBatchIds(pids).forEach(m -> portables.put(m.getId(), m));
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Material m : pg.getRecords()) {
            PortableItem it = byOrigin.get(m.getId());
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("id", m.getId());
            r.put("title", m.getTitle());
            r.put("category", m.getCategory());
            r.put("subtype", m.getSubtype());
            r.put("sourceBook", m.getSourceBook());
            r.put("summary", m.getSummary());
            r.put("otherPortables", m.getPortables() == null ? 0
                    : m.getPortables().stream().filter(x -> !Objects.equals(asLong(x.get("workspaceId")), id)).count());
            r.put("state", it == null ? "none" : it.getStatus());
            if (it != null) {
                r.put("error", it.getError());
                r.put("leaks", it.getLeaks());
                Material p = it.getPortableId() == null ? null : portables.get(it.getPortableId());
                if (p != null) {
                    Map<String, Object> pm = new LinkedHashMap<>();
                    pm.put("id", p.getId());
                    pm.put("title", p.getTitle());
                    pm.put("portability", p.getProfile() != null && p.getProfile().get("portable") instanceof Map<?, ?> pp ? pp.get("portability") : null);
                    r.put("portable", pm);
                }
            }
            rows.add(r);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", pg.getTotal());
        out.put("records", rows);
        return out;
    }

    /**
     * 加入待加工。body {ids: [原素材 id]} 或 {all: true, filter: {category, sourceBook, keyword, tags, tagMode}}；
     * redo = true 时已加工的也重新排队（重做会更新它原来那条架空版）。失败的总是重新排队。→ {added, requeued, skipped}
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> enqueue(Long id, Map<String, Object> body) {
        require(id);
        Map<String, Object> b = body == null ? Map.of() : body;
        boolean redo = Boolean.TRUE.equals(b.get("redo"));
        List<Long> ids = new ArrayList<>();
        if (Boolean.TRUE.equals(b.get("all"))) {
            Map<String, Object> f = b.get("filter") instanceof Map<?, ?> m ? cleanFilter((Map<String, Object>) m) : Map.of();
            Consumer<LambdaQueryWrapper<Material>> extra = redo ? null : stateFilter(id, "notDone");
            for (int page = 1; ids.size() < MAX_ENQUEUE; page++) {
                Page<Material> pg = materialService.search(str(f.get("category")), tags(f.get("tags")), str(f.get("tagMode")),
                        str(f.get("keyword")), str(f.get("sourceBook")), null, null, "origin", null, extra, page, 100);
                if (pg.getRecords().isEmpty()) {
                    break;
                }
                pg.getRecords().forEach(m -> ids.add(m.getId()));
            }
            PortableWorkspace patch = new PortableWorkspace();
            patch.setId(id);
            patch.setFilter(f);
            patch.setUpdateTime(LocalDateTime.now());
            wsMapper.updateById(patch);
        } else if (b.get("ids") instanceof List<?> l) {
            l.stream().map(PortableWorkspaceService::asLong).filter(Objects::nonNull).distinct().limit(MAX_ENQUEUE).forEach(ids::add);
        }
        int added = 0;
        int requeued = 0;
        int skipped = 0;
        Map<Long, PortableItem> existing = new HashMap<>();
        for (int i = 0; i < ids.size(); i += 500) {
            itemMapper.selectList(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, id)
                    .in(PortableItem::getOriginId, ids.subList(i, Math.min(ids.size(), i + 500)))).forEach(it -> existing.put(it.getOriginId(), it));
        }
        LocalDateTime now = LocalDateTime.now();
        for (Long oid : ids) {
            PortableItem it = existing.get(oid);
            if (it == null) {
                Material m = materialMapper.selectById(oid);
                if (m == null || MaterialService.isPortable(m) || m.getMergedInto() != null) {
                    skipped++;
                    continue;
                }
                PortableItem n = new PortableItem();
                n.setWorkspaceId(id);
                n.setOriginId(oid);
                n.setStatus(PortableItem.QUEUED);
                n.setLeaks(0);
                n.setUpdateTime(now);
                itemMapper.insert(n);
                added++;
            } else if (PortableItem.FAILED.equals(it.getStatus()) || redo && PortableItem.DONE.equals(it.getStatus())) {
                itemMapper.update(null, new LambdaUpdateWrapper<PortableItem>().eq(PortableItem::getId, it.getId())
                        .set(PortableItem::getStatus, PortableItem.QUEUED).set(PortableItem::getError, null).set(PortableItem::getUpdateTime, now));
                requeued++;
            } else {
                skipped++;
            }
        }
        touch(id);
        return Map.of("added", added, "requeued", requeued, "skipped", skipped);
    }

    /** 移出：只移出待加工 / 失败的（已加工的有架空版，留着；加工中的等它做完） → {removed} */
    public Map<String, Object> dequeue(Long id, Map<String, Object> body) {
        require(id);
        List<Long> ids = body != null && body.get("ids") instanceof List<?> l
                ? l.stream().map(PortableWorkspaceService::asLong).filter(Objects::nonNull).toList() : List.of();
        if (ids.isEmpty()) {
            return Map.of("removed", 0);
        }
        int n = itemMapper.delete(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, id)
                .in(PortableItem::getOriginId, ids).in(PortableItem::getStatus, PortableItem.QUEUED, PortableItem.FAILED));
        touch(id);
        return Map.of("removed", n);
    }

    // ------------------------------------------------------------------ 加工

    public synchronized PortableWorkspace start(Long id) {
        PortableWorkspace w = require(id);
        if (runningWs != null) {
            PortableWorkspace other = wsMapper.selectById(runningWs);
            throw new BizException(400, Objects.equals(runningWs, id) ? "已经在加工了"
                    : "工作区「" + (other == null ? runningWs : other.getTitle()) + "」正在加工，同一时间只跑一个，请等它结束或先暂停");
        }
        long queued = itemMapper.selectCount(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, id)
                .eq(PortableItem::getStatus, PortableItem.QUEUED));
        if (queued == 0) {
            throw new BizException(400, "没有待加工的素材：先勾选素材加入待加工");
        }
        NovelExtractService.ModelChoice choice = choose(w.getModel());
        runningWs = id;
        stopRequested = false;
        stopReason = null;
        setStatus(id, PortableWorkspace.RUNNING, "加工中（" + choice.label() + "，待加工 " + queued + " 条）");
        runner.submit(() -> run(w, choice.config()));
        return detail(id);
    }

    public PortableWorkspace pause(Long id) {
        require(id);
        if (Objects.equals(runningWs, id)) {
            stopRequested = true;
            stopReason = "已暂停";
            setStatus(id, PortableWorkspace.RUNNING, "正在暂停…（正在加工的几条做完后停下）");
        }
        return detail(id);
    }

    private void run(PortableWorkspace w, AiModelConfig cfg) {
        int workers = cfg == null || cfg.getConcurrency() == null ? 1 : Math.max(1, Math.min(8, cfg.getConcurrency()));
        ExecutorService pool = Executors.newFixedThreadPool(workers);
        int[] done = {0, 0};
        try {
            for (int k = 0; k < workers; k++) {
                pool.submit(() -> {
                    PortableItem it;
                    while (!stopRequested && (it = claim(w.getId())) != null) {
                        boolean ok = process(w, it, cfg);
                        synchronized (done) {
                            done[ok ? 0 : 1]++;
                        }
                    }
                });
            }
            pool.shutdown();
            while (!pool.awaitTermination(1, TimeUnit.SECONDS)) {
                if (Thread.currentThread().isInterrupted()) {
                    pool.shutdownNow();
                    break;
                }
            }
        } catch (InterruptedException e) {
            pool.shutdownNow();
            Thread.currentThread().interrupt();
        } finally {
            String summary = "本次加工 " + done[0] + " 条" + (done[1] > 0 ? "，失败 " + done[1] + " 条" : "");
            if (stopRequested) {
                setStatus(w.getId(), PortableWorkspace.PAUSED, (stopReason == null ? "已暂停" : stopReason) + "：" + summary + "，点「继续」接着加工");
            } else {
                setStatus(w.getId(), PortableWorkspace.IDLE, "完成：" + summary);
            }
            runningWs = null;
        }
    }

    /** 取下一条待加工的，标为加工中（多个线程同时取，所以同步） */
    private synchronized PortableItem claim(Long wsId) {
        PortableItem it = itemMapper.selectOne(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, wsId)
                .eq(PortableItem::getStatus, PortableItem.QUEUED).orderByAsc(PortableItem::getId).last("LIMIT 1"));
        if (it != null) {
            itemMapper.update(null, new LambdaUpdateWrapper<PortableItem>().eq(PortableItem::getId, it.getId())
                    .set(PortableItem::getStatus, PortableItem.RUNNING).set(PortableItem::getUpdateTime, LocalDateTime.now()));
        }
        return it;
    }

    private boolean process(PortableWorkspace w, PortableItem it, AiModelConfig cfg) {
        Material origin = materialMapper.selectById(it.getOriginId());
        if (origin == null || MaterialService.isPortable(origin)) {
            finishItem(it.getId(), PortableItem.FAILED, null, 0, "原素材已删除");
            return false;
        }
        try {
            PortableWorkspace fresh = wsMapper.selectById(w.getId());
            Material p = makeOne(origin, fresh == null ? w : fresh, it.getPortableId(), cfg);
            int leaks = p.getProfile() != null && p.getProfile().get("portable") instanceof Map<?, ?> pp
                    && pp.get("leaks") instanceof List<?> l ? l.size() : 0;
            finishItem(it.getId(), PortableItem.DONE, p.getId(), leaks, null);
            return true;
        } catch (ResourceAccessException e) {
            finishItem(it.getId(), PortableItem.QUEUED, it.getPortableId(), it.getLeaks() == null ? 0 : it.getLeaks(), null);
            stopRequested = true;
            stopReason = "AI 服务不可达，已暂停";
            return false;
        } catch (BizException e) {
            finishItem(it.getId(), PortableItem.FAILED, it.getPortableId(), 0, e.getMessage());
            if (e.getCode() == 402) {
                stopRequested = true; // Key 无效 / 余额不足：后面的也不会成功
                stopReason = "模型不可用（" + e.getMessage() + "），已暂停";
            }
            return false;
        } catch (Exception e) {
            log.warn("架空加工失败，materialId={}：{}", origin.getId(), e.getMessage());
            finishItem(it.getId(), PortableItem.FAILED, it.getPortableId(), 0, e.getMessage());
            return false;
        }
    }

    private void finishItem(Long itemId, String status, Long portableId, int leaks, String error) {
        itemMapper.update(null, new LambdaUpdateWrapper<PortableItem>().eq(PortableItem::getId, itemId)
                .set(PortableItem::getStatus, status).set(PortableItem::getPortableId, portableId)
                .set(PortableItem::getLeaks, leaks).set(PortableItem::getError, error == null ? null : trim(error, 300))
                .set(PortableItem::getUpdateTime, LocalDateTime.now()));
    }

    /** 一条原素材 → Python → 新建 / 更新它在这个工作区的架空版（existing = 这个工作区之前生成的那条） */
    @SuppressWarnings("unchecked")
    private Material makeOne(Material origin, PortableWorkspace ws, Long existing, AiModelConfig cfg) {
        JsonNode res;
        try {
            res = aiClient.materialPortable(item(origin), Objects.toString(ws.getTargetWorld(), ""), cfg);
        } catch (ResourceAccessException e) {
            throw e;
        } catch (Exception e) {
            throw new BizException(502, "AI 服务出错");
        }
        if (!res.path("ok").asBoolean(false)) {
            throw new BizException(res.path("fatal").asBoolean(false) ? 402 : 400, "架空加工失败：" + res.path("message").asText("未知原因"));
        }
        Map<String, Object> portable = MaterialService.cleanPortable(objectMapper.convertValue(res.path("portable"), Map.class));
        if (existing != null && materialMapper.selectById(existing) == null) {
            existing = null; // 架空版被删掉了：重新建一条
        }
        Material req = new Material();
        req.setId(existing);
        req.setCategory(origin.getCategory());
        req.setSubtype(origin.getSubtype());
        req.setTitle(origin.getTitle()); // 模型没给通用名时先用原名（applyPortable 会换成通用名）
        req.setTags(new ArrayList<>()); // 原素材的标签多是原作词（穿越、神术……），不带过来；applyPortable 加「架空」
        req.setSourceBook(origin.getSourceBook() == null ? "" : origin.getSourceBook());
        Map<String, Object> profile = new LinkedHashMap<>();
        if (origin.getProfile() != null && origin.getProfile().get("tier") != null) {
            profile.put("tier", origin.getProfile().get("tier"));
            profile.put("tierReason", "同原素材");
        }
        profile.put("portable", portable);
        req.setProfile(profile);
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("type", MaterialService.PORTABLE_TYPE);
        source.put("originId", origin.getId());
        source.put("originTitle", origin.getTitle());
        source.put("originBook", origin.getSourceBook());
        source.put("originUpdateTime", (origin.getUpdateTime() == null ? LocalDateTime.now() : origin.getUpdateTime()).toString());
        source.put("workspaceId", ws.getId());
        source.put("workspaceTitle", ws.getTitle());
        if (origin.getSource() != null && origin.getSource().get("resonance") != null) {
            source.put("resonance", origin.getSource().get("resonance")); // 共鸣素材：关系图跟着走，说明页显示节点对应
        }
        req.setSource(source);
        Material saved = materialService.save(req);
        if (existing != null) {
            materialService.updateSourceOf(existing, source); // save 不改已有素材的 source：重做时刷新原素材的时间等
        }
        return materialService.get(saved.getId());
    }

    private static Map<String, Object> item(Material m) {
        Map<String, Object> item = new LinkedHashMap<>();
        Map<String, Object> src = m.getSource() == null ? Map.of() : m.getSource();
        item.put("id", m.getId());
        item.put("category", m.getCategory());
        item.put("kind", "resonance".equals(m.getCategory()) ? "resonance" : "craft".equals(m.getCategory()) ? "craft" : "entity");
        item.put("title", m.getTitle());
        item.put("subtype", m.getSubtype());
        item.put("summary", m.getSummary());
        item.put("detail", m.getDetail());
        item.put("attributes", m.getAttributes());
        if (src.get("facts") instanceof List<?> fs) {
            item.put("facts", fs.size() > 8 ? fs.subList(0, 8) : fs);
        }
        if (src.get("resonance") instanceof Map<?, ?> r) {
            item.put("nodes", r.get("nodes"));
            item.put("rules", r.get("rules"));
        }
        return item;
    }

    // ------------------------------------------------------------------ 工具

    /** 工作区里的状态筛选：none = 没加入；notDone = 没加入或没加工完（「加入当前筛选全部」默认用）；其余 = 条目状态 */
    private Consumer<LambdaQueryWrapper<Material>> stateFilter(Long wsId, String state) {
        if ("none".equals(state)) {
            return q -> q.apply("id NOT IN (SELECT origin_id FROM portable_item WHERE workspace_id = {0})", wsId);
        }
        if ("notDone".equals(state)) {
            return q -> q.apply("id NOT IN (SELECT origin_id FROM portable_item WHERE workspace_id = {0} AND status = 'DONE')", wsId);
        }
        if (STATES.contains(state)) {
            return q -> q.apply("id IN (SELECT origin_id FROM portable_item WHERE workspace_id = {0} AND status = {1})", wsId, state);
        }
        return null;
    }

    private Map<Long, Map<String, Long>> countsByWorkspace() {
        Map<Long, Map<String, Long>> out = new HashMap<>();
        for (Map<String, Object> row : itemMapper.selectMaps(new QueryWrapper<PortableItem>()
                .select("workspace_id AS ws", "status AS st", "COUNT(*) AS n").groupBy("workspace_id", "status"))) {
            Long ws = asLong(row.get("ws"));
            out.computeIfAbsent(ws, k -> emptyCounts()).put(String.valueOf(row.get("st")), asLong(row.get("n")));
        }
        return out;
    }

    private static Map<String, Long> emptyCounts() {
        Map<String, Long> m = new LinkedHashMap<>();
        STATES.forEach(s -> m.put(s, 0L));
        return m;
    }

    private List<String> currentTitles(Long wsId) {
        List<Long> ids = itemMapper.selectList(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, wsId)
                .eq(PortableItem::getStatus, PortableItem.RUNNING)).stream().map(PortableItem::getOriginId).toList();
        return ids.isEmpty() ? List.of() : materialMapper.selectBatchIds(ids).stream().map(Material::getTitle).toList();
    }

    private List<PortableItem> items(Long wsId) {
        return itemMapper.selectList(new LambdaQueryWrapper<PortableItem>().eq(PortableItem::getWorkspaceId, wsId));
    }

    private PortableWorkspace require(Long id) {
        PortableWorkspace w = id == null ? null : wsMapper.selectById(id);
        if (w == null) {
            throw new BizException(404, "架空工作区不存在：" + id);
        }
        return w;
    }

    private void setStatus(Long id, String status, String message) {
        wsMapper.update(null, new LambdaUpdateWrapper<PortableWorkspace>().eq(PortableWorkspace::getId, id)
                .set(PortableWorkspace::getStatus, status).set(PortableWorkspace::getMessage, trim(message, 500))
                .set(PortableWorkspace::getUpdateTime, LocalDateTime.now()));
    }

    private void touch(Long id) {
        wsMapper.update(null, new LambdaUpdateWrapper<PortableWorkspace>().eq(PortableWorkspace::getId, id)
                .set(PortableWorkspace::getUpdateTime, LocalDateTime.now()));
    }

    private NovelExtractService.ModelChoice choose(Map<String, Object> model) {
        NovelExtractService.ModelChoice choice = extractService.resolveModel(model);
        if (choice.local() != null && !"gguf".equals(choice.local().get("source"))) {
            throw new BizException(400, "架空加工只支持大模型或 GGUF");
        }
        return choice;
    }

    private static Map<String, Object> model(Object v) {
        return Map.of("source", v instanceof Map<?, ?> m && "gguf".equals(m.get("source")) ? "gguf" : "api");
    }

    private static Map<String, Object> cleanFilter(Map<String, Object> f) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (String k : List.of("category", "sourceBook", "keyword", "tagMode")) {
            String v = str(f.get(k));
            if (v != null) {
                out.put(k, trim(v, 100));
            }
        }
        List<String> tags = tags(f.get("tags"));
        if (tags != null && !tags.isEmpty()) {
            out.put("tags", tags);
        }
        return out;
    }

    private static List<String> tags(Object v) {
        if (v instanceof List<?> l) {
            return l.stream().map(String::valueOf).filter(s -> !s.isBlank()).limit(12).toList();
        }
        String s = str(v);
        return s == null ? null : List.of(s.split(",")).stream().map(String::trim).filter(x -> !x.isEmpty()).limit(12).toList();
    }

    private static String str(Object v) {
        return v == null || String.valueOf(v).isBlank() ? null : String.valueOf(v).trim();
    }

    private static String trim(String s, int n) {
        return s == null || s.length() <= n ? s : s.substring(0, n);
    }

    private static int parseInt(Object v, int dflt) {
        try {
            return v == null ? dflt : Integer.parseInt(String.valueOf(v));
        } catch (NumberFormatException e) {
            return dflt;
        }
    }

    private static Long asLong(Object v) {
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return v == null ? null : Long.parseLong(String.valueOf(v));
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
