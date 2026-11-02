<template>
  <el-form label-position="top" class="opts-form" :disabled="disabled">
    <el-form-item label="提取模型">
      <el-radio-group v-model="model.source">
        <el-radio-button value="api">大模型</el-radio-button>
        <el-radio-button value="local">本地模型</el-radio-button>
        <el-radio-button value="gguf" :disabled="!llama" :title="llama ? '' : '先到「llama.cpp」页启动 GGUF 模型'">GGUF</el-radio-button>
      </el-radio-group>
    </el-form-item>

    <el-form-item v-if="model.source === 'api'" label="模型配置">
      <el-select v-model="model.configId" placeholder="选择已验证的模型配置" :loading="loadingConfigs">
        <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id">
          <span>{{ c.name }}</span>
          <span class="opt-meta">{{ c.model }}</span>
          <el-tag v-if="isLocalHost(c.baseUrl)" size="small" type="success" class="opt-tag">本机 · 免费</el-tag>
          <el-tag v-if="c.active" size="small" class="opt-tag">启用中</el-tag>
        </el-option>
      </el-select>
      <span class="hint">只用于本次提取，不改变「模型配置」里启用的模型；本机 OpenAI 兼容服务不计费</span>
      <span v-if="!loadingConfigs && !configs.length" class="hint warn">
        没有验证通过的模型配置，请先到「模型配置」添加并验证，或改用本地模型
      </span>
    </el-form-item>

    <el-form-item v-else-if="model.source === 'gguf'" label="GGUF 模型">
      <span v-if="llama">llama.cpp · {{ llama.name }}（上下文 {{ llama.ctx }}）</span>
      <span v-else class="hint warn">llama.cpp 没有运行：请先到「llama.cpp」页选择 GGUF 模型并启动</span>
      <span class="hint">本机运行不计费；一章最多读「分段字数」的 2 倍，上下文建议 ≥ 12288。提取期间不要在 llama.cpp 页换模型</span>
    </el-form-item>

    <template v-else>
      <el-form-item label="本地模型">
        <el-select v-model="model.baseId" placeholder="选择基础模型" :loading="loadingLocal">
          <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" :disabled="m.exists === false">
            <span>{{ m.name }}</span>
            <span v-if="m.exists === false" class="opt-meta">（模型目录不存在）</span>
          </el-option>
        </el-select>
        <span v-if="localError" class="hint warn">{{ localError }}</span>
        <span v-else-if="!loadingLocal && !localModels.length" class="hint warn">
          还没有本地生成模型，请先到「本地模型」页下载或登记（推荐 Qwen2.5-1.5B-Instruct）
        </span>
        <span class="hint">不花钱，但速度慢、更粗糙；运行时独占 GPU，章节生成 / 本地 AI 构思 / 训练要等它结束</span>
      </el-form-item>
      <el-form-item v-if="!opts.enabled" label="分段字数（章节分析）">
        <el-input-number v-model="model.chunkChars" :min="1000" :max="6000" :step="500" />
      </el-form-item>
    </template>

    <el-form-item label="记录设定实体">
      <el-switch v-model="opts.enabled" />
      <span class="hint">
        一章一章按顺序读：记录设定实体和原文依据（对不上的标为未核实），并按档位给每章做章节卡，读完的章在中间原文里高亮。
        关掉 = 只做旧版章节分析（没有逐章卡片）
      </span>
    </el-form-item>
    <template v-if="opts.enabled">
      <el-form-item label="拆解档位">
        <el-radio-group v-model="opts.depth">
          <el-radio-button v-for="d in DEPTHS" :key="d.value" :value="d.value">{{ d.label }}</el-radio-button>
        </el-radio-group>
        <span class="hint">{{ DEPTHS.find((d) => d.value === opts.depth)?.desc }}</span>
        <span v-if="opts.depth === 'deep' && model.source !== 'api'" class="hint warn">
          小模型标的情节节点段落区间可能不准，深拆建议用大模型
        </span>
      </el-form-item>
      <el-form-item label="实体分类">
        <el-checkbox-group v-model="opts.categories">
          <el-checkbox v-for="c in ENTITY_CATEGORIES" :key="c.code" :value="c.code">{{ c.label }}</el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="阅读遍数">
        <el-radio-group v-model="opts.rounds">
          <el-radio-button :value="1">1 遍</el-radio-button>
          <el-radio-button :value="2">2 遍</el-radio-button>
        </el-radio-group>
        <span class="hint">第 2 遍再按顺序读一次，只补漏掉的事实和实体（不做章节卡）</span>
      </el-form-item>
      <el-form-item v-if="model.source !== 'api'" label="分段字数">
        <el-input-number v-model="opts.chunkChars" :min="1500" :max="6000" :step="500" />
        <span class="hint">
          {{ model.source === 'gguf' ? '一章最多读这个字数的 2 倍' : '一章最多读这么多字' }}，更长的章按段落切开、按顺序读再合成一章
        </span>
      </el-form-item>
      <el-form-item label="特别关注">
        <el-input v-model="opts.focus" maxlength="300" placeholder="可选，如：重点记录怪物的弱点和习性" />
      </el-form-item>
    </template>
    <el-alert v-if="estimateText" type="info" :closable="false" show-icon :title="estimateText" />
  </el-form>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { MATERIAL_CATEGORIES } from '@/api/material'
