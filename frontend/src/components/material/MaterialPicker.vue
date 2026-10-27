<template>
  <el-drawer :model-value="modelValue" :title="drawerTitle" size="760px" @update:model-value="close" @open="onOpen" @closed="onClosed">
    <div class="filters">
      <el-radio-group v-model="mode" size="small" @change="onMode">
        <el-radio-button value="keyword">关键词</el-radio-button>
        <el-radio-button value="vector">向量检索</el-radio-button>
      </el-radio-group>
      <el-select v-model="category" placeholder="全部分类" clearable style="width: 120px" @change="onCategory">
        <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
      </el-select>
      <el-select v-model="tags" multiple filterable collapse-tags placeholder="标签" style="width: 170px" @change="research">
        <el-option v-for="t in tagCloud" :key="t.tag" :label="`${t.tag}（${t.count}）`" :value="t.tag" />
      </el-select>
      <template v-if="mode === 'keyword'">
        <el-input v-model="keyword" placeholder="关键词" clearable style="width: 170px" @keyup.enter="search" @clear="search" />
        <el-button :icon="Search" @click="search">检索</el-button>
      </template>
    </div>
    <div v-if="mode === 'vector'" class="filters">
      <el-input
        v-model="vq"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 4 }"
        maxlength="500"
        placeholder="描述想要的素材，本地向量模型按语义相似度排序（不用大模型、不花 token）"
        class="vector-input"
        @keydown.enter.exact.prevent="runVector"
      />
      <el-button type="primary" :icon="Search" :loading="loading" :disabled="!vq.trim()" @click="runVector">向量检索</el-button>
    </div>
    <div v-if="mode === 'vector' && vector" class="vector-info">
      比较了 {{ vector.considered }} 条素材（向量 + 关键词{{ vector.reranked ? ' + 重排' : '' }}），用时 {{ vector.ms }} ms
      <template v-if="vector.encoded">，新向量化 {{ vector.encoded }} 条</template>。
      <template v-if="vector.reranked">分数 = 相关度，{{ RERANK_MIN }} 以上一般算相关。</template>
      <template v-else>没有重排（{{ vector.rerankSkipped || '未启用' }}），分数 = 相似度，只看相对高低。</template>
    </div>
    <div v-if="editBlocked" class="blocked-row">
      <BlockedBooksSelect :model-value="excludeBooks" class="blocked-select" @update:model-value="onBlocked" />
      <span class="muted">屏蔽的书的素材不显示、不使用（标为「保留」的除外）；本工作区记住此设置</span>
    </div>
    <div v-else-if="excludeBooks.length" class="blocked-hint">
      已屏蔽来源书：{{ excludeBooks.map((b) => `《${b}》`).join('') }} —— 这些书的素材不显示（标为「保留」的除外）
    </div>

    <!-- 已选（含预选、其他检索里选的） -->
    <div v-if="selectedList.length" class="chosen">
      <span class="muted">已选 {{ selectedList.length }} 条：</span>
      <el-tag v-for="m in selectedList" :key="m.id" size="small" closable @close="selected[m.id] = null">{{ m.title }}</el-tag>
      <el-button link size="small" type="danger" @click="clearSelected">清空</el-button>
    </div>

    <div v-loading="loading" class="list">
      <el-empty v-if="!rows.length" :description="emptyText" :image-size="70" />
      <div v-for="r in rows" :key="r.material.id" class="pick-item" :class="{ 'is-checked': selected[r.material.id] }" @click="toggle(r.material)">
        <el-checkbox :model-value="!!selected[r.material.id]" @click.stop @change="toggle(r.material)" />
        <div class="pick-body">
          <div class="pick-head">
            <el-tag size="small" effect="plain">{{ categoryOf(r.material.category)?.label }}</el-tag>
            <b>{{ r.material.title }}</b>
            <span class="muted">{{ r.material.subtype }}</span>
            <el-tag v-if="r.material.pinned" size="small" type="warning" effect="plain">保留</el-tag>
            <span class="muted source">{{ r.material.sourceBook ? `《${r.material.sourceBook}》` : '手动添加' }}</span>
            <span v-if="r.score != null" class="score" :class="{ weak: vector?.reranked && r.score < RERANK_MIN }" :title="rankTip(r)">{{ r.score }}</span>
          </div>
          <div class="pick-summary">{{ r.material.summary }}</div>
          <div class="pick-tags">
            <el-tag v-for="t in (r.material.tags || []).slice(0, 6)" :key="t" size="small" type="info">{{ t }}</el-tag>
          </div>
          <div v-if="selected[r.material.id] && !pickOnly" class="target">将应用到：{{ describeTarget(r.material, categories) }}</div>
        </div>
      </div>
    </div>

    <template #footer>
      <template v-if="actionLabel">
        <span class="muted footer-hint">不选素材 = 只按输入框内容{{ actionLabel }}</span>
        <el-button @click="close">取消</el-button>
        <el-button @click="apply(true)">不用素材，直接{{ actionLabel }}</el-button>
        <el-button type="primary" :disabled="!selectedList.length" @click="apply(false)">用 {{ selectedList.length || '' }} 条素材{{ actionLabel }}</el-button>
      </template>
      <template v-else>
        <span class="muted footer-hint">{{ pickOnly ? '选中的素材会提供给 AI 构思书名 / 大纲 / 章节' : '应用 = 复制到当前设定，之后可随意修改；素材库后续修改不会影响已应用的内容' }}</span>
        <el-button @click="close">取消</el-button>
        <el-button type="primary" :disabled="!selectedList.length" @click="apply(false)">{{ pickOnly ? '选择' : '应用' }} {{ selectedList.length || '' }} 条</el-button>
      </template>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { MATERIAL_CATEGORIES, categoryOf, getMaterialTags, searchMaterials, vectorFeedback, vectorSearch } from '@/api/material'
