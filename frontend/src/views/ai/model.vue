<template>
  <div class="model-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">模型配置</span>
          <div>
            <el-button :icon="Refresh" :loading="loading" @click="loadModels">刷新</el-button>
            <el-button type="primary" :icon="Plus" @click="openForm()">新增模型</el-button>
          </div>
        </div>
      </template>

      <el-alert
        class="tip"
        type="info"
        :closable="false"
        show-icon
        title="可以选第三方模型提供商，也可以添加自定义模型 API（OpenAI 兼容 / Anthropic 协议）。新增或修改地址、协议、模型、Key 后必须「验证」通过才能启用；小说提取始终使用「当前启用」的模型。"
      />

      <el-empty v-if="!models.length" description="暂无模型配置，请点击「新增模型」" />

      <el-table v-else :data="models" stripe>
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <span class="model-name">{{ row.name }}</span>
            <el-tag v-if="row.active" type="success" size="small" effect="dark">当前启用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="提供商" min-width="150">
          <template #default="{ row }">
            <template v-if="row.providerType === 'custom'">
              <span class="provider-id">{{ row.providerId }}</span>
              <el-tag size="small" type="info" class="proto-tag">{{ protocolLabel(row.protocol) }}</el-tag>
            </template>
            <span v-else-if="row.providerType === 'preset'">{{ providerPreset(row.providerId)?.label || row.providerId }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="模型" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.model }}
            <span v-if="(row.models || []).length > 1" class="muted">（目录 {{ row.models.length }}）</span>
          </template>
        </el-table-column>
        <el-table-column prop="baseUrl" label="接口地址" min-width="200" show-overflow-tooltip />
        <el-table-column prop="apiKeyMasked" label="API Key" width="130" />
        <el-table-column prop="concurrency" label="并发" width="70" />
        <el-table-column label="验证状态" min-width="200">
          <template #default="{ row }">
            <el-tag :type="STATUS[row.status]?.type" size="small">{{ STATUS[row.status]?.label || row.status }}</el-tag>
            <div class="verify-msg" :title="row.verifyMessage">{{ row.verifyMessage }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="verifyingId === row.id" @click="onVerify(row)">验证</el-button>
            <el-button
              link
              type="success"
              :disabled="row.active || row.status !== 'VERIFIED'"
              :title="row.status !== 'VERIFIED' ? '验证通过后才能启用' : ''"
              @click="onActivate(row)"
            >
              启用
            </el-button>
            <el-button link type="primary" @click="openForm(row)">编辑</el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增 / 编辑：第三方模型提供商 / 自定义模型 API，最下面是模型目录 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑模型' : '新增模型'" width="660px" destroy-on-close>
      <div class="type-switch">
        <el-radio-group v-model="form.providerType" :disabled="!!form.id" @change="onTypeChange">
          <el-radio-button value="preset">第三方模型提供商</el-radio-button>
          <el-radio-button value="custom">自定义模型 API</el-radio-button>
        </el-radio-group>
        <span v-if="form.id" class="muted">添加方式保存后不能改，需要换方式请新增一个</span>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <!-- 第三方模型提供商 -->
        <template v-if="form.providerType === 'preset'">
          <el-form-item label="提供商" prop="providerId">
            <div class="provider-grid">
              <div
                v-for="p in PROVIDER_PRESETS"
                :key="p.key"
                class="provider-tile"
                :class="{ 'is-active': form.providerId === p.key }"
                @click="pickProvider(p.key)"
              >
                <div class="pt-name">{{ p.label }}</div>
                <div class="pt-host">{{ hostOf(p.baseUrl) }}</div>
              </div>
            </div>
          </el-form-item>
          <el-form-item label="显示名称" prop="name">
            <el-input v-model="form.name" placeholder="如：DeepSeek 主账号" maxlength="100" />
          </el-form-item>
          <el-form-item label="API 秘钥" prop="apiKey">
            <el-input
              v-model="form.apiKey"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="keyPlaceholder"
            />
          </el-form-item>
          <el-form-item label="接口地址" prop="baseUrl">
            <el-input v-model="form.baseUrl" placeholder="选好提供商会自动填写" />
            <div class="form-hint">一般不用改；走代理或私有部署时改成对应地址（{{ protocolLabel(form.protocol) }} 协议）</div>
          </el-form-item>
        </template>

        <!-- 自定义模型 API -->
        <template v-else>
          <el-form-item label="Provider ID" prop="providerId">
            <el-input v-model="form.providerId" placeholder="如：my-openrouter（字母、数字、. _ -）" maxlength="64" />
            <div class="form-hint">这个服务的唯一标识，不能和其他自定义模型重复</div>
          </el-form-item>
          <el-form-item label="显示名称" prop="name">
            <el-input v-model="form.name" placeholder="如：公司内网模型" maxlength="100" />
          </el-form-item>
          <el-form-item label="API 地址" prop="baseUrl">
            <el-input v-model="form.baseUrl" placeholder="如：https://api.example.com/v1" />
          </el-form-item>
          <el-form-item label="API 协议" prop="protocol">
            <el-select v-model="form.protocol" style="width: 220px">
              <el-option v-for="p in API_PROTOCOLS" :key="p.value" :label="p.label" :value="p.value" />
            </el-select>
            <div class="form-hint">{{ API_PROTOCOLS.find((p) => p.value === form.protocol)?.hint }}</div>
          </el-form-item>
          <el-form-item label="API 秘钥" prop="apiKey">
            <el-input
              v-model="form.apiKey"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="keyPlaceholder"
            />
          </el-form-item>
        </template>

        <el-form-item label="并发数" prop="concurrency">
          <el-input-number v-model="form.concurrency" :min="1" :max="8" />
          <span class="inline-hint">一个提取任务同时发出的请求数；本地模型填 1，远程服务视限流调整</span>
        </el-form-item>

        <!-- 模型目录：可用的模型名，选一个当前使用 -->
        <el-form-item label="模型目录" prop="model" class="catalog-item">
          <div class="catalog">
            <div class="catalog-head">
              <span class="muted">
                {{ form.models.length ? `共 ${form.models.length} 个，选中的是当前使用的模型` : '还没有模型' }}
              </span>
              <el-button size="small" :icon="Download" :loading="fetching" @click="onFetchModels">获取可用模型</el-button>
            </div>
            <div class="catalog-add">
              <el-input v-model="newModel" size="small" placeholder="手动添加模型名，如 deepseek-chat" @keyup.enter="addModel" />
              <el-button size="small" :icon="Plus" :disabled="!newModel.trim()" @click="addModel">添加</el-button>
              <el-input
                v-if="form.models.length > 8"
                v-model="modelFilter"
                size="small"
                clearable
                placeholder="筛选"
                class="catalog-filter"
                :prefix-icon="Search"
              />
            </div>
            <div v-if="fetchMessage" class="fetch-msg" :class="{ 'is-error': !fetchOk }">{{ fetchMessage }}</div>
            <el-radio-group v-if="shownModels.length" v-model="form.model" class="catalog-list">
              <div v-for="m in shownModels" :key="m" class="catalog-row" :class="{ 'is-current': form.model === m }">
                <el-radio :value="m">
                  <span class="cm-id">{{ m }}</span>
                  <span v-if="catalogNames[m]" class="cm-name">{{ catalogNames[m] }}</span>
                </el-radio>
                <el-tag v-if="form.model === m" size="small" type="success">当前使用</el-tag>
                <el-button link size="small" class="cm-del" :icon="Close" title="从目录移除" @click="removeModel(m)" />
              </div>
            </el-radio-group>
            <div v-else-if="form.models.length" class="catalog-empty">没有匹配「{{ modelFilter }}」的模型</div>
            <div v-else class="catalog-empty">点右上角「获取可用模型」从服务读取，或者手动添加</div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button :loading="saving" @click="onSave(false)">仅保存</el-button>
        <el-button type="primary" :loading="saving" @click="onSave(true)">保存并验证</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onActivated, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Download, Plus, Refresh, Search } from '@element-plus/icons-vue'
