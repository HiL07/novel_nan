<template>
  <div class="identity-test">
    <div class="muted">
      辨识度测试：AI 出 6 个情境 + 2 个保护性问题，让「适配版本 A」和「只有名字和身份的对照 B」各演一遍；评委看不到谁是谁（匿名、打乱），
      按扣分制打分，并检查核心特征体现 / 违背、是否说出「不该知道」的原世界知识；再做心理访谈（原型在原世界 vs 适配版）和一致性复测。
    </div>
    <div class="ops">
      <span>演员</span>
      <ModelPicker v-model="model" store-key="nan_novel.persona.testModel" />
      <span>评委</span>
      <el-select v-model="judgeId" size="small" clearable placeholder="同一个模型" class="judge">
        <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <el-button v-if="adaptation.testStatus !== 'RUNNING'" type="primary" size="small" :loading="starting" @click="start">开始测试</el-button>
      <el-button v-else size="small" @click="cancel">取消</el-button>
    </div>
    <div v-if="adaptation.testStatus" class="status">
      <el-progress v-if="adaptation.testStatus === 'RUNNING'" :percentage="adaptation.testProgress || 0" :stroke-width="10" />
      <span :class="adaptation.testStatus === 'FAILED' ? 'err' : 'muted'">{{ adaptation.testMessage }}</span>
    </div>

    <el-select v-if="tests.length > 1" v-model="reportIndex" size="small" class="history">
      <el-option v-for="(t, i) in tests" :key="i" :value="i" :label="`${t.at} · A ${t.summary?.scoreA} / B ${t.summary?.scoreB}`" />
    </el-select>
    <template v-if="report">
      <div class="stats">
        <el-statistic title="A 平均分" :value="s.scoreA" />
        <el-statistic title="对照 B 平均分" :value="s.scoreB" />
        <el-statistic title="评委选中 A" :value="pct(s.pickedA)" suffix="%" />
        <el-statistic title="核心体现率 A / B" :value="`${pct(s.manifestA)}% / ${pct(s.manifestB)}%`" />
        <el-statistic title="核心违背次数" :value="s.violationsA" />
        <el-statistic title="原世界知识泄漏" :value="s.leaks" />
        <el-statistic title="访谈一致" :value="s.interviewAgreement == null ? '—' : pct(s.interviewAgreement) + '%'" />
        <el-statistic title="复测一致" :value="s.consistency == null ? '—' : pct(s.consistency) + '%'" />
      </div>
      <div class="muted">模型 {{ report.model }} · 评委 {{ report.judge }} · {{ report.at }}</div>
      <el-collapse class="detail">
        <el-collapse-item v-for="(sc, i) in report.scenes" :key="i" :name="i">
          <template #title>
            <el-tag size="small" :type="sc.pickedA ? 'success' : 'danger'">{{ sc.pickedA ? '选中 A' : '选中 B' }}</el-tag>
            <span class="t">{{ sc.situation }} · A {{ sc.judgeA.score }} / B {{ sc.judgeB.score }}</span>
          </template>
          <p class="scene">{{ sc.scene }}</p>
          <div class="pair">
            <div><b>A（适配版本）</b><p>{{ sc.a }}</p><Flaws :j="sc.judgeA" /></div>
            <div><b>B（对照）</b><p>{{ sc.b }}</p><Flaws :j="sc.judgeB" /></div>
          </div>
          <p v-if="sc.reason" class="muted">评委：{{ sc.reason }}</p>
        </el-collapse-item>
        <el-collapse-item v-if="report.protective?.length" name="prot" title="保护性测试（不该知道的事）">
          <div v-for="(p, i) in report.protective" :key="i" class="prot">
            <b>{{ p.term }}</b>：{{ p.scene }}<p>{{ p.reply }}</p>
            <el-tag size="small" :type="p.leaked?.length ? 'danger' : 'success'">{{ p.leaked?.length ? '泄漏：' + p.leaked.join('、') : '没有泄漏' }}</el-tag>
          </div>
        </el-collapse-item>
        <el-collapse-item v-if="report.interview" name="iv" title="心理访谈：原型（原世界）vs 适配版">
          <div v-for="(q, i) in report.interview.questions" :key="i" class="prot">
            <b>{{ q }}</b> <el-tag size="small">{{ report.interview.verdicts?.[i] || '—' }}</el-tag>
            <div class="pair"><p>原型：{{ report.interview.prototype?.[i] }}</p><p>适配：{{ report.interview.adapted?.[i] }}</p></div>
          </div>
          <p v-if="report.interview.note" class="muted">{{ report.interview.note }}</p>
        </el-collapse-item>
      </el-collapse>
    </template>
  </div>
