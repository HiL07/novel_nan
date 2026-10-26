// ③ 视频镜头：首帧图 → 视频模型（图生视频；没有位图首帧时文生视频）。kenburns = 不调用模型，直接用首帧图推拉摇移
import fs from 'node:fs'
import path from 'node:path'
import { getConfig } from '../config.js'
import { mp4Duration } from '../media.js'
import { generateShot } from '../providers/video.js'
import { getProject, markStage, projectDir, saveProject } from '../store.js'
import { mapLimit, now } from '../util.js'
import { scenePrompt } from './assets.js'

const MOTION_TEXT = {
  'push-in': '镜头缓慢推近',
  'pull-out': '镜头缓慢拉远',
  'pan-left': '镜头向左平移',
  'pan-right': '镜头向右平移',
  static: '固定机位，画面中人物与环境有细微动态',
}

export async function runShots(projectId, ctx, { sceneIds, provider } = {}) {
  const p = getProject(projectId)
  const all = p.storyboard?.scenes || []
  if (!all.length) throw new Error('请先完成「编剧与分镜」')
  const scenes = sceneIds?.length ? all.filter((s) => sceneIds.includes(s.id)) : all
  const vcfg = getConfig().video
  const kind = provider || vcfg.provider
  const dir = projectDir(projectId)
  ctx.log(`▶ 视频镜头：${scenes.length} 个，方式 ${kind}`)

  if (kind === 'kenburns') {
    const fresh = getProject(projectId)
    for (const s of scenes) fresh.shots[s.id] = { type: 'image', provider: 'kenburns', at: now() }
    markStage(fresh, 'shots', { status: 'done', at: now(), error: null })
    saveProject(fresh)
    ctx.log('✓ 使用首帧图推拉摇移（未调用视频模型）')
    return { ok: scenes.length, failed: 0 }
  }

  const cfg = vcfg[kind]
  if (!cfg) throw new Error(`未知视频提供商：${kind}`)
  fs.mkdirSync(path.join(dir, 'shots'), { recursive: true })
  let done = 0
  const res = await mapLimit(
    scenes,
    2,
    async (s) => {
      const asset = p.assets?.scenes?.[s.id]?.file
      const image = asset && /\.(png|jpe?g|webp)$/i.test(asset) ? path.join(dir, asset) : null
      const rel = `shots/${s.id}.mp4`
      ctx.log(`  … ${s.id} ${image ? '图生视频' : '文生视频'}`)
      await generateShot(kind, cfg, {
        prompt: `${scenePrompt(p.storyboard, s)}。${MOTION_TEXT[s.cameraMotion] || ''}`,
        image,
        aspect: p.options.aspect,
        durationSec: vcfg.durationSec || 5,
        outFile: path.join(dir, rel),
        signal: ctx.signal,
        onWait: (status, sec) => ctx.progress(null, `${s.id} ${status || '生成中'}（${sec}s）`),
      })
      done++
      ctx.progress((done / scenes.length) * 100, `镜头 ${done}/${scenes.length}`)
      ctx.log(`  ✓ ${s.id}`)
      return { file: rel, duration: mp4Duration(path.join(dir, rel)) }
    },
    ctx.signal,
  )
  const fresh = getProject(projectId)
  let ok = 0
  for (const r of res) {
    if (r.ok) {
      ok++
      fresh.shots[r.item.id] = { type: 'video', provider: kind, file: r.value.file, duration: r.value.duration, at: now() }
    } else {
      ctx.log(`  ✗ ${r.item.id}：${r.error}`)
      // 失败的镜头退回首帧图推拉摇移，保证能出片
      fresh.shots[r.item.id] = { type: 'image', provider: kind, error: r.error, at: now() }
    }
  }
  const failed = scenes.length - ok
  markStage(fresh, 'shots', { status: 'done', at: now(), error: failed ? `${failed} 个镜头生成失败，已用首帧图代替` : null })
  saveProject(fresh)
  ctx.log(`✓ 视频镜头：成功 ${ok}，失败 ${failed}`)
  return { ok, failed }
}
