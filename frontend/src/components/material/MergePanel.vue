<template>
  <div class="merge-panel">
    <!-- ① 查找：本地向量模型，不花 token -->
    <div class="find-bar">
      <el-select v-model="scope.categories" multiple collapse-tags collapse-tags-tooltip placeholder="分类" size="small" style="width: 200px">
        <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
      </el-select>
      <el-select v-model="scope.books" multiple collapse-tags collapse-tags-tooltip clearable filterable placeholder="全部来源书" size="small" style="width: 220px">
        <el-option v-for="s in sources" :key="s.book ?? '__manual__'" :label="s.book ? `《${s.book}》（${s.count}）` : `手动添加（${s.count}）`" :value="s.book ?? '__manual__'" />
      </el-select>
      <span class="label" title="余弦相似度门槛：越高找到的越像、组越少；越低找得越多，误报也多">相似度 ≥</span>
      <el-slider v-model="scope.threshold" :min="0.75" :max="0.95" :step="0.01" :format-tooltip="(v) => v.toFixed(2)" style="width: 140px" />
      <span class="num">{{ scope.threshold.toFixed(2) }}</span>
      <span class="label">每组最多</span>
      <el-input-number v-model="scope.maxGroup" :min="2" :max="12" size="small" style="width: 90px" />
      <el-checkbox v-model="scope.crossBookOnly">只找跨书的</el-checkbox>
      <el-button type="primary" size="small" :icon="Search" :loading="finding" @click="doFind">查找相似素材</el-button>
    </div>
    <p class="tip">
      用本地向量模型（不花 token）找出同一分类里互相很像的素材：不同小说里的同一种东西（比如几本书的「狼人」），或同一本书里几乎重复的条目。
      找到的只是建议：可以让 AI 写合并稿（主条目只写共性 + 每本书的写法），也可以自己写；确认「合并」后成员收进主条目，随时可以拆分还原。
      <template v-if="findInfo">{{ findInfo }}</template>
    </p>

    <!-- 列表 -->
    <div class="list-bar">
      <el-radio-group v-model="status" size="small">
        <el-radio-button value="open">待处理（{{ counts.open || 0 }}）</el-radio-button>
        <el-radio-button value="APPLIED">已合并（{{ counts.APPLIED || 0 }}）</el-radio-button>
        <el-radio-button value="IGNORED">已忽略（{{ counts.IGNORED || 0 }}）</el-radio-button>
      </el-radio-group>
      <el-select v-model="filter.category" clearable placeholder="全部分类" size="small" style="width: 120px">
        <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
      </el-select>
      <el-select v-model="filter.cross" size="small" style="width: 110px">
        <el-option label="跨书和同书" value="" />
        <el-option label="只看跨书" value="true" />
        <el-option label="只看同书" value="false" />
      </el-select>
      <template v-if="status === 'open'">
        <el-checkbox :model-value="allChecked" :indeterminate="someChecked && !allChecked" :disabled="!rows.length" @change="toggleAll">本页全选</el-checkbox>
        <el-select v-model="draftModel" size="small" style="width: 190px" placeholder="写合并稿的模型">
          <el-option v-for="c in configs" :key="c.id" :label="`大模型 · ${c.name}`" :value="`api:${c.id}`" />
          <el-option :label="llama ? `GGUF · ${llama.name}` : 'GGUF（llama.cpp 未运行）'" value="gguf" :disabled="!llama" />
        </el-select>
        <el-button size="small" type="primary" plain :icon="MagicStick" :disabled="!checkedIds.length || drafting.running" @click="doDraft(checkedIds)">
          AI 写合并稿（{{ checkedIds.length }} 组）
        </el-button>
        <el-button size="small" :icon="Close" :disabled="!checkedIds.length" @click="doIgnore(checkedIds)">忽略选中</el-button>
      </template>
    </div>
    <el-alert v-if="drafting.running || drafting.lastError" :type="drafting.running ? 'info' : 'warning'" :closable="false" show-icon class="draft-alert">
      <template #title>
        <template v-if="drafting.running">
          正在写合并稿 {{ drafting.done + drafting.failed }}/{{ drafting.total }}（失败 {{ drafting.failed }}）
          <el-button link type="primary" size="small" @click="doStop">暂停</el-button>
        </template>
        <template v-else>上一批合并稿：{{ drafting.lastError }}</template>
      </template>
    </el-alert>

    <div v-loading="loading">
      <el-empty v-if="!rows.length" :description="emptyText" :image-size="70" />
      <div v-for="g in rows" :key="g.id" class="group" :class="{ checked: checked[g.id] }">
        <div class="group-head">
          <el-checkbox v-if="status === 'open'" v-model="checked[g.id]" />
          <el-tag size="small" effect="plain">{{ categoryOf(g.category)?.label || g.category }}</el-tag>
          <el-tag size="small" :type="g.crossBook ? 'success' : 'info'">{{ g.crossBook ? '跨书' : '同一本书' }}</el-tag>
          <span class="muted">相似度 {{ Math.round((g.score || 0) * 100) }}%</span>
          <el-tag v-if="g.status === 'DRAFTING'" size="small" type="warning">写合并稿中…</el-tag>
          <el-tag v-else-if="g.status === 'DRAFTED'" size="small" type="primary">AI 合并稿已写好</el-tag>
          <span v-if="g.message" class="warn">{{ g.message }}</span>
          <span class="spacer" />
          <template v-if="status === 'open'">
            <el-button v-if="g.status !== 'DRAFTING'" link type="primary" size="small" :disabled="drafting.running" @click="doDraft([g.id])">
              {{ g.draft ? '重写合并稿' : 'AI 写合并稿' }}
            </el-button>
            <el-button link size="small" @click="doIgnore([g.id])">忽略</el-button>
          </template>
          <el-button v-else-if="status === 'APPLIED'" link type="primary" size="small" @click="emit('open-material', g.materialId)">查看主条目</el-button>
          <el-button v-else link type="primary" size="small" @click="doRestore(g.id)">恢复</el-button>
        </div>

        <!-- 成员 -->
        <div class="members">
          <div v-for="m in g.members" :key="m.id" class="member" :class="{ off: status === 'open' && !edit(g).memberIds.includes(m.id) }">
            <div class="member-head">
              <el-checkbox
                v-if="status === 'open'"
                :model-value="edit(g).memberIds.includes(m.id)"
                title="去掉勾选 = 不合并这一条"
                @change="(v) => toggleMember(g, m.id, v)"
              />
              <span class="book">{{ m.sourceBook ? `《${m.sourceBook}》` : '手动' }}</span>
              <b>{{ m.title }}</b>
              <span v-if="m.subtype" class="muted">{{ m.subtype }}</span>
            </div>
            <div class="member-summary">{{ m.summary || '（无概括）' }}</div>
            <div class="member-attrs">
              <span v-for="(v, k) in firstAttrs(m.attributes)" :key="k"><b>{{ k }}</b>：{{ Array.isArray(v) ? v.join('、') : v }}</span>
            </div>
            <div v-if="status === 'open' && edit(g).memberIds.includes(m.id)" class="variant">
              <el-input v-model="edit(g).variants[m.id].label" size="small" maxlength="20" placeholder="版本名，如：宗教圣物" class="variant-label">
                <template #prepend>{{ versionMark(edit(g), m.id) }}</template>
              </el-input>
              <el-input
                v-model="edit(g).variants[m.id].note"
                size="small"
                type="textarea"
                :autosize="{ minRows: 1, maxRows: 3 }"
                maxlength="300"
                placeholder="这一版独有的设定（可留空，留空时用上面的概括）"
              />
            </div>
          </div>
          <div v-if="g.members.length < (g.memberIds?.length || 0)" class="muted">另有 {{ g.memberIds.length - g.members.length }} 条已删除</div>
        </div>

        <!-- 主条目（合并稿 / 手写） -->
        <div v-if="status === 'open'" class="master">
          <div class="master-title">
            合并后的主条目（共性；上面每条是一个可选版本）
            <span class="muted">{{ g.draft ? `AI 合并稿（${g.draft.model || ''}），可修改` : '还没有合并稿：默认用第一条的内容，可以直接改，或让 AI 写' }}</span>
          </div>
          <el-form label-width="64px" size="small">
            <el-form-item label="名称">
              <el-input v-model="edit(g).title" maxlength="100" style="width: 240px" />
              <el-input v-model="edit(g).subtype" placeholder="细分类型" maxlength="32" style="width: 140px; margin-left: 8px" />
            </el-form-item>
            <el-form-item label="共性">
              <el-input v-model="edit(g).summary" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="300" placeholder="一句话说清这些素材的共同点" />
            </el-form-item>
            <el-form-item label="详细">
              <el-input v-model="edit(g).detail" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="它们共有的设定" />
            </el-form-item>
            <el-form-item label="属性"><AttributeEditor v-model="edit(g).attributes" :category="g.category" style="width: 100%" /></el-form-item>
            <el-form-item label="标签"><el-input-tag v-model="edit(g).tags" placeholder="回车添加" :max="12" /></el-form-item>
          </el-form>
          <div class="master-actions">
            <el-button type="primary" size="small" :icon="Connection" :disabled="edit(g).memberIds.length < 2 || g.status === 'DRAFTING'" :loading="applying[g.id]" @click="doApply(g)">
              合并（{{ edit(g).memberIds.length }} 条）
            </el-button>
          </div>
        </div>
      </div>
      <el-pagination
        v-if="total > PAGE"
        v-model:current-page="page"
        class="pager"
        small
        layout="prev, pager, next, total"
        :total="total"
        :page-size="PAGE"
        @current-change="load"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Connection, MagicStick, Search } from '@element-plus/icons-vue'
