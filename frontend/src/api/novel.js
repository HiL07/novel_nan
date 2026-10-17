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
