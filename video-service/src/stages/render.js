// ⑤ 渲染成片：用最新的分镜 / 资产 / 配音重建时间轴，Remotion 渲染到 data/videos/<id>/out.mp4
import fs from 'node:fs'
import path from 'node:path'
import { remotionInstalled, render, writeProjectData } from '../remotion.js'
import { getProject, markStage, projectDir, saveProject } from '../store.js'
import { buildTimeline } from '../timeline.js'
import { now } from '../util.js'

export async function runRender(projectId, ctx) {
  if (!remotionInstalled()) throw new Error('Remotion 未安装：在 video-service 目录运行 npm run setup')
  const p = getProject(projectId)
  const t = buildTimeline(p)
  writeProjectData(projectId, t)
  const dir = projectDir(projectId)
  const out = path.join(dir, 'out.mp4')
  ctx.log(`▶ 渲染 ${t.width}×${t.height}，${(t.durationInFrames / t.fps).toFixed(1)} 秒（首次渲染会自动下载 Chrome Headless Shell）`)
  ctx.progress(2, '打包工程…')
  const started = Date.now()
  await render(projectId, { publicDir: dir, outFile: out, ctx })
  const fresh = getProject(projectId)
  fresh.render = {
    file: 'out.mp4',
    size: fs.statSync(out).size,
    durationSec: Math.round((t.durationInFrames / t.fps) * 10) / 10,
    seconds: Math.round((Date.now() - started) / 1000),
    at: now(),
    edit: fresh.edit?.by || 'default',
  }
  markStage(fresh, 'render', { status: 'done', at: now(), error: null })
  saveProject(fresh)
  ctx.log(`✓ 成片完成：${(fresh.render.size / 1024 / 1024).toFixed(1)} MB，用时 ${fresh.render.seconds}s`)
  return fresh.render
}
