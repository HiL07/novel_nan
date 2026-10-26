// ① 编剧与分镜：Claude Code（默认 Opus）读 source.txt，写 storyboard.json；服务端校验，不合格回喂修一次
import fs from 'node:fs'
import path from 'node:path'
import { z } from 'zod'
import { getConfig } from '../config.js'
import { runClaude } from '../claude.js'
import { getChapterText } from '../novels.js'
import { getProject, markStage, projectDir, saveProject } from '../store.js'
import { now, readJson } from '../util.js'

export const MOTIONS = ['push-in', 'pull-out', 'pan-left', 'pan-right', 'static']

export const StoryboardSchema = z.object({
  title: z.string().min(1).max(60),
  logline: z.string().max(300).optional().default(''),
  style: z.string().min(1).max(300),
  characters: z
    .array(z.object({ name: z.string().min(1).max(30), look: z.string().max(400) }))
    .max(20)
    .default([]),
  scenes: z
    .array(
      z.object({
        id: z.string().min(1).max(20),
        narration: z.string().min(1).max(400),
        speaker: z.string().max(30).default('旁白'),
        visualPrompt: z.string().min(1).max(800),
        characters: z.array(z.string().max(30)).max(8).default([]),
        cameraMotion: z.enum(MOTIONS).default('push-in'),
        durationSec: z.number().min(2).max(20).default(5),
        mood: z.string().max(40).default(''),
      }),
    )
    .min(1)
    .max(80),
})

/** 校验 + 规整（id 去重补齐）；不合格抛出带字段路径的错误 */
export function validateStoryboard(raw) {
  const r = StoryboardSchema.safeParse(raw)
  if (!r.success) {
    const msg = r.error.issues
      .slice(0, 12)
      .map((i) => `${i.path.join('.') || '(根)'}：${i.message}`)
      .join('；')
    throw new Error(`分镜格式不正确：${msg}`)
  }
  const sb = r.data
  const seen = new Set()
  sb.scenes.forEach((s, i) => {
    let id = s.id.replace(/[^A-Za-z0-9_-]/g, '') || `s${i + 1}`
    while (seen.has(id)) id = `${id}_${i + 1}`
    seen.add(id)
    s.id = id
  })
  return sb
}

const ASPECT_LABEL = { '16:9': '横屏 16:9', '9:16': '竖屏 9:16', '1:1': '方形 1:1' }

function buildPrompt(p) {
  const o = p.options
  const sceneHint = Math.max(3, Math.round((o.durationSec || 60) / 6))
  return `你是一名专业的短视频编剧兼分镜师。请把当前目录下 source.txt 的内容改编成一支「动态漫 / 有声小说」短视频的分镜脚本。

## 要求
- 成片目标时长约 ${o.durationSec || 60} 秒，${ASPECT_LABEL[o.aspect] || o.aspect}；大约 ${sceneHint} 个镜头（可按内容增减），每个镜头 3–10 秒。
- 视觉风格：${o.style || '由你根据内容决定（统一、适合 AI 生图的画风描述）'}。
- 旁白 / 台词（narration）用简体中文，口语化、适合朗读；每个镜头一到两句，读完时长要与 durationSec 相符（约每秒 4 个字）。
- speaker：旁白写「旁白」，角色台词写角色名（必须出现在 characters 里）。
- visualPrompt：给 AI 生图 / 生视频模型的画面描述（中文），写清主体、动作、场景、光线、构图、镜头景别，风格与 style 保持一致；出现角色时把该角色的外貌要点写进去，保证前后一致；不要在画面里要求出现文字。
- characters：出场的主要角色，look 写固定的外貌、服饰特征（用于保持角色一致性）。
- cameraMotion 只能是 ${MOTIONS.join(' / ')} 之一。
- 节奏：开头 1–2 个镜头抓住注意力，结尾留悬念或情绪落点。
${o.requirement ? `- 作者的额外要求：${o.requirement}\n` : ''}
## 输出
只用 Write 工具在当前目录写一个文件 storyboard.json（UTF-8，合法 JSON，不要写其它文件），结构如下：
{
  "title": "短视频标题（≤20 字）",
  "logline": "一句话简介",
  "style": "统一的视觉风格描述",
  "characters": [{"name": "角色名", "look": "外貌服饰要点"}],
  "scenes": [
    {"id": "s1", "narration": "旁白或台词", "speaker": "旁白", "visualPrompt": "画面描述", "characters": ["角色名"], "cameraMotion": "push-in", "durationSec": 5, "mood": "紧张"}
  ]
}
写完后用一句话总结你做了什么。`
}

async function loadSource(p, ctx) {
  const s = p.source
  if (s.type === 'text') return s.text
  const parts = []
  for (const idx of s.chapters) {
    const c = await getChapterText(s.novelId, idx)
    parts.push(`第${c.index}章 ${c.title || ''}\n\n${c.text}`)
    ctx.log(`  读取第 ${c.index} 章《${c.title || ''}》${c.text.length} 字`)
  }
  return `《${s.novelTitle || ''}》\n\n${parts.join('\n\n')}`
}

export async function runScript(projectId, ctx) {
  const p = getProject(projectId)
  const dir = projectDir(projectId)
  const cfg = getConfig().claude
  ctx.progress(5, '准备原文')
  let text = await loadSource(p, ctx)
  if (!text.trim()) throw new Error('原文为空')
  // 太长的原文只取前 30000 字，避免一次会话过大
  if (text.length > 30000) {
    ctx.log(`  原文 ${text.length} 字，只取前 30000 字`)
    text = text.slice(0, 30000)
  }
  fs.writeFileSync(path.join(dir, 'source.txt'), text, 'utf8')
  const sbFile = path.join(dir, 'storyboard.json')
  fs.rmSync(sbFile, { force: true })

  ctx.progress(15, 'Claude Code 正在编剧与分镜…')
  await runClaude({ prompt: buildPrompt(p), cwd: dir, model: cfg.scriptModel, tools: ['Read', 'Write', 'Edit'], ctx })

  let sb
  try {
    const raw = readJson(sbFile)
    if (!raw) throw new Error('没有写出 storyboard.json 或不是合法 JSON')
    sb = validateStoryboard(raw)
  } catch (e) {
    ctx.log(`  ${e.message}，让 Claude Code 修正…`)
    ctx.progress(70, '修正分镜格式…')
    await runClaude({
      prompt: `当前目录的 storyboard.json 有问题：${e.message}\n请修正它（保持内容不变，只修结构 / 字段 / 取值范围），只改这个文件。字段要求：scenes[].cameraMotion 只能是 ${MOTIONS.join(' / ')}；durationSec 是 2–20 的数字；narration ≤ 400 字。`,
      cwd: dir,
      model: cfg.scriptModel,
      tools: ['Read', 'Write', 'Edit'],
      ctx,
    })
    const raw = readJson(sbFile)
    if (!raw) throw new Error('storyboard.json 仍不是合法 JSON')
    sb = validateStoryboard(raw)
  }

  const fresh = getProject(projectId)
  fresh.storyboard = sb
  if (!fresh.title || fresh.title === '未命名视频') fresh.title = sb.title
  markStage(fresh, 'script', { status: 'done', at: now(), error: null })
  saveProject(fresh)
  ctx.log(`✓ 分镜完成：${sb.scenes.length} 个镜头，${sb.characters.length} 个角色`)
  return { scenes: sb.scenes.length }
}