</template>

<script setup>
import { computed, h, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { cancelIdentityTest, getAdaptation, startIdentityTest } from '@/api/persona'
import { listModels as listConfigs } from '@/api/aiModel'
import { errorMessage } from '@/api/request'
import ModelPicker from './ModelPicker.vue'

const props = defineProps({ adaptation: { type: Object, required: true } })
const emit = defineEmits(['update'])
const model = ref({ source: 'api', configId: null, baseId: '' })
const judgeId = ref(null)
const configs = ref([])
const starting = ref(false)
const reportIndex = ref(0)
let timer = null

const Flaws = (p) => h('div', { class: 'flaws' }, [
  ...(p.j.flaws || []).map((f) => h('div', { class: 'flaw' }, `−${f.severity * 4} ${f.issue}`)),
  h('div', { class: 'muted' }, `体现 ${p.j.traits?.['体现'] ?? 0} · 未体现 ${p.j.traits?.['未体现'] ?? 0} · 违背 ${p.j.traits?.['违背'] ?? 0}`)
])

const tests = computed(() => props.adaptation.tests || [])
const report = computed(() => tests.value[reportIndex.value])
const s = computed(() => report.value?.summary || {})
const pct = (v) => (v == null ? 0 : Math.round(v * 100))

listConfigs().then((res) => (configs.value = res.code === 0 ? (res.data || []).filter((c) => c.status === 'VERIFIED') : [])).catch(() => {})

function body() {
  const m = model.value
  const mb = m.source === 'local' ? { source: 'local', baseId: m.baseId } : m.source === 'gguf' ? { source: 'gguf' } : { source: 'api', configId: m.configId }
  return { model: mb, judgeConfigId: judgeId.value || undefined }
}

async function start() {
  starting.value = true
  try {
    const res = await startIdentityTest(props.adaptation.id, body())
    if (res.code !== 0) throw new Error(res.message)
    emit('update', res.data)
  } catch (e) {
    ElMessage.error(errorMessage(e, '开始测试失败'))
  } finally {
    starting.value = false
  }
}

async function cancel() {
  const res = await cancelIdentityTest(props.adaptation.id)
  if (res.code === 0) emit('update', res.data)
}

async function poll() {
  const res = await getAdaptation(props.adaptation.id).catch(() => null)
  if (res?.code === 0) {
    emit('update', res.data)
    if (res.data.testStatus !== 'RUNNING') reportIndex.value = 0
  }
}

watch(() => props.adaptation.testStatus, (st) => {
  clearInterval(timer)
  if (st === 'RUNNING') timer = setInterval(poll, 3000)
}, { immediate: true })
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.muted { font-size: 12px; color: var(--el-text-color-secondary); }
.err { font-size: 12px; color: var(--el-color-danger); }
.ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.judge { width: 180px; }
.status { margin-bottom: 10px; }
.history { width: 320px; margin-bottom: 10px; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 8px; }
.detail { margin-top: 12px; }
.t { margin-left: 8px; }
.scene { color: var(--el-text-color-regular); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pair p { white-space: pre-wrap; font-size: 13px; }
.prot { margin-bottom: 10px; font-size: 13px; }
:deep(.flaw) { font-size: 12px; color: var(--el-color-danger); }
</style>
