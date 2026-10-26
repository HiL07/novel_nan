import { inject } from 'vue'

/**
 * 编辑上下文（由 views/novel/create.vue provide）：
 * {
 *   editMode: Ref<boolean>,                       // 编辑模式：显示新增/删除字段、子选项的入口
 *   addField(targetFields, { title, suggestions }) // 打开「添加选项项」对话框，确认后 push 到 targetFields
 *   removeField(targetFields, field)
 *   addOption(field, label) → option              // 给选择类字段追加自定义选项
 *   removeOption(field, value)
 *   ai: { enabled: Ref<boolean>, busyKeyOf(path, field),
 *         loading(key) → 这个请求正在进行, locked(scope) → 写到 scope 的按钮要禁用
 *           （本地模型：有请求就全锁；大模型：只锁范围重叠的，见 aiFill.scopesOverlap），
 *         fillField(field, container, siblings, path, action: polish|generate),  // 文本：润色扩写 / 按方向生成
 *         customOption(field, {action, seed, materials, path, container, siblings}) → {label, desc} | null,
 *                                                         // 选择类「自定义」：AI 润色 / 生成一个选项（素材只用这次选的）
 *         excludeBooks: Ref<string[]>,                    // 屏蔽的来源书（素材选择器用）
 *         genItems(field, list, path, count, concept?) → 新增项[],
 *         fillItem(field, item, path),                      // 补全分组中某一项（如某个角色）
 *         chat(character, messages, {scene, userRole}) → 回复文本 | null,   // 角色试聊
 *         cfg, apiModel }                                    // AI 填写设置（模型来源等）
 *   // AI 填写设定
 * }
 */
export const EDITOR_KEY = Symbol('novelOptionEditor')

export function useOptionEditor() {
  const ctx = inject(EDITOR_KEY, null)
  if (!ctx) throw new Error('useOptionEditor 必须在 provide(EDITOR_KEY) 的页面内使用')
  return ctx
}
