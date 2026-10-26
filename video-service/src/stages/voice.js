// 配音：每个镜头的 narration → voice/<id>.wav|mp3 + 时长（镜头时长按配音对齐）
import fs from 'node:fs'
import path from 'node:path'
import { getConfig } from '../config.js'
import { synthesize } from '../providers/tts.js'
import { getProject, markStage, projectDir, saveProject } from '../store.js'
import { mapLimit, now } from '../util.js'

export async function runVoice(projectId, ctx, { sceneIds, provider } = {}) {
  const p = getProject(projectId)
  const all = p.storyboard?.scenes || []
  if (!all.length) throw new Error('请先完成「编剧与分镜」')
  const scenes = sceneIds?.length ? all.filter((s) => sceneIds.includes(s.id)) : all
  const tcfg = getConfig().tts
  const kind = provider || tcfg.provider
  const cfg = tcfg[kind]
  if (!cfg) throw new Error(`未知配音提供商：${kind}`)
  const dir = projectDir(projectId)
  fs.mkdirSync(path.join(dir, 'voice'), { recursive: true })
  // 角色单独的音色：options.voices = {角色名: 音色}；旁白用默认
  const voices = p.options.voices || {}
  ctx.log(`▶ 配音：${scenes.length} 句，方式 ${kind}`)
  let done = 0
  const res = await mapLimit(
    scenes,
    kind === 'sapi' ? 1 : 3,
    async (s) => {
      const voice = voices[s.speaker] || undefined
      const r = await synthesize(kind, kind === 'sapi' && voice ? { ...cfg, voice } : cfg, {
        text: s.narration,
        voice,
        outBase: path.join(dir, 'voice', s.id),
        signal: ctx.signal,
      })
      done++
      ctx.progress((done / scenes.length) * 100, `配音 ${done}/${scenes.length}`)
      ctx.log(`  ✓ ${s.id} ${r.duration.toFixed(1)}s`)
      return { file: path.relative(dir, r.file).replace(/\\/g, '/'), duration: Math.round(r.duration * 1000) / 1000 }
    },
    ctx.signal,
  )
  const fresh = getProject(projectId)
  let ok = 0
  for (const r of res) {
    const s = r.item
    if (r.ok) {
      ok++
      fresh.voice[s.id] = { ...r.value, text: s.narration, provider: kind, at: now() }
    } else {
      ctx.log(`  ✗ ${s.id}：${r.error}`)
      fresh.voice[s.id] = { file: null, text: s.narration, provider: kind, error: r.error, at: now() }
    }
  }
  const failed = scenes.length - ok
  markStage(fresh, 'voice', { status: ok ? 'done' : 'failed', at: now(), error: failed ? `${failed} 句配音失败` : null })
  saveProject(fresh)
  if (!ok) throw new Error(res[0]?.error || '配音全部失败')
  ctx.log(`✓ 配音：成功 ${ok}，失败 ${failed}`)
  return { ok, failed }
}
