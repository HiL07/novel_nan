<template>
  <div class="worldbook">
    <div class="intro muted">
      世界书把这个工作区的设定、人物内核、故事账本（人物的状态 / 目标 / 阻碍 / 关系 / 知道的秘密、伏笔、定时事件）、
      故事阶段和前情汇总在一起，是 AI 出走向时看到的「此刻的局面」。这里只读：设定在「设定」页改，人物局面和伏笔在「故事账本」页改。
      <el-button link type="primary" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>
    <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" class="mt" />

    <template v-if="wb">
      <div class="stats">
        <span>为第 {{ wb.chapter }} 章编译</span>
        <span>人物 {{ characters.length }}</span>
        <span>其他设定 {{ others.length }}</span>
        <span>未回收伏笔 {{ openThreads.length }}</span>
        <span>定时事件 {{ openClocks.length }}</span>
        <span v-if="stageLabel">阶段：{{ stageLabel }}</span>
        <el-button size="small" @click="showSnapshot = true">查看 AI 看到的局面</el-button>
      </div>

      <div class="section-head"><span class="col-title">人物局面</span>
        <span v-if="!hasGoals && characters.length" class="muted small">还没有人物的目标 / 关系：之后写的章节会自动记录，出走向时也会先整理一次</span>
      </div>
      <el-table :data="characters" size="small" empty-text="还没有人物">
        <el-table-column label="人物" width="150">
          <template #default="{ row }">
            <b>{{ row.name }}</b>
            <el-tag v-if="row.protagonist" size="small" type="danger" effect="plain">主角</el-tag>
            <el-tag v-if="row.source.type === 'persona' || hasPersona(row)" size="small" effect="plain">人物内核</el-tag>
            <el-tag v-if="row.notYet" size="small" type="info" effect="plain">第 {{ row.since }} 章登场</el-tag>
            <div v-if="row.role" class="muted small">{{ row.role }}</div>
          </template>
        </el-table-column>
        <el-table-column label="现在" min-width="160">
          <template #default="{ row }">
            <template v-if="row.state">{{ row.state.state || '—' }}<span class="muted small">（第{{ row.state.updatedIn }}章）</span></template>
            <span v-else class="muted">账本里还没有</span>
          </template>
        </el-table-column>
        <el-table-column label="想要 / 阻碍" min-width="180">
          <template #default="{ row }">
            <div v-if="row.state?.goal">想要：{{ row.state.goal }}</div>
            <div v-if="row.state?.obstacle">阻碍：{{ row.state.obstacle }}</div>
          </template>
        </el-table-column>
        <el-table-column label="关系" min-width="160">
          <template #default="{ row }">
            <div v-for="r in row.state?.relations || []" :key="r.to">{{ r.to }}：{{ r.rel }}</div>
          </template>
        </el-table-column>
        <el-table-column label="知道的秘密" min-width="180">
          <template #default="{ row }">
            <div v-for="(k, i) in row.state?.knows || []" :key="i">· {{ k }}</div>
          </template>
        </el-table-column>
        <el-table-column type="expand" width="40">
          <template #default="{ row }"><pre class="entry-text">{{ row.text || '（设定里没有这个人物，只在账本里出现过）' }}</pre></template>
        </el-table-column>
      </el-table>

      <el-alert v-if="wb.checks?.length" type="warning" :closable="false" show-icon class="mt" title="大纲 / 故事账本对不上的地方">
        <div v-for="(c, i) in wb.checks" :key="i">· {{ c }}</div>
      </el-alert>

      <template v-if="plannedThreads.length || plannedClocks.length">
        <div class="section-head"><span class="col-title">计划中（自动规划 / 大纲里定好、还没写出来的）</span></div>
        <div v-for="t in plannedThreads" :key="t.id" class="line" :class="{ overdue: t.plannedIn && t.plannedIn < wb.chapter }">
          <b>{{ t.id }}</b> {{ t.text }}
          <span class="muted small">计划第{{ t.plannedIn || '?' }}章埋<template v-if="t.payoffIn">，预计第{{ t.payoffIn }}章收</template></span>
          <el-tag v-if="t.plannedIn === wb.chapter" size="small" type="warning" effect="plain">下一章该埋</el-tag>
          <el-tag v-else-if="t.plannedIn && t.plannedIn < wb.chapter" size="small" type="danger" effect="plain">已超期</el-tag>
        </div>
        <div v-for="(k, i) in plannedClocks" :key="'k' + i" class="line">
          ⏳ {{ k.text }} <span class="muted small">计划第{{ k.plannedIn || '?' }}章定下<template v-if="k.dueIn">，第{{ k.dueIn }}章到期</template></span>
        </div>
      </template>

      <div class="section-head"><span class="col-title">未回收的伏笔 · 定时事件</span></div>
      <div class="two-col">
        <div>
          <div v-for="t in openThreads.slice(0, 30)" :key="t.id" class="line">
            <b>{{ t.id }}</b> {{ t.text }} <span class="muted small">第{{ t.plantedIn }}章埋下<template v-if="t.lastChapter !== t.plantedIn">，第{{ t.lastChapter }}章有进展</template></span>
          </div>
          <div v-if="openThreads.length > 30" class="muted small">还有 {{ openThreads.length - 30 }} 条，见「故事账本」</div>
          <div v-if="!openThreads.length" class="muted">没有未回收的伏笔</div>
        </div>
        <div>
          <div v-for="(k, i) in openClocks" :key="i" class="line">
            ⏳ {{ k.text }}<span v-if="k.due" class="muted">（{{ k.due }}）</span> <span class="muted small">第{{ k.chapter }}章定下</span>
          </div>
          <div v-if="!openClocks.length" class="muted">没有未到期的定时事件</div>
        </div>
      </div>

      <div class="section-head"><span class="col-title">设定</span></div>
      <el-collapse>
        <el-collapse-item v-for="e in others" :key="e.id" :name="e.id">
          <template #title>
            <span class="entry-title">{{ e.name }}</span>
            <el-tag size="small" effect="plain">{{ e.category }}</el-tag>
            <el-tag v-if="e.pinned" size="small" type="warning" effect="plain">常驻</el-tag>
            <el-tag v-else size="small" type="info" effect="plain">提到时才用</el-tag>
            <el-tag v-if="e.notYet" size="small" type="info" effect="plain">第 {{ e.since }} 章登场</el-tag>
          </template>
          <pre class="entry-text">{{ e.text }}</pre>
        </el-collapse-item>
      </el-collapse>
      <div v-if="wb.open?.length" class="muted small mt">尚未设定：{{ wb.open.join('、') }}（AI 可以在不矛盾的前提下自由发挥）</div>
    </template>

    <el-dialog v-model="showSnapshot" title="AI 看到的局面（走向引擎的输入）" width="760px">
      <pre class="snapshot">{{ wb?.snapshot }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getWorldbook } from '@/api/novelGen'
