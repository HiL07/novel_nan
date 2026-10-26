// 视频项目存储：data/videos/<id>/project.json（+ storyboard / assets / shots / voice / out.mp4）
import fs from 'node:fs'
import path from 'node:path'
import { VIDEOS_DIR } from './config.js'
import { BizError, newId, now, readJson, writeJsonAtomic } from './util.js'

export const STAGES = ['script', 'assets', 'shots', 'voice', 'edit', 'render']

const ID_RE = /^v\d{8}-[0-9a-f]{6}$/

export function projectDir(id) {
  if (!ID_RE.test(id || '')) throw new BizError(400, '非法项目 id')
  return path.join(VIDEOS_DIR, id)
}

function file(id) {
  return path.join(projectDir(id), 'project.json')
}

export function listProjects() {
  if (!fs.existsSync(VIDEOS_DIR)) return []
  return fs
    .readdirSync(VIDEOS_DIR)
    .filter((d) => ID_RE.test(d))
    .map((d) => readJson(path.join(VIDEOS_DIR, d, 'project.json')))
    .filter(Boolean)
    .map((p) => ({
      id: p.id,
      title: p.title,
      source: { type: p.source.type, novelTitle: p.source.novelTitle, chapters: p.source.chapters },
      options: p.options,
      sceneCount: p.storyboard?.scenes?.length || 0,
      stages: p.stages,
      hasVideo: !!p.render?.file,
      createdAt: p.createdAt,
      updatedAt: p.updatedAt,
    }))
    .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
}

export function getProject(id) {
  const p = readJson(file(id))
  if (!p) throw new BizError(404, '视频项目不存在')
  return p
}

export function saveProject(p) {
  p.updatedAt = now()
  writeJsonAtomic(file(p.id), p)
  return p
}

export function createProject({ title, source, options }) {
  const id = newId('v')
  const p = {
    id,
    title,
    source,
    options,
    storyboard: null,
    assets: { characters: {}, scenes: {} },
    shots: {},
    voice: {},
    bgm: null,
    edit: null,
    render: null,
    stages: Object.fromEntries(STAGES.map((s) => [s, { status: 'todo' }])),
    createdAt: now(),
    updatedAt: now(),
  }
  fs.mkdirSync(projectDir(id), { recursive: true })
  return saveProject(p)
}

export function deleteProject(id) {
  fs.rmSync(projectDir(id), { recursive: true, force: true })
}

/** 更新某一步的状态；把之后依赖它的步骤标记为「需重做」(stale) */
export function markStage(p, stage, patch) {
  p.stages[stage] = { ...p.stages[stage], ...patch }
  if (patch.status === 'done') {
    const later = STAGES.slice(STAGES.indexOf(stage) + 1)
    for (const s of later) if (p.stages[s]?.status === 'done') p.stages[s].stale = true
    p.stages[stage].stale = false
  }
}
