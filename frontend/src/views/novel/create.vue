<template>
  <div class="workspace-list">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">小说创作 · 工作区</span>
          <div>
            <el-button :icon="Refresh" @click="load">刷新</el-button>
            <el-button type="primary" :icon="Plus" @click="openCreate">新建工作区</el-button>
          </div>
        </div>
      </template>

      <!-- 默认模型检测 -->
      <el-alert
        v-if="status && !status.defaultModel.found"
        type="warning"
        show-icon
        :closable="false"
        class="model-alert"
        :title="`未找到默认生成模型 ${status.defaultModel.repoId}`"
      >
        <div>
          可一键下载到项目目录（<code>{{ status.defaultModel.downloadDir }}</code>，约 3.1 GB，完成后自动登记），
          或手动下载：<a :href="status.defaultModel.links.huggingface" target="_blank" rel="noopener">Hugging Face</a>
          ／ <a :href="status.defaultModel.links.mirror" target="_blank" rel="noopener">hf-mirror 国内镜像</a>
          ／ <a :href="status.defaultModel.links.modelscope" target="_blank" rel="noopener">ModelScope 魔搭</a>，
          再到「本地模型」页登记目录。
        </div>
        <el-button class="dl-btn" type="primary" size="small" :loading="downloading" @click="downloadDefault">下载到项目</el-button>
      </el-alert>
      <div v-else-if="status" class="model-ok">
        <el-tag type="success" size="small">默认模型就绪</el-tag>
        {{ status.defaultModel.model.name }} <code>{{ status.defaultModel.model.path }}</code>
      </div>
      <el-alert v-if="loadError" type="error" :closable="false" show-icon :title="loadError" class="model-alert" />

      <el-empty v-if="!novels.length" description="还没有工作区，点击「新建工作区」开始一部小说" />
      <div v-else class="novel-grid">
        <div v-for="n in novels" :key="n.id" class="novel-card" @click="open(n.id)">
          <div class="novel-title">{{ n.title }}</div>
          <div class="novel-meta">
            <span>{{ modelLabel(n.model) }}</span>
            <span>窗口 {{ n.contextWindow }}</span>
          </div>
          <div class="novel-meta">
            <span>{{ n.chapterCount }} 章 · {{ n.totalChars }} 字</span>
            <el-tag v-if="!n.hasSettings" size="small" type="info">未保存设定</el-tag>
          </div>
          <div class="novel-foot">
            <span class="muted">更新于 {{ n.updatedAt }}</span>
            <el-button link type="danger" size="small" @click.stop="onDelete(n)">删除</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 新建工作区 -->
    <el-dialog v-model="createDlg.visible" title="新建工作区" width="560px">
      <el-form label-width="96px">
        <el-form-item label="小说标题"><el-input v-model="createDlg.title" maxlength="100" placeholder="可稍后修改" /></el-form-item>
        <el-form-item label="模型来源">
          <el-radio-group v-model="createDlg.source">
            <el-radio-button value="local">本地模型</el-radio-button>
            <el-radio-button value="remote" disabled>远程模型（即将支持）</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="基础模型">
          <el-select v-model="createDlg.baseId" placeholder="选择已登记的本地模型" style="width: 100%">
            <el-option v-for="m in localModels" :key="m.id" :label="`${m.name}（${(m.numParams / 1e9).toFixed(1)}B）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="LoRA 适配器">
          <el-select model-value="" disabled placeholder="本阶段不启用适配器，仅使用基础模型" style="width: 100%" />
        </el-form-item>
        <el-form-item label="上下文窗口">
          <el-select v-model="createDlg.contextWindow" style="width: 160px">
            <el-option v-for="w in CONTEXT_WINDOWS" :key="w" :label="`${w} tokens`" :value="w" />
          </el-select>
          <span class="muted hint">8192 更快、更稳定；32768 可容纳更多前文与设定</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg.visible = false">取消</el-button>
        <el-button type="primary" :disabled="!createDlg.baseId" @click="onCreate">创建并开始写作</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onActivated, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { CONTEXT_WINDOWS, createNovel, deleteNovel, getGenStatus, listNovels } from '@/api/novelGen'
import { downloadModel, listModels } from '@/api/localModel'
import { errorMessage } from '@/api/request'

const router = useRouter()
const status = ref(null)
const novels = ref([])
const models = ref([])
const loadError = ref('')
const downloading = ref(false)

const localModels = computed(() => models.value.filter((m) => m.exists))
const modelLabel = (m) => (m?.source === 'local' ? models.value.find((x) => x.id === m.baseId)?.name || m.baseId : '远程模型')

async function call(promise, fallback) {
  try {
    const res = await promise
    if (res.code !== 0) throw new Error(res.message || fallback)
    return res.data
  } catch (e) {
    throw new Error(errorMessage(e, fallback))
  }
}

async function load() {
  try {
    const [s, n, m] = await Promise.all([
      call(getGenStatus(), '获取状态失败'), call(listNovels(), '获取工作区失败'), call(listModels(), '获取模型失败')
    ])
    status.value = s
    novels.value = n
    models.value = m
    loadError.value = ''
  } catch (e) {
    loadError.value = `${e.message}（请确认 AI 服务已启动，地址见 VITE_AI_BASE_URL）`
  }
}

async function downloadDefault() {
  downloading.value = true
  try {
    await call(downloadModel(status.value.defaultModel.repoId, 'Qwen2.5-1.5B-Instruct', 'auto'), '启动下载失败')
    ElMessage.success('已开始下载，可在「本地模型 → 风格微调 → 任务记录」查看进度，完成后刷新本页')
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    downloading.value = false
  }
}

const createDlg = reactive({ visible: false, title: '', source: 'local', baseId: '', contextWindow: 8192 })
function openCreate() {
  Object.assign(createDlg, {
    visible: true, title: '', source: 'local', contextWindow: 8192,
    baseId: status.value?.defaultModel.model?.id || localModels.value[0]?.id || ''
  })
}

async function onCreate() {
  try {
    const n = await call(createNovel({
      title: createDlg.title,
      model: { source: createDlg.source, baseId: createDlg.baseId },
      contextWindow: createDlg.contextWindow
    }), '创建失败')
    createDlg.visible = false
    open(n.id)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function open(id) {
  router.push(`/novel/workspace/${id}`)
}

async function onDelete(n) {
  try {
    await ElMessageBox.confirm(`删除工作区「${n.title}」及其全部章节？此操作不可恢复。`, '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await call(deleteNovel(n.id), '删除失败')
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onActivated(load)
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.model-alert {
  margin-bottom: 14px;
}
.dl-btn {
  margin-top: 8px;
}
.model-ok {
  margin-bottom: 14px;
  font-size: 13px;
  color: #606266;
}
code {
  font-family: Consolas, monospace;
  font-size: 12px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.hint {
  margin-left: 10px;
}
.novel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.novel-card {
  padding: 14px 16px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.novel-card:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
}
.novel-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.novel-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 12px;
  color: #606266;
}
.novel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
</style>
