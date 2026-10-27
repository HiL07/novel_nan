import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/file/upload' },
  {
    path: '/file/upload',
    name: 'fileUpload',
    component: () => import('@/views/file/upload.vue'),
    meta: { title: '文件上传', icon: 'Upload' }
  },
  {
    path: '/file/manage',
    name: 'fileManage',
    component: () => import('@/views/file/manage.vue'),
    meta: { title: '文件管理', icon: 'Folder' }
  },
  {
    path: '/novel/create',
    name: 'novelCreate',
    component: () => import('@/views/novel/create.vue'),
    meta: { title: '小说创作', icon: 'EditPen' }
  },
  {
    // 工作区详情（不在侧边栏显示）
    path: '/novel/workspace/:id',
    name: 'novelWorkspace',
    component: () => import('@/views/novel/workspace.vue')
  },
  {
    path: '/material',
    name: 'material',
    component: () => import('@/views/material/index.vue'),
    meta: { title: '素材库', icon: 'Collection' }
  },
  {
    // 侧边栏「小说抓取」：带子菜单，点父项进入第一个子页面
    path: '/novel/crawl',
    redirect: '/novel/crawl/config',
    meta: {
      title: '小说抓取',
      icon: 'Link',
      children: [
        { path: '/novel/crawl/config', title: '抓取配置', icon: 'Setting' },
        { path: '/novel/crawl/book', title: '单本抓取', icon: 'Document' },
        { path: '/novel/crawl/auto', title: '全自动抓取', icon: 'MagicStick' },
        { path: '/novel/crawl/progress', title: '抓取进度', icon: 'Odometer' }
      ]
    }
  },
  {
    // 四个子页面是同一个组件（crawl.vue 按 tab 显示对应一块，状态共用、切换不丢）
    // tasks / workspace 是旧地址（整本抓取进度 / 整站工作区，已合并为「抓取进度」），仍可打开
    path: '/novel/crawl/:tab(config|book|auto|progress|tasks|workspace)',
    name: 'novelCrawl',
    component: () => import('@/views/novel/crawl.vue')
  },
  {
    path: '/novel/extract',
    name: 'novelExtract',
    component: () => import('@/views/novel/extract.vue'),
    meta: { title: '小说提取', icon: 'MagicStick' }
  },
  {
    path: '/ai/model',
    name: 'aiModel',
    component: () => import('@/views/ai/model.vue'),
    meta: { title: '模型配置', icon: 'Cpu' }
  },
  {
    path: '/ai/pyenv',
    name: 'aiPyEnv',
    component: () => import('@/views/ai/pyenv.vue'),
    meta: { title: 'Python 环境', icon: 'SetUp' }
  },
  {
    path: '/ai/local',
    name: 'aiLocal',
    component: () => import('@/views/ai/local.vue'),
    meta: { title: '本地模型', icon: 'Monitor' }
  },
  {
    path: '/ai/llama',
    name: 'aiLlama',
    component: () => import('@/views/ai/llama.vue'),
    meta: { title: 'llama.cpp', icon: 'VideoPlay' }
  }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
