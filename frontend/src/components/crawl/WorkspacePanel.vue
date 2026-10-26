<template>
  <!-- 抓取进度：一个首页一个工作区，单本抓取和整站抓取都在里面，每本小说的进度具体到第几章（「来源」区分） -->
  <div class="ws-layout">
    <!-- 左：工作区列表 -->
    <div class="ws-list">
      <div class="ws-list-head">
        <span class="ws-list-title">工作区（{{ workspaces.length }}）</span>
        <el-button size="small" :icon="Refresh" :loading="loadingList" @click="reloadAll">刷新</el-button>
      </div>
      <el-empty v-if="!workspaces.length" :image-size="64" description="还没有抓取：在「单本抓取」或「全自动抓取」里开始抓取" />
      <div
        v-for="w in workspaces"
        :key="w.homeUrl"
        class="ws-card"
        :class="{ active: w.homeUrl === home, running: w.status === 'RUNNING' }"
        @click="select(w.homeUrl)"
      >
        <div class="ws-card-top">
          <span class="ws-name">{{ w.siteName || w.host }}</span>
          <el-tag size="small" :type="w.status === 'RUNNING' ? 'warning' : 'info'" effect="dark">
            {{ w.status === 'RUNNING' ? '抓取中' : '空闲' }}
          </el-tag>
        </div>
        <div class="meta mono">{{ w.homeUrl }}</div>
        <el-progress
          :percentage="w.books.total ? Math.round((w.books.succeeded * 100) / w.books.total) : 0"
          :stroke-width="6"
          :status="w.status === 'RUNNING' ? '' : w.books.failed ? 'warning' : 'success'"
          class="ws-card-progress"
        />
        <div class="meta">
          已完成 {{ w.books.succeeded }}/{{ w.books.total }} 本
          <span v-if="w.books.failed" class="err">· 失败 {{ w.books.failed }}</span>
          <span v-if="w.books.queued">· 排队 {{ w.books.queued }}</span>
        </div>
        <div v-if="w.current" class="meta ellipsis ws-card-current">
          正在抓《{{ w.current.bookName }}》{{ chapterText(w.current) }}
        </div>
      </div>
    </div>

    <!-- 右：工作区详情 -->
    <div class="ws-detail">
      <el-empty v-if="!current" :image-size="80" description="在左侧选择一个工作区" />
      <template v-else>
        <div class="ws-head">
          <div>
            <div class="ws-title">
              {{ current.siteName || current.host }}
              <el-tag size="small" :type="current.status === 'RUNNING' ? 'warning' : 'info'" effect="dark" class="ml6">
                {{ current.status === 'RUNNING' ? '抓取中' : '空闲' }}
              </el-tag>
            </div>
            <a class="meta mono" :href="current.homeUrl" target="_blank" rel="noopener noreferrer">{{ current.homeUrl }}</a>
            <span class="meta">· 单本抓取 {{ current.sources?.book || 0 }} 次 · 整站抓取 {{ current.sources?.site || 0 }} 次</span>
          </div>
          <div class="ws-ops">
            <el-button v-if="current.status === 'RUNNING'" type="danger" plain :loading="acting" @click="doCancel">取消抓取</el-button>
            <el-button v-if="current.resumable" type="warning" plain :loading="acting" @click="doResume">继续未完成的</el-button>
            <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
            <el-button v-if="current.status !== 'RUNNING'" type="danger" link :loading="acting" @click="doDelete">删除工作区</el-button>
          </div>
        </div>

        <div class="ws-stats">
          <div v-for="s in STATS" :key="s.key" class="ws-stat" :class="s.cls">
            <div class="ws-stat-value">{{ current.books[s.key] || 0 }}</div>
            <div class="ws-stat-label">{{ s.label }}</div>
          </div>
          <div class="ws-stat">
            <div class="ws-stat-value">{{ formatWords(current.words) }}</div>
            <div class="ws-stat-label">已抓字数</div>
          </div>
        </div>

        <el-alert v-if="current.current" type="warning" :closable="false" class="ws-now">
          <template #title>
            正在抓《{{ current.current.bookName }}》{{ chapterText(current.current) }}
          </template>
          <div class="meta">{{ current.current.message }}</div>
          <el-progress :percentage="current.current.progress || 0" :stroke-width="8" />
        </el-alert>

        <div class="ws-filter">
          <el-radio-group v-model="query.status" size="small" @change="onFilter">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="ACTIVE">进行中</el-radio-button>
            <el-radio-button value="SUCCEEDED">已完成</el-radio-button>
            <el-radio-button value="FAILED">失败</el-radio-button>
            <el-radio-button value="CANCELLED">已取消</el-radio-button>
          </el-radio-group>
          <div class="ws-filter-right">
            <el-select v-model="query.source" size="small" class="ws-source" @change="onFilter">
              <el-option label="全部来源" value="" />
              <el-option label="单本抓取" value="book" />
              <el-option label="整站抓取" value="site" />
            </el-select>
            <el-input v-model="query.keyword" size="small" class="ws-search" placeholder="书名" clearable :prefix-icon="Search" @keyup.enter="onFilter" @clear="onFilter" />
          </div>
        </div>

        <el-table v-loading="loadingBooks" :data="books" size="small" row-key="key" :row-class-name="({ row }) => `ws-row-${row.status}`">
          <el-table-column label="书名" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="book-name">{{ row.bookName || (row.source === 'book' && row.status !== 'SUCCEEDED' ? '（解析中）' : row.url) }}</div>
              <div class="meta">{{ row.author || '' }}<span v-if="row.category"> · {{ row.category }}</span></div>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.source === 'site' ? 'warning' : 'primary'" effect="plain">
                {{ row.source === 'site' ? '整站抓取' : '单本抓取' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="86">
            <template #default="{ row }">
              <el-tag size="small" :type="STATUS[row.status]?.type">{{ STATUS[row.status]?.label || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="190">
            <template #default="{ row }">
              <el-progress
                :percentage="row.status === 'SUCCEEDED' ? 100 : row.progress || 0"
                :stroke-width="8"
                :status="row.status === 'SUCCEEDED' ? 'success' : ['FAILED', 'CANCELLED'].includes(row.status) ? 'exception' : ''"
              />
              <div class="meta">
                <template v-if="row.chapterTotal">第 {{ row.chapterDone || 0 }}/{{ row.chapterTotal }} 章</template>
                <template v-else>{{ row.status === 'QUEUED' ? '等待中' : '-' }}</template>
                <span v-if="row.chapterFailed" class="err"> · 失败 {{ row.chapterFailed }} 章</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="当前 / 说明" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span :class="{ err: row.status === 'FAILED' }">{{ row.message || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="字数" width="90">
            <template #default="{ row }">{{ row.wordCount ? formatWords(row.wordCount) : '-' }}</template>
          </el-table-column>
          <el-table-column prop="updateTime" label="更新时间" width="150" />
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.fileId" link type="primary" @click="emit('extract', row)">小说提取</el-button>
              <!-- 单本抓取：每本就是一个任务，可以单独取消 / 继续 / 重抓 / 改参数 / 删除；整站抓取的书由工作区统一操作 -->
              <template v-if="row.source === 'book'">
                <el-button v-if="isActive(row)" link type="danger" @click="rowCancel(row)">取消</el-button>
                <template v-else>
                  <el-button v-if="['FAILED', 'CANCELLED'].includes(row.status)" link type="warning" @click="emit('resume', row.task)">继续</el-button>
                  <el-dropdown trigger="click" @command="(cmd) => rowCommand(cmd, row)">
                    <el-button link>更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="retry">从头重抓</el-dropdown-item>
                        <el-dropdown-item command="reuse">改参数</el-dropdown-item>
                        <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
              </template>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="total > 0"
          v-model:current-page="query.page"
          v-model:page-size="query.size"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          small
          class="ws-pager"
          @current-change="loadBooks"
          @size-change="onFilter"
        />
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import {
  cancelCrawl,
  cancelWorkspace,
  deleteCrawls,
  deleteWorkspace,
  listWorkspaceBooks,
  listWorkspaces,
  resumeWorkspace,
  retryCrawl
} from '@/api/crawl'
import { errorMessage } from '@/api/request'

const props = defineProps({
  visible: { type: Boolean, default: false }, // 当前子页面是不是「抓取进度」：不可见时不轮询
  preferHome: { type: String, default: '' } // 外部指定要打开的工作区（提交单本 / 全自动抓取后）
})
// extract 小说提取；resume 单本任务从断点继续（父页面的续抓弹窗，可换站点地址）；reuse 改参数（回单本抓取表单）
const emit = defineEmits(['extract', 'resume', 'reuse'])

const STATUS = {
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '抓取中', type: 'warning' },
  SUCCEEDED: { label: '已完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
  CANCELLED: { label: '已取消', type: 'info' }
}
const STATS = [
  { key: 'total', label: '书' },
  { key: 'succeeded', label: '已完成', cls: 'ok' },
  { key: 'running', label: '抓取中', cls: 'warn' },
  { key: 'queued', label: '排队' },
  { key: 'failed', label: '失败', cls: 'bad' },
  { key: 'cancelled', label: '已取消' }
]
const POLL_MS = 3000

const workspaces = ref([])
const home = ref('')
const books = ref([])
const total = ref(0)
const query = reactive({ status: '', source: '', keyword: '', page: 1, size: 20 })
const isActive = (row) => row.status === 'QUEUED' || row.status === 'RUNNING'
const loadingList = ref(false)
const loadingBooks = ref(false)
const acting = ref(false)
let timer = null

const current = computed(() => workspaces.value.find((w) => w.homeUrl === home.value) || null)

/** 「第 3/120 章：章节名」：从 Python 任务的说明里取当前章节，没有就用章节计数 */
function chapterText(cur) {
  const m = /第\s*(\d+)\s*\/\s*(\d+)\s*章[：:]\s*(.*)$/.exec(cur.message || '')
  if (m) return `：第 ${m[1]}/${m[2]} 章 · ${m[3]}`
  return cur.chapterTotal ? `：第 ${cur.chapterDone}/${cur.chapterTotal} 章` : '：准备中'
}

function formatWords(n) {
  if (!n) return '0'
  return n >= 10000 ? `${(n / 10000).toFixed(n >= 1000000 ? 0 : 1)} 万` : String(n)
}

async function loadList() {
  loadingList.value = true
  try {
    const res = await listWorkspaces()
    if (res.code === 0) {
      workspaces.value = res.data || []
      if (!current.value) home.value = workspaces.value.length ? workspaces.value[0].homeUrl : ''
    }
  } catch {
    // 后端没起时不影响其它功能
  } finally {
    loadingList.value = false
  }
}

async function loadBooks() {
  if (!home.value) {
    books.value = []
    total.value = 0
    return
  }
  loadingBooks.value = true
  try {
    const res = await listWorkspaceBooks({
      home: home.value,
      status: query.status || undefined,
      source: query.source || undefined,
      keyword: query.keyword.trim() || undefined,
      page: query.page,
      size: query.size
    })
    if (res.code === 0) {
      books.value = res.data.records || []
      total.value = res.data.total || 0
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载工作区书籍失败'))
  } finally {
    loadingBooks.value = false
  }
}

async function reloadAll() {
  await loadList()
  await loadBooks()
  schedulePoll()
}

function select(h) {
  if (home.value === h) return
  home.value = h
  Object.assign(query, { status: '', source: '', keyword: '', page: 1 })
  loadBooks()
}

function onFilter() {
  query.page = 1
  loadBooks()
}

/** 有抓取中的工作区、且当前就在这个子页面时，每 3 秒刷新 */
function schedulePoll() {
  stopPoll()
  if (!props.visible || !workspaces.value.some((w) => w.status === 'RUNNING')) return
  timer = setTimeout(async () => {
    await loadList()
    await loadBooks()
    schedulePoll()
  }, POLL_MS)
}

function stopPoll() {
  if (timer) clearTimeout(timer)
  timer = null
}

async function act(fn, okText) {
  acting.value = true
  try {
    const res = await fn(home.value)
    if (res.code !== 0) {
      ElMessage.error(res.message || '操作失败')
      return
    }
    if (okText) ElMessage.success(okText)
    await reloadAll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    acting.value = false
  }
}

async function doCancel() {
  try {
    await ElMessageBox.confirm('取消这个网站所有排队 / 正在抓的小说（单本和整站）？已抓到的章节都保留，之后可以「继续未完成的」。', '取消抓取', { type: 'warning' })
  } catch {
    return
  }
  await act(cancelWorkspace, '已取消')
}

async function doResume() {
  await act(resumeWorkspace, '已继续：没抓完的小说从断点接着抓（同一网站依次排队）')
}

/** 单本抓取行：取消 */
async function rowCancel(row) {
  try {
    const res = await cancelCrawl(row.crawlId)
    if (res.code !== 0) ElMessage.error(res.message || '取消失败')
    await reloadAll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '取消失败'))
  }
}

/** 单本抓取行：从头重抓 / 改参数 / 删除 */
async function rowCommand(cmd, row) {
  if (cmd === 'reuse') {
    emit('reuse', row.task)
    return
  }
  try {
    if (cmd === 'retry') {
      const res = await retryCrawl(row.crawlId)
      if (res.code !== 0) return ElMessage.error(res.message || '提交失败')
      ElMessage.success('已重新开始抓取')
    } else if (cmd === 'delete') {
      await ElMessageBox.confirm(`删除「${row.bookName || row.url}」的抓取记录和断点？已保存到文件管理的 txt 不受影响。`, '删除', { type: 'warning' })
      const res = await deleteCrawls([row.crawlId])
      if (res.code !== 0) return ElMessage.error(res.message || '删除失败')
      ElMessage.success('已删除')
    }
    await reloadAll()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

async function doDelete() {
  try {
    await ElMessageBox.confirm(
      `删除工作区「${current.value.siteName || current.value.host}」？这个网站的单本 / 整站抓取记录、每本小说的进度和断点都会删除，已保存到文件管理的 txt 不受影响。`,
      '删除工作区',
      { type: 'warning' }
    )
  } catch {
    return
  }
  const h = home.value
  home.value = ''
  acting.value = true
  try {
    const res = await deleteWorkspace(h)
    if (res.code !== 0) {
      ElMessage.error(res.message || '删除失败')
      home.value = h
      return
    }
    ElMessage.success('已删除工作区')
    await reloadAll()
  } catch (e) {
    home.value = h
    ElMessage.error(errorMessage(e, '删除失败'))
  } finally {
    acting.value = false
  }
}

// 进入本子页面时刷新并按需轮询；离开时停止
watch(
  () => props.visible,
  (v) => {
    if (v) reloadAll()
    else stopPoll()
  },
  { immediate: true }
)
// 提交全自动抓取后打开对应工作区
watch(
  () => props.preferHome,
  async (h) => {
    if (!h) return
    await loadList()
    home.value = h
    Object.assign(query, { status: '', source: '', keyword: '', page: 1 })
    await loadBooks()
    schedulePoll()
  }
)
onBeforeUnmount(stopPoll)

defineExpose({ reloadAll })
</script>

<style scoped>
.ws-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.ws-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ws-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ws-list-title {
  font-weight: 600;
  color: #303133;
}
.ws-card {
  padding: 12px 14px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafbfc;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.ws-card:hover {
  border-color: var(--el-color-primary-light-5);
}
.ws-card.active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
  background: #fff;
}
.ws-card.running {
  border-left: 3px solid var(--el-color-warning);
}
.ws-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
}
.ws-name {
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ws-card-progress {
  margin: 6px 0 2px;
}
.ws-card-current {
  margin-top: 4px;
  color: #b88230;
}
.ws-detail {
  min-width: 0;
}
.ws-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.ws-title {
  font-size: 17px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 2px;
}
.ws-ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ws-stats {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.ws-stat {
  padding: 10px 12px;
  background: #f7f8fa;
  border-radius: 8px;
  text-align: center;
}
.ws-stat-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
.ws-stat-label {
  font-size: 12px;
  color: #909399;
}
.ws-stat.ok .ws-stat-value {
  color: #67c23a;
}
.ws-stat.warn .ws-stat-value {
  color: #e6a23c;
}
.ws-stat.bad .ws-stat-value {
  color: #f56c6c;
}
.ws-now {
  margin-bottom: 12px;
}
.ws-filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.ws-search {
  width: 220px;
}
.ws-filter-right {
  display: flex;
  gap: 8px;
}
.ws-source {
  width: 120px;
}
.ws-pager {
  margin-top: 10px;
  justify-content: flex-end;
}
.book-name {
  font-weight: 500;
  color: #303133;
}
.ws-detail :deep(.ws-row-RUNNING) {
  background: #fdf6ec;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.mono {
  font-family: Consolas, monospace;
  word-break: break-all;
}
.err {
  color: #f56c6c;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ml6 {
  margin-left: 6px;
}
@media (max-width: 1100px) {
  .ws-layout {
    grid-template-columns: 1fr;
  }
  .ws-stats {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
