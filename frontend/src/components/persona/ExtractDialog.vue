<template>
  <el-dialog :model-value="modelValue" title="提取人物原型" width="640px" @update:model-value="(v) => emit('update:modelValue', v)" @open="onOpen">
    <el-form label-width="90px" size="small">
      <el-form-item label="资料来源">
        <el-radio-group v-model="form.type">
          <el-radio-button value="text">粘贴资料</el-radio-button>
          <el-radio-button value="file">文件管理里的文件</el-radio-button>
          <el-radio-button value="extract" :disabled="!entity">实体档案</el-radio-button>
          <el-radio-button value="manual">手写（空白卡）</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.type === 'extract' && entity" label="人物">
        <span>{{ entity.name }}（提取任务 #{{ entity.extractId }}，事实会作为已核实的证据一起用，并读这本书原文里他出场的段落）</span>
      </el-form-item>
      <el-form-item label="名字">
        <el-input v-model="form.name" maxlength="60" placeholder="如：拉瓦锡 / 林远" class="w240" />
      </el-form-item>
      <el-form-item label="别名">
        <el-select v-model="form.aliases" multiple filterable allow-create default-first-option class="full"
                   placeholder="书里对他的其他称呼（定位原文段落用），回车添加" />
      </el-form-item>
      <el-form-item label="分类">
        <el-input v-model="form.kind" maxlength="20" placeholder="可选：学者 / 剑客 / 商人…" class="w240" />
      </el-form-item>
      <el-form-item v-if="form.type === 'text'" label="资料">
        <el-input v-model="form.text" type="textarea" :autosize="{ minRows: 6, maxRows: 14 }" maxlength="600000" show-word-limit
                  placeholder="人物传记、小说片段、访谈……越多越好" />
      </el-form-item>
      <el-form-item v-if="form.type === 'file'" label="文件">
        <el-select v-model="form.fileIds" multiple filterable class="full" placeholder="txt / md / docx / pdf">
          <el-option v-for="f in files" :key="f.id" :label="f.fileName" :value="f.id" />
        </el-select>
      </el-form-item>
      <template v-if="form.type !== 'manual'">
        <el-form-item label="整篇关于他">
          <el-switch v-model="form.whole" />
          <span class="muted">开：整篇资料都读（传记）；关：只读名字 / 别名出现处前后 800 字（小说），提及太多时按开头 / 中段 / 结尾抽样</span>
        </el-form-item>
        <el-form-item label="最多读">
          <el-input-number v-model="form.maxBlocks" :min="5" :max="200" :step="10" /> <span class="muted">块（每块约 3000 字，一块一次调用）</span>
        </el-form-item>
        <el-form-item label="模型"><ModelPicker v-model="model" /></el-form-item>
      </template>
    </el-form>
    <div class="muted">每条证据都要带原文引文，引文会在原文里核对，对不上的丢掉；特征的出处（原文 / 推断）由代码判定。</div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="starting" @click="start">{{ form.type === 'manual' ? '新建' : '开始提取' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createPersona, extractPersona } from '@/api/persona'
import { listFiles } from '@/api/file'
import { errorMessage } from '@/api/request'
import ModelPicker from './ModelPicker.vue'

/** entity = {extractId, entityKey, name}：从实体档案「提取为原型」进来 */
const props = defineProps({ modelValue: { type: Boolean, default: false }, entity: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'started'])
const blank = () => ({ type: 'text', name: '', aliases: [], kind: '', text: '', fileIds: [], whole: false, maxBlocks: 60 })
const form = ref(blank())
const model = ref({ source: 'api', configId: null, baseId: '' })
const files = ref([])
const starting = ref(false)

async function onOpen() {
  form.value = blank()
  if (props.entity) Object.assign(form.value, { type: 'extract', name: props.entity.name || '' })
  try {
    const res = await listFiles()
    files.value = res.code === 0 ? (res.data || []).filter((f) => ['txt', 'md', 'docx', 'pdf'].includes((f.fileExt || '').toLowerCase())) : []
  } catch {
    files.value = []
  }
}

function modelBody() {
  const m = model.value
  return m.source === 'local' ? { source: 'local', baseId: m.baseId } : m.source === 'gguf' ? { source: 'gguf' } : { source: 'api', configId: m.configId }
}

async function start() {
  const f = form.value
  starting.value = true
  try {
    let res
    if (f.type === 'manual') {
      res = await createPersona({ name: f.name, aliases: f.aliases, kind: f.kind })
    } else {
      const source = { type: f.type, whole: f.whole }
      if (f.type === 'text') source.text = f.text
      if (f.type === 'file') source.fileIds = f.fileIds
      if (f.type === 'extract') Object.assign(source, { extractId: props.entity.extractId, entityKey: props.entity.entityKey })
      res = await extractPersona({ name: f.name, aliases: f.aliases, kind: f.kind, source, maxBlocks: f.maxBlocks, model: modelBody() })
    }
    if (res.code !== 0) throw new Error(res.message)
    emit('started', res.data)
    emit('update:modelValue', false)
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '开始失败'), duration: 8000 })
  } finally {
    starting.value = false
  }
}
</script>

<style scoped>
.muted { margin-left: 8px; font-size: 12px; color: #909399; }
.w240 { width: 240px; }
.full { width: 100%; }
</style>
