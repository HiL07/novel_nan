import React from 'react'
import { Composition } from 'remotion'
import { projects } from './registry'
import type { Timeline } from './lib/types'

// registry.ts 由 video-service 生成（列出 src/projects/<id>/），渲染时只含目标项目
export const RemotionRoot: React.FC = () => (
  <>
    {projects.map((p) => (
      <Composition
        key={p.id}
        id={p.id}
        component={p.component as React.FC<{ data: Timeline }>}
        durationInFrames={Math.max(1, p.data.durationInFrames)}
        fps={p.data.fps}
        width={p.data.width}
        height={p.data.height}
        defaultProps={{ data: p.data }}
      />
    ))}
  </>
)
