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
      <span v-if="!adding" class="chip chip-add" @click="startAdd">
        <el-icon><Plus /></el-icon>自定义
      </span>
      <!-- 自定义面板：手写一个选项，或用 AI 润色 / 生成（素材只对这个自定义选项生效） -->
      <div v-else class="custom-panel">
        <div class="panel-row">
          <el-input
            ref="inputRef"
            v-model="newLabel"
            class="custom-input"
            size="small"
            maxlength="30"
            :placeholder="aiOn ? '写一个选项，或写个大致想法再用 AI 润色 / 生成' : '输入选项名后回车'"
            @keyup.enter="confirmAdd"
            @keyup.esc="cancelAdd"
          />
          <el-button size="small" type="primary" :disabled="!newLabel.trim()" @click="confirmAdd">添加并选中</el-button>
          <el-button size="small" @click="cancelAdd">取消</el-button>
        </div>
        <div v-if="newDesc || aiOn" class="panel-row">
          <el-input v-model="newDesc" class="custom-desc" size="small" maxlength="120" placeholder="选项说明（可选，鼠标悬停在选项上时显示）" />
        </div>
        <template v-if="aiOn">
          <div class="panel-row">
            <el-button size="small" :icon="Collection" @click="pickerOpen = true">选素材</el-button>
            <el-tag v-for="m in materials" :key="m.id" size="small" closable @close="removeMaterial(m.id)">{{ m.title }}</el-tag>
            <span class="muted">素材只用于这个自定义选项，不影响别处</span>
          </div>
          <div class="panel-row">
            <span :title="aiTip('polish')">
              <el-button size="small" :icon="EditPen" :loading="ai.loading(aiKey)" :disabled="!canAi || locked" @click="runAi('polish')">AI 润色</el-button>
            </span>
            <span :title="aiTip('generate')">
              <el-button size="small" :icon="MagicStick" :loading="ai.loading(aiKey)" :disabled="!canAi || locked" @click="runAi('generate')">AI 生成</el-button>
            </span>
            <span class="muted">{{ canAi ? '润色：把你写的整理成一个选项（保留原意）；生成：按你写的方向 / 选的素材设计一个新选项' : '在上面写点内容或选择素材后才能用 AI' }}</span>
          </div>
        </template>
        <MaterialPicker v-if="pickerOpen" v-model="pickerOpen" pick-only :exclude-books="ai?.excludeBooks?.value || []" @apply="onPick" />
      </div>
    </template>

    <span v-if="field.type === 'multi' && field.max" class="choice-hint">最多选 {{ field.max }} 项</span>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, Close, Collection, EditPen, MagicStick, Plus } from '@element-plus/icons-vue'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import { useOptionEditor } from '@/novel-options/editor'

/**
 * value 结构：{ selected: string[], sub: { [optionValue]: 子字段取值容器 } }
 * path / container / siblings：本字段的位置和同一容器的字段（「自定义」里的 AI 用来了解上下文）
 */
const props = defineProps({
  field: { type: Object, required: true },
  value: { type: Object, required: true },
  path: { type: Array, default: () => [] },
  container: { type: Object, default: null },
  siblings: { type: Array, default: null }
})

const { editMode, addOption, removeOption, ai } = useOptionEditor()
const allowCustom = computed(() => props.field.allowCustom !== false)

const adding = ref(false)
const newLabel = ref('')
const newDesc = ref('')
const inputRef = ref()

/* ---- 自定义里的 AI：输入框有内容或选了素材才能用；素材只属于这一次自定义 ---- */
const aiOn = computed(() => !!ai?.enabled.value)
const materials = ref([])
const pickerOpen = ref(false)
const canAi = computed(() => !!newLabel.value.trim() || materials.value.length > 0)
const aiKey = computed(() => `${ai?.busyKeyOf(props.path, props.field)}|option`)
const locked = computed(() => aiOn.value && ai.locked([...props.path, props.field.label]))

function aiTip(action) {
  const what = action === 'polish'
    ? 'AI 润色：把框里写的（和选的素材）整理成一个简洁的选项 + 说明，保留原意'
    : 'AI 生成：按框里写的方向和 / 或选的素材，设计一个与已有选项不重复的新选项'
  const local = ai?.cfg?.source === 'local' && locked.value ? '（本地模型一次只能处理一个 AI 请求）' : ''
  return (canAi.value ? what : `${what}；需要先写点内容或选择素材`) + local
}

async function runAi(action) {
  const option = await ai.customOption(props.field, {
    action, seed: newLabel.value.trim(), materials: materials.value,
    path: props.path, container: props.container, siblings: props.siblings
  })
  if (!option) return
  newLabel.value = option.label
  newDesc.value = option.desc || ''
  ElMessage.success('AI 给出了一个选项，可以修改后点「添加并选中」')
}

function onPick(list) {
  const ids = new Set(materials.value.map((m) => m.id))
  materials.value.push(...list.filter((m) => !ids.has(m.id)))
}
function removeMaterial(id) {
  materials.value = materials.value.filter((m) => m.id !== id)
}

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

function cancelAdd() {
  adding.value = false
  newLabel.value = ''
  newDesc.value = ''
  materials.value = []
}

function confirmAdd() {
  const label = newLabel.value.trim()
  if (!label) return
  const existing = (props.field.options || []).find((o) => o.label === label)
  const o = existing || addOption(props.field, label)
  if (!existing && newDesc.value.trim()) o.desc = newDesc.value.trim()
  if (!isSelected(o)) toggle(o)
  cancelAdd()
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
.custom-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-basis: 100%;
  padding: 8px 10px;
  background: #fafafa;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
}
.panel-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.custom-input {
  width: 260px;
}
.custom-desc {
  width: 100%;
  max-width: 520px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.choice-hint {
  font-size: 12px;
  color: #909399;
}
</style>
