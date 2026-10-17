<template>
  <el-drawer :model-value="modelValue" title="从素材库添加" size="720px" @update:model-value="close" @open="onOpen">
    <div class="filters">
      <el-select v-model="category" placeholder="全部分类" clearable style="width: 130px" @change="onCategory">
        <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
      </el-select>
      <el-input v-model="keyword" placeholder="关键词" clearable style="width: 180px" @keyup.enter="search" @clear="search" />
      <el-select v-model="tags" multiple filterable collapse-tags placeholder="标签" style="width: 200px" @change="search">
        <el-option v-for="t in tagCloud" :key="t.tag" :label="`${t.tag}（${t.count}）`" :value="t.tag" />
      </el-select>
      <el-button :icon="Search" @click="search">检索</el-button>
    </div>

    <div v-loading="loading" class="list">
      <el-empty v-if="!records.length" description="没有符合条件的素材（可到「素材库」页新建或从小说提取中保存）" :image-size="70" />
      <div v-for="m in records" :key="m.id" class="pick-item" :class="{ 'is-checked': selected[m.id] }" @click="toggle(m)">
        <el-checkbox :model-value="!!selected[m.id]" @click.stop @change="toggle(m)" />
        <div class="pick-body">
          <div class="pick-head">
            <el-tag size="small" effect="plain">{{ categoryOf(m.category)?.label }}</el-tag>
            <b>{{ m.title }}</b>
            <span class="muted">{{ m.subtype }}</span>
          </div>
          <div class="pick-summary">{{ m.summary }}</div>
          <div class="pick-tags">
            <el-tag v-for="t in (m.tags || []).slice(0, 6)" :key="t" size="small" type="info">{{ t }}</el-tag>
          </div>
          <div v-if="selected[m.id]" class="target">将应用到：{{ describeTarget(m, categories) }}</div>
        </div>
      </div>
    </div>

    <template #footer>
      <span class="muted footer-hint">应用 = 复制到当前设定，之后可随意修改；素材库后续修改不会影响已应用的内容</span>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :disabled="!selectedList.length" @click="apply">应用 {{ selectedList.length || '' }} 条</el-button>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { MATERIAL_CATEGORIES, categoryOf, getMaterialTags, searchMaterials } from '@/api/material'
import { describeTarget } from '@/novel-options/materialApply'
import { errorMessage } from '@/api/request'

/** categories：当前设定的分类（用于预览应用位置）；initialCategory：打开时预选的素材分类 */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  categories: { type: Array, default: () => [] },
  initialCategory: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'apply'])

const category = ref('')
const keyword = ref('')
const tags = ref([])
const tagCloud = ref([])
const records = ref([])
const loading = ref(false)
const selected = reactive({})

const selectedList = computed(() => Object.values(selected).filter(Boolean))

function close() {
  emit('update:modelValue', false)
}

function onOpen() {
  category.value = props.initialCategory || ''
  Object.keys(selected).forEach((k) => delete selected[k])
  onCategory()
}

function onCategory() {
  tags.value = []
  getMaterialTags(category.value || undefined).then((r) => r.code === 0 && (tagCloud.value = r.data))
  search()
}

async function search() {
  loading.value = true
  try {
    const res = await searchMaterials({ category: category.value || undefined, keyword: keyword.value.trim() || undefined, tags: tags.value, tagMode: 'all', page: 1, size: 50 })
    if (res.code !== 0) throw new Error(res.message)
    records.value = res.data.records
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载素材失败'))
  } finally {
    loading.value = false
  }
}

function toggle(m) {
  selected[m.id] = selected[m.id] ? null : m
}

function apply() {
  emit('apply', selectedList.value)
  close()
}
</script>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.list {
  min-height: 200px;
}
.pick-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  cursor: pointer;
}
.pick-item.is-checked {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.pick-body {
  flex: 1;
  min-width: 0;
}
.pick-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pick-summary {
  margin-top: 4px;
  font-size: 13px;
  color: #606266;
}
.pick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.target {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-primary);
}
.muted {
  font-size: 12px;
  color: #909399;
}
.footer-hint {
  margin-right: 12px;
}
</style>
