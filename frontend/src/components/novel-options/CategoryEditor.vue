<template>
  <el-dialog
    :model-value="modelValue"
    :title="editing ? '编辑自定义元素' : '添加自定义元素'"
    width="680px"
    destroy-on-close
    @update:model-value="close"
  >
    <template v-if="!editing">
      <div class="section-title">选择起点</div>
      <div class="template-grid">
        <div class="template-card" :class="{ 'is-active': templateKey === '' }" @click="pickTemplate('')">
          <el-icon class="template-icon"><Plus /></el-icon>
          <div class="template-label">空白元素</div>
          <div class="template-desc">完全自己定义</div>
        </div>
        <div
          v-for="t in templates"
          :key="t.key"
          class="template-card"
          :class="{ 'is-active': templateKey === t.key }"
          @click="pickTemplate(t.key)"
        >
          <el-icon class="template-icon"><component :is="t.icon || 'Collection'" /></el-icon>
          <div class="template-label">{{ t.label }}</div>
          <div class="template-desc">{{ t.desc }}</div>
        </div>
      </div>
      <p v-if="currentTemplate" class="template-fields">
        包含：{{ currentTemplate.fields.map((f) => f.label).join('、') }}（添加后可增删修改）
      </p>
    </template>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="70px" class="cat-form">
      <el-form-item label="名称" prop="label">
        <el-input v-model="form.label" placeholder="如：怪物、灵宠、科技树" maxlength="20" />
      </el-form-item>
      <el-form-item label="图标">
        <div class="icon-grid">
          <span
            v-for="name in ICONS"
            :key="name"
            class="icon-item"
            :class="{ 'is-active': form.icon === name }"
            @click="form.icon = name"
          >
            <el-icon><component :is="name" /></el-icon>
          </span>
        </div>
      </el-form-item>
      <el-form-item label="说明">
        <el-input v-model="form.desc" maxlength="60" placeholder="可选" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" @click="submit">{{ editing ? '保存' : '添加' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Plus } from '@element-plus/icons-vue'

const ICONS = ['Collection', 'Warning', 'OfficeBuilding', 'Avatar', 'Location', 'Present', 'MagicStick', 'Star', 'Sunny', 'Moon', 'Lightning', 'Trophy', 'Key', 'Flag', 'Compass', 'Cpu']

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  templates: { type: Array, default: () => [] },
  /** 传入则为编辑已有自定义元素（只改名称 / 图标 / 说明） */
  editing: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue', 'save'])

const formRef = ref()
const templateKey = ref('')
const form = reactive({ label: '', icon: 'Collection', desc: '' })
const rules = { label: [{ required: true, message: '请输入名称', trigger: 'blur' }] }
const currentTemplate = computed(() => props.templates.find((t) => t.key === templateKey.value))

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    templateKey.value = ''
    Object.assign(form, props.editing
      ? { label: props.editing.label, icon: props.editing.icon || 'Collection', desc: props.editing.desc || '' }
      : { label: '', icon: 'Collection', desc: '' })
  }
)

function pickTemplate(key) {
  const prev = currentTemplate.value
  templateKey.value = key
  const t = currentTemplate.value
  // 名称为空或仍是上一个模板名时，跟随模板
  if (!form.label || (prev && form.label === prev.label)) form.label = t ? t.label : ''
  if (t) {
    form.icon = t.icon || 'Collection'
    form.desc = t.desc || ''
  }
}

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (!(await formRef.value.validate().catch(() => false))) return
  emit('save', { label: form.label.trim(), icon: form.icon, desc: form.desc.trim(), templateKey: templateKey.value })
  close()
}
</script>

<style scoped>
.section-title {
  margin-bottom: 10px;
  font-weight: 600;
  color: #303133;
}
.template-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.template-card {
  padding: 12px 10px;
  text-align: center;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.template-card:hover {
  border-color: var(--el-color-primary-light-3);
}
.template-card.is-active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.template-icon {
  font-size: 22px;
  color: var(--el-color-primary);
}
.template-label {
  margin-top: 4px;
  font-weight: 600;
  color: #303133;
}
.template-desc {
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
}
.template-fields {
  margin: 10px 0 0;
  font-size: 12px;
  color: #606266;
}
.cat-form {
  margin-top: 18px;
}
.icon-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.icon-item {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 16px;
  color: #606266;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: pointer;
}
.icon-item.is-active {
  color: #fff;
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
}
</style>
