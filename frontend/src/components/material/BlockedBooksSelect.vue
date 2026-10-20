<template>
  <el-select
    :model-value="modelValue"
    multiple
    filterable
    collapse-tags
    collapse-tags-tooltip
    clearable
    :placeholder="placeholder"
    :loading="loading"
    class="blocked-books"
    @visible-change="(v) => v && load()"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <el-option v-for="s in books" :key="s.book" :label="s.book" :value="s.book">
      <span>《{{ s.book }}》</span>
      <span class="meta">{{ s.count }} 条<template v-if="s.pinned">，保留 {{ s.pinned }}</template></span>
    </el-option>
    <template #empty>
      <div class="empty">素材库里还没有来自小说的素材</div>
    </template>
  </el-select>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getMaterialSources } from '@/api/material'

/** 选择要屏蔽的来源书（v-model = 书名数组）。被屏蔽的书里「保留」的素材仍会使用 */
defineProps({
  modelValue: { type: Array, default: () => [] },
  placeholder: { type: String, default: '屏蔽来源书（不用这些书的素材）' }
})
const emit = defineEmits(['update:modelValue'])

const sources = ref([])
const loading = ref(false)
const books = computed(() => sources.value.filter((s) => s.book && s.count))

async function load() {
  loading.value = true
  try {
    const res = await getMaterialSources()
    if (res.code === 0) sources.value = res.data || []
  } catch {
    // 下拉打开时再试
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.blocked-books {
  width: 100%;
}
.meta {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}
.empty {
  padding: 10px;
  font-size: 12px;
  color: #909399;
  text-align: center;
}
</style>
