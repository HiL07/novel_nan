<template>
  <!-- 素材选择：从这个工作区的卡片里挑出要进素材库的；库里已有这本书的同名素材时逐条选「更新已有 / 作为可选版本 / 跳过」 -->
  <div class="ms">
    <div class="ms-bar">
      <el-radio-group v-model="statusFilter" size="small">
        <el-radio-button value="todo">待选择（{{ counts.todo }}）</el-radio-button>
        <el-radio-button value="resync">卡片改过（{{ counts.resync }}）</el-radio-button>
        <el-radio-button value="saved">已入库（{{ counts.saved }}）</el-radio-button>
        <el-radio-button value="skipped">已跳过（{{ counts.skipped }}）</el-radio-button>
      </el-radio-group>
      <el-select v-model="kindFilter" size="small" clearable placeholder="类型 / 分类" style="width: 150px">
        <el-option v-for="o in KIND_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-select v-model="tierFilter" size="small" clearable placeholder="量级" style="width: 130px">
        <el-option v-for="t in TIERS" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
      <el-input v-model="keyword" size="small" clearable placeholder="搜索名称" style="width: 160px" />
      <span class="spacer" />
      <template v-if="statusFilter !== 'saved'">
        <el-button size="small" :disabled="!checked.length" :loading="busy === 'skip'" @click="skipChecked">
          {{ statusFilter === 'skipped' ? '恢复选中' : '跳过选中' }}
        </el-button>
        <el-button v-if="statusFilter !== 'skipped'" size="small" type="primary" :disabled="!checked.length" :loading="busy === 'save'" @click="saveChecked">
          存入素材库（{{ checked.length }}）
        </el-button>
      </template>
    </div>

    <el-empty v-if="!cards.length && !loading" description="还没有卡片：先在「卡片整理」里整理出卡片" />
    <el-table
      v-else
      ref="tableRef"
      v-loading="loading"
      :data="rows"
      size="small"
      height="100%"
      class="ms-table"
      row-key="id"
      empty-text="没有符合条件的卡片"
      @selection-change="(r) => (checked = r)"
    >
      <el-table-column v-if="statusFilter !== 'saved'" type="selection" width="40" reserve-selection />
      <el-table-column label="名称" min-width="200">
        <template #default="{ row }">
          <el-button link type="primary" @click="preview = row">{{ row.title }}</el-button>
          <el-tag v-for="w in worldOf[row.data?.entityKey] || []" :key="w" size="small" type="info" effect="plain" class="belong">属于：{{ w }}</el-tag>
          <div class="muted ellipsis">{{ row.data?.summary }}</div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">{{ kindText(row) }}</template>
      </el-table-column>
      <el-table-column label="量级" width="80">
        <template #default="{ row }">{{ TIERS.find((t) => t.value === row.data?.tier)?.short || '-' }}</template>
      </el-table-column>
      <el-table-column label="素材库里" min-width="300">
        <template #default="{ row }">
          <template v-if="row.status === 'SAVED' && !needsResync(row)">
            <el-tag size="small" type="success">已入库</el-tag>
            <span class="muted"> 素材 #{{ row.materialId }}</span>
          </template>
          <template v-else-if="row.match || needsResync(row)">
            <el-tag size="small" type="warning">{{ needsResync(row) ? '卡片入库后又改过' : `已有同名：${row.match.title}` }}</el-tag>
            <el-select v-model="actions[row.id]" size="small" style="width: 140px; margin-left: 6px">
              <el-option label="更新已有" value="update" />
              <el-option label="作为可选版本" value="version" />
              <el-option label="仍存为新的" value="new" />
            </el-select>
          </template>
          <el-tag v-else size="small" effect="plain">新的</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.edited" size="small" type="warning" effect="plain">手改</el-tag>
          <el-tag v-if="row.status === 'SKIPPED'" size="small" type="info" effect="plain">跳过</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="previewOpen" :title="preview?.title" size="45%" append-to-body>
      <CardEditor :card="preview" @saved="onCardSaved" />
    </el-drawer>

    <!-- 旧版本留下的待确认候选（整理卡片以前直接生成候选） -->
    <el-collapse v-if="hasOldCandidates" class="ms-old">
      <el-collapse-item title="旧版待确认候选（改版前整理出的，确认后同样进素材库）">
        <CandidateReview :extract-id="extractId" @changed="checkOld" />
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listCards, saveCards } from '@/api/novel'
import { MATERIAL_CATEGORIES, TIERS, categoryOf, listCandidates } from '@/api/material'
import { errorMessage } from '@/api/request'
import CandidateReview from './CandidateReview.vue'
import CardEditor from './CardEditor.vue'

const props = defineProps({
  extractId: { type: Number, required: true }
})
const emit = defineEmits(['changed'])

const KIND_LABEL = { craft: '写法卡', world: '世界观卡', system: '体系卡', arc: '剧情段', resonance: '共鸣素材' }
const KIND_OPTIONS = [
  { value: 'kind:resonance', label: '共鸣素材' },
  { value: 'kind:craft', label: '写法卡' },
  { value: 'kind:world', label: '世界观卡' },
  { value: 'kind:system', label: '体系卡' },
  ...MATERIAL_CATEGORIES.filter((c) => !['plot', 'craft', 'resonance'].includes(c.code)).map((c) => ({ value: `cat:${c.code}`, label: `实体 · ${c.label}` })),
  { value: 'kind:arc', label: '剧情段' }
]
const kindText = (c) => KIND_LABEL[c.kind] || `实体 · ${categoryOf(c.category)?.label || c.category}`

