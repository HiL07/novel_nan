// 视频提供商（图生视频 / 文生视频，异步任务轮询）：火山方舟 Seedance、阿里云百炼通义万相
import { dataUri, download, fetchJson, sleep } from '../util.js'

const POLL_MS = 5000
const MAX_WAIT_MS = 20 * 60 * 1000

const trim = (u) => u.replace(/\/+$/, '')

async function poll(fn, { signal, onWait }) {
  const start = Date.now()
  for (;;) {
    const r = await fn()
    if (r.done) return r
    if (Date.now() - start > MAX_WAIT_MS) throw new Error('视频生成超时（20 分钟）')
    onWait?.(r.status, Math.round((Date.now() - start) / 1000))
    await sleep(POLL_MS, signal)
  }
}

/** 火山方舟 Seedance：POST /contents/generations/tasks → GET /contents/generations/tasks/{id} */
async function seedance(cfg, { prompt, image, aspect, durationSec, signal, onWait }) {
  if (!cfg.apiKey) throw new Error('Seedance 未配置 API Key')
  const headers = { Authorization: `Bearer ${cfg.apiKey}` }
  const flags = [`--resolution ${cfg.resolution || '720p'}`, `--duration ${durationSec}`]
  if (!image) flags.push(`--ratio ${aspect}`)
  const content = [{ type: 'text', text: `${prompt} ${flags.join(' ')}` }]
  if (image) content.push({ type: 'image_url', image_url: { url: dataUri(image) } })
  const task = await fetchJson(`${trim(cfg.baseUrl)}/contents/generations/tasks`, {
    method: 'POST',
    headers,
    body: { model: cfg.model, content },
    signal,
  })
  if (!task?.id) throw new Error('Seedance 没有返回任务 id')
  const r = await poll(
    async () => {
      const t = await fetchJson(`${trim(cfg.baseUrl)}/contents/generations/tasks/${task.id}`, { headers, signal })
      if (t.status === 'succeeded') return { done: true, url: t.content?.video_url }
      if (t.status === 'failed' || t.status === 'cancelled') throw new Error(`Seedance 生成失败：${t.error?.message || t.status}`)
      return { done: false, status: t.status }
    },
    { signal, onWait },
  )
  return r.url
}

const WAN_SIZES = {
  '480P': { '16:9': '832*480', '9:16': '480*832', '1:1': '624*624' },
  '720P': { '16:9': '1280*720', '9:16': '720*1280', '1:1': '960*960' },
  '1080P': { '16:9': '1920*1080', '9:16': '1080*1920', '1:1': '1440*1440' },
}

/** 通义万相：POST /services/aigc/video-generation/video-synthesis（异步）→ GET /tasks/{id} */
async function wan(cfg, { prompt, image, aspect, durationSec, signal, onWait }) {
  if (!cfg.apiKey) throw new Error('通义万相未配置 API Key')
  const headers = { Authorization: `Bearer ${cfg.apiKey}` }
  const resolution = cfg.resolution || '480P'
  const body = image
    ? { model: cfg.i2vModel, input: { prompt, img_url: dataUri(image) }, parameters: { resolution, duration: durationSec, prompt_extend: true } }
    : {
        model: cfg.t2vModel,
        input: { prompt },
        parameters: { size: WAN_SIZES[resolution]?.[aspect] || '832*480', duration: durationSec, prompt_extend: true },
      }
  const task = await fetchJson(`${trim(cfg.baseUrl)}/services/aigc/video-generation/video-synthesis`, {
    method: 'POST',
    headers: { ...headers, 'X-DashScope-Async': 'enable' },
    body,
    signal,
  })
  const taskId = task?.output?.task_id
  if (!taskId) throw new Error('通义万相没有返回任务 id')
  const r = await poll(
    async () => {
      const t = await fetchJson(`${trim(cfg.baseUrl)}/tasks/${taskId}`, { headers, signal })
      const s = t?.output?.task_status
      if (s === 'SUCCEEDED') return { done: true, url: t.output.video_url }
      if (s === 'FAILED' || s === 'CANCELED' || s === 'UNKNOWN') throw new Error(`通义万相生成失败：${t.output?.message || s}`)
      return { done: false, status: s }
    },
    { signal, onWait },
  )
  return r.url
}

export const VIDEO_PROVIDERS = { seedance, wan }

/** 生成一个镜头并下载到 outFile；image 为首帧图路径（png/jpg/webp）或 null（文生视频） */
export async function generateShot(provider, cfg, opts) {
  const fn = VIDEO_PROVIDERS[provider]
  if (!fn) throw new Error(`未知视频提供商：${provider}`)
  const url = await fn(cfg, opts)
  if (!url) throw new Error('视频接口没有返回视频地址')
  await download(url, opts.outFile, { signal: opts.signal })
}
