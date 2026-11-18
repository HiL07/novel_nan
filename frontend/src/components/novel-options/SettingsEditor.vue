<template>
  <div class="settings-editor">
    <div class="page-header">
      <div class="header-title">
        <slot name="lead" />
        <el-tooltip placement="bottom-start" :show-after="200"
                    content="只有你选择 / 填写 / 调整过的内容才会作为生成约束；没动过的默认值不会写进提示词。点卡片修改，空着的项在下面「还可以补充」里">
          <el-icon class="hint-icon"><InfoFilled /></el-icon>
        </el-tooltip>
        <el-tag v-if="editMode" size="small" type="warning" effect="plain" closable @close="editMode = false">编辑结构中</el-tag>
      </div>
      <div class="header-actions">
        <AiFillSettings
          v-if="aiEnabled"
          :cfg="aiCfg"
          :api-model="ai.apiModel"
          :llama="ai.llama"
          :local-models="ai.localModels"
          :adapters="ai.adapters"
          :blocked-books="blockedBooks"
          :suggest="aiSuggestHints"
          @update:blocked-books="setBlockedBooks"
        />
        <slot name="actions" />
        <el-dropdown trigger="click" @command="onMore">
          <el-button :icon="MoreFilled">更多</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="picker" :icon="Collection">从素材库添加</el-dropdown-item>
              <el-dropdown-item command="preview" :icon="View">查看 AI 看到的设定</el-dropdown-item>
              <el-dropdown-item command="json" :icon="Document" :disabled="!spec.length">查看 JSON</el-dropdown-item>
              <el-dropdown-item command="structure" :icon="Operation" divided>
                {{ editMode ? '退出编辑结构' : '编辑结构（增删字段 / 选项）' }}
              </el-dropdown-item>
              <el-dropdown-item command="reset" :icon="RefreshLeft">重置设定</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <div v-loading="loading" class="create-body" :class="{ 'is-external-nav': externalNav }">
      <!-- 分类导航（externalNav：工作区书房把它放到最左栏，用 expose 的 nav 渲染） -->
      <el-card v-if="!externalNav" class="box-card nav-card" shadow="never">
        <div class="nav-group-title">基础设定</div>
        <div
          v-for="cat in builtinCategories"
          :key="cat.key"
          class="nav-item"
          :class="{ 'is-active': cat.key === activeKey }"
          @click="activeKey = cat.key"
        >
          <el-icon><component :is="cat.icon || 'Collection'" /></el-icon>
          <span class="nav-label">{{ cat.label }}</span>
          <el-tooltip :content="`已填 ${filledCount(cat)} / ${cat.fields.length} 项`" placement="right" :show-after="300">
            <span class="nav-dot" :class="`is-${progressOf(cat)}`" />
          </el-tooltip>
        </div>

        <div class="nav-group-title">自定义元素</div>
        <div
          v-for="cat in customCategories"
          :key="cat.key"
          class="nav-item"
          :class="{ 'is-active': cat.key === activeKey }"
          @click="activeKey = cat.key"
        >
          <el-icon><component :is="cat.icon || 'Collection'" /></el-icon>
          <span class="nav-label">{{ cat.label }}</span>
          <el-tooltip :content="`已填 ${filledCount(cat)} / ${cat.fields.length} 项`" placement="right" :show-after="300">
            <span class="nav-dot" :class="`is-${progressOf(cat)}`" />
          </el-tooltip>
        </div>
        <el-button class="nav-add" :icon="Plus" plain type="primary" @click="openCategoryEditor(null)">
          添加自定义元素
        </el-button>
        <p class="nav-tip">如：怪物、势力、种族、法宝……可套用推荐模板或完全自定义</p>
      </el-card>

      <!-- 当前分类的选项 -->
      <el-card v-if="activeCategory" class="box-card main-card" shadow="never">
        <div class="cat-header">
          <el-icon class="cat-icon"><component :is="activeCategory.icon || 'Collection'" /></el-icon>
          <div class="cat-title-wrap">
            <div class="cat-title">{{ activeCategory.label }}</div>
            <div v-if="activeCategory.desc" class="cat-desc">{{ activeCategory.desc }}</div>
          </div>
          <el-tooltip v-if="aiEnabled" content="让 AI 填写本分类中还没填的文本 / 标签 / 选择项（分组用各自的「AI 生成」；数字和滑块请自己定）" placement="top">
            <el-button :icon="MagicStick" type="primary" plain size="small" :loading="aiLoading(`cat:${activeCategory.key}`)" :disabled="aiLocked([activeCategory.label])" @click="fillCategory(activeCategory)">
              AI 补全本分类
            </el-button>
          </el-tooltip>
          <template v-if="activeCategory.custom">
            <el-button :icon="Edit" link @click="openCategoryEditor(activeCategory)">编辑</el-button>
            <el-button :icon="Delete" link type="danger" @click="removeCategory(activeCategory)">删除元素</el-button>
          </template>
        </div>

        <el-empty v-if="!activeCategory.fields.length" description="还没有选项项">
          <el-button type="primary" :icon="Plus" @click="addCategoryField">添加选项项</el-button>
        </el-empty>

        <!-- 编辑结构：所有字段都以表单展开（增删字段 / 选项要看到全部） -->
        <template v-if="editMode">
          <OptionField
            v-for="field in activeCategory.fields"
            :key="`${activeCategory.key}:${field.key}`"
            :field="field"
            :container="values[activeCategory.key]"
            :siblings="activeCategory.fields"
            :path="[activeCategory.label]"
          />
        </template>

        <!-- 平时：填过的字段是内容卡片，点一下才编辑；空着的收进「还可以补充」 -->
        <template v-else>
          <div v-if="shownFields.length" class="field-grid">
            <template v-for="field in shownFields" :key="`${activeCategory.key}:${field.key}`">
              <!-- 列表（背景卡、阶段表、怪物…）：卡片网格，点卡片在下面展开编辑 -->
              <div v-if="isGroupGrid(field)" class="field-card wide is-group">
                <GroupCardGrid :field="field" :container="values[activeCategory.key]" :path="[activeCategory.label]" />
              </div>
              <div v-else-if="isOpen(field)" class="field-card is-editing" :class="{ wide: isWide(field) }">
                <OptionField
                  :field="field"
                  :container="values[activeCategory.key]"
                  :siblings="activeCategory.fields"
                  :path="[activeCategory.label]"
                />
                <div v-if="field.type !== 'group'" class="card-foot">
                  <el-button size="small" type="primary" plain :icon="Check" @click="closeField(field)">完成</el-button>
                </div>
              </div>
              <div v-else class="field-card is-reading" :class="{ wide: isWide(field) }" title="点击修改" @click="openField(field)">
                <div class="fc-head">
                  <span class="fc-title">{{ field.label }}</span>
                  <el-icon class="fc-edit"><EditPen /></el-icon>
                </div>
                <!-- 力量体系：境界从低到高画成阶梯（悬停看说明 / 突破代价） -->
                <template v-if="ladderOf(field).steps.length">
                  <div v-if="ladderOf(field).intro" class="ladder-intro">{{ ladderOf(field).intro }}</div>
                  <div class="ladder">
                    <template v-for="(st, i) in ladderOf(field).steps" :key="i">
                      <span v-if="i" class="ladder-arrow">›</span>
                      <el-tooltip :content="st.desc || st.name" placement="top" :show-after="200" :disabled="!st.desc">
                        <span class="ladder-step" :style="{ '--lv': i / Math.max(ladderOf(field).steps.length - 1, 1) }">{{ st.name }}</span>
                      </el-tooltip>
                    </template>
                  </div>
                  <div v-if="ladderOf(field).rest" class="ladder-intro">{{ ladderOf(field).rest }}</div>
                </template>
                <!-- 标签：都是短词 → 小圆角标签；有长句（如世界规则）→ 列表，长句做成圆角标签很难读 -->
                <div v-else-if="field.type === 'tags' && values[activeKey][field.key].every((t) => String(t).length <= 14)" class="chips">
                  <span v-for="t in values[activeKey][field.key]" :key="t" class="chip">{{ t }}</span>
                </div>
                <ul v-else-if="field.type === 'tags'" class="rule-list">
                  <li v-for="t in values[activeKey][field.key]" :key="t">{{ t }}</li>
                </ul>
                <SpecTree v-else :items="summaryOf(field)" root compact />
              </div>
            </template>
          </div>
          <el-empty v-else-if="activeCategory.fields.length" :image-size="70"
                    description="这一类还没有填写，从下面挑一项开始，或者用「AI 补全本分类」" />
          <div v-if="emptyFields.length" class="more-fields">
            <span class="more-label">还可以补充：</span>
            <el-button v-for="field in emptyFields" :key="field.key" size="small" round :icon="Plus" @click="openField(field)">
              {{ field.label }}
            </el-button>
          </div>
        </template>

        <el-button
          v-if="editMode && activeCategory.fields.length"
          class="add-field-btn"
          :icon="Plus"
          type="primary"
          plain
          @click="addCategoryField"
        >
          为「{{ activeCategory.label }}」添加选项项
        </el-button>
      </el-card>

    </div>

    <!-- AI 看到的设定（原来右侧的「设定预览」栏） -->
    <el-drawer v-model="previewVisible" title="AI 看到的设定" size="420px" append-to-body>
      <div class="muted drawer-hint">只包含你选择 / 填写过的内容，写正文和 AI 构思时就是按这份设定生成的</div>
      <el-empty v-if="!spec.length" description="还没有选择任何设定" :image-size="80" />
      <div v-for="c in spec" :key="c.key" class="preview-cat">
        <div class="preview-cat-title" @click="activeKey = c.key; previewVisible = false">{{ c.label }}</div>
        <SpecTree :items="c.items" root />
      </div>
      <template #footer>
        <el-button :disabled="!spec.length" @click="jsonVisible = true">查看 JSON</el-button>
      </template>
    </el-drawer>

    <FieldEditor
      v-model="fieldEditor.visible"
      :title="fieldEditor.title"
      :suggestions="fieldEditor.suggestions"
      :existing="fieldEditor.target || []"
      @save="onFieldSave"
    />
    <CategoryEditor
      v-model="categoryEditor.visible"
      :templates="templates"
      :editing="categoryEditor.editing"
      @save="onCategorySave"
    />

    <MaterialPicker v-model="picker.visible" :categories="categories" :initial-category="picker.category" @apply="onApplyMaterials" />
    <!-- 每次 AI 生成 / 润色前必经的素材选择（可以什么都不选） -->
    <MaterialPicker
      v-model="aiPicker.visible"
      pick-only
      :title="aiPicker.title"
      :action-label="aiPicker.action"
      :vector-query="aiPicker.query"
      :auto-vector="aiPicker.auto"
      :initial-selected="aiPicker.initial"
      :exclude-books="blockedBooks"
      :feedback-context="aiPicker.context"
      :novel-id="novelId"
      @apply="onAiPicked"
      @cancel="onAiPickCancel"
    />

    <el-dialog v-model="jsonVisible" title="设定 JSON" width="680px">
      <el-radio-group v-model="jsonMode" size="small" class="json-mode">
        <el-radio-button value="spec">设定结果</el-radio-button>
        <el-radio-button value="full">完整配置（含自定义结构）</el-radio-button>
      </el-radio-group>
      <p class="json-hint">
        {{ jsonMode === 'spec' ? '只包含已选择 / 填写的内容，便于后续拼进生成提示词。' : '选项结构 + 取值，便于之后存入数据库后原样恢复。' }}
      </p>
      <pre class="json-box">{{ jsonText }}</pre>
      <template #footer>
        <el-button type="primary" :icon="CopyDocument" @click="copyJson">复制</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, h, onMounted, provide, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import { Check, Collection, CopyDocument, Delete, Document, Edit, EditPen, InfoFilled, MagicStick, MoreFilled, Operation, Plus, RefreshLeft, View } from '@element-plus/icons-vue'