import AttributeEditor from './AttributeEditor.vue'
import {
  MATERIAL_CATEGORIES,
  applyMerge,
  categoryOf,
  draftMerges,
  findMerges,
  getMaterialSources,
  ignoreMerges,
  listMerges,
  mergeCounts,
  mergeDraftStatus,
  restoreMerges,
  stopMergeDraft
} from '@/api/material'
import { listModels as listConfigs } from '@/api/aiModel'
import { runningLlama } from '@/api/localModel'
import { errorMessage } from '@/api/request'

/** 素材精炼 / 合并：查找相似素材组 → （可选）AI 写合并稿 → 逐组确认合并 */
const emit = defineEmits(['changed', 'open-material'])
const PAGE = 10
const MODEL_KEY = 'nan_novel.merge.model'

const scope = reactive({
  categories: MATERIAL_CATEGORIES.filter((c) => c.code !== 'plot').map((c) => c.code),
  books: [],
  threshold: 0.82,
  maxGroup: 6,
  crossBookOnly: false
})
const sources = ref([])
const finding = ref(false)
const findInfo = ref('')
const status = ref('open')
const filter = reactive({ category: '', cross: '' })
const rows = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const counts = ref({})
const checked = reactive({})
const edits = reactive({})
const applying = reactive({})
const configs = ref([])
const llama = ref(null)
const draftModel = ref(readModel())
const drafting = ref({ running: false, total: 0, done: 0, failed: 0 })
let timer = null

