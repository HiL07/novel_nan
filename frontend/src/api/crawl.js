import request from './request'

// 网络小说抓取（Java /api/novel/crawl/**，转发给 Python /api/crawl/**）。两种采集模式：
// - 单本 mode=book：给一本书的目录页 → 一个 txt；
//      options = {url, preset?, rule?, delayMs?, respectRobots?, startIndex?, endIndex?}
// - 整站 / 全自动 mode=site：书单来自站点书目（见下方 catalogs，按 AI 学到的规律采集）→ 每本一个 txt；
//      options = {url（站点首页）, preset?（learned:<规则id>）, rule?, delayMs?, respectRobots?, maxChaptersPerBook?,
//                 books:[{tocUrl, bookName?, author?, category?}]}
// rule 字段：{categoryLinks, bookLinks, listNext, tocLink, bookName, author, intro, tags,
//            chapterLinks, tocNext, content, contentNext, encoding, removePatterns[]}

/** 规则预设 [{key, name, description, domains, rule}]，GET /api/novel/crawl/presets */
export function listCrawlPresets() {
  return request.get('/api/novel/crawl/presets').then((res) => res.data)
}

/**
 * 单本：解析目录 + 试抓第一章（同步，目录分页多时可能较慢）
 * POST /api/novel/crawl/preview → {bookName, author, intro, chapters[{title,url}], chapterCount, tocPages, preset, rule, sample}
 */
export function previewCrawl(options) {
  return request.post('/api/novel/crawl/preview', options, { timeout: 180000 }).then((res) => res.data)
}

/** 提交抓取任务（异步），POST /api/novel/crawl/submit（按 options.mode 分派单本 / 整站） */
export function submitCrawl(options) {
  return request.post('/api/novel/crawl/submit', options).then((res) => res.data)
}

/** 提交整站抓取任务（异步，逐本抓取，每本一个 txt），POST /api/novel/crawl/site/submit */
export function submitSiteCrawl(options) {
  return request.post('/api/novel/crawl/site/submit', options).then((res) => res.data)
}

/** 任务列表（按创建时间倒序），GET /api/novel/crawl/list */
export function listCrawls() {
  return request.get('/api/novel/crawl/list').then((res) => res.data)
}

/** 整站任务的书籍明细，GET /api/novel/crawl/{id}/books（单本任务返回空数组） */
export function listCrawlBooks(id) {
  return request.get(`/api/novel/crawl/${id}/books`).then((res) => res.data)
}

/** 取消，POST /api/novel/crawl/{id}/cancel */
export function cancelCrawl(id) {
  return request.post(`/api/novel/crawl/${id}/cancel`).then((res) => res.data)
}

/** 按原参数重新抓取，POST /api/novel/crawl/{id}/retry */
export function retryCrawl(id) {
  return request.post(`/api/novel/crawl/${id}/retry`).then((res) => res.data)
}

/**
 * 从断点继续（同一任务；已抓章节不重抓，整站跳过已完成的书），POST /api/novel/crawl/{id}/resume
 * newOrigin：站点换了域名 / IP（路径不变）时填 http(s)://新域名[:端口]，可空
 */
export function resumeCrawl(id, newOrigin) {
  return request.post(`/api/novel/crawl/${id}/resume`, newOrigin ? { newOrigin } : {}).then((res) => res.data)
}

/** 断点概况 {chapterSaved, chapterTotal, booksWithCheckpoint, booksPending, url}，GET /api/novel/crawl/{id}/checkpoint */
export function getCrawlCheckpoint(id) {
  return request.get(`/api/novel/crawl/${id}/checkpoint`).then((res) => res.data)
}

// ---------------------------------------------------------------- AI 解析地址 / 学到的站点规则

