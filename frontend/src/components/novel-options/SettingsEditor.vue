<template>
  <div class="settings-editor">
    <div class="page-header">
      <span class="header-hint">只有你选择 / 填写 / 调整过的内容才会作为生成约束；标注「默认，未确认」的值不会写进提示词</span>
      <div class="header-actions">
        <span class="edit-switch">
          编辑模式
          <el-switch v-model="editMode" />
        </span>
        <AiFillSettings
          v-if="aiEnabled"
          :cfg="aiCfg"
          :api-model="ai.apiModel"
          :local-models="ai.localModels"
          :adapters="ai.adapters"
          :blocked-books="blockedBooks"
          :suggest="aiSuggestHints"
          @update:blocked-books="setBlockedBooks"
        />
        <el-button :icon="Collection" @click="openPicker">从素材库添加</el-button>
        <el-button :icon="RefreshLeft" @click="resetAll">重置设定</el-button>
        <slot name="actions" />
      </div>
    </div>

    <div v-loading="loading" class="create-body">
      <!-- 分类导航 -->
      <el-card class="box-card nav-card" shadow="never">
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
          <span class="nav-count">{{ filledCount(cat) }}/{{ cat.fields.length }}</span>
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
          <span class="nav-count">{{ filledCount(cat) }}/{{ cat.fields.length }}</span>
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

        <OptionField
          v-for="field in activeCategory.fields"
          :key="`${activeCategory.key}:${field.key}`"
          :field="field"
          :container="values[activeCategory.key]"
          :siblings="activeCategory.fields"
          :path="[activeCategory.label]"
        />

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

      <!-- 设定预览 -->
      <el-card class="box-card preview-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span class="card-title">设定预览</span>
            <div>
              <el-button link type="primary" :disabled="!spec.length" @click="jsonVisible = true">查看 JSON</el-button>
            </div>
          </div>
        </template>
        <el-empty v-if="!spec.length" description="还没有选择任何设定" :image-size="80" />
        <div v-for="c in spec" :key="c.key" class="preview-cat">
          <div class="preview-cat-title" @click="activeKey = c.key">{{ c.label }}</div>
          <SpecTree :items="c.items" root />
        </div>
      </el-card>
    </div>

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
import { Collection, CopyDocument, Delete, Edit, MagicStick, Plus, RefreshLeft } from '@element-plus/icons-vue'
import OptionField from './OptionField.vue'
import FieldEditor from './FieldEditor.vue'
import CategoryEditor from './CategoryEditor.vue'
import SpecTree from './SpecTree.vue'
import AiFillSettings from './AiFillSettings.vue'
import { generateIdeas } from '@/api/novelGen'
import { errorMessage } from '@/api/request'
import { NEW_ITEMS, aiFillable, applyValue, currentValues, fieldSchema, isTextField, scopesOverlap } from '@/novel-options/aiFill'
import { getOptionSchema } from '@/api/novelOptions'
import { EDITOR_KEY } from '@/novel-options/editor'
import { applyMaterial } from '@/novel-options/materialApply'
import { useBlockedBooks } from '@/components/material/blockedBooks'
import { recordMaterialUse } from '@/api/material'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import { buildSpec, clone, initValues, isFilled, newGroupItem, specToJson, uid, upgradeConfig } from '@/novel-options/schema'

/**
 * 小说设定编辑器（原「小说创作」页），嵌在工作区中使用。
 * config：已保存的编辑器配置 {categories, values}，为空则使用默认选项结构。
 * novelId + ai：开启「AI 填写」（ai = {apiModel, localModels, adapters, model: 工作区的模型配置}）。
 * 通过 ref 调用 getConfig() / getSpec() 取出当前配置与规范化设定；任何改动触发 change 事件。
 */
const props = defineProps({
  config: { type: Object, default: null },
  novelId: { type: String, default: '' },
  ai: { type: Object, default: null }
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
    const saved = useSaved && props.config?.categories?.length ? upgradeConfig(clone(props.config), res.data) : null
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

defineExpose({
  getConfig: () => clone({ schemaVersion: schemaVersion.value, categories: categories.value, values }),
  getSpec: () => clone(spec.value)
})

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
    source: m.source === 'local' ? 'local' : 'api',
    baseId: m.baseId || props.ai.localModels?.[0]?.id || '',
    adapterId: m.source === 'local' ? m.adapterId || '' : ''
  })
}, { immediate: true })
// 进行中的 AI 请求：标识 → 作用范围（位置路径）。本地模型一次只能处理一个（显卡上一个模型、生成串行）；
// 大模型可以同时发多个，只锁住会写到同一处的按钮（范围互为前缀，见 aiFill.scopesOverlap）
const aiRunning = reactive(new Map())
const aiLoading = (key) => aiRunning.has(key)
function aiLocked(scope) {
  if (!aiRunning.size) return false
  if (aiCfg.source === 'local') return true
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
    materialIds: aiCfg.picked.map((m) => m.id), excludeBooks: blockedBooks.value, spec: spec.value
  }
}

