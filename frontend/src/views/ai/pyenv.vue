<template>
  <div class="pyenv-page">
    <!-- 当前配置 -->
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">Python 环境</span>
          <el-button :icon="Refresh" :loading="discovering" @click="discover">重新扫描</el-button>
        </div>
      </template>
      <div v-if="current" class="current">
        <el-tag :type="current.exists ? (current.status === 'OK' ? 'success' : 'warning') : 'danger'" effect="dark">
          {{ !current.exists ? '路径已失效' : current.status === 'OK' ? '当前使用' : '当前使用（有警告）' }}
        </el-tag>
        <span class="current-type">{{ TYPE_LABEL[current.envType] }}<template v-if="current.condaEnv"> · {{ current.condaEnv }}</template></span>
        <code class="path">{{ current.pythonPath }}</code>
        <span>Python {{ current.pythonVersion }}</span>
        <span>{{ current.cudaAvailable ? `CUDA ✓ ${current.gpuName || ''}` : 'CUDA ✗' }}</span>
        <span v-if="current.torchVersion">torch {{ current.torchVersion }}</span>
        <span class="muted">检测于 {{ current.checkedTime }}</span>
        <el-button link type="primary" @click="recheckCurrent">重新检测</el-button>
      </div>
      <el-alert
        v-else
        type="info"
        :closable="false"
        show-icon
        title="还没有保存的 Python 环境"
        description="选择环境类型并点击「检测」，检测通过后会自动保存，下次启动（start.bat）自动使用。"
      />
    </el-card>

    <!-- 选择 + 检测 -->
    <el-card class="box-card" shadow="never">
      <div class="step-title">1. 选择环境类型</div>
      <el-radio-group v-model="envType" class="type-group" @change="onTypeChange">
        <el-radio-button v-for="(label, key) in TYPE_LABEL" :key="key" :value="key">{{ label }}</el-radio-button>
      </el-radio-group>

      <div class="step-title">2. 指定 Python</div>

      <!-- 系统 Python -->
      <template v-if="envType === 'SYSTEM'">
        <div v-if="discovering" class="muted">正在查找 PATH 上的 python…</div>
        <el-alert v-else-if="!realSystem.length" type="warning" :closable="false" show-icon title="PATH 上没有找到可用的 python" />
        <el-radio-group v-else v-model="pythonPath" class="candidate-list">
          <el-radio v-for="p in sys.system" :key="p.path" :value="p.path" :disabled="p.stub">
            <code>{{ p.path }}</code>
            <span v-if="p.stub" class="muted">（应用商店占位程序，不可用）</span>
            <span v-else class="muted">（Python {{ p.version || '版本未知' }}）</span>
          </el-radio>
        </el-radio-group>
      </template>

      <!-- Conda -->
      <template v-else-if="envType === 'CONDA'">
        <div v-if="condaLoading" class="muted">正在执行 conda env list…</div>
        <template v-else-if="conda?.found">
          <div class="muted">Conda：<code>{{ conda.root }}</code></div>
          <el-table :data="conda.envs" size="small" highlight-current-row class="conda-table" @current-change="onCondaPick">
            <el-table-column label="" width="40">
              <template #default="{ row }"><el-radio :model-value="condaEnv" :value="row.name" :disabled="!row.hasPython" @click.prevent /></template>
            </el-table-column>
            <el-table-column label="环境" width="160">
              <template #default="{ row }">{{ row.name }} <el-tag v-if="row.base" size="small" type="info">base</el-tag></template>
            </el-table-column>
            <el-table-column label="python.exe" min-width="320">
              <template #default="{ row }">
                <code>{{ row.pythonPath }}</code>
                <span v-if="!row.hasPython" class="danger">（该环境未安装 Python）</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="muted tip">没有合适的环境？可新建：<code>{{ conda.createCommand }}</code></div>
        </template>
        <div v-if="!condaLoading && !conda?.found" class="conda-manual">
          <el-alert type="warning" :closable="false" show-icon :title="conda?.message || '未找到 Conda'" />
          <div class="row">
            <el-input v-model="condaPath" placeholder="Conda 安装目录，如 D:\miniconda3（或其中的 Scripts\conda.exe）" />
            <el-button @click="browseFor('conda')">浏览</el-button>
            <el-button type="primary" @click="loadConda(condaPath)">查找环境</el-button>
          </div>
        </div>
      </template>

      <!-- venv -->
      <template v-else-if="envType === 'VENV'">
        <div class="muted">
          默认使用项目的 venv：<code>{{ sys?.venv?.venvDir }}</code>
          <el-tag size="small" :type="sys?.venv?.exists ? 'success' : 'danger'">{{ sys?.venv?.exists ? '已存在' : '不存在' }}</el-tag>
        </div>
        <div v-if="sys?.venv && !sys.venv.exists" class="muted tip">可在项目根目录创建：<code>{{ sys.venv.createCommand }}</code></div>
      </template>

      <!-- 路径输入（所有类型都可编辑） -->
      <div class="row path-row">
        <el-input v-model="pythonPath" placeholder="python.exe 的完整路径" clearable>
          <template #prepend>python.exe</template>
        </el-input>
        <el-button :icon="FolderOpened" @click="browseFor('python')">浏览</el-button>
        <el-button type="primary" :icon="CircleCheck" :loading="checking" :disabled="!pythonPath" @click="runCheck">检测</el-button>
      </div>
      <div v-if="checking" class="muted">正在运行该 Python 并检测依赖 / CUDA（导入 torch 可能需要几十秒）…</div>

      <!-- 检测结果 -->
      <template v-if="result">
        <div class="step-title">3. 检测结果</div>
        <el-alert
          :type="LEVEL[result.level].type"
          :closable="false"
          show-icon
          :title="LEVEL[result.level].title"
          :description="result.saved ? `已保存为当前环境，下次启动自动使用（写入 ${result.envFile}）。如 AI 服务正在运行，请重启它以切换解释器。` : '未保存：请先解决下面的错误。'"
        />

        <el-descriptions v-if="result.python" :column="3" border size="small" class="result-desc">
          <el-descriptions-item label="Python">
            {{ result.python.version }} · {{ result.python.arch }}
            <el-tag size="small" :type="result.versionOk ? 'success' : 'danger'">{{ result.versionOk ? `≥ ${result.minVersion}` : `需要 ≥ ${result.minVersion}` }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="环境">{{ result.python.condaEnv ? `conda: ${result.python.condaEnv}` : result.python.isVenv ? 'venv' : '系统' }}</el-descriptions-item>
          <el-descriptions-item label="位置"><code>{{ result.python.executable }}</code></el-descriptions-item>
          <el-descriptions-item label="PyTorch">{{ result.cuda?.torchInstalled ? result.cuda.torchVersion : '未安装' }}</el-descriptions-item>
          <el-descriptions-item label="CUDA">
            <el-tag size="small" :type="result.cuda?.cudaAvailable ? 'success' : 'warning'">{{ result.cuda?.cudaAvailable ? `可用（CUDA ${result.cuda.cudaVersion}）` : '不可用' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="GPU / 显存">
            <template v-if="result.cuda?.gpuName">{{ result.cuda.gpuName }} · {{ (result.cuda.vramTotalMB / 1024).toFixed(1) }} GB</template>
            <template v-else>-</template>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="result.problems.length" class="problems">
          <div v-for="(p, i) in result.problems" :key="i" class="problem" :class="p.level.toLowerCase()">
            <div class="problem-title">
              <el-icon><component :is="p.level === 'ERROR' ? 'CircleCloseFilled' : 'WarningFilled'" /></el-icon>{{ p.title }}
            </div>
            <div class="problem-detail">{{ p.detail }}</div>
            <div v-if="p.fix" class="problem-fix">
              <span class="muted">建议：</span>
              <pre>{{ p.fix }}</pre>
              <el-button link size="small" :icon="CopyDocument" @click="copy(p.fix)">复制</el-button>
            </div>
          </div>
        </div>

        <template v-for="r in result.requirements || []" :key="r.file">
          <div class="req-title">{{ r.label }} <span class="muted">{{ reqSummary(r) }}</span></div>
          <el-alert v-if="r.error" type="warning" :closable="false" :title="`无法读取 ${r.file}：${r.error}`" />
          <el-table v-else :data="r.items" size="small" class="req-table">
            <el-table-column prop="name" label="包" width="180" />
            <el-table-column prop="spec" label="要求" width="140" />
            <el-table-column label="已安装" width="180">
              <template #default="{ row }">{{ row.installed || '-' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag size="small" :type="REQ[row.status].type">{{ REQ[row.status].label }}</el-tag></template>
            </el-table-column>
          </el-table>
        </template>
      </template>
    </el-card>

    <!-- Miniconda 指引：没有可用环境 / 检测失败时展示 -->
    <el-card v-if="showMiniconda" class="box-card" shadow="never">
      <template #header><span class="card-title">安装 Miniconda（推荐）</span></template>
      <ol class="guide">
        <li>
          下载 Windows 64 位安装包：
          <a :href="guide.officialDownload" target="_blank" rel="noopener">官方下载</a>（<a :href="guide.officialUrl" target="_blank" rel="noopener">官网</a>）
          ／ <a :href="guide.tunaDownload" target="_blank" rel="noopener">清华镜像下载</a>（<a :href="guide.tunaUrl" target="_blank" rel="noopener">镜像目录</a>，国内更快）
        </li>
        <li>安装时建议选择「Just Me」，安装到空间充足的磁盘（如 D:\miniconda3）。</li>
        <li>打开「Anaconda Prompt」，创建环境：<pre>{{ guide.createCommand }}</pre></li>
        <li>安装依赖：<pre>{{ guide.installCommand }}</pre></li>
        <li>回到本页，选择「Conda 环境」→ 选中 nan_novel → 检测。</li>
      </ol>
    </el-card>

    <!-- 浏览对话框 -->
    <el-dialog v-model="browser.visible" :title="browser.mode === 'conda' ? '选择 Conda 安装目录' : '选择 python.exe'" width="640px">
      <div class="browser-path">
        <el-button size="small" :icon="Back" :disabled="browser.parent === null" @click="openDir(browser.parent)">上一级</el-button>
        <code>{{ browser.path || '此电脑' }}</code>
      </div>
      <div v-loading="browser.loading" class="browser-list">
        <div
          v-for="e in browser.entries"
          :key="e.path"
          class="browser-item"
          @click="e.dir ? openDir(e.path) : pickFile(e.path)"
        >
          <el-icon><component :is="e.dir ? 'Folder' : 'Document'" /></el-icon>
          <span :class="{ 'py-file': !e.dir }">{{ e.name }}</span>
        </div>
        <el-empty v-if="!browser.loading && !browser.entries.length" description="此目录下没有子目录或 python 可执行文件" :image-size="60" />
      </div>
      <template #footer>
        <el-button @click="browser.visible = false">取消</el-button>
        <el-button v-if="browser.mode === 'conda'" type="primary" :disabled="!browser.path" @click="pickCondaDir">选择当前目录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Back, CircleCheck, CopyDocument, FolderOpened, Refresh } from '@element-plus/icons-vue'
import { browseDir, checkEnv, discoverEnvs, listCondaEnvs } from '@/api/pythonEnv'
import { errorMessage } from '@/api/request'

const TYPE_LABEL = { SYSTEM: '系统 Python', CONDA: 'Conda 环境', VENV: '项目 venv', CUSTOM: '自定义路径' }
const LEVEL = {
  OK: { type: 'success', title: '检测通过' },
  WARN: { type: 'warning', title: '检测通过，但有需要处理的问题' },
  ERROR: { type: 'error', title: '检测未通过' }
}
const REQ = {
  ok: { label: '已安装', type: 'success' },
  missing: { label: '缺失', type: 'danger' },
  mismatch: { label: '版本不符', type: 'warning' }
}

const sys = ref(null)
const current = ref(null)
const discovering = ref(false)
const envType = ref('VENV')
const pythonPath = ref('')
const conda = ref(null)
const condaLoading = ref(false)
const condaPath = ref('')
const condaEnv = ref('')
const checking = ref(false)
const result = ref(null)

const realSystem = computed(() => (sys.value?.system || []).filter((p) => !p.stub))
const guide = computed(() => sys.value?.miniconda || {})
const showMiniconda = computed(() => (sys.value && !sys.value.anyUsable) || result.value?.level === 'ERROR')

function reqSummary(r) {
  if (!r.items) return ''
  const bad = r.items.filter((i) => i.status !== 'ok').length
  return bad ? `${bad} 项未满足 / 共 ${r.items.length} 项` : `全部满足（${r.items.length} 项）`
}

async function call(promise, fallback) {
  try {
    const res = await promise
    if (res.code !== 0) throw new Error(res.message || fallback)
    return res.data
  } catch (e) {
    throw new Error(errorMessage(e, fallback))
  }
}

async function discover() {
  discovering.value = true
  try {
    sys.value = await call(discoverEnvs(), '扫描 Python 环境失败')
    current.value = sys.value.current
    conda.value = sys.value.conda
    condaPath.value = sys.value.conda?.root || ''
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    discovering.value = false
  }
}

/** 切换类型时按类型自动填入路径 */
function onTypeChange(type) {
  result.value = null
  condaEnv.value = ''
  if (type === 'SYSTEM') pythonPath.value = realSystem.value[0]?.path || ''
  else if (type === 'VENV') pythonPath.value = sys.value?.venv?.path || ''
  else if (type === 'CONDA') {
    pythonPath.value = ''
    if (!conda.value) loadConda()
  } else pythonPath.value = ''
}

async function loadConda(path) {
  condaLoading.value = true
  try {
    conda.value = await call(listCondaEnvs(path || undefined), '查询 Conda 环境失败')
    if (conda.value.found) condaPath.value = conda.value.root
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    condaLoading.value = false
  }
}

function onCondaPick(row) {
  if (!row || !row.hasPython) return
  condaEnv.value = row.name
  pythonPath.value = row.pythonPath
}

async function runCheck() {
  checking.value = true
  result.value = null
  try {
    result.value = await call(checkEnv({
      envType: envType.value,
      pythonPath: pythonPath.value,
      condaRoot: envType.value === 'CONDA' ? conda.value?.root : null,
      condaEnv: envType.value === 'CONDA' ? condaEnv.value : null
    }), '检测失败')
    if (result.value.saved) {
      ElMessage.success('检测通过，已保存为当前 Python 环境')
      const d = await call(discoverEnvs(), '刷新失败').catch(() => null)
      if (d) current.value = d.current
    }
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    checking.value = false
  }
}

function recheckCurrent() {
  envType.value = current.value.envType
  pythonPath.value = current.value.pythonPath
  condaEnv.value = current.value.condaEnv || ''
  runCheck()
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

/* ---------------- 浏览 ---------------- */
const browser = reactive({ visible: false, mode: 'python', path: '', parent: null, entries: [], loading: false })

async function openDir(path) {
  browser.loading = true
  try {
    const d = await call(browseDir(path || undefined), '浏览目录失败')
    Object.assign(browser, { path: d.path, parent: d.path ? d.parent : null, entries: d.entries })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    browser.loading = false
  }
}

function browseFor(mode) {
  browser.mode = mode
  browser.visible = true
  // 从已填写路径所在目录开始浏览
  const start = mode === 'conda' ? condaPath.value : pythonPath.value.replace(/[\\/][^\\/]*$/, '')
  openDir(start || '').catch(() => openDir(''))
}

function pickFile(path) {
  if (browser.mode !== 'python') return
  pythonPath.value = path
  if (envType.value !== 'CUSTOM' && envType.value !== 'CONDA') envType.value = 'CUSTOM'
  browser.visible = false
}

function pickCondaDir() {
  condaPath.value = browser.path
  browser.visible = false
  loadConda(browser.path)
}

onMounted(async () => {
  await discover()
  if (current.value) {
    envType.value = current.value.envType
    pythonPath.value = current.value.pythonPath
    condaEnv.value = current.value.condaEnv || ''
    result.value = current.value.lastResult
  } else {
    envType.value = sys.value?.venv?.exists ? 'VENV' : realSystem.value.length ? 'SYSTEM' : 'CONDA'
    onTypeChange(envType.value)
  }
})
</script>

<style scoped>
.box-card {
  margin-bottom: 16px;
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
.current {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: #606266;
}
.current-type {
  font-weight: 600;
  color: #303133;
}
code,
.path {
  font-family: Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.danger {
  font-size: 12px;
  color: var(--el-color-danger);
}
.tip {
  margin-top: 6px;
}
.step-title {
  margin: 18px 0 10px;
  font-weight: 600;
  color: #303133;
}
.step-title:first-child {
  margin-top: 0;
}
.candidate-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.conda-table {
  margin-top: 8px;
  cursor: pointer;
}
.conda-manual {
  margin-top: 8px;
}
.row {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.path-row {
  margin-top: 14px;
  max-width: 900px;
}
.result-desc {
  margin-top: 12px;
}
.problems {
  margin-top: 12px;
}
.problem {
  padding: 10px 12px;
  margin-bottom: 8px;
  border-left: 3px solid var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  border-radius: 0 6px 6px 0;
}
.problem.error {
  border-left-color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}
.problem-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #303133;
}
.problem-detail {
  margin: 4px 0;
  font-size: 13px;
  color: #606266;
}
.problem-fix {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.problem-fix pre,
.guide pre {
  flex: 1;
  margin: 0;
  padding: 6px 10px;
  font-family: Consolas, monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
}
.req-title {
  margin: 16px 0 6px;
  font-weight: 600;
  color: #303133;
}
.req-table {
  max-width: 640px;
}
.guide {
  margin: 0;
  padding-left: 20px;
  line-height: 2;
  font-size: 13px;
  color: #303133;
}
.guide pre {
  margin: 4px 0;
}
.browser-path {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.browser-list {
  height: 360px;
  overflow: auto;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}
.browser-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}
.browser-item:hover {
  background: #f5f7fa;
}
.py-file {
  font-weight: 600;
  color: var(--el-color-primary);
}
</style>
