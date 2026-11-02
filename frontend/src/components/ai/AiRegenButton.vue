<template>
  <!-- AI 重新生成：两个开关组合成四种方式 —— 给不给方向 × 参考不参考已有内容（先读已有的，保留并补充，不重复） -->
  <el-popover v-model:visible="visible" trigger="click" placement="bottom-end" :width="basis ? 380 : 320" :disabled="disabled">
    <template #reference>
      <el-button :size="size" :link="link" type="primary" :icon="MagicStick" :loading="loading" :disabled="disabled" @click.stop>
        {{ text }}
      </el-button>
    </template>
    <div class="regen" @click.stop>
      <div class="title">AI 重新生成「{{ label }}」</div>
      <AiBasis v-if="basis" :md="basis" title="这次会参考" />
      <el-input
        v-model="direction"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 5 }"
        maxlength="500"
        :placeholder="placeholder"
      />
      <el-checkbox v-model="keep" :disabled="!hasExisting" class="keep">
        参考已有内容
        <span class="muted">{{ hasExisting ? '（保留已有的，在此基础上补充 / 按方向修改）' : '（现在还是空的）' }}</span>
      </el-checkbox>
      <div class="mode muted">{{ modeText }}</div>
      <div class="ops">
        <el-button size="small" @click="visible = false">取消</el-button>
        <el-button size="small" type="primary" @click="run">{{ keep && hasExisting ? '补充 / 修改' : '重新生成' }}</el-button>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import AiBasis from './AiBasis.vue'

const props = defineProps({
  label: { type: String, required: true },           // 这一块叫什么（力量体系、世界规则……）
  hasExisting: { type: Boolean, default: false },     // 已经有内容（才能「参考已有」）
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  text: { type: String, default: 'AI 重新生成' },
  size: { type: String, default: 'small' },
  link: { type: Boolean, default: true },
  basis: { type: String, default: '' },                // 可选：Markdown，列出会影响这次生成的选项（AiBasis 渲染）
  placeholder: { type: String, default: '可选：给个方向，比如「法师塔没有阶数，强弱看法师本人」。留空 = AI 自己发挥' }
})
const emit = defineEmits(['run'])

const visible = ref(false)
const direction = ref('')
const keep = ref(false)
// 打开时：有内容就默认「参考已有」（多数时候是想在已有的基础上改）
watch(visible, (v) => {
  if (v) keep.value = props.hasExisting
})

const modeText = computed(() => {
  const d = direction.value.trim()
  if (keep.value && props.hasExisting) return d ? '方式：按方向，在已有内容上补充 / 修改' : '方式：在已有内容上补充（不重复）'
  return d ? '方式：按方向整块重新生成' : '方式：整块重新生成（不看原来的）'
})

function run() {
  visible.value = false
  emit('run', { direction: direction.value.trim(), keep: keep.value && props.hasExisting })
}
</script>

<style scoped>
.regen { display: flex; flex-direction: column; gap: 8px; }
.title { font-weight: 600; font-size: 13px; }
.keep { height: auto; white-space: normal; align-items: flex-start; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.ops { display: flex; justify-content: flex-end; gap: 6px; }
</style>
