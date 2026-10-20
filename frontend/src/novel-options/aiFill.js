import { isChoice } from './fieldTypes'
import { summarizeFields } from './schema'

/**
 * AI 填写设定的辅助函数（请求体构造 + 把模型输出写回取值容器）。
 * 能由 AI 填写的字段类型：文本 / 多行文本 / 标签 / 单选 / 多选；数字、滑块是生成参数，由作者自己定。
 */
export const AI_TYPES = ['text', 'textarea', 'tags', 'single', 'multi']

export const aiFillable = (field) => AI_TYPES.includes(field.type)

/** 发给模型的字段说明：选择类带上选项文字 */
export function fieldSchema(field) {
  return {
    key: field.key,
    label: field.label,
    type: field.type,
    desc: field.desc || '',
    placeholder: field.placeholder || '',
    options: isChoice(field) ? (field.options || []).map((o) => o.label) : undefined
  }
}

/** 同一容器中已填写的其他字段 {标签: 展示值}，让模型与之配合 */
export function currentValues(fields, container, exceptKey) {
  const out = {}
  for (const s of summarizeFields((fields || []).filter((f) => f.key !== exceptKey), container)) {
    if (s.type === 'group') out[s.label] = s.children.map((c) => c.name || c.label)
    else out[s.label] = s.value ?? s.display
  }
  return out
}

/**
 * 把模型输出写进 container[field.key]。
 * 选择类：按选项文字匹配；没有对应选项时用 addOption 追加为自定义选项（与手动添加一致）。
 */
export function applyValue(field, container, value, addOption) {
  if (value == null || value === '') return false
  if (isChoice(field)) {
    let labels = (Array.isArray(value) ? value : [value]).map((v) => String(v).trim()).filter(Boolean)
    if (field.type === 'single') labels = labels.slice(0, 1)
    if (field.max) labels = labels.slice(0, field.max)
    const selected = labels.map((label) => {
      const hit = (field.options || []).find((o) => o.label === label)
      return (hit || addOption(field, label)).value
    })
    container[field.key] = { selected, sub: container[field.key]?.sub || {} }
    return selected.length > 0
  }
  if (field.type === 'tags') {
    container[field.key] = (Array.isArray(value) ? value : String(value).split(/[、，,]/)).map((v) => String(v).trim()).filter(Boolean)
    return container[field.key].length > 0
  }
  container[field.key] = Array.isArray(value) ? value.join('、') : String(value)
  return true
}
