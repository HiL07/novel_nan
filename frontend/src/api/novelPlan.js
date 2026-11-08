import request, { aiRequest } from './request'

/**
 * 自动规划（docs/自动规划.md），故事优先（不依赖素材库）：写作参数 + 灵感 → 设定 → 全书骨架 + 人物 / 元素 → 写进工作区；
 * 素材点睛 / 10 章大纲 / 审稿的接口还在（续规划和以后用）。原来的「素材优先」路线 2026-11-02 删掉了
 * 只产出设定 / 大纲 / 计划伏笔，不写正文。模型步骤经 Java（带模型配置、组装素材）；草稿与写入直接调 Python。
 * model = {source: api, configId?} | {source: gguf} | {source: local, baseId}（components/persona/ModelPicker）
 */
const java = (novelId, step, body) =>
  request.post(`/api/novel/plan/${novelId}/${step}`, body, { timeout: 300000 }).then((res) => res.data)

/** 故事优先 ① {premise?, directions?, bookConfig?, tone?, conditions?, count?, materialIds?（架空版）, model} → {ideas[{title, core, situation, conflict, payoff, hook, materials?[{id, title, used}]}], usage} */
export const planIdea = (novelId, body) => java(novelId, 'idea', body)
/** 参数这一步的小帮手 {kind: direction|style|conditions|premise|sellingPoint, text, premise?, conditions?, directions?, bookConfig?, materialIds?（架空版）, model} → {kind, value}（direction / style ≤7 字） */
export const planAssist = (novelId, body) => java(novelId, 'assist', body)
/** 设定的单个模块重新生成 {settings, module: rules|note|cards|power|abilities|mechanics|resources|characters|elements, category?, direction?, keep?, idea?, bookConfig?, book?, model} → {module, category, value, keep, usage} */
export const planSettingsPart = (novelId, body) => java(novelId, 'settings-part', body)
/** 故事优先 ③（在设定之后） {premise?, idea?, bookConfig?, settings?, volumePlan?[], volumeCount?, pace?: slow|normal|fast, book?（= 往后追加卷）, regen?{index, instruction}（= 只重来这一卷）, model} → {book{titleOptions, logline, storyHook, sellingPoints, worldPoints, volumes[{title, summary, chapters, stages[]}]}, issues, extended, usage} */
export const planBook = (novelId, body) => java(novelId, 'book', body)
/** 故事优先 · 骨架这一步：按骨架配配角和势力 / 地点 / 物品 / 怪物 → {characters, elements, stages, issues} */
export const planCast = (novelId, body) => java(novelId, 'cast', body)
/** 故事优先 ④ {settings, idea?, bookConfig?, excludeBooks?, stage?, model} → {suggestions[{target, kind, index, name, suggestion, fields, sources, leaks}], materials[], searched, usage} */
export const planEnrich = (novelId, body) => java(novelId, 'enrich', body)

/** 设定（世界 + 主角）{premise?, idea?, bookConfig?, book?, materialIds?, materialVariants?, model} → {draft{world, characters[], elements[], stages[]}, issues[], usage} */
export const planSettings = (novelId, body) => java(novelId, 'settings', body)
/** 10 章大纲 {premise?, idea?, bookConfig?, book?, settings, materialIds?, count?, model} → {outline{title, logline, synopsis, chapters[], foreshadows[], clocks[]}, issues[], usage} */
export const planOutline = (novelId, body) => java(novelId, 'outline', body)
/** 审稿 {premise?, idea?, bookConfig?, book?, settings, outline, model} → {chapters[{index, problems[], revised?}], overall[], codeIssues[], usage} */
export const planReview = (novelId, body) => java(novelId, 'review', body)

/** 写进工作区：大纲 + 账本里的计划伏笔 / 定时事件（设定由页面写进设定编辑器后保存）→ {outline, ids, planned} */
export const applyPlan = (novelId, outline, setTitle = false, extra = {}) =>
  aiRequest.post(`/api/gen/novels/${novelId}/plan/apply`, { outline, setTitle, ...extra }).then((res) => res.data)
