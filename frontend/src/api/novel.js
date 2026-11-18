import request from './request'

/** 支持小说提取的扩展名（与后端 NovelExtractService 一致） */
export const EXTRACTABLE_EXTS = ['txt', 'md', 'docx', 'pdf']

export function isExtractable(ext) {
  return EXTRACTABLE_EXTS.includes((ext || '').toLowerCase())
}

/**
 * 对文件发起小说提取（异步任务，立即返回任务记录）
 * POST /api/novel/extract/{fileId} {materials?, model?}
 */
export function submitExtract(fileId, options = {}) {
  // options.materials = {enabled, categories, maxPerChunk, focus}：同时提取创作素材候选（需用户确认后入库）
  // options.model = {source: 'api', configId?}（空 = 当前启用的配置）| {source: 'local', baseId, chunkChars}
  return request.post(`/api/novel/extract/${fileId}`, options).then((res) => res.data)
}

/**
 * 取消排队中 / 进行中 / 中断的提取任务（记为失败「已取消」）
 * POST /api/novel/extract/{id}/cancel
 */
export function cancelExtract(id) {
  return request.post(`/api/novel/extract/${id}/cancel`).then((res) => res.data)
}

/**
 * 暂停排队中 / 进行中的提取任务（停下后为「已中断」，断点保留，可继续或取消）
 * POST /api/novel/extract/{id}/pause
 */
export function pauseExtract(id) {
  return request.post(`/api/novel/extract/${id}/pause`).then((res) => res.data)
}

/**
 * 删除提取工作区（正在提取 / 整理的跳过）：记录、断点、结果文件、整理记录、素材候选；
 * 这本书最后一个工作区时连同这本书的素材（保留的除外）→ {deleted, skipped, materialsDeleted, reasons[]}
 * POST /api/novel/extract/delete {ids}
 */
export function deleteExtracts(ids) {
  return request.post('/api/novel/extract/delete', { ids }).then((res) => res.data)
}

/* ---------- 卡片（卡片整理 / 素材选择，ExtractCardService） ---------- */
/** 这个工作区的卡片 [{id, kind, category, title, data, history, version, edited, status, materialId, savedVersion, match}] */
export const listCards = (id) => request.get(`/api/novel/extract/${id}/cards`).then((res) => res.data)
/** 入库前比对 → {matches: {卡片id: [{id, title, category, summary, score, reason name|alias|vector, extractId, workspace}]}, suggest: {卡片id: {action, targetId}}, vector, message?} */
export const cardMatches = (id) => request.get(`/api/novel/extract/${id}/cards/matches`, { timeout: 180000 }).then((res) => res.data)
/** 手改卡片 {title?, subtype?, summary?, detail?, attributes?, tags?, tier?, category?} */
export const updateCard = (cid, body) => request.post(`/api/novel/extract/card/${cid}`, body).then((res) => res.data)
/** 换回历史版本 */
export const restoreCard = (cid, version) => request.post(`/api/novel/extract/card/${cid}/restore`, { version }).then((res) => res.data)
/** 素材选择：items [{cardId, action: new|update|version|skip|reset, targetId?}] → {saved, updated, versions, skipped, errors} */
export const saveCards = (id, items) => request.post(`/api/novel/extract/${id}/cards/save`, { items }).then((res) => res.data)

/**
 * 删除前预览 → {book, checkpointChapters, compileCount, candidateCount, lastOfBook, materialCount, pinnedCount, blocked}
 * GET /api/novel/extract/{id}/delete-preview
 */
export function deleteExtractPreview(id) {
  return request.get(`/api/novel/extract/${id}/delete-preview`).then((res) => res.data)
}

/**
 * 改工作区名（空 = 清掉，显示书名）
 * POST /api/novel/extract/{id}/title {title}
 */
export function renameExtract(id, title) {
  return request.post(`/api/novel/extract/${id}/title`, { title }).then((res) => res.data)
}

/**
 * 继续中断的提取任务（同一任务，从断点接着做；AI 服务里还在跑就直接接上）
 * POST /api/novel/extract/{id}/resume
 */
export function resumeExtract(id) {
  return request.post(`/api/novel/extract/${id}/resume`).then((res) => res.data)
}

/**
 * 整理卡片：对提取成功的小说，把实体档案整理成素材卡 / 体系卡 / 剧情段（进入待确认）
 * POST /api/novel/extract/{id}/compile {model, entityKeys?, categories?, topN?, plot?}
 */
export function compileExtract(id, body) {
  return request.post(`/api/novel/extract/${id}/compile`, body).then((res) => res.data)
}

/** 共鸣素材分组提议（只是建议）{model?} → {groups: [{name, cardIds, reason}], usage}；POST /api/novel/extract/{id}/resonance-groups */
export const resonanceGroups = (id, body = {}) =>
  request.post(`/api/novel/extract/${id}/resonance-groups`, body, { timeout: 300000 }).then((res) => res.data)

/** 世界观分组提议（只是建议）{model?} → {groups: [{name, members: [实体键], reason}], usage}；POST /api/novel/extract/{id}/world-groups */
export const worldGroups = (id, body = {}) =>
  request.post(`/api/novel/extract/${id}/world-groups`, body, { timeout: 300000 }).then((res) => res.data)

/** 这次提取的整理记录（最近的在前）GET /api/novel/extract/{id}/compiles */
export function listCompiles(id) {
  return request.get(`/api/novel/extract/${id}/compiles`).then((res) => res.data)
}