function aiModelReady() {
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

/** extraHint：本次额外的要求（如「一句话创建角色」的构想），放在补充要求前面；scope：会写到的位置（见 aiLocked） */
async function aiCall(fill, busyKey, extraHint = '', scope = []) {
  if (aiRunning.has(busyKey) || aiLocked(scope)) {
    ElMessage.warning(aiCfg.source === 'local' ? '本地模型一次只能处理一个 AI 请求，请等上一个完成' : '这一处正在由 AI 生成，请稍候')
    return null
  }
  if (!aiModelReady()) return null
  const hint = [extraHint.trim(), aiCfg.hint.trim()].filter(Boolean).join('；').slice(0, 500)
  if (aiCfg.autoMaterials && !hint) {
    ElMessage.warning('自动匹配素材需要在「AI 填写设置」里填写补充要求')
    return null
  }
  aiRunning.set(busyKey, scope)
  try {
    const res = await generateIdeas(props.novelId, {
      ...aiModelBody(), kind: 'fill', fill, hint, autoMaterials: aiCfg.autoMaterials
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
async function aiFillField(field, container, siblings, path, action = 'generate') {
  const text = isTextField(field)
  const before = container[field.key]
  const seed = text ? String(before ?? '').trim() : ''
  if (action === 'polish' && !seed) {
    ElMessage.warning('框里还没有内容，无法润色；可以先写几句，或用「AI 生成」')
    return
  }
  if (!text && isFilled(field, container)) {
    try {
      await ElMessageBox.confirm(`「${field.label}」已有内容，用 AI 生成的内容覆盖？`, 'AI 填写', { type: 'warning' })
    } catch {
      return
    }
  }
  const r = await aiCall({
    mode: 'field', path, fields: [fieldSchema(field)], current: currentValues(siblings, container, field.key),
    ...(text ? { action, seed } : {})
  }, `${busyKeyOf(path, field)}|${action}`, '', [...path, field.label])
  if (!r) return
  if (!applyValue(field, container, r.values?.[field.key], addOption)) {
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
    title: `AI 已${action === 'polish' ? '润色' : '生成'}「${field.label}」`,
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
  }, busyKeyOf(path, field), concept ? `${label}构想：${concept}` : '', [...path, field.label, NEW_ITEMS])
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
    `item:${item._id}`, '', path)
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
    `cat:${cat.key}`, '', [cat.label])
  if (!r) return
  const filled = targets.filter((f) => applyValue(f, container, r.values?.[f.key], addOption))
  ElMessage.success(`AI 填写了 ${filled.length} 项：${filled.map((f) => f.label).join('、') || '无'}`)
}

provide(EDITOR_KEY, {
  editMode, addField, removeField, addOption, removeOption,
  ai: {
    enabled: aiEnabled, loading: aiLoading, locked: aiLocked, busyKeyOf, fillField: aiFillField, genItems: aiGenItems, fillItem: aiFillItem,
    chat: aiChat, cfg: aiCfg, apiModel: computed(() => props.ai?.apiModel)
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

function onApplyMaterials(list) {
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
      lastKey = applyMaterial(m, ctx).categoryKey
      done.push(m.id)
    } catch (e) {
      failed.push(`${m.title}：${e.message}`)
    }
  }
  if (lastKey) activeKey.value = lastKey
  if (done.length) {
    ElMessage.success(`已应用 ${done.length} 条素材（可在对应分类中继续修改）`)
    recordMaterialUse(done).catch(() => {})
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
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.page-header {
  margin-bottom: 12px;
}
.page-header,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.header-hint {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.edit-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
}

.create-body {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}

/* 导航 */
.nav-card :deep(.el-card__body) {
  padding: 12px 10px;
}
.nav-group-title {
  margin: 6px 6px 6px;
  font-size: 12px;
  color: #909399;
}
.nav-group-title:not(:first-child) {
  margin-top: 16px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  font-size: 14px;
  color: #303133;
  border-radius: 6px;
  cursor: pointer;
}
.nav-item:hover {
  background: #f5f7fa;
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
.nav-count {
  font-size: 12px;
  font-weight: normal;
  color: #909399;
}
.nav-add {
  width: 100%;
  margin-top: 8px;
}
.nav-tip {
  margin: 8px 4px 0;
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}

/* 主区域 */
.cat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: 4px;
  border-bottom: 1px solid #ebeef5;
}
.cat-icon {
  font-size: 26px;
  color: var(--el-color-primary);
}
.cat-title-wrap {
  flex: 1;
}
.cat-title {
  font-size: 17px;
  font-weight: 600;
  color: #303133;
}
.cat-desc {
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
}
.add-field-btn {
  margin-top: 12px;
}

/* 预览 */
.preview-card {
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 32px);
  overflow: auto;
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
  color: #909399;
}
.json-box {
  max-height: 55vh;
  margin: 0;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  background: #f7f8fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}

@media (max-width: 1200px) {
  .create-body {
    grid-template-columns: 180px minmax(0, 1fr);
  }
  .preview-card {
    grid-column: 1 / -1;
    position: static;
    max-height: none;
  }
}
</style>
