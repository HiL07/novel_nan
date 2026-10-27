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

    <!-- 右上角：使用说明（每个 AI 功能用到哪些内容） -->
    <div class="panel-head">
      <el-popover placement="bottom-end" :width="760" trigger="click">
        <template #reference>
          <el-button size="small" :icon="QuestionFilled">使用说明</el-button>
        </template>
        <div class="manual">
          <div class="manual-title">AI 构思用到哪些内容</div>
          <table class="manual-table">
            <thead>
              <tr><th>功能</th><th v-for="c in MANUAL_COLS" :key="c">{{ c }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in MANUAL_ROWS" :key="r.name">
                <td><b>{{ r.name }}</b></td>
                <td v-for="(v, i) in r.uses" :key="i" :class="{ no: v === '—' }">{{ v }}</td>
              </tr>
            </tbody>
          </table>
          <ul class="manual-notes">
            <li>「设定」「章节」只提供勾选的项；设定分类没有内容时，勾了也不会发送。</li>
            <li>「已选走向」= 后续走向里点了「支持 / 追加」的项；没选的不会用到（等于拒绝）。</li>
            <li>「已采用的大纲」有就会带上；书名、大纲、章节题目、后续走向都参考它。</li>
            <li>「素材」= 点「AI 构思后续走向」时在右侧抽屉里选的素材（打开时用 基调 + 构思方向 本地检索预勾选；屏蔽来源书也在那里改）。选好的素材也用于书名 / 大纲 / 章节题目，可在走向按钮下方删掉。</li>
            <li>设定页里的「AI 填写」不受本页选择影响：它使用全部当前设定、已写章节和大纲。</li>
          </ul>
        </div>
      </el-popover>
    </div>

    <!-- 构思输入：方向 + 素材 -->
    <el-form label-width="90px" class="idea-form">
      <el-form-item label="构思模型">
        <div class="mat-row">
          <el-radio-group v-model="source" size="small">
            <el-radio-button value="api">大模型（API）</el-radio-button>
            <el-radio-button value="local" :disabled="!localModels.length">本地模型</el-radio-button>
            <el-radio-button value="gguf" :disabled="!llama" :title="llama ? '' : '先到「llama.cpp」页启动 GGUF 模型'">GGUF</el-radio-button>
            <el-radio-button value="remote" disabled>远程模型（即将支持）</el-radio-button>
          </el-radio-group>
          <template v-if="source === 'api'">
            <span class="muted">{{ apiModel ? `${apiModel.name} · ${apiModel.model}` : '' }}</span>
          </template>
          <template v-else-if="source === 'gguf'">
            <span class="muted">{{ llama ? `llama.cpp · ${llama.name}` : 'llama.cpp 没有运行：请先到「llama.cpp」页启动' }}</span>
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
      <el-form-item label="设定">
        <div class="setting-row">
          <span v-if="!settingCats.length" class="muted">设定里还没有分类</span>
          <el-check-tag
            v-for="c in settingCats"
            :key="c.key"
            :checked="selectedCats.includes(c.key)"
            :class="{ 'empty-cat': !filledKeys.has(c.key) }"
            :title="filledKeys.has(c.key) ? '' : '这个分类还没有内容，勾选了也不会发送'"
            @change="toggleCat(c.key)"
          >
            {{ c.label }}<span v-if="c.custom" class="cat-mark">自定义</span><span v-if="!filledKeys.has(c.key)" class="cat-mark">（空）</span>
          </el-check-tag>
          <template v-if="settingCats.length">
            <el-button link size="small" @click="selectedCats = settingCats.map((c) => c.key)">全选</el-button>
            <el-button link size="small" @click="selectedCats = []">清空</el-button>
          </template>
        </div>
        <div class="muted">
          勾选的设定分类会提供给 AI（使用设定页当前内容，含未保存的修改）；默认都不提供。已选 {{ selectedCats.length }} 项，实际提供给 AI：{{ sentCount }} 项
        </div>
      </el-form-item>
      <el-form-item label="章节">
        <div class="setting-row">
          <span v-if="nextIndex <= 1" class="muted">还没有写好的章节</span>
          <template v-else>
            <el-check-tag :checked="useCurrent" @change="useCurrent = !useCurrent">
              当前章节<span class="cat-mark">第{{ nextIndex - 1 }}章：摘要 + 结尾</span>
            </el-check-tag>
            <el-check-tag v-if="nextIndex > 2" :checked="usePast" @change="usePast = !usePast">
              过去章节<span class="cat-mark">第1~{{ nextIndex - 2 }}章摘要 + 前情概要</span>
            </el-check-tag>
          </template>
        </div>
        <div v-if="nextIndex > 1" class="muted">勾选的章节提供给后续走向、书名和大纲；默认不提供。生成章节题目总会带上已写章节（要承接剧情）</div>
      </el-form-item>
      <el-form-item label="基调">
        <el-input
          v-model="tone"
          maxlength="200"
          show-word-limit
          clearable
          placeholder="可选：整体基调，如：黑暗压抑的废土求生，节奏快，带点黑色幽默（后续走向 / 书名 / 大纲 / 章节都会围绕它）"
        />
      </el-form-item>
      <el-form-item label="构思方向">
        <div class="hint-box">
          <el-input
            v-model="hint"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 12 }"
            maxlength="3000"
            show-word-limit
            placeholder="写下你想写的大致情节即可，如：末世，主角是带着秘密的拾荒者，被卷进两大势力的争夺……可以点右上角「AI 润色」扩写成完整构思"
          />
          <el-button
            class="hint-polish-btn"
            size="small"
            type="primary"
            plain
            :icon="EditPen"
            :loading="loading === 'hint_polish'"
            :disabled="!!loading || !ready || !hint.trim()"
            title="只根据框内文字扩写，不使用设定 / 基调 / 章节 / 素材"
            @click="polishHint"
          >AI 润色</el-button>
        </div>
        <div class="muted">「AI 润色」只根据框内的文字扩写，与设定、基调、章节、素材都无关</div>
        <div v-if="polished" class="direction-card polished">
          <div class="direction-text">
            <div><b>扩写结果：</b><span class="pre">{{ polished.text }}</span></div>
            <div v-if="polished.changes" class="muted">扩写了：{{ polished.changes }}</div>
          </div>
          <div class="direction-ops">
            <el-button link type="primary" size="small" @click="hint = polished.text; polished = null">替换原文</el-button>
            <el-button link size="small" @click="polished = null">放弃</el-button>
          </div>
        </div>

        <div class="direction-bar">
          <el-button size="small" :icon="MagicStick" :loading="loading === 'direction'" :disabled="!!loading || !ready" @click="openDirectionPicker">
            {{ directionLabel }}
          </el-button>
          <span class="muted">先在右侧选素材（可不选），再结合构思方向、基调、勾选的设定 / 章节生成；可重复生成，每次给出不同的走向</span>
        </div>
        <div v-if="picked.length" class="chips">
          <span class="muted">已选素材（也用于书名 / 大纲 / 章节题目）：</span>
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
          <el-button link size="small" @click="picked = []">清空</el-button>
        </div>
        <div v-if="directions.length" class="directions">
          <div class="dir-head">
            <span class="muted">后续走向 {{ directions.length }} 个：「支持」= 只选这一个，「追加」= 再多选一个，「拒绝」= 删除并让 AI 之后避开；没选的不会用到</span>
            <el-button link size="small" @click="clearUnchosen">清空未选的</el-button>
          </div>
          <div v-for="d in directions" :key="d.id" class="direction-card" :class="{ chosen: chosenIds.includes(d.id) }">
            <div class="direction-text">
              <el-tag v-if="chosenIds.includes(d.id)" size="small" type="success" effect="dark">已选</el-tag>
              <b v-if="d.label">{{ d.label }}：</b>{{ d.direction }}
            </div>
            <div class="direction-ops">
              <template v-if="chosenIds.includes(d.id)">
                <el-button link size="small" @click="unchoose(d.id)">取消选择</el-button>
              </template>
              <template v-else>
                <el-button link type="primary" size="small" @click="support(d.id)">支持</el-button>
                <el-button link type="primary" size="small" @click="addChosen(d.id)">追加</el-button>
                <el-button link type="danger" size="small" @click="rejectDirection(d.id)">拒绝</el-button>
              </template>
            </div>
          </div>
        </div>
        <div v-if="chosenTexts.length" class="chosen-box">
          <b>已选后续走向（{{ chosenTexts.length }}）</b>
          <span class="muted">将用于生成书名 / 大纲 / 章节题目</span>
        </div>
        <div v-if="rejected.length" class="muted">
          已拒绝 {{ rejected.length }} 个走向，再生成时 AI 会避开类似的
          <el-button link size="small" @click="rejected = []">清空记录</el-button>
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
    <div v-else-if="last" class="used muted">本次没有使用素材</div>

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

    <!-- 「AI 构思后续走向」前的素材选择（右侧抽屉，可不选；屏蔽来源书也在这里改） -->
    <MaterialPicker
      v-model="pickerVisible"
      v-model:exclude-books="blockedBooks"
      pick-only
      edit-blocked
      title="选择素材后 AI 构思后续走向"
      action-label="构思走向"
      :initial-selected="picked"
      :vector-query="pickerQuery"
      :auto-vector="!!pickerQuery && !picked.length"
      feedback-context="AI 构思 › 后续走向"
      @apply="onPick"
    />
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElInput, ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { EditPen, MagicStick, QuestionFilled } from '@element-plus/icons-vue'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import { useBlockedBooks } from '@/components/material/blockedBooks'
import { categoryOf } from '@/api/material'
import { generateIdeas, updateNovel } from '@/api/novelGen'
import { errorMessage } from '@/api/request'

