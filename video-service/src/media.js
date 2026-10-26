// 媒体文件小工具：MP4 时长（读 mvhd）
import fs from 'node:fs'

/** MP4 / MOV 时长（秒），读 moov/mvhd；读不到返回 null */
export function mp4Duration(file) {
  let buf
  try {
    buf = fs.readFileSync(file)
  } catch {
    return null
  }
  const find = (start, end, type) => {
    let off = start
    while (off + 8 <= end) {
      let size = buf.readUInt32BE(off)
      const t = buf.toString('latin1', off + 4, off + 8)
      let header = 8
      if (size === 1) {
        size = Number(buf.readBigUInt64BE(off + 8))
        header = 16
      } else if (size === 0) size = end - off
      if (size < header) return null
      if (t === type) return { off, size, header }
      off += size
    }
    return null
  }
  const moov = find(0, buf.length, 'moov')
  if (!moov) return null
  const mvhd = find(moov.off + moov.header, moov.off + moov.size, 'mvhd')
  if (!mvhd) return null
  const p = mvhd.off + mvhd.header
  const version = buf[p]
  if (version === 1) {
    const timescale = buf.readUInt32BE(p + 20)
    const duration = Number(buf.readBigUInt64BE(p + 24))
    return timescale ? duration / timescale : null
  }
  const timescale = buf.readUInt32BE(p + 12)
  const duration = buf.readUInt32BE(p + 16)
  return timescale ? duration / timescale : null
}
