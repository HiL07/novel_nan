<template>
  <div class="choice-widget">
    <el-tooltip
      v-for="o in field.options || []"
      :key="o.value"
      :content="o.desc"
      :disabled="!o.desc"
      placement="top"
      :show-after="300"
    >
      <span class="chip" :class="{ 'is-active': isSelected(o), 'is-custom': o.custom }" @click="toggle(o)">
        {{ o.label }}
        <el-icon v-if="o.children?.length" class="chip-more" title="选中后有细分选项"><ArrowRight /></el-icon>
        <el-icon v-if="o.custom || editMode" class="chip-remove" title="删除此选项" @click.stop="remove(o)"><Close /></el-icon>
      </span>
    </el-tooltip>

    <template v-if="allowCustom">
      <el-input
        v-if="adding"
        ref="inputRef"
        v-model="newLabel"
        class="chip-input"
        size="small"
        maxlength="30"
        placeholder="输入后回车"
        @keyup.enter="confirmAdd"
        @blur="confirmAdd"
      />
      <span v-else class="chip chip-add" @click="startAdd">
        <el-icon><Plus /></el-icon>自定义
      </span>
    </template>

    <span v-if="field.type === 'multi' && field.max" class="choice-hint">最多选 {{ field.max }} 项</span>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, Close, Plus } from '@element-plus/icons-vue'
import { useOptionEditor } from '@/novel-options/editor'

/** value 结构：{ selected: string[], sub: { [optionValue]: 子字段取值容器 } } */
const props = defineProps({
  field: { type: Object, required: true },
  value: { type: Object, required: true }
})

const { editMode, addOption, removeOption } = useOptionEditor()
const allowCustom = computed(() => props.field.allowCustom !== false)

const adding = ref(false)
const newLabel = ref('')
const inputRef = ref()

const isSelected = (o) => props.value.selected.includes(o.value)

function toggle(o) {
  const sel = props.value.selected
  if (props.field.type === 'single') {
    props.value.selected = isSelected(o) ? [] : [o.value]
    return
  }
  if (isSelected(o)) {
    sel.splice(sel.indexOf(o.value), 1)
  } else if (props.field.max && sel.length >= props.field.max) {
    ElMessage.warning(`「${props.field.label}」最多选 ${props.field.max} 项`)
  } else {
    sel.push(o.value)
  }
}

async function startAdd() {
  adding.value = true
  await nextTick()
  inputRef.value?.focus()
}

function confirmAdd() {
  const label = newLabel.value.trim()
  adding.value = false
  newLabel.value = ''
  if (!label) return
  const existing = (props.field.options || []).find((o) => o.label === label)
  const o = existing || addOption(props.field, label)
  if (!isSelected(o)) toggle(o)
}

function remove(o) {
  const sel = props.value.selected
  if (sel.includes(o.value)) sel.splice(sel.indexOf(o.value), 1)
  removeOption(props.field, o.value)
}
</script>

<style scoped>
.choice-widget {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 4px 12px;
  font-size: 13px;
  line-height: 20px;
  color: #606266;
  background: #f4f4f5;
  border: 1px solid #e4e7ed;
  border-radius: 14px;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s;
}
.chip:hover {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
}
.chip.is-active {
  color: #fff;
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
}
.chip.is-custom:not(.is-active) {
  border-style: dashed;
}
.chip-more {
  font-size: 11px;
  opacity: 0.7;
}
.chip-remove {
  margin-left: 2px;
  font-size: 11px;
  border-radius: 50%;
  opacity: 0.6;
}
.chip-remove:hover {
  opacity: 1;
  background: rgba(0, 0, 0, 0.15);
}
.chip-add {
  color: var(--el-color-primary);
  background: #fff;
  border-style: dashed;
}
.chip-input {
  width: 130px;
}
.choice-hint {
  font-size: 12px;
  color: #909399;
}
</style>
