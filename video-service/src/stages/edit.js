// ④ Claude Code 剪辑：在 remotion/src/projects/<id>/ 写剪辑与动画程序（转场、字幕、标题卡…），类型检查不过就回喂修复
import fs from 'node:fs'
import path from 'node:path'
import { REMOTION_DIR, getConfig } from '../config.js'
import { runClaude } from '../claude.js'
import { remotionProjectDir, resetToDefault, typecheck, writeProjectData, writeRegistry } from '../remotion.js'
import { getProject, markStage, saveProject } from '../store.js'
import { buildTimeline } from '../timeline.js'
import { now } from '../util.js'

const FIX_ROUNDS = 2

function summary(t) {
  const sec = (f) => (f / t.fps).toFixed(1)
  return t.scenes
    .map((s) => `- ${s.id}：${sec(s.from)}s 起，${sec(s.durationInFrames)}s，${s.visual.type}，说话人 ${s.speaker}，情绪 ${s.mood || '—'}，运镜 ${s.cameraMotion}：${s.narration.slice(0, 40)}`)
    .join('\n')
}

function buildPrompt(id, t, p, instruction) {
  return `你在一个 Remotion 工程里（请先读当前目录的 CLAUDE.md），任务是为视频项目 ${id} 编写剪辑与动画程序。

## 素材
- 时间轴：src/projects/${id}/data.json（只读，类型 Timeline 见 src/lib/types.ts）。
- 要改写的文件：src/projects/${id}/index.tsx（导出 \`export const Video: React.FC<{ data: Timeline }>\`），当前是默认剪辑（src/lib/DefaultVideo.tsx），可以在它基础上改，也可以重写；需要的话在 src/projects/${id}/ 下新建组件文件。
- 成片：${t.width}×${t.height}，${t.fps} fps，共 ${(t.durationInFrames / t.fps).toFixed(1)} 秒；片头 ${(t.introFrames / t.fps).toFixed(1)} 秒；${t.bgm ? '有背景音乐' : '无背景音乐'}。
- 标题：${t.title}；风格：${p.storyboard.style}
- 镜头：
${summary(t)}

## 目标
做成一支有电影感的动态漫 / 有声小说短视频：
- 片头标题卡设计贴合故事气质；
- 镜头之间按情绪选择转场（硬切、交叉淡化、闪白、推移等，可用 @remotion/transitions 或自己用 interpolate 实现，但每个镜头的起止帧和配音位置不能变）；
- 图片镜头按 cameraMotion 做推拉摇移（可以叠加光效、粒子、暗角、胶片颗粒等氛围层）；
- 字幕清晰易读，说话人不是旁白时显示角色名；
- 情绪激烈的镜头可加轻微震动 / 闪光等强调，但不要喧宾夺主。
${instruction ? `\n## 作者这次的修改要求（优先满足）\n${instruction}\n` : ''}
## 约束
只修改 src/projects/${id}/ 下的文件；资源一律 staticFile(data 里的路径)；不安装依赖；完成后运行 \`npx tsc --noEmit\`，确保 src/projects/${id}/ 没有类型错误。最后用一两句话说明你做了哪些设计。`
}

export async function runEdit(projectId, ctx, { instruction, useClaude = true } = {}) {
  const p = getProject(projectId)
  const t = buildTimeline(p)
  writeProjectData(projectId, t)
  writeRegistry()
  const index = path.join(remotionProjectDir(projectId), 'index.tsx')

  if (!useClaude) {
    resetToDefault(projectId)
    const fresh = getProject(projectId)
    fresh.edit = { by: 'default', at: now(), instruction: null }
    markStage(fresh, 'edit', { status: 'done', at: now(), error: null })
    saveProject(fresh)
    ctx.log('✓ 已使用默认剪辑模板')
    return { by: 'default' }
  }

  const backup = fs.readFileSync(index, 'utf8')
  const model = getConfig().claude.editModel
  const tools = ['Read', 'Write', 'Edit', 'Glob', 'Grep', 'Bash(npx tsc:*)']
  ctx.progress(10, 'Claude Code 正在编写剪辑程序…')
  const r = await runClaude({ prompt: buildPrompt(projectId, t, p, instruction), cwd: REMOTION_DIR, model, tools, ctx })

  let errors = await typecheck(projectId, ctx.signal)
  for (let round = 1; errors.length && round <= FIX_ROUNDS; round++) {
    ctx.log(`  类型检查有 ${errors.length} 条错误，第 ${round} 次让 Claude Code 修复`)
    ctx.progress(70 + round * 10, `修复类型错误（第 ${round} 次）`)
    await runClaude({
      prompt: `src/projects/${projectId}/ 的代码有类型错误，请修复（只改这个目录下的文件），修完运行 npx tsc --noEmit 确认：\n${errors.join('\n')}`,
      cwd: REMOTION_DIR,
      model,
      tools,
      ctx,
    })
    errors = await typecheck(projectId, ctx.signal)
  }
  if (errors.length) {
    fs.writeFileSync(index, backup, 'utf8')
    throw new Error(`Claude Code 写的剪辑程序仍有类型错误，已恢复上一版：${errors.slice(0, 5).join(' | ')}`)
  }
  const fresh = getProject(projectId)
  fresh.edit = { by: 'claude', at: now(), instruction: instruction || null, note: r.text.slice(0, 1000) }
  markStage(fresh, 'edit', { status: 'done', at: now(), error: null })
  saveProject(fresh)
  ctx.log('✓ 剪辑程序完成，类型检查通过')
  return { by: 'claude' }
}

/** 读剪辑代码（页面上展示） */
export function readEditCode(projectId) {
  const dir = remotionProjectDir(projectId)
  if (!fs.existsSync(dir)) return []
  return fs
    .readdirSync(dir)
    .filter((f) => /\.(tsx?|css)$/.test(f))
    .map((f) => ({ name: f, code: fs.readFileSync(path.join(dir, f), 'utf8') }))
}
