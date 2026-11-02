<template>
  <!-- 文本框 + 框内右下角的魔术棒（悬停提示「AI 润色」等）：点一下把框里的内容交给 run(text) 处理，结果替换框内内容，可撤销 -->
  <div class="wand-input">
    <el-input
      :model-value="modelValue"
      type="textarea"
      :rows="rows"
      :maxlength="maxlength"
      :placeholder="placeholder"
      :disabled="busy"
      @update:model-value="(v) => emit('update:modelValue', v)"
    />
    <el-tooltip :content="modelValue?.trim() ? tip : emptyTip" placement="top">
      <span class="wand" :class="{ disabled: !modelValue?.trim() || disabled }" @click="go">
        <el-icon v-if="!busy"><MagicStick /></el-icon>
        <el-icon v-else class="is-loading"><Loading /></el-icon>
      </span>
    </el-tooltip>
    <div v-if="undo !== null" class="undo">
      AI 已{{ doneText }}，<el-button link type="primary" size="small" @click="revert">撤销</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Loading, MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { errorMessage } from '@/api/request'

const props = defineProps({
  modelValue: { type: String, default: '' },
  run: { type: Function, required: true },        // (text) => Promise<string>
  tip: { type: String, default: 'AI 润色' },
  emptyTip: { type: String, default: '先写几句，AI 再帮你润色' },
  doneText: { type: String, default: '润色' },
  rows: { type: Number, default: 2 },
  maxlength: { type: [Number, String], default: 500 },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])

const busy = ref(false)
const undo = ref(null)        // AI 改之前的内容；null = 没有可撤销的
let aiValue = null
// 作者在 AI 结果上又改了：撤销就没意义了（会冲掉手改的），收起
watch(() => props.modelValue, (v) => {
  if (undo.value !== null && v !== aiValue) undo.value = null
})

async function go() {
  const text = (props.modelValue || '').trim()
  if (!text || props.disabled || busy.value) return
  busy.value = true
  try {
    const value = await props.run(text)
    if (!value) return
    undo.value = props.modelValue
    aiValue = value
    emit('update:modelValue', value)
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, 'AI 处理失败'), duration: 6000 })
  } finally {
    busy.value = false
  }
}

function revert() {
  const before = undo.value
  undo.value = null
  emit('update:modelValue', before)
}
</script>

<style scoped>
.wand-input { position: relative; width: 100%; }
.wand-input :deep(.el-textarea__inner) { padding-right: 30px; }
.wand {
  position: absolute; right: 8px; bottom: 6px;
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 4px;
  color: var(--el-color-primary); cursor: pointer;
}
.wand:hover { background: var(--el-color-primary-light-9); }
.wand.disabled { color: var(--el-text-color-placeholder); cursor: not-allowed; background: none; }
.undo { font-size: 12px; color: var(--el-text-color-secondary); }
</style>
