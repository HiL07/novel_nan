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
 * 关键词 + 标签检索（分页）：{category, tags: [], tagMode: 'all'|'any', keyword, sourceBook?, excludeBooks?: [], pinned?, page, size}
 * sourceBook：只看某本书（MANUAL_BOOK = 手动添加的）；excludeBooks：屏蔽这些来源书（保留的素材除外）；pinned=true 只看保留的
 * 返回 MyBatis-Plus Page：{records, total, current, size}
 */
export const searchMaterials = ({ tags = [], excludeBooks = [], ...rest } = {}) =>
  get('/api/material/list', {
    ...rest,
    tags: tags.length ? tags.join(',') : undefined,
    excludeBooks: excludeBooks.length ? excludeBooks.join(',') : undefined
  })
/** 「手动添加」（无来源书）在按书筛选时的取值 */
export const MANUAL_BOOK = '__manual__'
/** 来源书 [{book（null = 手动添加）, count, pinned（保留数）, pending（待确认候选数）}] */
export const getMaterialSources = () => get('/api/material/sources')
/** 按来源书删除未保留的素材：{book, withCandidates?} → {deleted, kept, candidatesIgnored} */
export const deleteMaterialSource = (book, withCandidates = false) => post('/api/material/sources/delete', { book, withCandidates })
/** 保留 / 取消保留（保留的素材不会被「按书删除」删掉，屏蔽来源书时也照常可用） */
export const pinMaterial = (id, pinned) => post(`/api/material/${id}/pin`, { pinned })
/** AI 语义检索（使用「模型配置」中启用的模型）：{query, category?, tags?, excludeBooks?, limit?} → {expansion, considered, results: [{material, score, reason}]} */
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
