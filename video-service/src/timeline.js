// 由项目（分镜 + 资产 + 镜头 + 配音 + 背景音乐）生成 Remotion 时间轴 data.json（类型见 remotion/src/lib/types.ts）
export const FPS = 30
export const SIZES = { '16:9': [1920, 1080], '9:16': [1080, 1920], '1:1': [1080, 1080] }

/** 镜头时长 = 配音时长 + 0.6 秒留白；没有配音用分镜里的 durationSec */
const PAD_SEC = 0.6
const MIN_SEC = 2

/** 把一段旁白切成字幕句：按句末标点切，过长的再按逗号切 */
export function splitSubtitles(text, maxLen = 18) {
  const sentences = text
    .replace(/\s+/g, ' ')
    .split(/(?<=[。！？!?；;…])/)
    .map((s) => s.trim())
    .filter(Boolean)
  const out = []
  for (const s of sentences) {
    if (s.length <= maxLen) {
      out.push(s)
      continue
    }
    let buf = ''
    for (const part of s.split(/(?<=[，,、：:])/)) {
      if (buf && (buf + part).length > maxLen) {
        out.push(buf)
        buf = part
      } else buf += part
    }
    if (buf) out.push(buf)
  }
  return out.map((s) => s.replace(/[，,、；;：:]$/, ''))
}

/** 字幕时间按字数比例分配到 [startSec, startSec + spanSec] */
function cues(text, startSec, spanSec) {
  const parts = splitSubtitles(text)
  const total = parts.reduce((n, p) => n + p.length, 0) || 1
  let t = startSec
  return parts.map((p) => {
    const d = (spanSec * p.length) / total
    const cue = { text: p, from: Math.round(t * FPS), to: Math.round((t + d) * FPS) }
    t += d
    return cue
  })
}

export function buildTimeline(p) {
  const sb = p.storyboard
  if (!sb) throw new Error('还没有分镜')
  const [width, height] = SIZES[p.options.aspect] || SIZES['16:9']
  const introFrames = p.options.intro === false ? 0 : Math.round(2.5 * FPS)
  let cursor = introFrames
  const scenes = sb.scenes.map((s) => {
    const voice = p.voice?.[s.id]
    const voiceOk = voice?.file && voice.text === s.narration
    const sec = voiceOk ? Math.max(MIN_SEC, voice.duration + PAD_SEC) : Math.max(MIN_SEC, s.durationSec)
    const durationInFrames = Math.ceil(sec * FPS)
    const shot = p.shots?.[s.id]
    const asset = p.assets?.scenes?.[s.id]
    let visual = { type: 'none' }
    if (shot?.type === 'video' && shot.file) visual = { type: 'video', src: shot.file, clipDurationInFrames: shot.duration ? Math.round(shot.duration * FPS) : undefined }
    else if (asset?.file) visual = { type: 'image', src: asset.file }
    const scene = {
      id: s.id,
      from: cursor,
      durationInFrames,
      narration: s.narration,
      speaker: s.speaker || '旁白',
      mood: s.mood || '',
      cameraMotion: s.cameraMotion || 'push-in',
      visualPrompt: s.visualPrompt,
      visual,
      audio: voiceOk ? { src: voice.file, durationInFrames: Math.ceil(voice.duration * FPS) } : null,
      subtitles: p.options.subtitles === false ? [] : voiceOk ? cues(s.narration, 0.15, voice.duration) : cues(s.narration, 0.3, sec - 0.6),
    }
    cursor += durationInFrames
    return scene
  })
  return {
    fps: FPS,
    width,
    height,
    durationInFrames: cursor,
    title: sb.title,
    style: sb.logline || '',
    introFrames,
    bgm: p.bgm?.file ? { src: p.bgm.file, volume: p.bgm.volume ?? 0.2 } : null,
    characters: (sb.characters || []).map((c) => ({ name: c.name, look: c.look, image: p.assets?.characters?.[c.name]?.file })),
    scenes,
  }
}
