import request, { aiRequest } from './request'

/** 小说生成（Python 服务 /api/gen/**）。均返回 {code, message, data} */
const get = (url) => aiRequest.get(url).then((res) => res.data)
const post = (url, body) => aiRequest.post(url, body).then((res) => res.data)

export const CONTEXT_WINDOWS = [8192, 32768]

/** 默认模型（Qwen2.5-1.5B-Instruct）是否就绪、当前加载的模型、进行中的生成任务 */
export const getGenStatus = () => get('/api/gen/status')

/* ---------- 工作区 ---------- */
export const listNovels = () => get('/api/gen/novels')
/** {title, model: {source: 'local', baseId, adapterId?} | {source: 'api', apiName}, contextWindow}
 *  source：local = 本地模型（+ LoRA 适配器）；api = 大模型（「模型配置」中启用的）；remote = 远程 GPU 模型（预留） */
export const createNovel = (body) => post('/api/gen/novels', body)
/** 工作区详情（含章节列表，不含正文） */
export const getNovel = (id) => get(`/api/gen/novels/${id}`)
/** {title?, model?, contextWindow?, params?, settings?: {config, spec}, outline?, clearOutline?, arcSummary?} */
export const updateNovel = (id, body) => post(`/api/gen/novels/${id}/update`, body)
export const deleteNovel = (id) => post(`/api/gen/novels/${id}/delete`)
/** 加载工作区所选模型 + 适配器（同一基础模型已驻留时只切换适配器）；大模型工作区不需要 */
export const loadNovelModel = (id) => post(`/api/gen/novels/${id}/model/load`)

/* ---------- 章节 ---------- */
export const getChapter = (id, index) => get(`/api/gen/novels/${id}/chapters/${index}`)
export const deleteChapter = (id, index) => post(`/api/gen/novels/${id}/chapters/${index}/delete`)
/** 预览下一章第一段的上下文（不生成）：{goal, title, targetChars} */
export const previewContext = (id, body) => post(`/api/gen/novels/${id}/preview`, body)
/** 开始生成下一章（后台任务）：{goal, title, targetChars, polish?: {enabled, baseId, adapterId}}
 *  本地模型直接调 Python；大模型（api=true）经 Java，由它附带「模型配置」中启用的模型 */
export const startChapter = (id, body, api = false) =>
  api ? request.post(`/api/novel/gen/${id}/chapters`, body).then((res) => res.data) : post(`/api/gen/novels/${id}/chapters`, body)
/** AI 构思（经 Java：附带启用的大模型 + 素材库素材）：
 *  {kind: 'title'|'outline'|'chapter', source?: 'api'|'local', baseId?, adapterId?, hint?, count?, materialIds?[], autoMaterials?, query?}
 *  → {kind, nextIndex, result, usage, model, usedMaterials}。只返回建议；大纲采用后用 updateNovel({outline}) 保存 */
export const generateIdeas = (id, body) =>
  request.post(`/api/novel/gen/${id}/ideas`, body, { timeout: 240000 }).then((res) => res.data)
/** 用本地模型（+ LoRA 适配器）润色已完成的章节（后台任务）：{baseId, adapterId?} */
export const polishChapter = (id, index, body) => post(`/api/gen/novels/${id}/chapters/${index}/polish`, body)
/** 手动修改章节：{title?, goal?, text?, summary?}（只改传入的字段） */
export const editChapter = (id, index, body) => post(`/api/gen/novels/${id}/chapters/${index}/update`, body)
/** 恢复润色前的原文 */
export const revertPolish = (id, index) => post(`/api/gen/novels/${id}/chapters/${index}/polish/revert`)
export const getGenJob = (jobId) => get(`/api/gen/jobs/${jobId}`)
export const cancelGenJob = (jobId) => post(`/api/gen/jobs/${jobId}/cancel`)