/**
 * AI 解析地址（后台任务，用当前激活的大模型）：先试已学 / 内置规则，失败再让大模型看页面结构写 XPath，
 * 每次都真实试抓（目录 + 两章正文），成功后总结地址规律并按域名存为站点规则。
 * POST /api/novel/crawl/ai/analyze {url, maxAttempts?(1~10), delayMs?, respectRobots?, hint?, useKnown?} → job
 */
export function analyzeCrawlUrl(options) {
  return request.post('/api/novel/crawl/ai/analyze', options).then((res) => res.data)
}

/**
 * AI 解析任务状态 GET /api/novel/crawl/ai/jobs/{jobId}
 * → {jobId, url, status, progress, message, error, maxAttempts, savedRuleId?,
 *    attempts:[{index, strategy, reason, tocUrl, rule, ok, chapterCount, sampleChars, error, seconds}],
 *    result:{host, siteName, tocUrl, rule, summary, bookUrlPattern, tocUrlPattern, chapterUrlPattern, preview}}
 */
export function getCrawlAiJob(jobId) {
  return request.get(`/api/novel/crawl/ai/jobs/${jobId}`).then((res) => res.data)
}

/** 取消 AI 解析（当前这次尝试结束后停止），POST /api/novel/crawl/ai/jobs/{jobId}/cancel */
export function cancelCrawlAiJob(jobId) {
  return request.post(`/api/novel/crawl/ai/jobs/${jobId}/cancel`).then((res) => res.data)
}

/**
 * AI 解析出的站点规则，GET /api/novel/crawl/rules?status=PENDING|CONFIRMED（空 = 全部，待确认在前）
 * 每条 {id, host, siteName, status, rule, summary, *UrlPattern, sampleUrl, tocUrl, bookName, ruleFile(相对 data/), …}；
 * 只有 CONFIRMED 的会按域名自动套用
 */
export function listCrawlRules(status) {
  return request.get('/api/novel/crawl/rules', { params: status ? { status } : {} }).then((res) => res.data)
}

/** 确认待确认的规则（替换该域名原来已确认的），POST /api/novel/crawl/rules/{id}/confirm */
export function confirmCrawlRule(id) {
  return request.post(`/api/novel/crawl/rules/${id}/confirm`).then((res) => res.data)
}

/** 不确认：丢弃待确认的规则，POST /api/novel/crawl/rules/{id}/reject */
export function rejectCrawlRule(id) {
  return request.post(`/api/novel/crawl/rules/${id}/reject`).then((res) => res.data)
}

/** 删除学到的站点规则，POST /api/novel/crawl/rules/{id}/delete */
export function deleteCrawlRule(id) {
  return request.post(`/api/novel/crawl/rules/${id}/delete`).then((res) => res.data)
}

// ---------------------------------------------------------------- 常用地址（用户收藏的可抓取网址）

/** 常用地址（最近用过的在前），GET /api/novel/crawl/saved-urls → [{id, url, name, mode, note, useCount, lastUsedTime}] */
export function listSavedUrls() {
  return request.get('/api/novel/crawl/saved-urls').then((res) => res.data)
}

/** 收藏 / 修改常用地址（同地址已存在则更新），POST /api/novel/crawl/saved-urls/save {id?, url, name?, mode?, note?} */
export function saveSavedUrl(data) {
  return request.post('/api/novel/crawl/saved-urls/save', data).then((res) => res.data)
}

/** 选用一次（排序用），POST /api/novel/crawl/saved-urls/{id}/use */
export function useSavedUrl(id) {
  return request.post(`/api/novel/crawl/saved-urls/${id}/use`).then((res) => res.data)
}

/** 删除常用地址，POST /api/novel/crawl/saved-urls/{id}/delete */
export function deleteSavedUrl(id) {
  return request.post(`/api/novel/crawl/saved-urls/${id}/delete`).then((res) => res.data)
}

// ---------------------------------------------------------------- 全自动爬虫：站点书目（/api/novel/crawl/catalogs/**）
// 按 AI 解析学到的规律测试 → 决定是否使用 → 扩充书目 / 筛选 → 选中的书用 submitSiteCrawl 逐本抓取

