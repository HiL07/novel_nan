import { aiRequest } from './request'

/** 本地模型（Python 服务 /api/local/**）。所有函数返回 {code, message, data} */
const get = (url, config) => aiRequest.get(url, config).then((res) => res.data)
const post = (url, body) => aiRequest.post(url, body).then((res) => res.data)

/** 下载模型时的推荐列表（8GB 显存可训练的规模） */
export const RECOMMENDED_MODELS = [
  { repoId: 'Qwen/Qwen2.5-0.5B-Instruct', size: '约 1 GB', note: '最快，适合先跑通流程' },
  { repoId: 'Qwen/Qwen2.5-1.5B-Instruct', size: '约 3.1 GB', note: '8GB 显存推荐' },
  { repoId: 'Qwen/Qwen2.5-3B-Instruct', size: '约 6.2 GB', note: 'QLoRA 可训练，接近上限' },
  {
    repoId: 'Qwen/Qwen2.5-7B-Instruct',
    size: '约 15 GB',
    note: '8GB 显存只能 4bit 推理（约 5.5 GB，需关掉其他占显存的程序）；本机训练会超出资源，适合加载远程训练的 7B 适配器',
    big: true
  },
  {
    repoId: 'BAAI/bge-small-zh-v1.5',
    size: '约 0.1 GB',
    note: '向量（embedding）模型：只用于素材库「向量检索」，不能生成 / 微调',
    embedding: true
  },
  {
    repoId: 'BAAI/bge-reranker-v2-m3',
    size: '约 2.1 GB',
    note: '重排模型：给素材检索结果按相关度重新排序（GPU 约 1.1 GB 显存），不能生成 / 微调',
    embedding: true
  }
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
/** targetDir：保存位置（上级目录，实际存到 <targetDir>/<仓库名>）；空 = python-service/models/base/ */
export const downloadModel = (repoId, name, source = 'auto', targetDir = '') =>
  post('/api/local/models/download', { repoId, name, source, targetDir: targetDir || undefined })
/** 下载前检查（需联网几秒）→ {source, sourceLabel, files, sizeGb, target, freeGb, enough, hasWeights} */
export const checkDownload = (repoId, source = 'auto', targetDir = '') =>
  post('/api/local/models/download/check', { repoId, source, targetDir: targetDir || undefined })
/** 目录浏览（选择保存位置）：path 为空时列出各磁盘 → {path, parent, freeGb, dirs[{name, path, freeGb?}]} */
export const listDirs = (path = '') => get(`/api/local/fs/dirs?path=${encodeURIComponent(path)}`)
export const getDownloadSources = () => get('/api/local/models/download/sources')
export const deleteModel = (id) => post(`/api/local/models/${id}/delete`)
/** 资源评估：{baseModelId, mode: infer|train, quantization: 4bit|none, maxSeqLen, batchSize, loraR, adapterId?}
 *  推理时按服务当前驻留情况估算：同一基础模型已加载 → 只算适配器增量（resident: true） */
export const estimate = (body) => post('/api/local/estimate', body)

/** task：causal-lm = 生成模型；embedding = 向量模型；reranker = 重排模型。后两者只用于素材检索，不能推理 / 微调 / 写小说 */
export const isEmbeddingModel = (m) => m?.task === 'embedding'
export const isRerankerModel = (m) => m?.task === 'reranker'
/** 只用于检索的模型（向量 / 重排）：生成、微调、工作区的模型下拉里不出现 */
export const isRetrievalModel = (m) => isEmbeddingModel(m) || isRerankerModel(m)
/** GGUF（llama.cpp 格式）：只登记展示，本服务不能推理 / 训练，要用 llama-server 跑后到「模型配置」添加 */
export const isGgufModel = (m) => m?.task === 'gguf'
/** 可在本服务推理 / 加适配器 / 微调的 Hugging Face 生成模型（所有生成模型下拉框都用它过滤） */
export const isGenerationModel = (m) => (m?.task || 'causal-lm') === 'causal-lm'

/** 模型种类：本地模型页的醒目标签与图例 */
export const MODEL_KINDS = {
  'causal-lm': { label: '生成模型', type: 'primary', desc: 'Hugging Face 格式，本服务可直接推理、挂 LoRA 适配器、风格微调、写小说 / 提取' },
  embedding: { label: '向量模型', type: 'success', desc: '如 bge-small：把素材转成向量，用于素材库「向量检索」，不能生成文字' },
  reranker: { label: '重排模型', type: 'success', desc: '如 bge-reranker：给检索结果按相关度重新排序，不能生成文字' },
  gguf: { label: 'GGUF · llama.cpp', type: 'warning', desc: '量化后的单文件格式，只能用 llama.cpp 运行：启动 llama-server 后到「模型配置」添加' }
}
export const modelKind = (m) => MODEL_KINDS[m?.task] || MODEL_KINDS['causal-lm']

/* ---------- 向量（embedding）模型 ---------- */
/** → {status: idle|loading|loaded|error, baseId, name, device: cuda|cpu, dim, error} */
export const getEmbedding = () => get('/api/local/embedding')
export const unloadEmbedding = () => post('/api/local/embedding/unload')
/** {query, texts[], baseId?} → {scores[], device, model, instruction, ms}；未加载时自动加载 */
export const embeddingSimilarity = (body) => post('/api/local/embedding/similarity', body)
/* ---------- 重排模型 ---------- */
export const getReranker = () => get('/api/local/reranker')
export const unloadReranker = () => post('/api/local/reranker/unload')
/** {query, texts[], baseId?} → {scores[0–1], device, model, ms}；未加载时自动加载 */
export const rerankerScore = (body) => post('/api/local/reranker/score', body)

/* ---------- LoRA 适配器 ---------- */
/* llama.cpp（GGUF）：由 Python 启动 / 停止 llama-server（同一时间一个）；运行后各处模型来源可选「GGUF」 */
export const getLlama = () => get('/api/local/llama')
export const saveLlamaSettings = (serverPath) => post('/api/local/llama/settings', { serverPath })
/** body: {baseId? | path?, ctx, ngl} → {level ok|warn|error, problems[{level, text}], model, estimate, gpu, portOwner} */
export const checkLlama = (body) => post('/api/local/llama/check', body)
/** body: {baseId? | path?, ctx, ngl, stopExternal?}；端口上有别的 llama-server 时 400 + data.needConfirm */
export const startLlama = (body) => post('/api/local/llama/start', body)
export const stopLlama = () => post('/api/local/llama/stop')
export const getLlamaLog = (lines = 80) => get('/api/local/llama/log', { params: { lines } })
/** llama 是否正在运行（模型来源「GGUF」只有运行时才能选）→ 运行中的状态对象，否则 null */
export async function runningLlama() {
  try {
    const r = await getLlama()
    return r.code === 0 && r.data.status === 'running' ? r.data : null
  } catch {
    return null
  }
}

export const listAdapters = () => get('/api/local/adapters')
export const renameAdapter = (id, name) => post(`/api/local/adapters/${id}/rename`, { name })
export const deleteAdapter = (id) => post(`/api/local/adapters/${id}/delete`)

/* ---------- 推理 ---------- */
export const getInference = () => get('/api/local/inference')
export const loadModel = (baseId, adapterId, quantization = 'auto') => post('/api/local/inference/load', { baseId, adapterId, quantization })
export const unloadModel = () => post('/api/local/inference/unload')
/** {prompt, maxNewTokens, temperature, topP, repetitionPenalty, useChatTemplate, useAdapter?, seed?}
 *  useAdapter：不传 = 按当前启用状态；true / false = 本次启用 / 停用已挂载的适配器 */
export const generate = (body) => post('/api/local/inference/generate', body)
/** 同一提示词 + 种子：基础模型（停用适配器）与微调模型各生成一次 → {base, adapter}；需已加载带适配器的模型 */
export const compareGenerate = (body) => post('/api/local/inference/compare', body)
/** 同一文本停用 / 启用适配器的 loss 与困惑度 {text, maxTokens?} → {tokens, base:{loss,ppl}, adapter:{loss,ppl}, lossDelta, pplChangePct} */
export const evaluateAdapter = (body) => post('/api/local/inference/evaluate', body)

/* ---------- 训练任务 ---------- */
/** 见 python-service/app/local/router.py TrainReq；资源超限时返回 409（data 为评估结果），可带 force: true 强制开始 */
export const startTraining = (body) => post('/api/local/train', body)
export const listJobs = () => get('/api/local/jobs')
export const getJob = (id) => get(`/api/local/jobs/${id}`)
export const getJobLog = (id, lines = 300) => get(`/api/local/jobs/${id}/log`, { params: { lines } })
export const cancelJob = (id) => post(`/api/local/jobs/${id}/cancel`)
