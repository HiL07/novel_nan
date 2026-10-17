import request from './request'

/** 常用 OpenAI 兼容服务预设（选择后自动填入地址与模型，可再修改） */
export const MODEL_PRESETS = [
  { label: 'DeepSeek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', concurrency: 4 },
  { label: '通义千问（阿里云百炼）', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', concurrency: 4 },
  { label: 'Kimi（月之暗面）', baseUrl: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-32k', concurrency: 2 },
  { label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini', concurrency: 4 },
  { label: '本地 llama.cpp（千问 7B）', baseUrl: 'http://127.0.0.1:8001/v1', model: 'qwen2.5-7b-instruct', concurrency: 1 }
]

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
