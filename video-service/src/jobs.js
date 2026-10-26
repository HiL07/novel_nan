// 内存后台任务：每个项目同时只能跑一个；Claude Code 与渲染各自一条通道（同一时间各 1 个），其它网络任务并行
import { BizError, newId, now } from './util.js'

const jobs = new Map()
const lanes = { claude: { busy: false, queue: [] }, render: { busy: false, queue: [] } }
const MAX_LOG = 2000

function acquire(lane, job) {
  if (!lanes[lane]) return Promise.resolve()
  const l = lanes[lane]
  if (!l.busy) {
    l.busy = true
    return Promise.resolve()
  }
  job.message = lane === 'claude' ? '等待其它 Claude Code 任务结束…' : '等待其它渲染任务结束…'
  return new Promise((resolve, reject) => {
    l.queue.push({ resolve, reject, job })
  })
}

function release(lane) {
  const l = lanes[lane]
  if (!l) return
  while (l.queue.length) {
    const next = l.queue.shift()
    if (next.job.controller.signal.aborted) {
      next.reject(new Error('已取消'))
      continue
    }
    next.resolve()
    return
  }
  l.busy = false
}

export function activeJob(projectId) {
  for (const j of jobs.values()) if (j.projectId === projectId && (j.status === 'queued' || j.status === 'running')) return j
  return null
}

/**
 * 启动任务。run(ctx) 里用 ctx.log(text) 写日志、ctx.progress(0–100, message)、ctx.signal 判断取消；
 * 返回值存到 job.result。
 */
export function startJob({ projectId, stage, lane, run }) {
  if (activeJob(projectId)) throw new BizError(400, '该项目已有任务在运行，请等待或先取消')
  const job = {
    id: newId('j'),
    projectId,
    stage,
    lane: lane || 'net',
    status: 'queued',
    progress: 0,
    message: '排队中',
    log: [],
    logBase: 0,
    error: null,
    result: null,
    cost: null,
    createdAt: now(),
    finishedAt: null,
    controller: new AbortController(),
  }
  jobs.set(job.id, job)
  const ctx = {
    signal: job.controller.signal,
    log(text) {
      for (const line of String(text).split(/\r?\n/)) {
        job.log.push(line)
        if (job.log.length > MAX_LOG) {
          job.log.shift()
          job.logBase++
        }
      }
    },
    progress(pct, message) {
      if (pct != null) job.progress = Math.max(0, Math.min(100, Math.round(pct)))
      if (message) job.message = message
    },
    addCost(usd) {
      if (typeof usd === 'number') job.cost = Math.round(((job.cost || 0) + usd) * 10000) / 10000
    },
  }
  ;(async () => {
    try {
      await acquire(job.lane, job)
    } catch (e) {
      job.status = 'cancelled'
      job.error = e.message
      job.message = '已取消'
      job.finishedAt = now()
      return
    }
    try {
      if (job.controller.signal.aborted) throw new Error('已取消')
      job.status = 'running'
      job.message = '运行中'
      job.result = await run(ctx)
      job.status = 'succeeded'
      job.progress = 100
      if (job.message === '运行中') job.message = '完成'
    } catch (e) {
      const cancelled = job.controller.signal.aborted
      job.status = cancelled ? 'cancelled' : 'failed'
      job.error = cancelled ? '已取消' : e.message || String(e)
      job.message = job.error
      ctx.log(`✗ ${job.error}`)
      if (!cancelled && process.env.VIDEO_DEBUG) console.error(e)
    } finally {
      job.finishedAt = now()
      release(job.lane)
    }
  })()
  return view(job)
}

export function view(job, since = 0) {
  const from = Math.max(0, since - job.logBase)
  return {
    id: job.id,
    projectId: job.projectId,
    stage: job.stage,
    status: job.status,
    progress: job.progress,
    message: job.message,
    error: job.error,
    cost: job.cost,
    createdAt: job.createdAt,
    finishedAt: job.finishedAt,
    logTotal: job.logBase + job.log.length,
    log: job.log.slice(from),
  }
}

export function getJob(id) {
  const j = jobs.get(id)
  if (!j) throw new BizError(404, '任务不存在（服务重启后任务记录会清空）')
  return j
}

export function cancelJob(id) {
  const j = getJob(id)
  if (j.status === 'queued' || j.status === 'running') {
    j.controller.abort()
    j.message = '正在取消…'
  }
  return view(j)
}

/** 保留最近 200 个已结束的任务 */
setInterval(() => {
  const done = [...jobs.values()].filter((j) => j.finishedAt)
  for (const j of done.slice(0, Math.max(0, done.length - 200))) jobs.delete(j.id)
}, 60_000).unref()