/** 全部站点书目（一个首页一份），GET /api/novel/crawl/catalogs */
export function listCatalogs() {
  return request.get('/api/novel/crawl/catalogs').then((res) => res.data)
}

/**
 * 开始测试 / 扩充书目（后台任务），POST /api/novel/crawl/catalogs/start
 * body = {ruleId, phase: 'test'|'scan', maxBooks?, maxCategories?, maxListPages?, contentSamples?, tocPages?, delayMs?, respectRobots?}
 */
export function startCatalog(body) {
  return request.post('/api/novel/crawl/catalogs/start', body).then((res) => res.data)
}

/** 书目状态 / 进度 / 测试报告（report = 测试，lastReport = 最近一次采集），GET /api/novel/crawl/catalogs/{id} */
export function getCatalog(id) {
  return request.get(`/api/novel/crawl/catalogs/${id}`).then((res) => res.data)
}

export function cancelCatalog(id) {
  return request.post(`/api/novel/crawl/catalogs/${id}/cancel`).then((res) => res.data)
}

/** 决定是否使用：decision = USED | REJECTED | PENDING */
export function decideCatalog(id, decision) {
  return request.post(`/api/novel/crawl/catalogs/${id}/decide`, { decision }).then((res) => res.data)
}

export function deleteCatalog(id) {
  return request.post(`/api/novel/crawl/catalogs/${id}/delete`).then((res) => res.data)
}

/**
 * 书目分页筛选，GET /api/novel/crawl/catalogs/{id}/books
 * params = {keyword?（书名模糊）, author?（作者模糊）, tagKeyword?（类型，标签模糊）, category?, tags?: 'a,b', tagMode?: any|all, usable?, page, size}
 * → {records:[{id, bookName, author, category, tags[], aiTags[], intro, bookUrl, tocUrl, chapterCount, firstChapter,
 *              latestChapter, tocOk, contentOk, contentChars, error, crawl?{status, fileId, crawlId}}], total, page, size}
 */
export function listCatalogBooks(id, params) {
  return request.get(`/api/novel/crawl/catalogs/${id}/books`, { params }).then((res) => res.data)
}

/** 标签云与分类 → {tags[{tag, count, site, ai}], categories[{name, count}], total} */
export function getCatalogTags(id) {
  return request.get(`/api/novel/crawl/catalogs/${id}/tags`).then((res) => res.data)
}

/** 一本书采集时保存的完整目录 → {bookName, tocUrl, chapterCount, chapters[{title, url}], savedAt} */
export function getCatalogBookToc(bookId) {
  return request.get(`/api/novel/crawl/catalogs/books/${bookId}/toc`).then((res) => res.data)
}

/** 按情节找书 · AI 选标签（省 token）：从书目已有标签里挑 → {tags, suggested, reason, usage, model} */
export function plotTagsCatalog(id, query) {
  return request.post(`/api/novel/crawl/catalogs/${id}/plot-tags`, { query }, { timeout: 180000 }).then((res) => res.data)
}

/**
 * 按情节找书 · AI 读简介（耗 token）：body = {query, filter?（当前筛选，只分析筛出的书）, threshold?, estimate?}
 * estimate=true → {books, matched, truncated, batches, promptTokens, completionTokens, model}（不调用模型）
 * 否则 → {results[书 + score + reason], analyzed, scored, batches, failedBatches, errors, usage, model}
 */
export function introMatchCatalog(id, body) {
  return request.post(`/api/novel/crawl/catalogs/${id}/intro-match`, body, { timeout: 900000 }).then((res) => res.data)
}

/** AI 补标签（按书名 / 简介）{limit?, retag?} → {tagged, remaining, model} */
export function aiTagCatalog(id, body = {}) {
  return request.post(`/api/novel/crawl/catalogs/${id}/ai-tags`, body, { timeout: 600000 }).then((res) => res.data)
}
