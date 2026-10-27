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
        title="支持所有 OpenAI 兼容接口。新增或修改地址、模型、Key 后必须「验证」通过才能启用；小说提取始终使用「当前启用」的模型。"
      />

      <el-empty v-if="!models.length" description="暂无模型配置，请点击「新增模型」" />

      <el-table v-else :data="models" stripe>
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <span class="model-name">{{ row.name }}</span>
            <el-tag v-if="row.active" type="success" size="small" effect="dark">当前启用</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="模型" min-width="150" show-overflow-tooltip />
        <el-table-column prop="baseUrl" label="接口地址" min-width="220" show-overflow-tooltip />
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

    <!-- 新增 / 编辑 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑模型' : '新增模型'" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item v-if="!form.id" label="快速选择">
          <el-select v-model="preset" placeholder="选择常用服务自动填写" clearable @change="applyPreset">
            <el-option v-for="p in MODEL_PRESETS" :key="p.label" :label="p.label" :value="p.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如：DeepSeek 主账号" maxlength="100" />
        </el-form-item>
        <el-form-item label="接口地址" prop="baseUrl">
          <el-input v-model="form.baseUrl" placeholder="如：https://api.deepseek.com" />
          <div class="form-hint">OpenAI 兼容根地址，实际请求 {地址}/chat/completions</div>
        </el-form-item>
        <el-form-item label="模型名" prop="model">
          <el-input v-model="form.model" placeholder="如：deepseek-chat" />
        </el-form-item>
        <el-form-item label="API Key" prop="apiKey">
          <el-input
            v-model="form.apiKey"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="form.id ? `留空则保持原值（${form.apiKeyMasked || '未设置'}）` : 'sk-...（本地模型可留空）'"
          />
        </el-form-item>
        <el-form-item label="并发数" prop="concurrency">
          <el-input-number v-model="form.concurrency" :min="1" :max="8" />
          <div class="form-hint">一个提取任务同时发出的请求数；本地模型填 1，远程服务视限流调整</div>
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
import { onActivated, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { MODEL_PRESETS, activateModel, deleteModel, listModels, saveModel, verifyModel } from '@/api/aiModel'
import { errorMessage } from '@/api/request'

const STATUS = {
  UNVERIFIED: { label: '未验证', type: 'info' },
  VERIFIED: { label: '已验证', type: 'success' },
  FAILED: { label: '验证失败', type: 'danger' }
}

const LLAMACPP_PRESET = MODEL_PRESETS.find((p) => p.baseUrl.includes('127.0.0.1:8001'))?.label
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const models = ref([])
const verifyingId = ref(null)

const formVisible = ref(false)
const formRef = ref()
const saving = ref(false)
const preset = ref('')
const form = reactive({ id: null, name: '', baseUrl: '', model: '', apiKey: '', apiKeyMasked: '', concurrency: 4 })
const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  baseUrl: [
    { required: true, message: '请输入接口地址', trigger: 'blur' },
    { pattern: /^https?:\/\/\S+$/i, message: '需以 http:// 或 https:// 开头', trigger: 'blur' }
  ],
  model: [{ required: true, message: '请输入模型名', trigger: 'blur' }]
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

function openForm(row) {
  preset.value = ''
  Object.assign(form, row
    ? { id: row.id, name: row.name, baseUrl: row.baseUrl, model: row.model, apiKey: '', apiKeyMasked: row.apiKeyMasked, concurrency: row.concurrency }
    : { id: null, name: '', baseUrl: '', model: '', apiKey: '', apiKeyMasked: '', concurrency: 4 })
  formVisible.value = true
}

function applyPreset(label) {
  const p = MODEL_PRESETS.find((x) => x.label === label)
  if (!p) return
  Object.assign(form, { baseUrl: p.baseUrl, model: p.model, concurrency: p.concurrency })
  if (!form.name) form.name = p.label
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
  // 从「本地模型」的 GGUF「使用方法」跳来：?llamacpp=1&name=…&model=… → 打开新增表单并填好 llama.cpp 地址
  if (route.query.llamacpp) {
    openForm()
    applyPreset(LLAMACPP_PRESET)
    if (route.query.name) form.name = String(route.query.name).slice(0, 60)
    if (route.query.model) form.model = String(route.query.model).slice(0, 100)
    router.replace({ path: route.path })
  }
})
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
.tip {
  margin-bottom: 12px;
}
.model-name {
  margin-right: 6px;
}
.verify-msg {
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.form-hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}
</style>
