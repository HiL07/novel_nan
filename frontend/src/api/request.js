import axios from 'axios'

// 后端地址：由 .env.[mode] 的 VITE_API_BASE_URL 决定（日常 8022，测试 `npm run dev:test` 用 8012）
export const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8022'

// 全局共享的 Axios 实例，各 api 模块统一使用
const request = axios.create({
  baseURL,
  timeout: 60000
})

/** 取后端 Result 里的错误信息（HTTP 非 2xx 时 axios 会 reject） */
export function errorMessage(e, fallback) {
  return e?.response?.data?.message || e?.message || fallback
}

export default request
