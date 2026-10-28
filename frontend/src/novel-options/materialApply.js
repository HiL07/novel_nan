import { categoryOf } from '@/api/material'
import { ensureValue, newGroupItem, uid } from './schema'

/**
 * 把素材库中的素材「复制」进写作设定（之后与手填内容一样可编辑；素材库再改不影响已应用的内容）。
 *
 * 映射：素材分类 → 设定中的位置。fields 为「设定字段 key → 素材来源」：
 *   'title' = 素材名称；'*' = 汇总文本（概括 + 未映射的属性 + 详细）；其他 = attributes 中同名属性。
 * 目标为模板创建的自定义元素时（怪物 / 势力 / 地点 / 物品），工作区里没有就按模板自动创建。
 */
export const APPLY_TARGETS = {
  monster: { template: 'monster', group: 'list', fields: { name: 'title', appearance: '外形', abilities: '能力', weakness: '弱点', habitat: '栖息地' } },
  faction: { template: 'faction', group: 'list', fields: { name: 'title', stance: '立场', feature: '*' } },
  location: { template: 'location', group: 'list', fields: { name: 'title', kind: '类型', detail: '*' } },
  item: { template: 'item', group: 'list', fields: { name: 'title', kind: '类别', effect: '*' } },
  character: { builtin: 'characters', group: 'cast', fields: { name: 'title', personality: '性格', background: '*' } },
  plot: { builtin: 'plot', group: 'milestones', fields: { name: 'title', detail: '*' } },
  world: { builtin: 'world', append: 'worldNote' }
}

const asList = (v) => (Array.isArray(v) ? v.map(String) : String(v ?? '').split(/[、,，;；]/)).map((s) => s.trim()).filter(Boolean)
const asText = (v) => (Array.isArray(v) ? v.join('、') : String(v ?? '')).trim()

/** 概括 + 未被映射的属性 + 详细，组成一段说明文字 */
function compose(material, mappedAttrs, withTitle = false) {
  const lines = []
  if (withTitle) lines.push(`【${material.title}】`)
  if (material.summary) lines.push(material.summary)
  for (const [k, v] of Object.entries(material.attributes || {})) {
    if (!mappedAttrs.has(k) && asText(v)) lines.push(`${k}：${asText(v)}`)
  }
  if (material.detail) lines.push(material.detail)
  return lines.join('\n')
}

function findTargetCategory(categories, target) {
  return target.builtin
    ? categories.find((c) => c.key === target.builtin)
    : categories.find((c) => c.custom && c.templateKey === target.template)
}

const MARKS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫'

/**
 * 多版本素材（合并而来的主条目）复制进设定前，按选的用法展开成一条普通素材：
 * 只用某一版 = 共性 + 那一版的概括 / 属性 / 详细；让 AI 选 / 融合 = 共性 + 「可选版本」逐条写进详细（落到备注里，作者自己挑）。
 * members：主条目详情里的成员素材。
 */
export function resolveVersions(master, members = []) {
  const variants = master.source?.variants || []
  if (master.source?.type !== 'merge' || variants.length < 2) return master
  const memberOf = (id) => members.find((m) => m.id === id)
  const chosen = variants.find((v) => String(v.id) === String(master.variant))
  if (chosen) {
    const mem = memberOf(chosen.id) || {}
    return {
      ...master,
      summary: mem.summary || chosen.note || master.summary,
      attributes: { ...(master.attributes || {}), ...(mem.attributes || {}) },
      detail: [chosen.note, mem.detail].filter(Boolean).join('\n')
    }
  }
  const lines = variants.map((v, i) => {
    const mem = memberOf(v.id) || {}
    const book = v.book ? `《${v.book}》` : ''
    return `${MARKS[i] || i + 1}${v.label || v.title}${book}：${v.note || mem.summary || ''}`
  })
  const head = master.variant === 'blend' ? '可选版本（打算融合使用）：' : '可选版本（选一种用）：'
  return { ...master, detail: [master.detail, head, ...lines].filter(Boolean).join('\n') }
}

