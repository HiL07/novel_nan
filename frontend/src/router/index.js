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
  }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
