import { aiRequest } from './request'

/** 小说生成（Python 服务 /api/gen/**）。均返回 {code, message, data} */
const get = (url) => aiRequest.get(url).then((res) => res.data)
const post = (url, body) => aiRequest.post(url, body).then((res) => res.data)

export const CONTEXT_WINDOWS = [8192, 32768]

/** 默认模型（Qwen2.5-1.5B-Instruct）是否就绪、当前加载的模型、进行中的生成任务 */
export const getGenStatus = () => get('/api/gen/status')

/* ---------- 工作区 ---------- */
export const listNovels = () => get('/api/gen/novels')
/** {title, model: {source: 'local'|'remote', baseId}, contextWindow} */
export const createNovel = (body) => post('/api/gen/novels', body)
/** 工作区详情（含章节列表，不含正文） */
export const getNovel = (id) => get(`/api/gen/novels/${id}`)
/** {title?, model?, contextWindow?, params?, settings?: {config, spec}} */
export const updateNovel = (id, body) => post(`/api/gen/novels/${id}/update`, body)
export const deleteNovel = (id) => post(`/api/gen/novels/${id}/delete`)
/** 加载工作区所选模型（不使用适配器） */
export const loadNovelModel = (id) => post(`/api/gen/novels/${id}/model/load`)

/* ---------- 章节 ---------- */
export const getChapter = (id, index) => get(`/api/gen/novels/${id}/chapters/${index}`)
export const deleteChapter = (id, index) => post(`/api/gen/novels/${id}/chapters/${index}/delete`)
/** 预览下一章第一段的上下文（不生成）：{goal, title, targetChars} */
export const previewContext = (id, body) => post(`/api/gen/novels/${id}/preview`, body)
/** 开始生成下一章（后台任务）：{goal, title, targetChars} */
export const startChapter = (id, body) => post(`/api/gen/novels/${id}/chapters`, body)
export const getGenJob = (jobId) => get(`/api/gen/jobs/${jobId}`)
export const cancelGenJob = (jobId) => post(`/api/gen/jobs/${jobId}/cancel`)