/** 应用前的预览文字，如「自定义元素·怪物 → 典型怪物（新增一项）」 */
export function describeTarget(material, categories) {
  const target = APPLY_TARGETS[material.category]
  if (!target) return '不支持的分类'
  const cat = findTargetCategory(categories, target)
  if (target.append) return `${cat?.label || '世界观'} → 世界观补充（追加一段）`
  const catLabel = cat ? cat.label : `自定义元素·${categoryOf(material.category)?.label}（将自动创建）`
  const group = cat?.fields.find((f) => f.key === target.group)
  return `${catLabel} → ${group?.label || '列表'}（新增一项）`
}

function setChoice(field, container, raw) {
  const wanted = asList(raw)
  if (!wanted.length) return
  if (!field.options) field.options = []
  const picked = []
  for (const w of wanted) {
    let opt = field.options.find((o) => o.label === w || w.includes(o.label) || o.label.includes(w))
    if (!opt && field.allowCustom !== false) {
      opt = { value: uid('o'), label: w, custom: true }
      field.options.push(opt)
    }
    if (opt && !picked.includes(opt.value)) picked.push(opt.value)
  }
  const value = ensureValue(container, field)
  value.selected = field.type === 'single' ? picked.slice(0, 1) : picked.slice(0, field.max || picked.length)
}

/**
 * 应用一条素材。ctx = { categories: 分类数组, values: 取值树, createFromTemplate(templateKey) → 新建的自定义分类 }
 * 返回 { categoryKey, label }（应用到的位置），无法应用时抛错。
 */
export function applyMaterial(material, ctx) {
  const target = APPLY_TARGETS[material.category]
  if (!target) throw new Error(`不支持的素材分类：${material.category}`)
  let cat = findTargetCategory(ctx.categories, target)
  if (!cat && target.template) cat = ctx.createFromTemplate(target.template)
  if (!cat) throw new Error('找不到对应的设定分类')
  const container = ctx.values[cat.key]

  if (target.append) {
    const field = cat.fields.find((f) => f.key === target.append)
    if (!field) throw new Error(`「${cat.label}」中没有可追加的说明字段`)
    const prev = asText(ensureValue(container, field))
    container[field.key] = [prev, compose(material, new Set(), true)].filter(Boolean).join('\n\n')
    return { categoryKey: cat.key, label: `${cat.label} → ${field.label}` }
  }

  const group = cat.fields.find((f) => f.key === target.group && f.type === 'group')
  if (!group) throw new Error(`「${cat.label}」中的目标列表已被删除，无法应用`)
  const mapped = new Set(Object.values(target.fields).filter((s) => s !== 'title' && s !== '*'))
  const item = newGroupItem(group)
  item._fromMaterial = material.id
  let composed = false
  for (const f of group.fields || []) {
    const src = target.fields[f.key]
    if (!src) continue
    const raw = src === 'title' ? material.title : src === '*' ? compose(material, mapped) : material.attributes?.[src]
    if (src === '*') composed = true
    if (raw == null || raw === '' || (Array.isArray(raw) && !raw.length)) continue
    if (f.type === 'tags') item[f.key] = asList(raw)
    else if (f.type === 'single' || f.type === 'multi') setChoice(f, item, raw)
    else item[f.key] = asText(raw)
  }
  // 没有可承载说明的字段（如怪物）时，给该列表加一个「备注」字段，放概括与其余属性
  const rest = composed ? '' : compose(material, mapped)
  if (rest) {
    let note = group.fields.find((f) => f.key === 'materialNote')
    if (!note) {
      note = { key: 'materialNote', label: '备注', type: 'textarea', custom: true }
      group.fields.push(note)
    }
    item[note.key] = rest
  }
  ensureValue(container, group).push(item)
  return { categoryKey: cat.key, label: `${cat.label} → ${group.label}` }
}