const cards = ref([])
const loading = ref(false)
const statusFilter = ref('todo')
const kindFilter = ref('')
const tierFilter = ref(null)
const keyword = ref('')
const checked = ref([])
const tableRef = ref(null)
const actions = reactive({}) // cardId → update | version | new（库里有同名 / 入库后又改过的）
const busy = ref('')

/* 被世界观卡收进去的实体卡：实体键 → [世界观卡名] */
const worldOf = computed(() => {
  const out = {}
  cards.value.filter((c) => c.kind === 'world').forEach((w) => (w.data?.members || []).forEach((k) => (out[k] = [...(out[k] || []), w.title])))
  return out
})
const needsResync = (c) => c.status === 'SAVED' && c.materialId && c.savedVersion != null && c.version > c.savedVersion
const stateOf = (c) => (needsResync(c) ? 'resync' : c.status === 'SAVED' ? 'saved' : c.status === 'SKIPPED' ? 'skipped' : 'todo')
const counts = computed(() => {
  const o = { todo: 0, resync: 0, saved: 0, skipped: 0 }
  cards.value.forEach((c) => o[stateOf(c)]++)
  return o
})
const rows = computed(() => {
  const kw = keyword.value.trim()
  const k = kindFilter.value
  return cards.value.filter(
    (c) =>
      stateOf(c) === statusFilter.value &&
      (!k || (k.startsWith('kind:') ? c.kind === k.slice(5) : c.kind === 'entity' && c.category === k.slice(4))) &&
      (tierFilter.value == null || c.data?.tier === tierFilter.value) &&
      (!kw || c.title.includes(kw))
  )
})
watch(statusFilter, () => tableRef.value?.clearSelection())

async function load() {
  loading.value = true
  try {
    const res = await listCards(props.extractId)
    if (res.code !== 0) throw new Error(res.message)
    cards.value = res.data || []
    cards.value.forEach((c) => {
      // 库里已有同名：默认「更新已有」；卡片入库后又改过：默认更新到它存进去的那条
      if (actions[c.id] == null && (c.match || needsResync(c))) actions[c.id] = 'update'
    })
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取卡片失败'))
  } finally {
    loading.value = false
  }
}

function itemOf(c) {
  const target = needsResync(c) ? c.materialId : c.match?.id
  const action = c.match || needsResync(c) ? actions[c.id] || 'update' : 'new'
  return { cardId: c.id, action, targetId: action === 'new' ? undefined : target }
}

async function saveChecked() {
  busy.value = 'save'
  try {
    const res = await saveCards(props.extractId, checked.value.map(itemOf))
    if (res.code !== 0) throw new Error(res.message)
    const r = res.data
    const parts = []
    if (r.saved) parts.push(`新存 ${r.saved} 条`)
    if (r.updated) parts.push(`更新 ${r.updated} 条`)
    if (r.versions) parts.push(`挂为可选版本 ${r.versions} 条`)
    ElMessage.success(`已存入素材库：${parts.join('，') || '0 条'}`)
    if (r.errors?.length) ElMessage.warning(r.errors.slice(0, 3).join('；'))
    tableRef.value?.clearSelection()
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '存入素材库失败'))
  } finally {
    busy.value = ''
  }
}

async function skipChecked() {
  busy.value = 'skip'
  const action = statusFilter.value === 'skipped' ? 'reset' : 'skip'
  try {
    const res = await saveCards(props.extractId, checked.value.map((c) => ({ cardId: c.id, action })))
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(action === 'skip' ? `已跳过 ${checked.value.length} 张` : `已恢复 ${checked.value.length} 张`)
    tableRef.value?.clearSelection()
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    busy.value = ''
  }
}

const preview = ref(null)
const previewOpen = computed({ get: () => !!preview.value, set: (v) => !v && (preview.value = null) })
function onCardSaved(card) {
  const i = cards.value.findIndex((c) => c.id === card.id)
  if (i >= 0) cards.value[i] = { ...card, match: cards.value[i].match }
  preview.value = cards.value[i] || card
}

/* 旧版候选：有待确认的才显示 */
const hasOldCandidates = ref(false)
async function checkOld() {
  try {
    const res = await listCandidates({ status: 'PENDING', extractId: props.extractId })
    hasOldCandidates.value = res.code === 0 && (res.data || []).length > 0
  } catch {
    hasOldCandidates.value = false
  }
}

watch(
  () => props.extractId,
  (id) => {
    if (!id) return
    load()
    checkOld()
  },
  { immediate: true }
)
</script>

<style scoped>
.ms {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.ms-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--ws-card, var(--el-bg-color));
}
.spacer {
  flex: 1;
}
.ms-table {
  flex: 1;
  min-height: 0;
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
.belong {
  margin-left: 6px;
}
.ms-old {
  max-height: 45%;
  overflow: auto;
  padding: 0 16px;
}
</style>
