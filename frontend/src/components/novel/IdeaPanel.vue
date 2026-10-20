<template>
  <div class="idea-panel">
    <el-alert
      v-if="source === 'api' && !apiModel"
      type="warning"
      :closable="false"
      show-icon
      title="没有可用的大模型：请先在「模型配置」中添加模型并验证通过，或改用本地模型"
    >
      <el-button size="small" type="primary" @click="router.push('/ai/model')">去配置模型</el-button>
      <el-button size="small" @click="emit('detect-api')">重新检测</el-button>
    </el-alert>

    <!-- 构思输入：方向 + 素材 -->
    <el-form label-width="90px" class="idea-form">
      <el-form-item label="构思模型">
        <div class="mat-row">
          <el-radio-group v-model="source" size="small">
            <el-radio-button value="api">大模型（API）</el-radio-button>
            <el-radio-button value="local" :disabled="!localModels.length">本地模型</el-radio-button>
            <el-radio-button value="remote" disabled>远程模型（即将支持）</el-radio-button>
          </el-radio-group>
          <template v-if="source === 'api'">
            <span class="muted">{{ apiModel ? `${apiModel.name} · ${apiModel.model}` : '' }}</span>
          </template>
          <template v-else>
            <el-select v-model="baseId" size="small" style="width: 200px" @change="adapterId = ''">
              <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>
            <el-select v-model="adapterId" size="small" style="width: 200px" placeholder="不使用适配器">
              <el-option label="不使用适配器（基础模型）" value="" />
              <el-option v-for="a in baseAdapters" :key="a.id" :label="`适配器：${a.name}`" :value="a.id" />
            </el-select>
            <span class="muted">本地小模型不擅长策划，结果可能较弱；首次使用会自动加载模型</span>
          </template>
        </div>
      </el-form-item>
      <el-form-item label="构思方向">
        <el-input
          v-model="hint"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          maxlength="500"
          show-word-limit
          placeholder="可选：想要的方向、基调、卖点，如：废土末世 + 群像，主角是带着秘密的拾荒者，节奏紧凑、悬疑感强"
        />
        <div class="direction-bar">
          <el-button size="small" :icon="MagicStick" :loading="loading === 'direction'" :disabled="!!loading || !ready" @click="suggestDirections">
            {{ hint.trim() ? 'AI 细化 / 发散这个方向' : 'AI 给我几个方向' }}
          </el-button>
          <span class="muted">结合已有设定与素材给出 5 个构思方向，点一个即可填入（也可追加）</span>
        </div>
        <div v-if="directions.length" class="directions">
          <div v-for="(d, i) in directions" :key="i" class="direction-card">
            <div class="direction-text"><b v-if="d.label">{{ d.label }}：</b>{{ d.direction }}</div>
            <div class="direction-ops">
              <el-button link type="primary" size="small" @click="useDirection(d, false)">采用</el-button>
              <el-button link size="small" @click="useDirection(d, true)">追加</el-button>
            </div>
          </div>
          <el-button link size="small" @click="directions = []">收起</el-button>
        </div>
      </el-form-item>
      <el-form-item label="素材">
        <div class="mat-row">
          <el-button size="small" :icon="Collection" @click="pickerVisible = true">从素材库选择</el-button>
          <el-switch v-model="autoMaterials" active-text="AI 自动匹配素材" :disabled="!apiModel" />
          <span class="muted">{{ !apiModel ? '自动匹配用大模型做语义检索，需先配置大模型' : autoMaterials ? '用构思方向在素材库中语义检索，取最相关的几条（需要填写构思方向）' : '' }}</span>
        </div>
        <div class="mat-row blocked-row">
          <BlockedBooksSelect v-model="blockedBooks" class="blocked-select" />
          <span class="muted">屏蔽的书不参与选择与自动匹配（标为「保留」的素材除外）；本工作区记住此设置</span>
        </div>
        <div v-if="picked.length" class="chips">
          <el-tag
            v-for="m in picked"
            :key="m.id"
            closable
            size="small"
            :type="isBlocked(m) ? 'info' : ''"
            :title="isBlocked(m) ? `来源书《${m.sourceBook}》已屏蔽，本次不会使用` : ''"
            @close="removePicked(m.id)"
          >
            <s v-if="isBlocked(m)">{{ categoryOf(m.category)?.label }} · {{ m.title }}</s>
            <template v-else>{{ categoryOf(m.category)?.label }} · {{ m.title }}</template>
          </el-tag>
        </div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :icon="MagicStick" :loading="loading === 'title'" :disabled="!!loading || !ready" @click="run('title')">生成书名</el-button>
        <span class="count-input">
          <el-button type="primary" :icon="MagicStick" :loading="loading === 'outline'" :disabled="!!loading || !ready" @click="run('outline')">生成大纲</el-button>
          规划 <el-input-number v-model="outlineCount" :min="3" :max="source === 'local' ? 15 : 40" size="small" controls-position="right" style="width: 90px" /> 章
        </span>
        <el-button type="primary" :icon="MagicStick" :loading="loading === 'chapter'" :disabled="!!loading || !ready" @click="run('chapter')">生成第{{ nextIndex }}章题目</el-button>
        <span v-if="loading" class="muted">{{ loading === 'outline' ? '大纲较长，约需半分钟到两分钟…' : '构思中…' }}{{ source === 'local' ? '（本地模型可能需要先加载）' : '' }}</span>
      </el-form-item>
    </el-form>

    <!-- 本次用到的素材 -->
    <div v-if="last?.usedMaterials?.length" class="used">
      <span class="muted">提供给模型的素材：</span>
      <el-tooltip v-for="m in last.usedMaterials" :key="m.id" :content="m.auto ? `自动匹配 ${m.score} 分：${m.reason}` : '手动选择'" placement="top">
        <el-tag size="small" :type="m.auto ? 'success' : ''" effect="plain">{{ categoryOf(m.category)?.label }} · {{ m.title }}</el-tag>
      </el-tooltip>
    </div>
    <div v-else-if="last" class="used muted">本次没有使用素材（{{ autoMaterials ? '没有匹配到相关度足够高的素材' : '未选择素材' }}）</div>

    <div v-if="last && last.kind !== 'outline'" class="muted edit-tip">AI 给出的内容都可以直接修改后再采用</div>

    <!-- 书名候选 -->
    <div v-if="last?.kind === 'title'" class="result">
      <div v-for="(t, i) in last.result.titles" :key="i" class="idea-card">
        <div class="idea-head">
          <el-input v-model="t.title" size="small" class="idea-input" maxlength="100"><template #prepend>书名</template></el-input>
          <el-button size="small" type="primary" plain :disabled="!t.title.trim()" @click="useTitle(t.title.trim())">采用</el-button>
        </div>
        <div>{{ t.pitch }}</div>
        <div v-if="t.materials.length" class="muted">素材：{{ t.materials.join('、') }}</div>
      </div>
    </div>

    <!-- 章节方案 -->
    <div v-if="last?.kind === 'chapter'" class="result">
      <div v-for="(o, i) in last.result.options" :key="i" class="idea-card">
        <div class="idea-head">
          <el-input v-model="o.title" size="small" class="idea-input" maxlength="60"><template #prepend>第{{ last.nextIndex }}章</template></el-input>
          <el-button size="small" type="primary" plain :disabled="!o.goal.trim()" @click="emit('use-chapter', { title: o.title.trim(), goal: o.goal.trim() })">用这个方案写</el-button>
        </div>
        <el-input v-model="o.goal" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" maxlength="2000" />
        <div v-if="o.materials.length" class="muted">素材：{{ o.materials.join('、') }}</div>
      </div>
    </div>

    <!-- 大纲草稿（可编辑，采用后保存到工作区） -->
    <div v-if="draft" class="result">
      <div class="outline-head">
        <b>大纲草稿</b>
        <span class="muted">可直接修改，点「采用大纲」后保存到工作区，写作时按章自动填入标题与目标</span>
        <el-button v-if="draft.title && draft.title !== novel.title" size="small" @click="useTitle(draft.title)">采用书名《{{ draft.title }}》</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="saveOutline(draft)">采用大纲</el-button>
        <el-button size="small" @click="draft = null">丢弃</el-button>
      </div>
      <OutlineEditor :outline="draft" />
    </div>

    <!-- 已采用的大纲 -->
    <div v-if="novel.outline && !draft" class="result">
      <div class="outline-head">
        <b>已采用的大纲</b>
        <span class="muted">保存于 {{ novel.outline.savedAt }}</span>
        <el-button size="small" @click="editSaved">编辑</el-button>
        <el-button size="small" type="danger" plain @click="clearOutline">清除</el-button>
      </div>
      <OutlineEditor :outline="novel.outline" readonly :next-index="nextIndex" />
    </div>

    <MaterialPicker v-model="pickerVisible" pick-only :exclude-books="blockedBooks" @apply="onPick" />
  </div>
