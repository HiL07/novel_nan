<template>
  <div class="attr-editor">
    <div v-for="(row, i) in rows" :key="i" class="attr-row">
      <el-input v-model="row.key" placeholder="属性" size="small" class="attr-key" @change="emitValue" />
      <el-input v-model="row.value" placeholder="值（多个用、分隔）" size="small" class="attr-value" @change="emitValue" />
      <el-button link type="danger" size="small" :icon="Delete" @click="remove(i)" />
    </div>
    <div class="attr-add">
      <el-button size="small" :icon="Plus" @click="add('')">添加属性</el-button>
      <el-button v-for="k in missingSuggestions" :key="k" size="small" link type="primary" @click="add(k)">+ {{ k }}</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import { categoryOf } from '@/api/material'

/** 结构化属性编辑：{属性: 值}；数组值以「、」显示与编辑 */
const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  category: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])

const rows = ref([])
const toRows = (obj) =>
  Object.entries(obj || {}).map(([key, v]) => ({ key, value: Array.isArray(v) ? v.join('、') : String(v ?? '') }))
// 自己 emit 回来的值不重建行（否则刚添加、尚未填值的行会消失）
let lastEmitted = null
watch(() => props.modelValue, (v) => {
  if (lastEmitted !== null && JSON.stringify(v || {}) === lastEmitted) return
  rows.value = toRows(v)
}, { immediate: true })

const missingSuggestions = computed(() =>
  (categoryOf(props.category)?.attrs || []).filter((k) => !rows.value.some((r) => r.key === k))
)

function emitValue() {
  const obj = {}
  for (const r of rows.value) {
    const k = r.key.trim()
    if (!k || !r.value.trim()) continue
    const parts = r.value.split(/[、,，;；]/).map((s) => s.trim()).filter(Boolean)
    obj[k] = parts.length > 1 ? parts : r.value.trim()
  }
  lastEmitted = JSON.stringify(obj)
  emit('update:modelValue', obj)
}

function add(key) {
  rows.value.push({ key, value: '' })
}

function remove(i) {
  rows.value.splice(i, 1)
  emitValue()
}
</script>

<style scoped>
.attr-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.attr-key {
  width: 120px;
}
.attr-value {
  flex: 1;
}
.attr-add {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
</style>
