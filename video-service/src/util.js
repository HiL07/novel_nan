// 通用工具：原子写文件、路径越界检查、子进程（可取消、Windows 结束整棵进程树）、HTTP 下载
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawn, execFile } from 'node:child_process'

export class BizError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

export function now() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function newId(prefix) {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${prefix}${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${crypto.randomBytes(3).toString('hex')}`
}

export function writeFileAtomic(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const tmp = `${file}.${process.pid}.tmp`
  fs.writeFileSync(tmp, data)
  fs.renameSync(tmp, file)
}

export function writeJsonAtomic(file, obj) {
  writeFileAtomic(file, JSON.stringify(obj, null, 2))
}

export function readJson(file, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    return fallback
  }
}

/** root 下的相对路径 → 绝对路径；越界（../、绝对路径）抛 400 */
export function safeJoin(root, rel) {
  const abs = path.resolve(root, rel)
  const r = path.resolve(root)
  if (abs !== r && !abs.startsWith(r + path.sep)) throw new BizError(400, '非法路径')
  return abs
}

export function killTree(child) {
  if (!child || child.exitCode !== null) return
  if (process.platform === 'win32') {
    execFile('taskkill', ['/pid', String(child.pid), '/T', '/F'], () => {})
  } else {
    child.kill('SIGTERM')
  }
}

/**
 * 运行子进程，逐行回调 stdout / stderr；signal.aborted 时结束进程树。
 * 返回 {code, stdout, stderr}（stdout / stderr 只保留末尾 200 KB）
 */
export function runProcess(cmd, args, { cwd, env, input, onLine, signal, shell = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { cwd, env: env || process.env, shell, windowsHide: true })
    let stdout = ''
    let stderr = ''
    const keep = (s) => (s.length > 200_000 ? s.slice(-200_000) : s)
    const lineReader = (stream, kind) => {
      let buf = ''
      stream.setEncoding('utf8')
      stream.on('data', (chunk) => {
        if (kind === 'out') stdout = keep(stdout + chunk)
        else stderr = keep(stderr + chunk)
        buf += chunk
        const lines = buf.split(/\r?\n|\r/)
        buf = lines.pop()
        for (const l of lines) if (l.trim()) onLine?.(l, kind)
      })
      stream.on('end', () => {
        if (buf.trim()) onLine?.(buf, kind)
      })
    }
    lineReader(child.stdout, 'out')
    lineReader(child.stderr, 'err')
    const onAbort = () => killTree(child)
    signal?.addEventListener('abort', onAbort)
    child.on('error', (e) => {
      signal?.removeEventListener('abort', onAbort)
      reject(e)
    })
    child.on('close', (code) => {
      signal?.removeEventListener('abort', onAbort)
      resolve({ code, stdout, stderr })
    })
    if (input != null) child.stdin.end(input)
    else child.stdin.end()
  })
}

/** fetch 带超时与取消；非 2xx 抛出带简短说明的错误（不回显请求体，避免泄露 key） */
export async function fetchJson(url, { method = 'GET', headers = {}, body, timeoutMs = 120_000, signal } = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  const onAbort = () => ctrl.abort()
  signal?.addEventListener('abort', onAbort)
  try {
    const res = await fetch(url, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json', ...headers } : headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    })
    const text = await res.text()
    let data = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = null
    }
    if (!res.ok) {
      const msg = data?.error?.message || data?.message || data?.msg || (typeof data?.error === 'string' ? data.error : '') || text.slice(0, 200)
      throw new Error(`HTTP ${res.status}${msg ? `：${msg}` : ''}`)
    }
    return data
  } catch (e) {
    if (signal?.aborted) throw new Error('已取消')
    if (e.name === 'AbortError') throw new Error(`请求超时（${Math.round(timeoutMs / 1000)}s）`)
    throw e
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

/** 下载二进制到文件（先写 .part 再改名） */
export async function download(url, file, { headers = {}, timeoutMs = 300_000, signal } = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  const onAbort = () => ctrl.abort()
  signal?.addEventListener('abort', onAbort)
  try {
    const res = await fetch(url, { headers, signal: ctrl.signal })
    if (!res.ok) throw new Error(`下载失败 HTTP ${res.status}`)
    const buf = Buffer.from(await res.arrayBuffer())
    writeFileAtomic(file, buf)
    return buf.length
  } catch (e) {
    if (signal?.aborted) throw new Error('已取消')
    if (e.name === 'AbortError') throw new Error('下载超时')
    throw e
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

export function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new Error('已取消'))
    }, { once: true })
  })
}

/** 并发上限为 limit 地逐个处理 items；单项失败不影响其它项，返回 [{item, ok, value|error}] */
export async function mapLimit(items, limit, fn, signal) {
  const results = new Array(items.length)
  let next = 0
  const worker = async () => {
    while (next < items.length) {
      if (signal?.aborted) throw new Error('已取消')
      const i = next++
      try {
        results[i] = { item: items[i], ok: true, value: await fn(items[i], i) }
      } catch (e) {
        if (signal?.aborted) throw new Error('已取消')
        results[i] = { item: items[i], ok: false, error: e.message || String(e) }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, worker))
  return results
}

/** 图片文件 → data URI（发给图生视频接口） */
export function dataUri(file) {
  const ext = path.extname(file).slice(1).toLowerCase()
  const mime = ext === 'jpg' || ext === 'jpeg' ? 'image/jpeg' : ext === 'webp' ? 'image/webp' : 'image/png'
  return `data:${mime};base64,${fs.readFileSync(file).toString('base64')}`
}