</template>

<script setup>
import { computed, defineComponent, h, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElInput, ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { Collection, MagicStick } from '@element-plus/icons-vue'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import BlockedBooksSelect from '@/components/material/BlockedBooksSelect.vue'
import { useBlockedBooks } from '@/components/material/blockedBooks'
import { categoryOf } from '@/api/material'
import { generateIdeas, updateNovel } from '@/api/novelGen'
import { errorMessage } from '@/api/request'

/** AI 构思：书名 / 大纲 / 下一章题目，结合设定与素材库。经 Java（取素材），模型可选大模型或本地模型（+ 适配器） */
const props = defineProps({
  novel: { type: Object, required: true },
  apiModel: { type: Object, default: null },
  localModels: { type: Array, default: () => [] },
  adapters: { type: Array, default: () => [] },
  nextIndex: { type: Number, required: true }
})
const emit = defineEmits(['updated', 'use-chapter', 'detect-api'])
const router = useRouter()

// 构思模型：默认跟随工作区（大模型工作区用大模型；本地工作区用它的基础模型 + 适配器）
const source = ref(props.novel.model.source === 'local' ? 'local' : 'api')
const baseId = ref(props.novel.model.baseId || props.localModels[0]?.id || '')
const adapterId = ref(props.novel.model.source === 'local' ? props.novel.model.adapterId || '' : '')
const baseAdapters = computed(() => props.adapters.filter((a) => a.compat === 'ok' && a.matchedBaseId === baseId.value))
const ready = computed(() => (source.value === 'api' ? !!props.apiModel : !!baseId.value))
watch(() => props.localModels, (list) => { if (!baseId.value && list.length) baseId.value = list[0].id })

const hint = ref('')
const picked = ref([])
const autoMaterials = ref(false)
const outlineCount = ref(10)
const loading = ref('')
const saving = ref(false)
const last = ref(null)
const draft = ref(null)
const pickerVisible = ref(false)
const directions = ref([])
const blockedBooks = useBlockedBooks(props.novel.id)
const isBlocked = (m) => !m.pinned && !!m.sourceBook && blockedBooks.value.includes(m.sourceBook)

/** 模型选择 + 素材 + 屏蔽书：所有构思请求共用 */
function modelAndMaterials() {
  return {
    source: source.value, baseId: source.value === 'local' ? baseId.value : undefined,
    adapterId: source.value === 'local' ? adapterId.value || null : undefined,
    materialIds: picked.value.map((m) => m.id), excludeBooks: blockedBooks.value
  }
}

/** AI 给构思方向：没填时给灵感，填了就在它基础上细化 / 发散 */
async function suggestDirections() {
  loading.value = 'direction'
  try {
    const data = await call(generateIdeas(props.novel.id, {
      ...modelAndMaterials(), kind: 'direction', hint: hint.value.trim(), count: 5, purpose: '构思书名、大纲与章节'
    }), 'AI 生成方向失败')
    directions.value = data.result.directions || []
    if (!directions.value.length) ElMessage.warning('模型没有给出方向，请重试')
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 8000 })
  } finally {
    loading.value = ''
  }
}

