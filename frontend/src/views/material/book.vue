<template>
  <div class="book-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>
            <el-button text :icon="ArrowLeft" @click="router.push('/material/books')">书库</el-button>
            <span class="card-title">《{{ name }}》</span>
            <span class="muted">{{ data?.materials.length || 0 }} 条素材 · {{ data?.workspaces.length || 0 }} 个提取工作区</span>
          </span>
          <span>
            <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
            <el-button type="danger" plain :disabled="!data?.materials.length" @click="clearBook">清空这本书的素材</el-button>
          </span>
        </div>
      </template>

      <el-tabs v-model="tab">
        <!-- 全貌：这本书的全部素材，按分类分组 -->
        <el-tab-pane :label="`全貌（${data?.materials.length || 0}）`" name="all">
          <div class="toolbar">
            <el-radio-group v-model="cat" size="small">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="c in presentCats" :key="c.code" :value="c.code">{{ c.label }}（{{ c.n }}）</el-radio-button>
            </el-radio-group>
            <el-select v-model="ws" size="small" clearable placeholder="来自哪个工作区" style="width: 180px">
              <el-option v-for="w in data?.workspaces || []" :key="w.id" :label="wsName(w)" :value="w.id" />
            </el-select>
            <el-input v-model="keyword" size="small" clearable placeholder="搜索名称 / 概括" style="width: 180px" />
          </div>
          <el-empty v-if="!filtered.length" description="没有符合条件的素材" :image-size="60" />
          <section v-for="g in grouped" :key="g.code" class="cat-group">
            <div class="cat-title">{{ g.label }}（{{ g.items.length }}）</div>
            <div class="mat-grid">
              <div v-for="m in g.items" :key="m.id" class="mat" @click="openMaterial(m.id)">
                <div class="mat-title">
                  {{ m.title }}
                  <el-tag v-if="m.multiVersion" size="small" type="warning" effect="plain">多个版本</el-tag>
                  <el-tag v-if="m.pinned" size="small" effect="plain">保留</el-tag>
                </div>
                <div class="mat-sum">{{ m.summary }}</div>
                <div class="muted">
                  <span v-if="m.subtype">{{ m.subtype }} · </span>
                  <span v-if="tierOf(m)">{{ tierLabel(tierOf(m)) }} · </span>
                  <span v-if="m.workspace">来自「{{ m.workspace }}」</span>
                </div>
              </div>
            </div>
          </section>
        </el-tab-pane>

        <!-- 来源：这本书的提取工作区 -->
        <el-tab-pane :label="`来源（${data?.workspaces.length || 0}）`" name="src">
          <el-table :data="data?.workspaces || []" size="small" empty-text="这本书还没有提取工作区">
            <el-table-column label="工作区" min-width="200">
              <template #default="{ row }">
                <div>{{ wsName(row) }}</div>
                <div class="muted">{{ wsSubtitle(row) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="WS_STATUS[row.status]?.type" size="small">{{ WS_STATUS[row.status]?.label || row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="saved" label="已存进书库" width="100" />
            <el-table-column label="待入库卡片" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.pending" size="small" type="warning">{{ row.pending }}</el-tag>
                <span v-else class="muted">0</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button link type="primary" @click="router.push(`/novel/extract/${row.id}?tab=materials`)">去素材选择</el-button>
                <el-button link @click="router.push(`/novel/extract/${row.id}`)">打开工作区</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 关系：共鸣素材的关系图 -->
        <el-tab-pane :label="`关系（${data?.resonance.length || 0}）`" name="rel">
          <el-empty v-if="!data?.resonance.length" description="这本书还没有共鸣素材：在提取工作区的「卡片整理」里整理共鸣素材并存进素材库" :image-size="60" />
          <div v-else class="rel">
            <aside class="rel-list">
              <div v-for="r in data.resonance" :key="r.id" class="rel-item" :class="{ active: r.id === relId }" @click="relId = r.id">
                <div>{{ r.title }}</div>
                <div class="muted">{{ r.graph?.nodes?.length || 0 }} 个节点</div>
              </div>
            </aside>
            <section class="rel-view">
              <ResonanceView v-if="relData" :data="relData" @pick-card="pickNode" />
            </section>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <MaterialEditor v-model="editor.visible" :material="editor.material" @saved="load" @deleted="load" />
  </div>
</template>

<script setup>
import { computed, onActivated, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { MATERIAL_CATEGORIES, deleteMaterialSource, getBook, getMaterial, tierLabel } from '@/api/material'
import { errorMessage } from '@/api/request'
import MaterialEditor from '@/components/material/MaterialEditor.vue'
import ResonanceView from '@/components/material/ResonanceView.vue'
import { WS_STATUS, wsSubtitle } from '@/components/material/extractWorkspaces'

/** 单本书库：全貌（这本书的全部素材）/ 来源（提取工作区）/ 关系（共鸣素材的关系图） */
const route = useRoute()
const router = useRouter()
const name = ref('')
const data = ref(null)
const loading = ref(false)
const tab = ref('all')
const cat = ref('')
const ws = ref(null)
const keyword = ref('')

const wsName = (w) => w.title || `工作区 #${w.id}`
const tierOf = (m) => Number(m.profile?.tier) || null
const presentCats = computed(() =>
  MATERIAL_CATEGORIES.map((c) => ({ code: c.code, label: c.label, n: (data.value?.materials || []).filter((m) => m.category === c.code).length })).filter(
    (c) => c.n
  )
)
const filtered = computed(() => {
  const kw = keyword.value.trim()
  return (data.value?.materials || []).filter(
    (m) =>
      (!cat.value || m.category === cat.value) &&
      (ws.value == null || m.extractId === ws.value) &&
      (!kw || (m.title || '').includes(kw) || (m.summary || '').includes(kw))
  )
})
const grouped = computed(() =>
  MATERIAL_CATEGORIES.map((c) => ({ code: c.code, label: c.label, items: filtered.value.filter((m) => m.category === c.code) })).filter(
    (g) => g.items.length
  )
)

/* 关系：选中的共鸣素材 */
const relId = ref(null)
const relItem = computed(() => (data.value?.resonance || []).find((r) => r.id === relId.value))
const relData = computed(() => (relItem.value ? { ...relItem.value.graph, summary: relItem.value.summary } : null))
function pickNode(cardId) {
  const node = (relItem.value?.graph?.nodes || []).find((n) => n.cardId === cardId)
  if (node?.materialId) openMaterial(node.materialId)
  else ElMessage.info('这个节点对应的卡片还没存进素材库')
}

async function load() {
  name.value = String(route.query.name || '')
  if (!name.value) return
  loading.value = true
  try {
    const res = await getBook(name.value)
    if (res.code !== 0) throw new Error(res.message)
    data.value = res.data
    if (!data.value.resonance.some((r) => r.id === relId.value)) relId.value = data.value.resonance[0]?.id ?? null
  } catch (e) {
    data.value = null
    ElMessage.error(errorMessage(e, '读取书库失败'))
  } finally {
    loading.value = false
  }
}

const editor = reactive({ visible: false, material: null })
async function openMaterial(id) {
  try {
    const res = await getMaterial(id)
    if (res.code !== 0) throw new Error(res.message)
    editor.material = res.data
    editor.visible = true
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取素材失败'))
  }
}

async function clearBook() {
  try {
    await ElMessageBox.prompt(`删除《${name.value}》书库里的素材（标记为保留的不删），提取工作区和卡片不动。输入书名确认：`, '清空这本书的素材', {
      type: 'warning',
      confirmButtonText: '删除',
      confirmButtonClass: 'el-button--danger',
      inputValidator: (v) => (v || '').trim() === name.value || '书名不对'
    })
  } catch {
    return
  }
  try {
    const res = await deleteMaterialSource(name.value, false)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(`已删除 ${res.data.deleted} 条` + (res.data.kept ? `，保留 ${res.data.kept} 条` : ''))
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

watch(() => route.query.name, () => route.name === 'materialBook' && load())
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
  margin-right: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.cat-group {
  margin-bottom: 16px;
}
.cat-title {
  margin-bottom: 8px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.mat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.mat {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  cursor: pointer;
}
.mat:hover {
  border-color: var(--el-color-primary);
}
.mat-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.mat-sum {
  margin: 4px 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.rel {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 14px;
}
.rel-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
}
.rel-item:hover,
.rel-item.active {
  background: var(--el-fill-color-light);
}
.rel-item.active {
  color: var(--el-color-primary);
}
</style>
