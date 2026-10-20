import request from './request'

// 网络小说抓取（Java /api/novel/crawl/**，转发给 Python /api/crawl/**）。两种采集模式：
// - 单本 mode=book：给一本书的目录页 → 一个 txt；
//      options = {url, preset?, rule?, delayMs?, respectRobots?, startIndex?, endIndex?}
// - 整站 mode=site（copybook 式：首页 → 分类 → 列表翻页 → 书籍 → 目录）→ 每本一个 txt；
//      options = {url（站点首页/分类页）, preset?, rule?, delayMs?, respectRobots?,
//                 maxCategories?, maxListPages?, maxBooks?, categories?, verify?, maxChaptersPerBook?,
//                 books:[{tocUrl, bookName?, author?, category?}]}
// rule 字段：{categoryLinks, bookLinks, listNext, tocLink, bookName, author, intro,
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

/**
 * 整站：发现书籍（同步；会逐页访问分类列表与书籍详情，书多时较慢）
 * POST /api/novel/crawl/discover
 * → {siteName, categoriesAll[{name,url}], categories[{name,url,pages,books,error}], truncated, preset, rule,
 *    bookCount, books:[{bookName, author, intro, category, tocUrl, sourceUrl, chapterCount, error}]}
 */
export function discoverCrawl(options) {
  return request.post('/api/novel/crawl/discover', options, { timeout: 300000 }).then((res) => res.data)
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
