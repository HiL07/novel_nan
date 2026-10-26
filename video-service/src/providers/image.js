// 图片提供商：OpenAI 兼容 /images/generations（硅基流动 Kolors / Flux、OpenAI 等）。svg（Claude Code 画）在 stages/assets.js
import fs from 'node:fs'
import { fetchJson, writeFileAtomic } from '../util.js'

const SIZES = { '16:9': '1280x720', '9:16': '720x1280', '1:1': '1024x1024' }

/** 按文件头判断图片格式 */
export function imageExt(buf) {
  if (buf[0] === 0xff && buf[1] === 0xd8) return 'jpg'
  if (buf.slice(0, 4).toString('hex') === '89504e47') return 'png'
  if (buf.slice(0, 4).toString() === 'RIFF' && buf.slice(8, 12).toString() === 'WEBP') return 'webp'
  return 'png'
}

/**
 * 生成一张图，写到 `${fileBase}.<ext>`，返回实际文件路径
 * @param {{baseUrl, apiKey, model, size}} cfg
 */
export async function generateImage(cfg, { prompt, aspect, fileBase, signal }) {
  if (!cfg.apiKey) throw new Error('图片接口未配置 API Key（生成视频 → 提供商设置）')
  const size = cfg.size || SIZES[aspect] || SIZES['16:9']
  const data = await fetchJson(`${cfg.baseUrl.replace(/\/+$/, '')}/images/generations`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${cfg.apiKey}` },
    // size：OpenAI 写法；image_size / batch_size：硅基流动写法（多余字段各家会忽略）
    body: { model: cfg.model, prompt, n: 1, size, image_size: size, batch_size: 1 },
    timeoutMs: 180_000,
    signal,
  })
  const item = data?.data?.[0] || data?.images?.[0]
  let buf
  if (item?.b64_json) buf = Buffer.from(item.b64_json, 'base64')
  else if (item?.url) {
    const res = await fetch(item.url, { signal })
    if (!res.ok) throw new Error(`下载图片失败 HTTP ${res.status}`)
    buf = Buffer.from(await res.arrayBuffer())
  } else throw new Error('图片接口没有返回图片')
  const out = `${fileBase}.${imageExt(buf)}`
  for (const ext of ['png', 'jpg', 'webp', 'svg']) if (`${fileBase}.${ext}` !== out) fs.rmSync(`${fileBase}.${ext}`, { force: true })
  writeFileAtomic(out, buf)
  return out
}
