import React from 'react'
import { AbsoluteFill, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig } from 'remotion'
import type { CameraMotion, SceneVisual } from './types'

/** 推拉摇移：根据镜头运动在本镜头时长内插值缩放 / 平移 */
export function cameraTransform(motion: CameraMotion, frame: number, duration: number): string {
  const t = interpolate(frame, [0, Math.max(1, duration)], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  switch (motion) {
    case 'push-in':
      return `scale(${1 + 0.15 * t})`
    case 'pull-out':
      return `scale(${1.15 - 0.15 * t})`
    case 'pan-left':
      return `scale(1.15) translateX(${4 - 8 * t}%)`
    case 'pan-right':
      return `scale(1.15) translateX(${-4 + 8 * t}%)`
    default:
      return `scale(${1.02 + 0.03 * t})`
  }
}

/** 一个镜头的画面：视频静音播放（配音另放），图片做推拉摇移，没有画面就用渐变背景 */
export const Shot: React.FC<{
  visual: SceneVisual
  motion: CameraMotion
  durationInFrames: number
  fallbackText?: string
}> = ({ visual, motion, durationInFrames, fallbackText }) => {
  const frame = useCurrentFrame()
  const { width } = useVideoConfig()
  if (visual.type === 'video' && visual.src) {
    const clip = visual.clipDurationInFrames
    const playbackRate = clip ? Math.max(0.5, Math.min(1, clip / Math.max(1, durationInFrames))) : 1
    return (
      <AbsoluteFill style={{ backgroundColor: 'black' }}>
        <OffthreadVideo
          src={staticFile(visual.src)}
          muted
          playbackRate={playbackRate}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </AbsoluteFill>
    )
  }
  if (visual.type === 'image' && visual.src) {
    return (
      <AbsoluteFill style={{ backgroundColor: 'black', overflow: 'hidden' }}>
        <Img
          src={staticFile(visual.src)}
          style={{ width: '100%', height: '100%', objectFit: 'cover', transform: cameraTransform(motion, frame, durationInFrames) }}
        />
      </AbsoluteFill>
    )
  }
  const hue = interpolate(frame, [0, Math.max(1, durationInFrames)], [220, 260])
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 30% 30%, hsl(${hue},45%,28%), hsl(${hue + 30},50%,8%))`,
        justifyContent: 'center',
        alignItems: 'center',
        padding: width * 0.08,
      }}
    >
      {fallbackText ? (
        <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: width * 0.03, textAlign: 'center', lineHeight: 1.6 }}>{fallbackText}</div>
      ) : null}
    </AbsoluteFill>
  )
}
