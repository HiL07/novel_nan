import React from 'react'
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion'
import type { SubtitleCue } from './types'

export const FONT_FAMILY = '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif'

/** 底部字幕：按 cue 显示，每句淡入淡出；说话人不是旁白时在上方标出名字 */
export const Subtitle: React.FC<{ cues: SubtitleCue[]; speaker?: string }> = ({ cues, speaker }) => {
  const frame = useCurrentFrame()
  const { width, height } = useVideoConfig()
  const cue = cues.find((c) => frame >= c.from && frame < c.to)
  if (!cue) return null
  const fade = Math.max(1, Math.min(6, Math.floor((cue.to - cue.from) / 3)))
  const opacity = interpolate(frame, [cue.from, cue.from + fade, cue.to - fade, cue.to], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })
  const portrait = height > width
  const size = portrait ? width * 0.05 : height * 0.045
  return (
    <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: height * (portrait ? 0.16 : 0.07) }}>
      <div style={{ opacity, maxWidth: '86%', textAlign: 'center', fontFamily: FONT_FAMILY }}>
        {speaker && speaker !== '旁白' ? (
          <div style={{ color: '#ffd479', fontSize: size * 0.75, marginBottom: size * 0.2, textShadow: '0 2px 6px rgba(0,0,0,0.9)' }}>
            {speaker}
          </div>
        ) : null}
        <div
          style={{
            color: 'white',
            fontSize: size,
            lineHeight: 1.45,
            fontWeight: 600,
            textShadow: '0 2px 4px rgba(0,0,0,0.95), 0 0 12px rgba(0,0,0,0.6)',
          }}
        >
          {cue.text}
        </div>
      </div>
    </AbsoluteFill>
  )
}
