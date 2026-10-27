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
            <span
              v-if="isExtractable(item.fileExt) && extractInfo(item)"
              class="extract-badge"
              :class="`is-${extractInfo(item).state}`"
              :title="extractInfo(item).tip"
            >
              {{ extractInfo(item).label }}
            </span>
          </div>

          <div class="file-card-info">
            <span class="file-name">{{ item.fileName }}</span>
            <span class="file-size">
              {{ formatSize(item.fileSize) }}
              <template v-if="chapterText(item)"> · <span :title="chapterTip(item)">{{ chapterText(item) }}</span></template>
            </span>
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
            :title="extractInfo(item) ? `小说提取（${extractInfo(item).tip}，仍可再次提取）` : '小说提取'"
            @click.stop="startExtract(item)"
          >
            <MagicStick />
          </el-icon>
        </div>
      </div>
    </el-card>

    <ExtractOptionsDialog
      v-model="extractDlg.visible"
      :file-name="extractDlg.item?.fileName"
      :file-size="extractDlg.item?.fileSize || 0"
      @confirm="doExtract"
    />

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
            <template v-else>
              <pre ref="textBox" class="preview-text" @scroll="onTextScroll">{{ textContent }}</pre>
              <div v-if="textPage.total" class="preview-more">
                已显示 {{ formatChars(textPage.next) }} / {{ formatChars(textPage.total) }} 字
                <el-button v-if="!textPage.done" link type="primary" :loading="textPage.loading" @click="loadMoreText">
                  加载更多
                </el-button>
              </div>
            </template>
          </div>
          <div class="preview-actions">
            <el-button type="primary" @click="downloadFile(current.id)">下载</el-button>
            <el-button @click="copyPreview">
              {{ previewType === 'pdf' ? '复制地址' : '复制全文' }}
            </el-button>
            <el-button v-if="isExtractable(current.fileExt)" type="success" @click="startExtract(current)">
              {{ extractInfo(current)?.state === 'done' ? '再次提取' : '小说提取' }}
            </el-button>
            <span v-if="isExtractable(current.fileExt) && extractInfo(current)" class="extract-hint">
              {{ extractInfo(current).tip }}
            </span>
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
import { classify, downloadFile, downloadUrl, fetchText, fetchTextPage, listFiles, previewUrl } from '@/api/file'
import { bookOf, isExtractable, listExtracts, submitExtract } from '@/api/novel'
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
// 文本分页：每次取 PAGE_CHARS 字，滚到底部附近自动续上（9MB 的 txt 约 450 万字，一次渲染会卡死页面）
const PAGE_CHARS = 100000
const textBox = ref(null)
const textPage = reactive({ id: null, next: 0, total: 0, done: true, loading: false })

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

/**
 * 已提取的小说：按书名（bookOf，去扩展名 / 站点标记 / 副本后缀）比对提取任务。
 * 只做提示，不禁止再次提取（可能是同名的另一本书，或之前提取不完整）
 */
const extractsByBook = ref(new Map())
async function loadExtracts() {
  try {
    const res = await listExtracts()
    if (res.code !== 0) return
    const map = new Map()
    for (const t of res.data || []) {
      const book = bookOf(t.fileName)
      if (!book) continue
      const e = map.get(book) || { done: 0, running: 0, last: null }
      if (t.status === 'SUCCEEDED') {
        e.done++
        if (!e.last || (t.createTime || '') > (e.last.createTime || '')) e.last = t
      } else if (t.status === 'QUEUED' || t.status === 'RUNNING') {
        e.running++
      }
      map.set(book, e)
    }
    extractsByBook.value = map
  } catch (e) {
    // 只影响「已提取」标记，不打扰文件列表
  }
}

function extractInfo(item) {
  const e = extractsByBook.value.get(bookOf(item?.fileName))
  if (!e) return null
  if (e.running) return { state: 'running', label: '提取中', tip: `同名小说有 ${e.running} 个提取任务进行中` }
  if (!e.done) return null
  const time = e.last?.createTime ? `，最近 ${String(e.last.createTime).slice(0, 16)}` : ''
  return { state: 'done', label: '已提取', tip: `同名小说已提取 ${e.done} 次${time}` }
}

async function loadFiles() {
  loading.value = true
  loadExtracts()
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
  Object.assign(textPage, { id: item.id, next: 0, total: 0, done: true, loading: false })
  dialogVisible.value = true
}

async function loadMoreText() {
  if (textPage.loading || textPage.done) return
  const id = textPage.id
  textPage.loading = true
  try {
    const res = await fetchTextPage(id, textPage.next, PAGE_CHARS)
    if (id !== textPage.id) return // 已换成别的文件
    if (res.code !== 0) throw new Error(res.message)
    const page = res.data
    textContent.value = textPage.next === 0 ? page.text : textContent.value + page.text
    Object.assign(textPage, { next: page.nextOffset, total: page.totalChars, done: page.done })
  } catch (e) {
    if (id !== textPage.id) return
    if (textPage.next === 0) textContent.value = '文本加载失败'
    ElMessage.error(errorMessage(e, '文本加载失败'))
  } finally {
    if (id === textPage.id) textPage.loading = false
  }
}

function onTextScroll() {
  const el = textBox.value
  if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 400) loadMoreText()
}

function formatChars(n) {
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n)
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
    textPage.done = false
    await loadMoreText()
  } else if (category === 'office' && ext === 'pdf') {
    openDialog(item, 'pdf')
  } else if (category === 'office' && ext === 'docx') {
    // docx 直接下载，不进预览弹窗
    downloadFile(item.id)
  }
  // 二进制 / 其他：不预览
}

async function copyPreview() {
  try {
    let text = textContent.value
    if (previewType.value === 'pdf') text = downloadUrl(current.value.id)
    else if (!textPage.done) text = await fetchText(current.value.id) // 只取不渲染，不会卡
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

/** 章节数：后端逐个数章节标题行得出（不看最后一章写的序号）；null = 非 txt/md 或尚未统计 */
function chapterText(item) {
  const n = item.chapterCount
  if (n == null || n < 0) return ''
  return n > 0 ? `${n} 章` : '未识别章节'
}

function chapterTip(item) {
  return item.chapterCount > 0
    ? '按「第X章 / Chapter N」等标题行逐个数出的章节数，与小说提取切分的章节一致'
    : '没有找到「第X章」之类的章节标题，提取时会整篇当作一章'
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
.file-card-preview {
  position: relative;
}
.extract-badge {
  position: absolute;
  top: 6px;
  left: 6px;
  padding: 1px 6px;
  font-size: 11px;
  line-height: 16px;
  border-radius: 8px;
  color: #ffffff;
}
.extract-badge.is-done {
  background: var(--el-color-success);
}
.extract-badge.is-running {
  background: var(--el-color-warning);
}
.extract-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
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
.preview-more {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
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
