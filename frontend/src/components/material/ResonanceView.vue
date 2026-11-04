<template>
  <!-- 共鸣素材：关系图（SVG，简单力导向布局）/ 说明（综合描述、联动规则、融入指南、缺口）/ 3D（占位） -->
  <el-tabs v-model="tab" class="rv">
    <el-tab-pane label="关系图" name="graph">
      <div class="legend">
        <span v-for="(c, r) in ROLE_COLOR" :key="r" class="lg"><i :style="{ background: c }" />{{ r }}</span>
        <span class="muted">点节点看它的关系；点下面的联动规则，高亮「改了谁 → 影响谁」</span>
      </div>
      <svg :viewBox="`0 0 ${W} ${H}`" class="graph" @click.self="clear">
        <defs>
          <marker id="rv-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" class="arrow" />
          </marker>
        </defs>
        <g v-for="(e, i) in edges" :key="'e' + i" :class="['edge', { hot: edgeHot(e), dim: dimmed && !edgeHot(e) }]">
          <line :x1="pos[e.from]?.x" :y1="pos[e.from]?.y" :x2="end(e).x" :y2="end(e).y" marker-end="url(#rv-arrow)" />
          <text :x="(pos[e.from]?.x + pos[e.to]?.x) / 2" :y="(pos[e.from]?.y + pos[e.to]?.y) / 2 - 4" class="elabel">{{ e.type }}</text>
        </g>
        <g
          v-for="n in nodes"
          :key="n.id"
          :class="['node', { hot: nodeHot(n.id), dim: dimmed && !nodeHot(n.id) }]"
          :transform="`translate(${pos[n.id]?.x}, ${pos[n.id]?.y})`"
          @click.stop="pickNode(n.id)"
        >
          <circle :r="R" :style="{ fill: ROLE_COLOR[n.role] || ROLE_COLOR['其他'] }" />
          <text y="4" class="nlabel">{{ short(n.title) }}</text>
          <title>{{ n.title }}（{{ n.role }}）{{ n.note ? '：' + n.note : '' }}</title>
        </g>
      </svg>
      <div v-if="focusNode" class="focus">
        <b>{{ focusNode.title }}</b>
        <el-tag size="small" effect="plain">{{ focusNode.role }}</el-tag>
        <span class="muted">{{ focusNode.note }}</span>
        <el-button link type="primary" size="small" @click="emit('pick-card', focusNode.cardId)">打开原卡片</el-button>
        <div v-for="(e, i) in edges.filter((x) => x.from === focusNode.id || x.to === focusNode.id)" :key="i" class="muted">
          {{ titleOf(e.from) }} —{{ e.type }}→ {{ titleOf(e.to) }}<template v-if="e.note">：{{ e.note }}</template>
        </div>
      </div>
      <div class="rules">
        <div class="sec-title">联动规则（{{ rules.length }}）</div>
        <div v-for="(r, i) in rules" :key="i" class="rule" :class="{ on: ruleIdx === i }" @click="pickRule(i)">
          如果 <b>{{ titleOf(r.if.node) }}</b> {{ r.if.change }} →
          <span v-for="(t, j) in r.then" :key="j">
            <b>{{ titleOf(t.node) }}</b> {{ t.effect }}<template v-if="j < r.then.length - 1">；</template>
          </span>
        </div>
      </div>
    </el-tab-pane>

    <el-tab-pane label="说明" name="text">
      <p v-if="data.summary" class="lead">{{ data.summary }}</p>
      <p v-if="data.detail" class="detail">{{ data.detail }}</p>
      <div class="sec-title">节点（{{ nodes.length }}）</div>
      <div v-for="n in nodes" :key="n.id" class="line">
        <el-tag size="small" effect="plain">{{ n.role }}</el-tag>
        <el-button link type="primary" size="small" @click="emit('pick-card', n.cardId)">{{ n.title }}</el-button>
        <span class="muted">{{ n.note }}</span>
      </div>
      <div class="sec-title">联动规则</div>
      <div v-for="(r, i) in rules" :key="i" class="line">
        如果「{{ titleOf(r.if.node) }}」{{ r.if.change }}：
        <span v-for="(t, j) in r.then" :key="j">「{{ titleOf(t.node) }}」{{ t.effect }}<template v-if="j < r.then.length - 1">；</template></span>
      </div>
      <div class="sec-title">融入其他世界观</div>
      <div v-if="fusion.keep?.length" class="line">
        <b>可以直接保留：</b>
        <span v-for="(k, i) in fusion.keep" :key="i">「{{ titleOf(k.node) }}」{{ k.why }}<template v-if="i < fusion.keep.length - 1">；</template></span>
      </div>
      <div v-for="(r, i) in fusion.replace || []" :key="'r' + i" class="line">
        <b>替换「{{ titleOf(r.node) }}」</b>：{{ r.why }}<template v-if="r.hint"> → {{ r.hint }}</template>
      </div>
      <div v-if="fusion.cascade" class="line"><b>替换后要联动调整：</b>{{ fusion.cascade }}</div>
      <template v-if="data.gaps?.length">
        <div class="sec-title">原书还没讲清楚的（借用时自己补）</div>
        <div v-for="(g, i) in data.gaps" :key="i" class="line">· {{ g }}</div>
      </template>
    </el-tab-pane>

    <el-tab-pane label="3D" name="3d">
      <el-empty description="3D 展示之后实现" :image-size="60" />
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) } // 共鸣素材卡片的 data
})
const emit = defineEmits(['pick-card'])

