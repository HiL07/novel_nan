<template>
  <div class="books-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">书库</span>
          <div>
            <el-input v-model="keyword" size="small" clearable placeholder="按书名搜索" style="width: 200px; margin-right: 8px" />
            <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
          </div>
        </div>
      </template>
      <p class="muted intro">
        一本书一个素材库工作区（同名小说算一本）：这本书各个提取工作区存进来的素材都在这里，是这本书共有的。
        卡片入库前会先和这里已有的素材比对，避免同一个东西存两份。
      </p>
      <el-empty v-if="!shown.length && !loading" description="还没有书：先在「小说提取」里提取，再在「素材选择」里存进素材库" />
      <div v-else class="novel-grid">
        <div v-for="b in shown" :key="b.book" class="novel-card" @click="open(b.book)">
          <div class="novel-title" :title="b.book">《{{ b.book }}》</div>
          <div class="novel-meta">
            <span><b>{{ b.total }}</b> 条素材<template v-if="b.pinned"> · {{ b.pinned }} 条保留</template></span>
            <span>{{ b.workspaces }} 个提取工作区</span>
          </div>
          <div class="cats">
            <el-tag v-for="c in catsOf(b)" :key="c.code" size="small" effect="plain">{{ c.label }} {{ c.n }}</el-tag>
            <span v-if="!b.total" class="muted">还没有素材</span>
          </div>
          <div class="novel-foot">
            <span class="muted">更新于 {{ String(b.updateTime || '').slice(0, 16) }}</span>
            <el-tag v-if="b.pending" size="small" type="warning">{{ b.pending }} 张卡片待入库</el-tag>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onActivated, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { MATERIAL_CATEGORIES, listBooks } from '@/api/material'
import { errorMessage } from '@/api/request'

/** 书库列表：每本书一张卡（素材数、分类小计、来源工作区、待入库卡片），点进去是书库详情（views/material/book.vue） */
const router = useRouter()
const books = ref([])
const loading = ref(false)
const keyword = ref('')
const shown = computed(() => {
  const kw = keyword.value.trim()
  return books.value.filter((b) => !kw || b.book.includes(kw))
})
const catsOf = (b) =>
  MATERIAL_CATEGORIES.map((c) => ({ code: c.code, label: c.label, n: b.byCategory?.[c.code] || 0 })).filter((c) => c.n)

async function load() {
  loading.value = true
  try {
    const res = await listBooks()
    if (res.code !== 0) throw new Error(res.message)
    books.value = res.data || []
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取书库失败'))
  } finally {
    loading.value = false
  }
}

function open(book) {
  router.push({ path: '/material/book', query: { name: book } })
}

onActivated(load)
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
.intro {
  margin: 0 0 14px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.novel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.novel-card {
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.novel-card:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
}
.novel-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.novel-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.cats {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
  min-height: 22px;
}
.novel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
</style>