function readModel() {
  try {
    return localStorage.getItem(MODEL_KEY) || ''
  } catch {
    return ''
  }
}

const emptyText = computed(() =>
  status.value === 'open' ? '没有待处理的合并建议：设好范围后点「查找相似素材」' : status.value === 'APPLIED' ? '还没有合并过' : '没有忽略的建议'
)
const checkedIds = computed(() => rows.value.filter((g) => checked[g.id]).map((g) => g.id))
const allChecked = computed(() => rows.value.length > 0 && rows.value.every((g) => checked[g.id]))
const someChecked = computed(() => rows.value.some((g) => checked[g.id]))
const toggleAll = (v) => rows.value.forEach((g) => (checked[g.id] = v))

const firstAttrs = (attrs) => Object.fromEntries(Object.entries(attrs || {}).slice(0, 3))

/**
 * 每组的编辑状态；成员默认 = 合并稿判定的 same（没有 = 全部）。主条目只放共性：有合并稿就照用（共性为空也保持为空，
 * 各自的写法在版本里）；没有合并稿时名称 / 概括先用第一条，详细 / 属性留空让作者写共性。
 */
function edit(g) {
  if (!edits[g.id]) {
    const d = g.draft || {}
    const first = g.members[0] || {}
    const same = (d.same || []).filter((id) => g.members.some((m) => m.id === id))
    edits[g.id] = {
      memberIds: same.length >= 2 ? same : g.members.map((m) => m.id),
      title: d.title || first.title || '',
      subtype: d.subtype || '',
      summary: d.summary || first.summary || '',
      detail: d.detail || '',
      attributes: { ...(d.attributes || {}) },
      tags: [...(d.tags?.length ? d.tags : first.tags || [])],
      // 每条成员是一个可选版本：合并稿给了就用（旧格式是一句话），否则版本名默认用细分类型 / 名称
      variants: Object.fromEntries(
        g.members.map((m) => {
          const v = d.variants?.[m.id]
          const obj = typeof v === 'string' ? { note: v } : v || {}
          return [m.id, { label: obj.label || m.subtype || m.title || '', note: obj.note || '' }]
        })
      )
    }
  }
  return edits[g.id]
}

