<template>
  <!-- 卡片整理工作区：把提取结果总结成这个工作区的卡片（不是素材；在「素材选择」里挑过才进素材库） -->
  <div class="cw">
    <el-empty v-if="!entities.length" :description="emptyText">
      <template v-if="extracting && status === 'INTERRUPTED'">
        <p v-if="message" class="muted empty-msg">{{ message }}</p>
        <el-button type="primary" @click="emit('go-extract')">回提取工作区继续提取</el-button>
      </template>
      <el-button v-else-if="['QUEUED', 'RUNNING'].includes(status)" @click="emit('go-extract')">去提取工作区暂停</el-button>
    </el-empty>
    <template v-else>
      <el-alert v-if="partial" type="info" :closable="false" show-icon class="cw-alert">
        提取还没读完（已读 {{ readChapters }} / {{ totalChapters }} 章），现在整理用的是已读部分的 {{ entities.length }} 个实体。
        之后继续提取、再整理一次，同一实体的卡会更新（手改过的保留，新内容放进历史），新出现的实体会新建卡片。
      </el-alert>
      <!-- 顶栏：发起整理 / 当前整理进度 / 整理记录 / 实体档案 -->
      <div class="cw-bar">
        <el-button type="primary" size="small" :disabled="!!running" @click="openCompile([])">整理实体卡…</el-button>
        <el-button size="small" :disabled="!!running" title="从节奏、章末钩子、爽点、伏笔、开篇、主角变化总结写法规律" @click="openCompile([], 'craft')">
          整理写法卡…
        </el-button>
        <el-button size="small" :disabled="!!running" title="把相关的实体（如骑士、骑士侍从、骑士精神）总结成一张世界观卡" @click="worldOpen = true">
          整理世界观卡…
        </el-button>
        <el-button
          size="small"
          :disabled="!!running || resonanceSource.length < 3"
          :title="resonanceSource.length < 3 ? '先整理出至少 3 张世界观 / 体系 / 实体卡' : '把同一主题的卡片关联起来：关系图、联动规则、融入其他世界观的指南'"
          @click="resonanceOpen = true"
        >
          整理共鸣素材…
        </el-button>
        <template v-if="running">
          <el-tag :type="running.status === 'INTERRUPTED' ? 'warning' : 'primary'" size="small">
            {{ running.status === 'INTERRUPTED' ? '整理已暂停' : '整理中' }} {{ running.progress || 0 }}%
          </el-tag>
          <span class="muted ellipsis" :title="running.message">{{ running.message }}</span>
          <template v-if="running.status === 'INTERRUPTED'">
            <el-button link type="primary" size="small" :loading="busy === running.id" @click="act(running, 'resume')">继续</el-button>
            <el-button link type="danger" size="small" :loading="busy === running.id" @click="act(running, 'cancel')">取消</el-button>
          </template>
          <template v-else>
            <el-button link type="primary" size="small" :disabled="stopping(running)" @click="act(running, 'pause')">暂停</el-button>
            <el-button link type="danger" size="small" :disabled="stopping(running)" @click="act(running, 'cancel')">取消</el-button>
          </template>
        </template>
        <span class="spacer" />
        <el-button link size="small" @click="recordsOpen = true">整理记录（{{ compiles.length }}）</el-button>
        <el-button link size="small" @click="archiveOpen = true">实体档案（{{ entities.length }}）</el-button>
      </div>

      <el-empty v-if="!cards.length && !loadingCards" description="还没有卡片：点「整理实体卡…」用实体档案整理出卡片" />
      <div v-else class="cw-body">
        <!-- 左：按类型 / 分类 -->
        <aside class="cw-nav">
          <div v-for="g in groups" :key="g.key" class="nav-item" :class="{ active: g.key === group, off: !g.count }" @click="g.count && (group = g.key)">
            <span>{{ g.label }}</span>
            <span class="muted">{{ g.count || (g.todo ? '未整理' : 0) }}</span>
          </div>
          <div v-if="craftNote" class="muted pad nav-note">{{ craftNote }}</div>
        </aside>
        <!-- 中：列表 -->
        <section class="cw-list">
          <el-input v-model="keyword" size="small" clearable placeholder="搜索名称" class="cw-search" />
          <div
            v-for="c in shown"
            :key="c.id"
            class="card-row"
            :class="{ active: c.id === selectedId }"
            @click="selectedId = c.id"
          >
            <div class="row-title">{{ c.title }}</div>
            <div class="row-meta">
              <span v-if="c.data?.subtype">{{ c.data.subtype }}</span>
              <span v-if="c.data?.facts?.length">{{ c.data.facts.length }} 条事实</span>
              <el-tag v-if="c.edited" size="small" type="warning" effect="plain">手改</el-tag>
              <el-tag v-if="c.status === 'SAVED'" size="small" type="success" effect="plain">已入库</el-tag>
              <el-tag v-else-if="c.status === 'SKIPPED'" size="small" type="info" effect="plain">跳过</el-tag>
            </div>
          </div>
          <div v-if="!shown.length" class="muted pad">没有卡片</div>
        </section>
        <!-- 右：详情 -->
        <section class="cw-detail">
          <CardEditor :card="selected" @saved="onCardSaved" @jump="(n) => emit('jump', n)" @pick-entity="pickEntity" @pick-card="pickCard" />
        </section>
      </div>
    </template>

    <CompileDialog
      v-model="dialogVisible"
      :extract-id="extractId"
      :file-name="fileName"
      :entities="entities"
      :selected-keys="dialogKeys"
      :chapter-count="chapterCount"
      :mode="dialogMode"
      :groups="dialogGroups"
      @started="onStarted"
    />
    <WorldGroupDialog v-model="worldOpen" :extract-id="extractId" :entities="entities" @confirm="(g) => openCompile([], 'world', g)" />
    <ResonanceGroupDialog v-model="resonanceOpen" :extract-id="extractId" :cards="resonanceSource" @confirm="(g) => openCompile([], 'resonance', g)" />

    <el-drawer v-model="recordsOpen" title="整理记录" size="50%" append-to-body>
      <el-table :data="compiles" size="small" empty-text="还没有整理过">
        <el-table-column prop="createTime" label="时间" width="160" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="STATUS[row.status]?.type" size="small">{{ STATUS[row.status]?.label || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模型 / 范围" min-width="200">
          <template #default="{ row }">{{ compileScope(row) }}</template>
        </el-table-column>
        <el-table-column prop="message" label="结果" min-width="240" show-overflow-tooltip />
      </el-table>
    </el-drawer>

    <el-drawer v-model="archiveOpen" title="实体档案（整理卡片的输入）" size="60%" append-to-body>
      <p class="muted">删掉认错的实体、勾选只整理哪些；合并同一个东西（如「骑士」和「骑士侍从」）请在提取工作区的「全书实体」里做。</p>
      <p v-if="partial" class="muted">提取还没读完：这里是已读部分的实体，只能勾选来整理；删改实体请等提取完成后再做（写回只对完成的结果有效）。</p>
      <EntityArchive :entities="entities" :saving="saving" :extract-id="extractId" @save="(l) => (partial ? ElMessage.warning('提取完成后才能保存实体档案') : saveEntities(l))" @compile="(k) => ((archiveOpen = false), openCompile(k))" />
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cancelCompile, listCards, listCompiles, pauseCompile, resumeCompile, updateExtractResult } from '@/api/novel'
import { MATERIAL_CATEGORIES, categoryOf } from '@/api/material'
import { errorMessage } from '@/api/request'
import CardEditor from './CardEditor.vue'
import CompileDialog from './CompileDialog.vue'
import EntityArchive from './EntityArchive.vue'
import WorldGroupDialog from './WorldGroupDialog.vue'
import ResonanceGroupDialog from './ResonanceGroupDialog.vue'

const props = defineProps({
  extractId: { type: Number, required: true },
  fileName: { type: String, default: '' },
  chapterCount: { type: Number, default: 0 },
  result: { type: Object, default: null }, // 已解析的提取结果
  extracting: { type: Boolean, default: false }, // 提取还没完成
  status: { type: String, default: '' }, // 提取任务状态
  message: { type: String, default: '' },
  liveEntities: { type: Array, default: () => [] }, // 提取暂停时：断点里已读部分的实体档案
  readChapters: { type: Number, default: 0 },
  totalChapters: { type: Number, default: 0 }
})
const emit = defineEmits(['saved', 'changed', 'go-extract', 'jump'])

const STATUS = {
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '整理中', type: 'warning' },
  INTERRUPTED: { label: '已暂停', type: 'warning' },
  SUCCEEDED: { label: '已完成', type: 'success' },
  FAILED: { label: '已取消', type: 'danger' }
}
const POLL_MS = 3000

