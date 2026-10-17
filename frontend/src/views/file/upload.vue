<template>
  <div class="upload-page">
    <!-- 一、上传区 -->
    <el-card class="box-card" shadow="never">
      <template #header>
        <span class="card-title">选择文件</span>
      </template>

      <el-upload
        drag
        multiple
        :auto-upload="false"
        :show-file-list="false"
        :on-change="onFileChange"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">将文件拖到此处，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持多选，选择后先进入下方待上传列表；单文件上限 50MB</div>
        </template>
      </el-upload>
    </el-card>

    <!-- 二、待上传列表（预览区）+ 上传按钮 -->
    <el-card v-if="pendingList.length" class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">待上传（{{ pendingList.length }}）</span>
          <el-button
            type="primary"
            :loading="uploading"
            :disabled="uploading"
            @click="handleUploadAll"
          >
            上传
          </el-button>
        </div>
      </template>

      <div class="preview-grid">
        <div
          v-for="item in pendingList"
          :key="item.id"
          class="file-card"
          :class="{ 'is-image': item.isImage }"
        >
          <img v-if="item.isImage" class="file-thumb" :src="item.url" :alt="item.name" />
          <el-icon v-else class="file-icon"><Document /></el-icon>

          <div class="file-meta">
            <span class="file-name">{{ item.name }}</span>
            <span class="file-size">{{ formatSize(item.size) }}</span>
          </div>

          <el-icon class="file-remove" @click="removeItem(item)"><Close /></el-icon>
        </div>
      </div>
    </el-card>

    <!-- 三、上传结果 -->
    <el-card v-if="results.length" class="box-card" shadow="never">
      <template #header>
        <span class="card-title">上传结果</span>
      </template>

      <div class="result-list">
        <div v-for="(r, i) in results" :key="i" class="result-item">
          <el-icon v-if="r.status === 'ok'" class="result-icon is-ok"><CircleCheck /></el-icon>
          <el-icon v-else class="result-icon is-fail"><CircleClose /></el-icon>

          <div class="result-body">
            <div class="result-name">{{ r.file.name }}</div>
            <div v-if="r.status === 'ok'" class="result-meta">
              {{ r.info?.storagePath }} · {{ r.info?.createTime }}
            </div>
            <div v-else class="result-error">{{ r.message }}</div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadFiles } from '@/api/file'

const pendingList = ref([])
const results = ref([])
const uploading = ref(false)
let seq = 0

/** 选择文件 → 加入待上传列表（按 name + size 去重） */
function onFileChange(uploadFileObj) {
  const raw = uploadFileObj?.raw
  if (!raw) return
  const duplicated = pendingList.value.some(
    (it) => it.name === raw.name && it.size === raw.size
  )
  if (duplicated) return

  const isImage = (raw.type || '').startsWith('image/')
  pendingList.value.push({
    id: ++seq,
    raw,
    name: raw.name,
    size: raw.size,
    isImage,
    url: isImage ? URL.createObjectURL(raw) : ''
  })
}

/** 从待上传列表移除并释放对象 URL */
function removeItem(item) {
  const idx = pendingList.value.findIndex((it) => it.id === item.id)
  if (idx === -1) return
  if (item.url) URL.revokeObjectURL(item.url)
  pendingList.value.splice(idx, 1)
}

/** 批量上传全部待上传项，每项独立成功/失败 */
async function handleUploadAll() {
  if (uploading.value || !pendingList.value.length) return
  uploading.value = true

  const items = pendingList.value
  try {
    results.value = await uploadFiles(items.map((it) => it.raw))
    const okCount = results.value.filter((r) => r.status === 'ok').length
    const failCount = results.value.length - okCount
    if (failCount === 0) {
      ElMessage.success(`全部上传成功（${okCount} 个）`)
    } else {
      ElMessage.warning(`成功 ${okCount} 个，失败 ${failCount} 个`)
    }
  } finally {
    // 结束后清空待上传列表，并释放对象 URL
    items.forEach((it) => {
      if (it.url) URL.revokeObjectURL(it.url)
    })
    pendingList.value = []
    uploading.value = false
  }
}

function formatSize(bytes) {
  if (bytes == null) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

onBeforeUnmount(() => {
  pendingList.value.forEach((it) => {
    if (it.url) URL.revokeObjectURL(it.url)
  })
})
</script>

<style scoped>
.upload-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.upload-icon {
  font-size: 48px;
  color: #c0c4cc;
  margin-bottom: 8px;
}

/* 预览区：待上传卡片 */
.preview-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
.file-card {
  position: relative;
  box-sizing: border-box;
  width: 120px;
  height: 160px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  text-align: center;
  word-break: break-all;
  overflow: hidden;
}
.file-card.is-image {
  padding: 0;
  gap: 0;
  justify-content: flex-start;
}
.file-thumb {
  display: block;
  width: 100%;
  height: 110px;
  object-fit: cover;
}
.file-card.is-image .file-meta {
  padding: 4px 6px;
}
.file-icon {
  font-size: 36px;
  color: #c0c4cc;
}
.file-meta {
  box-sizing: border-box;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}
.file-name {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: #303133;
}
.file-size {
  color: #909399;
}
.file-remove {
  position: absolute;
  top: 4px;
  right: 4px;
  padding: 2px;
  font-size: 12px;
  color: #ffffff;
  background: rgba(0, 0, 0, 0.45);
  border-radius: 50%;
  cursor: pointer;
}
.file-remove:hover {
  background: rgba(0, 0, 0, 0.7);
}

/* 上传结果 */
.result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.result-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.result-icon {
  margin-top: 2px;
  font-size: 16px;
}
.result-icon.is-ok {
  color: #67c23a;
}
.result-icon.is-fail {
  color: #f56c6c;
}
.result-body {
  min-width: 0;
  flex: 1;
}
.result-name {
  font-size: 14px;
  color: #303133;
  word-break: break-all;
}
.result-meta {
  font-size: 12px;
  color: #909399;
  word-break: break-all;
}
.result-error {
  font-size: 12px;
  color: #f56c6c;
  word-break: break-all;
}
</style>
