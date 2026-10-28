<template>
  <el-dialog :model-value="modelValue" title="小说提取" width="640px" @update:model-value="close" @open="onOpen">
    <p class="intro">解析《{{ fileName }}》的章节、人物和文风，耗时视篇幅可能需要数分钟。</p>

    <el-form label-width="100px">
      <el-form-item label="提取模型">
        <el-radio-group v-model="model.source">
          <el-radio-button value="api">大模型</el-radio-button>
          <el-radio-button value="local">本地模型</el-radio-button>
          <el-radio-button value="gguf" :disabled="!llama" :title="llama ? '' : '先到「llama.cpp」页启动 GGUF 模型'">GGUF</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <template v-if="model.source === 'api'">
        <el-form-item label="模型配置">
          <el-select v-model="model.configId" placeholder="选择已验证的模型配置" style="width: 100%" :loading="loadingConfigs">
            <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id">
              <span>{{ c.name }}</span>
              <span class="opt-meta">{{ c.model }}</span>
              <el-tag v-if="isLocalHost(c.baseUrl)" size="small" type="success" class="opt-tag">本机 · 免费</el-tag>
              <el-tag v-if="c.active" size="small" class="opt-tag">启用中</el-tag>
            </el-option>
          </el-select>
          <span class="hint block">
            只用于本次提取，不改变「模型配置」里启用的模型。本机 OpenAI 兼容服务（如 llama.cpp 的千问 7B，地址 127.0.0.1:8001）不计费
          </span>
          <span v-if="!loadingConfigs && !configs.length" class="hint block warn">
            没有验证通过的模型配置，请先到「模型配置」添加并验证，或改用本地模型
          </span>
        </el-form-item>
      </template>

      <template v-else-if="model.source === 'gguf'">
        <el-form-item label="GGUF 模型">
          <span v-if="llama">llama.cpp · {{ llama.name }}（上下文 {{ llama.ctx }}）</span>
          <span v-else class="hint warn">llama.cpp 没有运行：请先到「llama.cpp」页选择 GGUF 模型并启动</span>
          <span class="hint block">
            用「llama.cpp」页正在运行的模型，本机运行不计费；按大模型的方式分块（每块约 6000 字），上下文建议 ≥ 12288。
            提取期间不要在 llama.cpp 页换模型
          </span>
        </el-form-item>
      </template>

      <template v-else>
        <el-form-item label="本地模型">
          <el-select v-model="model.baseId" placeholder="选择基础模型" style="width: 100%" :loading="loadingLocal">
            <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" :disabled="m.exists === false">
              <span>{{ m.name }}</span>
              <span v-if="m.exists === false" class="opt-meta">（模型目录不存在）</span>
            </el-option>
          </el-select>
          <span v-if="localError" class="hint block warn">{{ localError }}</span>
          <span v-else-if="!loadingLocal && !localModels.length" class="hint block warn">
            还没有本地生成模型，请先到「本地模型」页下载或登记（推荐 Qwen2.5-1.5B-Instruct）
          </span>
        </el-form-item>
        <el-form-item label="分段字数">
          <el-input-number v-model="model.chunkChars" :min="1000" :max="6000" :step="500" />
          <span class="hint">字 / 段。小模型一次读不了太长，段越小越稳但段数越多；1.5B 建议 2000~3000</span>
        </el-form-item>
        <el-alert type="warning" :closable="false" show-icon class="local-alert">
          <template #title>
            本地模型不花钱，但速度慢、提取得更粗糙（偶尔有段落解析失败会被跳过）；运行时独占 GPU，
            章节生成 / 本地 AI 构思 / 训练要等它结束。
            <template v-if="estimate">预计 {{ estimate.chunks }} 段，约 {{ estimate.text }}。</template>
          </template>
        </el-alert>
      </template>

      <el-form-item label="记录设定实体">
        <el-switch v-model="opts.enabled" />
        <span class="hint">
          逐段记录魔物 / 世界观 / 角色 / 物品等在原文里的具体事实（每条附原文依据，对不上原文的自动丢弃），得到「实体档案」。
          这一步只读原文：之后在「提取成功」里单独「整理卡片」，再逐条确认进素材库
        </span>
      </el-form-item>
      <template v-if="opts.enabled">
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
          <span class="hint">第 2 遍带着已知实体再读一次，补上漏掉的细节和实体；本地 / GGUF 小模型建议 2 遍，耗时约翻倍</span>
        </el-form-item>
        <el-form-item label="分段字数">
          <el-input-number v-model="opts.chunkChars" :min="1500" :max="6000" :step="500" />
          <span class="hint">字 / 段。段越小越不容易漏，段数越多；短章节会合并成一段</span>
        </el-form-item>
        <el-form-item label="特别关注">
          <el-input
            v-model="opts.focus"
            maxlength="300"
            placeholder="可选，如：重点记录怪物的弱点和习性、魔法的代价"
          />
        </el-form-item>
        <el-alert v-if="readEstimate" type="info" :closable="false" show-icon class="local-alert" :title="readEstimate" />
      </template>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :disabled="!canStart" @click="confirm">开始提取</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { MATERIAL_CATEGORIES } from '@/api/material'
