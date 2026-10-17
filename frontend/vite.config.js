import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    // @ 指向 src（见 docx/fronted_vue3/router/router.md）
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    // 日常 5173；测试 `npm run dev:test` 用 5174。须在后端 CORS 白名单内（application.yml 的 app.cors.allowed-origins）
    port: 5173
  }
})