import OptionField from './OptionField.vue'
import FieldEditor from './FieldEditor.vue'
import CategoryEditor from './CategoryEditor.vue'
import SpecTree from './SpecTree.vue'
import GroupCardGrid from './GroupCardGrid.vue'
import AiFillSettings from './AiFillSettings.vue'
import { generateIdeas } from '@/api/novelGen'
import { errorMessage } from '@/api/request'
import { NEW_ITEMS, aiFillable, applyValue, currentValues, fieldSchema, isTextField, scopesOverlap } from '@/novel-options/aiFill'
import { getOptionSchema } from '@/api/novelOptions'
import { EDITOR_KEY } from '@/novel-options/editor'
import { applyMaterial, applyPlanItem, resolveVersions } from '@/novel-options/materialApply'
import { useBlockedBooks } from '@/components/material/blockedBooks'
import { getMaterial, isMultiVersion, materialVariants, recordMaterialUse } from '@/api/material'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import { buildSpec, clone, initValues, isFilled, newGroupItem, specToJson, summarizeFields, syncBuiltinDescs, uid, upgradeConfig } from '@/novel-options/schema'

/**
 * 小说设定编辑器（原「小说创作」页），嵌在工作区中使用。
 * config：已保存的编辑器配置 {categories, values}，为空则使用默认选项结构。
 * novelId + ai：开启「AI 填写」（ai = {apiModel, localModels, adapters, model: 工作区的模型配置}）。
 * 通过 ref 调用 getConfig() / getSpec() 取出当前配置与规范化设定；任何改动触发 change 事件。
 */