// 提取完成用结果里的实体档案；暂停时用已读部分（断点）的实体，整理的也是这些（后端同口径）
const partial = computed(() => props.status === 'INTERRUPTED' && !props.result?.entities?.length && props.liveEntities.length > 0)
const entities = computed(() => (partial.value ? props.liveEntities : props.result?.entities || []))
const emptyText = computed(() =>
  props.extracting
    ? props.status === 'INTERRUPTED'
      ? '提取已暂停，已读的部分里还没有实体（或 AI 服务没连上）'
      : props.status === 'FAILED'
        ? '这次提取已取消，没有实体档案可以整理'
        : ['QUEUED', 'RUNNING'].includes(props.status)
          ? '提取进行中：暂停后可以先用已读的部分整理卡片，也可以等提取完成'
          : '提取完成后，这里用实体档案整理卡片'
    : props.result
      ? '这次提取没有记录设定实体（只做了章节分析），没有可整理的卡片'
      : '还没有提取结果'
)

/* ---------- 卡片 ---------- */
// 浅层响应式：卡片多（几百张、每张带事实和历史版本）时深层代理会拖慢切换；改卡片时整体替换数组
const cards = shallowRef([])
const loadingCards = ref(false)
const group = ref('')
const keyword = ref('')
const selectedId = ref(null)
async function loadCards() {
  loadingCards.value = true
  try {
    const res = await listCards(props.extractId)
    if (res.code !== 0) throw new Error(res.message)
    cards.value = res.data || []
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取卡片失败'))
  } finally {
    loadingCards.value = false
  }
}
/* 左栏：写法卡 / 世界观卡、体系卡、实体卡按分类、剧情段 */
const groups = computed(() => {
  const count = (fn) => cards.value.filter(fn).length
  const out = [
    { key: 'resonance', label: '共鸣素材', count: count((c) => c.kind === 'resonance') },
    { key: 'craft', label: '写法卡', count: count((c) => c.kind === 'craft') },
    { key: 'world', label: '世界观卡', count: count((c) => c.kind === 'world') },
    { key: 'system', label: '体系卡', count: count((c) => c.kind === 'system') }
  ]
  MATERIAL_CATEGORIES.filter((c) => !['plot', 'craft', 'resonance'].includes(c.code)).forEach((c) =>
    out.push({ key: `entity:${c.code}`, label: `实体 · ${c.label}`, count: count((x) => x.kind === 'entity' && x.category === c.code) })
  )
  out.push({ key: 'arc', label: '剧情段', count: count((c) => c.kind === 'arc') })
  return out
})
const inGroup = (c, g) => (g.startsWith('entity:') ? c.kind === 'entity' && c.category === g.slice(7) : c.kind === g)
const shown = computed(() => {
  const kw = keyword.value.trim()
  return cards.value.filter((c) => inGroup(c, group.value) && (!kw || c.title.includes(kw)))
})
const selected = computed(() => cards.value.find((c) => c.id === selectedId.value) || null)
// 最近一次写法卡整理里「缺少依据没整理」的说明
const craftNote = computed(() => {
  const c = compiles.value.find((x) => x.status === 'SUCCEEDED' && (x.message || '').includes('写法卡'))
  const m = (c?.message || '').split('缺少依据没整理：')[1]
  return m ? `缺少依据没整理：${m}` : ''
})
watch(groups, (gs) => {
  if (!gs.find((g) => g.key === group.value)?.count) group.value = gs.find((g) => g.count)?.key || ''
})
watch(shown, (list) => {
  if (!list.some((c) => c.id === selectedId.value)) selectedId.value = list[0]?.id ?? null
})
/** 共鸣素材的节点 → 打开对应的卡片 */
function pickCard(id) {
  const c = cards.value.find((x) => x.id === id)
  if (!c) {
    ElMessage.info('这张卡已经不在了（被删除或重新整理过）')
    return
  }
  group.value = c.kind === 'entity' ? `entity:${c.category}` : c.kind
  keyword.value = ''
  selectedId.value = c.id
}
/** 世界观卡的成员 → 对应的实体卡（没整理过实体卡的提示一下） */
function pickEntity(key) {
  const c = cards.value.find((x) => x.kind === 'entity' && x.data?.entityKey === key)
  if (!c) {
    ElMessage.info('这个成员还没有实体卡（可以用「整理实体卡」整理它）')
    return
  }
  group.value = `entity:${c.category}`
  keyword.value = ''
  selectedId.value = c.id
}
function onCardSaved(card) {
  const i = cards.value.findIndex((c) => c.id === card.id)
  if (i >= 0) cards.value = cards.value.map((c, k) => (k === i ? { ...card, match: c.match } : c))
}