import BlockedBooksSelect from '@/components/material/BlockedBooksSelect.vue'
import { describeTarget } from '@/novel-options/materialApply'
import { errorMessage } from '@/api/request'

/** categories：当前设定的分类（用于预览应用位置）；initialCategory：打开时预选的素材分类；pickOnly：只选择不应用（AI 用）；
 *  excludeBooks：屏蔽的来源书（不列出其素材，保留的除外）；
 *  initialSelected：打开时预先勾选的素材；vectorQuery：向量检索框预填的内容；autoVector：打开即向量检索并预勾选前 AUTO_PICK 条；
 *  actionLabel：AI 动作（如「生成」「润色」）——有它时可以什么都不选直接确认（apply 传空数组），关闭 / 取消发 cancel；
 *  feedbackContext：记录检索反馈时说明用在哪（如「设定 › 世界观 › 力量体系」）；
 *  editBlocked：在抽屉里直接修改屏蔽的来源书（v-model:exclude-books） */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  pickOnly: { type: Boolean, default: false },
  categories: { type: Array, default: () => [] },
  initialCategory: { type: String, default: '' },
  excludeBooks: { type: Array, default: () => [] },
  initialSelected: { type: Array, default: () => [] },
  vectorQuery: { type: String, default: '' },
  autoVector: { type: Boolean, default: false },
  actionLabel: { type: String, default: '' },
  title: { type: String, default: '' },
  feedbackContext: { type: String, default: '' },
  editBlocked: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'update:excludeBooks', 'apply', 'cancel'])

const AUTO_PICK = 5
/** 重排后的相关度达到这个分才算相关（与 Java MaterialService.RERANK_MIN_SCORE 一致） */
const RERANK_MIN = 30
const rankTip = (r) => `相似度 ${r.similarity}` + (r.vecRank ? ` · 向量第 ${r.vecRank}` : '') + (r.lexRank ? ` · 关键词第 ${r.lexRank}` : '')

const mode = ref('keyword')
const category = ref('')
const keyword = ref('')
const tags = ref([])
const tagCloud = ref([])
const records = ref([])
const vq = ref('')
const vector = ref(null)
const loading = ref(false)
const selected = reactive({})
let applied = false

const selectedList = computed(() => Object.values(selected).filter(Boolean))
const drawerTitle = computed(() => props.title || (props.actionLabel ? `选择素材后 AI ${props.actionLabel}` : props.pickOnly ? '选择构思用的素材' : '从素材库添加'))
const rows = computed(() => (mode.value === 'vector'
  ? vector.value?.results || []
  : records.value.map((m) => ({ material: m, score: null }))))
const emptyText = computed(() => (mode.value === 'vector'
  ? (vector.value ? '没有符合条件的素材' : '输入需求后点「向量检索」')
  : '没有符合条件的素材（可到「素材库」页新建或从小说提取中保存）'))

