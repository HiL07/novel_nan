import request from './request'

/**
 * 创作素材库（Java /api/material/**）。均返回 {code, message, data}。
 * 分类代码与 Java MaterialService.CATEGORIES、python-service/app/materials.py 一致。
 */
export const MATERIAL_CATEGORIES = [
  { code: 'world', label: '世界观', icon: 'MapLocation', attrs: ['规则内容', '代价', '限制', '谁能打破', '对社会的影响'] },
  { code: 'faction', label: '势力', icon: 'OfficeBuilding', attrs: ['结构', '目标', '资源', '内部矛盾'] },
  { code: 'character', label: '角色', icon: 'User', attrs: ['人设核心', '反差', '能力', '动机', '关系', '名场面'] },
  { code: 'monster', label: '怪物', icon: 'Warning', attrs: ['外形', '能力', '弱点及原因', '习性', '社会结构', '来源', '与人类的关系'] },
  { code: 'location', label: '地点', icon: 'Location', attrs: ['特征', '危险', '特殊规则', '产出'] },
  { code: 'item', label: '物品功法', icon: 'Present', attrs: ['作用', '代价', '获取方式', '限制'] },
  { code: 'plot', label: '情节', icon: 'Guide', attrs: ['起因', '冲突', '转折', '结果', '功能'] }
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
/* ---------- 向量检索（本地 embedding 模型，如 bge-small-zh；不用大模型） ---------- */
/** 选用的向量模型 id（素材库页与素材选择弹窗共用）；空 = 服务端默认 */
const VECTOR_MODEL_KEY = 'nan_novel.material.vectorModel'
export function getVectorModelId() {
  try {
    return localStorage.getItem(VECTOR_MODEL_KEY) || ''
  } catch {
    return ''
  }
}
export function setVectorModelId(id) {
  try {
    localStorage.setItem(VECTOR_MODEL_KEY, id || '')
  } catch {
    /* 隐私模式等：不记住也能用 */
  }
}
/** {query, modelId?, category?, tags?, excludeBooks?, limit?} → {results[{material, score(0–100), similarity}], total, considered, model, modelId, device, encoded, cached, ms} */
export const vectorSearch = (body) => post('/api/material/vector-search', { modelId: getVectorModelId() || undefined, ...body }, { timeout: 200000 })
/** 全部素材的向量化情况（encode=false）/ 一键全部向量化 → {total, cached, encoded, pending, model, device, ms} */
export const vectorIndex = (encode = false) => post('/api/material/vector-index', { modelId: getVectorModelId() || undefined, encode }, { timeout: 600000 })
/** 向量检索后勾选 / 没勾选的素材 {query, modelId, shownIds, pickedIds, context}（以后微调向量模型用）；失败不打扰 */
export const vectorFeedback = (body) => post('/api/material/vector-feedback', body).catch(() => null)
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

// ------------------------------------------------------------------ 精炼 / 合并

/** 查找相似素材组（本地向量模型，不花 token）{categories?, books?, crossBookOnly?, threshold?, maxGroup?, modelId?} → {found, skipped, …} */
export const findMerges = (body) =>
  post('/api/material/merge/find', { modelId: getVectorModelId() || undefined, ...body }, { timeout: 15 * 60 * 1000 })
/** 合并建议（分页）status: open | APPLIED | IGNORED */
export const listMerges = (params) => get('/api/material/merge/list', params)
/** {open, drafted, cross, APPLIED, IGNORED} */
export const mergeCounts = () => get('/api/material/merge/counts')
/** AI 写合并稿（后台逐组）{ids, model} */
export const draftMerges = (ids, model) => post('/api/material/merge/draft', { ids, model })
export const mergeDraftStatus = () => get('/api/material/merge/draft/status')
export const stopMergeDraft = () => post('/api/material/merge/draft/stop')
/** 确认合并 {memberIds, title, subtype, summary, detail, attributes, tags, variants} → 主条目 */
export const applyMerge = (id, body) => post(`/api/material/merge/${id}/apply`, body)
export const ignoreMerges = (ids) => post('/api/material/merge/ignore', { ids })
export const restoreMerges = (ids) => post('/api/material/merge/restore', { ids })
/** 拆分主条目：成员回到素材库 */
export const unmergeMaterial = (materialId) => post(`/api/material/merge/unmerge/${materialId}`)

/** 合并而来、有多个可选版本的素材 */
export const isMultiVersion = (m) => m?.source?.type === 'merge' && (m.source.variants?.length || 0) > 1

/** 选中素材里多版本素材的用法 → 请求里的 materialVariants {素材 id: 'blend' | 成员 id}（'auto' = 让 AI 选，默认，不用发） */
export function materialVariants(list) {
  const out = {}
  for (const m of list || []) {
    if (isMultiVersion(m) && m.variant && m.variant !== 'auto') out[m.id] = String(m.variant)
  }
  return out
}