function useDirection(d, append) {
  const text = d.label ? `${d.label}：${d.direction}` : d.direction
  hint.value = (append && hint.value.trim() ? `${hint.value.trim()}\n${text}` : text).slice(0, 500)
}

/** 大纲：一句话 + 梗概 + 分章表（readonly 时高亮下一章） */
const OutlineEditor = defineComponent({
  props: { outline: Object, readonly: Boolean, nextIndex: Number },
  setup(p) {
    const field = (obj, key, rows) => (p.readonly
      ? h('div', { class: 'ro' }, obj[key] || '-')
      : h(ElInput, { modelValue: obj[key], 'onUpdate:modelValue': (v) => (obj[key] = v), type: 'textarea', autosize: { minRows: 1, maxRows: rows } }))
    return () => h('div', { class: 'outline' }, [
      h('div', { class: 'ol-line' }, [h('b', '一句话：'), field(p.outline, 'logline', 2)]),
      h('div', { class: 'ol-line' }, [h('b', '梗概：'), field(p.outline, 'synopsis', 8)]),
      ...p.outline.chapters.map((c) => h('div', { class: ['ol-chapter', { next: p.readonly && c.index === p.nextIndex }] }, [
        h('div', { class: 'ol-chapter-head' }, [
          h('span', `第${c.index}章`),
          p.readonly ? h('b', c.title) : h(ElInput, { modelValue: c.title, 'onUpdate:modelValue': (v) => (c.title = v), size: 'small', style: 'width: 240px' }),
          p.readonly && c.index === p.nextIndex ? h(ElTag, { size: 'small', type: 'success' }, () => '下一章') : null,
          c.materials?.length ? h('span', { class: 'muted' }, `素材：${c.materials.join('、')}`) : null
        ]),
        field(c, 'goal', 5)
      ]))
    ])
  }
})