/** 暂停 / 继续 / 取消整理：POST /api/novel/extract/compile/{cid}/pause|resume|cancel */
export const pauseCompile = (cid) => request.post(`/api/novel/extract/compile/${cid}/pause`).then((res) => res.data)
export const resumeCompile = (cid) => request.post(`/api/novel/extract/compile/${cid}/resume`).then((res) => res.data)
export const cancelCompile = (cid) => request.post(`/api/novel/extract/compile/${cid}/cancel`).then((res) => res.data)

/**
 * 提取任务列表（不含结果），按创建时间倒序
 * GET /api/novel/extract/list
 */
export function listExtracts() {
  return request.get('/api/novel/extract/list').then((res) => res.data)
}

/**
 * 提取任务详情，data.result 为结果 JSON 字符串
 * GET /api/novel/extract/{id}
 */
export function getExtract(id) {
  return request.get(`/api/novel/extract/${id}`).then((res) => res.data)
}

/**
 * 提取前预览分章（和提取同一套规则，选章节范围用）→ {chars, total, chapters[{index (从 1 数), title, kind, chars}], warnings}
 * GET /api/novel/extract/split/{fileId}
 */
export function splitPreview(fileId) {
  return request.get(`/api/novel/extract/split/${fileId}`).then((res) => res.data)
}

/**
 * 逐章查看（提取中）：since = 上次的 live.next → {status, progress, message, live?: {exists, range, chapters?, rows, next, current, running}, finished?}
 * GET /api/novel/extract/{id}/live?since=N
 */
export function getExtractLive(id, since = 0) {
  return request.get(`/api/novel/extract/${id}/live`, { params: { since } }).then((res) => res.data)
}

/**
 * 按文件取全书第 index 章（从 0 数，和提取同一套分章）的原文 → {index, title, kind, text, total}（提取工作区，开始提取前也能看）
 * GET /api/novel/extract/file/{fileId}/chapters/{index}/text
 */
export function getFileChapterText(fileId, index) {
  return request.get(`/api/novel/extract/file/${fileId}/chapters/${index}/text`).then((res) => res.data)
}

/**
 * 保存手动修改后的提取结果（整体替换，须含 chapters）
 * POST /api/novel/extract/{id}/result
 */
export function updateExtractResult(id, result) {
  return request.post(`/api/novel/extract/${id}/result`, result).then((res) => res.data)
}

/**
 * 打开提取工作区：这个文件「未开始」（DRAFT）的提取，没有就新建
 * POST /api/novel/extract/draft/{fileId}
 */
export function createExtractDraft(fileId) {
  return request.post(`/api/novel/extract/draft/${fileId}`).then((res) => res.data)
}

/**
 * 保存未开始提取的草稿设置 {model, materials}（含章节范围）
 * POST /api/novel/extract/{id}/draft
 */
export function saveExtractDraft(id, body) {
  return request.post(`/api/novel/extract/${id}/draft`, body).then((res) => res.data)
}

/**
 * 开始未开始的提取 {model, materials}
 * POST /api/novel/extract/{id}/start
 */
export function startExtract(id, body) {
  return request.post(`/api/novel/extract/${id}/start`, body).then((res) => res.data)
}

/**
 * 全书实体的 AI 归并建议（不改数据，作者逐组采用）{entities:[{key, category, name, aliases, fact}], model}
 * → {groups[{keys, category, type same|system, name, reason}], usage}
 * POST /api/novel/extract/entity-groups
 */
export function entityGroupsAI(body) {
  return request.post('/api/novel/extract/entity-groups', body, { timeout: 300000 }).then((res) => res.data)
}

/**
 * 接着读到第 N 章（0 = 读到最后）：前面的章不重读，伏笔 / 主角状态 / 实体档案接着往下走
 * POST /api/novel/extract/{id}/extend {toChapter}
 */
export function extendExtract(id, toChapter) {
  return request.post(`/api/novel/extract/${id}/extend`, { toChapter }).then((res) => res.data)
}

/**
 * 重读这几章（范围内序号，0 起），其他章不动
 * POST /api/novel/extract/{id}/reread {cis}
 */
export function rereadExtract(id, cis) {
  return request.post(`/api/novel/extract/${id}/reread`, { cis }).then((res) => res.data)
}

const SITE_TAG = /[[【(（][^\]】)）]*\.[A-Za-z]{2,}[^\]】)）]*[\]】)）]/g
const COPY_SUFFIX = /(\s*[(（]\d{1,3}[)）]|\s*-\s*副本)+$/

/**
 * 文件名 → 书名（与后端 MaterialService.bookOf 一致）：去扩展名、站点标记、副本后缀、书名号，
 * 用于判断同一本小说是否已提取过
 */
export function bookOf(fileName) {
  if (!fileName || !fileName.trim()) return ''
  let name = fileName.replace(/\\/g, '/')
  name = name.substring(name.lastIndexOf('/') + 1)
  const dot = name.lastIndexOf('.')
  if (dot > 0) name = name.substring(0, dot)
  const cleaned = name.replace(SITE_TAG, '').replace(COPY_SUFFIX, '').trim()
  name = cleaned || name.trim()
  if (name.startsWith('《') && name.endsWith('》') && name.length > 2) {
    name = name.substring(1, name.length - 1).trim()
  }
  return name
}