/** AI 构思：书名 / 大纲 / 下一章题目，结合设定与素材库。经 Java（取素材），模型可选大模型或本地模型（+ 适配器） */
const props = defineProps({
  novel: { type: Object, required: true },
  apiModel: { type: Object, default: null },
  llama: { type: Object, default: null }, // 运行中的 llama.cpp（GGUF）；null = 没运行
  localModels: { type: Array, default: () => [] },
  adapters: { type: Array, default: () => [] },
  nextIndex: { type: Number, required: true },
  /** () => {categories: [{key, label, custom}], spec}：设定编辑器的当前分类与设定 */
  readSettings: { type: Function, default: null }
})
const emit = defineEmits(['updated', 'use-chapter', 'detect-api'])
const router = useRouter()

// 构思模型：默认跟随工作区（大模型工作区用大模型；本地工作区用它的基础模型 + 适配器）
const source = ref(['local', 'gguf'].includes(props.novel.model.source) ? props.novel.model.source : 'api')
const baseId = ref(props.novel.model.baseId || props.localModels[0]?.id || '')
const adapterId = ref(props.novel.model.source === 'local' ? props.novel.model.adapterId || '' : '')
const baseAdapters = computed(() => props.adapters.filter((a) => a.compat === 'ok' && a.matchedBaseId === baseId.value))
const ready = computed(() => (source.value === 'api' ? !!props.apiModel : source.value === 'gguf' ? !!props.llama : !!baseId.value))
watch(() => props.localModels, (list) => { if (!baseId.value && list.length) baseId.value = list[0].id })

