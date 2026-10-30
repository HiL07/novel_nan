<template>
  <!-- 素材量级（1–5，影响范围）：灵感墙 / AI 构思按故事阶段挡掉超出主角量级的素材。AI 批量补全，作者手改的不动 -->
  <div class="profile-box">
    <div class="line">
      <span class="title" :title="TIER_TIP">量级</span>
      <span class="muted">已标 {{ st.labeled }} / {{ st.total }}</span>
      <el-popover placement="right" :width="300" trigger="click">
        <template #reference>
          <el-button link size="small" type="primary">{{ st.running ? '补全中…' : '补全' }}</el-button>
        </template>
        <div class="pop">
          <div class="tip">
            量级 = 这条素材在原书里的影响范围：
            <div v-for="t in TIERS" :key="t.value">{{ t.label }}：{{ t.desc }}</div>
            灵感墙按故事阶段用它挡掉主角现在打不过的对手。手改过的（素材编辑里）不会被覆盖。
          </div>
          <el-select v-model="model" size="small" placeholder="标注用的模型" style="width: 100%">
            <el-option v-for="c in configs" :key="c.id" :label="`大模型 · ${c.name}`" :value="`api:${c.id}`" />
            <el-option :label="llama ? `GGUF · ${llama.name}` : 'GGUF（llama.cpp 未运行）'" value="gguf" :disabled="!llama" />
          </el-select>
          <el-checkbox v-model="redo">AI 标过的也重标</el-checkbox>
          <div class="muted">
            {{ redo ? st.total - st.byUser : st.missing }} 条，每 20 条一次调用，约 {{ Math.ceil((redo ? st.total - st.byUser : st.missing) / 20) }} 次
          </div>
          <div class="ops">
            <el-button v-if="st.running" size="small" @click="stop">暂停</el-button>
            <el-button v-else size="small" type="primary" :disabled="!model || !(redo ? st.total - st.byUser : st.missing)" @click="start">开始补全</el-button>
          </div>
        </div>
      </el-popover>
    </div>
    <el-progress v-if="st.running" :percentage="pct" :stroke-width="6" />
    <div v-if="!st.running && st.batchTotal" class="muted">
      上次：标了 {{ st.done }} 条<template v-if="st.failed">，失败 {{ st.failed }} 条</template>
      <template v-if="st.positions">，补了 {{ st.positions }} 条原书位置</template>
    </div>
    <div v-if="st.lastError" class="danger" :title="st.lastError">{{ st.lastError }}</div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { TIERS, profileStatus, startProfile, stopProfile } from '@/api/material'
import { listModels as listConfigs } from '@/api/aiModel'
import { runningLlama } from '@/api/localModel'

const emit = defineEmits(['changed'])
const MODEL_KEY = 'nan_novel.profile.model'
const TIER_TIP = '素材在原书里的影响范围 1–5：灵感墙 / AI 构思按故事阶段过滤'

const st = ref({ total: 0, labeled: 0, missing: 0, byUser: 0, running: false, batchTotal: 0, done: 0, failed: 0 })
const configs = ref([])
const llama = ref(null)
const model = ref(read())
const redo = ref(false)
let timer = null

function read() {
  try {
    return localStorage.getItem(MODEL_KEY) || ''
  } catch {
    return ''
  }
}
watch(model, (v) => {
  try {
    localStorage.setItem(MODEL_KEY, v || '')
  } catch {
    /* 隐私模式 */
  }
})

const pct = computed(() => (st.value.batchTotal ? Math.round(((st.value.done + st.value.failed) * 100) / st.value.batchTotal) : 0))

async function refresh() {
  const res = await profileStatus().catch(() => null)
  if (res?.code === 0) {
    const was = st.value.running
    st.value = res.data
    if (was && !res.data.running) emit('changed')
    if (res.data.running) poll()
  }
}
function poll() {
  clearTimeout(timer)
  timer = setTimeout(refresh, 3000)
}

async function start() {
  const body = { onlyMissing: !redo.value, model: model.value === 'gguf' ? { source: 'gguf' } : { source: 'api', configId: Number(model.value.replace('api:', '')) } }
  const res = await startProfile(body).catch((e) => e?.response?.data)
  if (res?.code === 0) {
    st.value = res.data
    poll()
  } else {
    ElMessage.error(res?.message || '开始补全失败')
  }
}
async function stop() {
  await stopProfile().catch(() => null)
  refresh()
}

defineExpose({ refresh })

onMounted(async () => {
  refresh()
  runningLlama().then((l) => (llama.value = l))
  try {
    const res = await listConfigs()
    configs.value = res.code === 0 ? (res.data || []).filter((c) => c.status === 'VERIFIED') : []
    if (!model.value && configs.value.length) model.value = `api:${(configs.value.find((c) => c.active) || configs.value[0]).id}`
  } catch {
    configs.value = []
  }
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.profile-box { margin-top: 12px; padding: 8px; border: 1px dashed var(--el-border-color); border-radius: 6px; font-size: 12px; }
.line { display: flex; align-items: center; gap: 6px; }
.title { font-weight: 600; cursor: help; }
.muted { color: var(--el-text-color-secondary); }
.danger { color: var(--el-color-danger); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pop { display: flex; flex-direction: column; gap: 8px; font-size: 12px; }
.tip { color: var(--el-text-color-secondary); line-height: 1.6; }
.ops { display: flex; justify-content: flex-end; }
</style>
