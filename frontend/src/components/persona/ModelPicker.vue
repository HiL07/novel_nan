<template>
  <div class="model-picker">
    <el-radio-group :model-value="value.source" size="small" @update:model-value="set({ source: $event })">
      <el-radio-button value="api">大模型</el-radio-button>
      <el-radio-button value="gguf" :disabled="!llama" :title="llama ? '' : '先到「llama.cpp」页启动 GGUF 模型'">GGUF</el-radio-button>
      <el-radio-button value="local">本地模型</el-radio-button>
    </el-radio-group>
    <el-select v-if="value.source === 'api'" :model-value="value.configId" size="small" placeholder="已验证的模型配置"
               class="sel" @update:model-value="set({ configId: $event })">
      <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id" />
    </el-select>
    <span v-else-if="value.source === 'gguf'" class="hint">{{ llama ? 'llama.cpp · ' + llama.name : 'llama.cpp 没有运行' }}</span>
    <el-select v-else :model-value="value.baseId" size="small" placeholder="基础模型" class="sel"
               @update:model-value="set({ baseId: $event })">
      <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" :disabled="m.exists === false" />
    </el-select>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { listModels as listConfigs } from '@/api/aiModel'
import { isGenerationModel, listModels as listLocalModels, runningLlama } from '@/api/localModel'

/** v-model = {source: api|gguf|local, configId, baseId}；storeKey 记住选择 */
const props = defineProps({
  modelValue: { type: Object, required: true },
  storeKey: { type: String, default: 'nan_novel.persona.model' }
})
const emit = defineEmits(['update:modelValue'])
const value = computed(() => props.modelValue)
const configs = ref([])
const localModels = ref([])
const llama = ref(null)

function set(patch) {
  const next = { ...props.modelValue, ...patch }
  emit('update:modelValue', next)
  try {
    localStorage.setItem(props.storeKey, JSON.stringify(next))
  } catch {
    // 浏览器不让存：不记住
  }
}

onMounted(async () => {
  let start = { ...props.modelValue }
  try {
    const saved = JSON.parse(localStorage.getItem(props.storeKey) || 'null')
    if (saved && typeof saved === 'object') start = { ...start, ...saved }
  } catch {
    // 忽略
  }
  runningLlama().then((l) => (llama.value = l)).catch(() => {})
  try {
    const res = await listConfigs()
    configs.value = res.code === 0 ? (res.data || []).filter((c) => c.status === 'VERIFIED') : []
    if (!configs.value.some((c) => c.id === start.configId)) {
      start.configId = (configs.value.find((c) => c.active) || configs.value[0])?.id ?? null
    }
  } catch {
    configs.value = []
  }
  emit('update:modelValue', start)
  try {
    const res = await listLocalModels()
    localModels.value = res.code === 0 ? (res.data || []).filter(isGenerationModel) : []
  } catch {
    localModels.value = []
  }
})

defineExpose({ configs })
</script>

<style scoped>
.model-picker { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sel { width: 200px; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