const hint = ref('')
const tone = ref('')
const rejected = ref([])         // 拒绝过的走向，再生成时让 AI 避开
const picked = ref([])           // 构思走向时在抽屉里选的素材，书名 / 大纲 / 章节题目也用
const outlineCount = ref(10)
const loading = ref('')
const saving = ref(false)
const last = ref(null)
const draft = ref(null)
const pickerVisible = ref(false)
const pickerQuery = ref('')      // 打开抽屉时的检索词（基调 + 构思方向）
const directions = ref([])
const blockedBooks = useBlockedBooks(props.novel.id)
const isBlocked = (m) => !m.pinned && !!m.sourceBook && blockedBooks.value.includes(m.sourceBook)

/* ---- 设定：按分类勾选提供给 AI 的设定（默认都不选，按工作区记在本机） ---- */
const settingCats = ref([])
const filledKeys = ref(new Set())
const selectedKey = `nan_novel.ideaSettings.${props.novel.id}`
const selectedCats = ref(loadSelected())
const sentCount = computed(() => selectedCats.value.filter((k) => filledKeys.value.has(k)).length)

function loadSelected() {
  try {
    const v = JSON.parse(localStorage.getItem(selectedKey) || '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}
watch(selectedCats, (v) => {
  try {
    localStorage.setItem(selectedKey, JSON.stringify(v))
  } catch {
    // 存储不可用：本次会话内仍然有效
  }
})

function toggleCat(key) {
  selectedCats.value = selectedCats.value.includes(key)
    ? selectedCats.value.filter((k) => k !== key)
    : [...selectedCats.value, key]
}

function readSettings() {
  return props.readSettings?.() || { categories: [], spec: [] }
}

/** 重新读取设定分类（切到本页时由工作区调用）：新增的分类默认不选，已删除的分类从选择中去掉 */
function refreshSettings() {
  const { categories, spec } = readSettings()
  settingCats.value = categories
  filledKeys.value = new Set(spec.map((c) => c.key))
  if (categories.length) {
    const keys = new Set(categories.map((c) => c.key))
    const kept = selectedCats.value.filter((k) => keys.has(k))
    if (kept.length !== selectedCats.value.length) selectedCats.value = kept
  }
}
onMounted(refreshSettings)
defineExpose({ refreshSettings })

/** 发请求时现取设定，只保留勾选且有内容的分类；都没选时发 []（不提供设定） */
function selectedSpec() {
  refreshSettings()
  const selected = new Set(selectedCats.value)
  return readSettings().spec.filter((c) => selected.has(c.key))
}

/* ---- 章节：是否提供当前章节 / 过去章节（默认都不提供，按工作区记在本机） ---- */
const chaptersKey = `nan_novel.ideaChapters.${props.novel.id}`
const savedChapters = (() => {
  try {
    return JSON.parse(localStorage.getItem(chaptersKey) || '{}') || {}
  } catch {
    return {}
  }
})()
const useCurrent = ref(savedChapters.current === true)
const usePast = ref(savedChapters.past === true)
watch([useCurrent, usePast], ([current, past]) => {
  try {
    localStorage.setItem(chaptersKey, JSON.stringify({ current, past }))
  } catch {
    // 存储不可用：本次会话内仍然有效
  }
})

/** 模型选择 + 设定 + 章节 + 素材 + 屏蔽书：所有构思请求共用 */
function modelAndMaterials() {
  return {
    ...modelOnly(),
    spec: selectedSpec(),
    chapterContext: { current: useCurrent.value, past: usePast.value },
    materialIds: picked.value.map((m) => m.id), excludeBooks: blockedBooks.value
  }
}
function modelOnly() {
  return {
    source: source.value, baseId: source.value === 'local' ? baseId.value : undefined,
    adapterId: source.value === 'local' ? adapterId.value || null : undefined
  }
}

/** 素材抽屉向量检索的检索词：基调 + 构思方向（检索词最多 500 字） */
const materialQuery = () => [tone.value.trim(), hint.value.trim()].filter(Boolean).join('；').slice(0, 500)

/** AI 润色：只把构思方向框里的文字发给模型扩写（不带设定 / 基调 / 章节 / 素材），结果由作者决定是否替换 */
const polished = ref(null)
async function polishHint() {
  loading.value = 'hint_polish'
  try {
    const data = await call(generateIdeas(props.novel.id, { ...modelOnly(), kind: 'hint_polish', hint: hint.value.trim() }), 'AI 润色失败')
    polished.value = data.result
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 8000 })
  } finally {
    loading.value = ''
  }
}

/* ---- 后续走向：可重复生成（新的追加在后面），支持 / 追加 = 选中，拒绝 = 删除并让 AI 避开；没选的不使用 ---- */
let directionSeq = 0
const chosenIds = ref([])
const directionText = (d) => (d.label ? `${d.label}：${d.direction}` : d.direction)
const chosenTexts = computed(() => chosenIds.value
  .map((id) => directions.value.find((d) => d.id === id))
  .filter(Boolean)
  .map(directionText))
const directionLabel = computed(() => (hint.value.trim() ? 'AI 构思后续走向'
  : tone.value.trim() ? 'AI 围绕基调给几个走向' : 'AI 给我几个走向'))

/** 点「AI 构思后续走向」：先在右侧抽屉选素材，确认后再生成 */
function openDirectionPicker() {
  pickerQuery.value = materialQuery()
  pickerVisible.value = true
}

async function suggestDirections() {
  const base = modelAndMaterials()
  // 已经给过的（含已选的）和拒绝过的都让 AI 避开，保证每次生成不同的走向
  const avoid = [...rejected.value, ...directions.value.map(directionText)].slice(-30)
  loading.value = 'direction'
  try {
    const data = await call(generateIdeas(props.novel.id, {
      ...base, kind: 'direction', hint: hint.value.trim(), tone: tone.value.trim(), rejected: avoid,
      count: 5, purpose: '作为后续走向，用于生成书名、大纲与章节', autoMaterials: false
    }), 'AI 生成走向失败')
    const list = (data.result.directions || []).map((d) => ({ ...d, id: ++directionSeq }))
    if (!list.length) ElMessage.warning('模型没有给出走向，请重试')
    directions.value = [...directions.value, ...list]
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 8000 })
  } finally {
    loading.value = ''
  }
}

