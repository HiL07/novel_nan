// 生成视频服务：小说 → Opus 编剧分镜 → 视觉资产 → 视频镜头 → 配音 → Claude Code 剪辑 → Remotion 成片
// 响应统一 {code, message, data}（code 0 = 成功）；只用 GET / POST（与项目其它服务一致）
import fs from 'node:fs'
import path from 'node:path'
import express from 'express'
import { CORS_ORIGINS, PORT, PY_URL, VIDEOS_DIR, getConfig, publicConfig, saveConfig } from './config.js'
import { claudeVersion } from './claude.js'
import { activeJob, cancelJob, getJob, startJob, view } from './jobs.js'
import { getNovel, listNovels } from './novels.js'
import { imageExt } from './providers/image.js'
import { remotionInstalled, removeProject, writeRegistry } from './remotion.js'
import { runAssets } from './stages/assets.js'
import { readEditCode, runEdit } from './stages/edit.js'
import { runRender } from './stages/render.js'
import { runScript, validateStoryboard } from './stages/script.js'
import { runShots } from './stages/shots.js'
import { runVoice } from './stages/voice.js'
import { STAGES, createProject, deleteProject, getProject, listProjects, markStage, projectDir, saveProject } from './store.js'
import { buildTimeline } from './timeline.js'
import { BizError, now, runProcess, safeJoin, writeFileAtomic } from './util.js'

const app = express()
app.disable('x-powered-by')

app.use((req, res, next) => {
  const origin = req.headers.origin
  if (origin && CORS_ORIGINS.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin)
    res.setHeader('Vary', 'Origin')
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST')
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type,X-File-Name')
  }
  if (req.method === 'OPTIONS') return res.sendStatus(204)
  next()
})

const json = express.json({ limit: '2mb' })
const ok = (res, data = null) => res.json({ code: 0, message: 'ok', data })

/** 包一层：BizError → 对应 HTTP 状态；其它错误 500（只回 message） */
const h = (fn) => async (req, res) => {
  try {
    const data = await fn(req, res)
    if (!res.headersSent) ok(res, data)
  } catch (e) {
    const status = e instanceof BizError ? e.status : 500
    if (status >= 500) console.error(`[video] ${req.method} ${req.path}:`, e.message)
    if (!res.headersSent) res.status(status).json({ code: status, message: e.message || '服务器错误', data: null })
  }
}

// ---------- 状态 / 配置 ----------

app.get(
  '/api/video/health',
  h(async () => {
    const cfg = getConfig()
    let python = false
    try {
      const r = await fetch(`${PY_URL}/api/health`, { signal: AbortSignal.timeout(3000) })
      python = r.ok
    } catch {
      python = false
    }
    return {
      claude: await claudeVersion(),
      remotion: remotionInstalled(),
      python,
      pythonUrl: PY_URL,
      node: process.version,
      providers: { image: cfg.image.provider, video: cfg.video.provider, tts: cfg.tts.provider },
    }
  }),
)

app.get('/api/video/config', h(() => publicConfig()))
app.post('/api/video/config', json, h((req) => saveConfig(req.body || {})))

/** 本机 Windows 语音列表（配音设置里选音色） */
app.get(
  '/api/video/tts/voices',
  h(async () => {
    if (process.platform !== 'win32') return []
    const r = await runProcess('powershell.exe', [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.GetInstalledVoices() | ? Enabled | % { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture + '|' + $_.VoiceInfo.Gender }; $s.Dispose()",
    ])
    return r.stdout
      .split(/\r?\n/)
      .filter(Boolean)
      .map((l) => {
        const [name, culture, gender] = l.trim().split('|')
        return { name, culture, gender }
      })
  }),
)

// ---------- 小说（只读，来自 Python AI 服务） ----------

app.get('/api/video/novels', h(() => listNovels()))
app.get('/api/video/novels/:id', h((req) => getNovel(req.params.id)))

// ---------- 项目 ----------

const ASPECTS = ['16:9', '9:16', '1:1']

function cleanOptions(o = {}, prev = {}) {
  const out = { ...prev }
  if (o.aspect !== undefined) {
    if (!ASPECTS.includes(o.aspect)) throw new BizError(400, '画幅只能是 16:9 / 9:16 / 1:1')
    out.aspect = o.aspect
  }
  if (o.durationSec !== undefined) out.durationSec = Math.max(15, Math.min(600, Number(o.durationSec) || 60))
  for (const k of ['style', 'requirement']) if (o[k] !== undefined) out[k] = String(o[k] || '').slice(0, k === 'style' ? 300 : 2000)
  for (const k of ['intro', 'subtitles']) if (o[k] !== undefined) out[k] = !!o[k]
  if (o.voices !== undefined) {
    out.voices = {}
    for (const [k, v] of Object.entries(o.voices || {})) if (v) out.voices[String(k).slice(0, 30)] = String(v).slice(0, 120)
  }
  return out
}

app.get('/api/video/projects', h(() => listProjects().map((p) => ({ ...p, job: activeJob(p.id) ? view(activeJob(p.id), 1e9) : null }))))

