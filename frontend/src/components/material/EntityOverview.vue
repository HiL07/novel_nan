<template>
  <div class="eo">
    <el-empty v-if="!raw.length" description="还没有读出实体" />
    <template v-else>
      <!-- 合并选项 -->
      <section class="merge-box">
        <div class="merge-row">
          <b>合并选项</b>
          <el-checkbox v-model="state.contain" title="同一分类里名字 / 别名相同或互相包含（≥2 字）就合并">名字相近自动合并</el-checkbox>
          <span class="sep" />
          <ModelPicker v-model="aiModel" store-key="nan_novel.entityMerge.model" />
          <el-button size="small" :loading="aiBusy" @click="runAi">AI 找可合并的</el-button>
          <span class="muted">只看物品 / 世界观 / 怪物 / 地点；人物和势力请手动合并</span>
        </div>
        <div v-if="aiPending.length" class="ai-list">
          <div class="ai-head">
            <span>AI 建议（{{ aiPending.length }} 组，采用了才合并；约有一半需要你判断）</span>
            <el-button size="small" link type="primary" @click="acceptAll">全部采用</el-button>
            <el-button size="small" link @click="ignoreAll">全部忽略</el-button>
          </div>
          <div v-for="g in aiPending" :key="g.id" class="ai-item">
            <el-tag size="small" :type="g.type === 'system' ? 'warning' : 'info'" effect="plain">{{ g.type === 'system' ? '同一体系' : '同一个' }}</el-tag>
            <b>{{ g.name || '（未命名）' }}</b> ← {{ g.keys.map(nameOf).join('、') }}
            <span class="muted">{{ g.reason }}</span>
            <el-button size="small" link type="primary" @click="g.accepted = true">采用</el-button>
            <el-button size="small" link @click="ignoreAi(g)">忽略</el-button>
          </div>
        </div>
        <div v-if="state.splits.length || acceptedAi.length || state.joins.length" class="muted chips">
          <template v-if="acceptedAi.length">已采用 AI 建议 {{ acceptedAi.length }} 组
            <el-button size="small" link @click="acceptedAi.forEach((g) => (g.accepted = false))">撤回</el-button>；</template>
          <template v-if="state.joins.length">手动合并 {{ state.joins.length }} 组
            <el-button size="small" link @click="state.joins = []">全部撤销</el-button>；</template>
          <template v-if="state.splits.length">已拆出：
            <el-tag v-for="k in state.splits" :key="k" size="small" closable class="chip" @close="unsplit(k)">{{ nameOf(k) }}</el-tag>
          </template>
        </div>
      </section>

      <!-- 视图 -->
      <div class="eo-bar">
        <el-radio-group v-model="view" size="small">
          <el-radio-button value="after">合并后 {{ after.length }}</el-radio-button>
          <el-radio-button value="before">合并前 {{ before.length }}</el-radio-button>
          <el-radio-button value="compare">对比 {{ mergedGroups.length }} 组</el-radio-button>
        </el-radio-group>
        <el-checkbox v-if="view !== 'compare'" v-model="onlyMerged">只看有合并的</el-checkbox>
        <el-radio-group v-model="cat" size="small">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button v-for="c in catCounts" :key="c.code" :value="c.code">{{ c.label }} {{ c.count }}</el-radio-button>
        </el-radio-group>
        <el-input v-model="keyword" size="small" clearable placeholder="找实体（名字 / 别名 / 事实）" class="eo-search" />
        <el-select v-if="view !== 'compare'" v-model="sortBy" size="small" class="eo-sort">
          <el-option label="按出场章数" value="chapters" />
          <el-option label="按事实数" value="facts" />
          <el-option label="按首次出现" value="first" />
        </el-select>
        <span class="grow" />
        <el-button v-if="view === 'before'" size="small" :disabled="picked.length < 2 || !samePickedCat" @click="joinPicked">
          合并选中（{{ picked.length }}）
        </el-button>
        <el-button v-if="canApply && mergedGroups.length" size="small" type="primary" plain @click="apply">写回实体档案</el-button>
      </div>
      <p class="muted">
        合并前 {{ before.length }} 个 → 合并后 {{ after.length }} 个（已读 {{ readCis.length }} 章）。出场 = 名字在原文出现。
        <template v-if="view === 'before'">勾选同一分类的几个实体可以「合并选中」。</template>
        <template v-if="view === 'compare'">左边是合并前的各条，右边是合并后的样子；合错了就点「拆出」。</template>
      </p>

      <!-- 对比视图 -->
      <section v-if="view === 'compare'">
        <el-empty v-if="!shownGroups.length" description="没有合并的组" :image-size="60" />
        <div v-for="g in shownGroups.slice(0, cardLimit)" :key="g.id" class="cmp">
          <div class="cmp-before">
            <div v-for="m in g.members" :key="m.key" class="cmp-member">
              <div class="card-head">
                <b>{{ m.name }}</b>
                <span v-if="m.aliases?.length" class="muted">又名 {{ m.aliases.slice(0, 3).join('、') }}</span>
                <el-tag v-for="r in g.why[m.key] || []" :key="r" size="small" effect="plain" class="why">{{ r }}</el-tag>
                <span class="grow" />
                <el-button size="small" link type="danger" @click="split(m.key)">拆出</el-button>
              </div>
              <div class="muted">事实 {{ m.facts?.length || 0 }} 条</div>
              <ul class="facts"><li v-for="(f, i) in (m.facts || []).slice(0, 2)" :key="i">{{ f.fact }}</li></ul>
            </div>
          </div>
          <div class="cmp-arrow">→</div>
          <div class="cmp-after card">
            <div class="card-head">
              <el-tag size="small" effect="plain">{{ catLabel(g.category) }}</el-tag>
              <b class="card-name">{{ g.name }}</b>
            </div>
            <div class="muted card-meta">
              又名 {{ g.aliases.slice(0, 6).join('、') || '-' }} · 第 {{ base + g.first + 1 }} 章首次出现 · 出场 {{ g.chapters.size }} 章 · 事实 {{ g.facts.length }} 条
            </div>
            <ul class="facts"><li v-for="(f, i) in g.facts.slice(0, 4)" :key="i">{{ f.fact }}</li></ul>
          </div>
        </div>
      </section>

      <template v-else>
        <!-- 出场图 -->
        <section>
          <div class="sec-head">
            <h4>实体出场图</h4>
            <span class="legend">
              <span class="cell lv1" />提到 <span class="cell lv2" />有新事实 <span class="cell lv3" />获得 / 使用 / 击败等动态
            </span>
            <span v-if="bucket > 1" class="muted">每格 = {{ bucket }} 章，取最深</span>
          </div>
          <div class="grid-wrap">
            <div class="grid" :style="{ gridTemplateColumns: `140px repeat(${cols.length}, minmax(10px, 1fr))` }">
              <div class="g-corner muted">实体 \ 章</div>
              <div v-for="(c, i) in cols" :key="'h' + i" class="g-head" :title="colTitle(c)" @click="emit('jump', base + c.from)">
                {{ i % labelEvery === 0 ? base + c.from + 1 : '' }}
              </div>
              <template v-for="e in shownList.slice(0, gridRows)" :key="e.id">
                <div class="g-name" :class="{ on: open === e.id }" :title="e.name" @click="toggle(e.id)">
                  <span class="dot" :class="`c-${e.category}`" />{{ e.name }}
                </div>
                <div
                  v-for="(c, i) in cols"
                  :key="e.id + i"
                  class="cell"
                  :class="`lv${level(e, c)}`"
                  :title="cellTitle(e, c)"
                  @click="level(e, c) && emit('jump', base + firstHit(e, c))"
                />
              </template>
            </div>
          </div>
          <el-button v-if="shownList.length > gridRows" link type="primary" @click="gridRows += 30">
            再显示 30 个（共 {{ shownList.length }} 个）
          </el-button>
        </section>

        <!-- 实体列表 -->
        <section>
          <h4>实体（{{ shownList.length }}）</h4>
          <div class="cards">
            <div v-for="e in shownList.slice(0, cardLimit)" :key="e.id" class="card" :class="{ open: open === e.id }">
              <div class="card-head">
                <el-checkbox v-if="view === 'before'" :model-value="picked.includes(e.id)" @change="togglePick(e.id)" />
                <el-tag size="small" effect="plain">{{ catLabel(e.category) }}</el-tag>
                <b class="card-name" @click="toggle(e.id)">{{ e.name }}</b>
                <span v-if="e.aliases.length" class="muted aliases">又名 {{ e.aliases.slice(0, 4).join('、') }}</span>
              </div>
              <div class="muted card-meta" @click="toggle(e.id)">
                第 {{ base + e.first + 1 }} 章首次出现 · 出场 {{ e.chapters.size }} 章 · 事实 {{ e.facts.length }} 条
                <template v-if="e.moves.length"> · 动态 {{ e.moves.length }}</template>
                <span v-if="e.unverified.length" class="unv-count" title="模型写了、但原文里找不到对应句子的事实；展开后可以改为已核实或删除">
                  · 未核实 {{ e.unverified.length }}</span>
                <span v-if="e.members.length > 1" class="merged" :title="e.members.map((m) => m.name).join('、')">· 合并自 {{ e.members.length }} 条</span>
                <span v-else-if="view === 'before' && groupOf[e.id]" class="merged">· 合并后归入「{{ groupOf[e.id] }}」</span>
              </div>
              <ul v-if="open !== e.id" class="facts">
                <li v-for="(f, i) in e.facts.slice(0, 3)" :key="i">{{ f.fact }}</li>
              </ul>
              <div v-else class="detail">
                <div v-for="g in byChapter(e)" :key="g.ci" class="ch-group">
                  <a class="ch-link" @click="emit('jump', base + g.ci)">第 {{ base + g.ci + 1 }} 章</a>
                  <div v-for="(m, i) in g.moves" :key="'m' + i" class="move">
                    <el-tag size="small" type="warning" effect="plain">{{ m.act }}</el-tag> {{ m.text }}
                  </div>
                  <div v-for="(f, i) in g.facts" :key="'f' + i" class="fact">
                    {{ f.fact }}<span v-if="f.quote" class="quote">「{{ f.quote }}」</span>
                  </div>
                  <div v-for="(u, i) in g.unverified" :key="'u' + i" class="fact unv">
                    <el-tag size="small" type="info" effect="plain">未核实</el-tag> {{ u.fact }}
                    <span v-if="u.quote" class="quote">模型给的原文：「{{ u.quote }}」（原文里找不到）</span>
                    <template v-if="canApply">
                      <el-button size="small" link type="primary" @click="editUnverified(u, true)">改为已核实</el-button>
                      <el-button size="small" link type="danger" @click="editUnverified(u, false)">删除</el-button>
                    </template>
                  </div>
                  <div v-if="!g.moves.length && !g.facts.length && !g.unverified.length" class="muted">出场，没有新事实</div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
      <el-button v-if="(view === 'compare' ? shownGroups : shownList).length > cardLimit" link type="primary" @click="cardLimit += 40">
        再显示 40 个
      </el-button>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MATERIAL_CATEGORIES, categoryOf } from '@/api/material'