const W = 680
const H = 440
const R = 22
// 节点颜色用主题变量（不写死 Element 默认色）
const ROLE_COLOR = {
  核心: 'var(--el-color-primary)',
  规则: 'var(--el-color-warning)',
  代价: 'var(--el-color-danger)',
  载体: 'var(--el-color-success)',
  组织: 'var(--el-color-primary-light-5)',
  人物: 'var(--el-color-success-light-5)',
  场所: 'var(--el-color-warning-light-5)',
  现象: 'var(--el-color-danger-light-5)',
  其他: 'var(--el-color-info-light-5)'
}

const tab = ref('graph')
const nodes = computed(() => props.data?.nodes || [])
const edges = computed(() => (props.data?.edges || []).filter((e) => pos.value[e.from] && pos.value[e.to]))
const rules = computed(() => props.data?.rules || [])
const fusion = computed(() => props.data?.fusion || {})
const data = computed(() => props.data || {})
const byId = computed(() => Object.fromEntries(nodes.value.map((n) => [n.id, n])))
const titleOf = (id) => byId.value[id]?.title || id
const short = (t) => (t && t.length > 5 ? t.slice(0, 5) + '…' : t)

/* ---------- 布局：圆周初始化 + 200 步力导向（节点 ≤15，直接算） ---------- */
const pos = ref({})
function layout() {
  const ns = nodes.value
  const es = props.data?.edges || []
  const p = {}
  ns.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, ns.length)
    p[n.id] = { x: W / 2 + 150 * Math.cos(a), y: H / 2 + 130 * Math.sin(a) }
  })
  const k = Math.sqrt((W * H) / Math.max(1, ns.length)) * 0.55
  for (let step = 0; step < 200; step++) {
    const disp = Object.fromEntries(ns.map((n) => [n.id, { x: 0, y: 0 }]))
    for (const a of ns) {
      for (const b of ns) {
        if (a.id === b.id) continue
        const dx = p[a.id].x - p[b.id].x
        const dy = p[a.id].y - p[b.id].y
        const d = Math.max(1, Math.hypot(dx, dy))
        disp[a.id].x += (dx / d) * ((k * k) / d)
        disp[a.id].y += (dy / d) * ((k * k) / d)
      }
    }
    for (const e of es) {
      if (!p[e.from] || !p[e.to]) continue
      const dx = p[e.from].x - p[e.to].x
      const dy = p[e.from].y - p[e.to].y
      const d = Math.max(1, Math.hypot(dx, dy))
      const f = (d * d) / k
      disp[e.from].x -= (dx / d) * f
      disp[e.from].y -= (dy / d) * f
      disp[e.to].x += (dx / d) * f
      disp[e.to].y += (dy / d) * f
    }
    const t = 20 * (1 - step / 200) + 1
    for (const n of ns) {
      const d = disp[n.id]
      const len = Math.max(1, Math.hypot(d.x, d.y))
      p[n.id].x += (d.x / len) * Math.min(len, t) + (W / 2 - p[n.id].x) * 0.01
      p[n.id].y += (d.y / len) * Math.min(len, t) + (H / 2 - p[n.id].y) * 0.01
      p[n.id].x = Math.min(W - R - 4, Math.max(R + 4, p[n.id].x))
      p[n.id].y = Math.min(H - R - 4, Math.max(R + 4, p[n.id].y))
    }
  }
  pos.value = p
}
watch(() => props.data, () => {
  layout()
  clear()
}, { immediate: true })

