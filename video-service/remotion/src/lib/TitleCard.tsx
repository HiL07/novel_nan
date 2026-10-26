import React from 'react'
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { FONT_FAMILY } from './Subtitle'

/** 片头标题卡：标题弹入，结尾淡出 */
export const TitleCard: React.FC<{ title: string; subtitle?: string }> = ({ title, subtitle }) => {
  const frame = useCurrentFrame()
  const { fps, width, durationInFrames } = useVideoConfig()
  const s = spring({ frame, fps, config: { damping: 200 } })
  const out = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill style={{ backgroundColor: '#07070c', justifyContent: 'center', alignItems: 'center', opacity: out, fontFamily: FONT_FAMILY }}>
      <div
        style={{
          color: 'white',
          fontSize: width * 0.06,
          letterSpacing: width * 0.006,
          fontWeight: 700,
          transform: `translateY(${(1 - s) * 30}px)`,
          opacity: s,
          textAlign: 'center',
          padding: '0 6%',
        }}
      >
        {title}
      </div>
      {subtitle ? (
        <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: width * 0.022, marginTop: width * 0.02, opacity: s, textAlign: 'center', padding: '0 8%' }}>
          {subtitle}
        </div>
      ) : null}
    </AbsoluteFill>
  )
}
