<template>
  <div class="extract-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">小说提取 · 工作区</span>
          <div>
            <el-button @click="router.push('/ai/model')">模型配置</el-button>
            <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
            <el-button type="primary" :icon="Plus" @click="router.push('/file/manage')">去选择小说</el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="!tasks.length" description="还没有提取工作区：在「文件管理」里选小说文件，点「小说提取」" />

      <template v-else>
        <div class="toolbar">
          <el-radio-group v-model="filter" size="small">
            <el-radio-button v-for="(f, k) in FILTERS" :key="k" :value="k">{{ f.label }}（{{ counts[k] || 0 }}）</el-radio-button>
          </el-radio-group>
          <el-input v-model="keyword" size="small" clearable placeholder="按书名 / 工作区名搜索" class="search" />
        </div>
        <el-empty v-if="!groups.length" description="没有符合条件的工作区" />
        <!-- 按书分组：同一本书可以有多个工作区 -->
        <section v-for="g in groups" :key="g.book" class="book-group">
          <div class="group-head">
            <span class="group-title">《{{ g.book }}》</span>
            <span class="muted">{{ g.items.length }} 个工作区</span>
            <el-button link type="primary" size="small" :icon="Plus" @click="newFor(g.items[0])">新建工作区</el-button>
          </div>
          <div class="novel-grid">
            <div v-for="t in g.items" :key="t.id" class="novel-card" @click="open(t)">
              <div class="card-top">
                <div class="novel-title" :title="t.fileName">{{ wsTitle(t) }}</div>
                <el-dropdown trigger="click" @command="(c) => onCommand(c, t)">
                  <el-button link :icon="MoreFilled" @click.stop />
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="rename" :icon="EditPen">改名</el-dropdown-item>
                      <el-dropdown-item command="delete" :icon="Delete" divided>删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
              <div class="novel-sub">{{ wsSubtitle(t) }}</div>
              <div class="novel-meta">
                <span>
                  <el-tag :type="WS_STATUS[t.status]?.type" size="small">{{ WS_STATUS[t.status]?.label || t.status }}</el-tag>
                  <span v-if="['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(t.status)" class="pct">{{ t.progress || 0 }}%</span>
                </span>
                <el-tag v-if="cardText(t)" :type="cardText(t).type" size="small" effect="plain">{{ cardText(t).label }}</el-tag>
              </div>
              <el-progress
                v-if="['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(t.status)"
                class="bar"
                :percentage="t.progress || 0"
                :show-text="false"
                :stroke-width="4"
                :status="t.status === 'INTERRUPTED' ? 'warning' : ''"
              />
              <div class="novel-msg" :title="t.message">{{ t.message || '' }}</div>
              <div class="novel-foot">
                <span class="muted">更新于 {{ String(t.updateTime || '').slice(0, 16) }}</span>
                <span class="muted">{{ wan(t.wordCount) }}</span>
              </div>
            </div>
          </div>
        </section>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Delete, EditPen, MoreFilled, Plus, Refresh } from '@element-plus/icons-vue'
import { bookOf, createExtractDraft, listExtracts } from '@/api/novel'
import { errorMessage } from '@/api/request'
import { WS_STATUS, deleteWorkspace, optionsOf, renameWorkspace, wsSubtitle, wsTitle } from '@/components/material/extractWorkspaces'

/**
 * 小说提取 = 工作区列表（同「小说创作」），按书分组，同一本书可以有多个工作区（比如快速档读全书 + 深拆读前 10 章）。
 * 点进去是全屏的提取工作区，顶部切换 提取工作区 / 卡片整理 / 素材选择（views/novel/extractWorkspace.vue）。
 */
const FILTERS = {
  all: { label: '全部', test: () => true },
  active: { label: '提取中', test: (t) => ['DRAFT', 'QUEUED', 'RUNNING', 'INTERRUPTED'].includes(t.status) },
  done: { label: '提取完成', test: (t) => t.status === 'SUCCEEDED' },
  failed: { label: '失败', test: (t) => t.status === 'FAILED' }
}
const POLL_MS = 3000

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const tasks = ref([])
const filter = ref('all')
const keyword = ref('')
let timer = null

