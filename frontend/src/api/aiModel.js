import request from './request'

/**
 * 第三方模型提供商（「新增模型 → 第三方模型提供商」）：选一个就填好地址 / 协议 / 常用模型，只需填 Key。
 * key = 保存为 providerId；models = 预置的模型目录（还可以「获取可用模型」）；noKey = 本机服务不需要 Key。
 */
export const PROVIDER_PRESETS = [
  { key: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com', protocol: 'openai', models: ['deepseek-chat', 'deepseek-flash', 'deepseek-v4-pro'], concurrency: 4 },
  { key: 'qwen', label: '通义千问（阿里云百炼）', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', protocol: 'openai', models: ['qwen-plus', 'qwen-max', 'qwen-turbo'], concurrency: 4 },
  { key: 'moonshot', label: 'Kimi（月之暗面）', baseUrl: 'https://api.moonshot.cn/v1', protocol: 'openai', models: ['moonshot-v1-32k', 'moonshot-v1-128k', 'moonshot-v1-8k'], concurrency: 2 },
  { key: 'zhipu', label: '智谱 GLM', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', protocol: 'openai', models: ['glm-4-plus', 'glm-4-flash'], concurrency: 4 },
  { key: 'siliconflow', label: '硅基流动', baseUrl: 'https://api.siliconflow.cn/v1', protocol: 'openai', models: ['deepseek-ai/DeepSeek-V3', 'Qwen/Qwen2.5-72B-Instruct'], concurrency: 4 },
  { key: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', protocol: 'openai', models: [], concurrency: 4 },
  { key: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', protocol: 'openai', models: ['gpt-4o-mini', 'gpt-4o'], concurrency: 4 },
  { key: 'anthropic', label: 'Anthropic（Claude）', baseUrl: 'https://api.anthropic.com', protocol: 'anthropic', models: ['claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-opus-5-5'], concurrency: 4 },
  { key: 'llamacpp', label: '本地 llama.cpp', baseUrl: 'http://127.0.0.1:8001/v1', protocol: 'openai', models: ['qwen2.5-7b-instruct'], concurrency: 1, noKey: true }
]

/** API 协议（自定义模型 API） */
export const API_PROTOCOLS = [
  { value: 'openai', label: 'OpenAI 兼容', hint: '请求 {地址}/chat/completions，模型列表 {地址}/models' },
  { value: 'anthropic', label: 'Anthropic', hint: '请求 {地址}/v1/messages（地址已以 /v1 结尾则 {地址}/messages），请求头 x-api-key' }
]

export const providerPreset = (key) => PROVIDER_PRESETS.find((p) => p.key === key) || null

/**
 * 模型配置列表（apiKey 只返回脱敏的 apiKeyMasked）
 * GET /api/ai/model/list
 */
export function listModels() {
  return request.get('/api/ai/model/list').then((res) => res.data)
}

/**
 * 新增 / 修改（id 为空则新增；修改时 apiKey 留空保持原值）
 * POST /api/ai/model/save
 */
export function saveModel(data) {
  return request.post('/api/ai/model/save', data).then((res) => res.data)
}

/**
 * 获取可用模型（模型目录）：apiKey 留空 + id = 用已保存的 Key → {ok, models[{id, name}], message}
 * POST /api/ai/model/fetch-models
 */
export function fetchModelCatalog(data) {
  return request.post('/api/ai/model/fetch-models', data, { timeout: 60000 }).then((res) => res.data)
}

/**
 * 验证配置（真实调用一次模型，最长约 60s）
 * POST /api/ai/model/{id}/verify
 */
export function verifyModel(id) {
  return request.post(`/api/ai/model/${id}/verify`).then((res) => res.data)
}

/**
 * 启用（仅限已验证的配置）
 * POST /api/ai/model/{id}/activate
 */
export function activateModel(id) {
  return request.post(`/api/ai/model/${id}/activate`).then((res) => res.data)
}

/**
 * 删除
 * POST /api/ai/model/{id}/delete
 */
export function deleteModel(id) {
  return request.post(`/api/ai/model/${id}/delete`).then((res) => res.data)
}
