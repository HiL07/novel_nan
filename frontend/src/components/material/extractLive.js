/**
 * 提取工作区的逐章数据（docs/素材提取改造方案.md §E）。
 * 所有东西按「全书章节下标 idx」（从 0 数）索引：左栏永远是全书分章，提取范围外的章显示为不在范围。
 * - 提取中：每 3 秒按 since 拉断点里新读完的章（GET /api/novel/extract/{id}/live），行里的 ci 按 range.from 换算成 idx；
 * - 提取成功：从结果里的 chapterCards / entities / threads 拼出同样的数据（fromResult）。
 * 原文按文件取（GET /api/novel/extract/file/{fileId}/chapters/{idx}/text），开始提取前也能看；
 * 核实过的摘抄按 at（本章内偏移）定位：先在 at 附近精确查找，找不到再全章查找，都找不到就按 at 高亮。
 */
import { computed, nextTick, reactive, ref } from 'vue'
import { getExtractLive, getFileChapterText } from '@/api/novel'
import { categoryOf } from '@/api/material'
import { errorMessage } from '@/api/request'

export const KINDS = { hook: '钩子', payoff: '爽点', thread: '伏笔', person: '人物', move: '设定动态', fact: '事实' }
export const STATE_LABELS = {
  pending: '待读', reading: '读取中', partial: '读了一部分', done: '完成', failed: '失败', empty: '没有内容', out: '不在范围'
}
const POS = { open: '开头', mid: '章中', end: '章末' }
const OPS = { plant: '埋', advance: '推', payoff: '收' }
const POLL_MS = 3000