import { errorMessage } from '@/api/request'

const props = defineProps({
  novelId: { type: String, required: true },
  reloadKey: { type: [Number, String], default: 0 } // 章节完成 / 账本变化后重新编译
})

const PHASES = { opening: '开篇', early: '前期', mid: '中期', late: '后期' }
const wb = ref(null)
const loading = ref(false)
const error = ref('')
const showSnapshot = ref(false)

const characters = computed(() => (wb.value?.entries || [])
  .filter((e) => e.kind === 'character')
  .sort((a, b) => (b.protagonist ? 1 : 0) - (a.protagonist ? 1 : 0) || (b.state?.updatedIn || 0) - (a.state?.updatedIn || 0)))
const others = computed(() => (wb.value?.entries || []).filter((e) => e.kind !== 'character'))
const openThreads = computed(() => (wb.value?.threads || []).filter((t) => t.status === 'open')
  .sort((a, b) => b.lastChapter - a.lastChapter))
const openClocks = computed(() => (wb.value?.clocks || []).filter((k) => k.status === 'open'))
const plannedThreads = computed(() => (wb.value?.threads || []).filter((t) => t.status === 'planned')
  .sort((a, b) => (a.plannedIn || 999) - (b.plannedIn || 999)))
const plannedClocks = computed(() => (wb.value?.clocks || []).filter((k) => k.status === 'planned'))
const hasGoals = computed(() => characters.value.some((e) => e.state?.goal))
const stageLabel = computed(() => {
  const s = wb.value?.stage
  if (!s || !PHASES[s.phase]) return ''
  return PHASES[s.phase] + (s.tierMax ? `，对手不超过量级 ${s.tierMax}` : '')
})
const hasPersona = (e) => (e.text || '').includes('【人物内核·')

async function load() {
  loading.value = true
  try {
    const res = await getWorldbook(props.novelId)
    if (res.code !== 0) throw new Error(res.message)
    wb.value = res.data
    error.value = ''
  } catch (e) {
    error.value = errorMessage(e, '编译世界书失败')
  } finally {
    loading.value = false
  }
}
watch(() => [props.novelId, props.reloadKey], load, { immediate: true })
defineExpose({ load })
</script>

<style scoped>
.intro { font-size: 13px; line-height: 1.7; }
.mt { margin-top: 10px; }
.muted { color: var(--el-text-color-secondary); }
.small { font-size: 12px; }
.stats { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin: 12px 0; font-size: 13px; }
.section-head { display: flex; align-items: center; gap: 12px; margin: 18px 0 8px; }
.col-title { font-weight: 600; }
.two-col { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; font-size: 13px; }
.line { margin-bottom: 4px; line-height: 1.6; }
.line.overdue { color: var(--el-color-danger); }
.entry-title { margin-right: 8px; font-weight: 500; }
.entry-title + .el-tag, .el-tag + .el-tag { margin-left: 4px; }
.entry-text, .snapshot { white-space: pre-wrap; font-family: inherit; font-size: 13px; line-height: 1.7; margin: 0; }
.snapshot { max-height: 65vh; overflow: auto; }
</style>
