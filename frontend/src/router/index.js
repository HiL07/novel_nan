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
  }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
