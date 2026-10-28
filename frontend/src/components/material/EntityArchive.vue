<template>
  <div class="entity-archive">
    <div class="toolbar">
      <el-select v-model="category" placeholder="全部分类" clearable size="small" style="width: 130px">
        <el-option v-for="c in categories" :key="c.code" :label="`${c.label}（${c.count}）`" :value="c.code" />
      </el-select>
      <el-input v-model="keyword" placeholder="名称 / 事实" clearable size="small" style="width: 180px" />
      <el-checkbox :model-value="allChecked" :indeterminate="someChecked && !allChecked" :disabled="!filtered.length" @change="toggleAll">
        全选当前（已勾选 {{ selected.length }}）
      </el-checkbox>
      <el-button size="small" type="danger" plain :icon="Delete" :disabled="!selected.length" @click="removeSelected">删除勾选</el-button>
      <el-button v-if="dirty" size="small" type="success" :icon="Check" :loading="saving" @click="emit('save', list)">保存修改</el-button>
      <el-button size="small" type="primary" :icon="MagicStick" @click="emit('compile', selected)">
        整理卡片{{ selected.length ? `（勾选的 ${selected.length} 个）` : '' }}
      </el-button>
    </div>
    <p class="tip">
      提取时从原文记下的实体和事实（都已核对原文）。认错的、不想要的可以删掉再保存；勾选后点「整理卡片」只整理勾选的。
    </p>

    <el-empty v-if="!filtered.length" description="没有符合条件的实体" :image-size="70" />
    <div v-for="e in paged" :key="e.key" class="entity" :class="{ checked: checked[e.key] }">
      <div class="entity-head">
        <el-checkbox v-model="checked[e.key]" />
        <el-tag size="small" effect="plain">{{ categoryOf(e.category)?.label || e.category }}</el-tag>
        <span class="name">{{ e.name }}</span>
        <span v-if="e.aliases?.length" class="muted">又称 {{ e.aliases.join('、') }}</span>
        <span class="muted">{{ e.facts.length }} 条事实 · {{ chapterSpan(e) }}</span>
        <el-button link type="danger" :icon="Delete" class="del" @click="remove([e.key])" />
      </div>
      <div class="facts-preview">{{ e.facts.slice(0, 3).map((f) => f.fact).join('；') }}{{ e.facts.length > 3 ? '…' : '' }}</div>
      <FactList :facts="e.facts" />
    </div>
    <el-pagination
      v-if="filtered.length > PAGE"
      v-model:current-page="page"
      class="pager"
      small
      layout="prev, pager, next, total"
      :total="filtered.length"
      :page-size="PAGE"
    />
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Check, Delete, MagicStick } from '@element-plus/icons-vue'
import FactList from './FactList.vue'
import { MATERIAL_CATEGORIES, categoryOf } from '@/api/material'

/** 实体档案：提取时记下的实体 + 事实。可筛选、删除（保存由父组件写回提取结果）、勾选后整理卡片 */
const PAGE = 20

const props = defineProps({
  entities: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false }
})
const emit = defineEmits(['save', 'compile'])

const list = ref([])
const dirty = ref(false)
const checked = reactive({})
const category = ref('')
const keyword = ref('')
const page = ref(1)

watch(
  () => props.entities,
  (v) => {
    list.value = [...(v || [])]
    dirty.value = false
    Object.keys(checked).forEach((k) => delete checked[k])
  },
  { immediate: true }
)
watch([category, keyword], () => (page.value = 1))

const categories = computed(() =>
  MATERIAL_CATEGORIES.map((c) => ({ ...c, count: list.value.filter((e) => e.category === c.code).length })).filter((c) => c.count)
)
const filtered = computed(() => {
  const kw = keyword.value.trim()
  return list.value.filter(
    (e) =>
      (!category.value || e.category === category.value) &&
      (!kw || e.name.includes(kw) || e.aliases?.some((a) => a.includes(kw)) || e.facts.some((f) => f.fact.includes(kw)))
  )
})
const paged = computed(() => filtered.value.slice((page.value - 1) * PAGE, page.value * PAGE))
const selected = computed(() => list.value.filter((e) => checked[e.key]).map((e) => e.key))
const allChecked = computed(() => filtered.value.length > 0 && filtered.value.every((e) => checked[e.key]))
const someChecked = computed(() => filtered.value.some((e) => checked[e.key]))

function toggleAll(v) {
  filtered.value.forEach((e) => (checked[e.key] = v))
}

function remove(keys) {
  const drop = new Set(keys)
  list.value = list.value.filter((e) => !drop.has(e.key))
  keys.forEach((k) => delete checked[k])
  dirty.value = true
}

const removeSelected = () => remove(selected.value)

function chapterSpan(e) {
  const chs = [...new Set(e.facts.map((f) => f.chapter).filter(Boolean))]
  if (!chs.length) return ''
  return chs.length === 1 ? chs[0] : `${chs[0]} 等 ${chs.length} 章`
}
</script>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.tip {
  margin: 8px 0 10px;
  font-size: 12px;
  color: #909399;
}
.entity {
  padding: 8px 10px;
  margin-bottom: 8px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.entity.checked {
  border-color: #a0cfff;
  background: #f5f9ff;
}
.entity-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.name {
  font-weight: 600;
  color: #303133;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.del {
  margin-left: auto;
}
.facts-preview {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
.pager {
  margin-top: 10px;
  justify-content: center;
}
</style>
