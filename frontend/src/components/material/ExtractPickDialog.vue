<template>
  <!-- 「小说提取」入口（文件管理 / 抓取进度）：这本书已有工作区时选一个打开，或新建；没有就直接新建 -->
  <el-dialog v-model="visible" :title="`《${book}》的提取工作区`" width="560px" append-to-body>
    <div class="list">
      <div v-for="t in rows" :key="t.id" class="row" @click="go(t.id)">
        <div class="main">
          <div class="title">{{ wsTitle(t) }}</div>
          <div class="sub">{{ wsSubtitle(t) }}<template v-if="t.fileName !== fileName"> · 文件 {{ t.fileName }}</template></div>
        </div>
        <el-tag :type="WS_STATUS[t.status]?.type" size="small">{{ WS_STATUS[t.status]?.label || t.status }}</el-tag>
        <span class="time">{{ String(t.updateTime || '').slice(0, 16) }}</span>
      </div>
    </div>
    <template #footer>
      <span class="hint">同一本书可以有多个工作区，比如一个快速档读全书、一个深拆读前几章</span>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="creating" @click="create">新建工作区</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { bookOf, createExtractDraft, listExtracts } from '@/api/novel'
import { errorMessage } from '@/api/request'
import { WS_STATUS, wsSubtitle, wsTitle } from './extractWorkspaces'

const router = useRouter()
const visible = ref(false)
const creating = ref(false)
const fileId = ref(null)
const fileName = ref('')
const rows = ref([])
const book = computed(() => bookOf(fileName.value))

/** 入口：file = {id, fileName}。这本书（同书名）没有工作区就直接新建并打开，有就弹出来选 */
async function open(file) {
  fileId.value = file.id
  fileName.value = file.fileName || ''
  let list = []
  try {
    const res = await listExtracts()
    if (res.code === 0) list = res.data || []
  } catch {
    // 列表取不到：当作没有，直接新建
  }
  rows.value = list
    .filter((t) => bookOf(t.fileName) === book.value)
    .sort((a, b) => String(b.updateTime || '').localeCompare(String(a.updateTime || '')))
  if (!rows.value.length) return create()
  visible.value = true
}

async function create() {
  creating.value = true
  try {
    const res = await createExtractDraft(fileId.value)
    if (res.code !== 0) throw new Error(res.message)
    go(res.data.id)
  } catch (e) {
    ElMessage.error(errorMessage(e, '新建提取工作区失败'))
  } finally {
    creating.value = false
  }
}

function go(id) {
  visible.value = false
  router.push(`/novel/extract/${id}`)
}

defineExpose({ open })
</script>

<style scoped>
.list {
  max-height: 360px;
  overflow: auto;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
}
.row:hover {
  border-color: var(--el-color-primary);
}
.main {
  flex: 1;
  min-width: 0;
}
.title {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.sub,
.time,
.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.sub {
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hint {
  float: left;
  line-height: 32px;
}
</style>
