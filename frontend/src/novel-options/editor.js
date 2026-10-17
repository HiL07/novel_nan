import { inject } from 'vue'

/**
 * 编辑上下文（由 views/novel/create.vue provide）：
 * {
 *   editMode: Ref<boolean>,                       // 编辑模式：显示新增/删除字段、子选项的入口
 *   addField(targetFields, { title, suggestions }) // 打开「添加选项项」对话框，确认后 push 到 targetFields
 *   removeField(targetFields, field)
 *   addOption(field, label) → option              // 给选择类字段追加自定义选项
 *   removeOption(field, value)
 * }
 */
export const EDITOR_KEY = Symbol('novelOptionEditor')

export function useOptionEditor() {
  const ctx = inject(EDITOR_KEY, null)
  if (!ctx) throw new Error('useOptionEditor 必须在 provide(EDITOR_KEY) 的页面内使用')
  return ctx
}
