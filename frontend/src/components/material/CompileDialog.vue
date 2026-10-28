<template>
  <el-dialog :model-value="modelValue" title="整理卡片" width="620px" @update:model-value="close" @open="onOpen">
    <p class="intro">
      把《{{ fileName }}》实体档案里的事实整理成素材卡（详细描述、属性、作者用法、借用提示），同类世界观合成体系卡，
      并可从章节摘要里找出剧情段。整理好的进入「待确认」，逐条确认后才进素材库。可以换模型 / 换范围多次整理。
    </p>
    <el-form label-width="90px">
      <el-form-item label="整理模型">
        <el-radio-group v-model="model.source">
          <el-radio-button value="api">大模型</el-radio-button>
          <el-radio-button value="gguf" :disabled="!llama" :title="llama ? '' : '先到「llama.cpp」页启动 GGUF 模型'">GGUF</el-radio-button>
          <el-radio-button value="local">本地模型</el-radio-button>
        </el-radio-group>
        <span class="hint block">和提取用的模型无关：输入只有已核实的事实（很短），用大模型写「作者用法」更准，一本书约 1 元；GGUF / 本地模型不花钱但慢</span>
      </el-form-item>
      <el-form-item v-if="model.source === 'api'" label="模型配置">
        <el-select v-model="model.configId" placeholder="选择已验证的模型配置" style="width: 100%">
          <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id">
            <span>{{ c.name }}</span>
            <span class="opt-meta">{{ c.model }}</span>
          </el-option>
        </el-select>
      </el-form-item>
      <el-form-item v-else-if="model.source === 'gguf'" label="GGUF 模型">
        <span v-if="llama">llama.cpp · {{ llama.name }}</span>
        <span v-else class="hint warn">llama.cpp 没有运行：请先到「llama.cpp」页启动</span>
      </el-form-item>
      <el-form-item v-else label="本地模型">
        <el-select v-model="model.baseId" placeholder="选择基础模型" style="width: 100%">
          <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" :disabled="m.exists === false" />
        </el-select>
      </el-form-item>

      <el-form-item label="范围">
        <el-radio-group v-model="scope.mode">
          <el-radio value="all">全部 {{ entities.length }} 个实体</el-radio>
          <el-radio value="selected" :disabled="!selectedKeys.length">实体档案里勾选的 {{ selectedKeys.length }} 个</el-radio>
          <el-radio value="top">事实最多的前</el-radio>
        </el-radio-group>
        <el-input-number v-if="scope.mode === 'top'" v-model="scope.topN" :min="1" :max="5000" :step="50" size="small" class="top-n" />
      </el-form-item>
      <el-form-item label="分类">
        <el-checkbox-group v-model="scope.categories">
          <el-checkbox v-for="c in presentCategories" :key="c.code" :value="c.code">{{ c.label }}（{{ c.count }}）</el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="剧情段">
        <el-switch v-model="scope.plot" />
        <span class="hint">从章节摘要里找跨章的完整剧情段，存成去掉人名地名的骨架（起因 / 冲突 / 转折 / 结果）</span>
      </el-form-item>
      <el-alert type="info" :closable="false" show-icon :title="estimate" />
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :disabled="!canStart" :loading="starting" @click="confirm">开始整理（{{ chosen.length }} 个实体）</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { MATERIAL_CATEGORIES } from '@/api/material'
import { listModels as listConfigs } from '@/api/aiModel'
import { isGenerationModel, listModels as listLocalModels, runningLlama } from '@/api/localModel'
import { compileExtract } from '@/api/novel'
import { errorMessage } from '@/api/request'
import { costOf, formatCost, priceOf } from '@/utils/modelPricing'

/** 整理卡片：对一次成功的提取，按范围把实体档案整理成素材卡（结果进入待确认） */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  extractId: { type: Number, default: null },
  fileName: { type: String, default: '' },
  entities: { type: Array, default: () => [] }, // 实体档案（已按事实数排序）
  selectedKeys: { type: Array, default: () => [] }, // 实体档案里勾选的实体键
  chapterCount: { type: Number, default: 0 }
})
const emit = defineEmits(['update:modelValue', 'started'])

const STORE_KEY = 'nan_novel.compile.model'
// 实测（《耐瑟瑞尔》前 6 章）：GGUF Qwen3-4B 约 18 秒一张；大模型并发约 1.5 秒；本地 transformers 约 45 秒
const CARD_SECONDS = { gguf: 18, api: 1.5, local: 45 }
const CARD_TOKENS = { input: 500, output: 600 }
const ARC_WINDOW = 17 // 剧情段每窗约 17 章新内容，一窗一次调用

