// ② 视觉资产：角色定妆图 + 每个镜头的首帧图。svg = Claude Code 画矢量插画；openai = 图片接口；none = 不生成
import fs from 'node:fs'
import path from 'node:path'
import { getConfig } from '../config.js'
import { runClaude } from '../claude.js'
import { generateImage } from '../providers/image.js'
import { getProject, markStage, projectDir, saveProject } from '../store.js'
import { SIZES } from '../timeline.js'
import { mapLimit, now } from '../util.js'

function targetScenes(p, sceneIds) {
  const all = p.storyboard?.scenes || []
  if (!all.length) throw new Error('请先完成「编剧与分镜」')
  return sceneIds?.length ? all.filter((s) => sceneIds.includes(s.id)) : all
}

function characterLooks(sb, names) {
  return (sb.characters || [])
    .filter((c) => names.includes(c.name))
    .map((c) => `${c.name}：${c.look}`)
    .join('；')
}

export function scenePrompt(sb, s) {
  const looks = characterLooks(sb, s.characters || [])
  return [sb.style, s.visualPrompt, looks ? `角色外貌：${looks}` : '', '画面中不要出现文字'].filter(Boolean).join('。')
}

async function viaSvg(p, scenes, ctx) {
  const dir = projectDir(p.id)
  const [w, h] = SIZES[p.options.aspect] || SIZES['16:9']
  fs.mkdirSync(path.join(dir, 'assets'), { recursive: true })
  for (const s of scenes) fs.rmSync(path.join(dir, 'assets', `${s.id}.svg`), { force: true })
  const list = scenes.map((s) => `- assets/${s.id}.svg：${scenePrompt(p.storyboard, s)}`).join('\n')
  const prompt = `你是一名插画师，请用 SVG 为一支动态漫短视频绘制每个镜头的画面。

统一画风：${p.storyboard.style}
画布：viewBox="0 0 ${w} ${h}"，width="${w}" height="${h}"。

请用 Write 工具在当前目录逐个写出下列文件（每个文件都是完整独立的 SVG，以 <svg xmlns="http://www.w3.org/2000/svg" 开头）：
${list}

绘制要求：
- 有层次的完整场景：背景（天空 / 远景）、中景、前景、主体；多用渐变（linearGradient / radialGradient）、半透明叠加、光晕营造氛围与光影。
- 人物用剪影或简化造型即可，但姿态、位置、服饰颜色要与描述相符，同一角色在各镜头保持一致的配色。
- 画面元素铺满画布（后期会做推拉摇移，四周留出可裁切的内容）。
- 不要任何文字、不要 <text>、不要外部引用（图片 / 字体 / 链接），不要 <script>。
- 每个文件不超过 40 KB。
只写这些 SVG 文件，不要改其它文件。全部写完后用一句话总结。`
  await runClaude({ prompt, cwd: dir, model: getConfig().claude.svgModel, tools: ['Read', 'Write'], ctx })
  const fresh = getProject(p.id)
  let ok = 0
  for (const s of scenes) {
    const rel = `assets/${s.id}.svg`
    const abs = path.join(dir, rel)
    const valid = fs.existsSync(abs) && /^\s*(<\?xml[^>]*>\s*)?<svg[\s>]/i.test(fs.readFileSync(abs, 'utf8').slice(0, 400)) && !/<script/i.test(fs.readFileSync(abs, 'utf8'))
    if (valid) {
      fresh.assets.scenes[s.id] = { file: rel, provider: 'svg', at: now() }
      ok++
    } else {
      fs.rmSync(abs, { force: true })
      fresh.assets.scenes[s.id] = { file: null, provider: 'svg', at: now(), error: '没有画出合法的 SVG' }
    }
  }
  return { fresh, ok }
}

async function viaImageApi(p, scenes, ctx, { characters }) {
  const dir = projectDir(p.id)
  const cfg = getConfig().image.openai
  const sb = p.storyboard
  const charResults = {}
  if (characters && sb.characters?.length) {
    ctx.progress(5, '生成角色定妆图…')
    const res = await mapLimit(
      sb.characters,
      2,
      async (c, i) => {
        const file = await generateImage(cfg, {
          prompt: `${sb.style}。角色定妆图，单人半身像，纯色背景：${c.name}，${c.look}。画面中不要出现文字`,
          aspect: '1:1',
          fileBase: path.join(dir, 'assets', `char-${i + 1}`),
          signal: ctx.signal,
        })
        ctx.log(`  ✓ 角色 ${c.name}`)
        return path.relative(dir, file).replace(/\\/g, '/')
      },
      ctx.signal,
    )
    for (const r of res) {
      charResults[r.item.name] = r.ok ? { file: r.value, at: now() } : { file: null, error: r.error, at: now() }
      if (!r.ok) ctx.log(`  ✗ 角色 ${r.item.name}：${r.error}`)
    }
  }
  let done = 0
  const res = await mapLimit(
    scenes,
    2,
    async (s) => {
      const file = await generateImage(cfg, {
        prompt: scenePrompt(sb, s),
        aspect: p.options.aspect,
        fileBase: path.join(dir, 'assets', s.id),
        signal: ctx.signal,
      })
      done++
      ctx.progress(20 + (done / scenes.length) * 78, `镜头首帧图 ${done}/${scenes.length}`)
      ctx.log(`  ✓ ${s.id}`)
      return path.relative(dir, file).replace(/\\/g, '/')
    },
    ctx.signal,
  )
  const fresh = getProject(p.id)
  Object.assign(fresh.assets.characters, charResults)
  let ok = 0
  for (const r of res) {
    if (r.ok) ok++
    else ctx.log(`  ✗ ${r.item.id}：${r.error}`)
    fresh.assets.scenes[r.item.id] = r.ok ? { file: r.value, provider: 'openai', at: now() } : { file: null, provider: 'openai', error: r.error, at: now() }
  }
  return { fresh, ok }
}

export async function runAssets(projectId, ctx, { sceneIds, provider } = {}) {
  const p = getProject(projectId)
  const scenes = targetScenes(p, sceneIds)
  const kind = provider || getConfig().image.provider
  ctx.log(`▶ 视觉资产：${scenes.length} 个镜头，方式 ${kind}`)
  let fresh
  let ok = 0
  if (kind === 'none') {
    fresh = getProject(projectId)
    for (const s of scenes) fresh.assets.scenes[s.id] = { file: null, provider: 'none', at: now() }
    ok = scenes.length
  } else if (kind === 'svg') {
    ctx.progress(10, 'Claude Code 正在绘制 SVG 画面…')
    ;({ fresh, ok } = await viaSvg(p, scenes, ctx))
  } else if (kind === 'openai') {
    ;({ fresh, ok } = await viaImageApi(p, scenes, ctx, { characters: !sceneIds?.length }))
  } else throw new Error(`未知图片方式：${kind}`)
  const failed = scenes.length - ok
  markStage(fresh, 'assets', { status: failed && !ok ? 'failed' : 'done', at: now(), error: failed ? `${failed} 个镜头没有生成画面` : null })
  saveProject(fresh)
  ctx.log(`✓ 视觉资产：成功 ${ok}，失败 ${failed}`)
  if (!ok && failed) throw new Error('所有镜头都没有生成画面')
  return { ok, failed }
}
