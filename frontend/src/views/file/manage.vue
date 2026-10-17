<template>
  <div class="manage-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">文件管理</span>
          <el-button :icon="Refresh" :loading="loading" @click="loadFiles">刷新</el-button>
        </div>
      </template>

      <!-- 分类标签页 -->
      <el-tabs v-model="activeTab">
        <el-tab-pane
          v-for="tab in tabs"
          :key="tab.name"
          :name="tab.name"
          :label="`${tab.label}（${countOf(tab.name)}）`"
        />
      </el-tabs>

      <el-empty v-if="!currentFiles.length" description="暂无文件" />

      <!-- 文件卡片网格 -->
      <div v-else class="file-grid">
        <div
          v-for="item in currentFiles"
          :key="item.id"
          class="file-card"
          :class="{ 'is-clickable': !isDownloadOnly(item) }"
          @click="onCardClick(item)"
        >
          <div class="file-card-preview">
            <img
              v-if="classify(item.fileExt) === 'image'"
              class="file-thumb"
              :src="previewUrl(item.id)"
              :alt="item.fileName"
            />
            <el-icon v-else class="file-icon"><component :is="iconOf(item)" /></el-icon>
          </div>

          <div class="file-card-info">
            <span class="file-name">{{ item.fileName }}</span>
            <span class="file-size">{{ formatSize(item.fileSize) }}</span>
          </div>

          <el-icon
            v-if="isDownloadOnly(item)"
            class="file-download"
            title="下载"
            @click.stop="downloadFile(item.id)"
          >
            <Download />
          </el-icon>
          <el-icon
            v-if="isExtractable(item.fileExt)"
            class="file-extract"
            title="小说提取"
            @click.stop="startExtract(item)"
          >
            <MagicStick />
          </el-icon>
        </div>
      </div>
    </el-card>

    <ExtractOptionsDialog v-model="extractDlg.visible" :file-name="extractDlg.item?.fileName" @confirm="doExtract" />

    <!-- 预览弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="current?.fileName"
      width="760px"
      top="6vh"
      destroy-on-close
    >
      <template v-if="current">
        <!-- 图像：内容 + 底部「下载」 -->
        <div v-if="previewType === 'image'" class="preview-body">
          <img class="preview-image" :src="previewUrl(current.id)" :alt="current.fileName" />
        </div>

        <!-- 纯文本 / pdf：左侧内容 + 右侧「下载」「复制」 -->
        <div v-else class="preview-row">
          <div class="preview-main">
            <iframe
              v-if="previewType === 'pdf'"
              class="preview-iframe"
              :src="previewUrl(current.id)"
            />
            <pre v-else class="preview-text">{{ textContent }}</pre>
          </div>
          <div class="preview-actions">
            <el-button type="primary" @click="downloadFile(current.id)">下载</el-button>
            <el-button @click="copyPreview">
              {{ previewType === 'pdf' ? '复制地址' : '复制' }}
            </el-button>
            <el-button v-if="isExtractable(current.fileExt)" type="success" @click="startExtract(current)">
              小说提取
            </el-button>
          </div>
        </div>
      </template>

      <template v-if="previewType === 'image'" #footer>
        <el-button type="primary" @click="downloadFile(current.id)">下载</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onActivated, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, MagicStick, Refresh } from '@element-plus/icons-vue'
import { classify, downloadFile, downloadUrl, fetchText, listFiles, previewUrl } from '@/api/file'
import { isExtractable, submitExtract } from '@/api/novel'
import ExtractOptionsDialog from '@/components/material/ExtractOptionsDialog.vue'
import { errorMessage } from '@/api/request'

const router = useRouter()

const tabs = [
  { name: 'all', label: '全部' },
  { name: 'text', label: '纯文本' },
  { name: 'office', label: 'Office' },
  { name: 'image', label: '图像' },
  { name: 'binary', label: '二进制' },
  { name: 'other', label: '其他' }
]

const loading = ref(false)
const files = ref([])
const activeTab = ref('all')

const dialogVisible = ref(false)
const current = ref(null)
const previewType = ref('')
const textContent = ref('')

const currentFiles = computed(() =>
  activeTab.value === 'all'
    ? files.value
    : files.value.filter((f) => classify(f.fileExt) === activeTab.value)
)

function countOf(name) {
  return name === 'all'
    ? files.value.length
    : files.value.filter((f) => classify(f.fileExt) === name).length
}

