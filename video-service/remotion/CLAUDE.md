# Remotion 剪辑工程（nan_novel「生成视频」）

这个工程由 `video-service` 驱动：每个视频项目一个目录 `src/projects/<projectId>/`。你（Claude Code）在这里负责**剪辑与动画程序**。

## 目录
- `src/lib/` — 预置组件，**不要修改**：`Shot`（视频 / 图片推拉摇移 / 渐变占位）、`Subtitle`、`TitleCard`、`DefaultVideo`（完整的默认剪辑，可作为起点）、`types.ts`（时间轴类型 `Timeline`）。
- `src/projects/<id>/data.json` — 时间轴数据，由服务生成，**只读**：镜头的起止帧、画面、配音、字幕、片头帧数、背景音乐。
- `src/projects/<id>/index.tsx` — 你要写的文件：`export const Video: React.FC<{ data: Timeline }>`。
- `src/registry.ts` / `src/Root.tsx` — 由服务生成 / 维护，不要改。

## 规则
- 只修改 `src/projects/<当前项目 id>/` 下的文件（可以新增组件文件），不要碰其它项目和 `src/lib/`。
- 所有资源都用 `staticFile(path)` 引用，path 取自 `data.json`（相对项目数据目录），不要硬编码绝对路径或网络地址。
- 视频时长由 `data.durationInFrames` 决定；每个镜头必须在 `scene.from` 开始、持续 `scene.durationInFrames` 帧，保证配音与画面同步。配音用 `<Audio src={staticFile(scene.audio.src)} />` 放在该镜头的 `<Sequence>` 里。
- 动画只用 `useCurrentFrame()` / `interpolate()` / `spring()` 驱动，不要用 CSS transition / animation 或 setTimeout。
- 不要安装新依赖；可用：`remotion`、`@remotion/transitions`、`react`。
- 字体用系统字体（`FONT_FAMILY` from `../../lib`）。
- 完成后运行 `npx tsc --noEmit` 确认没有类型错误。
- 可参考 `.claude/skills/remotion-*`（Remotion 官方 skills）。