import { listModels as listConfigs } from '@/api/aiModel'
import { isGenerationModel, listModels as listLocalModels, runningLlama } from '@/api/localModel'
import { errorMessage } from '@/api/request'

/** 提取设置（提取工作区右栏）：模型 + 素材选项；章节范围由工作区左栏选，chars = 选中范围的字数（估算用）。build() → {model, materials?} */
const props = defineProps({
  chars: { type: Number, default: 0 },
  disabled: { type: Boolean, default: false }
})

const STORE_KEY = 'nan_novel.extract.model'
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]', '::1']
const LOCAL_SECONDS_PER_CHUNK = 45 // 旧版章节分析：本地 1.5B 每段约 45 秒
// 逐章串行读的粗估：秒 / 千字（第 1 遍，按档位）。大模型 = DeepSeek 实测（2026-11-02，5 章 1 万字标准档 47 秒）；
// GGUF / 本地 = 旧的分块实测（GGUF Qwen3-4B Q4 约 16 秒 / 千字）加上章节卡多出的输出，待实测校准。
// 第 2 遍补漏按「快速」算。token：每千字输入约 1.4k，输出按档位（标准档实测 0.85k）
const READ_SECONDS = {
  api: { fast: 2, standard: 4.5, deep: 5.5 },
  gguf: { fast: 16, standard: 30, deep: 35 },
  local: { fast: 40, standard: 70, deep: 80 }
}
const READ_TOKENS = { input: 1400, output: { fast: 350, standard: 850, deep: 1000 } }
const DEPTHS = [
  { value: 'fast', label: '快速', desc: '每章：设定实体 + 事实、一句话、关键事件，加上代码统计（字数、对白比例、出场实体）。最省' },
  {
    value: 'standard',
    label: '标准',
    desc: '快速档 + 钩子、爽点、伏笔（埋 / 推 / 收，自动编号串起来）、情绪曲线、本章功能、主角变化、人物关系、设定动态、名场面金句；全书前 3 章另做黄金三章深拆'
  },
  { value: 'deep', label: '深拆', desc: '标准档 + 每章 3–6 个情节节点（原文按节点分段着色），输出最多' }
]
const ENTITY_CATEGORIES = MATERIAL_CATEGORIES.filter((c) => c.code !== 'plot') // 情节由「整理卡片」从章节卡里找

const opts = reactive({
  enabled: true,
  categories: ENTITY_CATEGORIES.map((c) => c.code),
  rounds: 1,
  depth: 'standard',
  chunkChars: 3000,
  focus: ''
})
const model = reactive({ source: 'api', configId: null, baseId: '', chunkChars: 2500, ...readSaved() })
const configs = ref([])
const localModels = ref([])
const loadingConfigs = ref(false)
const loadingLocal = ref(false)
const localError = ref('')
const llama = ref(null)

function readSaved() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE_KEY) || 'null')
    if (!v || typeof v !== 'object') return {}
    return {
      source: ['local', 'gguf'].includes(v.source) ? v.source : 'api',
      configId: v.configId ?? null,
      baseId: v.baseId || '',
      chunkChars: Number(v.chunkChars) || 2500
    }
  } catch {
    return {}
  }
}

function isLocalHost(url) {
  try {
    return LOCAL_HOSTS.includes(new URL(url).hostname)
  } catch {
    return false
  }
}