import { listModels as listConfigs } from '@/api/aiModel'
import { isGenerationModel, listModels as listLocalModels, runningLlama } from '@/api/localModel'
import { errorMessage } from '@/api/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  fileName: { type: String, default: '' },
  // 用于估算本地模型耗时：charCount（字数）优先，否则按 fileSize（字节）粗估
  charCount: { type: Number, default: 0 },
  fileSize: { type: Number, default: 0 }
})
const emit = defineEmits(['update:modelValue', 'confirm'])

const STORE_KEY = 'nan_novel.extract.model'
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]', '::1']
// 本地 1.5B 约 10~16 token/s：每段输出约 400~700 token，再加读入正文的时间
const LOCAL_SECONDS_PER_CHUNK = 45
// 记录实体的粗估：秒 / 千字 / 遍（GGUF Qwen3-4B Q4 在 RTX 4060 Laptop 实测约 16 秒，《耐瑟瑞尔》前 6 章 1.4 万字）；
// token：每遍每千字约 1.3k 输入 + 0.25k 输出
const READ_SECONDS = { gguf: 16, api: 1.5, local: 40 }
const READ_TOKENS = { input: 1300, output: 250 }
// 情节不在提取时记录：剧情段由「整理卡片」从章节摘要里找
const ENTITY_CATEGORIES = MATERIAL_CATEGORIES.filter((c) => c.code !== 'plot')

// 记住上次的选择（同一会话内）
const opts = reactive({
  enabled: true,
  categories: ENTITY_CATEGORIES.map((c) => c.code),
  rounds: 2,
  chunkChars: 3000,
  focus: ''
})
const model = reactive({ source: 'api', configId: null, baseId: '', chunkChars: 2500, ...readSaved() })

const configs = ref([])
const localModels = ref([])
const loadingConfigs = ref(false)
const loadingLocal = ref(false)
const localError = ref('')
const llama = ref(null) // 运行中的 llama.cpp（GGUF）；null = 没运行

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

function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(model))
  } catch {
    // 隐私模式等：不记住也能用
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

function onOpen() {
  loadConfigs()
  runningLlama().then((l) => (llama.value = l))
  if (model.source === 'local') loadLocal()
}

watch(
  () => model.source,
  (s) => {
    if (s === 'local' && props.modelValue && !localModels.value.length) loadLocal()
  }
)

const estimate = computed(() => {
  // GBK / UTF-8 中文每字 2~3 字节，粗估取 2.5
  const chars = props.charCount || Math.round(props.fileSize / 2.5)
  if (!chars) return null
  const chunks = Math.max(1, Math.ceil(chars / model.chunkChars))
  const seconds = chunks * LOCAL_SECONDS_PER_CHUNK * (opts.enabled ? 1.4 : 1)
  const text = seconds < 3600 ? `${Math.max(1, Math.round(seconds / 60))} 分钟` : `${(seconds / 3600).toFixed(1)} 小时`
  return { chunks, text }
})

const readEstimate = computed(() => {
  if (!opts.enabled) return ''
  const chars = props.charCount || Math.round(props.fileSize / 2.5)
  if (!chars) return ''
  const k = chars / 1000
  const reads = k * opts.rounds
  const sec = reads * READ_SECONDS[model.source]
  const time = sec < 3600 ? `${Math.max(1, Math.round(sec / 60))} 分钟` : `${(sec / 3600).toFixed(1)} 小时`
  const head = `约 ${Math.round(k / 10)} 万字 × ${opts.rounds} 遍，预计 ${time}`
  if (model.source !== 'api') return `${head}，不花钱；长篇可以随时「暂停」，中断后点「继续」从断点接着读`
  const yuan = Math.round(((reads * READ_TOKENS.input * 2 + reads * READ_TOKENS.output * 3) / 1e6) * 10) / 10
  return `${head}，约 ${((reads * (READ_TOKENS.input + READ_TOKENS.output)) / 1e6).toFixed(1)}M tokens（DeepSeek 约 ${yuan} 元，按 2 / 3 元每百万输入 / 输出粗算）`
})

const canStart = computed(() => {
  if (opts.enabled && !opts.categories.length) return false
  if (model.source === 'gguf') return !!llama.value
  return model.source === 'local' ? !!model.baseId : !!model.configId
})

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  save()
  const m =
    model.source === 'gguf'
      ? { source: 'gguf' }
      : model.source === 'local'
        ? { source: 'local', baseId: model.baseId, chunkChars: model.chunkChars }
        : { source: 'api', configId: model.configId }
  const out = { model: m }
  if (opts.enabled) out.materials = { ...opts, categories: [...opts.categories], focus: opts.focus.trim() }
  emit('confirm', out)
  close()
}
</script>

<style scoped>
.intro {
  margin: 0 0 14px;
  font-size: 13px;
  color: #606266;
}
.hint {
  flex: 1;
  min-width: 0;
  margin-left: 10px;
  line-height: 1.5;
  font-size: 12px;
  color: #909399;
}
.hint.block {
  flex-basis: 100%;
  margin-left: 0;
  margin-top: 4px;
}
.hint.warn {
  color: #e6a23c;
}
.opt-meta {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}
.opt-tag {
  margin-left: 6px;
}
.local-alert {
  margin-bottom: 18px;
}
</style>