async function loadFiles() {
  loading.value = true
  try {
    const res = await listFiles()
    if (res.code === 0) {
      files.value = res.data || []
    } else {
      ElMessage.error(res.message || '加载失败')
    }
  } catch (e) {
    ElMessage.error('加载文件列表失败')
  } finally {
    loading.value = false
  }
}

function iconOf(item) {
  const category = classify(item.fileExt)
  if (category === 'text') return 'Document'
  if (category === 'office') return 'Tickets'
  if (category === 'binary') return 'Box'
  return 'Document'
}

/** 二进制 / 其他：不预览，卡片上提供下载 */
function isDownloadOnly(item) {
  const category = classify(item.fileExt)
  return category === 'binary' || category === 'other'
}

function openDialog(item, type) {
  current.value = item
  previewType.value = type
  textContent.value = ''
  dialogVisible.value = true
}

/** 按分类决定点击行为（见 docx/fronted_vue3/view/file_manage.md 三） */
async function onCardClick(item) {
  const ext = (item.fileExt || '').toLowerCase()
  const category = classify(ext)

  if (category === 'image') {
    openDialog(item, 'image')
  } else if (category === 'text') {
    openDialog(item, 'text')
    textContent.value = '加载中…'
    try {
      textContent.value = await fetchText(item.id)
    } catch (e) {
      textContent.value = '文本加载失败'
      ElMessage.error('文本加载失败')
    }
  } else if (category === 'office' && ext === 'pdf') {
    openDialog(item, 'pdf')
  } else if (category === 'office' && ext === 'docx') {
    // docx 直接下载，不进预览弹窗
    downloadFile(item.id)
  }
  // 二进制 / 其他：不预览
}

async function copyPreview() {
  const text = previewType.value === 'pdf' ? downloadUrl(current.value.id) : textContent.value
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch (e) {
    ElMessage.error('复制失败')
  }
}

/** 选中小说文件 → 选择提取范围（含素材）→ 提交提取任务 → 跳转到提取结果页查看进度 */
const extractDlg = reactive({ visible: false, item: null })
function startExtract(item) {
  Object.assign(extractDlg, { visible: true, item })
}

async function doExtract(options) {
  const item = extractDlg.item
  try {
    const res = await submitExtract(item.id, options)
    if (res.code !== 0) {
      ElMessage.error(res.message || '提交失败')
      return
    }
    ElMessage.success('已提交提取任务')
    dialogVisible.value = false
    router.push({ path: '/novel/extract', query: { id: res.data.id } })
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交提取任务失败'))
  }
}

function formatSize(bytes) {
  if (bytes == null) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

// 页面被 keep-alive 缓存，用 onActivated 保证每次进入都重新拉取
onActivated(loadFiles)
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* 文件卡片网格 */
.file-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
.file-card {
  position: relative;
  box-sizing: border-box;
  width: 140px;
  height: 180px;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.file-card.is-clickable {
  cursor: pointer;
}
.file-card.is-clickable:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
}
.file-card-preview {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fafafa;
}
.file-thumb {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.file-icon {
  font-size: 40px;
  color: #c0c4cc;
}
.file-card-info {
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: center;
  font-size: 12px;
  border-top: 1px solid #f0f0f0;
}
.file-name {
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-size {
  color: #909399;
}
.file-download {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 3px;
  font-size: 13px;
  color: #ffffff;
  background: rgba(0, 0, 0, 0.45);
  border-radius: 50%;
  cursor: pointer;
}
.file-download:hover {
  background: rgba(0, 0, 0, 0.7);
}
.file-extract {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 4px;
  font-size: 14px;
  color: #ffffff;
  background: var(--el-color-success);
  border-radius: 50%;
  cursor: pointer;
  opacity: 0.85;
}
.file-extract:hover {
  opacity: 1;
}

/* 预览弹窗 */
.preview-body {
  text-align: center;
}
.preview-image {
  max-width: 100%;
  max-height: 68vh;
  border-radius: 6px;
}
.preview-row {
  display: flex;
  gap: 12px;
}
.preview-main {
  flex: 1;
  min-width: 0;
}
.preview-iframe {
  width: 100%;
  height: 66vh;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}
.preview-text {
  margin: 0;
  padding: 12px;
  max-height: 66vh;
  overflow: auto;
  background: #f7f8fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
}
.preview-actions {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.preview-actions :deep(.el-button) {
  margin-left: 0;
}
</style>
