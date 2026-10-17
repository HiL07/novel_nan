import request from './request'

/**
 * 创作素材库（Java /api/material/**）。均返回 {code, message, data}。
 * 分类代码与 Java MaterialService.CATEGORIES、python-service/app/materials.py 一致。
 */
export const MATERIAL_CATEGORIES = [
  { code: 'world', label: '世界观', icon: 'MapLocation', attrs: ['规则', '影响', '适用题材'] },
  { code: 'faction', label: '势力', icon: 'OfficeBuilding', attrs: ['类型', '立场', '实力', '特点'] },
  { code: 'character', label: '角色', icon: 'User', attrs: ['身份', '性格', '能力', '经历'] },
  { code: 'monster', label: '怪物', icon: 'Warning', attrs: ['外形', '能力', '弱点', '栖息地', '习性'] },
  { code: 'location', label: '地点', icon: 'Location', attrs: ['类型', '特点'] },
  { code: 'item', label: '物品功法', icon: 'Present', attrs: ['类别', '作用', '代价'] },
  { code: 'plot', label: '情节', icon: 'Guide', attrs: ['套路', '冲突', '转折', '可借鉴之处'] }
]
export const categoryOf = (code) => MATERIAL_CATEGORIES.find((c) => c.code === code)

const get = (url, params) => request.get(url, { params }).then((res) => res.data)
const post = (url, body, config) => request.post(url, body, config).then((res) => res.data)

/** [{code, label, count}] */
export const getMaterialCategories = () => get('/api/material/categories')
/** 标签云 [{tag, count}] */
export const getMaterialTags = (category) => get('/api/material/tags', { category })
/**
 * 关键词 + 标签检索（分页）：{category, tags: [], tagMode: 'all'|'any', keyword, page, size}
 * 返回 MyBatis-Plus Page：{records, total, current, size}
 */
export const searchMaterials = ({ tags = [], ...rest } = {}) =>
  get('/api/material/list', { ...rest, tags: tags.length ? tags.join(',') : undefined })
/** AI 语义检索（使用「模型配置」中启用的模型）：{query, category?, tags?, limit?} → {expansion, considered, results: [{material, score, reason}]} */
export const semanticSearch = (body) => post('/api/material/semantic-search', body, { timeout: 150000 })
export const getMaterial = (id) => get(`/api/material/${id}`)
/** 新增（无 id）或修改 */
export const saveMaterial = (m) => post('/api/material/save', m)
export const deleteMaterial = (id) => post(`/api/material/${id}/delete`)
/** 素材被应用到写作设定后记一次使用 */
export const recordMaterialUse = (ids) => post('/api/material/use', { ids })

/* ---------- AI 提取候选（待确认） ---------- */
export const listCandidates = (params = {}) => get('/api/material/candidates', params)
export const pendingCandidateCount = () => get('/api/material/candidates/count')
/** items: [{id, category?, subtype?, title?, summary?, attributes?, tags?, detail?}]（带修改后的内容） */
export const saveCandidates = (items) => post('/api/material/candidates/save', { items })
export const ignoreCandidates = (ids) => post('/api/material/candidates/ignore', { ids })
