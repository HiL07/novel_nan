<template>
  <div class="settings-editor">
    <div class="page-header">
      <span class="header-hint">只有你选择 / 填写 / 调整过的内容才会作为生成约束；标注「默认，未确认」的值不会写进提示词</span>
      <div class="header-actions">
        <span class="edit-switch">
          编辑模式
          <el-switch v-model="editMode" />
        </span>
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
import { computed, onMounted, provide, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, CopyDocument, Delete, Edit, Plus, RefreshLeft } from '@element-plus/icons-vue'
import OptionField from './OptionField.vue'
import FieldEditor from './FieldEditor.vue'
import CategoryEditor from './CategoryEditor.vue'
import SpecTree from './SpecTree.vue'
import { getOptionSchema } from '@/api/novelOptions'
import { EDITOR_KEY } from '@/novel-options/editor'
import { applyMaterial } from '@/novel-options/materialApply'
import { recordMaterialUse } from '@/api/material'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import { buildSpec, clone, initValues, isFilled, specToJson, uid } from '@/novel-options/schema'

/**
 * 小说设定编辑器（原「小说创作」页），嵌在工作区中使用。
 * config：已保存的编辑器配置 {categories, values}，为空则使用默认选项结构。
 * 通过 ref 调用 getConfig() / getSpec() 取出当前配置与规范化设定；任何改动触发 change 事件。
 */
const props = defineProps({
  config: { type: Object, default: null }
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
    templates.value = res.data.elementTemplates
    genericSuggestions.value = res.data.genericSuggestions
    const saved = useSaved && props.config?.categories?.length ? clone(props.config) : null
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
  getConfig: () => clone({ categories: categories.value, values }),
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

provide(EDITOR_KEY, { editMode, addField, removeField, addOption, removeOption })

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
