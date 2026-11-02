import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// 霞鹜文楷（按 unicode-range 切片，只下载页面用到的字）：标题 / 正文用，见 styles/ink-theme.css
import 'lxgw-wenkai-webfont/lxgwwenkai-regular.css'
import './styles/ink-theme.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'

const app = createApp(App)

// 全量注册图标组件，供 <component :is="meta.icon"> 按名字解析（见 docx/fronted_vue3/router/router.md）
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

app.use(ElementPlus).use(router).mount('#app')
