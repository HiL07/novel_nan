// 时间轴数据：video-service 写到 src/projects/<id>/data.json。
// 资源路径相对项目数据目录（渲染时的 public 目录），用 staticFile() 取。

export type CameraMotion = 'push-in' | 'pull-out' | 'pan-left' | 'pan-right' | 'static'

export interface SubtitleCue {
  text: string
  /** 相对本镜头开始的帧 */
  from: number
  to: number
}

export interface SceneVisual {
  /** video = 视频模型生成的镜头；image = 首帧图（推拉摇移）；none = 没有画面（渐变背景） */
  type: 'video' | 'image' | 'none'
  src?: string
  /** 视频片段本身的帧数（比镜头短时放慢播放，最多慢到 0.5 倍） */
  clipDurationInFrames?: number
}

export interface TimelineScene {
  id: string
  /** 在成片中的起始帧 */
  from: number
  durationInFrames: number
  narration: string
  speaker: string
  mood: string
  cameraMotion: CameraMotion
  visualPrompt: string
  visual: SceneVisual
  audio: { src: string; durationInFrames: number } | null
  subtitles: SubtitleCue[]
}

export interface TimelineCharacter {
  name: string
  look: string
  image?: string
}

export interface Timeline {
  fps: number
  width: number
  height: number
  durationInFrames: number
  title: string
  style: string
  /** 片头标题卡帧数（0 = 无） */
  introFrames: number
  bgm: { src: string; volume: number } | null
  characters: TimelineCharacter[]
  scenes: TimelineScene[]
}
