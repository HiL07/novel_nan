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

/**
 * 旧版本保存的设定升级到当前结构（只在版本号变化时做一次，避免把用户在编辑模式下删掉的字段又加回来）：
 * 内置分类里的分组字段（如「主要角色」）补上新增的子字段、同步展示方式（display / section / desc），
 * 子字段按默认顺序排列，用户自定义的子字段保持在后面。已填的值不动，新字段的值由 ensureValue 按需初始化。
 */
export function upgradeConfig(saved, defaults) {
  const from = saved.schemaVersion || 1
  const to = defaults.schemaVersion || 1
  if (from >= to) return saved
  for (const defCat of defaults.categories || []) {
    const cat = (saved.categories || []).find((c) => c.key === defCat.key && !c.custom)
    if (!cat) continue
    for (const defField of defCat.fields || []) {
      if (defField.type !== 'group') continue
      const field = cat.fields.find((f) => f.key === defField.key)
      if (!field || field.type !== 'group') continue
      if (defField.display) field.display = defField.display
      if (defField.desc) field.desc = defField.desc
      const children = field.fields || []
      const merged = defField.fields.map((d) => {
        const old = children.find((c) => c.key === d.key)
        return old ? { ...old, section: d.section } : clone(d)
      })
      field.fields = [...merged, ...children.filter((c) => !defField.fields.some((d) => d.key === c.key))]
    }
  }
  saved.schemaVersion = to
  return saved
}

/** 新建分组中的一项 */
export function newGroupItem(field) {
  return { _id: uid('item'), ...initValues(field.fields || []) }
}

/** 数字 / 滑块始终有值（默认值），只有用户动过才算「已确认」；记录在容器的 __touched 上 */
const NEEDS_TOUCH = ['number', 'slider']

export function markTouched(container, field) {
  if (!container.__touched) container.__touched = {}
  container.__touched[field.key] = true
}

function isEmpty(field, value, container) {
  if (value == null) return true
  if (NEEDS_TOUCH.includes(field.type)) return !container?.__touched?.[field.key]
  if (isChoice(field)) return !value.selected?.length
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'string') return value.trim() === ''
  return false
}

/** 字段是否已填写 / 确认（用于分类计数）；container 为该字段所在的取值容器 */
export function isFilled(field, container) {
  return !isEmpty(field, container?.[field.key], container)
}

/**
 * 把「字段定义 + 取值」整理成与界面无关的设定结构（小说生成的约束来源 / 存库）：
 * [{ key, label, type, value, display, children: [...] }]，未填写 / 未确认的字段会被省略。
 * type 为字段类型；选择项的细分选项容器为 type="option"；分组中的每一项为 type="groupItem"（带 name）。
 */
export function summarizeFields(fields, container) {
  const out = []
  for (const field of fields) {
    const value = container?.[field.key]
    if (isEmpty(field, value, container)) continue

    if (isChoice(field)) {
      const picked = value.selected
        .map((v) => field.options?.find((o) => o.value === v))
        .filter(Boolean)
      const children = []
      for (const opt of picked) {
        if (!opt.children?.length) continue
        const sub = summarizeFields(opt.children, value.sub?.[opt.value])
        if (sub.length) children.push({ key: opt.value, label: opt.label, type: 'option', value: null, display: '', children: sub })
      }
      out.push({
        key: field.key,
        label: field.label,
        type: field.type,
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
            type: 'groupItem',
            name: nameItem ? nameItem.value : '',
            value: null,
            display: '',
            children: sub
          }
        })
        .filter((it) => it.children.length)
      if (items.length) {
        out.push({ key: field.key, label: field.label, type: 'group', value: null, display: `${items.length} 个`, children: items })
      }
    } else if (field.type === 'tags') {
      out.push({ key: field.key, label: field.label, type: 'tags', value: [...value], display: value.join('、'), children: [] })
    } else {
      out.push({ key: field.key, label: field.label, type: field.type, value, display: String(value), children: [] })
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
