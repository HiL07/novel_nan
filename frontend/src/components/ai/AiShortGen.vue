<template>
  <!-- 描述一段 → AI 给一个很短的结果（如 7 字以内的创作方向 / 文风），作者可以改了再用 -->
  <el-popover v-model:visible="visible" trigger="click" placement="bottom-start" :width="300">
    <template #reference>
      <slot>
        <el-button size="small" :icon="MagicStick" link type="primary">{{ text }}</el-button>
      </slot>
    </template>
    <div class="short-gen" @click.stop>
      <div class="title">{{ title }}</div>
      <el-input v-model="desc" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" maxlength="500" :placeholder="placeholder" />
      <div class="row">
        <el-button size="small" type="primary" plain :icon="MagicStick" :loading="busy" :disabled="!desc.trim()" @click="gen">
          {{ result ? '再生成一个' : 'AI 生成' }}
        </el-button>
        <span class="muted">{{ limit }} 字以内</span>
      </div>
      <template v-if="result !== ''">
        <el-input v-model="result" :maxlength="limit" show-word-limit size="small" />
        <div class="ops">
          <el-button size="small" @click="visible = false">取消</el-button>
          <el-button size="small" type="primary" :disabled="!result.trim()" @click="use">{{ useText }}</el-button>
        </div>
      </template>
    </div>
  </el-popover>
</template>

<script setup>
import { ref, watch } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { errorMessage } from '@/api/request'

const props = defineProps({
  run: { type: Function, required: true },   // (描述) => Promise<string>
  title: { type: String, default: 'AI 生成' },
  text: { type: String, default: 'AI 生成' },
  placeholder: { type: String, default: '描述你想要的感觉' },
  useText: { type: String, default: '使用' },
  limit: { type: Number, default: 7 }
})
const emit = defineEmits(['use'])

const visible = ref(false)
const desc = ref('')
const result = ref('')
const busy = ref(false)
watch(visible, (v) => {
  if (v) result.value = ''
})

async function gen() {
  busy.value = true
  try {
    result.value = String((await props.run(desc.value.trim())) || '').slice(0, props.limit)
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, 'AI 生成失败'), duration: 6000 })
  } finally {
    busy.value = false
  }
}

function use() {
  emit('use', result.value.trim())
  visible.value = false
}
</script>

<style scoped>
.short-gen { display: flex; flex-direction: column; gap: 8px; }
.title { font-weight: 600; font-size: 13px; }
.row { display: flex; align-items: center; gap: 8px; }
.muted { font-size: 12px; color: var(--el-text-color-secondary); }
.ops { display: flex; justify-content: flex-end; gap: 6px; }
</style>
