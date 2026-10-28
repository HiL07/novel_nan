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
 * 删除提取失败的任务（成功 / 提取中的跳过）→ {deleted, skipped}
 * POST /api/novel/extract/delete {ids}
 */
export function deleteExtracts(ids) {
  return request.post('/api/novel/extract/delete', { ids }).then((res) => res.data)
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
 * 保存手动修改后的提取结果（整体替换，须含 chapters）
 * POST /api/novel/extract/{id}/result
 */
export function updateExtractResult(id, result) {
  return request.post(`/api/novel/extract/${id}/result`, result).then((res) => res.data)
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
