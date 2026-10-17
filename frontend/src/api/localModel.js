import { aiRequest } from './request'

/** 本地模型（Python 服务 /api/local/**）。所有函数返回 {code, message, data} */
const get = (url, config) => aiRequest.get(url, config).then((res) => res.data)
const post = (url, body) => aiRequest.post(url, body).then((res) => res.data)

/** 下载模型时的推荐列表（8GB 显存可训练的规模） */
export const RECOMMENDED_MODELS = [
  { repoId: 'Qwen/Qwen2.5-0.5B-Instruct', size: '约 1 GB', note: '最快，适合先跑通流程' },
  { repoId: 'Qwen/Qwen2.5-1.5B-Instruct', size: '约 3.1 GB', note: '8GB 显存推荐' },
  { repoId: 'Qwen/Qwen2.5-3B-Instruct', size: '约 6.2 GB', note: 'QLoRA 可训练，接近上限' }
]

/** GPU / 内存 / 磁盘 / 依赖 / 当前推理状态 / 进行中的任务 */
export const getSystem = () => get('/api/local/system')

/* ---------- 基础模型 ---------- */
export const listModels = () => get('/api/local/models')
export const registerModel = (name, path) => post('/api/local/models/register', { name, path })
/** 下载源：auto（依次尝试 ModelScope → hf-mirror → Hugging Face）/ modelscope / hf-mirror / huggingface；空 = 服务默认 */
export const DOWNLOAD_SOURCES = [
  { value: 'auto', label: '自动（推荐）', note: '依次尝试，某个源不可用时自动换下一个' },
  { value: 'modelscope', label: 'ModelScope 魔搭', note: '国内直连，逐文件校验 SHA-256' },
  { value: 'hf-mirror', label: 'hf-mirror 镜像', note: 'Hugging Face 国内镜像' },
  { value: 'huggingface', label: 'Hugging Face 官方', note: '需能访问 huggingface.co' }
]
export const downloadModel = (repoId, name, source = 'auto') => post('/api/local/models/download', { repoId, name, source })
export const getDownloadSources = () => get('/api/local/models/download/sources')
export const deleteModel = (id) => post(`/api/local/models/${id}/delete`)
/** 资源评估：{baseModelId, mode: infer|train, quantization: 4bit|none, maxSeqLen, batchSize, loraR} */
export const estimate = (body) => post('/api/local/estimate', body)

/* ---------- LoRA 适配器 ---------- */
export const listAdapters = () => get('/api/local/adapters')
export const renameAdapter = (id, name) => post(`/api/local/adapters/${id}/rename`, { name })
export const deleteAdapter = (id) => post(`/api/local/adapters/${id}/delete`)

/* ---------- 推理 ---------- */
export const getInference = () => get('/api/local/inference')
export const loadModel = (baseId, adapterId, quantization = 'auto') => post('/api/local/inference/load', { baseId, adapterId, quantization })
export const unloadModel = () => post('/api/local/inference/unload')
/** {prompt, maxNewTokens, temperature, topP, repetitionPenalty, useChatTemplate} */
export const generate = (body) => post('/api/local/inference/generate', body)

/* ---------- 训练任务 ---------- */
/** 见 python-service/app/local/router.py TrainReq；资源超限时返回 409（data 为评估结果），可带 force: true 强制开始 */
export const startTraining = (body) => post('/api/local/train', body)
export const listJobs = () => get('/api/local/jobs')
export const getJob = (id) => get(`/api/local/jobs/${id}`)
export const getJobLog = (id, lines = 300) => get(`/api/local/jobs/${id}/log`, { params: { lines } })
export const cancelJob = (id) => post(`/api/local/jobs/${id}/cancel`)
