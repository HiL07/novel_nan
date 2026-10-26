// 读取小说创作工作区：只调用 Python AI 服务现有的只读接口（/api/gen/novels/**）
import { PY_URL } from './config.js'
import { BizError, fetchJson } from './util.js'

async function py(pathname) {
  let res
  try {
    res = await fetchJson(`${PY_URL}${pathname}`, { timeoutMs: 30_000 })
  } catch (e) {
    throw new BizError(503, `读取小说失败（Python AI 服务 ${PY_URL}）：${e.message}`)
  }
  if (res?.code !== 0) throw new BizError(400, res?.message || '读取小说失败')
  return res.data
}

export async function listNovels() {
  const list = await py('/api/gen/novels')
  return list.map((n) => ({ id: n.id, title: n.title, updatedAt: n.updatedAt, chapterCount: n.chapterCount ?? n.chapters?.length }))
}

export async function getNovel(id) {
  const n = await py(`/api/gen/novels/${encodeURIComponent(id)}`)
  return {
    id: n.id,
    title: n.title,
    chapters: (n.chapters || []).map((c) => ({ index: c.index, title: c.title, summary: c.summary, chars: c.chars, status: c.status })),
  }
}

export async function getChapterText(novelId, index) {
  const c = await py(`/api/gen/novels/${encodeURIComponent(novelId)}/chapters/${index}`)
  return { index: c.index, title: c.title, text: c.text || '' }
}