async function loadConfigs() {
  loadingConfigs.value = true
  try {
    const res = await listConfigs()
    configs.value = res.code === 0 ? (res.data || []).filter((c) => c.status === 'VERIFIED') : []
    if (!configs.value.some((c) => c.id === model.configId)) {
      model.configId = (configs.value.find((c) => c.active) || configs.value[0])?.id ?? null
    }
  } catch {
    configs.value = []
  } finally {
    loadingConfigs.value = false
  }
}

async function loadLocal() {
  loadingLocal.value = true
  localError.value = ''
  try {
    const res = await listLocalModels()
    if (res.code !== 0) throw new Error(res.message)
    localModels.value = (res.data || []).filter((m) => isGenerationModel(m))
    if (!localModels.value.some((m) => m.id === model.baseId && m.exists !== false)) {
      const usable = localModels.value.filter((m) => m.exists !== false)
      model.baseId = (usable.find((m) => /qwen2\.5-1\.5b/i.test(m.name)) || usable[0])?.id || ''
    }
  } catch (e) {
    localModels.value = []
    localError.value = errorMessage(e, '无法连接 AI 服务，读取本地模型列表失败')
  } finally {
    loadingLocal.value = false
  }
}

onMounted(() => {
  loadConfigs()
  runningLlama().then((l) => (llama.value = l))
  if (model.source === 'local') loadLocal()
})
watch(
  () => model.source,
  (s) => s === 'local' && !localModels.value.length && loadLocal()
)

const estimateText = computed(() => {
  const k = props.chars / 1000
  if (!k) return ''
  const fmt = (sec) => (sec < 3600 ? `${Math.max(1, Math.round(sec / 60))} 分钟` : `${(sec / 3600).toFixed(1)} 小时`)
  if (!opts.enabled) {
    if (model.source !== 'local') return ''
    return `约 ${Math.ceil(props.chars / model.chunkChars)} 段，预计 ${fmt(Math.ceil(props.chars / model.chunkChars) * LOCAL_SECONDS_PER_CHUNK)}`
  }
  const speed = READ_SECONDS[model.source]
  const sec = k * speed[opts.depth] + (opts.rounds === 2 ? k * speed.fast : 0)
  const label = DEPTHS.find((d) => d.value === opts.depth)?.label
  const head = `选中约 ${k >= 10 ? Math.round(k / 10) + ' 万' : Math.round(k) + ' 千'}字，${label}档 × ${opts.rounds} 遍，预计 ${fmt(sec)}（粗估）`
  if (model.source !== 'api') return `${head}，不花钱；可以随时暂停，之后从断点接着读`
  const input = k * READ_TOKENS.input * opts.rounds
  const output = k * (READ_TOKENS.output[opts.depth] + (opts.rounds === 2 ? READ_TOKENS.output.fast : 0))
  const yuan = Math.round(((input * 2 + output * 3) / 1e6) * 100) / 100
  return `${head}，约 ${((input + output) / 1e6).toFixed(2)}M tokens（DeepSeek 约 ${yuan} 元，按 2 / 3 元每百万输入 / 输出粗算）`
})

const canStart = computed(() => {
  if (opts.enabled && !opts.categories.length) return false
  if (model.source === 'gguf') return !!llama.value
  return model.source === 'local' ? !!model.baseId : !!model.configId
})

/** → {model, materials?}（并记住模型选择） */
function build() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(model))
  } catch {
    // 隐私模式等：不记住也能用
  }
  const m =
    model.source === 'gguf'
      ? { source: 'gguf' }
      : model.source === 'local'
        ? { source: 'local', baseId: model.baseId, chunkChars: model.chunkChars }
        : { source: 'api', configId: model.configId }
  const out = { model: m }
  if (opts.enabled) out.materials = { ...opts, categories: [...opts.categories], focus: opts.focus.trim() }
  return out
}

defineExpose({ build, canStart, enabled: computed(() => opts.enabled) })
</script>

<style scoped>
.opts-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.opts-form :deep(.el-select) {
  width: 100%;
}
.hint {
  display: block;
  width: 100%;
  margin-top: 4px;
  line-height: 1.5;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.hint.warn {
  color: var(--el-color-warning);
}
.opt-meta {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.opt-tag {
  margin-left: 6px;
}
</style>
