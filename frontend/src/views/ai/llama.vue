<template>
  <div class="llama-page">
    <!-- 运行状态 -->
    <el-card class="box-card" shadow="never">
      <div class="head-row">
        <span class="card-title">llama.cpp（GGUF 模型）</span>
        <el-tag :type="STATUS[st.status]?.type || 'info'" effect="dark">{{ STATUS[st.status]?.label || st.status }}</el-tag>
        <span v-if="gpu" class="muted">
          {{ gpu.name }} · 显存 {{ gpu.usedGB.toFixed(1) }}/{{ gpu.totalGB.toFixed(1) }} GB
        </span>
        <el-button class="head-refresh" :icon="Refresh" circle size="small" @click="refresh" />
      </div>
      <p class="intro">
        默认不启动。选一个 GGUF 模型 → 自动检查 → 点「启动」后，写作工作区 / AI 构思 / AI 填写 / 小说提取选模型时就能选「GGUF」。
        同一时间只运行一个，换模型会先关掉当前的；AI 服务关闭时它也一起关闭。
      </p>

      <div v-if="st.status !== 'stopped'" class="run-box">
        <div class="run-line">
          <b>{{ st.name }}</b>
          <el-tag v-if="st.quant" size="small">{{ st.quant }}</el-tag>
          <span class="muted">上下文 {{ st.ctx }} · GPU 层数 {{ st.ngl }} · 端口 {{ st.port }}<template v-if="st.pid"> · PID {{ st.pid }}</template></span>
        </div>
        <div class="muted">
          <template v-if="st.status === 'starting'"><el-icon class="is-loading"><Loading /></el-icon> 正在加载模型…（{{ st.startedAt }} 开始）</template>
          <template v-else-if="st.status === 'running'">运行中，地址 {{ st.baseUrl }}（{{ st.readyAt }} 就绪）<template v-if="st.estimateGB"> · 预计占显存约 {{ st.estimateGB }} GB</template></template>
        </div>
        <el-alert v-if="st.error" class="mt8" type="error" show-icon :closable="false" :title="st.error" />
        <div class="mt8">
          <el-button v-if="st.status === 'starting' || st.status === 'running'" type="danger" plain :loading="busy" @click="onStop">停止</el-button>
        </div>
      </div>
    </el-card>

    <!-- 选择并启动 -->
    <el-card class="box-card" shadow="never">
      <template #header><span class="card-title">选择 GGUF 模型并启动</span></template>
      <el-form label-width="120px" class="form">
        <el-form-item label="GGUF 模型">
          <el-select v-model="form.choice" filterable placeholder="选择已登记的 GGUF，或「其他路径」" style="width: 460px" @change="scheduleCheck">
            <el-option v-for="m in ggufModels" :key="m.id" :label="`${m.name}${m.quant ? ' · ' + m.quant : ''}`" :value="m.id" />
            <el-option label="其他 .gguf 路径…" value="__path__" />
          </el-select>
          <router-link class="link" to="/ai/local">去「本地模型」登记 GGUF</router-link>
        </el-form-item>
        <el-form-item v-if="form.choice === '__path__'" label=".gguf 路径">
          <el-input v-model="form.path" placeholder="例如 E:\workplace\model\xxx-Q4_K_M.gguf" style="width: 560px" @change="scheduleCheck" />
        </el-form-item>
        <el-form-item label="上下文长度">
          <el-input-number v-model="form.ctx" :min="512" :max="131072" :step="1024" @change="scheduleCheck" />
          <span class="hint">越长占显存越多；小说提取建议 ≥ 12288。写作工作区的上下文窗口不要超过它</span>
        </el-form-item>
        <el-form-item label="GPU 层数">
          <el-input-number v-model="form.ngl" :min="0" :max="999" @change="scheduleCheck" />
          <span class="hint">99 = 全部放进显存；显存不够时调小，其余层在 CPU 上跑（会变慢）</span>
        </el-form-item>
        <el-form-item label="固定参数">
          <code>{{ settings.stableArgs }}</code>
          <span class="hint">这台机器上的稳定配置（默认 4 个并发槽 + 8GB 提示缓存会在约 15 分钟后 CUDA 报错崩溃）</span>
        </el-form-item>
      </el-form>

      <!-- 检查结果 -->
      <div v-if="checking" class="muted"><el-icon class="is-loading"><Loading /></el-icon> 检查中…</div>
      <template v-else-if="report">
        <el-alert :type="LEVEL[report.level].type" :closable="false" show-icon :title="LEVEL[report.level].title">
          <ul v-if="report.problems.length" class="problems">
            <li v-for="(p, i) in report.problems" :key="i" :class="`p-${p.level}`">{{ p.text }}</li>
          </ul>
        </el-alert>
        <div v-if="report.model" class="model-info">
          <span>架构 {{ report.model.modelType }}</span>
          <span v-if="report.model.quant">量化 {{ report.model.quant }}</span>
          <span>文件 {{ gb(report.model.sizeBytes) }} GB</span>
          <span v-if="report.model.contextLength">训练上下文 {{ report.model.contextLength }}</span>
          <span v-if="report.estimate">
            预计显存：权重 {{ report.estimate.weightsGB }} + 上下文缓存 {{ report.estimate.kvGB }} + 开销 {{ report.estimate.overheadGB }}
            ≈ <b>{{ report.estimate.needGB }} GB</b><template v-if="report.estimate.freeGB != null"> / 可用 {{ report.estimate.freeGB }} GB</template>
          </span>
        </div>
      </template>

      <div class="actions">
        <el-button :disabled="!hasModel" :loading="checking" @click="runCheck">重新检查</el-button>
        <el-button type="primary" :disabled="!canStart" :loading="busy" @click="onStart()">
          {{ st.status === 'running' || st.status === 'starting' ? '换成这个模型（先停止当前的）' : '启动' }}
        </el-button>
      </div>
    </el-card>

    <!-- llama-server 位置 -->
    <el-card class="box-card" shadow="never">
      <template #header><span class="card-title">llama-server 位置</span></template>
      <div class="server-row">
        <el-input v-model="serverPath" placeholder="llama-server.exe 的完整路径（或所在目录）" style="width: 620px" />
        <el-button :loading="savingServer" @click="onSaveServer">保存</el-button>
        <el-tag :type="settings.serverExists ? 'success' : 'danger'" size="small">{{ settings.serverExists ? '已找到' : '找不到' }}</el-tag>
      </div>
    </el-card>

    <!-- 日志 -->
    <el-card class="box-card" shadow="never">
      <template #header>
        <span class="card-title">日志（最后 {{ LOG_LINES }} 行）</span>
        <el-button class="log-btn" size="small" text :icon="Refresh" @click="loadLog">刷新</el-button>
      </template>
      <pre class="log">{{ logText || '（还没有日志）' }}</pre>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { checkLlama, getLlama, getLlamaLog, isGgufModel, listModels, saveLlamaSettings, startLlama, stopLlama } from '@/api/localModel'