import { entityGroupsAI } from '@/api/novel'
import { errorMessage } from '@/api/request'
import ModelPicker from '@/components/persona/ModelPicker.vue'

/**
 * 全书实体总览（全书实体视图的主体）。
 * 合并选项：名字相近自动合并（同分类名字 / 别名相同或互相包含）、AI 建议（逐组采用）、手动合并（合并前视图勾选）、拆出（对比视图）。
 * 视图：合并后 / 合并前 / 对比（只列有合并的组：左合并前各条，右合并后）；「只看有合并的」筛选。
 * 合并只影响这里的显示；「写回实体档案」（提取完成后）才把合并结果写进结果文件（父组件保存），合并掉的键记在 mergedFrom。
 * 合并选择按提取任务记在本机 localStorage（nan_novel.entityMerge.<id>）。
 * entities：facts[].ci = 范围内序号；appear：ci → 原文里出现了名字的实体键；rows：全书下标 → 逐章行；base = range.from − 1。
 */
const props = defineProps({
  entities: { type: Array, default: () => [] },
  appear: { type: Object, default: () => ({}) },
  rows: { type: Object, default: () => ({}) },
  base: { type: Number, default: 0 },
  readCis: { type: Array, default: () => [] },
  extractId: { type: [Number, String], default: null },
  canApply: { type: Boolean, default: false }
})
const emit = defineEmits(['jump', 'apply'])

