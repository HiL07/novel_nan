import { ElMessage, ElMessageBox } from 'element-plus'
import { deletePortableWs, portableWsDeletePreview, updatePortableWs } from '@/api/material'
import { errorMessage } from '@/api/request'

/** 架空工作区：列表页和工作区页共用的状态文案 / 改名 / 删除 */
export const WS_STATE = {
  IDLE: { label: '空闲', type: 'info' },
  RUNNING: { label: '加工中', type: 'primary' },
  PAUSED: { label: '已暂停', type: 'warning' }
}

/** 条目在工作区里的状态（none = 还没加入） */
export const ITEM_STATE = {
  none: { label: '未加入', type: 'info' },
  QUEUED: { label: '待加工', type: 'warning' },
  RUNNING: { label: '加工中', type: 'primary' },
  DONE: { label: '已加工', type: 'success' },
  FAILED: { label: '失败', type: 'danger' }
}

export const wsDone = (w) => w.counts?.DONE || 0
export const wsTotal = (w) => Object.values(w.counts || {}).reduce((a, b) => a + b, 0)
export const wsPercent = (w) => (wsTotal(w) ? Math.round(((wsDone(w) + (w.counts?.FAILED || 0)) * 100) / wsTotal(w)) : 0)

/** 改名 → 新的工作区；取消返回 null */
export async function renameWs(w) {
  let title
  try {
    ;({ value: title } = await ElMessageBox.prompt('工作区名称', '改名', {
      inputValue: w.title,
      inputValidator: (v) => !!(v || '').trim() || '名称不能为空'
    }))
  } catch {
    return null
  }
  try {
    const res = await updatePortableWs(w.id, { title: title.trim() })
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success('已改名')
    return res.data
  } catch (e) {
    ElMessage.error(errorMessage(e, '改名失败'))
    return null
  }
}

/** 删除（二次确认；产出过架空版时问要不要一起删）→ true = 删了 */
export async function deleteWs(w) {
  let preview
  try {
    const res = await portableWsDeletePreview(w.id)
    if (res.code !== 0) throw new Error(res.message)
    preview = res.data
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
    return false
  }
  if (preview.blocked) {
    ElMessage.warning(preview.blocked)
    return false
  }
  let withMaterials = false
  if (preview.portables) {
    try {
      await ElMessageBox.confirm(
        `「${w.title}」产出了 ${preview.portables} 条架空版，它们在素材库里。删除工作区时要不要一起删掉？`,
        '删除架空工作区',
        { type: 'warning', distinguishCancelAndClose: true, confirmButtonText: '连架空版一起删', cancelButtonText: '只删工作区，架空版留着' }
      )
      withMaterials = true
    } catch (action) {
      if (action !== 'cancel') return false // 关掉弹窗 = 不删
    }
  }
  try {
    await ElMessageBox.confirm(
      withMaterials ? `确定删除「${w.title}」和它的 ${preview.portables} 条架空版？不能恢复。` : `确定删除「${w.title}」？原素材不受影响。`,
      '再确认一次',
      { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' }
    )
  } catch {
    return false
  }
  try {
    const res = await deletePortableWs(w.id, withMaterials)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(withMaterials ? `已删除，连同 ${res.data.deletedMaterials} 条架空版` : '已删除')
    return true
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
    return false
  }
}