/** 草稿（每一步的结果，刷新不丢）；draft = null 清空 */
export const getPlanDraft = (novelId) => aiRequest.get(`/api/gen/novels/${novelId}/plan/draft`).then((res) => res.data)
export const savePlanDraft = (novelId, draft) =>
  aiRequest.post(`/api/gen/novels/${novelId}/plan/draft`, { draft }).then((res) => res.data)

export const ROLE_LABELS = ['主角', '女主 / 男主', '反派', '导师', '伙伴', '宿敌', '配角']
export const ELEMENT_LABELS = { faction: '势力', location: '地点', item: '物品', monster: '怪物' }
export const ACTION_LABELS = { plant: '埋', advance: '推', resolve: '收' }

/* ---------- 故事优先：写作参数的选项（可以自己填） ---------- */
export const PLATFORMS = ['起点中文网', '番茄小说', '七猫免费', '晋江文学城', '纵横中文网', '飞卢小说', '不限']
export const GENRES = ['玄幻', '仙侠', '奇幻', '西幻', '都市', '历史', '科幻', '悬疑', '游戏', '武侠', '末世', '古言', '现言', '幻言', '轻小说']
export const STORY_TAGS = ['升级流', '无敌流', '系统', '重生', '穿越', '苟道', '争霸', '种田', '冒险', '克系', '规则怪谈', '无限流',
  '悬疑破案', '甜宠', '大女主', '群像', '学院', '废土']
export const DIRECTIONS = ['重生逆袭', '系统流', '扮猪吃虎', '苟道求生', '克苏鲁诡秘', '朝堂权谋', '赛博都市', '规则怪谈',
  '冒险探索', '种田经营', '穿书自救', '大女主成长', '师徒羁绊', '宿命对决']
export const AUDIENCES = ['男频读者', '女频读者', '全频读者']
export const POVS = ['第三人称', '第一人称']
export const TARGET_WORDS = ['30万字', '50万字', '100万字', '200万字']
export const CHAPTER_WORDS = ['2000字', '3000字', '4000字']
export const blankBookConfig = () => ({ platform: '番茄小说', genre: '', tags: [], audience: '男频读者', sellingPoint: '', pov: '第三人称',
  style: '', targetWords: '100万字', chapterWords: '3000字' })

/** 全书骨架 → 按章节排好的阶段（与 Python planner.book_layout 同一规则：阶段没写章数就平分本卷剩下的，卷没写章数按 30 章） */
export function bookLayout(book) {
  const rows = []
  let n = 1
  ;(book?.volumes || []).forEach((v, vi) => {
    const stages = v.stages?.length ? v.stages : [{ title: v.title, chapters: 0, goal: v.summary || '' }]
    const given = stages.map((s) => Number(s.chapters) || 0)
    const total = Number(v.chapters) || given.reduce((a, b) => a + b, 0) || 30
    const missing = given.map((g, i) => (g ? -1 : i)).filter((i) => i >= 0)
    if (missing.length) {
      const share = Math.max(1, Math.floor((total - given.reduce((a, b) => a + b, 0)) / missing.length))
      for (const i of missing) given[i] = share
    }
    stages.forEach((s, si) => {
      rows.push({ ...s, volume: vi, stage: si, volumeTitle: v.title, start: n, end: n + given[si] - 1 })
      n += given[si]
    })
  })
  return rows
}

/** 骨架 → 设定编辑器的阶段表行（与 Python planner.book_stages 同一规则） */
export function bookStages(book) {
  return bookLayout(book).map((r) => {
    let note = `${r.volumeTitle}·${r.title || '阶段'}：${r.goal || ''}`
    if (r.mustHappen?.length) note += `；必须发生：${r.mustHappen.join('、')}`
    return { range: `${r.start}-${r.end}`, power: r.power || (r.endState || '').slice(0, 60), tierMax: r.tierMax, note: note.slice(0, 300) }
  })
}

export const PACES = [
  { value: 'slow', label: '慢热', desc: '每卷只推进一小步，前几卷舞台基本不换' },
  { value: 'normal', label: '适中', desc: '每卷一个新目标，舞台逐步扩大' },
  { value: 'fast', label: '偏快', desc: '每卷明显升级 / 换地图' }
]