const MAX_COLS = 120
const view = ref('after')
const onlyMerged = ref(false)
const cat = ref('')
const keyword = ref('')
const sortBy = ref('chapters')
const open = ref('')
const gridRows = ref(30)
const cardLimit = ref(40)
const picked = ref([])
const aiBusy = ref(false)
const aiModel = ref(readModel())

const norm = (s) => String(s || '').replace(/[\s·・,，。、:："'“”《》（）()]/g, '').toLowerCase()
const catLabel = (c) => categoryOf(c)?.label || c

/* ---------- 合并状态（按提取任务记住） ---------- */
const storeKey = computed(() => `nan_novel.entityMerge.${props.extractId}`)
const state = reactive({ contain: true, ai: [], joins: [], splits: [] })
function readModel() {
  try {
    return JSON.parse(localStorage.getItem('nan_novel.entityMerge.model') || 'null') || { source: 'api', configId: null }
  } catch {
    return { source: 'api', configId: null }
  }
}
watch(
  storeKey,
  (k) => {
    let saved = null
    try {
      saved = JSON.parse(localStorage.getItem(k) || 'null')
    } catch {
      saved = null
    }
    Object.assign(state, { contain: true, ai: [], joins: [], splits: [], ...(saved || {}) })
  },
  { immediate: true }
)
watch(
  state,
  () => {
    try {
      localStorage.setItem(storeKey.value, JSON.stringify(state))
    } catch {
      // 存不下也能用，只是刷新后不记得
    }
  },
  { deep: true }
)

const raw = computed(() => props.entities)
const byKey = computed(() => Object.fromEntries(raw.value.map((e) => [e.key, e])))
const nameOf = (k) => byKey.value[k]?.name || k
const aiPending = computed(() => state.ai.filter((g) => !g.accepted && g.keys.every((k) => byKey.value[k])))
const acceptedAi = computed(() => state.ai.filter((g) => g.accepted))

async function runAi() {
  const items = raw.value.map((e) => ({ key: e.key, category: e.category, name: e.name, aliases: e.aliases || [], fact: e.facts?.[0]?.fact || '' }))
  aiBusy.value = true
  try {
    const res = await entityGroupsAI({ entities: items, model: aiModel.value })
    if (res.code !== 0) throw new Error(res.message)
    const known = new Set(state.ai.map((g) => [...g.keys].sort().join('|')))
    const fresh = (res.data.groups || [])
      .filter((g) => !known.has([...g.keys].sort().join('|')))
      .map((g, i) => ({ ...g, id: `ai${Date.now()}_${i}`, accepted: false }))
    state.ai.push(...fresh)
    ElMessage.success(fresh.length ? `AI 找到 ${fresh.length} 组可合并的，看一下再采用` : 'AI 没找到新的可合并的')
  } catch (e) {
    ElMessage.error(errorMessage(e, 'AI 归并失败'))
  } finally {
    aiBusy.value = false
  }
}
function acceptAll() {
  aiPending.value.forEach((g) => (g.accepted = true))
}
function ignoreAi(g) {
  state.ai = state.ai.filter((x) => x !== g)
}
function ignoreAll() {
  state.ai = state.ai.filter((g) => g.accepted)
}
function split(k) {
  if (!state.splits.includes(k)) state.splits.push(k)
}
function unsplit(k) {
  state.splits = state.splits.filter((x) => x !== k)
}
const samePickedCat = computed(() => new Set(picked.value.map((k) => byKey.value[k]?.category)).size === 1)
function togglePick(k) {
  picked.value = picked.value.includes(k) ? picked.value.filter((x) => x !== k) : [...picked.value, k]
}
function joinPicked() {
  state.joins.push({ keys: [...picked.value] })
  state.splits = state.splits.filter((k) => !picked.value.includes(k))
  picked.value = []
  ElMessage.success('已合并，可以在「对比」里查看或拆出')
}

/* ---------- 分组：并查集，边 = 名字相近 / 采用的 AI 建议 / 手动合并；拆出的实体不参与任何边 ---------- */
function buildGroups(withEdges) {
  const list = raw.value
  const idx = Object.fromEntries(list.map((e, i) => [e.key, i]))
  const parent = list.map((_, i) => i)
  const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])))
  const why = {} // 实体键 → 合并原因
  const out = new Set(state.splits)
  const link = (a, b, reason) => {
    if (out.has(a) || out.has(b) || idx[a] == null || idx[b] == null) return
    parent[find(idx[b])] = find(idx[a])
    for (const k of [a, b]) (why[k] ||= new Set()).add(reason)
  }
  if (withEdges) {
    if (state.contain) {
      const ns = list.map((e) => [...new Set([e.name, ...(e.aliases || [])].map(norm).filter((n) => n.length >= 2))])
      for (let i = 0; i < list.length; i++) {
        for (let j = i + 1; j < list.length; j++) {
          if (list[i].category === list[j].category && ns[i].some((x) => ns[j].some((y) => x === y || x.includes(y) || y.includes(x)))) {
            link(list[i].key, list[j].key, '名字相近')
          }
        }
      }
    }
    for (const g of acceptedAi.value) {
      g.keys.slice(1).forEach((k) => link(g.keys[0], k, g.type === 'system' ? 'AI·同一体系' : 'AI·同一个'))
    }
    for (const j of state.joins) j.keys.slice(1).forEach((k) => link(j.keys[0], k, '手动'))
  }
  const groups = new Map()
  list.forEach((e, i) => {
    const r = find(i)
    if (!groups.has(r)) groups.set(r, [])
    groups.get(r).push(e)
  })
  // 体系类 AI 建议给的总名称：整组都来自同一条建议时用它
  const sysName = (members) => {
    const keys = new Set(members.map((m) => m.key))
    const g = acceptedAi.value.find((x) => x.type === 'system' && x.name && x.keys.every((k) => keys.has(k)))
    return g?.name || ''
  }
  return [...groups.values()].map((members) => assemble(members, why, sysName(members)))
}