function support(id) {
  chosenIds.value = [id]
}
function addChosen(id) {
  if (!chosenIds.value.includes(id)) chosenIds.value = [...chosenIds.value, id]
}
function unchoose(id) {
  chosenIds.value = chosenIds.value.filter((x) => x !== id)
}
function rejectDirection(id) {
  const d = directions.value.find((x) => x.id === id)
  if (!d) return
  const text = directionText(d)
  if (!rejected.value.includes(text)) rejected.value = [...rejected.value, text].slice(-20)
  directions.value = directions.value.filter((x) => x.id !== id)
}
function clearUnchosen() {
  directions.value = directions.value.filter((d) => chosenIds.value.includes(d.id))
}

/* ---- 使用说明：每个 AI 功能用到哪些内容（改请求内容时同步这里） ---- */
const MANUAL_COLS = ['设定（勾选）', '章节（勾选）', '基调', '构思方向', '已选走向', '已采用大纲', '素材']
const MANUAL_ROWS = [
  { name: 'AI 润色', uses: ['—', '—', '—', '只用框内文字', '—', '—', '—'] },
  { name: 'AI 构思后续走向', uses: ['✓', '✓', '✓', '✓', '避开已给出 / 已拒绝的', '✓', '右侧抽屉里选的'] },
  { name: '生成书名', uses: ['✓', '✓', '✓', '✓', '✓', '✓', '已选素材'] },
  { name: '生成大纲', uses: ['✓', '✓', '✓', '✓', '✓', '✓', '已选素材'] },
  { name: '生成章节题目', uses: ['✓', '总是带全部已写章节', '✓', '✓', '✓', '✓', '已选素材'] },
  { name: '素材抽屉预勾选', uses: ['—', '—', '检索词', '检索词', '—', '—', '本地向量检索素材库'] }
]

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