function close() {
  emit('update:modelValue', false)
}

function onClosed() {
  if (!applied) emit('cancel')
}

async function onOpen() {
  applied = false
  category.value = props.initialCategory || ''
  tags.value = []
  vector.value = null
  vq.value = props.vectorQuery || ''
  Object.keys(selected).forEach((k) => delete selected[k])
  props.initialSelected.forEach((m) => (selected[m.id] = m))
  loadTags()
  if (props.autoVector && vq.value.trim()) {
    mode.value = 'vector'
    await runVector()
    // 重排过：只预勾相关度够的；没重排：分数不可比，取最前面几条
    ;(vector.value?.results || [])
      .filter((r) => !vector.value.reranked || r.score >= RERANK_MIN)
      .slice(0, AUTO_PICK)
      .forEach((r) => (selected[r.material.id] = r.material))
  } else {
    mode.value = 'keyword'
    search()
  }
}

function loadTags() {
  getMaterialTags(category.value || undefined).then((r) => r.code === 0 && (tagCloud.value = r.data))
}

function onCategory() {
  tags.value = []
  loadTags()
  research()
}

function onMode(m) {
  if (m === 'keyword' && !records.value.length) search()
}

/** 分类 / 标签变化：重新跑当前的检索方式 */
function research() {
  if (mode.value === 'keyword') search()
  else if (vq.value.trim()) runVector()
}

async function search() {
  loading.value = true
  try {
    const res = await searchMaterials({
      category: category.value || undefined, keyword: keyword.value.trim() || undefined, tags: tags.value, tagMode: 'all',
      excludeBooks: props.excludeBooks, page: 1, size: 50
    })
    if (res.code !== 0) throw new Error(res.message)
    records.value = res.data.records
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载素材失败'))
  } finally {
    loading.value = false
  }
}

async function runVector() {
  const query = vq.value.trim()
  if (!query) return
  loading.value = true
  try {
    const res = await vectorSearch({
      query, category: category.value || undefined, tags: tags.value, excludeBooks: props.excludeBooks, limit: 30
    })
    if (res.code !== 0) throw new Error(res.message)
    vector.value = { ...res.data, query }
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '向量检索失败'), duration: 6000 })
  } finally {
    loading.value = false
  }
}

/** 抽屉里改了屏蔽书：等父组件更新 excludeBooks 后重新检索 */
async function onBlocked(books) {
  emit('update:excludeBooks', books)
  await nextTick()
  research()
}

function toggle(m) {
  selected[m.id] = selected[m.id] ? null : m
}

function clearSelected() {
  Object.keys(selected).forEach((k) => delete selected[k])
}

/** none：「不用素材，直接…」 */
function apply(none) {
  const list = none ? [] : selectedList.value
  if (vector.value?.results?.length) {
    // 向量检索的结果里勾了哪些、没勾哪些：以后微调向量模型的训练数据
    vectorFeedback({
      query: vector.value.query, modelId: vector.value.modelId || '', context: props.feedbackContext,
      shownIds: vector.value.results.map((r) => r.material.id), pickedIds: list.map((m) => m.id)
    })
  }
  applied = true
  emit('apply', list)
  close()
}
</script>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
}
.blocked-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.blocked-select {
  width: 300px;
}
.vector-input {
  flex: 1;
  min-width: 240px;
}
.vector-info {
  margin: -4px 0 10px;
  font-size: 12px;
  color: #606266;
}
.chosen {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  padding: 8px 10px;
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
}
.list {
  min-height: 200px;
}
.pick-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  cursor: pointer;
}
.pick-item.is-checked {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.pick-body {
  flex: 1;
  min-width: 0;
}
.pick-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pick-summary {
  margin-top: 4px;
  font-size: 13px;
  color: #606266;
}
.pick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.target {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-primary);
}
.muted {
  font-size: 12px;
  color: #909399;
}
.source {
  margin-left: auto;
  white-space: nowrap;
}
.score.weak {
  color: #c0c4cc;
}
.score {
  min-width: 28px;
  font-weight: 600;
  text-align: right;
  color: var(--el-color-primary);
}
.blocked-hint {
  margin: -4px 0 10px;
  font-size: 12px;
  color: var(--el-color-warning-dark-2);
}
.footer-hint {
  margin-right: 12px;
}
</style>
