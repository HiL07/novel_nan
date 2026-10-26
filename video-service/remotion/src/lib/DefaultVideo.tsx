import React from 'react'
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion'
import { Shot } from './Shot'
import { Subtitle } from './Subtitle'
import { TitleCard } from './TitleCard'
import type { Timeline, TimelineScene } from './types'

/** 镜头首尾淡入淡出的帧数 */
export const FADE = 8

const SceneView: React.FC<{ scene: TimelineScene }> = ({ scene }) => {
  const frame = useCurrentFrame()
  const d = scene.durationInFrames
  const f = Math.max(1, Math.min(FADE, Math.floor(d / 4)))
  const opacity = interpolate(frame, [0, f, d - f, d], [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill style={{ opacity }}>
      <Shot visual={scene.visual} motion={scene.cameraMotion} durationInFrames={d} fallbackText={scene.visualPrompt} />
      <Subtitle cues={scene.subtitles} speaker={scene.speaker} />
    </AbsoluteFill>
  )
}

/** 默认剪辑：片头标题卡 → 逐镜头（画面 + 配音 + 字幕，淡入淡出）→ 背景音乐。Claude Code 以此为起点改写 */
export const DefaultVideo: React.FC<{ data: Timeline }> = ({ data }) => (
  <AbsoluteFill style={{ backgroundColor: 'black' }}>
    {data.introFrames > 0 ? (
      <Sequence durationInFrames={data.introFrames}>
        <TitleCard title={data.title} subtitle={data.style} />
      </Sequence>
    ) : null}
    {data.scenes.map((s) => (
      <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames}>
        <SceneView scene={s} />
        {s.audio ? <Audio src={staticFile(s.audio.src)} /> : null}
      </Sequence>
    ))}
    {data.bgm ? <Audio src={staticFile(data.bgm.src)} volume={data.bgm.volume} loop /> : null}
  </AbsoluteFill>
)