import {
  API_PROTOCOLS,
  PROVIDER_PRESETS,
  activateModel,
  deleteModel,
  fetchModelCatalog,
  listModels,
  providerPreset,
  saveModel,
  verifyModel
} from '@/api/aiModel'
import { errorMessage } from '@/api/request'

const STATUS = {
  UNVERIFIED: { label: '未验证', type: 'info' },
  VERIFIED: { label: '已验证', type: 'success' },
  FAILED: { label: '验证失败', type: 'danger' }
}

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const models = ref([])
const verifyingId = ref(null)

const formVisible = ref(false)
const formRef = ref()
const saving = ref(false)
const blankForm = () => ({
  id: null,
  providerType: 'preset',
  providerId: '',
  protocol: 'openai',
  name: '',
  baseUrl: '',
  model: '',
  models: [],
  apiKey: '',
  apiKeyMasked: '',
  concurrency: 4
})
const form = reactive(blankForm())

// 模型目录
const newModel = ref('')
const modelFilter = ref('')
const fetching = ref(false)
const fetchMessage = ref('')
const fetchOk = ref(true)
const catalogNames = reactive({}) // 获取到的显示名（如 Anthropic 的 display_name），只用于展示

const shownModels = computed(() => {
  const q = modelFilter.value.trim().toLowerCase()
  return q ? form.models.filter((m) => m.toLowerCase().includes(q)) : form.models
})