const model = reactive({ source: 'api', configId: null, baseId: '', ...readSaved() })
const scope = reactive({ mode: 'all', topN: 200, categories: [], plot: true })
const configs = ref([])
const localModels = ref([])
const llama = ref(null)
const starting = ref(false)

function readSaved() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE_KEY) || 'null')
    return v && typeof v === 'object' ? { source: v.source || 'api', configId: v.configId ?? null, baseId: v.baseId || '' } : {}
  } catch {
    return {}
  }
}

const presentCategories = computed(() =>
  MATERIAL_CATEGORIES.map((c) => ({ ...c, count: props.entities.filter((e) => e.category === c.code).length })).filter((c) => c.count)
)

const chosen = computed(() => {
  const cats = new Set(scope.categories)
  let list = props.entities.filter((e) => cats.has(e.category))
  if (scope.mode === 'selected') {
    const keys = new Set(props.selectedKeys)
    list = list.filter((e) => keys.has(e.key))
  }
  return scope.mode === 'top' ? list.slice(0, scope.topN) : list
})

const estimate = computed(() => {
  // 只有 1 条事实的实体 5 个一批
  const multi = chosen.value.filter((e) => (e.facts?.length || 0) >= 2).length
  const calls = multi + Math.ceil((chosen.value.length - multi) / 5) + (scope.plot ? Math.ceil(props.chapterCount / ARC_WINDOW) : 0)
  const sec = calls * CARD_SECONDS[model.source]
  const time = sec < 3600 ? `${Math.max(1, Math.round(sec / 60))} 分钟` : `${(sec / 3600).toFixed(1)} 小时`
  if (model.source !== 'api') return `约 ${calls} 次调用，预计 ${time}，不花钱；可以随时暂停，中断后继续`
  const cfg = configs.value.find((c) => c.id === model.configId)
  const usage = { promptTokens: calls * CARD_TOKENS.input, completionTokens: calls * CARD_TOKENS.output }
  const price = priceOf(cfg?.model)
  const cost = price ? `，约 ${formatCost(costOf(usage, price), price.currency)}` : ''
  return `约 ${calls} 次调用、${((usage.promptTokens + usage.completionTokens) / 1e6).toFixed(2)}M tokens，预计 ${time}${cost}`
})

const canStart = computed(() => {
  if (!chosen.value.length) return false
  if (model.source === 'gguf') return !!llama.value
  return model.source === 'local' ? !!model.baseId : !!model.configId
})

async function onOpen() {
  scope.mode = props.selectedKeys.length ? 'selected' : 'all'
  scope.categories = presentCategories.value.map((c) => c.code)
  runningLlama().then((l) => (llama.value = l))
  try {
    const res = await listConfigs()
    configs.value = res.code === 0 ? (res.data || []).filter((c) => c.status === 'VERIFIED') : []
    if (!configs.value.some((c) => c.id === model.configId)) {
      model.configId = (configs.value.find((c) => c.active) || configs.value[0])?.id ?? null
    }
  } catch {
    configs.value = []
  }
  try {
    const res = await listLocalModels()
    localModels.value = res.code === 0 ? (res.data || []).filter(isGenerationModel) : []
  } catch {
    localModels.value = [] // AI 服务没开：本地模型不可选
  }
}

function close() {
  emit('update:modelValue', false)
}

async function confirm() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(model))
  } catch {
    // 隐私模式等：不记住也能用
  }
  const m =
    model.source === 'gguf'
      ? { source: 'gguf' }
      : model.source === 'local'
        ? { source: 'local', baseId: model.baseId }
        : { source: 'api', configId: model.configId }
  const body = { model: m, plot: scope.plot }
  const allCats = scope.categories.length === presentCategories.value.length
  if (scope.mode === 'selected') body.entityKeys = chosen.value.map((e) => e.key)
  else if (!allCats) body.categories = [...scope.categories]
  if (scope.mode === 'top') body.topN = scope.topN
  starting.value = true
  try {
    const res = await compileExtract(props.extractId, body)
    if (res.code !== 0) throw new Error(res.message || '发起失败')
    ElMessage.success('已开始整理卡片')
    emit('started', res.data)
    close()
  } catch (e) {
    ElMessage.error(errorMessage(e, '发起整理卡片失败'))
  } finally {
    starting.value = false
  }
}
</script>

<style scoped>
.intro {
  margin: 0 0 14px;
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
.hint {
  margin-left: 10px;
  font-size: 12px;
  line-height: 1.5;
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
.top-n {
  margin-left: 8px;
  width: 120px;
}
</style>