/** 版本序号 ①②…：按当前勾选的成员排 */
const MARKS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫'
function versionMark(e, id) {
  const i = e.memberIds.indexOf(id)
  return i >= 0 ? MARKS[i] || `${i + 1}` : '·'
}

function toggleMember(g, id, on) {
  const e = edit(g)
  e.memberIds = on ? [...new Set([...e.memberIds, id])] : e.memberIds.filter((x) => x !== id)
}

async function load() {
  loading.value = true
  try {
    const res = await listMerges({
      status: status.value,
      category: filter.category || undefined,
      crossBook: filter.cross || undefined,
      page: page.value,
      size: PAGE
    })
    if (res.code !== 0) throw new Error(res.message)
    rows.value = res.data.records || []
    total.value = res.data.total || 0
    rows.value.forEach((g) => {
      // 合并稿刚写好：丢掉旧的编辑状态，换成合并稿的内容
      if (edits[g.id] && g.status === 'DRAFTED' && !edits[g.id].fromDraft) delete edits[g.id]
      edit(g).fromDraft = !!g.draft
    })
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载合并建议失败'))
  } finally {
    loading.value = false
  }
  loadCounts()
}

async function loadCounts() {
  try {
    const res = await mergeCounts()
    if (res.code === 0) counts.value = res.data
  } catch {
    // 数量只是提示
  }
}

watch([status, () => filter.category, () => filter.cross], () => {
  page.value = 1
  load()
})
watch(draftModel, (v) => {
  try {
    localStorage.setItem(MODEL_KEY, v || '')
  } catch {
    // 不记住也能用
  }
})

async function doFind() {
  if (!scope.categories.length) {
    ElMessage.warning('请至少选一个分类')
    return
  }
  finding.value = true
  try {
    const res = await findMerges({ ...scope, categories: [...scope.categories], books: [...scope.books] })
    if (res.code !== 0) throw new Error(res.message)
    const d = res.data
    findInfo.value = `上次查找：比较了 ${d.considered} 条，新建议 ${d.found} 组` + (d.skipped ? `，跳过 ${d.skipped} 组（已处理过 / 不符合范围）` : '') + (d.ms ? `，耗时 ${(d.ms / 1000).toFixed(1)} 秒` : '')
    ElMessage.success(`找到 ${d.found} 组相似素材`)
    status.value = 'open'
    page.value = 1
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e, '查找相似素材失败（需要本地向量模型，见「本地模型」页）'))
  } finally {
    finding.value = false
  }
}

function modelBody() {
  if (draftModel.value === 'gguf') return { source: 'gguf' }
  const id = Number(String(draftModel.value).replace('api:', ''))
  return { source: 'api', configId: id || undefined }
}