const keyPlaceholder = computed(() => {
  if (form.id) return `留空则保持原值（${form.apiKeyMasked || '未设置'}）`
  if (form.providerType === 'preset' && providerPreset(form.providerId)?.noKey) return '本机服务不需要，可留空'
  return form.protocol === 'anthropic' ? 'sk-ant-...' : 'sk-...（本地服务可留空）'
})

const urlRule = [
  { required: true, message: '请输入 API 地址', trigger: 'blur' },
  { pattern: /^https?:\/\/\S+$/i, message: '需以 http:// 或 https:// 开头', trigger: 'blur' }
]
const rules = computed(() => ({
  name: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
  baseUrl: urlRule,
  providerId: form.providerType === 'custom'
    ? [
        { required: true, message: '请输入 Provider ID', trigger: 'blur' },
        { pattern: /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/, message: '只能用字母、数字、. _ -，以字母或数字开头', trigger: 'blur' }
      ]
    : [{ required: true, message: '请选择提供商', trigger: 'change' }],
  model: [{ required: true, message: '请在模型目录里选一个要用的模型（可以手动添加）', trigger: 'change' }]
}))

const protocolLabel = (p) => API_PROTOCOLS.find((x) => x.value === (p || 'openai'))?.label || p
const hostOf = (url) => {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

async function loadModels() {
  loading.value = true
  try {
    const res = await listModels()
    if (res.code === 0) {
      models.value = res.data || []
    } else {
      ElMessage.error(res.message || '加载失败')
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载模型配置失败'))
  } finally {
    loading.value = false
  }
}

function resetCatalogUi() {
  newModel.value = ''
  modelFilter.value = ''
  fetchMessage.value = ''
  fetchOk.value = true
  Object.keys(catalogNames).forEach((k) => delete catalogNames[k])
}

/** 老配置（没有 providerType）：地址和某个预设一样就当第三方提供商，否则当自定义 */
function guessType(row) {
  if (row.providerType) return { providerType: row.providerType, providerId: row.providerId || '' }
  const p = PROVIDER_PRESETS.find((x) => x.baseUrl.replace(/\/+$/, '') === (row.baseUrl || '').replace(/\/+$/, ''))
  if (p) return { providerType: 'preset', providerId: p.key }
  return { providerType: 'custom', providerId: hostOf(row.baseUrl).replace(/[^A-Za-z0-9._-]/g, '-').replace(/^[^A-Za-z0-9]+/, '').slice(0, 64) }
}

function openForm(row) {
  resetCatalogUi()
  Object.assign(form, blankForm())
  if (row) {
    const list = Array.isArray(row.models) && row.models.length ? [...row.models] : [row.model].filter(Boolean)
    if (row.model && !list.includes(row.model)) list.unshift(row.model)
    Object.assign(form, {
      id: row.id,
      ...guessType(row),
      protocol: row.protocol || 'openai',
      name: row.name,
      baseUrl: row.baseUrl,
      model: row.model,
      models: list,
      apiKeyMasked: row.apiKeyMasked,
      concurrency: row.concurrency
    })
  }
  formVisible.value = true
}

function onTypeChange(type) {
  resetCatalogUi()
  const keep = { name: form.name, apiKey: form.apiKey, concurrency: form.concurrency }
  Object.assign(form, blankForm(), keep, { providerType: type })
  formRef.value?.clearValidate()
}

function pickProvider(key) {
  const p = providerPreset(key)
  if (!p) return
  const oldPreset = providerPreset(form.providerId)
  // 名称没改过（空或等于上一个提供商名）就跟着换
  if (!form.name || form.name === oldPreset?.label) form.name = p.label
  resetCatalogUi()
  Object.assign(form, {
    providerId: p.key,
    baseUrl: p.baseUrl,
    protocol: p.protocol,
    models: [...p.models],
    model: p.models[0] || '',
    concurrency: p.concurrency
  })
  formRef.value?.clearValidate(['providerId', 'baseUrl', 'model'])
}

function addModel() {
  const m = newModel.value.trim()
  if (!m) return
  if (m.length > 200) {
    ElMessage.warning('模型名太长')
    return
  }
  if (!form.models.includes(m)) form.models.unshift(m)
  if (!form.model) form.model = m
  newModel.value = ''
  formRef.value?.clearValidate('model')
}

function removeModel(m) {
  form.models = form.models.filter((x) => x !== m)
  if (form.model === m) form.model = form.models[0] || ''
}

async function onFetchModels() {
  if (!/^https?:\/\/\S+$/i.test(form.baseUrl.trim())) {
    ElMessage.warning('先填好 API 地址')
    return
  }
  fetching.value = true
  fetchMessage.value = ''
  try {
    const res = await fetchModelCatalog({
      id: form.id,
      baseUrl: form.baseUrl.trim(),
      protocol: form.protocol,
      apiKey: form.apiKey.trim()
    })
    if (res.code !== 0) {
      fetchOk.value = false
      fetchMessage.value = res.message || '获取失败'
      return
    }
    const data = res.data || {}
    fetchOk.value = !!data.ok
    if (!data.ok) {
      fetchMessage.value = data.message || '获取失败'
      return
    }
    const ids = (data.models || []).map((m) => m.id)
    ;(data.models || []).forEach((m) => { if (m.name && m.name !== m.id) catalogNames[m.id] = m.name })
    // 合并：手动加的 / 已有的留着，新获取的接在后面
    const before = form.models.length
    form.models = [...new Set([...form.models, ...ids])].slice(0, 1000)
    if (!form.model && form.models.length) form.model = form.models[0]
    const added = form.models.length - before
    fetchMessage.value = `${data.message || `获取到 ${ids.length} 个模型`}${added ? `，新加入目录 ${added} 个` : '，目录里都已经有了'}`
    formRef.value?.clearValidate('model')
  } catch (e) {
    fetchOk.value = false
    fetchMessage.value = errorMessage(e, '获取可用模型失败')
  } finally {
    fetching.value = false
  }
}

async function onSave(andVerify) {
  if (!(await formRef.value.validate().catch(() => false))) return
  saving.value = true
  try {
    const { apiKeyMasked, ...payload } = form
    const res = await saveModel(payload)
    if (res.code !== 0) {
      ElMessage.error(res.message || '保存失败')
      return
    }
    formVisible.value = false
    ElMessage.success('已保存')
    await loadModels()
    if (andVerify) await onVerify(res.data)
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function onVerify(row) {
  verifyingId.value = row.id
  try {
    const res = await verifyModel(row.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '验证失败')
    } else if (res.data.status === 'VERIFIED') {
      ElMessage.success(`「${res.data.name}」${res.data.verifyMessage}${res.data.active ? '，已启用' : ''}`)
    } else {
      ElMessage.error({ message: `验证失败：${res.data.verifyMessage}`, duration: 6000 })
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '验证请求失败'))
  } finally {
    verifyingId.value = null
    loadModels()
  }
}

async function onActivate(row) {
  try {
    const res = await activateModel(row.id)
    if (res.code === 0) {
      ElMessage.success(`已启用「${row.name}」`)
    } else {
      ElMessage.error(res.message || '启用失败')
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '启用失败'))
  }
  loadModels()
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name}」？${row.active ? '它是当前启用的模型，删除后需启用其他模型才能继续提取。' : ''}`,
      '删除模型配置',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res = await deleteModel(row.id)
    if (res.code === 0) {
      ElMessage.success('已删除')
    } else {
      ElMessage.error(res.message || '删除失败')
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
  loadModels()
}

onActivated(() => {
  loadModels()
  // 从「本地模型」的 GGUF「使用方法」跳来：?llamacpp=1&name=…&model=… → 打开新增表单，选好本地 llama.cpp
  if (route.query.llamacpp) {
    openForm()
    pickProvider('llamacpp')
    if (route.query.name) form.name = String(route.query.name).slice(0, 60)
    if (route.query.model) {
      const m = String(route.query.model).slice(0, 100)
      form.models = [m, ...form.models.filter((x) => x !== m)]
      form.model = m
    }
    router.replace({ path: route.path })
  }
})
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
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.tip {
  margin-bottom: 12px;
}
.model-name {
  margin-right: 6px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.provider-id {
  margin-right: 6px;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.proto-tag {
  vertical-align: middle;
}
.verify-msg {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.form-hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}
.inline-hint {
  margin-left: 10px;
  font-size: 12px;
  line-height: 1.4;
  color: var(--el-text-color-secondary);
}

/* 添加方式 */
.type-switch {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}

/* 第三方提供商 */
.provider-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}
.provider-tile {
  padding: 8px 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.provider-tile:hover {
  border-color: var(--el-color-primary-light-5);
}
.provider-tile.is-active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  box-shadow: inset 0 0 0 1px var(--el-color-primary);
}
.pt-name {
  font-size: 13px;
  line-height: 1.4;
  color: var(--el-text-color-primary);
}
.provider-tile.is-active .pt-name {
  color: var(--el-color-primary);
  font-weight: 600;
}
.pt-host {
  overflow: hidden;
  font-size: 11px;
  line-height: 1.4;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 模型目录 */
.catalog-item {
  margin-bottom: 0;
}
.catalog {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.catalog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.catalog-add {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.catalog-filter {
  width: 140px;
  flex-shrink: 0;
}
.fetch-msg {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-color-success);
}
.fetch-msg.is-error {
  color: var(--el-color-danger);
}
.catalog-list {
  display: block;
  max-height: 240px;
  margin-top: 8px;
  overflow-y: auto;
}
.catalog-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 6px;
  border-radius: 6px;
}
.catalog-row:hover {
  background: var(--el-fill-color-blank);
}
.catalog-row.is-current {
  background: var(--el-fill-color-blank);
}
.catalog-row .el-radio {
  flex: 1;
  min-width: 0;
  height: 30px;
  margin-right: 0;
}
.catalog-row :deep(.el-radio__label) {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.cm-id {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.cm-name {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.cm-del {
  visibility: hidden;
}
.catalog-row:hover .cm-del {
  visibility: visible;
}
.catalog-empty {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
