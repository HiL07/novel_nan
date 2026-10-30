import request, { aiRequest } from './request'

/**
 * 自动规划（docs/自动规划.md），两条路线：
 * - 故事优先（mode: 'story'，不依赖素材库）：写作参数 + 灵感 → 全书骨架 → 设定 → 素材点睛（可选）→ 10 章大纲 → 审稿 → 写进工作区
 * - 素材优先：一句构思 → 拆需求 → 选素材 → 设定草案 → 10 章大纲 + 伏笔计划 → 审稿 → 写进工作区
 * 只产出设定 / 大纲 / 计划伏笔，不写正文。模型步骤经 Java（带模型配置、组装素材）；草稿与写入直接调 Python。
 * model = {source: api, configId?} | {source: gguf} | {source: local, baseId}（components/persona/ModelPicker）
 */
const java = (novelId, step, body) =>
  request.post(`/api/novel/plan/${novelId}/${step}`, body, { timeout: 300000 }).then((res) => res.data)

/** 故事优先 ① {premise?, directions?, bookConfig?, tone?, conditions?, count?, model} → {ideas[{title, core, situation, conflict, payoff, hook}], usage} */
export const planIdea = (novelId, body) => java(novelId, 'idea', body)
/** 故事优先 ② {premise?, idea?, bookConfig?, book?（= 往后追加卷）, model} → {book{titleOptions, logline, storyHook, sellingPoints, worldPoints, volumes[{title, summary, chapters, stages[]}]}, issues, extended, usage} */
export const planBook = (novelId, body) => java(novelId, 'book', body)
/** 故事优先 ④ {settings, idea?, bookConfig?, excludeBooks?, stage?, model} → {suggestions[{target, kind, index, name, suggestion, fields, sources, leaks}], materials[], searched, usage} */
export const planEnrich = (novelId, body) => java(novelId, 'enrich', body)

/** ① {premise, tone?, conditions?, stage?, model} → {summary, needs[{category, query, count, role, why}], stage, opening, startIndex, usage} */
export const planNeeds = (novelId, body) => java(novelId, 'needs', body)
/** ② {needs, excludeBooks?, stage?} → {groups[{need, items[{material, score, variant, matchedLabel, from: search|weak, tier, fit}], hidden}], reranked}（本地，不花 token） */
export const planRetrieve = (novelId, body) => java(novelId, 'retrieve', body)
/** ③ {premise, tone?, stage?, materialIds, materialVariants?, model} → {draft{title, world, characters[], elements[], stages[]}, issues[], usage} */
export const planSettings = (novelId, body) => java(novelId, 'settings', body)
/** ④ {premise, tone?, settings, materialIds?, stage?, count?, model} → {outline{title, logline, synopsis, chapters[], foreshadows[], clocks[]}, issues[], usage} */
export const planOutline = (novelId, body) => java(novelId, 'outline', body)
/** ⑤ {premise, tone?, settings, outline, stage?, model} → {chapters[{index, problems[], revised?}], overall[], codeIssues[], usage} */
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
