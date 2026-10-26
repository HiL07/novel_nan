import request from './request'

/** 支持小说提取的扩展名（与后端 NovelExtractService 一致） */
export const EXTRACTABLE_EXTS = ['txt', 'md', 'docx', 'pdf']

export function isExtractable(ext) {
  return EXTRACTABLE_EXTS.includes((ext || '').toLowerCase())
}

/**
 * 对文件发起小说提取（异步任务，立即返回任务记录）
 * POST /api/novel/extract/{fileId} {materials?}
 */
export function submitExtract(fileId, options = {}) {
  // options.materials = {enabled, categories, maxPerChunk, focus}：同时提取创作素材候选（需用户确认后入库）
  return request.post(`/api/novel/extract/${fileId}`, options).then((res) => res.data)
}

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