const moveIndex = computed(() => {
  const m = new Map()
  for (const [idx, r] of Object.entries(props.rows)) {
    for (const mv of r.card?.entityMoves || []) {
      const k = norm(mv.name)
      if (!m.has(k)) m.set(k, [])
      m.get(k).push({ ci: +idx - props.base, act: mv.act, text: mv.text })
    }
  }
  return m
})

function assemble(members, why, overrideName) {
  members = [...members].sort((a, b) => (b.facts?.length || 0) - (a.facts?.length || 0))
  const main = members[0]
  const allNames = [...new Set(members.flatMap((e) => [e.name, ...(e.aliases || [])]))]
  const name = overrideName || main.name
  const seen = new Set()
  const facts = members
    .flatMap((e) => e.facts || [])
    .filter((f) => (seen.has(f.fact) ? false : seen.add(f.fact)))
    .sort((a, b) => (a.ci ?? 0) - (b.ci ?? 0))
  const keys = new Set(members.flatMap((e) => [e.key, ...(e.mergedFrom || [])]))
  // 未核实事实：记下属于哪个原始实体（合并视图里改的也是那一条）
  const unverified = members.flatMap((e) => (e.unverified || []).map((u) => ({ ...u, owner: e.key })))
  const moves = [...new Set(allNames.map(norm))].flatMap((n) => moveIndex.value.get(n) || [])
  const factCis = new Set(facts.map((f) => f.ci).filter((ci) => typeof ci === 'number'))
  const moveCis = new Set(moves.map((m) => m.ci))
  const chapters = new Set([...factCis, ...moveCis])
  for (const [ci, ks] of Object.entries(props.appear)) if (ks.some((k) => keys.has(k))) chapters.add(+ci)
  return {
    id: main.key,
    category: main.category,
    name,
    aliases: allNames.filter((n) => n !== name),
    members,
    why: Object.fromEntries(members.map((m) => [m.key, [...(why[m.key] || [])]])),
    facts,
    unverified,
    moves,
    factCis,
    moveCis,
    chapters,
    first: chapters.size ? Math.min(...chapters) : 0,
    text: norm(allNames.join(' ') + facts.map((f) => f.fact).join(' '))
  }
}

