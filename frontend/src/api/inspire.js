import request from './request'

/**
 * 灵感墙：多面墙（可关联工作区）、墙上的思路 / 素材、构思记录；构思三步 = 拆需求 → 检索素材 → 生成思路；
 * 细化、追问修改、逛素材。对应 Java InspirationController（/api/inspire/**）。
 */
const get = (url, params) => request.get(url, { params }).then((res) => res.data)
// 模型调用（拆需求 / 生成 / 细化 / 修改）可能要一两分钟
const LONG = { timeout: 5 * 60 * 1000 }
const post = (url, body, config) => request.post(url, body, config).then((res) => res.data)

export const TARGETS = [
  { value: 'adventure', label: '冒险路线' },
  { value: 'plot', label: '剧情段' },
  { value: 'location', label: '地点' },
  { value: 'monster', label: '怪物' },
  { value: 'faction', label: '势力' },
  { value: 'character', label: '角色' },
  { value: 'world', label: '世界设定' },
  { value: 'item', label: '物品功法' },
  { value: 'free', label: '自由构思' }
]
export const targetLabel = (v) => TARGETS.find((t) => t.value === v)?.label || '自由构思'

export const listWalls = () => get('/api/inspire/walls')
/** {id?, name, note?, novelId?（'' = 取消关联）, excludeBooks?} */
export const saveWall = (body) => post('/api/inspire/walls/save', body)
export const deleteWall = (id) => post(`/api/inspire/walls/${id}/delete`)
export const listItems = (wallId) => get(`/api/inspire/walls/${wallId}/items`)
/** {id?, wallId, type: idea|material, title, content, sources, note} */
export const saveItem = (body) => post('/api/inspire/items/save', body)
export const deleteItem = (id) => post(`/api/inspire/items/${id}/delete`)
export const pinMaterial = (wallId, materialId) => post(`/api/inspire/walls/${wallId}/pin`, { materialId })

/** ① 拆需求 {request, target, conditions, model} → {summary, needs, explore, usage, model} */
export const planInspiration = (wallId, body) => post(`/api/inspire/walls/${wallId}/plan`, body, LONG)
/** ② 检索素材（本地）{needs, explore} → {groups[{need, items[{material, score, variant, matchedLabel, from}]}], total} */
export const retrieveMaterials = (wallId, body) => post(`/api/inspire/walls/${wallId}/retrieve`, body, LONG)
/** ③ 生成思路 → 构思记录 {id, ideas, materials, usage…} */
export const generateInspiration = (wallId, body) => post(`/api/inspire/walls/${wallId}/ideas`, body, LONG)
export const refineIdea = (body) => post('/api/inspire/ideas/refine', body, LONG)
export const reviseIdea = (body) => post('/api/inspire/ideas/revise', body, LONG)
export const listRuns = (wallId) => get(`/api/inspire/walls/${wallId}/runs`)
export const updateRun = (id, ideas) => post(`/api/inspire/runs/${id}/update`, { ideas })
/** 逛素材：跨书随机，每本书最多 2 条 */
export const browseMaterials = (params) => get('/api/inspire/browse', params)

/** 「写进工作区」里的设定元素 / 构思方向：灵感墙页写进 sessionStorage，工作区页面读到后应用并删除 */
export const APPLY_KEY = 'nan_novel.inspire.apply'