const props = defineProps({
  config: { type: Object, default: null },
  novelId: { type: String, default: '' },
  ai: { type: Object, default: null },
  /** 分类导航由外面渲染（工作区书房的左栏，见 components/novel/study/SettingsNav.vue），这里只留内容卡片 */
  externalNav: { type: Boolean, default: false }
})
const emit = defineEmits(['change'])

const loading = ref(false)
const categories = ref([])
const templates = ref([])
const genericSuggestions = ref([])
/** 取值树：{ [categoryKey]: { [fieldKey]: value } } */
const values = reactive({})
const activeKey = ref('')
const editMode = ref(false)
const schemaVersion = ref(1)

const builtinCategories = computed(() => categories.value.filter((c) => !c.custom))
const customCategories = computed(() => categories.value.filter((c) => c.custom))
const activeCategory = computed(() => categories.value.find((c) => c.key === activeKey.value))

const spec = computed(() => buildSpec(categories.value, values))

function filledCount(cat) {
  return cat.fields.filter((f) => isFilled(f, values[cat.key])).length
}

/** 导航上的进度点：没填 / 填了一部分 / 填了大半 */
function progressOf(cat) {
  const n = filledCount(cat)
  if (!n) return 'empty'
  return n / Math.max(cat.fields.length, 1) >= 0.6 ? 'full' : 'part'
}

/* ---- 内容卡片：填过的字段只显示内容，点一下才展开成表单；空着的收进「还可以补充」 ---- */
const openFields = reactive(new Set())   // 正在编辑的字段 `分类.字段`
const fieldId = (field) => `${activeKey.value}.${field.key}`
const filled = (field) => isFilled(field, values[activeKey.value])
// 分组（角色卡、阶段表、背景卡…）本身就是可增删的列表：有内容就一直展开
const isOpen = (field) => openFields.has(fieldId(field)) || (field.type === 'group' && filled(field))
const shownFields = computed(() => (activeCategory.value?.fields || []).filter((f) => filled(f) || openFields.has(fieldId(f))))
const emptyFields = computed(() => (activeCategory.value?.fields || []).filter((f) => !filled(f) && !openFields.has(fieldId(f))))
// 长文本、分组、长句标签、带细分选项的选择项占满一行，其余两列排
const isWide = (field) => {
  if (['textarea', 'group'].includes(field.type)) return true
  // 标签里有长句（世界规则这种，显示成列表）也占满一行，半宽的列表右边空一大块
  if (field.type === 'tags' && (values[activeKey.value]?.[field.key] || []).some((t) => String(t).length > 14)) return true
  const picked = values[activeKey.value]?.[field.key]?.selected || []
  return (field.options || []).some((o) => o.children?.length && picked.includes(o.value))
}
const summaryOf = (field) => summarizeFields([field], values[activeKey.value])

// 分组（除了角色卡这种自带卡片视图的）一律用卡片网格；有内容的才算「填过」，空分组在「还可以补充」里
const isGroupGrid = (field) => field.type === 'group' && field.display !== 'characterCards' && isOpen(field)