const after = computed(() => buildGroups(true))
const before = computed(() => buildGroups(false))
const mergedGroups = computed(() => after.value.filter((g) => g.members.length > 1))
/** 合并前视图里每个实体归入了哪个合并组（只记有合并的） */
const groupOf = computed(() => {
  const m = {}
  for (const g of mergedGroups.value) for (const mem of g.members) m[mem.key] = g.name
  return m
})

const catCounts = computed(() => {
  const list = view.value === 'before' ? before.value : after.value
  return MATERIAL_CATEGORIES.map((c) => ({ code: c.code, label: c.label, count: list.filter((e) => e.category === c.code).length }))
    .filter((c) => c.count)
})

function filterSort(list) {
  const k = norm(keyword.value)
  const by = {
    chapters: (a, b) => b.chapters.size - a.chapters.size || b.facts.length - a.facts.length,
    facts: (a, b) => b.facts.length - a.facts.length,
    first: (a, b) => a.first - b.first || b.chapters.size - a.chapters.size
  }[sortBy.value]
  return list.filter((e) => (!cat.value || e.category === cat.value) && (!k || e.text.includes(k))).sort(by)
}
const shownList = computed(() => {
  if (view.value === 'before') {
    return filterSort(before.value.filter((e) => !onlyMerged.value || groupOf.value[e.id]))
  }
  return filterSort(after.value.filter((e) => !onlyMerged.value || e.members.length > 1))
})
const shownGroups = computed(() => filterSort([...mergedGroups.value]))

