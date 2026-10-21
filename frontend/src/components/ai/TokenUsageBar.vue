<template>
  <div v-if="usage" class="token-usage">
    <el-tag :type="SOURCE[source].type" size="small" effect="plain">{{ SOURCE[source].label }}</el-tag>
    <span class="model">{{ usage.model }}<span v-if="source === 'local' && usage.host" class="dim"> @ {{ usage.host }}</span></span>
    <span>调用 {{ usage.calls || 0 }} 次</span>
    <span>
      输入 {{ fmt(usage.promptTokens) }}
      <span v-if="usage.cacheHitTokens" class="dim">（缓存命中 {{ fmt(usage.cacheHitTokens) }}）</span>
    </span>
    <span>输出 {{ fmt(usage.completionTokens) }}</span>
    <span>合计 {{ fmt((usage.promptTokens || 0) + (usage.completionTokens || 0)) }} token</span>
    <template v-if="source === 'api'">
      <span class="cost">费用 ≈ {{ price ? formatCost(cost, price.currency) : '未知单价' }}</span>
      <el-popover v-model:visible="editing" placement="bottom" :width="300" trigger="click">
        <template #reference>
          <el-button link type="primary" size="small" @click="openEdit">
            {{ price ? `单价：入 ${sign}${price.input} / 出 ${sign}${price.output} 每百万${price.custom ? '（自定义）' : '（参考价）'}` : '设置单价' }}
          </el-button>
        </template>
        <div class="price-form">
          <div class="dim">「{{ usage.model }}」每百万 token 单价，存在本机；内置价可能过时，以厂商账单为准。</div>
          <el-radio-group v-model="form.currency" size="small">
            <el-radio-button value="CNY">人民币 ¥</el-radio-button>
            <el-radio-button value="USD">美元 $</el-radio-button>
          </el-radio-group>
          <label>输入 <el-input-number v-model="form.input" :min="0" :step="0.1" :precision="4" size="small" controls-position="right" /></label>
          <label>缓存命中输入 <el-input-number v-model="form.cacheHit" :min="0" :step="0.1" :precision="4" size="small" controls-position="right" placeholder="同输入" /></label>
          <label>输出 <el-input-number v-model="form.output" :min="0" :step="0.1" :precision="4" size="small" controls-position="right" /></label>
          <div class="ops">
            <el-button size="small" @click="resetPrice">恢复内置价</el-button>
            <el-button size="small" type="primary" @click="savePrice">保存</el-button>
          </div>
        </div>
      </el-popover>
    </template>
    <span v-else-if="source === 'local'" class="dim">本机运行，不按 token 计费</span>
    <span v-else class="dim">远程 GPU 按时长计费，不按 token</span>
    <span v-if="live" class="dim">· 实时更新中</span>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { CURRENCY_SIGN, costOf, formatCost, priceOf, setCustomPrice } from '@/utils/modelPricing'

/** usage = {source: api|local|remote, model, host?, calls, promptTokens, completionTokens, cacheHitTokens?} */
const props = defineProps({
  usage: { type: Object, default: null },
  live: { type: Boolean, default: false }
})

const SOURCE = {
  api: { label: '大模型', type: 'primary' },
  local: { label: '本地模型', type: 'success' },
  remote: { label: '远程模型', type: 'warning' }
}

const source = computed(() => (SOURCE[props.usage?.source] ? props.usage.source : 'api'))
// 改单价后重算：priceOf 读 localStorage，不是响应式，用版本号触发
const priceVersion = ref(0)
const price = computed(() => (priceVersion.value, priceOf(props.usage?.model)))
const cost = computed(() => costOf(props.usage, price.value))
const sign = computed(() => CURRENCY_SIGN[price.value?.currency] || '')

const editing = ref(false)
const form = reactive({ currency: 'CNY', input: 0, cacheHit: undefined, output: 0 })

function openEdit() {
  const p = price.value
  Object.assign(form, { currency: p?.currency || 'CNY', input: p?.input ?? 0, cacheHit: p?.cacheHit, output: p?.output ?? 0 })
}

function savePrice() {
  setCustomPrice(props.usage.model, { ...form })
  priceVersion.value++
  editing.value = false
}

function resetPrice() {
  setCustomPrice(props.usage.model, null)
  priceVersion.value++
  editing.value = false
}

function fmt(n) {
  return (n || 0).toLocaleString()
}
</script>

<style scoped>
.token-usage {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  margin: 6px 0;
  font-size: 12px;
  color: #606266;
}
.model {
  font-weight: 600;
  color: #303133;
}
.cost {
  font-weight: 600;
  color: #e6a23c;
}
.dim {
  color: #909399;
  font-weight: normal;
}
.price-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
}
.price-form label {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ops {
  display: flex;
  justify-content: flex-end;
}
</style>