export function useExtractLive({ fileId, onStatus, onFinished }) {
  const chapters = ref([]) // 全书分章 [{idx, title, kind, chars}]
  const rows = reactive({}) // idx → {status, card, entities, threadOps, error}
  const range = ref(null) // {from, to, total}（从 1 数）；null = 还没开始
  const current = ref(null) // 正在读的 idx
  const running = ref(false)
  const follow = ref(true)
  const selected = ref(null)
  const activeMark = ref('')
  const liveError = ref('')
  let since = 0
  let timer = null
  let stopped = true
  let taskId = null

  function setBook(list) {
    chapters.value = list.map((c) => ({ idx: c.index - 1, title: c.title, kind: c.kind, chars: c.chars }))
  }

  function reset() {
    stopPoll()
    for (const k of Object.keys(rows)) delete rows[k]
    range.value = null
    current.value = null
    running.value = false
    since = 0
    liveError.value = ''
  }

  function inRange(idx) {
    const r = range.value
    return !r || (idx >= r.from - 1 && idx <= r.to - 1)
  }

  /* ---------- 提取成功：从结果拼 ---------- */
  function fromResult(r) {
    const base = (r.range?.from || 1) - 1
    const cards = r.chapterCards || []
    range.value = r.range || { from: 1, to: cards.length, total: chapters.value.length || cards.length }
    const ents = {}
    for (const e of r.entities || []) {
      const add = (ci, key, f) => {
        const byCi = (ents[ci] ||= {})
        const cur = (byCi[e.key || e.name] ||= { category: e.category, name: e.name, facts: [], unverified: [] })
        cur[key].push(f)
      }
      for (const f of e.facts || []) if (typeof f.ci === 'number') add(f.ci, 'facts', f)
      for (const f of e.unverified || []) if (typeof f.ci === 'number') add(f.ci, 'unverified', f)
    }
    const ops = {}
    for (const t of r.threads || []) {
      ;(ops[t.plantCi] ||= []).push({ op: 'plant', id: t.id, kind: t.kind, text: t.text, quote: t.quote, at: t.at })
      for (const a of t.advances || []) {
        ;(ops[a.ci] ||= []).push({ op: a.act, id: t.id, kind: t.kind, text: a.text, quote: a.quote, at: a.at })
      }
    }
    cards.forEach((c, ci) => {
      rows[base + ci] = {
        status: c.status || 'done', card: c, entities: Object.values(ents[ci] || {}), threadOps: ops[ci] || [], error: c.error
      }
    })
    if (!chapters.value.length) {
      chapters.value = cards.map((c, ci) => ({ idx: base + ci, title: c.title, kind: c.kind, chars: c.stats?.chars || 0 }))
    }
    const first = cards.findIndex((c) => c.status === 'done')
    if (selected.value == null || !inRange(selected.value)) select(base + Math.max(0, first))
  }

  /* ---------- 提取中：轮询断点 ---------- */
  function startPoll(id) {
    stopPoll()
    taskId = id
    stopped = false
    poll()
  }

  function stopPoll() {
    stopped = true
    if (timer) clearTimeout(timer)
    timer = null
  }

  async function poll() {
    timer = null
    let status = ''
    try {
      const res = await getExtractLive(taskId, since)
      if (stopped) return
      if (res.code !== 0) throw new Error(res.message)
      const d = res.data
      status = d.status
      onStatus?.(d)
      liveError.value = ''
      if (d.finished) {
        running.value = false
        current.value = null
        stopped = true
        onFinished?.()
        return
      }
      const live = d.live || {}
      if (live.range) range.value = live.range
      const base = (range.value?.from || 1) - 1
      for (const r of live.rows || []) rows[base + r.ci] = r
      since = live.next ?? since
      current.value = live.current == null ? null : base + live.current
      running.value = !!live.running
      if (follow.value && live.rows?.length) {
        const last = [...live.rows].reverse().find((r) => r.status === 'done' || r.status === 'partial')
        if (last) select(base + last.ci)
      }
    } catch (e) {
      liveError.value = errorMessage(e, '读取逐章进度失败')
    }
    if (!stopped && (!status || ['QUEUED', 'RUNNING'].includes(status))) timer = setTimeout(poll, POLL_MS)
  }

  function stateOf(idx) {
    if (!inRange(idx)) return 'out'
    const r = rows[idx]
    const reading = idx === current.value && running.value
    if (r) return r.status === 'partial' && reading ? 'reading' : r.status
    return reading ? 'reading' : 'pending'
  }

  function badges(idx) {
    const c = rows[idx]?.card
    if (!c) return ''
    const out = []
    if (c.payoffs?.length) out.push(`爽${c.payoffs.length}`)
    if (c.hooks?.some((h) => h.pos === 'end')) out.push('钩')
    const n = c.stats?.newEntities ?? rows[idx].entities?.length
    if (n) out.push(`新${n}`)
    return out.join(' ')
  }

  /* ---------- 选章 / 原文 ---------- */
  const textCache = new Map()
  const chapterText = ref({ title: '', text: '' })
  const textLoading = ref(false)
  const textError = ref('')

  async function select(idx, byUser = false) {
    if (idx == null) return
    if (byUser) follow.value = false
    if (selected.value === idx && chapterText.value.text) return
    selected.value = idx
    activeMark.value = ''
    textError.value = ''
    const key = `${fileId.value}:${idx}`
    if (textCache.has(key)) {
      chapterText.value = textCache.get(key)
      return
    }
    textLoading.value = true
    try {
      const res = await getFileChapterText(fileId.value, idx)
      if (res.code !== 0) throw new Error(res.message)
      textCache.set(key, res.data)
      if (textCache.size > 30) textCache.delete(textCache.keys().next().value)
      if (selected.value === idx) chapterText.value = res.data
    } catch (e) {
      if (selected.value === idx) {
        chapterText.value = { title: chapters.value.find((c) => c.idx === idx)?.title || '', text: '' }
        textError.value = errorMessage(e, '读取原文失败（AI 服务没启动？）')
      }
    } finally {
      textLoading.value = false
    }
  }

  const row = computed(() => (selected.value == null ? null : rows[selected.value]))
  const card = computed(() => (row.value?.card && Object.keys(row.value.card).length ? row.value.card : null))
  const emotionText = computed(() => {
    const e = card.value?.emotion
    return e ? [e.open, e.peak, e.close].filter(Boolean).join(' → ') : ''
  })

  /** 右栏「本章」的条目（带 mark 的才能点、才在原文里高亮） */
  const sections = computed(() => {
    const c = card.value || {}
    const r = row.value || {}
    const mk = (kind, tag, list, fn) =>
      (list || []).map((x, i) => ({
        id: `${kind}-${tag}-${i}`, kind, quote: x.quote, at: x.at, mark: !!(x.quote && x.at != null),
        unverified: x.verified === false, ...fn(x)
      }))
    const stars = (n) => '★'.repeat(n || 1)
    const out = [
      { title: '钩子', items: mk('hook', 'h', c.hooks, (x) => ({ head: `${POS[x.pos] || x.pos}·${x.type}${stars(x.strength)}`, text: x.text })) },
      { title: '爽点', items: mk('payoff', 'p', c.payoffs, (x) => ({ head: `${x.type}${stars(x.strength)}${x.amplified ? '·旁观' : ''}`, text: x.setup ? `铺垫：${x.setup}` : '' })) },
      { title: '伏笔', items: mk('thread', 't', r.threadOps, (x) => ({ head: `${OPS[x.op] || x.op}${x.id ? ' ' + x.id : ''}·${x.kind}`, text: x.text })) },
      { title: '主角变化', items: mk('person', 'l', c.leadChanges, (x) => ({ head: x.field, text: (x.before ? `${x.before} → ` : '') + x.after })) },
      { title: '人物关系', items: mk('person', 'r', c.relations, (x) => ({ head: `${x.a}—${x.b}·${x.rel}`, text: `${x.change}${x.text ? '：' + x.text : ''}` })) },
      { title: '设定动态', items: mk('move', 'm', c.entityMoves, (x) => ({ head: `${x.act}·${x.name}`, text: x.text })) },
      { title: '金句', items: mk('person', 's', c.lines, (x) => ({ head: x.speaker || '台词', text: '' })) },
      { title: '开篇点评', items: mk('hook', 'g', c.golden?.anchors, (x) => ({ head: '原文', text: x.comment })) }
    ]
    const facts = []
    for (const e of r.entities || []) {
      const name = `${categoryOf(e.category)?.label || e.category}·${e.name}`
      ;(e.facts || []).forEach((f, i) =>
        facts.push({ id: `fact-${e.name}-${i}`, kind: 'fact', head: name, text: f.fact, quote: f.quote, at: f.at, mark: f.at != null })
      )
      ;(e.unverified || []).forEach((f, i) =>
        facts.push({ id: `unv-${e.name}-${i}`, kind: 'fact', head: name, text: f.fact, quote: '', unverified: true, mark: false })
      )
    }
    out.push({ title: '设定实体的事实', items: facts })
    return out.filter((s) => s.items.length)
  })

  /** 原文按段落切开，摘抄处切成高亮片段；深拆档的情节节点给段落加底色 */
  const paragraphs = computed(() => {
    const text = chapterText.value?.text || ''
    if (!text) return []
    const marks = []
    for (const s of sections.value) {
      for (const it of s.items) {
        if (!it.mark) continue
        const span = locate(text, it.quote, it.at)
        if (span) marks.push({ ...span, id: it.id, kind: it.kind, label: `${KINDS[it.kind]}：${it.head}` })
      }
    }
    marks.sort((a, b) => a.start - b.start || b.end - a.end)
    const clean = []
    for (const m of marks) if (!clean.length || m.start >= clean[clean.length - 1].end) clean.push(m)
    const nodes = card.value?.nodes || []
    const out = []
    let pos = 0
    let mi = 0
    for (const line of text.split('\n')) {
      const start = pos
      const end = pos + line.length
      pos = end + 1
      if (!line.trim()) continue
      const segs = []
      let cur = start
      while (mi < clean.length && clean[mi].end <= start) mi++
      for (let k = mi; k < clean.length && clean[k].start < end; k++) {
        const a = Math.max(clean[k].start, start)
        const b = Math.min(clean[k].end, end)
        if (a > cur) segs.push({ text: text.slice(cur, a) })
        if (b > a) segs.push({ text: text.slice(a, b), mark: clean[k] })
        cur = Math.max(cur, b)
      }
      if (cur < end) segs.push({ text: text.slice(cur, end) })
      const ni = nodes.findIndex((n) => start >= n.start && start < n.end)
      const prev = out[out.length - 1]
      out.push({ segs, node: ni >= 0 ? ni : null, nodeHead: ni >= 0 && prev?.node !== ni ? nodes[ni] : null })
    }
    return out
  })

  function pickMark(id, from) {
    activeMark.value = id
    nextTick(() => {
      const sel = from === 'card' ? `[data-mark="${id}"]` : `[data-item="${id}"]`
      document.querySelector(sel)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  }

  return {
    chapters, rows, range, current, running, follow, selected, activeMark, liveError,
    chapterText, textLoading, textError, row, card, emotionText, sections, paragraphs,
    setBook, reset, fromResult, startPoll, stopPoll, stateOf, badges, select, pickMark, inRange
  }
}

function locate(text, quote, at) {
  if (!quote) return null
  const near = text.indexOf(quote, Math.max(0, (at || 0) - 50))
  const i = near >= 0 && near - (at || 0) < 200 ? near : text.indexOf(quote)
  if (i >= 0) return { start: i, end: i + quote.length }
  if (at == null || at >= text.length) return null
  return { start: at, end: Math.min(text.length, at + quote.length) } // 模糊命中：只是近似位置
}
