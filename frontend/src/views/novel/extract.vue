<template>
  <div class="extract-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">小说提取</span>
          <div>
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
      <div v-if="result" class="result">
        <div class="result-actions">
          <el-button type="primary" :icon="Download" @click="downloadJson">下载 JSON</el-button>
        </div>

        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="总字数">{{ result.wordCount }}</el-descriptions-item>
          <el-descriptions-item label="章节数">{{ result.chapterCount }}</el-descriptions-item>
          <el-descriptions-item label="对话占比">{{ percent(result.style?.dialogRatio) }}</el-descriptions-item>
          <el-descriptions-item label="节奏">{{ result.style?.pace || '-' }}</el-descriptions-item>
          <el-descriptions-item label="基调">{{ (result.style?.tones || []).join('、') || '-' }}</el-descriptions-item>
          <el-descriptions-item label="解析失败分块">{{ result.failedChunks }}</el-descriptions-item>
        </el-descriptions>

        <h4>人物（{{ result.characters?.length || 0 }}）</h4>
        <el-table :data="result.characters" size="small" max-height="300">
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="role" label="身份 / 首次动作" min-width="200" show-overflow-tooltip />
          <el-table-column prop="firstAppear" label="首次出场" width="160" show-overflow-tooltip />
          <el-table-column prop="chapterCount" label="出场章数" width="90" />
        </el-table>

        <h4>章节</h4>
        <el-collapse>
          <el-collapse-item v-for="(ch, i) in result.chapters" :key="i" :name="i">
            <template #title>
              <span class="chapter-title">{{ ch.title }}</span>
              <span class="chapter-meta">{{ ch.wordCount }} 字</span>
            </template>
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
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import { getExtract, listExtracts } from '@/api/novel'
import { errorMessage } from '@/api/request'

const STATUS = {
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '提取中', type: 'warning' },
  SUCCEEDED: { label: '已完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' }
}
const POLL_MS = 3000

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const tasks = ref([])
const drawerVisible = ref(false)
const detail = ref(null)
let timer = null

const result = computed(() => {
  if (!detail.value?.result) return null
  try {
    return JSON.parse(detail.value.result)
  } catch {
    return null
  }
})

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
    detail.value = res.data
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
