import request from './request'

/**
 * 跨世界观角色卡（Java /api/persona/**）。均返回 {code, message, data}。
 * model = {source: api, configId?} | {source: gguf} | {source: local, baseId}
 */
const get = (url, params) => request.get(url, { params }).then((res) => res.data)
const post = (url, body, config) => request.post(url, body, config).then((res) => res.data)
const SLOW = { timeout: 300000 } // 适配 / 试聊一次长输出

export const LAYERS = [
  { code: 'thinking', label: '思维方式' },
  { code: 'values', label: '价值观' },
  { code: 'motivation', label: '动机' },
  { code: 'fear', label: '恐惧' },
  { code: 'personality', label: '性格' },
  { code: 'behavior', label: '行为习惯' },
  { code: 'voice', label: '说话方式' },
  { code: 'relationship', label: '人际关系' }
]
export const layerLabel = (code) => LAYERS.find((l) => l.code === code)?.label || code
export const SITUATIONS = ['面对未知现象', '与自身理论矛盾的证据', '权威压制', '失败', '危险', '利益冲突']
export const PROVENANCE = {
  quoted: { label: '原文', type: 'success', tip: '有原文引文作证（引文已在原文里核实）' },
  inferred: { label: '推断', type: 'warning', tip: 'AI 从证据推断，没有直接引文' },
  user: { label: '作者', type: 'primary', tip: '作者写的或改过的' }
}
export const CHAT_MODES = [
  { value: 'free', label: '自由聊天' },
  { value: 'scene', label: '场景演绎' },
  { value: 'interview', label: '采访' }
]

// 原型卡
export const listPersonas = (params) => get('/api/persona/cards', params)
export const getPersona = (id) => get(`/api/persona/cards/${id}`)
export const extractPersona = (body) => post('/api/persona/cards/extract', body)
export const createPersona = (body) => post('/api/persona/cards/create', body)
export const resumePersona = (id) => post(`/api/persona/cards/${id}/resume`)
export const stopPersona = (id) => post(`/api/persona/cards/${id}/stop`)
export const updatePersonaMeta = (id, body) => post(`/api/persona/cards/${id}/meta`, body)
export const deletePersona = (id) => post(`/api/persona/cards/${id}/delete`)

// 版本（只追加）
export const listVersions = (id) => get(`/api/persona/cards/${id}/versions`)
export const getVersion = (id, no) => get(`/api/persona/cards/${id}/versions/${no}`)
export const saveVersion = (id, content, note = '') => post(`/api/persona/cards/${id}/versions/save`, { content, note })
export const restoreVersion = (id, no) => post(`/api/persona/cards/${id}/versions/${no}/restore`)

// 适配版本
export const listAdaptations = (cardId) => get(`/api/persona/cards/${cardId}/adaptations`)
/** {version?, novelId?, world?, wish?, model} */
export const adaptPersona = (cardId, body) => post(`/api/persona/cards/${cardId}/adapt`, body, SLOW)
export const getAdaptation = (id) => get(`/api/persona/adaptations/${id}`)
export const saveAdaptation = (id, content) => post(`/api/persona/adaptations/${id}/save`, { content })
export const confirmAdaptation = (id) => post(`/api/persona/adaptations/${id}/confirm`)
export const deleteAdaptation = (id) => post(`/api/persona/adaptations/${id}/delete`)
/** {novelId?, role?} → {novelId, personas, card, name, role} */
export const applyAdaptation = (id, body) => post(`/api/persona/adaptations/${id}/apply`, body)
/** {model, judgeConfigId?} */
export const startIdentityTest = (id, body) => post(`/api/persona/adaptations/${id}/test`, body)
export const cancelIdentityTest = (id) => post(`/api/persona/adaptations/${id}/test/cancel`)

// 工作区
export const novelPersonas = (novelId) => get(`/api/persona/novels/${novelId}`)
export const removeNovelPersona = (novelId, name) => post(`/api/persona/novels/${novelId}/remove`, { name })

// 试聊
export const listChats = (params) => get('/api/persona/chats', params)
/** {cardId? | adaptationId? | novelId + character{name, card, userRole?}, mode?, scene?, inner?} */
export const startChat = (body) => post('/api/persona/chats/start', body)
export const getChat = (id) => get(`/api/persona/chats/${id}`)
export const updateChat = (id, body) => post(`/api/persona/chats/${id}/update`, body)
export const sendChat = (id, body) => post(`/api/persona/chats/${id}/send`, body, SLOW)
export const regenerateChat = (id, body) => post(`/api/persona/chats/${id}/regenerate`, body, SLOW)
/** {index, rating: good|bad|null, reason?} */
export const chatFeedback = (id, body) => post(`/api/persona/chats/${id}/feedback`, body)
export const deleteChat = (id) => post(`/api/persona/chats/${id}/delete`)
export const feedbackSummary = (params) => get('/api/persona/feedback', params)
