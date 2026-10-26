// 调用本机 Claude Code（claude -p，非交互）：prompt 从 stdin 传入，stream-json 输出解析成实时日志
import { getConfig } from './config.js'
import { runProcess } from './util.js'

function childEnv() {
  const env = { ...process.env }
  // 服务若是从一个 Claude Code 会话里启动的，去掉会话标记，避免子进程被当成嵌套会话
  for (const k of Object.keys(env)) if (k === 'CLAUDECODE' || k.startsWith('CLAUDE_CODE_')) delete env[k]
  return env
}

function short(s, n = 160) {
  s = String(s ?? '').replace(/\s+/g, ' ').trim()
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function describeTool(name, input = {}) {
  const target = input.file_path || input.path || input.pattern || input.command || ''
  return `🔧 ${name}${target ? ` ${short(target, 120)}` : ''}`
}

/**
 * 运行一次 Claude Code。
 * @param {object} o
 * @param {string} o.prompt
 * @param {string} o.cwd           工作目录（acceptEdits 只自动放行这里的编辑）
 * @param {string} o.model         opus / sonnet / 完整模型 id
 * @param {string[]} o.tools       允许的工具（如 ['Read', 'Write', 'Bash(npx tsc:*)']）
 * @param {string[]} [o.addDirs]   额外可访问目录
 * @param {object} o.ctx           任务上下文（log / signal / addCost）
 * @returns {Promise<{text: string, costUsd: number|null, turns: number|null}>}
 */
export async function runClaude({ prompt, cwd, model, tools, addDirs = [], ctx }) {
  const cfg = getConfig().claude
  const args = ['-p', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits', '--no-session-persistence']
  if (model) args.push('--model', model)
  if (cfg.maxBudgetUsd > 0) args.push('--max-budget-usd', String(cfg.maxBudgetUsd))
  for (const d of addDirs) args.push('--add-dir', d)
  args.push('--allowedTools', tools.join(','))

  ctx.log(`▶ Claude Code（${model || '默认模型'}）开始工作…`)
  let result = null
  const onLine = (line, kind) => {
    if (kind === 'err') {
      ctx.log(`[stderr] ${short(line, 300)}`)
      return
    }
    let ev
    try {
      ev = JSON.parse(line)
    } catch {
      ctx.log(short(line, 300))
      return
    }
    if (ev.type === 'system' && ev.subtype === 'init') {
      ctx.log(`  会话已启动（模型 ${ev.model || model}）`)
    } else if (ev.type === 'assistant') {
      for (const c of ev.message?.content || []) {
        if (c.type === 'text' && c.text?.trim()) ctx.log(`💬 ${short(c.text, 400)}`)
        else if (c.type === 'tool_use') ctx.log(describeTool(c.name, c.input))
      }
    } else if (ev.type === 'user') {
      for (const c of ev.message?.content || []) {
        if (c.type === 'tool_result' && c.is_error) {
          const text = Array.isArray(c.content) ? c.content.map((x) => x.text || '').join(' ') : c.content
          ctx.log(`  ⚠ ${short(text, 300)}`)
        }
      }
    } else if (ev.type === 'result') {
      result = ev
    }
  }
  let out
  try {
    out = await runProcess(cfg.bin || 'claude', args, { cwd, env: childEnv(), input: prompt, onLine, signal: ctx.signal })
  } catch (e) {
    if (e.code === 'ENOENT') throw new Error(`找不到 Claude Code 命令「${cfg.bin}」，请先安装 Claude Code 并登录，或在设置里填写 claude 可执行文件路径`)
    throw e
  }
  if (ctx.signal.aborted) throw new Error('已取消')
  if (!result) {
    const tail = short(out.stderr || out.stdout, 400)
    throw new Error(`Claude Code 异常退出（code ${out.code}）${tail ? `：${tail}` : ''}`)
  }
  const cost = typeof result.total_cost_usd === 'number' ? result.total_cost_usd : null
  ctx.addCost?.(cost)
  ctx.log(`■ Claude Code 结束：${result.num_turns ?? '?'} 轮${cost != null ? `，约 $${cost.toFixed(4)}` : ''}`)
  if (result.is_error) throw new Error(`Claude Code 返回错误：${short(result.result || result.subtype, 300)}`)
  return { text: result.result || '', costUsd: cost, turns: result.num_turns ?? null }
}

/** 健康检查：claude --version */
export async function claudeVersion() {
  try {
    const out = await runProcess(getConfig().claude.bin || 'claude', ['--version'], { env: childEnv() })
    return out.code === 0 ? out.stdout.trim() : null
  } catch {
    return null
  }
}