/** 箭头停在目标圆的边上 */
function end(e) {
  const a = pos.value[e.from]
  const b = pos.value[e.to]
  if (!a || !b) return { x: 0, y: 0 }
  const d = Math.max(1, Math.hypot(b.x - a.x, b.y - a.y))
  return { x: b.x - ((b.x - a.x) / d) * (R + 3), y: b.y - ((b.y - a.y) / d) * (R + 3) }
}

/* ---------- 高亮：选中节点 / 选中联动规则 ---------- */
const focusId = ref(null)
const ruleIdx = ref(-1)
const focusNode = computed(() => (focusId.value ? byId.value[focusId.value] : null))
const hotNodes = computed(() => {
  if (ruleIdx.value >= 0) {
    const r = rules.value[ruleIdx.value]
    return new Set([r.if.node, ...r.then.map((t) => t.node)])
  }
  if (focusId.value) {
    const s = new Set([focusId.value])
    edges.value.forEach((e) => {
      if (e.from === focusId.value) s.add(e.to)
      if (e.to === focusId.value) s.add(e.from)
    })
    return s
  }
  return null
})
const dimmed = computed(() => !!hotNodes.value)
const nodeHot = (id) => !!hotNodes.value?.has(id)
function edgeHot(e) {
  if (ruleIdx.value >= 0) {
    const r = rules.value[ruleIdx.value]
    return e.from === r.if.node && r.then.some((t) => t.node === e.to) || (hotNodes.value.has(e.from) && hotNodes.value.has(e.to))
  }
  return !!focusId.value && (e.from === focusId.value || e.to === focusId.value)
}
function pickNode(id) {
  ruleIdx.value = -1
  focusId.value = focusId.value === id ? null : id
}
function pickRule(i) {
  focusId.value = null
  ruleIdx.value = ruleIdx.value === i ? -1 : i
}
function clear() {
  focusId.value = null
  ruleIdx.value = -1
}
</script>

<style scoped>
.legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  font-size: 12px;
}
.lg i {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin-right: 3px;
  border-radius: 50%;
  vertical-align: -1px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.graph {
  width: 100%;
  max-height: 460px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.edge line {
  stroke: var(--el-border-color-darker);
  stroke-width: 1.4;
}
.edge.hot line {
  stroke: var(--el-color-primary);
  stroke-width: 2.4;
}
.edge.dim {
  opacity: 0.2;
}
.arrow {
  fill: var(--el-border-color-darker);
}
.elabel {
  font-size: 10px;
  text-anchor: middle;
  fill: var(--el-text-color-secondary);
}
.node {
  cursor: pointer;
}
.node circle {
  stroke: var(--el-bg-color);
  stroke-width: 2;
}
.node.hot circle {
  stroke: var(--el-text-color-primary);
  stroke-width: 3;
}
.node.dim {
  opacity: 0.25;
}
.nlabel {
  font-size: 11px;
  text-anchor: middle;
  fill: var(--el-text-color-primary);
  paint-order: stroke;
  stroke: var(--el-bg-color);
  stroke-width: 3px;
}
.focus {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 13px;
  line-height: 1.7;
}
.focus > b {
  margin-right: 6px;
}
.rules {
  margin-top: 10px;
}
.sec-title {
  margin: 12px 0 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
}
.rule {
  padding: 5px 8px;
  margin-bottom: 4px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  cursor: pointer;
}
.rule:hover {
  background: var(--el-fill-color-light);
}
.rule.on {
  background: var(--el-color-primary-light-9);
}
.lead {
  font-weight: 600;
  line-height: 1.7;
}
.detail {
  line-height: 1.8;
  white-space: pre-wrap;
}
.line {
  margin-bottom: 6px;
  font-size: 13px;
  line-height: 1.6;
}
</style>
