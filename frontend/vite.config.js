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
    // 与后端 CORS 白名单一致（见 backend/src/main/java/com/example/file/config/WebConfig.java）
    port: 5173
  }
})
