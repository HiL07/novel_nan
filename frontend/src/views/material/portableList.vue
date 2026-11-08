<template>
  <div class="pl-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>
            <span class="card-title">架空工作区</span>
            <span class="muted">每次架空一个工作区：勾选素材库里的原素材加入待加工，生成能搬到别的小说里用的架空版（原素材不动，不同工作区的架空版互相独立）</span>
          </span>
          <span>
            <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
            <el-button type="primary" :icon="Plus" @click="openCreate">新建工作区</el-button>
          </span>
        </div>
      </template>

      <el-empty v-if="!list.length && !loading" description="还没有架空工作区：新建一个，选好示例世界，再勾选要加工的素材" />
      <div class="ws-grid">
        <div v-for="w in list" :key="w.id" class="ws-card" @click="router.push(`/material/portable/${w.id}`)">
          <div class="ws-head">
            <span class="ws-title">{{ w.title }}</span>
            <el-tag size="small" :type="WS_STATE[w.status]?.type">{{ WS_STATE[w.status]?.label || w.status }}</el-tag>
            <span class="spacer" />
            <el-dropdown trigger="click" @command="(c) => onCommand(c, w)" @click.stop>
              <el-button link :icon="MoreFilled" @click.stop />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">改名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="muted">示例世界：{{ w.targetWorld || 'AI 自选（和原作类型差别大的世界）' }} · {{ w.model?.source === 'gguf' ? 'GGUF' : '大模型' }}</div>
          <div class="ws-counts">
            <span>已加工 <b>{{ w.counts?.DONE || 0 }}</b></span>
            <span>待加工 <b>{{ w.counts?.QUEUED || 0 }}</b></span>
            <span v-if="w.counts?.RUNNING">加工中 <b>{{ w.counts.RUNNING }}</b></span>
            <span v-if="w.counts?.FAILED" class="danger">失败 <b>{{ w.counts.FAILED }}</b></span>
          </div>
          <el-progress :percentage="wsPercent(w)" :stroke-width="6" :show-text="false" />
          <div v-if="w.current?.length" class="muted ellipsis">正在加工：{{ w.current.join('、') }}</div>
          <div v-else-if="w.message" class="muted ellipsis" :title="w.message">{{ w.message }}</div>
          <div class="muted">更新于 {{ w.updateTime }}</div>
        </div>
      </div>
    </el-card>

    <el-dialog v-model="createDlg.visible" title="新建架空工作区" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="createDlg.title" maxlength="60" placeholder="不填：架空工作区 N" />
        </el-form-item>
        <el-form-item label="示例世界">
          <el-input v-model="createDlg.targetWorld" maxlength="200" clearable placeholder="如「赛博朋克都市」；不填：每条由 AI 选一个和原作类型差别大的世界" />
        </el-form-item>
        <el-form-item label="模型">
          <el-radio-group v-model="createDlg.source">
            <el-radio-button value="api">大模型（启用中的配置）</el-radio-button>
            <el-radio-button value="gguf">GGUF</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="createDlg.saving" @click="create">新建并打开</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { MoreFilled, Plus, Refresh } from '@element-plus/icons-vue'
import { createPortableWs, listPortableWs } from '@/api/material'
import { errorMessage } from '@/api/request'
import { WS_STATE, deleteWs, renameWs, wsPercent } from '@/components/material/portableWs'

/** 架空工作区列表：卡片网格，加工中的工作区每 3 秒刷新进度 */
const router = useRouter()
const list = ref([])
const loading = ref(false)
let timer = null

async function load() {
  clearTimeout(timer)
  loading.value = true
  try {
    const res = await listPortableWs()
    if (res.code !== 0) throw new Error(res.message)
    list.value = res.data || []
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取架空工作区失败'))
  } finally {
    loading.value = false
  }
  if (list.value.some((w) => w.status === 'RUNNING')) timer = setTimeout(load, 3000)
}

const createDlg = reactive({ visible: false, title: '', targetWorld: '', source: 'api', saving: false })
function openCreate() {
  Object.assign(createDlg, { visible: true, title: '', targetWorld: '', source: 'api', saving: false })
}
async function create() {
  createDlg.saving = true
  try {
    const res = await createPortableWs({
      title: createDlg.title.trim() || undefined,
      targetWorld: createDlg.targetWorld.trim(),
      model: { source: createDlg.source }
    })
    if (res.code !== 0) throw new Error(res.message)
    createDlg.visible = false
    router.push(`/material/portable/${res.data.id}`)
  } catch (e) {
    ElMessage.error(errorMessage(e, '新建失败'))
  } finally {
    createDlg.saving = false
  }
}

async function onCommand(cmd, w) {
  if (cmd === 'rename' && (await renameWs(w))) load()
  if (cmd === 'delete' && (await deleteWs(w))) load()
}

onActivated(load)
onDeactivated(() => clearTimeout(timer))
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(60, 40, 20, 0.06);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.card-title {
  margin-right: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ws-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.ws-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  cursor: pointer;
  background: var(--el-bg-color);
}
.ws-card:hover {
  border-color: var(--el-color-primary);
}
.ws-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ws-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.spacer {
  flex: 1;
}
.ws-counts {
  display: flex;
  gap: 14px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.danger {
  color: var(--el-color-danger);
}
</style>
