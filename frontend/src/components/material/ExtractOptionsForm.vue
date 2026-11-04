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
        <span class="hint">
          第 2 遍再按顺序读一次，带着全书已知的实体，只补漏掉的事实和实体（不做章节卡）。实测读 1 遍只抓到 2 遍的 65–78% 的实体、
          35–49% 的事实，时间约多 70%；只想看章节卡、不在乎实体档案全不全时可以选 1 遍
        </span>
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
import { costOf, formatCost, priceOf } from '@/utils/modelPricing'
import { estimateRead, fmtDuration } from './extractEstimate'

/**
 * 提取设置（提取工作区右栏）：模型 + 素材选项；章节范围由工作区左栏选，chars = 选中范围的字数（估算用）。
 * build() → {model, materials?}（开始提取用）；snapshot() → 草稿 {model, materials}（materials 带 enabled，关着也存）；
 * restore(草稿) 还原；改了任何设置都 emit('change')（工作区据此自动保存草稿）。
 */
const props = defineProps({
  chars: { type: Number, default: 0 },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['change'])

const STORE_KEY = 'nan_novel.extract.model'
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]', '::1']
const LOCAL_SECONDS_PER_CHUNK = 45 // 旧版章节分析：本地 1.5B 每段约 45 秒
// 逐章串行读的估算常数和函数在 extractEstimate.js（工作区「接着读」也用）
const DEPTHS = [
  { value: 'fast', label: '快速', desc: '每章：设定实体 + 事实、一句话、关键事件，加上代码统计（字数、对白比例、出场实体）。最省' },
  {
    value: 'standard',
    label: '标准',
    desc: '快速档 + 钩子、爽点、伏笔（埋 / 推 / 收，自动编号串起来）、情绪曲线、本章功能、主角变化、人物关系、设定动态、名场面金句；全书前 3 章另做黄金三章深拆'
  },
  { value: 'deep', label: '深拆', desc: '标准档 + 每章 3–6 个情节节点（原文按节点分段着色），输出最多' }
]
const ENTITY_CATEGORIES = MATERIAL_CATEGORIES.filter((c) => !['plot', 'craft', 'resonance'].includes(c.code)) // 情节 / 写法由「卡片整理」总结

const opts = reactive({
  enabled: true,
  categories: ENTITY_CATEGORIES.map((c) => c.code),
  rounds: 2,
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
      configId: null, // 大模型默认 = 启用中的配置（不记上次选的那个：换了启用的配置后还会用旧的）
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
  const fmt = fmtDuration
  if (!opts.enabled) {
    if (model.source !== 'local') return ''
    return `约 ${Math.ceil(props.chars / model.chunkChars)} 段，预计 ${fmt(Math.ceil(props.chars / model.chunkChars) * LOCAL_SECONDS_PER_CHUNK)}`
  }
  const { seconds: sec, input, output } = estimateRead(props.chars, { source: model.source, depth: opts.depth, rounds: opts.rounds })
  const label = DEPTHS.find((d) => d.value === opts.depth)?.label
  const head = `选中约 ${k >= 10 ? Math.round(k / 10) + ' 万' : Math.round(k) + ' 千'}字，${label}档 × ${opts.rounds} 遍，预计 ${fmt(sec)}${model.source === 'api' ? '（按实测估算）' : '（粗估，未实测）'}`
  if (model.source !== 'api') return `${head}，不花钱；可以随时暂停，之后从断点接着读`
  const tokens = `约 ${((input + output) / 1e6).toFixed(2)}M tokens（输入 ${(input / 1e6).toFixed(2)}M / 输出 ${(output / 1e6).toFixed(2)}M）`
  // 按所选配置的模型名查参考单价（utils/modelPricing.js，用户改过的优先）；查不到就只给 token
  const name = configs.value.find((c) => c.id === model.configId)?.model
  const price = priceOf(name)
  if (!price) return `${head}，${tokens}；「${name || '这个模型'}」没有参考单价，可在 token 统计条上填写`
  const cost = formatCost(costOf({ promptTokens: input, completionTokens: output }, price), price.currency)
  return `${head}，${tokens}，按${price.custom ? '你填的' : '参考'}单价约 ${cost}（以账单为准）`
})

const canStart = computed(() => {
  if (opts.enabled && !opts.categories.length) return false
  if (model.source === 'gguf') return !!llama.value
  return model.source === 'local' ? !!model.baseId : !!model.configId
})

function modelBody() {
  return model.source === 'gguf'
    ? { source: 'gguf' }
    : model.source === 'local'
      ? { source: 'local', baseId: model.baseId, chunkChars: model.chunkChars }
      : { source: 'api', configId: model.configId }
}

function snapshot() {
  return { model: modelBody(), materials: { ...opts, categories: [...opts.categories], focus: opts.focus.trim() } }
}

let restoring = false
function restore(saved) {
  if (!saved) return
  restoring = true
  const m = saved.model || {}
  if (['api', 'local', 'gguf'].includes(m.source)) model.source = m.source
  if (m.configId != null) model.configId = m.configId
  if (m.baseId) model.baseId = m.baseId
  if (m.chunkChars) model.chunkChars = Number(m.chunkChars) || model.chunkChars
  const mt = saved.materials
  if (mt) {
    opts.enabled = mt.enabled !== false
    if (Array.isArray(mt.categories) && mt.categories.length) {
      opts.categories = mt.categories.filter((c) => ENTITY_CATEGORIES.some((x) => x.code === c))
    }
    if ([1, 2].includes(mt.rounds)) opts.rounds = mt.rounds
    if (DEPTHS.some((d) => d.value === mt.depth)) opts.depth = mt.depth
    if (mt.chunkChars) opts.chunkChars = Number(mt.chunkChars) || opts.chunkChars
    opts.focus = typeof mt.focus === 'string' ? mt.focus : ''
  } else {
    opts.enabled = false // 存过草稿但没开记录设定实体
  }
  if (model.source === 'local' && !localModels.value.length) loadLocal()
  setTimeout(() => (restoring = false))
}

watch([opts, model], () => !restoring && emit('change'), { deep: true })

/** → {model, materials?}（并记住模型选择） */
function build() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(model))
  } catch {
    // 隐私模式等：不记住也能用
  }
  const out = { model: modelBody() }
  if (opts.enabled) out.materials = { ...opts, categories: [...opts.categories], focus: opts.focus.trim() }
  return out
}

defineExpose({ build, snapshot, restore, canStart, enabled: computed(() => opts.enabled) })
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
