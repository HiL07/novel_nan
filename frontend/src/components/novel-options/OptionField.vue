<template>
  <div class="option-field" :class="`depth-${Math.min(depth, 3)}`">
    <div class="field-head">
      <span class="field-label">{{ field.label }}</span>
      <el-tag v-if="editMode" size="small" type="info" effect="plain">{{ typeLabel }}</el-tag>
      <el-tag v-if="field.custom" size="small" type="warning" effect="plain">自定义</el-tag>
      <span v-if="field.desc" class="field-desc">{{ field.desc }}</span>
      <el-button
        v-if="editMode && siblings"
        class="field-remove"
        link
        type="danger"
        size="small"
        :icon="Delete"
        @click="removeField(siblings, field)"
      >
        删除此项
      </el-button>
    </div>

    <!-- 选择类：选项 + 选中项的细分选项 -->
    <template v-if="choice">
      <ChoiceWidget :field="field" :value="value" />
      <div v-for="o in expandedOptions" :key="o.value" class="sub-block">
        <div class="sub-title">「{{ o.label }}」的细分选项</div>
        <OptionField
          v-for="child in o.children || []"
          :key="child.key"
          :field="child"
          :container="subContainer(o)"
          :siblings="o.children"
          :depth="depth + 1"
        />
        <el-button v-if="editMode" class="add-btn" size="small" :icon="Plus" @click="addSubField(o)">
          为「{{ o.label }}」添加细分选项
        </el-button>
      </div>
    </template>

    <!-- 可重复分组：如角色列表、怪物列表 -->
    <template v-else-if="field.type === 'group'">
      <div v-for="(item, i) in value" :key="item._id" class="group-item">
        <div class="group-item-head">
          <span>
            {{ field.itemLabel || '项' }} {{ i + 1 }}<template v-if="itemName(item)">：{{ itemName(item) }}</template>
            <el-tag v-if="item._fromMaterial" size="small" type="success" effect="plain" class="from-material">来自素材库</el-tag>
          </span>
          <div>
            <el-button link size="small" :icon="CopyDocument" @click="duplicateItem(i)">复制</el-button>
            <el-button link type="danger" size="small" :icon="Delete" @click="value.splice(i, 1)">删除</el-button>
          </div>
        </div>
        <OptionField
          v-for="child in field.fields || []"
          :key="child.key"
          :field="child"
          :container="item"
          :siblings="field.fields"
          :depth="depth + 1"
        />
      </div>
      <div class="group-actions">
        <el-button size="small" type="primary" plain :icon="Plus" @click="value.push(newGroupItem(field))">
          添加{{ field.itemLabel || '项' }}
        </el-button>
        <el-button v-if="editMode" size="small" :icon="Plus" @click="addGroupField">
          为每个{{ field.itemLabel || '项' }}添加字段
        </el-button>
      </div>
    </template>

    <!-- 其他：文本 / 数字 / 滑块 / 标签 -->
    <InputWidget v-else :field="field" :container="container" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { CopyDocument, Delete, Plus } from '@element-plus/icons-vue'
import ChoiceWidget from './ChoiceWidget.vue'
import InputWidget from './InputWidget.vue'
import { FIELD_TYPES, isChoice } from '@/novel-options/fieldTypes'
import { clone, ensureValue, newGroupItem, uid } from '@/novel-options/schema'
import { useOptionEditor } from '@/novel-options/editor'

/**
 * 递归渲染一个选项项。
 * container：本字段所在的取值容器（响应式对象），本字段的值为 container[field.key]
 * siblings：本字段所在的字段数组（编辑模式下用于删除）
 */
const props = defineProps({
  field: { type: Object, required: true },
  container: { type: Object, required: true },
  siblings: { type: Array, default: null },
  depth: { type: Number, default: 0 }
})

const { editMode, addField, removeField } = useOptionEditor()

ensureValue(props.container, props.field)
const value = computed(() => ensureValue(props.container, props.field))
const choice = computed(() => isChoice(props.field))
const typeLabel = computed(() => FIELD_TYPES[props.field.type]?.label || props.field.type)

/** 选中的、且有细分选项（或处于编辑模式可添加细分）的选项 */
const expandedOptions = computed(() =>
  (props.field.options || []).filter(
    (o) => value.value.selected.includes(o.value) && (o.children?.length || editMode.value)
  )
)

function subContainer(o) {
  const sub = value.value.sub
  if (!sub[o.value]) sub[o.value] = {}
  return sub[o.value]
}

function addSubField(o) {
  if (!o.children) o.children = []
  addField(o.children, { title: `为「${o.label}」添加细分选项` })
}

function addGroupField() {
  if (!props.field.fields) props.field.fields = []
  addField(props.field.fields, { title: `为每个${props.field.itemLabel || '项'}添加字段` })
}

function itemName(item) {
  const nameField = (props.field.fields || []).find((f) => f.type === 'text')
  return nameField ? item[nameField.key] : ''
}

function duplicateItem(i) {
  const copy = clone(value.value[i])
  copy._id = uid('item')
  value.value.splice(i + 1, 0, copy)
}
</script>

<style scoped>
.option-field {
  padding: 12px 0;
}
.option-field + .option-field {
  border-top: 1px dashed #ebeef5;
}
.field-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.field-label {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.depth-1 .field-label,
.depth-2 .field-label,
.depth-3 .field-label {
  font-size: 13px;
}
.field-desc {
  font-size: 12px;
  color: #909399;
}
.field-remove {
  margin-left: auto;
}
.sub-block {
  margin-top: 12px;
  padding: 4px 14px 8px;
  background: #f8faff;
  border-left: 3px solid var(--el-color-primary-light-5);
  border-radius: 0 6px 6px 0;
}
.sub-title {
  padding-top: 8px;
  font-size: 12px;
  color: var(--el-color-primary);
}
.group-item {
  margin-bottom: 12px;
  padding: 0 14px 4px;
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.group-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  border-bottom: 1px solid #ebeef5;
}
.from-material {
  margin-left: 6px;
}
.group-actions,
.add-btn {
  margin-top: 8px;
}
</style>
