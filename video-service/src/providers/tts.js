// 配音提供商：sapi（Windows 自带，离线）/ openai（OpenAI 兼容 /audio/speech）/ edge（微软 Edge 在线语音）
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { runProcess, writeFileAtomic } from '../util.js'

const SAPI_SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), 'sapi.ps1')

/** WAV 时长（秒）：读 fmt 的 byteRate 和 data 块大小 */
export function wavDuration(buf) {
  if (buf.slice(0, 4).toString() !== 'RIFF') return null
  let off = 12
  let byteRate = 0
  while (off + 8 <= buf.length) {
    const id = buf.slice(off, off + 4).toString()
    const size = buf.readUInt32LE(off + 4)
    if (id === 'fmt ') byteRate = buf.readUInt32LE(off + 16)
    if (id === 'data') {
      const dataSize = Math.min(size, buf.length - off - 8)
      return byteRate ? dataSize / byteRate : null
    }
    off += 8 + size + (size % 2)
  }
  return null
}

async function sapi(cfg, { text, outBase, signal }) {
  if (process.platform !== 'win32') throw new Error('Windows 自带语音只能在 Windows 上使用')
  const out = `${outBase}.wav`
  const txt = `${outBase}.txt`
  fs.mkdirSync(path.dirname(out), { recursive: true })
  fs.writeFileSync(txt, text, 'utf8')
  try {
    const r = await runProcess(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', SAPI_SCRIPT, '-TextFile', txt, '-OutFile', out, '-Voice', cfg.voice || '', '-Rate', String(cfg.rate || 0)],
      { signal },
    )
    if (r.code !== 0) throw new Error(`Windows 语音合成失败：${(r.stderr || r.stdout).trim().slice(0, 300)}`)
  } finally {
    fs.rmSync(txt, { force: true })
  }
  return { file: out, duration: wavDuration(fs.readFileSync(out)) }
}

async function openai(cfg, { text, voice, outBase, signal }) {
  if (!cfg.apiKey) throw new Error('语音接口未配置 API Key')
  const res = await fetch(`${cfg.baseUrl.replace(/\/+$/, '')}/audio/speech`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${cfg.apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: cfg.model, input: text, voice: voice || cfg.voice, response_format: 'wav' }),
    signal,
  })
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(`语音接口 HTTP ${res.status}：${t.slice(0, 200)}`)
  }
  const buf = Buffer.from(await res.arrayBuffer())
  const out = `${outBase}.wav`
  writeFileAtomic(out, buf)
  return { file: out, duration: wavDuration(buf) }
}

async function edge(cfg, { text, voice, outBase, signal }) {
  const { MsEdgeTTS, OUTPUT_FORMAT } = await import('msedge-tts')
  const tts = new MsEdgeTTS()
  try {
    await tts.setMetadata(voice || cfg.voice, OUTPUT_FORMAT.AUDIO_24KHZ_48KBITRATE_MONO_MP3)
    const { audioStream } = tts.toStream(text)
    const chunks = []
    await new Promise((resolve, reject) => {
      audioStream.on('data', (d) => chunks.push(d))
      audioStream.on('end', resolve)
      audioStream.on('error', reject)
      signal?.addEventListener('abort', () => reject(new Error('已取消')), { once: true })
    })
    const buf = Buffer.concat(chunks)
    if (!buf.length) throw new Error('Edge 语音没有返回音频')
    const out = `${outBase}.mp3`
    writeFileAtomic(out, buf)
    // 48 kbps 恒定码率
    return { file: out, duration: (buf.length * 8) / 48000 }
  } catch (e) {
    if (/403/.test(e.message)) throw new Error('Edge 在线语音被拒绝（403），当前网络无法使用，请换用 Windows 自带语音或语音接口')
    throw e
  } finally {
    tts.close()
  }
}

export const TTS_PROVIDERS = { sapi, openai, edge }

/** 合成一句配音，写到 outBase.<ext>，返回 {file, duration(秒)} */
export async function synthesize(provider, cfg, opts) {
  const fn = TTS_PROVIDERS[provider]
  if (!fn) throw new Error(`未知配音提供商：${provider}`)
  for (const ext of ['wav', 'mp3']) fs.rmSync(`${opts.outBase}.${ext}`, { force: true })
  const r = await fn(cfg, opts)
  if (!r.duration || r.duration <= 0) throw new Error('读取配音时长失败')
  return r
}