/** 力量体系文本 → 阶梯：「1. 学徒：能做到…（突破：…）」这样的行是一级；其余行是简介 / 补充 */
const LADDER_LINE = /^\s*(\d+)[.、．)]\s*([^：:（(\n]{1,16})\s*[：:]?\s*(.*)$/
function ladderOf(field) {
  if (field.key !== 'powerSystem') return { steps: [] }
  const lines = String(values[activeKey.value]?.[field.key] || '').split('\n')
  const steps = []
  const intro = []
  const rest = []
  for (const line of lines) {
    const m = line.match(LADDER_LINE)
    if (m) steps.push({ name: m[2].trim(), desc: m[3].trim() })
    else if (line.trim() && !/^境界/.test(line.trim())) (steps.length ? rest : intro).push(line.trim())
  }
  return steps.length >= 2 ? { steps, intro: intro.join('\n'), rest: rest.join('\n') } : { steps: [] }
}

function openField(field) {
  openFields.add(fieldId(field))
}
function closeField(field) {
  openFields.delete(fieldId(field))
}

const previewVisible = ref(false)
function onMore(cmd) {
  if (cmd === 'picker') openPicker()
  else if (cmd === 'preview') previewVisible.value = true
  else if (cmd === 'json') jsonVisible.value = true
  else if (cmd === 'structure') editMode.value = !editMode.value
  else if (cmd === 'reset') resetAll()
}

let ready = false

async function loadSchema(useSaved = true) {
  ready = false
  loading.value = true
  try {
    const res = await getOptionSchema()
    if (res.code !== 0) {
      ElMessage.error(res.message || '加载选项失败')
      return
    }
    schemaVersion.value = res.data.schemaVersion || 1
    templates.value = res.data.elementTemplates
    genericSuggestions.value = res.data.genericSuggestions
    const saved = useSaved && props.config?.categories?.length
      ? syncBuiltinDescs(upgradeConfig(clone(props.config), res.data), res.data) : null
    categories.value = saved ? saved.categories : res.data.categories
    Object.keys(values).forEach((k) => delete values[k])
    categories.value.forEach((c) => (values[c.key] = saved?.values?.[c.key] || initValues(c.fields)))
    activeKey.value = categories.value[0]?.key || ''
  } finally {
    loading.value = false
    setTimeout(() => (ready = true))
  }
}

watch([categories, values], () => ready && emit('change'), { deep: true })

/** 给外部导航用：分类列表 / 当前分类 / 进度点 / 切换 / 新增元素（reactive 里的 computed 访问时自动解包） */
const nav = reactive({
  builtin: builtinCategories,
  custom: customCategories,
  activeKey,
  filledCount,
  progressOf,
  select: (key) => { activeKey.value = key },
  add: () => openCategoryEditor(null),
  // 书房的素材库栏（components/material/MaterialDock.vue）用：
  materialCategory: computed(() => {
    const cat = activeCategory.value
    return (cat && MATERIAL_OF[cat.custom ? cat.templateKey : cat.key]) || ''
  }),
  allCategories: categories,
  contextQuery: computed(() => contextQueryOf(activeCategory.value)),
  usedMaterialIds: computed(() => usedMaterialIds()),
  applyMaterials: (list) => onApplyMaterials(list)
})

/** 「按当前设定找相关素材」的检索文本：分类名 + 已填内容（拍平成一行行，≤300 字） */
function contextQueryOf(cat) {
  if (!cat) return ''
  const lines = []
  const walk = (nodes) => {
    for (const n of nodes) {
      if (n.type === 'groupItem') lines.push(n.name || '')
      else if (n.display) lines.push(`${n.label}：${n.display}`)
      if (n.children?.length) walk(n.children)
    }
  }
  walk(summarizeFields(cat.fields, values[cat.key]))
  return [cat.label, ...lines].filter(Boolean).join('\n').slice(0, 300)
}

/** 已经加进设定的素材 id（分组项上的 _fromMaterial，任意深度） */
function usedMaterialIds() {
  const ids = new Set()
  const walk = (v) => {
    if (Array.isArray(v)) v.forEach(walk)
    else if (v && typeof v === 'object') {
      if (v._fromMaterial != null) ids.add(v._fromMaterial)
      Object.values(v).forEach(walk)
    }
  }
  walk(values)
  return ids
}

defineExpose({
  nav,
  getConfig: () => clone({ schemaVersion: schemaVersion.value, categories: categories.value, values }),
  getSpec: () => clone(spec.value),
  // 灵感墙「写进工作区 → 加进设定」：思路里的元素当作素材应用（id 为空：不标「来自素材库」、不计使用次数）
  applyExternal: (list) => onApplyMaterials(list),
  // 自动规划「写进工作区」：按设定字段直接写（角色卡 / 元素 / 世界规则 / 阶段表 + 出场条件），返回 {done, failed}
  applyPlan: (list) => onApplyPlan(list)
})

function onApplyPlan(list) {
  const ctx = {
    categories: categories.value,
    values,
    createFromTemplate: (key) => {
      const t = templates.value.find((x) => x.key === key)
      return addCustomCategory({ label: t?.label || key, icon: t?.icon || 'Collection', desc: t?.desc || '', templateKey: key })
    }
  }
  const failed = []
  let done = 0
  for (const p of list) {
    try {
      applyPlanItem(p, ctx)
      done++
    } catch (e) {
      failed.push(`${p.fields?.name || p.kind}：${e.message}`)
    }
  }
  const used = [...new Set(list.flatMap((p) => p.sources || []).filter(Number.isInteger))]
  if (used.length) recordMaterialUse(used).catch(() => {})
  return { done, failed }
}

async function resetAll() {
  try {
    await ElMessageBox.confirm('将清空所有选择，并移除自定义元素和自定义选项项，确定重置？', '重置', {
      type: 'warning',
      confirmButtonText: '重置',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await loadSchema(false)
  emit('change')
}

/* ---------------- 编辑上下文：任意层级的字段 / 选项增删 ---------------- */
const fieldEditor = reactive({ visible: false, title: '', target: null, suggestions: [] })

function addField(target, { title, suggestions } = {}) {
  Object.assign(fieldEditor, {
    visible: true,
    title: title || '添加选项项',
    target,
    suggestions: suggestions ?? genericSuggestions.value
  })
}

function onFieldSave(field) {
  fieldEditor.target?.push(field)
  ElMessage.success(`已添加「${field.label}」`)
}

async function removeField(target, field) {
  try {
    await ElMessageBox.confirm(`删除选项项「${field.label}」及其已填写的内容？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  const i = target.indexOf(field)
  if (i >= 0) target.splice(i, 1)
}

function addOption(field, label) {
  const o = { value: uid('o'), label, custom: true }
  if (!field.options) field.options = []
  field.options.push(o)
  return o
}

function removeOption(field, value) {
  field.options = (field.options || []).filter((o) => o.value !== value)
}

/* ---------------- AI 填写：单个字段 / 分组新增若干项 / 整个分类的未填项 ---------------- */
const aiEnabled = computed(() => !!props.novelId && !!props.ai)
// 默认跟随工作区：本地工作区用它的基础模型 + 适配器，否则用大模型
const aiCfg = reactive({ source: 'api', baseId: '', adapterId: '', hint: '', picked: [], autoMaterials: false })
watch(() => props.ai?.model, (m) => {
  if (!m) return
  Object.assign(aiCfg, {
    source: m.source === 'local' || m.source === 'gguf' ? m.source : 'api',
    baseId: m.baseId || props.ai.localModels?.[0]?.id || '',
    adapterId: m.source === 'local' ? m.adapterId || '' : ''
  })
}, { immediate: true })
// 进行中的 AI 请求：标识 → 作用范围（位置路径）。本地模型 / GGUF 一次只能处理一个（显卡上一个模型、生成串行）；
// 大模型可以同时发多个，只锁住会写到同一处的按钮（范围互为前缀，见 aiFill.scopesOverlap）
const aiRunning = reactive(new Map())
const aiLoading = (key) => aiRunning.has(key)
function aiLocked(scope) {
  if (!aiRunning.size) return false
  if (aiSerial()) return true
  return [...aiRunning.values()].some((s) => scopesOverlap(s, scope))
}
// 屏蔽的来源书（按工作区记住，与「AI 构思」共用）：这些书的素材不参与 AI 填写（保留的素材除外）
const blockedBooks = useBlockedBooks(props.novelId)
const setBlockedBooks = (v) => (blockedBooks.value = v)

/** 模型 + 素材 + 屏蔽书：AI 填写 / 试聊 / 出主意共用的请求字段 */
function aiModelBody() {
  const local = aiCfg.source === 'local'
  return {
    source: aiCfg.source, baseId: local ? aiCfg.baseId : undefined, adapterId: local ? aiCfg.adapterId || null : undefined,
    materialIds: aiCfg.picked.map((m) => m.id), materialVariants: materialVariants(aiCfg.picked), excludeBooks: blockedBooks.value, spec: spec.value
  }
}

/** 本地模型和 GGUF（llama.cpp 只开一个并发槽）一次只处理一个 AI 请求 */
function aiSerial() {
  return aiCfg.source === 'local' || aiCfg.source === 'gguf'
}

function aiModelReady() {
  if (aiCfg.source === 'gguf') {
    if (!props.ai.llama) ElMessage.warning('llama.cpp 没有运行：请先到「llama.cpp」页启动 GGUF 模型，或在「AI 填写设置」里换模型')
    return !!props.ai.llama
  }
  if (aiCfg.source !== 'local' && !props.ai.apiModel) {
    ElMessage.warning('没有可用的大模型：请在「模型配置」中启用，或在「AI 填写设置」里改用本地模型')
    return false
  }
  if (aiCfg.source === 'local' && !aiCfg.baseId) {
    ElMessage.warning('请在「AI 填写设置」里选择本地模型')
    return false
  }
  return true
}

/** AI 请求前的检查：同一处 / 本地模型是否正忙、模型是否可用 */
function aiPreflight(busyKey, scope) {
  if (aiRunning.has(busyKey) || aiLocked(scope)) {
    ElMessage.warning(aiSerial() ? '本地模型 / GGUF 一次只能处理一个 AI 请求，请等上一个完成' : '这一处正在由 AI 生成，请稍候')
    return false
  }
  return aiModelReady()
}

/* ---- 每次 AI 生成 / 润色前必须先选素材（可以什么都不选）：「AI 填写设置」里的素材预先勾上，
       开着「自动匹配」时用本地向量模型按 query 检索并预勾选前几条 ---- */
const aiPicker = reactive({ visible: false, action: '', title: '', query: '', context: '', initial: [], auto: false })
let aiPickResolve = null

/** → 选中的素材数组（可为空 = 不用素材）；取消返回 null。
 *  action：动作名（生成 / 润色 / 创建 / 补全）；target：作用对象（显示在标题里）；query：向量检索预填内容（会加上补充要求）；
 *  initial：预选（默认「AI 填写设置」里选的素材） */
function pickMaterials({ action, target, query = '', initial = null }) {
  aiPickResolve?.(null)
  return new Promise((resolve) => {
    aiPickResolve = resolve
    Object.assign(aiPicker, {
      visible: true, action, title: `AI ${action}「${target}」：先选参考素材（可以不选）`, context: `设定 › ${target}`,
      query: [query, aiCfg.hint].map((s) => (s || '').trim()).filter(Boolean).join('；').slice(0, 500),
      initial: initial ?? aiCfg.picked, auto: aiCfg.autoMaterials
    })
  })
}
function onAiPicked(list) {
  const r = aiPickResolve
  aiPickResolve = null
  r?.(list)
}
function onAiPickCancel() {
  const r = aiPickResolve
  aiPickResolve = null
  r?.(null)
}

/** extraHint：本次额外的要求（如「一句话创建角色」的构想），放在补充要求前面；scope：会写到的位置（见 aiLocked）；
 *  pick：先弹素材选择（见 pickMaterials 的参数），取消则不请求；materials：已选好的素材（不再弹选择）。
 *  素材只用这次选的（不选 = 不用素材），不再自动匹配 */
async function aiCall(fill, busyKey, extraHint = '', scope = [], { pick = null, materials = null } = {}) {
  if (!aiPreflight(busyKey, scope)) return null
  let chosen = materials
  if (!chosen && pick) {
    chosen = await pickMaterials(pick)
    if (!chosen) return null
    if (!aiPreflight(busyKey, scope)) return null
  }
  const hint = [extraHint.trim(), aiCfg.hint.trim()].filter(Boolean).join('；').slice(0, 500)
  aiRunning.set(busyKey, scope)
  try {
    const res = await generateIdeas(props.novelId, {
      ...aiModelBody(), kind: 'fill', fill, hint, autoMaterials: false, materialIds: (chosen || []).map((m) => m.id),
      materialVariants: materialVariants(chosen)
    })
    if (res.code !== 0) throw new Error(res.message || 'AI 填写失败')
    return res.data.result
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, 'AI 填写失败'), duration: 8000 })
    return null
  } finally {
    aiRunning.delete(busyKey)
  }
}

const busyKeyOf = (path, field) => `${path.join('/')}|${field.key}`

/**
 * 填写单个字段；siblings：同一容器的字段，用来告诉模型已填的内容。
 * 文本类字段（action）：polish = AI 润色，保留框内已写内容并扩写；generate = AI 生成，框内文字只当大致方向（可空）。
 * 文本写入后可「撤销」；选择 / 标签字段已有内容时先确认覆盖。
 */
/**
 * 字段的 AI 填写。how = {direction, keep}（AiRegenButton 的四种方式：给不给方向 × 参考不参考已有内容），
 * 也兼容旧的 'polish' / 'generate'。文本：参考已有 = 在框内内容上润色扩写（+ 方向）；不参考 = 按方向重新写。
 * 标签：参考已有 = 保留已有的再补充；不参考 = 重新生成（覆盖前确认）。
 */
async function aiFillField(field, container, siblings, path, how = 'generate') {
  const opts = typeof how === 'string' ? { keep: how === 'polish', direction: '' } : { keep: !!how?.keep, direction: how?.direction || '' }
  const text = isTextField(field)
  const before = container[field.key]
  const boxText = text ? String(before ?? '').trim() : ''
  const action = text && opts.keep ? 'polish' : 'generate'
  if (action === 'polish' && !boxText) {
    ElMessage.warning('框里还没有内容，无法在已有内容上修改；可以先写几句，或者不勾「参考已有内容」')
    return
  }
  if (!text && !opts.keep && isFilled(field, container)) {
    try {
      await ElMessageBox.confirm(`「${field.label}」已有内容，用 AI 重新生成的内容覆盖？（想保留已有的，勾「参考已有内容」）`, 'AI 填写', { type: 'warning' })
    } catch {
      return
    }
  }
  const label = opts.keep ? '修改' : '生成'
  // 文本：polish 的 seed = 框内内容，direction 另给；generate 的 seed = 方向（旧的「生成」把框内文字当方向）
  const seed = text ? (action === 'polish' ? boxText : opts.direction || (typeof how === 'string' ? boxText : '')) : ''
  const r = await aiCall({
    mode: 'field', path, fields: [fieldSchema(field)], current: currentValues(siblings, container, field.key),
    ...(text ? { action, seed } : {}),
    direction: opts.direction, keep: opts.keep, ...(!text && opts.keep ? { keepValue: before } : {})
  }, `${busyKeyOf(path, field)}|ai`, '', [...path, field.label],
  { pick: { action: label, target: [...path, field.label].join(' › '), query: [...path, field.label, opts.direction || boxText].filter(Boolean).join(' ') } })
  if (!r) return
  const value = r.values?.[field.key]
  // 标签参考已有：模型只给新补充的，接在已有的后面（去重）
  const merged = !text && opts.keep && field.type === 'tags' && Array.isArray(before)
    ? [...new Set([...before, ...(Array.isArray(value) ? value : String(value ?? '').split(/[、，,]/)).map((v) => String(v).trim()).filter(Boolean)])]
    : value
  if (!applyValue(field, container, merged, addOption)) {
    ElMessage.warning('模型没有给出这个字段的内容，请重试')
    return
  }
  if (!text) {
    ElMessage.success(`AI 已填写「${field.label}」`)
    return
  }
  // 文本：给一个「撤销」，恢复成 AI 写入前的内容
  const n = ElNotification({
    type: 'success',
    title: `AI 已${label}「${field.label}」`,
    duration: 8000,
    message: h('span', ['可以继续修改，或 ', h('a', {
      style: 'cursor: pointer; color: var(--el-color-primary)',
      onClick: () => {
        container[field.key] = before
        n.close()
      }
    }, '撤销')])
  })
}

/**
 * 选择类字段「自定义」里的 AI：polish = 把框里写的整理成一个选项；generate = 按框里的方向 / 选的素材设计新选项。
 * 先弹素材选择（预选这个自定义框上次选的素材）。返回 {option: {label, desc} 草稿, materials: 这次选的}；取消 / 失败返回 null
 * （选了素材但请求失败时 option 为 null）。
 */
async function aiCustomOption(field, { action, seed, materials, path, container, siblings }) {
  const busyKey = `${busyKeyOf(path, field)}|option`
  const scope = [...path, field.label]
  if (!aiPreflight(busyKey, scope)) return null
  const target = [...path, field.label, '自定义选项'].join(' › ')
  const chosen = await pickMaterials({ action: action === 'polish' ? '润色' : '生成', target, query: [...scope, seed].filter(Boolean).join(' '), initial: materials })
  if (!chosen) return null
  if (!seed && !chosen.length) {
    ElMessage.warning('自定义框里没有内容时，需要至少选一条素材')
    return { option: null, materials: chosen }
  }
  const r = await aiCall({
    mode: 'option', path, fields: [fieldSchema(field)], action, seed,
    current: siblings ? currentValues(siblings, container, field.key) : {}
  }, busyKey, '', scope, { materials: chosen })
  return { option: r?.option || null, materials: chosen }
}

/** 分组新增 count 项（如关键情节节点、角色），每项的文本 / 标签 / 选择字段都由 AI 填写；
 *  concept：一句话构想（如「嘴硬心软的女剑客，主角的宿敌」），按它来设计 */
async function aiGenItems(field, list, path, count, concept = '') {
  const fields = (field.fields || []).filter(aiFillable)
  if (!fields.length) {
    ElMessage.warning(`「${field.label}」的字段都不能由 AI 填写`)
    return
  }
  const nameField = (field.fields || []).find((f) => f.type === 'text')
  const label = field.itemLabel || '项'
  const r = await aiCall({
    mode: 'items', path: [...path, field.label], itemLabel: label, count, fields: fields.map(fieldSchema),
    existing: nameField ? list.map((it) => it[nameField.key]).filter(Boolean) : []
  }, busyKeyOf(path, field), concept ? `${label}构想：${concept}` : '', [...path, field.label, NEW_ITEMS],
  { pick: { action: concept ? '创建' : `生成 ${count} 个${label}`, target: [...path, field.label].join(' › '), query: [...path, field.label, concept].filter(Boolean).join(' ') } })
  if (!r) return []
  const added = []
  for (const it of r.items || []) {
    const item = newGroupItem(field)
    fields.forEach((f) => applyValue(f, item, it[f.key], addOption))
    list.push(item)
    added.push(item)
  }
  ElMessage.success(`AI 新增了 ${added.length} 个${label}，可继续修改`)
  return added
}

/** 补全分组中某一项（如某个角色）还没填的文本 / 标签 / 选择字段 */
async function aiFillItem(field, item, path) {
  const targets = (field.fields || []).filter((f) => aiFillable(f) && !isFilled(f, item))
  if (!targets.length) {
    ElMessage.info('这一项能由 AI 填写的字段都已填写')
    return
  }
  const r = await aiCall({ mode: 'category', path, fields: targets.map(fieldSchema), current: currentValues(field.fields, item) },
    `item:${item._id}`, '', path, { pick: { action: '补全', target: path.join(' › '), query: path.join(' ') } })
  if (!r) return
  const filled = targets.filter((f) => applyValue(f, item, r.values?.[f.key], addOption))
  ElMessage.success(`AI 补全了 ${filled.length} 项：${filled.map((f) => f.label).join('、') || '无'}`)
}

/**
 * 角色试聊（character.ai 式）：character = {name, card: {字段名: 展示值}}，messages = [{role: user|assistant, content}]。
 * 返回角色的回复文本；失败返回 null。试聊有自己的忙碌状态，不占用 AI 填写。
 */
async function aiChat(character, messages, { scene = '', userRole = '' } = {}) {
  if (!aiModelReady()) return null
  try {
    const res = await generateIdeas(props.novelId, {
      ...aiModelBody(), materialIds: [], kind: 'chat', chat: { character, messages, scene, userRole }
    })
    if (res.code !== 0) throw new Error(res.message || '试聊失败')
    return res.data.result.reply
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '试聊失败'), duration: 8000 })
    return null
  }
}

/** 「AI 填写设置」里的补充要求：让 AI 给几个方向（已有内容时在其基础上细化） */
async function aiSuggestHints(current) {
  if (!aiModelReady()) return []
  try {
    const res = await generateIdeas(props.novelId, {
      ...aiModelBody(), kind: 'direction', hint: (current || '').trim(), count: 5, purpose: '补全小说设定（世界观 / 角色 / 情节）时的补充要求'
    })
    if (res.code !== 0) throw new Error(res.message || 'AI 生成失败')
    return res.data.result.directions || []
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, 'AI 生成失败'), duration: 8000 })
    return []
  }
}

/** 补全分类中还没填写的文本 / 标签 / 选择字段 */
async function fillCategory(cat) {
  const container = values[cat.key]
  const targets = cat.fields.filter((f) => aiFillable(f) && !isFilled(f, container))
  if (!targets.length) {
    ElMessage.info('本分类能由 AI 填写的项都已填写（分组请用各自的「AI 生成」，数字 / 滑块请自己设置）')
    return
  }
  const r = await aiCall({ mode: 'category', path: [cat.label], fields: targets.map(fieldSchema), current: currentValues(cat.fields, container) },
    `cat:${cat.key}`, '', [cat.label], { pick: { action: '补全', target: cat.label, query: `${cat.label} ${targets.map((f) => f.label).join(' ')}` } })
  if (!r) return
  const filled = targets.filter((f) => applyValue(f, container, r.values?.[f.key], addOption))
  ElMessage.success(`AI 填写了 ${filled.length} 项：${filled.map((f) => f.label).join('、') || '无'}`)
}

provide(EDITOR_KEY, {
  editMode, addField, removeField, addOption, removeOption,
  ai: {
    enabled: aiEnabled, loading: aiLoading, locked: aiLocked, busyKeyOf, fillField: aiFillField, customOption: aiCustomOption,
    excludeBooks: blockedBooks, genItems: aiGenItems, fillItem: aiFillItem,
    chat: aiChat, cfg: aiCfg, apiModel: computed(() => props.ai?.apiModel),
    novelId: computed(() => props.novelId)
  }
})

function addCategoryField() {
  const cat = activeCategory.value
  addField(cat.fields, { title: `为「${cat.label}」添加选项项`, suggestions: cat.suggestions || genericSuggestions.value })
}

/* ---------------- 自定义元素（分类） ---------------- */
const categoryEditor = reactive({ visible: false, editing: null })

function openCategoryEditor(cat) {
  Object.assign(categoryEditor, { visible: true, editing: cat })
}

function onCategorySave({ label, icon, desc, templateKey }) {
  if (categoryEditor.editing) {
    Object.assign(categoryEditor.editing, { label, icon, desc })
    return
  }
  const cat = addCustomCategory({ label, icon, desc, templateKey })
  activeKey.value = cat.key
  ElMessage.success(`已添加自定义元素「${label}」`)
}

/** 新建自定义元素（可基于模板），返回响应式分类对象 */
function addCustomCategory({ label, icon, desc, templateKey }) {
  const t = templates.value.find((x) => x.key === templateKey)
  categories.value.push({
    key: uid('cat'),
    label,
    icon,
    desc,
    custom: true,
    templateKey: templateKey || null,
    fields: t ? clone(t.fields) : [],
    // 模板推荐 + 通用推荐（按名称去重）
    suggestions: [...(t?.suggestions || []), ...genericSuggestions.value].filter(
      (s, i, arr) => arr.findIndex((x) => x.label === s.label) === i
    )
  })
  const cat = categories.value[categories.value.length - 1]
  values[cat.key] = initValues(cat.fields)
  return cat
}

/* ---------------- 素材库：选择素材并应用到当前设定 ---------------- */
const picker = reactive({ visible: false, category: '' })
// 当前设定分类 → 素材分类（用于打开素材库时预选）
const MATERIAL_OF = { world: 'world', characters: 'character', plot: 'plot', monster: 'monster', faction: 'faction', location: 'location', item: 'item', skill: 'item' }

function openPicker() {
  const cat = activeCategory.value
  picker.category = (cat && MATERIAL_OF[cat.custom ? cat.templateKey : cat.key]) || ''
  picker.visible = true
}

async function onApplyMaterials(list) {
  const ctx = {
    categories: categories.value,
    values,
    createFromTemplate: (key) => {
      const t = templates.value.find((x) => x.key === key)
      return addCustomCategory({ label: t?.label || key, icon: t?.icon || 'Collection', desc: t?.desc || '', templateKey: key })
    }
  }
  const done = []
  const failed = []
  let lastKey = ''
  for (const m of list) {
    try {
      // 多版本素材：取详情拿到各版本的成员，按选的用法展开
      let material = m
      if (isMultiVersion(m)) {
        const res = await getMaterial(m.id)
        material = resolveVersions(m, res.code === 0 ? res.data.members || [] : [])
      }
      lastKey = applyMaterial(material, ctx).categoryKey
      done.push(m.id)
    } catch (e) {
      failed.push(`${m.title}：${e.message}`)
    }
  }
  if (lastKey) activeKey.value = lastKey
  if (done.length) {
    ElMessage.success(`已应用 ${done.length} 条素材（可在对应分类中继续修改）`)
    const used = done.filter((id) => Number.isInteger(id))
    if (used.length) recordMaterialUse(used).catch(() => {})
  }
  if (failed.length) ElMessage.error({ message: failed.join('；'), duration: 6000 })
}

async function removeCategory(cat) {
  try {
    await ElMessageBox.confirm(`删除自定义元素「${cat.label}」及其所有设定？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  categories.value = categories.value.filter((c) => c.key !== cat.key)
  delete values[cat.key]
  activeKey.value = categories.value[0]?.key || ''
}

/* ---------------- JSON 导出 ---------------- */
const jsonVisible = ref(false)
const jsonMode = ref('spec')
const jsonText = computed(() =>
  JSON.stringify(
    jsonMode.value === 'spec' ? specToJson(spec.value) : { categories: categories.value, values },
    null,
    2
  )
)

async function copyJson() {
  try {
    await navigator.clipboard.writeText(jsonText.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

onMounted(() => loadSchema(true))
</script>

<style scoped>
/* 设定页的几个设计变量（之后整个工作区统一时再提到外层） */
.settings-editor {
  /* 取全站墨色主题的 --ws-*（styles/ink-theme.css），括号里是兜底值 */
  --se-ink: var(--ws-ink, #303133);
  --se-sub: var(--ws-sub, #909399);
  --se-line: var(--ws-line, #e8e9ed);
  --se-card: var(--ws-card, #fff);
  --se-soft: var(--ws-soft, #f7f8fa);
  --se-radius: var(--ws-radius, 10px);
}
.box-card {
  border: 1px solid var(--se-line);
  border-radius: var(--se-radius);
  box-shadow: none;
}
.page-header,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.page-header {
  margin-bottom: 12px;
}
.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 13px;
}
.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--se-ink);
}
.hint-icon {
  color: var(--se-sub);
  cursor: help;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.muted {
  font-size: 12px;
  color: var(--se-sub);
}

.create-body {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.create-body.is-external-nav {
  grid-template-columns: minmax(0, 1fr);
}

/* 导航 */
.nav-card {
  position: sticky;
  top: 12px;
}
.nav-card :deep(.el-card__body) {
  padding: 12px 8px;
}
.nav-group-title {
  margin: 4px 8px 6px;
  font-size: 12px;
  color: var(--se-sub);
}
.nav-group-title:not(:first-child) {
  margin-top: 16px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  font-size: 14px;
  color: var(--se-ink);
  border-radius: 8px;
  cursor: pointer;
}
.nav-item:hover {
  background: var(--se-soft);
}
.nav-item.is-active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}
.nav-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nav-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1.5px solid var(--el-color-primary);
}
.nav-dot.is-empty {
  border-color: var(--el-border-color-darker);
}
.nav-dot.is-part {
  background: linear-gradient(90deg, var(--el-color-primary) 50%, transparent 50%);
}
.nav-dot.is-full {
  background: var(--el-color-primary);
}
.nav-add {
  width: 100%;
  margin-top: 8px;
}
.nav-tip {
  margin: 8px 4px 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--se-sub);
}

/* 主区域 */
.cat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--se-line);
}
.cat-icon {
  font-size: 24px;
  color: var(--el-color-primary);
}
.cat-title-wrap {
  flex: 1;
}
.cat-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--se-ink);
}
.cat-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--se-sub);
}
.add-field-btn {
  margin-top: 12px;
}

/* 内容卡片 */
.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-flow: row dense;
  gap: 12px;
}
.field-card {
  min-width: 0;
  padding: 12px 14px;
  background: var(--se-card);
  border: 1px solid var(--se-line);
  border-radius: var(--se-radius);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.field-card.wide {
  grid-column: 1 / -1;
}
.field-card.is-reading {
  cursor: pointer;
}
.field-card.is-reading:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}
.field-card.is-editing {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 0 0 3px var(--el-color-primary-light-9);
}
.field-card.is-editing :deep(.option-field) {
  padding: 0;
}
.fc-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.fc-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--se-sub);
}
.fc-edit {
  margin-left: auto;
  color: var(--se-sub);
  opacity: 0;
  transition: opacity 0.15s;
}
.field-card.is-reading:hover .fc-edit {
  opacity: 1;
}
.card-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}
.more-fields {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--se-line);
}
.more-fields .el-button + .el-button {
  margin-left: 0;
}
.more-label {
  font-size: 13px;
  color: var(--se-sub);
}

