// 路径、端口与提供商配置（config.local.json，git-ignore；API Key 只写不读）
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { writeJsonAtomic } from './util.js'

export const SERVICE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const REPO_DIR = path.resolve(SERVICE_DIR, '..')
export const REMOTION_DIR = path.join(SERVICE_DIR, 'remotion')
export const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(REPO_DIR, 'data'))
export const VIDEOS_DIR = path.join(DATA_DIR, 'videos')

export const PORT = Number(process.env.PORT || 8023)
/** Python AI 服务（读小说工作区；只用现有的只读接口） */
export const PY_URL = (process.env.PY_URL || 'http://localhost:8021').replace(/\/+$/, '')
export const CORS_ORIGINS = (process.env.CORS_ORIGINS || 'http://localhost:5173,http://localhost:5174').split(',').map((s) => s.trim())

const CONFIG_FILE = path.join(SERVICE_DIR, 'config.local.json')

export const DEFAULT_CONFIG = {
  // scriptModel = 编剧分镜；svgModel = 画 SVG 画面（量大，默认 sonnet 省钱）；editModel = 写剪辑程序
  claude: { bin: 'claude', scriptModel: 'opus', svgModel: 'sonnet', editModel: 'opus', maxBudgetUsd: 0 },
  image: {
    // none = 不生成图片（渐变占位）；svg = Claude Code 画矢量插画；openai = OpenAI 兼容 /images/generations
    provider: 'svg',
    openai: { baseUrl: 'https://api.siliconflow.cn/v1', apiKey: '', model: 'Kwai-Kolors/Kolors', size: '' },
  },
  video: {
    // kenburns = 不调用视频模型，首帧图做推拉摇移；seedance = 火山方舟；wan = 阿里云百炼（通义万相）
    provider: 'kenburns',
    durationSec: 5,
    seedance: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', apiKey: '', model: 'doubao-seedance-1-0-lite-i2v-250428', resolution: '720p' },
    wan: { baseUrl: 'https://dashscope.aliyuncs.com/api/v1', apiKey: '', i2vModel: 'wan2.2-i2v-flash', t2vModel: 'wan2.2-t2v-plus', resolution: '480P' },
  },
  tts: {
    // sapi = Windows 自带语音（离线、免费）；openai = OpenAI 兼容 /audio/speech（如硅基流动 CosyVoice2）；edge = 微软 Edge 在线语音
    provider: 'sapi',
    sapi: { voice: 'Microsoft Huihui Desktop', rate: 0 },
    openai: { baseUrl: 'https://api.siliconflow.cn/v1', apiKey: '', model: 'FunAudioLLM/CosyVoice2-0.5B', voice: 'FunAudioLLM/CosyVoice2-0.5B:alex' },
    edge: { voice: 'zh-CN-YunxiNeural' },
  },
}

function merge(base, over) {
  if (!over || typeof over !== 'object' || Array.isArray(over)) return base
  const out = { ...base }
  for (const [k, v] of Object.entries(over)) {
    if (!(k in base)) continue
    out[k] = base[k] && typeof base[k] === 'object' && !Array.isArray(base[k]) ? merge(base[k], v) : v
  }
  return out
}

let cache = null

export function getConfig() {
  if (!cache) {
    let stored = {}
    try {
      stored = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'))
    } catch {
      stored = {}
    }
    cache = merge(DEFAULT_CONFIG, stored)
  }
  return cache
}

function mask(key) {
  if (!key) return ''
  return key.length <= 8 ? '****' : `${key.slice(0, 3)}****${key.slice(-4)}`
}

/** 给前端看的配置：apiKey 清空，只带 apiKeyMasked */
export function publicConfig() {
  const walk = (o) => {
    if (!o || typeof o !== 'object') return o
    const out = {}
    for (const [k, v] of Object.entries(o)) {
      if (k === 'apiKey') {
        out.apiKey = ''
        out.apiKeyMasked = mask(v)
      } else out[k] = walk(v)
    }
    return out
  }
  return walk(getConfig())
}

/** 保存配置：未知字段丢弃，空 apiKey 保留原值 */
export function saveConfig(input) {
  const current = getConfig()
  const keepKeys = (next, prev) => {
    if (!next || typeof next !== 'object') return next
    for (const [k, v] of Object.entries(next)) {
      if (k === 'apiKey' && !v) next[k] = prev?.apiKey || ''
      else if (v && typeof v === 'object' && !Array.isArray(v)) keepKeys(v, prev?.[k])
    }
    return next
  }
  const next = keepKeys(merge(current, input), current)
  writeJsonAtomic(CONFIG_FILE, next)
  cache = next
  return publicConfig()
}
