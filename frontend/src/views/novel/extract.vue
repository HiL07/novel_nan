<template>
  <div class="extract-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">小说提取</span>
          <div>
            <el-button @click="router.push('/ai/model')">模型配置</el-button>
            <el-button @click="router.push('/file/manage')">去选择文件</el-button>
            <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="!tasks.length" description="暂无提取任务，请在「文件管理」中选择小说文件后点击「小说提取」" />

      <el-table v-else :data="tasks" stripe>
        <el-table-column prop="fileName" label="文件" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="STATUS[row.status]?.type" size="small">{{ STATUS[row.status]?.label || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress
              :percentage="row.progress || 0"
              :status="row.status === 'SUCCEEDED' ? 'success' : row.status === 'FAILED' ? 'exception' : ''"
            />
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip />
        <el-table-column prop="createTime" label="创建时间" width="170" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="row.status !== 'SUCCEEDED'" @click="openDetail(row.id)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 结果详情 -->
    <el-drawer v-model="drawerVisible" :title="detail?.fileName" size="60%" destroy-on-close>
      <el-tabs v-if="result" v-model="drawerTab">
        <el-tab-pane label="提取结果" name="result">
      <div class="result">
        <div class="result-actions">
          <el-button type="primary" :icon="Download" :disabled="!!draft" @click="downloadJson">下载 JSON</el-button>
          <template v-if="!draft">
            <el-button :icon="EditPen" @click="startEdit">修改结果</el-button>
            <span v-if="result.editedAt" class="chapter-meta">已手动修改 · {{ result.editedAt }}</span>
          </template>
          <template v-else>
            <el-button type="success" :icon="Check" :loading="saving" @click="saveEdit">保存修改</el-button>
            <el-button @click="draft = null">取消</el-button>
            <span class="chapter-meta">AI 提取的摘要、人物、事件、伏笔、文风都可以改；展开章节即可编辑</span>
          </template>
        </div>

        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="总字数">{{ result.wordCount }}</el-descriptions-item>
          <el-descriptions-item label="章节数">{{ result.chapterCount }}</el-descriptions-item>
          <el-descriptions-item label="对话占比">{{ percent(result.style?.dialogRatio) }}</el-descriptions-item>
          <el-descriptions-item label="节奏">
            <el-input v-if="draft" v-model="draft.style.pace" size="small" />
            <template v-else>{{ result.style?.pace || '-' }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="基调">
            <el-input-tag v-if="draft" v-model="draft.style.tones" size="small" />
            <template v-else>{{ (result.style?.tones || []).join('、') || '-' }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="解析失败分块">{{ result.failedChunks }}</el-descriptions-item>
          <el-descriptions-item label="使用模型">{{ result.model || '-' }}</el-descriptions-item>
        </el-descriptions>

        <h4>
          人物（{{ view.characters?.length || 0 }}）
          <el-button v-if="draft" link type="primary" :icon="Plus" @click="draft.characters.unshift({ name: '', role: '', firstAppear: '', chapterCount: 0 })">添加人物</el-button>
        </h4>
        <el-table v-if="draft" :data="draft.characters" size="small" max-height="360">
          <el-table-column label="姓名" width="140">
            <template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
          </el-table-column>
          <el-table-column label="身份 / 首次动作" min-width="220">
            <template #default="{ row }"><el-input v-model="row.role" size="small" /></template>
          </el-table-column>
          <el-table-column label="首次出场" width="160">
            <template #default="{ row }"><el-input v-model="row.firstAppear" size="small" /></template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }"><el-button link type="danger" :icon="Delete" @click="draft.characters.splice($index, 1)" /></template>
          </el-table-column>
        </el-table>
        <el-table v-else :data="result.characters" size="small" max-height="300">
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="role" label="身份 / 首次动作" min-width="200" show-overflow-tooltip />
          <el-table-column prop="firstAppear" label="首次出场" width="160" show-overflow-tooltip />
          <el-table-column prop="chapterCount" label="出场章数" width="90" />
        </el-table>

        <h4>章节（{{ view.chapters?.length || 0 }}）</h4>
        <!-- 分页 + 只渲染展开的章节内容：长篇有数百章、上千条事件，全部渲染会卡 -->
        <el-collapse v-model="openChapters">
          <el-collapse-item v-for="(ch, i) in pagedChapters" :key="chapterOffset + i" :name="chapterOffset + i">
            <template #title>
              <span class="chapter-title">{{ ch.title }}</span>
              <span class="chapter-meta">{{ ch.wordCount }} 字</span>
            </template>
            <el-form v-if="draft && openChapters.includes(chapterOffset + i)" label-width="72px" size="small" class="chapter-edit">
              <el-form-item label="标题"><el-input v-model="ch.title" /></el-form-item>
              <el-form-item label="摘要"><el-input v-model="ch.summary" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" /></el-form-item>
              <el-form-item label="出场人物"><el-input-tag v-model="ch.characters" placeholder="回车添加" /></el-form-item>
              <el-form-item label="关键事件">
                <div class="events-edit">
                  <div v-for="(ev, j) in ch.events" :key="j" class="event-row">
                    <el-input v-model="ev.summary" placeholder="事件" class="ev-summary" />
                    <el-input v-model="ev.location" placeholder="地点" class="ev-meta" />
                    <el-input v-model="ev.time" placeholder="时间" class="ev-meta" />
                    <el-button link type="danger" :icon="Delete" @click="ch.events.splice(j, 1)" />
                  </div>
                  <el-button link type="primary" :icon="Plus" @click="ch.events.push({ summary: '', location: '', time: '' })">添加事件</el-button>
                </div>
              </el-form-item>
              <el-form-item label="伏笔"><el-input-tag v-model="ch.foreshadowing" placeholder="回车添加" /></el-form-item>
            </el-form>
            <template v-else-if="openChapters.includes(chapterOffset + i)">
            <p><b>摘要：</b>{{ ch.summary || '-' }}</p>
            <p><b>出场人物：</b>{{ ch.characters?.join('、') || '-' }}</p>
            <div v-if="ch.events?.length">
              <b>关键事件：</b>
              <ul>
                <li v-for="(ev, j) in ch.events" :key="j">
                  {{ ev.summary }}
                  <span v-if="ev.location || ev.time" class="chapter-meta">（{{ [ev.location, ev.time].filter(Boolean).join('，') }}）</span>
                </li>
              </ul>
            </div>
            <p v-if="ch.foreshadowing?.length"><b>伏笔：</b>{{ ch.foreshadowing.join('；') }}</p>
            </template>
          </el-collapse-item>
        </el-collapse>
        <el-pagination
          v-if="(view.chapters?.length || 0) > CHAPTER_PAGE"
          v-model:current-page="chapterPage"
          class="pager"
          small
          layout="prev, pager, next, total"
          :total="view.chapters.length"
          :page-size="CHAPTER_PAGE"
        />
      </div>
        </el-tab-pane>
        <el-tab-pane :label="`素材候选${result.materials ? '（' + result.materials.length + '）' : ''}`" name="materials" lazy>
          <el-alert
            v-if="!result.materials"
            type="info"
            :closable="false"
            show-icon
            title="这次提取没有开启素材提取。可在「文件管理」中重新提取并勾选「提取创作素材」。"
          />
          <CandidateReview v-else :extract-id="detail.id" />
        </el-tab-pane>
      </el-tabs>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check, Delete, Download, EditPen, Plus, Refresh } from '@element-plus/icons-vue'
import { getExtract, listExtracts, updateExtractResult } from '@/api/novel'
import CandidateReview from '@/components/material/CandidateReview.vue'
import { errorMessage } from '@/api/request'

const STATUS = {
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '提取中', type: 'warning' },
  SUCCEEDED: { label: '已完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' }
}
const POLL_MS = 3000
const CHAPTER_PAGE = 30

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const tasks = ref([])
const drawerVisible = ref(false)
const detail = ref(null)
const drawerTab = ref('result')
const chapterPage = ref(1)
const openChapters = ref([])
let timer = null

const result = computed(() => {
  if (!detail.value?.result) return null
  try {
    return JSON.parse(detail.value.result)
  } catch {
    return null
  }
})

const chapterOffset = computed(() => (chapterPage.value - 1) * CHAPTER_PAGE)
/* 修改结果：draft 为可编辑副本（深层响应式），保存时整体提交；查看时用只读的 result */
const draft = ref(null)
const saving = ref(false)
const view = computed(() => draft.value || result.value)
const pagedChapters = computed(() => view.value?.chapters?.slice(chapterOffset.value, chapterOffset.value + CHAPTER_PAGE) || [])

function startEdit() {
  const d = JSON.parse(JSON.stringify(result.value))
  d.style = d.style || {}
  d.style.tones = d.style.tones || []
  d.characters = d.characters || []
  d.chapters.forEach((ch) => {
    ch.characters = ch.characters || []
    ch.events = ch.events || []
    ch.foreshadowing = ch.foreshadowing || []
  })
  draft.value = d
}

async function saveEdit() {
  saving.value = true
  try {
    const d = draft.value
    d.characters = d.characters.filter((c) => c.name?.trim())
    d.chapters.forEach((ch) => (ch.events = ch.events.filter((ev) => ev.summary?.trim())))
    const res = await updateExtractResult(detail.value.id, d)
    if (res.code !== 0) throw new Error(res.message || '保存失败')
    detail.value = Object.freeze(res.data)
    draft.value = null
    ElMessage.success('提取结果已保存')
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存提取结果失败'))
  } finally {
    saving.value = false
  }
}

const hasActive = () => tasks.value.some((t) => t.status === 'QUEUED' || t.status === 'RUNNING')

async function loadTasks() {
  loading.value = true
  try {
    const res = await listExtracts()
    if (res.code === 0) {
      tasks.value = res.data || []
    } else {
      ElMessage.error(res.message || '加载失败')
    }
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

async function openDetail(id) {
  try {
    const res = await getExtract(id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '加载失败')
      return
    }
    detail.value = Object.freeze(res.data) // 只读展示：大结果不做深层响应式
    draft.value = null
    chapterPage.value = 1
    openChapters.value = []
    // 有待确认的素材候选时直接打开「素材候选」
    drawerTab.value = res.data.message?.includes("素材候选") ? "materials" : "result"
    drawerVisible.value = true
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载提取结果失败'))
  }
}

function downloadJson() {
  const blob = new Blob([JSON.stringify(result.value, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${(detail.value.fileName || 'novel').replace(/\.[^.]+$/, '')}_提取结果.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

function percent(v) {
  return typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : '-'
}

// 页面被 keep-alive 缓存：进入时拉取并按需轮询，离开时停止轮询
onActivated(async () => {
  await loadTasks()
  if (hasActive()) schedulePoll()
  const id = Number(route.query.id)
  const task = tasks.value.find((t) => t.id === id)
  if (task?.status === 'SUCCEEDED') openDetail(id)
})
onDeactivated(stopPoll)
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
.pager {
  margin-top: 10px;
  justify-content: center;
}
.chapter-edit {
  padding-top: 6px;
}
.events-edit {
  width: 100%;
}
.event-row {
  display: flex;
  gap: 6px;
  margin-bottom: 4px;
}
.ev-summary {
  flex: 1;
}
.ev-meta {
  width: 110px;
}
.result-actions {
  margin-bottom: 12px;
}
.result h4 {
  margin: 18px 0 8px;
  color: #303133;
}
.chapter-title {
  font-weight: 600;
}
.chapter-meta {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.result p,
.result ul {
  margin: 4px 0;
  line-height: 1.7;
}
</style>
