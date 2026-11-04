/**
 * 逐章串行读的时间 / token 估算（提取设置、提取工作区「接着读」共用）。
 * 按每千字原文。大模型 = 2c 实测（2026-11-03，deepseek-v4.1-flash 关思考，两本书各 10 章）：
 * 第 1 遍 快速 3.6 / 标准 4.8 / 深拆 6.5 秒，第 2 遍补漏另加 3.3 秒；token 见 READ_TOKENS（第 2 遍另加输入 1000 / 输出 410）。
 * GGUF / 本地 = 未实测的粗估（旧分块实测 GGUF Qwen3-4B Q4 约 16 秒 / 千字，加上章节卡多出的输出），第 2 遍按快速档算。
 */
export const READ_SECONDS = {
  api: { fast: 3.6, standard: 4.8, deep: 6.5, second: 3.3 },
  gguf: { fast: 16, standard: 30, deep: 35, second: 16 },
  local: { fast: 40, standard: 70, deep: 80, second: 40 }
}
export const READ_TOKENS = {
  input: { fast: 860, standard: 1250, deep: 1340, second: 1000 },
  output: { fast: 460, standard: 730, deep: 940, second: 410 }
}

export const fmtDuration = (sec) =>
  sec < 3600 ? `${Math.max(1, Math.round(sec / 60))} 分钟` : `${(sec / 3600).toFixed(1)} 小时`

/** chars 字、source api|gguf|local、depth、rounds → {seconds, input, output}（token 只对大模型有意义） */
export function estimateRead(chars, { source = 'api', depth = 'standard', rounds = 1 } = {}) {
  const k = chars / 1000
  const speed = READ_SECONDS[source] || READ_SECONDS.api
  const d = speed[depth] != null ? depth : 'standard'
  const two = rounds === 2
  return {
    seconds: k * (speed[d] + (two ? speed.second : 0)),
    input: k * (READ_TOKENS.input[d] + (two ? READ_TOKENS.input.second : 0)),
    output: k * (READ_TOKENS.output[d] + (two ? READ_TOKENS.output.second : 0))
  }
}