async function doDraft(ids) {
  if (!draftModel.value) {
    ElMessage.warning('先选写合并稿用的模型')
    return
  }
  try {
    const res = await draftMerges(ids, modelBody())
    if (res.code !== 0) throw new Error(res.message)
    drafting.value = res.data
    ids.forEach((id) => (checked[id] = false))
    await load()
    poll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '开始写合并稿失败'))
  }
}

async function doStop() {
  try {
    await stopMergeDraft()
    ElMessage.success('当前这组写完后停下，没写的回到待处理')
  } catch (e) {
    ElMessage.error(errorMessage(e, '暂停失败'))
  }
}

function poll() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    try {
      const res = await mergeDraftStatus()
      if (res.code === 0) drafting.value = res.data
    } catch {
      // 下次再试
    }
    await load()
    if (drafting.value.running) poll()
  }, 3000)
}

async function doIgnore(ids) {
  try {
    const res = await ignoreMerges(ids)
    if (res.code !== 0) throw new Error(res.message)
    ids.forEach((id) => (checked[id] = false))
    ElMessage.success('已忽略，以后查找不再建议这些组')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e, '忽略失败'))
  }
}

async function doRestore(id) {
  try {
    await restoreMerges([id])
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e, '恢复失败'))
  }
}

async function doApply(g) {
  const e = edit(g)
  applying[g.id] = true
  try {
    const variants = Object.fromEntries(e.memberIds.map((id) => [id, e.variants[id] || { label: '', note: '' }]))
    const res = await applyMerge(g.id, {
      memberIds: e.memberIds,
      title: e.title,
      subtype: e.subtype,
      summary: e.summary,
      detail: e.detail,
      attributes: e.attributes,
      tags: e.tags,
      variants
    })
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(`已合并为「${res.data.title}」，成员收进主条目（可在主条目里拆分）`)
    delete edits[g.id]
    emit('changed')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '合并失败'))
  } finally {
    applying[g.id] = false
  }
}

onMounted(async () => {
  load()
  mergeDraftStatus().then((res) => {
    if (res.code === 0) {
      drafting.value = res.data
      if (res.data.running) poll()
    }
  })
  getMaterialSources().then((res) => (sources.value = res.code === 0 ? res.data || [] : []))
  runningLlama().then((l) => (llama.value = l))
  try {
    const res = await listConfigs()
    configs.value = res.code === 0 ? (res.data || []).filter((c) => c.status === 'VERIFIED') : []
    if (!draftModel.value && configs.value.length) draftModel.value = `api:${(configs.value.find((c) => c.active) || configs.value[0]).id}`
  } catch {
    configs.value = []
  }
})
onBeforeUnmount(() => clearTimeout(timer))

defineExpose({ reload: load })
</script>

<style scoped>
.find-bar,
.list-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.label {
  font-size: 12px;
  color: #606266;
}
.num {
  width: 32px;
  font-size: 12px;
  color: #606266;
}
.tip {
  margin: 8px 0 14px;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}
.draft-alert {
  margin-top: 10px;
}
.group {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.group.checked {
  border-color: #a0cfff;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.spacer {
  flex: 1;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.warn {
  font-size: 12px;
  color: #e6a23c;
}
.members {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.member {
  padding: 8px;
  background: #fafafa;
  border-radius: 6px;
  font-size: 13px;
}
.member.off {
  opacity: 0.45;
}
.member-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.book {
  color: #409eff;
  font-size: 12px;
}
.member-summary {
  margin-top: 4px;
  line-height: 1.6;
  color: #606266;
}
.member-attrs {
  display: flex;
  flex-direction: column;
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.variant-label {
  margin-bottom: 4px;
}
.variant {
  margin-top: 6px;
}
.master {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #dcdfe6;
}
.master-title {
  margin-bottom: 8px;
  font-weight: 600;
  color: #303133;
}
.master-title .muted {
  margin-left: 8px;
  font-weight: normal;
}
.master-actions {
  text-align: right;
}
.pager {
  margin-top: 12px;
  justify-content: center;
}
</style>