function onPick(list) {
  const ids = new Set(picked.value.map((m) => m.id))
  picked.value.push(...list.filter((m) => !ids.has(m.id)))
}
function removePicked(id) {
  picked.value = picked.value.filter((m) => m.id !== id)
}

async function call(promise, fallback) {
  try {
    const res = await promise
    if (res.code !== 0) throw new Error(res.message || fallback)
    return res.data
  } catch (e) {
    throw new Error(errorMessage(e, fallback))
  }
}

async function run(kind) {
  if (autoMaterials.value && !hint.value.trim()) {
    ElMessage.warning('自动匹配素材需要先填写构思方向')
    return
  }
  loading.value = kind
  try {
    const data = await call(generateIdeas(props.novel.id, {
      ...modelAndMaterials(), kind, hint: hint.value.trim(), count: kind === 'outline' ? outlineCount.value : undefined,
      autoMaterials: autoMaterials.value
    }), 'AI 构思失败')
    last.value = data
    if (kind === 'outline') draft.value = data.result
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 8000 })
  } finally {
    loading.value = ''
  }
}

async function useTitle(title) {
  try {
    emit('updated', await call(updateNovel(props.novel.id, { title }), '保存书名失败'))
    ElMessage.success(`书名已改为《${title}》`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function saveOutline(outline) {
  saving.value = true
  try {
    emit('updated', await call(updateNovel(props.novel.id, { outline }), '保存大纲失败'))
    draft.value = null
    ElMessage.success('大纲已保存，写作时会按章自动填入标题与目标')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

function editSaved() {
  draft.value = JSON.parse(JSON.stringify(props.novel.outline))
}

async function clearOutline() {
  try {
    await ElMessageBox.confirm('清除已采用的大纲？已写的章节不受影响。', '清除大纲', { type: 'warning' })
  } catch {
    return
  }
  try {
    emit('updated', await call(updateNovel(props.novel.id, { clearOutline: true }), '清除失败'))
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.idea-form {
  margin-top: 12px;
}
.mat-row,
.chips,
.used,
.outline-head,
.idea-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.chips {
  margin-top: 6px;
}
.blocked-row {
  width: 100%;
  margin-top: 6px;
}
.blocked-select {
  width: 300px;
}
.direction-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  margin-top: 6px;
}
.directions {
  width: 100%;
  margin-top: 6px;
}
.direction-card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 10px;
  margin-bottom: 6px;
  font-size: 13px;
  line-height: 1.6;
  background: #f7f8fa;
  border-radius: 6px;
}
.direction-text {
  flex: 1;
}
.direction-ops {
  display: flex;
  flex-shrink: 0;
}
.count-input {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 12px;
  font-size: 13px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.used {
  margin: 4px 0 10px;
}
.result {
  margin-top: 10px;
}
.idea-card {
  padding: 10px 12px;
  margin-bottom: 8px;
  font-size: 13px;
  line-height: 1.7;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
}
.idea-input {
  flex: 1;
  max-width: 420px;
}
.idea-head {
  margin-bottom: 6px;
}
.outline-head {
  margin-bottom: 8px;
}
.outline :deep(.ol-line) {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 6px;
  margin-bottom: 8px;
  font-size: 13px;
}
.outline :deep(.ol-chapter) {
  padding: 8px 10px;
  margin-bottom: 6px;
  font-size: 13px;
  line-height: 1.7;
  border-left: 3px solid #e4e7ed;
}
.outline :deep(.ol-chapter.next) {
  border-left-color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}
.outline :deep(.ol-chapter-head) {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 4px;
}
.outline :deep(.ro) {
  white-space: pre-wrap;
}
</style>
