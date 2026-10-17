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
  }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