import { errorMessage } from '@/api/request'

const STATUS = {
  stopped: { label: '未启动', type: 'info' },
  starting: { label: '启动中', type: 'warning' },
  running: { label: '运行中', type: 'success' },
  error: { label: '出错', type: 'danger' }
}
const LEVEL = {
  ok: { type: 'success', title: '检查通过，可以启动' },
  warn: { type: 'warning', title: '可以启动，但有需要注意的地方' },
  error: { type: 'error', title: '不能启动' }
}
const LOG_LINES = 80

const st = ref({ status: 'stopped' })
const gpu = ref(null)
const settings = ref({ stableArgs: '', serverExists: true })
const serverPath = ref('')
const savingServer = ref(false)
const ggufModels = ref([])
const form = reactive({ choice: '', path: '', ctx: 12288, ngl: 99 })
const report = ref(null)
const checking = ref(false)
const busy = ref(false)
const logText = ref('')

const gb = (b) => (b / 1024 ** 3).toFixed(2)
const hasModel = computed(() => (form.choice === '__path__' ? !!form.path.trim() : !!form.choice))
const canStart = computed(() => hasModel.value && report.value && report.value.level !== 'error' && !checking.value)

function modelBody() {
  return form.choice === '__path__'
    ? { path: form.path.trim(), ctx: form.ctx, ngl: form.ngl }
    : { baseId: form.choice, ctx: form.ctx, ngl: form.ngl }
}

async function refresh() {
  try {
    const r = await getLlama()
    if (r.code !== 0) throw new Error(r.message)
    const { settings: s, gpu: g, ...rest } = r.data
    st.value = rest
    gpu.value = g
    if (!settings.value.serverPath || settings.value.serverPath !== s.serverPath) serverPath.value = s.serverPath
    settings.value = s
  } catch (e) {
    st.value = { status: 'error', error: errorMessage(e, 'AI 服务连不上') }
  }
  loadLog()
  schedulePoll()
}

async function loadLog() {
  try {
    const r = await getLlamaLog(LOG_LINES)
    if (r.code === 0) logText.value = r.data.text
  } catch {
    /* 日志读不到不影响页面 */
  }
}