/** 抽屉确认（含「不用素材」= 空数组）：记下选择，然后生成走向 */
function onPick(list) {
  picked.value = list
  suggestDirections()
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
  loading.value = kind
  try {
    const data = await call(generateIdeas(props.novel.id, {
      ...modelAndMaterials(), kind, hint: hint.value.trim(), tone: tone.value.trim(), chosenDirections: chosenTexts.value,
      count: kind === 'outline' ? outlineCount.value : undefined,
      autoMaterials: false
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
  width: 100%;
  margin-top: 6px;
}
.setting-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  width: 100%;
}
.setting-row .el-check-tag {
  padding: 4px 10px;
  font-size: 13px;
  font-weight: normal;
}
.setting-row .empty-cat {
  opacity: 0.6;
}
.cat-mark {
  margin-left: 4px;
  font-size: 11px;
  color: #909399;
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
.direction-card.polished {
  margin-top: 6px;
  width: 100%;
  background: var(--el-color-primary-light-9);
}
.direction-card.chosen {
  background: var(--el-color-success-light-9);
  outline: 1px solid var(--el-color-success-light-5);
}
.direction-text .el-tag {
  margin-right: 6px;
}
.pre {
  white-space: pre-wrap;
}
.panel-head {
  display: flex;
  justify-content: flex-end;
}
.hint-box {
  position: relative;
  width: 100%;
}
.hint-box :deep(.el-textarea__inner) {
  padding-right: 96px;
}
.hint-polish-btn {
  position: absolute;
  top: 6px;
  right: 8px;
}
.dir-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.chosen-box {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  margin-top: 4px;
  font-size: 13px;
}
.manual {
  font-size: 13px;
  line-height: 1.6;
}
.manual-title {
  margin-bottom: 8px;
  font-weight: 600;
}
.manual-table {
  width: 100%;
  border-collapse: collapse;
}
.manual-table th,
.manual-table td {
  padding: 4px 6px;
  text-align: center;
  border: 1px solid var(--el-border-color-lighter);
}
.manual-table th:first-child,
.manual-table td:first-child {
  text-align: left;
  white-space: nowrap;
}
.manual-table td.no {
  color: var(--el-text-color-placeholder);
}
.manual-notes {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
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