app.post(
  '/api/video/projects',
  json,
  h(async (req) => {
    const { title, source = {}, options = {} } = req.body || {}
    let src
    if (source.type === 'novel') {
      const chapters = [...new Set((source.chapters || []).map(Number).filter((n) => n > 0))].sort((a, b) => a - b)
      if (!source.novelId || !chapters.length) throw new BizError(400, '请选择小说和章节')
      if (chapters.length > 20) throw new BizError(400, '一次最多选 20 章')
      const novel = await getNovel(source.novelId)
      src = { type: 'novel', novelId: novel.id, novelTitle: novel.title, chapters }
    } else {
      const text = String(source.text || '').trim()
      if (!text) throw new BizError(400, '请填写原文或讲述要求')
      if (text.length > 30000) throw new BizError(400, '原文最多 30000 字')
      src = { type: 'text', text }
    }
    const opts = cleanOptions({ aspect: '16:9', durationSec: 60, intro: true, subtitles: true, ...options })
    return createProject({ title: String(title || '').trim().slice(0, 60) || '未命名视频', source: src, options: opts })
  }),
)

app.get(
  '/api/video/projects/:id',
  h((req) => {
    const p = getProject(req.params.id)
    const job = activeJob(p.id)
    let timeline = null
    try {
      timeline = p.storyboard ? buildTimeline(p) : null
    } catch {
      timeline = null
    }
    return { ...p, job: job ? view(job, 1e9) : null, timeline: timeline && { durationInFrames: timeline.durationInFrames, fps: timeline.fps, width: timeline.width, height: timeline.height, scenes: timeline.scenes.map((s) => ({ id: s.id, from: s.from, durationInFrames: s.durationInFrames })) } }
  }),
)

app.get('/api/video/projects/:id/code', h((req) => (getProject(req.params.id), readEditCode(req.params.id))))

app.post(
  '/api/video/projects/:id/update',
  json,
  h((req) => {
    const p = getProject(req.params.id)
    if (activeJob(p.id)) throw new BizError(400, '任务运行中，不能修改')
    const b = req.body || {}
    if (b.title !== undefined) p.title = String(b.title || '').trim().slice(0, 60) || p.title
    if (b.options) p.options = cleanOptions(b.options, p.options)
    if (b.storyboard) {
      try {
        p.storyboard = validateStoryboard(b.storyboard)
      } catch (e) {
        throw new BizError(400, e.message)
      }
      p.stages.script = { ...p.stages.script, status: 'done', edited: now() }
      for (const s of STAGES.slice(1)) if (p.stages[s]?.status === 'done') p.stages[s].stale = true
    }
    if (b.bgmVolume !== undefined && p.bgm) p.bgm.volume = Math.max(0, Math.min(1, Number(b.bgmVolume) || 0))
    return saveProject(p)
  }),
)

app.post(
  '/api/video/projects/:id/delete',
  h((req) => {
    const id = req.params.id
    getProject(id)
    if (activeJob(id)) throw new BizError(400, '任务运行中，请先取消')
    deleteProject(id)
    removeProject(id)
    return null
  }),
)

const RUNNERS = {
  script: { lane: 'claude', run: (id, ctx) => runScript(id, ctx) },
  assets: { lane: 'net', run: (id, ctx, b) => runAssets(id, ctx, b) },
  shots: { lane: 'net', run: (id, ctx, b) => runShots(id, ctx, b) },
  voice: { lane: 'net', run: (id, ctx, b) => runVoice(id, ctx, b) },
  edit: { lane: 'claude', run: (id, ctx, b) => runEdit(id, ctx, b) },
  render: { lane: 'render', run: (id, ctx) => runRender(id, ctx) },
}

app.post(
  '/api/video/projects/:id/stages/:stage',
  json,
  h((req) => {
    const { id, stage } = req.params
    const r = RUNNERS[stage]
    if (!r) throw new BizError(400, '未知步骤')
    const p = getProject(id)
    if (stage !== 'script' && !p.storyboard) throw new BizError(400, '请先完成「编剧与分镜」')
    const b = req.body || {}
    const body = {
      sceneIds: Array.isArray(b.sceneIds) ? b.sceneIds.map(String).slice(0, 80) : undefined,
      provider: b.provider ? String(b.provider) : undefined,
      instruction: b.instruction ? String(b.instruction).slice(0, 2000) : undefined,
      useClaude: b.useClaude !== false,
    }
    // SVG 画面由 Claude Code 绘制，走 Claude 通道
    const lane = stage === 'assets' && (body.provider || getConfig().image.provider) === 'svg' ? 'claude' : r.lane
    const job = startJob({
      projectId: id,
      stage,
      lane,
      run: async (ctx) => {
        const cur = getProject(id)
        markStage(cur, stage, { status: 'running', error: null })
        saveProject(cur)
        try {
          return await r.run(id, ctx, body)
        } catch (e) {
          const fresh = getProject(id)
          markStage(fresh, stage, { status: ctx.signal.aborted ? 'cancelled' : 'failed', error: ctx.signal.aborted ? '已取消' : e.message, at: now() })
          saveProject(fresh)
          throw e
        }
      },
    })
    return job
  }),
)

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp']

