/**
 * 大模型 token 单价（每百万 token）与费用估算。
 *
 * 内置的是各家公开的参考价（整理于 2025 年底，按模型名匹配，先匹配先用），厂商随时可能调价、促销或按上下文长度分档，
 * 以账单为准。用户可在页面上按模型名改单价（存在本机 localStorage），改过的优先于内置价。
 * cacheHit = 命中上下文缓存的输入单价（DeepSeek / OpenAI 等有；没有时按普通输入价算）。
 */
const BUILTIN = [
  { match: /^deepseek-(chat|reasoner|v3)/i, name: 'DeepSeek V3.x', currency: 'CNY', input: 2, cacheHit: 0.2, output: 3 },
  { match: /^qwen3?-max/i, name: '通义千问 Max', currency: 'CNY', input: 2.4, output: 9.6 },
  { match: /^qwen3?-plus/i, name: '通义千问 Plus', currency: 'CNY', input: 0.8, output: 2 },
  { match: /^qwen-turbo/i, name: '通义千问 Turbo', currency: 'CNY', input: 0.3, output: 0.6 },
  { match: /^qwen-flash/i, name: '通义千问 Flash', currency: 'CNY', input: 0.15, output: 1.5 },
  { match: /^qwen-long/i, name: '通义千问 Long', currency: 'CNY', input: 0.5, output: 2 },
  { match: /^moonshot-v1-8k/i, name: 'Kimi 8K', currency: 'CNY', input: 2, output: 10 },
  { match: /^moonshot-v1-32k/i, name: 'Kimi 32K', currency: 'CNY', input: 5, output: 20 },
  { match: /^moonshot-v1-128k/i, name: 'Kimi 128K', currency: 'CNY', input: 10, output: 30 },
  { match: /^kimi-k2/i, name: 'Kimi K2', currency: 'CNY', input: 4, cacheHit: 1, output: 16 },
  { match: /^glm-4-flash/i, name: '智谱 GLM-4-Flash（免费）', currency: 'CNY', input: 0, output: 0 },
  { match: /^gpt-4o-mini/i, name: 'GPT-4o mini', currency: 'USD', input: 0.15, cacheHit: 0.075, output: 0.6 },
  { match: /^gpt-4o/i, name: 'GPT-4o', currency: 'USD', input: 2.5, cacheHit: 1.25, output: 10 },
  { match: /^gpt-4\.1-nano/i, name: 'GPT-4.1 nano', currency: 'USD', input: 0.1, cacheHit: 0.025, output: 0.4 },
  { match: /^gpt-4\.1-mini/i, name: 'GPT-4.1 mini', currency: 'USD', input: 0.4, cacheHit: 0.1, output: 1.6 },
  { match: /^gpt-4\.1/i, name: 'GPT-4.1', currency: 'USD', input: 2, cacheHit: 0.5, output: 8 }
]

const STORE_KEY = 'nan_novel.modelPrices'
export const CURRENCY_SIGN = { CNY: '¥', USD: '$' }

function loadCustom() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {}
  } catch (e) {
    return {}
  }
}

/** 模型的单价：{name, currency, input, cacheHit?, output, custom} ；未知模型返回 null */
export function priceOf(model) {
  const key = (model || '').trim()
  const custom = loadCustom()[key.toLowerCase()]
  if (custom) return { name: key, ...custom, custom: true }
  const hit = BUILTIN.find((p) => p.match.test(key))
  return hit ? { name: hit.name, currency: hit.currency, input: hit.input, cacheHit: hit.cacheHit, output: hit.output, custom: false } : null
}

/** 保存自定义单价（price 为 null 时恢复内置价） */
export function setCustomPrice(model, price) {
  const all = loadCustom()
  const key = (model || '').trim().toLowerCase()
  if (price) all[key] = { currency: price.currency, input: +price.input, cacheHit: price.cacheHit === '' || price.cacheHit == null ? undefined : +price.cacheHit, output: +price.output }
  else delete all[key]
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(all))
  } catch (e) {
    // 隐私模式等写不进去：本次会话内不生效即可
  }
}

/** usage {promptTokens, completionTokens, cacheHitTokens} × 单价 → 费用（单位同 price.currency） */
export function costOf(usage, price) {
  if (!usage || !price) return null
  const hit = Math.min(usage.cacheHitTokens || 0, usage.promptTokens || 0)
  const miss = (usage.promptTokens || 0) - hit
  return (miss * price.input + hit * (price.cacheHit ?? price.input) + (usage.completionTokens || 0) * price.output) / 1e6
}

export function formatCost(cost, currency) {
  if (cost == null) return '-'
  const sign = CURRENCY_SIGN[currency] || ''
  if (cost === 0) return `${sign}0`
  return cost < 0.01 ? `${sign}${cost.toFixed(4)}` : `${sign}${cost.toFixed(cost < 1 ? 3 : 2)}`
}
