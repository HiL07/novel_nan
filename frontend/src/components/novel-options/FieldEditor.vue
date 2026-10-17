<template>
  <el-dialog :model-value="modelValue" :title="title" width="620px" destroy-on-close @update:model-value="close">
    <el-tabs v-model="tab">
      <el-tab-pane v-if="suggestions.length" label="从推荐添加" name="suggest">
        <p class="hint">点击即可添加，添加后仍可修改选项。</p>
        <div class="suggest-grid">
          <div
            v-for="s in suggestions"
            :key="s.key + s.label"
            class="suggest-card"
            :class="{ 'is-used': isUsed(s) }"
            @click="!isUsed(s) && pickSuggestion(s)"
          >
            <div class="suggest-label">{{ s.label }}</div>
            <div class="suggest-meta">
              {{ typeLabel(s.type) }}<template v-if="s.options?.length"> · {{ s.options.map((o) => o.label).slice(0, 4).join(' / ') }}{{ s.options.length > 4 ? '…' : '' }}</template>
            </div>
            <el-tag v-if="isUsed(s)" size="small" type="info">已添加</el-tag>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="自己定义" name="custom">
        <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
          <el-form-item label="名称" prop="label">
            <el-input v-model="form.label" placeholder="如：怪物弱点、灵根属性" maxlength="30" />
          </el-form-item>
          <el-form-item label="类型" prop="type">
            <el-select v-model="form.type">
              <el-option v-for="t in FIELD_TYPE_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="form.desc" placeholder="可选，显示在名称旁" maxlength="60" />
          </el-form-item>

          <template v-if="isChoiceType">
            <el-form-item label="选项" prop="optionsText">
              <el-input
                v-model="form.optionsText"
                type="textarea"
                :autosize="{ minRows: 4, maxRows: 10 }"
                placeholder="每行一个选项；可写成「选项：说明」&#10;例如：&#10;火属性：攻击性强&#10;水属性&#10;雷属性"
              />
            </el-form-item>
            <el-form-item label="允许自定义">
              <el-switch v-model="form.allowCustom" />
              <span class="inline-hint">选择时可再临时追加选项</span>
            </el-form-item>
            <el-form-item v-if="form.type === 'multi'" label="最多可选">
              <el-input-number v-model="form.max" :min="0" :max="50" controls-position="right" />
              <span class="inline-hint">0 表示不限</span>
            </el-form-item>
          </template>

          <template v-if="form.type === 'number' || form.type === 'slider'">
            <el-form-item label="范围">
              <el-input-number v-model="form.min" controls-position="right" />
              <span class="range-sep">~</span>
              <el-input-number v-model="form.max" controls-position="right" />
            </el-form-item>
            <el-form-item label="默认值">
              <el-input-number v-model="form.default" :min="form.min" :max="form.max" controls-position="right" />
            </el-form-item>
          </template>

          <el-form-item v-if="['text', 'textarea', 'tags'].includes(form.type)" label="占位提示">
            <el-input v-model="form.placeholder" maxlength="60" />
          </el-form-item>

          <template v-if="form.type === 'group'">
            <el-form-item label="单项名称">
              <el-input v-model="form.itemLabel" placeholder="如：怪物、法宝" maxlength="10" />
            </el-form-item>
            <el-form-item label="每项字段">
              <el-input
                v-model="form.groupFieldsText"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="每行一个字段名（单行文本），如：&#10;名称&#10;外形&#10;能力&#10;创建后可在编辑模式继续添加单选 / 多选等字段"
              />
            </el-form-item>
          </template>
        </el-form>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button v-if="tab === 'custom'" type="primary" @click="submitCustom">添加</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { FIELD_TYPES, FIELD_TYPE_OPTIONS } from '@/novel-options/fieldTypes'
import { clone, uid } from '@/novel-options/schema'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '添加选项项' },
  /** 推荐字段（Field 定义） */
  suggestions: { type: Array, default: () => [] },
  /** 目标数组中已有的字段，用于标记「已添加」 */
  existing: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:modelValue', 'save'])

const tab = ref('custom')
const formRef = ref()
const blank = () => ({
  label: '', type: 'single', desc: '', optionsText: '', allowCustom: true, max: 0,
  min: 0, default: null, placeholder: '', itemLabel: '', groupFieldsText: '名称\n描述'
})
const form = reactive(blank())

const isChoiceType = computed(() => !!FIELD_TYPES[form.type]?.choice)
const rules = {
  label: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  optionsText: [{ validator: (_, v, cb) => (isChoiceType.value && !v?.trim() && !form.allowCustom ? cb(new Error('请至少填写一个选项，或开启允许自定义')) : cb()) }]
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, blank())
    tab.value = props.suggestions.some((s) => !isUsed(s)) ? 'suggest' : 'custom'
  }
)

const typeLabel = (t) => FIELD_TYPES[t]?.label || t
const isUsed = (s) => props.existing.some((f) => f.label === s.label)

function close() {
  emit('update:modelValue', false)
}

function pickSuggestion(s) {
  const field = clone(s)
  // 推荐字段的 key 可能与已有字段重复，统一换成新 key
  field.key = uid('f')
  field.custom = true
  emit('save', field)
  close()
}

function parseOptions(text) {
  const seen = new Set()
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [label, ...rest] = line.split(/[:：]/)
      return { value: uid('o'), label: label.trim(), desc: rest.join('：').trim(), custom: true }
    })
    .filter((o) => o.label && !seen.has(o.label) && seen.add(o.label))
}

async function submitCustom() {
  if (!(await formRef.value.validate().catch(() => false))) return
  const field = { key: uid('f'), label: form.label.trim(), type: form.type, custom: true }
  if (form.desc.trim()) field.desc = form.desc.trim()

  if (isChoiceType.value) {
    field.options = parseOptions(form.optionsText)
    field.allowCustom = form.allowCustom
    if (form.type === 'multi' && form.max > 0) field.max = form.max
  } else if (form.type === 'number' || form.type === 'slider') {
    field.min = form.min ?? 0
    // 未填或不大于最小值时给一个可用的默认范围
    field.max = form.max != null && form.max > field.min ? form.max : field.min + (form.type === 'slider' ? 10 : 1000)
    if (form.default != null) field.default = form.default
  } else if (form.type === 'group') {
    field.itemLabel = form.itemLabel.trim() || '项'
    field.fields = form.groupFieldsText
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .map((label) => ({ key: uid('f'), label, type: 'text', custom: true }))
  }
  if (['text', 'textarea', 'tags'].includes(form.type) && form.placeholder.trim()) {
    field.placeholder = form.placeholder.trim()
  }
  emit('save', field)
  close()
}
</script>

<style scoped>
.hint,
.inline-hint {
  font-size: 12px;
  color: #909399;
}
.hint {
  margin: 0 0 10px;
}
.inline-hint {
  margin-left: 10px;
}
.range-sep {
  margin: 0 8px;
  color: #909399;
}
.suggest-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.suggest-card {
  position: relative;
  padding: 10px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.suggest-card:hover:not(.is-used) {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
}
.suggest-card.is-used {
  cursor: default;
  opacity: 0.55;
}
.suggest-card .el-tag {
  position: absolute;
  top: 8px;
  right: 8px;
}
.suggest-label {
  font-weight: 600;
  color: #303133;
}
.suggest-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
</style>
