<template>
  <div class="bd">
    <EntityOverview
      :entities="entities"
      :appear="appear"
      :rows="rows"
      :base="base"
      :read-cis="readCis"
      :extract-id="extractId"
      :can-apply="canApply"
      @jump="(i) => emit('jump', i)"
      @apply="(list, done, msg) => emit('apply', list, done, msg)"
    />

    <el-collapse v-if="pacing && pacing.carded" v-model="aiOpen" class="ai-collapse">
      <el-collapse-item name="ai">
        <template #title>
          <span class="ai-title">写法统计（给 AI 学习用）</span>
          <span class="muted">钩子 = 吊住读者往下看的地方，爽点 = 兑现给读者的满足感；这些主要用来让 AI 学这本书的节奏，可以不看</span>
        </template>
      <!-- 统计卡 -->
      <section class="tiles">
        <div class="tile">
          <div class="tile-num">{{ pacing.payoffsPerChapter }}</div>
          <div class="tile-label">每章爽点</div>
        </div>
        <div class="tile">
          <div class="tile-num">{{ pct(pacing.endHookRate) }}</div>
          <div class="tile-label">章末有钩子</div>
        </div>
        <div class="tile clickable" :title="gapTip" @click="gap.length && emit('jump', gap.from)">
          <div class="tile-num">{{ gap.length }} 章</div>
          <div class="tile-label">最长没有爽点<template v-if="gap.length">（第 {{ no(gap.from) }}–{{ no(gap.to) }} 章）</template></div>
        </div>
        <div class="tile">
          <div class="tile-num">{{ pacing.threads.planted }} / {{ pacing.threads.paid }}</div>
          <div class="tile-label">伏笔 埋 / 收<template v-if="pacing.threads.avgDistance != null">，平均隔 {{ pacing.threads.avgDistance }} 章回收</template></div>
        </div>
        <div class="tile">
          <div class="tile-num">{{ pct(pacing.amplifiedRate) }}</div>
          <div class="tile-label">爽点写了旁观者反应</div>
        </div>
        <div v-if="pacing.style?.dialogRatio" class="tile">
          <div class="tile-num">{{ pct(pacing.style.dialogRatio) }}</div>
          <div class="tile-label">对白占比 · 平均段长 {{ pacing.style.avgParagraph }} 字</div>
        </div>
      </section>
      <p class="muted">统计只算读完的 {{ pacing.carded }} 章（共 {{ pacing.chapters }} 章有记录）；这些数据主要给 AI 用（节奏配方、写法素材），这里只是展示。</p>

      <!-- 节奏曲线 -->
      <section>
        <div class="sec-head">
          <h4>节奏曲线</h4>
          <span class="muted">柱高 = 本章最强爽点（1–3）<template v-if="bucket > 1">，每根柱 = {{ bucket }} 章取最强</template>；下方小块 = 章末钩子（越深越强）。点柱子看那一章</span>
          <el-switch v-model="asTable" size="small" active-text="表格" />
        </div>
        <div v-if="!asTable" class="curve-wrap">
          <svg :viewBox="`0 0 ${W} ${H}`" class="curve" role="img" aria-label="每章爽点强度与章末钩子">
            <line v-for="y in [1, 2, 3]" :key="y" :x1="PADL" :x2="W" :y1="yOf(y)" :y2="yOf(y)" class="grid" />
            <text v-for="y in [1, 2, 3]" :key="'t' + y" :x="PADL - 6" :y="yOf(y) + 4" class="axis" text-anchor="end">{{ y }}</text>
            <g
              v-for="(b, i) in bars"
              :key="i"
              class="bar-g"
              @mouseenter="hover = { ...b, x: xOf(i) + barW / 2 }"
              @mouseleave="hover = null"
              @click="emit('jump', b.from)"
            >
              <rect :x="xOf(i)" :y="0" :width="slot" :height="H" class="hit" />
              <path v-if="b.peak" :d="barPath(xOf(i), yOf(b.peak), barW, yOf(0) - yOf(b.peak))" class="bar" />
              <rect
                v-if="b.endHook"
                :x="xOf(i)"
                :y="yOf(0) + 6"
                :width="barW"
                height="6"
                rx="2"
                class="hook"
                :style="{ opacity: 0.35 + 0.22 * b.endHook }"
              />
            </g>
            <line :x1="PADL" :x2="W" :y1="yOf(0)" :y2="yOf(0)" class="base" />
            <text :x="PADL" :y="H - 2" class="axis">第 {{ no(bars[0]?.from) }} 章</text>
            <text :x="W" :y="H - 2" class="axis" text-anchor="end">第 {{ no(bars[bars.length - 1]?.to) }} 章</text>
          </svg>
          <div v-if="hover" class="tip" :style="{ left: `${(hover.x / W) * 100}%` }">
            <b>{{ hover.from === hover.to ? `第 ${no(hover.from)} 章` : `第 ${no(hover.from)}–${no(hover.to)} 章` }}</b>
            <div>爽点 {{ hover.count }} 个，最强 {{ hover.peak || '无' }}</div>
            <div>章末钩子：{{ hover.endHookText || '无' }}</div>
            <div v-if="hover.function">本章功能：{{ hover.function }}</div>
          </div>
        </div>
        <el-table v-else :data="curveRows" size="small" max-height="320" @row-click="(r) => emit('jump', r.ci)">
          <el-table-column label="章" width="70"><template #default="{ row }">{{ no(row.ci) }}</template></el-table-column>
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column prop="function" label="功能" width="80" />
          <el-table-column prop="payoffCount" label="爽点数" width="70" />
          <el-table-column prop="payoffPeak" label="最强" width="60" />
          <el-table-column label="章末钩子" width="110">
            <template #default="{ row }">{{ row.endHook ? `${row.endHook.type}${'★'.repeat(row.endHook.strength || 1)}` : '-' }}</template>
          </el-table-column>
        </el-table>
      </section>

      <!-- 类型分布 -->
      <section class="dists">
        <div v-for="d in dists" :key="d.title" class="dist">
          <h4>{{ d.title }}</h4>
          <div v-for="t in d.items.slice(0, 8)" :key="t.type" class="dist-row" :title="`${t.type}：${t.count}`">
            <span class="dist-label">{{ t.type }}</span>
            <span class="dist-track"><span class="dist-bar" :style="{ width: `${(t.count / d.max) * 100}%` }" /></span>
            <span class="dist-num">{{ t.count }}</span>
          </div>
          <div v-if="!d.items.length" class="muted">没有</div>
        </div>
      </section>

      <!-- 伏笔表 -->
      <section>
        <div class="sec-head">
          <h4>伏笔 / 悬念 / 承诺（{{ threads.length }}）</h4>
          <el-radio-group v-model="threadFilter" size="small">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="open">未回收</el-radio-button>
            <el-radio-button value="paid">已回收</el-radio-button>
          </el-radio-group>
        </div>
        <el-table :data="shownThreads" size="small" max-height="360" @row-click="(r) => emit('jump', r.plantCi)">
          <el-table-column prop="id" label="编号" width="64" />
          <el-table-column prop="kind" label="类型" width="64" />
          <el-table-column prop="text" label="内容" min-width="220" show-overflow-tooltip />
          <el-table-column label="埋于" width="70"><template #default="{ row }">第 {{ no(row.plantCi) }} 章</template></el-table-column>
          <el-table-column label="推进" min-width="120">
            <template #default="{ row }">
              <span v-if="!row.advances.length" class="muted">-</span>
              <el-tag
                v-for="(a, i) in row.advances"
                :key="i"
                size="small"
                :type="a.act === 'payoff' ? 'success' : 'info'"
                class="adv"
                :title="a.text"
                @click.stop="emit('jump', a.ci)"
              >{{ a.act === 'payoff' ? '收' : '推' }} {{ no(a.ci) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="70">
            <template #default="{ row }">{{ row.status === 'paid' ? '已回收' : '未回收' }}</template>
          </el-table-column>
        </el-table>
      </section>

      <!-- 主角成长线 -->
      <section v-if="pacing.leadLine?.length">
        <h4>主角变化（{{ pacing.leadLine.length }}）</h4>
        <div class="lead-line">
          <div v-for="(l, i) in pacing.leadLine.slice(0, leadLimit)" :key="i" class="lead-item" @click="emit('jump', l.ci)">
            <span class="lead-ch">第 {{ no(l.ci) }} 章</span>
            <el-tag size="small" effect="plain">{{ l.field }}</el-tag>
            <span>{{ l.after }}</span>
          </div>
          <el-button v-if="pacing.leadLine.length > leadLimit" link type="primary" @click="leadLimit += 30">再显示 30 条</el-button>
        </div>
      </section>

      <!-- 案例检索 -->
      <section>
        <div class="sec-head">
          <h4>检索案例</h4>
          <el-input v-model="caseQuery" size="small" clearable placeholder="在钩子 / 爽点 / 事件 / 一句话里找，空格 = 同时包含，如「打脸 旁观」" class="case-input" />
        </div>
        <div v-if="caseQuery.trim()" class="cases">
          <div v-for="(c, i) in cases.slice(0, 50)" :key="i" class="case" @click="emit('jump', c.idx)">
            <span class="lead-ch">第 {{ c.idx + 1 }} 章</span>
            <el-tag size="small" effect="plain">{{ c.kind }}</el-tag>
            <span>{{ c.text }}</span>
            <div v-if="c.quote" class="quote">「{{ c.quote }}」</div>
          </div>
          <div v-if="!cases.length" class="muted">没找到</div>
          <div v-else-if="cases.length > 50" class="muted">只显示前 50 条（共 {{ cases.length }} 条）</div>
        </div>
      </section>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import EntityOverview from './EntityOverview.vue'

/**
 * 拆书视图（docs/素材提取改造方案.md §7.1，先不含报告）：统计卡、节奏曲线、类型分布、伏笔表、主角成长线、案例检索。
 * pacing / threads 的 ci 是范围内序号；base = range.from − 1，换成全书下标 idx = base + ci（jump 发出的是 idx）。
 * rows = 全书下标 → 章节卡行（案例检索用），chapters = 全书分章（标题）。
 */
const props = defineProps({
  pacing: { type: Object, default: null },
  threads: { type: Array, default: () => [] },
  rows: { type: Object, default: () => ({}) },
  chapters: { type: Array, default: () => [] },
  base: { type: Number, default: 0 },
  entities: { type: Array, default: () => [] },
  appear: { type: Object, default: () => ({}) },
  extractId: { type: [Number, String], default: null },
  canApply: { type: Boolean, default: false }
})
const aiOpen = ref([])
// 已读的章（范围内序号）：有章节卡的行
const readCis = computed(() =>
  Object.entries(props.rows)
    .filter(([, r]) => r.status === 'done' || r.status === 'partial')
    .map(([idx]) => +idx - props.base)
    .sort((a, b) => a - b)
)
const emit = defineEmits(['jump', 'apply'])

const W = 900
const H = 120
const PADL = 22
const MAX_BARS = 120
const asTable = ref(false)
const hover = ref(null)
const threadFilter = ref('all')
const leadLimit = ref(30)
const caseQuery = ref('')

const no = (ci) => (ci == null ? '' : props.base + ci + 1)
const pct = (v) => `${Math.round((v || 0) * 100)}%`
const gap = computed(() => props.pacing?.longestPayoffGap || { length: 0 })
const gapTip = computed(() => (gap.value.length ? '点一下跳到那几章' : ''))

/* ---------- 曲线：章数多时按区间聚合（取最强），避免柱子细到看不见 ---------- */
const bucket = computed(() => Math.max(1, Math.ceil((props.pacing?.curve?.length || 0) / MAX_BARS)))
const bars = computed(() => {
  const curve = (props.pacing?.curve || []).filter((p) => p.carded)
  const out = []
  for (let i = 0; i < curve.length; i += bucket.value) {
    const g = curve.slice(i, i + bucket.value)
    const ends = g.map((p) => p.endHook).filter(Boolean)
    const best = ends.sort((a, b) => (b.strength || 0) - (a.strength || 0))[0]
    out.push({
      from: g[0].ci,
      to: g[g.length - 1].ci,
      peak: Math.max(...g.map((p) => p.payoffPeak)),
      count: g.reduce((n, p) => n + p.payoffCount, 0),
      endHook: best ? best.strength || 1 : 0,
      endHookText: best ? `${best.type}${'★'.repeat(best.strength || 1)}` + (g.length > 1 ? `（${ends.length}/${g.length} 章有）` : '') : '',
      function: g.length === 1 ? g[0].function : ''
    })
  }
  return out
})
const slot = computed(() => (W - PADL) / Math.max(1, bars.value.length))
const barW = computed(() => Math.max(2, Math.min(18, slot.value - 2))) // 柱间至少留 2px 空
const xOf = (i) => PADL + i * slot.value + (slot.value - barW.value) / 2
const yOf = (v) => 8 + ((3 - v) / 3) * (H - 40)
function barPath(x, y, w, h) {
  // 顶端 4px 圆角，底端贴着基线
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`
}
const curveRows = computed(() =>
  (props.pacing?.curve || []).map((p) => ({ ...p, title: props.chapters.find((c) => c.idx === props.base + p.ci)?.title || '' }))
)

/* ---------- 类型分布 ---------- */
const dists = computed(() => {
  const p = props.pacing || {}
  return [
    { title: '爽点类型', items: p.payoffTypes || [] },
    { title: '章末钩子类型', items: p.endHookTypes || [] },
    { title: '本章功能', items: p.functions || [] }
  ].map((d) => ({ ...d, max: Math.max(1, ...d.items.map((t) => t.count)) }))
})

/* ---------- 伏笔 ---------- */
const shownThreads = computed(() =>
  props.threads.filter((t) => threadFilter.value === 'all' || (threadFilter.value === 'paid') === (t.status === 'paid'))
)

/* ---------- 案例检索：前端关键词匹配（空格 = 且） ---------- */
const cases = computed(() => {
  const words = caseQuery.value.trim().split(/\s+/).filter(Boolean)
  if (!words.length) return []
  const hit = (s) => words.every((w) => s.includes(w))
  const out = []
  for (const [idx, r] of Object.entries(props.rows)) {
    const c = r.card || {}
    const push = (kind, text, quote) => hit(`${kind} ${text} ${quote || ''}`) && out.push({ idx: +idx, kind, text, quote })
    if (c.oneLine) push('一句话', c.oneLine)
    for (const e of c.events || []) push('事件', e)
    for (const h of c.hooks || []) push(`钩子·${h.type}`, h.text, h.quote)
    for (const p of c.payoffs || []) push(`爽点·${p.type}${p.amplified ? '·旁观' : ''}`, p.setup ? `铺垫：${p.setup}` : '', p.quote)
  }
  return out.sort((a, b) => a.idx - b.idx)
})
</script>

<style scoped>
.bd {
  font-size: 13px;
}
.ai-collapse {
  margin-top: 8px;
}
.ai-title {
  margin-right: 12px;
  font-size: 14px;
  font-weight: 600;
}
.ai-collapse :deep(.el-collapse-item__content) {
  padding-top: 12px;
}
section {
  margin-bottom: 22px;
}
h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.sec-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.sec-head h4 {
  margin: 0;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
  margin-bottom: 8px;
}
.tile {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--ws-card, var(--el-bg-color));
}
.tile.clickable {
  cursor: pointer;
}
.tile-num {
  font-size: 22px;
  font-family: var(--ws-font-title, inherit);
  color: var(--el-text-color-primary);
}
.tile-label {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.curve-wrap {
  position: relative;
}
.curve {
  width: 100%;
  height: 150px;
  display: block;
}
.grid {
  stroke: var(--el-border-color-lighter);
  stroke-width: 1;
}
.base {
  stroke: var(--el-border-color);
  stroke-width: 1;
}
.axis {
  font-size: 11px;
  fill: var(--el-text-color-secondary);
}
.bar {
  fill: var(--el-color-primary-light-3);
}
.hook {
  fill: var(--el-color-primary);
}
.hit {
  fill: transparent;
}
.bar-g {
  cursor: pointer;
}
.bar-g:hover .bar {
  fill: var(--el-color-primary);
}
.tip {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  padding: 6px 8px;
  border-radius: 4px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--el-box-shadow-light);
  font-size: 12px;
  color: var(--el-text-color-primary);
  pointer-events: none;
  white-space: nowrap;
}
.dists {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}
.dist-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.dist-label {
  width: 56px;
  flex: none;
  color: var(--el-text-color-regular);
}
.dist-track {
  flex: 1;
  height: 8px;
}
.dist-bar {
  display: block;
  height: 8px;
  border-radius: 0 4px 4px 0;
  background: var(--el-color-primary-light-3);
}
.dist-num {
  width: 28px;
  text-align: right;
  color: var(--el-text-color-secondary);
}
.adv {
  margin: 0 4px 2px 0;
  cursor: pointer;
}
.lead-line,
.cases {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.lead-item,
.case {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  padding: 3px 4px;
  border-radius: 4px;
  cursor: pointer;
}
.lead-item:hover,
.case:hover {
  background: var(--el-fill-color-light);
}
.lead-ch {
  flex: none;
  width: 64px;
  color: var(--el-text-color-secondary);
}
.case .quote {
  width: 100%;
  padding-left: 72px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.case-input {
  max-width: 420px;
}
</style>
