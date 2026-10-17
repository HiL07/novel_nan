import axios from 'axios'

// 后端地址：由 .env.[mode] 的 VITE_API_BASE_URL 决定（日常 8022，测试 `npm run dev:test` 用 8012）
export const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8022'

// 全局共享的 Axios 实例，各 api 模块统一使用
const request = axios.create({
  baseURL,
  timeout: 60000
})

// Python AI 服务地址（本地模型管理页直接调用）：VITE_AI_BASE_URL，日常 8021，测试 8011
export const aiBaseURL = import.meta.env.VITE_AI_BASE_URL || 'http://localhost:8021'

/** Python AI 服务的共享 Axios 实例（响应同样为 {code, message, data}）；生成 / 加载可能较慢，超时放宽 */
export const aiRequest = axios.create({
  baseURL: aiBaseURL,
  timeout: 180000
})

/** 取后端 Result 里的错误信息（HTTP 非 2xx 时 axios 会 reject） */
export function errorMessage(e, fallback) {
  return e?.response?.data?.message || e?.message || fallback
}

export default request