const counts = computed(() => {
  const c = {}
  for (const k in FILTERS) c[k] = tasks.value.filter(FILTERS[k].test).length
  return c
})
/* 筛选后按书名分组；组按最近更新排序，组内也是 */
const groups = computed(() => {
  const kw = keyword.value.trim()
  const byBook = new Map()
  for (const t of tasks.value) {
    if (!FILTERS[filter.value].test(t)) continue
    const book = bookOf(t.fileName) || t.fileName || '未命名'
    if (kw && !book.includes(kw) && !(t.title || '').includes(kw)) continue
    if (!byBook.has(book)) byBook.set(book, [])
    byBook.get(book).push(t)
  }
  const time = (t) => String(t.updateTime || '')
  return [...byBook.entries()]
    .map(([book, items]) => ({ book, items: items.sort((a, b) => time(b).localeCompare(time(a))) }))
    .sort((a, b) => time(b.items[0]).localeCompare(time(a.items[0])))
})

function cardText(t) {
  const st = t.latestCompile?.status
  if (['QUEUED', 'RUNNING'].includes(st)) return { label: `卡片整理中 ${t.latestCompile.progress || 0}%`, type: 'warning' }
  if (st === 'INTERRUPTED') return { label: '卡片整理已暂停', type: 'warning' }
  if (t.pendingCount > 0) return { label: `${t.pendingCount} 条素材待选择`, type: 'warning' }
  if (st === 'SUCCEEDED' || t.candidateCount > 0) return { label: '素材已处理', type: 'success' }
  if (t.status === 'SUCCEEDED' && optionsOf(t).materials?.enabled) return { label: '未整理卡片', type: 'info' }
  return null
}
const wan = (n) => (n ? (n >= 10000 ? `${(n / 10000).toFixed(1)} 万字` : `${n} 字`) : '')

function open(t) {
  router.push(`/novel/extract/${t.id}`)
}

/** 同一本书再建一个工作区（用这一组里某个工作区的文件；这个文件已有未开始的就打开它） */
async function newFor(t) {
  try {
    const res = await createExtractDraft(t.fileId)
    if (res.code !== 0) throw new Error(res.message)
    router.push(`/novel/extract/${res.data.id}`)
  } catch (e) {
    ElMessage.error(errorMessage(e, '新建提取工作区失败'))
  }
}

async function onCommand(cmd, t) {
  if (cmd === 'rename') {
    const title = await renameWorkspace(t)
    if (title !== null) t.title = title
  } else if (cmd === 'delete' && (await deleteWorkspace(t))) {
    await loadTasks()
  }
}

const hasActive = () =>
  tasks.value.some(
    (t) => ['QUEUED', 'RUNNING'].includes(t.status) || ['QUEUED', 'RUNNING'].includes(t.latestCompile?.status)
  )

async function loadTasks() {
  loading.value = true
  try {
    const res = await listExtracts()
    if (res.code === 0) tasks.value = res.data || []
    else ElMessage.error(res.message || '加载失败')
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载提取任务失败'))
  } finally {
    loading.value = false
  }
}

/** 有进行中的任务时定时刷新，全部结束后停止 */
function schedulePoll() {
  stopPoll()
  timer = setTimeout(async () => {
    await loadTasks()
    if (hasActive()) schedulePoll()
  }, POLL_MS)
}
function stopPoll() {
  if (timer) clearTimeout(timer)
  timer = null
}

// 页面被 keep-alive 缓存：进入时拉取并按需轮询，离开时停止轮询；旧链接 ?id= 直接进那个工作区
onActivated(async () => {
  const id = Number(route.query.id)
  if (id) {
    router.replace(`/novel/extract/${id}`)
    return
  }
  await loadTasks()
  if (hasActive()) schedulePoll()
})
onDeactivated(stopPoll)
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(60, 40, 20, 0.06);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.search {
  width: 200px;
  margin-left: auto;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.novel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.novel-card {
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.novel-card:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
}
.book-group {
  margin-bottom: 20px;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.group-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.card-top {
  display: flex;
  align-items: center;
  gap: 6px;
}
.card-top .novel-title {
  flex: 1;
  min-width: 0;
}
.novel-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.novel-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.novel-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.pct {
  margin-left: 6px;
}
.bar {
  margin-top: 6px;
}
.novel-msg {
  margin-top: 6px;
  min-height: 18px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.novel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
</style>