/* ---------- 出场图 ---------- */
const bucket = computed(() => Math.max(1, Math.ceil(props.readCis.length / MAX_COLS)))
const cols = computed(() => {
  const out = []
  for (let i = 0; i < props.readCis.length; i += bucket.value) {
    const cis = props.readCis.slice(i, i + bucket.value)
    out.push({ from: cis[0], to: cis[cis.length - 1], cis })
  }
  return out
})
const labelEvery = computed(() => Math.max(1, Math.ceil(cols.value.length / 20)))
function level(e, c) {
  let lv = 0
  for (const ci of c.cis) {
    if (e.moveCis.has(ci)) return 3
    if (e.factCis.has(ci)) lv = 2
    else if (e.chapters.has(ci)) lv = Math.max(lv, 1)
  }
  return lv
}
function firstHit(e, c) {
  return c.cis.find((ci) => e.chapters.has(ci)) ?? c.from
}
function colTitle(c) {
  return c.from === c.to ? `第 ${props.base + c.from + 1} 章` : `第 ${props.base + c.from + 1}–${props.base + c.to + 1} 章`
}
function cellTitle(e, c) {
  const lv = level(e, c)
  if (!lv) return `${e.name} · ${colTitle(c)}：没出现`
  const moves = e.moves.filter((m) => c.cis.includes(m.ci)).map((m) => `${m.act}：${m.text}`)
  const facts = e.facts.filter((f) => c.cis.includes(f.ci)).map((f) => f.fact)
  return [`${e.name} · ${colTitle(c)}`, ...moves, ...facts.slice(0, 4), facts.length > 4 ? `…共 ${facts.length} 条事实` : '']
    .filter(Boolean)
    .join('\n')
}
function byChapter(e) {
  const cis = new Set([...e.chapters, ...e.unverified.map((u) => u.ci).filter((ci) => typeof ci === 'number')])
  return [...cis]
    .sort((a, b) => a - b)
    .map((ci) => ({
      ci,
      facts: e.facts.filter((f) => f.ci === ci),
      moves: e.moves.filter((m) => m.ci === ci),
      unverified: e.unverified.filter((u) => u.ci === ci)
    }))
}

/** 未核实事实：改为已核实（移进 facts，标 manual）或删除；写回整个实体档案（提取完成后才可以） */
function editUnverified(u, verify) {
  const list = raw.value.map((e) => {
    if (e.key !== u.owner) return e
    const unverified = (e.unverified || []).filter((x) => !(x.fact === u.fact && x.ci === u.ci))
    const facts = verify
      ? [...(e.facts || []), { fact: u.fact, quote: u.quote, chapter: u.chapter, ci: u.ci, at: null, manual: true }]
      : e.facts
    return { ...e, facts, unverified }
  })
  emit('apply', list, null, verify ? '已改为已核实' : '已删除这条未核实事实')
}
function toggle(id) {
  open.value = open.value === id ? '' : id
}

