// Remotion 工程操作：生成 registry.ts、写项目时间轴 / 默认剪辑、类型检查、渲染
import fs from 'node:fs'
import path from 'node:path'
import { REMOTION_DIR } from './config.js'
import { runProcess, writeFileAtomic, writeJsonAtomic } from './util.js'

const PROJECTS_DIR = path.join(REMOTION_DIR, 'src', 'projects')
const REGISTRY = path.join(REMOTION_DIR, 'src', 'registry.ts')
const TSC = path.join(REMOTION_DIR, 'node_modules', 'typescript', 'bin', 'tsc')
const REMOTION_CLI = path.join(REMOTION_DIR, 'node_modules', '@remotion', 'cli', 'remotion-cli.js')

export const DEFAULT_INDEX = `import React from 'react'
import { DefaultVideo } from '../../lib'
import type { Timeline } from '../../lib'

// 默认剪辑（片头 + 逐镜头画面 / 配音 / 字幕 + 背景音乐）。「Claude Code 剪辑」会改写这个文件。
export const Video: React.FC<{ data: Timeline }> = ({ data }) => <DefaultVideo data={data} />
`

export function remotionProjectDir(id) {
  return path.join(PROJECTS_DIR, id)
}

export function remotionInstalled() {
  return fs.existsSync(REMOTION_CLI) && fs.existsSync(TSC)
}

/** 写 registry.ts：only = 只注册这些项目（渲染时只打包目标项目，别的项目有错也不影响） */
export function writeRegistry(only) {
  const ids = (only || (fs.existsSync(PROJECTS_DIR) ? fs.readdirSync(PROJECTS_DIR) : [])).filter(
    (id) => fs.existsSync(path.join(PROJECTS_DIR, id, 'index.tsx')) && fs.existsSync(path.join(PROJECTS_DIR, id, 'data.json')),
  )
  const name = (id) => `p_${id.replace(/[^A-Za-z0-9]/g, '_')}`
  const lines = [
    '// 由 video-service 自动生成，勿手改',
    "import type React from 'react'",
    "import type { Timeline } from './lib/types'",
    ...ids.flatMap((id) => [
      `import { Video as ${name(id)} } from './projects/${id}'`,
      `import ${name(id)}_data from './projects/${id}/data.json'`,
    ]),
    '',
    'export const projects: { id: string; component: React.FC<any>; data: Timeline }[] = [',
    ...ids.map((id) => `  { id: '${id}', component: ${name(id)}, data: ${name(id)}_data as unknown as Timeline },`),
    ']',
    '',
  ]
  writeFileAtomic(REGISTRY, lines.join('\n'))
}

/** 写时间轴；没有 index.tsx 时放默认剪辑 */
export function writeProjectData(id, timeline) {
  const dir = remotionProjectDir(id)
  writeJsonAtomic(path.join(dir, 'data.json'), timeline)
  const index = path.join(dir, 'index.tsx')
  if (!fs.existsSync(index)) writeFileAtomic(index, DEFAULT_INDEX)
}

export function resetToDefault(id) {
  writeFileAtomic(path.join(remotionProjectDir(id), 'index.tsx'), DEFAULT_INDEX)
}

export function removeProject(id) {
  fs.rmSync(remotionProjectDir(id), { recursive: true, force: true })
  writeRegistry()
}

/** 类型检查，只返回与该项目有关的错误行 */
export async function typecheck(id, signal) {
  const r = await runProcess(process.execPath, [TSC, '--noEmit', '-p', '.'], { cwd: REMOTION_DIR, signal })
  if (r.code === 0) return []
  const mine = `src/projects/${id}/`
  return (r.stdout + r.stderr)
    .split(/\r?\n/)
    .filter((l) => l.replace(/\\/g, '/').includes(mine) || /^src\/(lib|Root|registry|index)/.test(l.replace(/\\/g, '/')))
    .slice(0, 40)
}

/** 渲染成片：public 目录 = 项目数据目录（staticFile 相对它） */
export async function render(id, { publicDir, outFile, ctx }) {
  writeRegistry([id])
  const tmp = outFile.replace(/\.mp4$/, '.part.mp4')
  fs.rmSync(tmp, { force: true })
  const args = [REMOTION_CLI, 'render', 'src/index.ts', id, tmp, '--public-dir', publicDir, '--overwrite', '--log', 'info']
  let lastPct = -1
  // 渲染中间文件放在数据目录下（系统临时目录可能不可写 / 空间不足），结束后清掉
  const tmpDir = path.join(path.dirname(publicDir), '.render-tmp', id)
  fs.mkdirSync(tmpDir, { recursive: true })
  try {
    const r = await runProcess(process.execPath, args, {
      cwd: REMOTION_DIR,
      env: { ...process.env, TEMP: tmpDir, TMP: tmpDir, TMPDIR: tmpDir },
      signal: ctx.signal,
      onLine: (line) => {
        // eslint-disable-next-line no-control-regex
        const clean = line.replace(/\u001b\[[0-9;]*m/g, '')
        const m = clean.match(/(Render|Encod|Stitch)\w*[^\d]*(\d+)\/(\d+)/i)
        if (m) {
          const pct = Math.floor((Number(m[2]) / Math.max(1, Number(m[3]))) * 100)
          const phase = /encod|stitch/i.test(m[1]) ? '编码' : '渲染帧'
          ctx.progress(/encod|stitch/i.test(m[1]) ? 85 + pct * 0.14 : 5 + pct * 0.8, `${phase} ${m[2]}/${m[3]}`)
          if (pct >= lastPct + 10 || pct === 100) {
            lastPct = pct
            ctx.log(`  ${clean.trim()}`)
          }
        } else if (clean.trim()) ctx.log(`  ${clean.trim().slice(0, 300)}`)
      },
    })
    if (ctx.signal.aborted) throw new Error('已取消')
    if (r.code !== 0 || !fs.existsSync(tmp)) {
      const tail = (r.stderr || r.stdout).replace(/\u001b\[[0-9;]*m/g, '').trim().split(/\r?\n/).slice(-8).join('\n')
      throw new Error(`渲染失败：${tail.slice(0, 800)}`)
    }
    fs.renameSync(tmp, outFile)
  } finally {
    writeRegistry()
    fs.rmSync(tmpDir, { recursive: true, force: true })
  }
}
