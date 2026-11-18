<template>
  <div class="pw-page">
    <el-card class="box-card" shadow="never">
      <!-- 顶栏：名称 / 示例世界 / 模型 / 状态 / 进度 / 正在加工 -->
      <template #header>
        <div class="pw-head">
          <el-button text :icon="ArrowLeft" @click="router.push('/material/portable')">架空工作区</el-button>
          <span class="pw-title">{{ ws?.title }}</span>
          <el-tag v-if="ws" size="small" :type="WS_STATE[ws.status]?.type">{{ WS_STATE[ws.status]?.label }}</el-tag>
          <span class="spacer" />
          <template v-if="ws">
            <el-button v-if="ws.status === 'RUNNING'" :disabled="(ws.message || '').startsWith('正在暂停')" @click="pause">暂停</el-button>
            <el-button v-else type="primary" :disabled="!ws.counts?.QUEUED" :loading="busy === 'start'" @click="start">
              {{ ws.status === 'PAUSED' ? '继续' : '开始' }}（待加工 {{ ws.counts?.QUEUED || 0 }}）
            </el-button>
            <el-dropdown trigger="click" @command="onCommand">
              <el-button :icon="MoreFilled" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">改名</el-dropdown-item>
                  <el-dropdown-item command="world">改示例世界 / 模型</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </div>
      </template>

      <template v-if="ws">
        <div class="pw-info">
          <span>示例世界：<b>{{ ws.targetWorld || 'AI 自选（和原作类型差别大的世界）' }}</b></span>
          <span>模型：{{ ws.model?.source === 'gguf' ? 'GGUF' : '大模型（启用中的配置）' }}</span>
          <span>筛选标准：{{ filterText(ws.filter) }}</span>
        </div>
        <div class="pw-progress">
          <el-progress :percentage="wsPercent(ws)" :stroke-width="8" class="pw-bar" />
          <span class="muted">
            已加工 {{ ws.counts?.DONE || 0 }} · 待加工 {{ ws.counts?.QUEUED || 0 }} · 加工中 {{ ws.counts?.RUNNING || 0 }} · 失败 {{ ws.counts?.FAILED || 0 }}
          </span>
        </div>
        <div v-if="ws.current?.length" class="pw-current">
          <el-icon class="is-loading"><Loading /></el-icon> 正在加工：{{ ws.current.join('、') }}
        </div>
        <div v-else-if="ws.message" class="muted pw-msg">{{ ws.message }}</div>

        <!-- 筛选：全库原素材 -->
        <div class="pw-filter">
          <el-select v-model="filter.category" size="small" clearable placeholder="分类" style="width: 120px" @change="reload">
            <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
          </el-select>
          <el-select v-model="filter.sourceBook" size="small" clearable filterable placeholder="来源书" style="width: 220px" @change="reload">
            <el-option v-for="s in sources" :key="s.book || MANUAL_BOOK" :label="s.book ? `《${s.book.replace(/^《|》$/g, '')}》（${s.count}）` : `手动添加（${s.count}）`" :value="s.book || MANUAL_BOOK" />
          </el-select>
          <el-select v-model="filter.tags" size="small" multiple filterable collapse-tags clearable placeholder="标签" style="width: 180px" @change="reload">
            <el-option v-for="t in tagCloud" :key="t.tag" :label="`${t.tag}（${t.count}）`" :value="t.tag" />
          </el-select>
          <el-input v-model="filter.keyword" size="small" clearable placeholder="名称 / 概括关键词" style="width: 180px" @keyup.enter="reload" @clear="reload" />
          <el-button size="small" :icon="Search" @click="reload">筛选</el-button>
        </div>
        <div class="pw-bar-row">
          <el-radio-group v-model="state" size="small" @change="reload">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="none">未加入</el-radio-button>
            <el-radio-button value="QUEUED">待加工（{{ ws.counts?.QUEUED || 0 }}）</el-radio-button>
            <el-radio-button value="RUNNING">加工中（{{ ws.counts?.RUNNING || 0 }}）</el-radio-button>
            <el-radio-button value="DONE">已加工（{{ ws.counts?.DONE || 0 }}）</el-radio-button>
            <el-radio-button value="FAILED">失败（{{ ws.counts?.FAILED || 0 }}）</el-radio-button>
          </el-radio-group>
          <span class="spacer" />
          <el-button size="small" type="primary" :disabled="!checked.length" @click="enqueue(checked.map((r) => r.id))">加入选中（{{ checked.length }}）</el-button>
          <el-button size="small" :disabled="!total" @click="enqueueAll">加入当前筛选全部（{{ total }}）</el-button>
          <el-button size="small" :disabled="!checked.some((r) => r.state === 'DONE')" @click="enqueue(checked.filter((r) => r.state === 'DONE').map((r) => r.id), true)">重做选中</el-button>
          <el-button size="small" :disabled="!checked.some((r) => ['QUEUED', 'FAILED'].includes(r.state))" @click="dequeue(checked.map((r) => r.id))">移出选中</el-button>
        </div>

        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          size="small"
          row-key="id"
          class="pw-table"
          empty-text="没有符合条件的原素材"
          @selection-change="(r) => (checked = r)"
        >
          <el-table-column type="selection" width="40" reserve-selection />
          <el-table-column label="原素材" min-width="220">
            <template #default="{ row }">
              <el-button link type="primary" @click="openMaterial(row.id)">{{ row.title }}</el-button>
              <el-tag v-if="row.otherPortables" size="small" effect="plain" class="ml" title="在别的架空工作区里也加工过">别处已架空 {{ row.otherPortables }}</el-tag>
              <div class="muted ellipsis">{{ row.summary }}</div>
            </template>
          </el-table-column>
          <el-table-column label="分类" width="90">
            <template #default="{ row }">{{ categoryOf(row.category)?.label || row.category }}</template>
          </el-table-column>
          <el-table-column label="来源书" min-width="150">
            <template #default="{ row }"><span class="ellipsis-cell">{{ row.sourceBook || '手动添加' }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="ITEM_STATE[row.state]?.type" :effect="row.state === 'none' ? 'plain' : 'light'">
                <el-icon v-if="row.state === 'RUNNING'" class="is-loading"><Loading /></el-icon>
                {{ ITEM_STATE[row.state]?.label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="架空版" min-width="220">
            <template #default="{ row }">
              <template v-if="row.portable">
                <el-button link type="primary" @click="openMaterial(row.portable.id)">{{ row.portable.title }}</el-button>
                <el-tag size="small" effect="plain" :type="row.portable.portability === 'direct' ? 'success' : ''" class="ml">
                  {{ row.portable.portability === 'direct' ? '直接可用' : '需要适配' }}
                </el-tag>
                <el-tag v-if="row.leaks" size="small" type="danger" effect="plain" class="ml" title="示例或通用名里还有原作专名，打开架空版手改">有原作专名 {{ row.leaks }}</el-tag>
              </template>
              <span v-else-if="row.state === 'FAILED'" class="danger ellipsis-cell" :title="row.error">{{ row.error }}</span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button v-if="row.state === 'none' || row.state === 'FAILED'" link type="primary" @click="enqueue([row.id])">{{ row.state === 'FAILED' ? '重试' : '加入' }}</el-button>
              <el-button v-if="row.state === 'DONE'" link type="primary" @click="enqueue([row.id], true)">重做</el-button>
              <el-button v-if="row.state === 'QUEUED' || row.state === 'FAILED'" link @click="dequeue([row.id])">移出</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="total > PAGE"
          v-model:current-page="page"
          class="pw-pager"
          small
          layout="total, prev, pager, next"
          :total="total"
          :page-size="PAGE"
          @current-change="loadRows"
        />
      </template>
    </el-card>

    <MaterialEditor v-model="editor.visible" :material="editor.material" @saved="refresh" @deleted="refresh" @open-material="openMaterial" />
  </div>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Loading, MoreFilled, Search } from '@element-plus/icons-vue'
import {
  MANUAL_BOOK, MATERIAL_CATEGORIES, categoryOf, getMaterial, getMaterialSources, getMaterialTags, getPortableWs, pausePortableWs,
  portableWsDequeue, portableWsEnqueue, portableWsMaterials, startPortableWs, updatePortableWs
} from '@/api/material'
import { errorMessage } from '@/api/request'
import MaterialEditor from '@/components/material/MaterialEditor.vue'
import { ITEM_STATE, WS_STATE, deleteWs, renameWs, wsPercent } from '@/components/material/portableWs'

/** 架空工作区：全库原素材 + 在这个工作区的状态；勾选加入待加工，开始后后台逐条生成架空版。页面被 keep-alive 复用，按路由 id 重新加载 */
const route = useRoute()
const router = useRouter()
const ws = ref(null)
const rows = ref([])
const total = ref(0)
const PAGE = 50
const page = ref(1)
const state = ref('all')
const loading = ref(false)
const busy = ref('')
const checked = ref([])
const tableRef = ref(null)
const filter = reactive({ category: '', sourceBook: '', keyword: '', tags: [] })
const sources = ref([])
const tagCloud = ref([])
let timer = null

const wsId = () => Number(route.params.id)

function filterText(f) {
  const parts = []
  if (f?.category) parts.push(categoryOf(f.category)?.label || f.category)
  if (f?.sourceBook) parts.push(f.sourceBook === MANUAL_BOOK ? '手动添加' : `《${f.sourceBook.replace(/^《|》$/g, '')}》`)
  if (f?.keyword) parts.push(`关键词「${f.keyword}」`)
  if (f?.tags?.length) parts.push(`标签 ${f.tags.join('、')}`)
  return parts.join(' · ') || '全部原素材'
}
const currentFilter = () => ({
  category: filter.category || undefined,
  sourceBook: filter.sourceBook || undefined,
  keyword: filter.keyword.trim() || undefined,
  tags: filter.tags.length ? [...filter.tags] : undefined
})

async function loadWs() {
  try {
    const res = await getPortableWs(wsId())
    if (res.code !== 0) throw new Error(res.message)
    const was = ws.value?.status
    ws.value = res.data
    return was
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取架空工作区失败'))
    return null
  }
}

async function loadRows() {
  loading.value = true
  try {
    const res = await portableWsMaterials(wsId(), { ...currentFilter(), tags: filter.tags, state: state.value, page: page.value, size: PAGE })
    if (res.code !== 0) throw new Error(res.message)
    rows.value = res.data.records || []
    total.value = res.data.total || 0
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取素材失败'))
  } finally {
    loading.value = false
  }
}

/** 筛选变了：回到第 1 页，清掉勾选，并把筛选条件记进工作区（页面上显示「筛选标准」） */
async function reload() {
  page.value = 1
  tableRef.value?.clearSelection()
  await loadRows()
  try {
    const res = await updatePortableWs(wsId(), { filter: currentFilter() })
    if (res.code === 0) ws.value = res.data
  } catch {
    // 记不住筛选不影响使用
  }
}

/** 定时刷新：加工中每 3 秒刷新计数和当前页 */
async function poll() {
  clearTimeout(timer)
  const was = await loadWs()
  if (ws.value?.status === 'RUNNING') {
    loadRows()
    timer = setTimeout(poll, 3000)
  } else if (was === 'RUNNING') {
    loadRows()
    ElMessage.info(ws.value.message || '加工结束')
  }
}

async function refresh() {
  await loadWs()
  await loadRows()
}

async function open() {
  ws.value = null
  rows.value = []
  checked.value = []
  state.value = 'all'
  await loadWs()
  if (!ws.value) return
  Object.assign(filter, { category: '', sourceBook: '', keyword: '', tags: [] }, ws.value.filter || {})
  page.value = 1
  await loadRows()
  if (ws.value.status === 'RUNNING') poll()
  getMaterialSources().then((r) => (sources.value = r.code === 0 ? (r.data || []).filter((s) => s.count) : []))
  getMaterialTags().then((r) => (tagCloud.value = r.code === 0 ? (r.data || []).slice(0, 200) : []))
}

async function enqueue(ids, redo = false) {
  if (!ids.length) return
  try {
    const res = await portableWsEnqueue(wsId(), { ids, redo })
    if (res.code !== 0) throw new Error(res.message)
    afterEnqueue(res.data)
  } catch (e) {
    ElMessage.error(errorMessage(e, '加入失败'))
  }
}
async function enqueueAll() {
  try {
    await ElMessageBox.confirm(
      `把当前筛选（${filterText(currentFilter())}）里的 ${total.value} 条原素材加入待加工？已经加工过的会跳过（要重做请勾选后点「重做选中」）。每条约 1–2 次模型调用。`,
      '加入当前筛选全部',
      { type: 'info', confirmButtonText: '加入' }
    )
  } catch {
    return
  }
  try {
    const res = await portableWsEnqueue(wsId(), { all: true, filter: currentFilter() })
    if (res.code !== 0) throw new Error(res.message)
    afterEnqueue(res.data)
  } catch (e) {
    ElMessage.error(errorMessage(e, '加入失败'))
  }
}
function afterEnqueue(r) {
  const parts = []
  if (r.added) parts.push(`新加入 ${r.added} 条`)
  if (r.requeued) parts.push(`重新排队 ${r.requeued} 条`)
  if (r.skipped) parts.push(`跳过 ${r.skipped} 条（已在队列或已加工）`)
  ElMessage.success(parts.join('，') || '没有变化')
  tableRef.value?.clearSelection()
  refresh()
}
async function dequeue(ids) {
  try {
    const res = await portableWsDequeue(wsId(), ids)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(`已移出 ${res.data.removed} 条（已加工、加工中的不移出）`)
    tableRef.value?.clearSelection()
    refresh()
  } catch (e) {
    ElMessage.error(errorMessage(e, '移出失败'))
  }
}

async function start() {
  busy.value = 'start'
  try {
    const res = await startPortableWs(wsId())
    if (res.code !== 0) throw new Error(res.message)
    ws.value = res.data
    poll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '开始失败'))
  } finally {
    busy.value = ''
  }
}
async function pause() {
  try {
    const res = await pausePortableWs(wsId())
    if (res.code !== 0) throw new Error(res.message)
    ws.value = res.data
  } catch (e) {
    ElMessage.error(errorMessage(e, '暂停失败'))
  }
}