/* ---------- 写回实体档案（提取完成后） ---------- */
async function apply() {
  try {
    await ElMessageBox.confirm(
      `把 ${mergedGroups.value.length} 组合并写进这次提取的实体档案（${before.value.length} 个 → ${after.value.length} 个）？` +
        '之后「整理卡片」用的就是合并后的实体；合并掉的条目记在 mergedFrom 里。',
      '写回实体档案',
      { type: 'warning' }
    )
  } catch {
    return
  }
  const entities = after.value.map((g) => {
    if (g.members.length === 1) return g.members[0]
    const main = g.members[0]
    const seen = new Set(g.facts.map((f) => f.fact))
    const unverified = g.members.flatMap((m) => m.unverified || []).filter((u) => (seen.has(u.fact) ? false : seen.add(u.fact)))
    return {
      key: main.key,
      category: main.category,
      name: g.name,
      aliases: g.aliases.slice(0, 12),
      facts: g.facts,
      unverified: unverified.slice(0, 10),
      mergedFrom: [...new Set(g.members.flatMap((m) => (m === main ? m.mergedFrom || [] : [m.key, ...(m.mergedFrom || [])])))]
    }
  })
  emit('apply', entities, () => Object.assign(state, { ai: [], joins: [], splits: [] }))
}
</script>

<style scoped>
.eo {
  font-size: 13px;
  --c-character: var(--el-color-primary);
  --c-item: var(--el-color-warning);
  --c-monster: var(--el-color-danger-dark-2, #7a1f17);
  --c-location: var(--el-color-success);
  --c-faction: var(--el-color-info);
  --c-world: var(--el-text-color-regular);
}
section {
  margin-bottom: 22px;
}
h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.grow {
  flex: 1;
}
.merge-box {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--ws-card, var(--el-bg-color));
}
.merge-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.sep {
  width: 1px;
  height: 18px;
  background: var(--el-border-color-lighter);
}
.ai-list {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.ai-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ai-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 3px 0;
}
.chips {
  margin-top: 8px;
}
.chip {
  margin: 0 4px 2px 0;
}
.eo-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 14px 0 6px;
}
.eo-search {
  width: 200px;
}
.eo-sort {
  width: 120px;
}
.sec-head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.sec-head h4 {
  margin: 0;
}
.legend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.legend .cell {
  display: inline-block;
  width: 12px;
  height: 12px;
  margin-left: 8px;
  cursor: default;
}
.grid-wrap {
  overflow-x: auto;
}
.grid {
  display: grid;
  gap: 2px;
  min-width: 100%;
}
.g-corner,
.g-head {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  text-align: center;
  line-height: 18px;
}
.g-corner {
  text-align: left;
}
.g-head {
  cursor: pointer;
}
.g-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 16px;
  cursor: pointer;
}
.g-name.on {
  color: var(--el-color-primary);
}
.dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 50%;
  vertical-align: middle;
}
.c-character { background: var(--c-character); }
.c-item { background: var(--c-item); }
.c-monster { background: var(--c-monster); }
.c-location { background: var(--c-location); }
.c-faction { background: var(--c-faction); }
.c-world { background: var(--c-world); }
.cell {
  height: 16px;
  border-radius: 2px;
  background: var(--el-fill-color-light);
}
.cell.lv1 {
  background: var(--el-color-primary-light-8);
  cursor: pointer;
}
.cell.lv2 {
  background: var(--el-color-primary-light-5);
  cursor: pointer;
}
.cell.lv3 {
  background: var(--el-color-primary);
  cursor: pointer;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 10px;
}
.card {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--ws-card, var(--el-bg-color));
}
.card.open {
  grid-column: 1 / -1;
  border-color: var(--el-color-primary-light-5);
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.card-name {
  font-size: 15px;
  font-family: var(--ws-font-title, inherit);
  font-weight: normal;
  cursor: pointer;
}
.card-meta {
  margin: 4px 0;
  cursor: pointer;
}
.merged {
  cursor: help;
  text-decoration: underline dotted;
}
.facts {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
}
.detail {
  margin-top: 6px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px 16px;
}
.ch-group {
  padding: 4px 0;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.ch-link {
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
}
.move,
.fact {
  margin-top: 3px;
  line-height: 1.6;
}
.unv {
  color: var(--el-text-color-secondary);
}
.unv-count {
  color: var(--el-color-warning);
}
.quote {
  margin-left: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.cmp {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.cmp-before {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cmp-member {
  padding: 6px 10px;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
}
.cmp-arrow {
  text-align: center;
  font-size: 18px;
  color: var(--el-text-color-secondary);
}
.why {
  margin-left: 2px;
}
</style>
