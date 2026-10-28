<template>
  <div ref="rootRef" v-loading="loading" class="candidate-review">
    <div class="toolbar">
      <el-checkbox :model-value="allChecked" :indeterminate="someChecked && !allChecked" :disabled="!visibleItems.length" @change="toggleAll">
        全选{{ filterCategory ? '本分类' : '' }}（已选 {{ checkedIds.length }}/{{ items.length }}）
      </el-checkbox>
      <el-select v-model="filterCategory" placeholder="全部分类" clearable size="small" style="width: 130px">
        <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
      </el-select>
      <el-button type="primary" size="small" :icon="Check" :disabled="!checkedIds.length" :loading="saving" @click="onSave">保存选中到素材库</el-button>
      <el-button size="small" :icon="Close" :disabled="!checkedIds.length" @click="onIgnore">忽略选中</el-button>
      <span class="hint">保存前可直接修改；只有点「保存」的条目才会进入素材库</span>
    </div>

    <el-empty v-if="!loading && !items.length" :description="extractId ? '这次提取没有待确认的素材候选' : '没有待确认的素材候选'" :image-size="80" />

    <div v-for="c in pagedItems" :key="c.id" class="cand-card" :class="{ 'is-checked': checked[c.id] }">
      <div class="cand-head">
        <el-checkbox v-model="checked[c.id]" />
        <el-select v-model="c.edit.category" size="small" style="width: 110px">
          <el-option v-for="x in MATERIAL_CATEGORIES" :key="x.code" :label="x.label" :value="x.code" />
        </el-select>
        <el-input v-model="c.edit.title" size="small" class="cand-title" maxlength="100" />
        <el-input v-model="c.edit.subtype" size="small" placeholder="细分类型" style="width: 120px" maxlength="32" />
        <el-tag v-if="c.duplicateOf" type="warning" size="small">库中已有同名素材</el-tag>
        <span class="muted cand-src">{{ c.fileName }}<template v-if="c.payload.chapters?.length"> · {{ c.payload.chapters.slice(0, 3).join('、') }}{{ c.payload.chapters.length > 3 ? ' 等' : '' }}</template></span>
      </div>
      <el-input v-model="c.edit.summary" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="300" placeholder="一句话概括" />
      <el-input
        v-if="c.payload.detail !== undefined"
        v-model="c.edit.detail"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        placeholder="详细描述"
        class="cand-detail"
      />
      <div class="cand-body">
        <AttributeEditor v-model="c.edit.attributes" :category="c.edit.category" class="cand-attrs" />
        <div class="cand-side">
          <el-input-tag v-model="c.edit.tags" size="small" placeholder="标签，回车添加" :max="12" />
          <div v-if="c.payload.excerpt && !c.payload.facts?.length" class="excerpt">“{{ c.payload.excerpt }}”</div>
          <FactList v-if="c.payload.facts?.length" :facts="c.payload.facts" />
        </div>
      </div>
    </div>
    <!-- 每页只渲染少量可编辑卡片：候选可能有数百条，每张卡片含十几个表单组件，全部渲染会明显卡顿 -->
    <el-pagination
      v-if="visibleItems.length > PAGE_SIZE"
      v-model:current-page="page"
      class="pager"
      layout="prev, pager, next, total"
      :total="visibleItems.length"
      :page-size="PAGE_SIZE"
      @current-change="scrollTop"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Close } from '@element-plus/icons-vue'
import AttributeEditor from './AttributeEditor.vue'
import FactList from './FactList.vue'
import { MATERIAL_CATEGORIES, ignoreCandidates, listCandidates, saveCandidates } from '@/api/material'
import { errorMessage } from '@/api/request'

/** 素材候选确认：extractId 为空时显示全部待确认候选 */
const PAGE_SIZE = 20

const props = defineProps({
  extractId: { type: Number, default: null }
})
const emit = defineEmits(['changed'])

const loading = ref(false)
const saving = ref(false)
const items = ref([])
const checked = reactive({})
const filterCategory = ref('')
const page = ref(1)
const rootRef = ref()

const visibleItems = computed(() => items.value.filter((c) => !filterCategory.value || c.edit.category === filterCategory.value))
const pagedItems = computed(() => visibleItems.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
const checkedIds = computed(() => items.value.filter((c) => checked[c.id]).map((c) => c.id))
const allChecked = computed(() => visibleItems.value.length > 0 && visibleItems.value.every((c) => checked[c.id]))
const someChecked = computed(() => visibleItems.value.some((c) => checked[c.id]))

watch(filterCategory, () => (page.value = 1))

function scrollTop() {
  rootRef.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

async function load() {
  loading.value = true
  try {
    const res = await listCandidates({ status: 'PENDING', extractId: props.extractId || undefined })
    if (res.code !== 0) throw new Error(res.message)
    items.value = (res.data || []).map((c) => ({
      ...c,
      edit: {
        category: c.payload.category || c.category,
        title: c.payload.title || c.title,
        subtype: c.payload.subtype || '',
        summary: c.payload.summary || '',
        attributes: { ...(c.payload.attributes || {}) },
        tags: [...(c.payload.tags || [])],
        ...(c.payload.detail !== undefined ? { detail: c.payload.detail || '' } : {})
      }
    }))
    Object.keys(checked).forEach((k) => delete checked[k])
    page.value = Math.min(page.value, Math.max(1, Math.ceil(visibleItems.value.length / PAGE_SIZE)))
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载素材候选失败'))
  } finally {
    loading.value = false
  }
}

/** 全选作用于当前筛选出的全部候选（不只本页） */
function toggleAll(v) {
  visibleItems.value.forEach((c) => (checked[c.id] = v))
}

async function onSave() {
  saving.value = true
  try {
    const payload = items.value.filter((c) => checked[c.id]).map((c) => ({ id: c.id, ...c.edit }))
    const res = await saveCandidates(payload)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(`已保存 ${res.data.length} 条素材`)
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function onIgnore() {
  try {
    const res = await ignoreCandidates(checkedIds.value)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.info(`已忽略 ${res.data} 条`)
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

watch(() => props.extractId, load)
onMounted(load)
defineExpose({ reload: load })
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}
.hint,
.muted {
  font-size: 12px;
  color: #909399;
}
.cand-card {
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
}
.cand-card.is-checked {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.cand-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.cand-title {
  width: 200px;
}
.cand-src {
  margin-left: auto;
}
.cand-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 12px;
  margin-top: 8px;
}
.pager {
  margin-top: 12px;
  justify-content: center;
}
.cand-detail {
  margin-top: 6px;
}
.excerpt {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
}
</style>
