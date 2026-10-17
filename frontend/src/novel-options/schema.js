import { initValue, isChoice } from './fieldTypes'

let seq = 0
/** 生成本地唯一 key（自定义字段 / 选项 / 分类用；接数据库后可换成后端 id） */
export function uid(prefix = 'c') {
  seq += 1
  return `${prefix}_${Date.now().toString(36)}${seq.toString(36)}`
}

export function clone(obj) {
  return JSON.parse(JSON.stringify(obj))
}

/** 确保容器里有该字段的值（字段是后加的、或从模板新增时） */
export function ensureValue(container, field) {
  if (!(field.key in container)) {
    container[field.key] = initValue(field)
  }
  return container[field.key]
}

/** 为一组字段生成初始值容器 */
export function initValues(fields) {
  const container = {}
  fields.forEach((f) => ensureValue(container, f))
  return container
}

/** 新建分组中的一项 */
export function newGroupItem(field) {
  return { _id: uid('item'), ...initValues(field.fields || []) }
}

function isEmpty(field, value) {
  if (value == null) return true
  if (isChoice(field)) return !value.selected?.length
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'string') return value.trim() === ''
  return false
}

/** 字段是否已填写（用于分类计数） */
export function isFilled(field, value) {
  return !isEmpty(field, value)
}

/**
 * 把「字段定义 + 取值」整理成与界面无关的设定结构（之后可直接拼进生成小说的 prompt / 存库）：
 * [{ key, label, value, display, children: [...] }]，未填写的字段会被省略。
 */
export function summarizeFields(fields, container) {
  const out = []
  for (const field of fields) {
    const value = container?.[field.key]
    if (isEmpty(field, value)) continue

    if (isChoice(field)) {
      const picked = value.selected
        .map((v) => field.options?.find((o) => o.value === v))
        .filter(Boolean)
      const children = []
      for (const opt of picked) {
        if (!opt.children?.length) continue
        const sub = summarizeFields(opt.children, value.sub?.[opt.value])
        if (sub.length) children.push({ key: opt.value, label: opt.label, value: null, display: '', children: sub })
      }
      out.push({
        key: field.key,
        label: field.label,
        value: picked.map((o) => o.label),
        display: picked.map((o) => o.label).join('、'),
        children
      })
    } else if (field.type === 'group') {
      const items = value
        .map((item, i) => {
          const sub = summarizeFields(field.fields || [], item)
          const nameItem = sub.find((s) => typeof s.value === 'string')
          return {
            key: item._id,
            label: `${field.itemLabel || '项'} ${i + 1}${nameItem ? `：${nameItem.value}` : ''}`,
            value: null,
            display: '',
            children: sub
          }
        })
        .filter((it) => it.children.length)
      if (items.length) {
        out.push({ key: field.key, label: field.label, value: null, display: `${items.length} 个`, children: items })
      }
    } else if (field.type === 'tags') {
      out.push({ key: field.key, label: field.label, value: [...value], display: value.join('、'), children: [] })
    } else {
      out.push({ key: field.key, label: field.label, value, display: String(value), children: [] })
    }
  }
  return out
}

/** 整个创作设定：按分类汇总 */
export function buildSpec(categories, values) {
  return categories
    .map((cat) => ({
      key: cat.key,
      label: cat.label,
      custom: !!cat.custom,
      items: summarizeFields(cat.fields, values[cat.key])
    }))
    .filter((c) => c.items.length)
}

/** 去掉内部 key / display 等界面字段，得到便于阅读和传给模型的纯 JSON：{ 分类: { 字段: 值 | {选择, 子项} } } */
export function specToJson(spec) {
  const convert = (items) => {
    const obj = {}
    for (const it of items) {
      if (!it.children.length) {
        obj[it.label] = it.value
      } else if (it.value == null) {
        obj[it.label] = convert(it.children)
      } else {
        obj[it.label] = { 选择: it.value, ...convert(it.children) }
      }
    }
    return obj
  }
  return Object.fromEntries(spec.map((c) => [c.label, convert(c.items)]))
}