/** 手动上传某个镜头的画面（替换 AI 生成的首帧图） */
app.post(
  '/api/video/projects/:id/scenes/:sid/image',
  express.raw({ type: IMAGE_TYPES, limit: '15mb' }),
  h((req) => {
    const p = getProject(req.params.id)
    const sid = req.params.sid
    if (!p.storyboard?.scenes.some((s) => s.id === sid)) throw new BizError(404, '镜头不存在')
    if (!Buffer.isBuffer(req.body) || !req.body.length) throw new BizError(400, '请上传 png / jpg / webp 图片')
    const ext = imageExt(req.body)
    const rel = `assets/${sid}.${ext}`
    const dir = projectDir(p.id)
    for (const e of ['png', 'jpg', 'webp', 'svg']) if (e !== ext) fs.rmSync(path.join(dir, 'assets', `${sid}.${e}`), { force: true })
    writeFileAtomic(path.join(dir, rel), req.body)
    p.assets.scenes[sid] = { file: rel, provider: 'upload', at: now() }
    if (p.shots[sid]?.type === 'video') p.shots[sid].stale = true
    return saveProject(p)
  }),
)

const AUDIO_TYPES = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/wave', 'audio/ogg', 'audio/aac', 'audio/mp4', 'audio/x-m4a', 'audio/flac']
const AUDIO_EXT = { 'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/wave': 'wav', 'audio/ogg': 'ogg', 'audio/aac': 'aac', 'audio/mp4': 'm4a', 'audio/x-m4a': 'm4a', 'audio/flac': 'flac' }

/** 背景音乐（上传；之后可接 ACE-Step 等音乐模型） */
app.post(
  '/api/video/projects/:id/bgm',
  express.raw({ type: AUDIO_TYPES, limit: '40mb' }),
  h((req) => {
    const p = getProject(req.params.id)
    if (!Buffer.isBuffer(req.body) || !req.body.length) throw new BizError(400, '请上传 mp3 / wav / ogg / m4a 音频')
    const ext = AUDIO_EXT[String(req.headers['content-type']).split(';')[0]] || 'mp3'
    const dir = projectDir(p.id)
    if (p.bgm?.file) fs.rmSync(path.join(dir, p.bgm.file), { force: true })
    const rel = `bgm.${ext}`
    writeFileAtomic(path.join(dir, rel), req.body)
    const name = decodeURIComponent(String(req.headers['x-file-name'] || '')).slice(0, 100)
    p.bgm = { file: rel, name: name || rel, volume: p.bgm?.volume ?? 0.2, at: now() }
    return saveProject(p)
  }),
)

app.post(
  '/api/video/projects/:id/bgm/delete',
  h((req) => {
    const p = getProject(req.params.id)
    if (p.bgm?.file) fs.rmSync(path.join(projectDir(p.id), p.bgm.file), { force: true })
    p.bgm = null
    return saveProject(p)
  }),
)

/** 项目文件（图片 / 镜头 / 配音 / 成片），支持 Range（视频拖动） */
app.get(
  '/api/video/projects/:id/files/*file',
  h((req, res) => {
    const dir = projectDir(req.params.id)
    const rel = [].concat(req.params.file).join('/')
    if (rel === 'project.json') throw new BizError(404, '文件不存在')
    const abs = safeJoin(dir, rel)
    if (!fs.existsSync(abs) || !fs.statSync(abs).isFile()) throw new BizError(404, '文件不存在')
    if (req.query.download) res.attachment(path.basename(abs))
    return new Promise((resolve, reject) => {
      res.sendFile(abs, { headers: { 'Cache-Control': 'no-cache' }, dotfiles: 'deny' }, (err) => (err && !res.headersSent ? reject(err) : resolve()))
    })
  }),
)

// ---------- 任务 ----------

app.get('/api/video/jobs/:id', h((req) => view(getJob(req.params.id), Number(req.query.since) || 0)))
app.post('/api/video/jobs/:id/cancel', h((req) => cancelJob(req.params.id)))

app.use((req, res) => res.status(404).json({ code: 404, message: '接口不存在', data: null }))

// ---------- 启动 ----------

fs.mkdirSync(VIDEOS_DIR, { recursive: true })
// 服务重启后，内存任务已丢失：把仍是 running 的步骤标记为中断
for (const p of listProjects()) {
  const full = getProject(p.id)
  let changed = false
  for (const s of STAGES) {
    if (full.stages[s]?.status === 'running') {
      full.stages[s] = { ...full.stages[s], status: 'failed', error: '服务重启，任务中断' }
      changed = true
    }
  }
  if (changed) saveProject(full)
}
writeRegistry()

app.listen(PORT, () => {
  console.log(`[video] 生成视频服务 http://localhost:${PORT}  数据 ${VIDEOS_DIR}  Python ${PY_URL}`)
})