/* ---------- 整理任务 ---------- */
const compiles = ref([])
const recordsOpen = ref(false)
const archiveOpen = ref(false)
const running = computed(() => compiles.value.find((c) => ['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(c.status)))
let timer = null
async function loadCompiles() {
  clearTimeout(timer)
  timer = null
  try {
    const res = await listCompiles(props.extractId)
    const before = compiles.value.filter((c) => ['QUEUED', 'RUNNING'].includes(c.status)).length
    compiles.value = res.code === 0 ? res.data || [] : []
    const now = compiles.value.filter((c) => ['QUEUED', 'RUNNING'].includes(c.status)).length
    if (before && !now) {
      loadCards() // 整理结束：卡片变了
      emit('changed')
    }
  } catch {
    compiles.value = []
  }
  if (compiles.value.some((c) => ['QUEUED', 'RUNNING'].includes(c.status))) timer = setTimeout(loadCompiles, POLL_MS)
}
watch(
  () => props.extractId,
  (id) => {
    if (!id) return
    loadCompiles()
    loadCards()
  },
  { immediate: true }
)
onBeforeUnmount(() => clearTimeout(timer))

const stopping = (row) => ['正在取消…', '正在暂停…'].includes(row?.message)
const busy = ref(null)
async function act(row, kind) {
  if (kind === 'cancel') {
    try {
      await ElMessageBox.confirm('取消这次整理？已整理的部分不会写成卡片，可以重新发起整理。', '取消整理', {
        type: 'warning',
        confirmButtonText: '取消整理',
        cancelButtonText: '再想想'
      })
    } catch {
      return
    }
  }
  const fn = { pause: pauseCompile, resume: resumeCompile, cancel: cancelCompile }[kind]
  const ok = { pause: '已请求暂停，当前这张卡整理完后停下', resume: '已重新排队，从断点接着整理', cancel: '已取消' }[kind]
  busy.value = row.id
  try {
    const res = await fn(row.id)
    if (res.code !== 0) throw new Error(res.message || '操作失败')
    ElMessage.success(ok)
    await loadCompiles()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    busy.value = null
  }
}

function compileScope(row) {
  let o = {}
  try {
    o = JSON.parse(row.options || '{}') || {}
  } catch {
    // 参数读不出来：只显示实体数
  }
  const m = o.model
  const parts = [!m || m.source === 'api' ? '大模型' : m.source === 'gguf' ? 'GGUF' : `本地模型 ${m.baseId || ''}`]
  if (o.entityKeys) parts.push(`勾选的 ${o.entityKeys.length} 个`)
  else if (o.topN) parts.push(`事实最多的前 ${o.topN} 个`)
  if (o.categories) parts.push(o.categories.map((c) => categoryOf(c)?.label || c).join('、'))
  parts.push(`${row.entityCount ?? '?'} 个实体`)
  if (o.plot) parts.push('含剧情段')
  if (o.partial) parts.push(`用已读的 ${o.partial.readChapters}/${o.partial.totalChapters} 章`)
  return parts.join(' · ')
}

const dialogVisible = ref(false)
const dialogKeys = ref([])
const dialogMode = ref('entity')
const dialogGroups = ref([])
const worldOpen = ref(false)
const resonanceOpen = ref(false)
// 共鸣素材能关联的卡：世界观卡 / 体系卡 / 实体卡
const resonanceSource = computed(() => cards.value.filter((c) => ['world', 'system', 'entity'].includes(c.kind)))
function openCompile(keys, mode = 'entity', groups = []) {
  if (running.value) {
    ElMessage.warning('上一次整理还没结束（可以先暂停 / 取消）')
    return
  }
  dialogKeys.value = keys || []
  dialogMode.value = mode
  dialogGroups.value = groups
  dialogVisible.value = true
}
async function onStarted() {
  await loadCompiles()
  emit('changed')
}

const saving = ref(false)
async function saveEntities(list) {
  saving.value = true
  try {
    const res = await updateExtractResult(props.extractId, { ...props.result, entities: list })
    if (res.code !== 0) throw new Error(res.message || '保存失败')
    ElMessage.success(`实体档案已保存（${list.length} 个实体）`)
    emit('saved', res.data)
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存实体档案失败'))
  } finally {
    saving.value = false
  }
}

defineExpose({ reload: loadCards })
</script>

<style scoped>
.cw {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.cw-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--ws-card, var(--el-bg-color));
}
.spacer {
  flex: 1;
}
.ellipsis {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.pad {
  padding: 12px;
}
.cw-alert {
  margin: 8px 16px 0;
  width: auto;
}
.empty-msg {
  max-width: 640px;
  margin: 0 auto 12px;
  word-break: break-all;
}
.cw-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 170px 300px minmax(0, 1fr);
}
.cw-nav,
.cw-list,
.cw-detail {
  overflow: auto;
  min-height: 0;
}
.cw-nav {
  padding: 8px 0;
  border-right: 1px solid var(--el-border-color-lighter);
}
.nav-item {
  display: flex;
  justify-content: space-between;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
}
.nav-item:hover,
.nav-item.active {
  background: var(--el-fill-color-light);
}
.nav-item.active {
  color: var(--el-color-primary);
  font-weight: 600;
}
.nav-note {
  line-height: 1.5;
}
.nav-item.off {
  cursor: default;
  color: var(--el-text-color-placeholder);
}
.cw-list {
  padding: 8px;
  border-right: 1px solid var(--el-border-color-lighter);
}
.cw-search {
  margin-bottom: 8px;
}
.card-row {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
}
.card-row:hover {
  background: var(--el-fill-color-light);
}
.card-row.active {
  background: var(--el-color-primary-light-9);
}
.row-title {
  font-size: 14px;
  color: var(--el-text-color-primary);
}
.row-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.cw-detail {
  padding: 14px 18px;
}
</style>
