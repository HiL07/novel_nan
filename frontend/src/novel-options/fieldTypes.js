/**
 * 字段类型注册表：新增一种选项控件只需在这里注册（label / 初始值 / 是否为选择类 / 摘要方式），
 * 再在 OptionField.vue 中映射到对应控件。
 *
 * 字段定义（Field）结构：
 * {
 *   key: string,              // 字段唯一键（同级唯一）
 *   label: string,            // 显示名称
 *   type: keyof FIELD_TYPES,
 *   desc?: string,            // 说明
 *   placeholder?: string,
 *   options?: Option[],       // 选择类字段的选项
 *   allowCustom?: boolean,    // 选择类：是否允许用户追加自定义选项（默认 true）
 *   max?: number,             // multi：最多可选数；number/slider：最大值
 *   min?: number, step?: number, default?: any, marks?: object,   // number / slider
 *   fields?: Field[],         // group：每一项包含的子字段
 *   itemLabel?: string,       // group：单项名称，如「角色」「怪物」
 *   custom?: boolean          // 用户自建（可删除）
 * }
 * 选项（Option）结构：{ value, label, desc?, children?: Field[], custom?: boolean }
 *   —— 选中某个选项后，展示它的 children 作为「子选项」，可无限嵌套。
 */
export const FIELD_TYPES = {
  single: { label: '单选', choice: true, init: () => ({ selected: [], sub: {} }) },
  multi: { label: '多选', choice: true, init: () => ({ selected: [], sub: {} }) },
  text: { label: '单行文本', init: () => '' },
  textarea: { label: '多行文本', init: () => '' },
  number: { label: '数字', init: (f) => f.default ?? null },
  slider: { label: '滑块（程度）', init: (f) => f.default ?? f.min ?? 0 },
  tags: { label: '标签（自由输入）', init: () => [] },
  group: { label: '可重复分组（如角色列表）', container: true, init: () => [] }
}

export const FIELD_TYPE_OPTIONS = Object.entries(FIELD_TYPES).map(([value, t]) => ({ value, label: t.label }))

export function isChoice(field) {
  return !!FIELD_TYPES[field.type]?.choice
}

export function initValue(field) {
  const t = FIELD_TYPES[field.type]
  return t ? t.init(field) : null
}
