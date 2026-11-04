/**
 * 提取工作区的公共小工具（列表页 / 工作区顶栏 / 文件管理的选择弹窗共用）：
 * 状态标签、自动副标题、改名、删除（带预览的二次确认）。同一本书可以有多个工作区。
 */
import { h } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { bookOf, deleteExtractPreview, deleteExtracts, renameExtract } from '@/api/novel'
import { errorMessage } from '@/api/request'

export const WS_STATUS = {
  DRAFT: { label: '未开始', type: 'info' },
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '提取中', type: 'warning' },
  INTERRUPTED: { label: '已暂停', type: 'warning' },
  SUCCEEDED: { label: '提取完成', type: 'success' },
  FAILED: { label: '失败 / 已取消', type: 'danger' }
}
const DEPTH = { fast: '快速', standard: '标准', deep: '深拆' }

export function optionsOf(t) {
  try {
    return JSON.parse(t?.options || 'null') || {}
  } catch {
    return {}
  }
}

/** 主标题：工作区名，没有就用书名 */
export function wsTitle(t) {
  return t?.title || `《${bookOf(t?.fileName)}》`
}

/** 自动副标题：「深拆 · 2 遍 · 第 1–10 章」；还没设置的草稿只写「未设置」 */
export function wsSubtitle(t) {
  const m = optionsOf(t).materials
  if (!m) return t?.status === 'DRAFT' ? '还没设置' : '章节分析（旧版）'
  const n = t.chapterCount
  const from = m.fromChapter || 1
  const range = from > 1 || m.toChapter ? `第 ${from}–${m.toChapter || n || '末'} 章` : n ? `全书 ${n} 章` : '全书'
  const parts = []
  if (DEPTH[m.depth]) parts.push(`${DEPTH[m.depth]}档`)
  if (m.rounds) parts.push(`${m.rounds} 遍`)
  parts.push(range)
  return parts.join(' · ')
}

const pre = (text) => h('div', { style: 'white-space: pre-line' }, text)

/** 改名对话框 → 新名字（取消 / 失败返回 null） */
export async function renameWorkspace(t) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt('给这个工作区起个名字，方便区分同一本书的几个工作区（留空 = 显示书名）', '工作区名', {
      inputValue: t.title || '',
      inputPlaceholder: `如：${wsSubtitle(t)}`,
      inputValidator: (v) => (v || '').trim().length <= 60 || '最多 60 个字'
    }))
  } catch {
    return null
  }
  try {
    const res = await renameExtract(t.id, (value || '').trim())
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success('已改名')
    return res.data.title || ''
  } catch (e) {
    ElMessage.error(errorMessage(e, '改名失败'))
    return null
  }
}

/**
 * 删除工作区：先读预览列出会删掉什么，二次确认；是这本书最后一个工作区时要输入书名才删（连同这本书的素材）。
 * → true = 已删除
 */
export async function deleteWorkspace(t) {
  let p
  try {
    const res = await deleteExtractPreview(t.id)
    if (res.code !== 0) throw new Error(res.message)
    p = res.data
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取删除预览失败'))
    return false
  }
  if (p.blocked) {
    ElMessage.warning(p.blocked)
    return false
  }
  const items = []
  if (p.checkpointChapters) items.push(`已读 ${p.checkpointChapters} 份的断点`)
  if (p.compileCount) items.push(`整理记录 ${p.compileCount} 次`)
  if (p.candidateCount) items.push(`素材候选 ${p.candidateCount} 条`)
  items.push('提取结果（逐章卡片、实体档案）')
  let msg = `删除「${wsTitle(t)}」（${wsSubtitle(t)}）？将删除：${items.join('、')}。小说文件不动。`
  if (!p.lastOfBook) msg += `\n《${p.book}》还有别的工作区，素材库里这本书的素材保留。`
  try {
    if (p.lastOfBook && p.materialCount > 0) {
      const keep = p.pinnedCount ? `（标记为保留的 ${p.pinnedCount} 条不删）` : ''
      await ElMessageBox.prompt(
        pre(`${msg}\n\n这是《${p.book}》的最后一个工作区：素材库里这本书的 ${p.materialCount} 条素材会一并删除${keep}。\n输入书名「${p.book}」确认：`),
        '删除工作区',
        {
          type: 'warning',
          confirmButtonText: '删除',
          confirmButtonClass: 'el-button--danger',
          inputValidator: (v) => (v || '').trim() === p.book || '书名不对'
        }
      )
    } else {
      await ElMessageBox.confirm(pre(msg), '删除工作区', { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' })
    }
  } catch {
    return false
  }
  try {
    const res = await deleteExtracts([t.id])
    if (res.code !== 0) throw new Error(res.message)
    if (!res.data.deleted) throw new Error(res.data.reasons?.[0] || '没有删掉')
    ElMessage.success('已删除' + (res.data.materialsDeleted ? `，同时删除 ${res.data.materialsDeleted} 条素材` : ''))
    try {
      localStorage.removeItem(`nan_novel.entityMerge.${t.id}`)
    } catch {
      // 存储不可用：忽略
    }
    return true
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
    return false
  }
}
