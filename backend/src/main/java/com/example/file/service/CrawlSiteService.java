package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.CrawlSite;
import com.example.file.entity.CrawlSiteCatalog;
import com.example.file.entity.CrawlSiteRule;
import com.example.file.mapper.CrawlSiteCatalogMapper;
import com.example.file.mapper.CrawlSiteMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 小说抓取页「小说网站爬取」：用户指定的小说网站。新增时任何站内地址（书籍页 / 目录页 / 首页）都归一为首页
 * scheme://host[:port]/，同一首页只存一行（再次新增 = 更新名称和样例地址）；原地址留作 AI 解析的样例书。
 * 列表附带该站的 AI 解析规则状态（{@link CrawlRuleService}）与全自动书目概况（crawl_site_catalog，按首页关联）。
 */
@Service
public class CrawlSiteService {

    private static final Logger log = LoggerFactory.getLogger(CrawlSiteService.class);

    private final CrawlSiteMapper mapper;
    private final CrawlSiteCatalogMapper catalogMapper;
    private final CrawlRuleService ruleService;

    public CrawlSiteService(CrawlSiteMapper mapper, CrawlSiteCatalogMapper catalogMapper, CrawlRuleService ruleService) {
        this.mapper = mapper;
        this.catalogMapper = catalogMapper;
        this.ruleService = ruleService;
    }

    /** 全部网站，先加的在前；附规则与书目概况 */
    public List<CrawlSite> list() {
        List<CrawlSite> sites = mapper.selectList(new LambdaQueryWrapper<CrawlSite>().orderByAsc(CrawlSite::getId));
        if (sites.isEmpty()) {
            return sites;
        }
        List<CrawlSiteRule> rules = ruleService.list(null);   // 待确认 → 已确认 → 失败，同组新的在前
        for (CrawlSite site : sites) {
            site.setRule(ruleSummary(bestRule(rules, site.getHost())));
            CrawlSiteCatalog catalog = catalogMapper.selectOne(new LambdaQueryWrapper<CrawlSiteCatalog>()
                    .eq(CrawlSiteCatalog::getHomeUrl, site.getHomeUrl()).last("LIMIT 1"));
            if (catalog != null) {
                Map<String, Object> info = new LinkedHashMap<>();
                info.put("id", catalog.getId());
                info.put("decision", catalog.getDecision());
                info.put("status", catalog.getStatus());
                info.put("bookCount", catalog.getBookCount());
                site.setCatalog(info);
            }
        }
        return sites;
    }

    /**
     * 新增 / 修改：{id?, url, name?, note?}。url 可以是站内任意地址，存为首页；同一首页已存在则更新它
     * （名称为空时保留原名称，样例地址取这次填的非首页地址）。
     */
    public CrawlSite save(Map<String, Object> body) {
        if (body == null) {
            throw new BizException(400, "缺少参数");
        }
        String url = str(body.get("url"));
        String home = homeOf(url);
        if (home == null) {
            throw new BizException(400, "请输入 http:// 或 https:// 开头的网址");
        }
        Long id = body.get("id") instanceof Number n ? n.longValue() : null;
        CrawlSite same = mapper.selectOne(new LambdaQueryWrapper<CrawlSite>().eq(CrawlSite::getHomeUrl, home).last("LIMIT 1"));
        CrawlSite row;
        if (id != null) {
            row = require(id);
            if (same != null && !same.getId().equals(id)) {
                throw new BizException(400, "这个网站已经添加过了（" + home + "）");
            }
        } else {
            row = same;
        }
        LocalDateTime now = LocalDateTime.now();
        boolean insert = row == null;
        if (insert) {
            row = new CrawlSite();
            row.setCreateTime(now);
        }
        row.setHomeUrl(home);
        row.setHost(CrawlRuleService.hostOf(home));
        String name = trim(str(body.get("name")), 100);
        if (name != null || insert || id != null) {
            row.setName(name);
        }
        // 填的是站内某本书 / 目录页时记下来，AI 解析直接用它；只填了首页就保留原来的样例
        if (!isHomeOnly(url)) {
            row.setSampleUrl(trim(url, 2000));
        }
        if (body.containsKey("note")) {
            row.setNote(trim(str(body.get("note")), 500));
        }
        row.setUpdateTime(now);
        if (insert) {
            mapper.insert(row);
            log.info("新增小说网站 id={} {}", row.getId(), home);
        } else {
            mapper.updateById(row);
        }
        return row;
    }

    public void delete(Long id) {
        require(id);
        mapper.deleteById(id);
    }

    private CrawlSite require(Long id) {
        CrawlSite row = mapper.selectById(id);
        if (row == null) {
            throw new BizException(404, "该网站不存在（可能已删除）");
        }
        return row;
    }

    /** 与 CrawlRuleService#findForUrl 同口径匹配域名（忽略 www. / m. / wap.），取最相关的一条：已确认 > 待确认 > 失败 */
    private static CrawlSiteRule bestRule(List<CrawlSiteRule> rules, String host) {
        if (host == null) {
            return null;
        }
        String bare = host.replaceFirst("^(www|m|wap)\\.", "");
        // host 本身没有 www. 等前缀时与 bare 相同，Set.of 遇到重复会抛异常，所以用 HashSet
        Set<String> hosts = new HashSet<>(List.of(host, bare, "www." + bare, "m." + bare, "wap." + bare));
        for (String status : List.of(CrawlSiteRule.CONFIRMED, CrawlSiteRule.PENDING, CrawlSiteRule.FAILED)) {
            CrawlSiteRule hit = rules.stream()
                    .filter(r -> status.equals(r.getStatus()) && hosts.contains(r.getHost()))
                    .findFirst().orElse(null);
            if (hit != null) {
                return hit;
            }
        }
        return null;
    }

    private static Map<String, Object> ruleSummary(CrawlSiteRule rule) {
        if (rule == null) {
            return null;
        }
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("id", rule.getId());
        info.put("status", rule.getStatus());
        info.put("siteName", rule.getSiteName());
        info.put("error", rule.getError());
        Map<String, Object> sm = rule.getSiteMap();
        if (sm != null) {
            info.put("mastered", sm.get("mastered"));
            info.put("total", sm.get("total"));
        }
        return info;
    }

    /** 站内任意地址 → 首页 scheme://host[:port]/（scheme、域名小写）；不是 http(s) 地址返回 null */
    static String homeOf(String url) {
        if (url == null || CrawlRuleService.hostOf(url) == null) {
            return null;
        }
        try {
            URI uri = new URI(url.trim());
            int port = uri.getPort();
            String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
            boolean defaultPort = port < 0 || ("http".equals(scheme) && port == 80) || ("https".equals(scheme) && port == 443);
            return scheme + "://" + uri.getHost().toLowerCase(Locale.ROOT) + (defaultPort ? "" : ":" + port) + "/";
        } catch (Exception e) {
            return null;
        }
    }

    /** 地址本身就是首页（路径为空或 /，没有参数） */
    private static boolean isHomeOnly(String url) {
        try {
            URI uri = new URI(url.trim());
            String path = Objects.requireNonNullElse(uri.getRawPath(), "");
            return (path.isEmpty() || "/".equals(path)) && uri.getRawQuery() == null;
        } catch (Exception e) {
            return true;
        }
    }

    private static String trim(String s, int max) {
        if (s == null || s.isEmpty()) {
            return null;
        }
        return s.length() > max ? s.substring(0, max) : s;
    }

    private static String str(Object value) {
        return value == null ? null : String.valueOf(value).trim();
    }
}