.field-card.is-group {
  cursor: default;
}
.ladder-intro {
  font-size: 13px;
  line-height: 1.7;
  color: var(--se-ink);
  white-space: pre-wrap;
}
.ladder {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 8px 0;
}
.ladder-step {
  padding: 4px 10px;
  font-size: 13px;
  color: var(--se-ink);
  /* 越往上越深：颜色随等级加深 */
  background: color-mix(in srgb, var(--el-color-primary) calc(8% + var(--lv) * 30%), #fff);
  border-radius: 999px;
  cursor: default;
}
.ladder-arrow {
  color: var(--se-sub);
}
.rule-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--se-ink);
}
.rule-list li::marker {
  color: var(--el-color-primary);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  padding: 2px 10px;
  font-size: 13px;
  color: var(--se-ink);
  background: var(--se-soft);
  border: 1px solid var(--se-line);
  border-radius: 999px;
}

/* AI 看到的设定（抽屉） */
.drawer-hint {
  margin-bottom: 12px;
}
.preview-cat + .preview-cat {
  margin-top: 14px;
}
.preview-cat-title {
  margin-bottom: 4px;
  font-weight: 600;
  color: var(--el-color-primary);
  cursor: pointer;
}
.json-mode {
  margin-bottom: 6px;
}
.json-hint {
  margin: 4px 0 8px;
  font-size: 12px;
  color: var(--se-sub);
}
.json-box {
  max-height: 55vh;
  margin: 0;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  background: var(--se-soft);
  border: 1px solid var(--se-line);
  border-radius: 6px;
}

@media (max-width: 1100px) {
  .create-body {
    grid-template-columns: 1fr;
  }
  .nav-card {
    position: static;
  }
  .field-grid {
    grid-template-columns: 1fr;
  }
}
</style>
