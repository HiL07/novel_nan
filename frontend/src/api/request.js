import axios from 'axios'

// 后端地址（见 docx/fronted_vue3/api/file_upload.md）
export const baseURL = 'http://localhost:8080'

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