async function onCommand(cmd) {
  if (cmd === 'rename') {
    const w = await renameWs(ws.value)
    if (w) ws.value = w
  } else if (cmd === 'delete') {
    if (await deleteWs(ws.value)) router.push('/material/portable')
  } else if (cmd === 'world') {
    let value
    try {
      ;({ value } = await ElMessageBox.prompt('示例世界（空 = 每条由 AI 选一个和原作类型差别大的世界）。只影响之后加工的条目；已加工的要重做才会换。', '改示例世界', {
        inputValue: ws.value.targetWorld || ''
      }))
    } catch {
      return
    }
    try {
      const res = await updatePortableWs(wsId(), { targetWorld: (value || '').trim() })
      if (res.code !== 0) throw new Error(res.message)
      ws.value = res.data
    } catch (e) {
      ElMessage.error(errorMessage(e, '修改失败'))
    }
  }
}

const editor = reactive({ visible: false, material: null })
async function openMaterial(id) {
  try {
    const res = await getMaterial(id)
    if (res.code !== 0) throw new Error(res.message)
    editor.material = res.data
    editor.visible = true
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取素材失败'))
  }
}

watch(() => route.params.id, (id) => id && route.name === 'portableWorkspace' && open())
onActivated(() => {
  if (!ws.value || ws.value.id !== wsId()) open()
  else poll()
})
onDeactivated(() => clearTimeout(timer))
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(60, 40, 20, 0.06);
}
.pw-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pw-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.spacer {
  flex: 1;
}
.pw-info {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.pw-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.pw-bar {
  width: 320px;
}
.pw-current {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-color-primary);
}
.pw-msg {
  margin-top: 6px;
}
.pw-filter,
.pw-bar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}
.pw-table {
  margin-top: 10px;
}
.pw-pager {
  justify-content: center;
  margin-top: 8px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ellipsis-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.danger {
  color: var(--el-color-danger);
  font-size: 12px;
}
.ml {
  margin-left: 6px;
}
</style>