async function loadModels() {
  try {
    const r = await listModels()
    if (r.code === 0) ggufModels.value = r.data.filter(isGgufModel)
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取模型列表失败'))
  }
}

/* 选择 / 参数变化后稍等再检查，避免连续输入时反复请求 */
let checkTimer = null
function scheduleCheck() {
  clearTimeout(checkTimer)
  report.value = null
  if (hasModel.value) checkTimer = setTimeout(runCheck, 400)
}

async function runCheck() {
  if (!hasModel.value) return
  checking.value = true
  try {
    const r = await checkLlama(modelBody())
    if (r.code !== 0) throw new Error(r.message)
    report.value = r.data
  } catch (e) {
    report.value = { level: 'error', problems: [{ level: 'error', text: errorMessage(e, '检查失败') }] }
  } finally {
    checking.value = false
  }
}

async function onStart(stopExternal = false) {
  if (!stopExternal && (st.value.status === 'running' || st.value.status === 'starting')) {
    try {
      await ElMessageBox.confirm(`会先停止当前运行的「${st.value.name}」，再启动所选模型。`, '换模型', { type: 'warning', confirmButtonText: '换', cancelButtonText: '取消' })
    } catch {
      return
    }
  }
  busy.value = true
  try {
    const r = await startLlama({ ...modelBody(), stopExternal })
    if (r.code !== 0) throw new Error(r.message)
    ElMessage.success('已开始加载模型')
    await refresh()
  } catch (e) {
    const data = e?.response?.data?.data
    if (data?.needConfirm) {
      busy.value = false
      try {
        await ElMessageBox.confirm(
          `端口 ${st.value.port || 8001} 上有一个不是本页启动的 llama-server（PID ${data.portOwner.pid}，可能是 start-llama.bat 开的）。结束它并启动所选模型？`,
          '端口被占用', { type: 'warning', confirmButtonText: '结束它并启动', cancelButtonText: '取消' })
      } catch {
        return
      }
      return onStart(true)
    }
    ElMessage.error({ message: errorMessage(e, '启动失败'), duration: 8000 })
    if (data?.problems) report.value = data
  } finally {
    busy.value = false
  }
}

async function onStop() {
  busy.value = true
  try {
    await stopLlama()
    ElMessage.success('已停止')
  } catch (e) {
    ElMessage.error(errorMessage(e, '停止失败'))
  } finally {
    busy.value = false
    refresh()
    if (hasModel.value) runCheck()
  }
}

async function onSaveServer() {
  savingServer.value = true
  try {
    const r = await saveLlamaSettings(serverPath.value)
    if (r.code !== 0) throw new Error(r.message)
    settings.value = r.data
    serverPath.value = r.data.serverPath
    ElMessage.success('已保存')
    if (hasModel.value) runCheck()
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    savingServer.value = false
  }
}

/* 启动中每 2 秒、运行中每 10 秒刷新一次状态和日志 */
let pollTimer = null
function schedulePoll() {
  clearTimeout(pollTimer)
  const s = st.value.status
  if (s === 'starting' || s === 'running') pollTimer = setTimeout(refresh, s === 'starting' ? 2000 : 10000)
}

onMounted(async () => {
  await Promise.all([refresh(), loadModels()])
  // 默认选中上次启动的模型（只选中，不启动）
  const last = settings.value.last
  if (last && !form.choice) {
    if (last.baseId && ggufModels.value.some((m) => m.id === last.baseId)) form.choice = last.baseId
    else if (last.path) Object.assign(form, { choice: '__path__', path: last.path })
    if (last.ctx) form.ctx = last.ctx
    if (last.ngl != null) form.ngl = last.ngl
    scheduleCheck()
  }
})
onBeforeUnmount(() => {
  clearTimeout(pollTimer)
  clearTimeout(checkTimer)
})
</script>

<style scoped>
.llama-page .box-card {
  margin-bottom: 16px;
}
.card-title {
  font-weight: 600;
}
.head-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.head-refresh {
  margin-left: auto;
}
.intro,
.muted,
.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.hint {
  margin-left: 12px;
}
.run-box {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 12px;
}
.run-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.mt8 {
  margin-top: 8px;
}
.link {
  margin-left: 12px;
  font-size: 13px;
}
.problems {
  margin: 4px 0 0;
  padding-left: 18px;
}
.p-error {
  color: var(--el-color-danger);
}
.model-info {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.actions {
  margin-top: 14px;
}
.server-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.log-btn {
  float: right;
}
.log {
  max-height: 360px;
  overflow: auto;
  background: var(--el-fill-color-light);
  padding: 10px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
