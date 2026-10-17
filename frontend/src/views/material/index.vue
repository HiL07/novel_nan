<template>
  <div class="material-page">
    <el-card class="box-card" shadow="never">
      <el-tabs v-model="tab">
        <!-- ===================== 素材库 ===================== -->
        <el-tab-pane label="素材库" name="library">
          <div class="lib-grid">
            <!-- 分类 -->
            <div class="cat-col">
              <div class="cat-item" :class="{ 'is-active': !category }" @click="setCategory('')">
                <el-icon><Collection /></el-icon><span>全部</span><span class="count">{{ totalCount }}</span>
              </div>
              <div v-for="c in categories" :key="c.code" class="cat-item" :class="{ 'is-active': category === c.code }" @click="setCategory(c.code)">
                <el-icon><component :is="categoryOf(c.code)?.icon || 'Collection'" /></el-icon>
                <span>{{ c.label }}</span><span class="count">{{ c.count }}</span>
              </div>
              <el-button class="new-btn" type="primary" plain :icon="Plus" @click="openEditor(null)">新建素材</el-button>
            </div>

            <div class="main-col">
              <!-- 检索 -->
              <div class="search-bar">
                <el-radio-group v-model="mode" size="small">
                  <el-radio-button value="keyword">关键词检索</el-radio-button>
                  <el-radio-button value="semantic">AI 语义检索</el-radio-button>
                </el-radio-group>
                <template v-if="mode === 'keyword'">
                  <el-input v-model="keyword" placeholder="名称 / 概括 / 详细 / 标签中的关键词" clearable class="search-input" @keyup.enter="search(1)" @clear="search(1)" />
                  <el-select v-model="selectedTags" multiple filterable collapse-tags collapse-tags-tooltip placeholder="按标签筛选" style="width: 240px" @change="search(1)">
                    <el-option v-for="t in tagCloud" :key="t.tag" :label="`${t.tag}（${t.count}）`" :value="t.tag" />
                  </el-select>
                  <el-select v-model="tagMode" style="width: 110px" :disabled="selectedTags.length < 2" @change="search(1)">
                    <el-option label="包含全部" value="all" />
                    <el-option label="包含任一" value="any" />
                  </el-select>
                  <el-button type="primary" :icon="Search" @click="search(1)">检索</el-button>
                </template>
                <template v-else>
                  <el-input
                    v-model="semanticQuery"
                    placeholder="用自然语言描述想要的素材，如：适合废土末世的、群居且怕光的变异生物"
                    clearable
                    class="search-input wide"
                    @keyup.enter="runSemantic"
                  />
                  <el-select v-model="selectedTags" multiple filterable collapse-tags placeholder="限定标签（可选）" style="width: 200px">
                    <el-option v-for="t in tagCloud" :key="t.tag" :label="t.tag" :value="t.tag" />
                  </el-select>
                  <el-button type="primary" :icon="MagicStick" :loading="semanticLoading" :disabled="!semanticQuery.trim()" @click="runSemantic">AI 检索</el-button>
                </template>
              </div>

              <!-- 标签云（关键词模式） -->
              <div v-if="mode === 'keyword' && tagCloud.length" class="tag-cloud">
                <el-check-tag
                  v-for="t in tagCloud.slice(0, 30)"
                  :key="t.tag"
                  :checked="selectedTags.includes(t.tag)"
                  @change="toggleTag(t.tag)"
                >
                  {{ t.tag }} <span class="count">{{ t.count }}</span>
                </el-check-tag>
              </div>

              <!-- AI 语义检索说明 -->
              <div v-if="mode === 'semantic' && semantic" class="semantic-info">
                模型 {{ semantic.model }} 扩展了关键词：{{ [...semantic.expansion.keywords].join('、') }}
                <template v-if="semantic.expansion.tags.length">；标签：{{ semantic.expansion.tags.join('、') }}</template>
                ；从 {{ semantic.considered }} 条候选中找到 {{ semantic.results.length }} 条相关素材
              </div>

              <!-- 结果 -->
              <div v-loading="loading || semanticLoading" class="results">
                <el-empty v-if="!displayList.length" :description="emptyText" :image-size="80" />
                <div v-else class="card-grid">
                  <div v-for="r in displayList" :key="r.material.id" class="mat-card" @click="openEditor(r.material)">
                    <div class="mat-head">
                      <el-tag size="small" effect="plain">{{ categoryOf(r.material.category)?.label }}</el-tag>
                      <span class="mat-title">{{ r.material.title }}</span>
                      <span v-if="r.score != null" class="score" :title="r.reason">{{ r.score }}</span>
                    </div>
                    <div v-if="r.reason" class="reason">匹配理由：{{ r.reason }}</div>
                    <div class="mat-summary">{{ r.material.summary || '（无概括）' }}</div>
                    <div class="mat-attrs">
                      <span v-for="(v, k) in pickAttrs(r.material.attributes)" :key="k"><b>{{ k }}</b>：{{ Array.isArray(v) ? v.join('、') : v }}</span>
                    </div>
                    <div class="mat-foot">
                      <el-tag v-for="t in (r.material.tags || []).slice(0, 5)" :key="t" size="small" type="info">{{ t }}</el-tag>
                      <span class="muted">{{ r.material.subtype }}<template v-if="r.material.useCount"> · 已用 {{ r.material.useCount }} 次</template></span>
                    </div>
                  </div>
                </div>
                <el-pagination
                  v-if="mode === 'keyword' && total > pageSize"
                  class="pager"
                  layout="prev, pager, next, total"
                  :total="total"
                  :page-size="pageSize"
                  :current-page="page"
                  @current-change="search"
                />
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- ===================== 待确认 ===================== -->
        <el-tab-pane name="pending">
          <template #label>
            待确认<el-badge v-if="pending" :value="pending" class="pending-badge" />
          </template>
          <div class="pending-tip">
            AI 在「小说提取」中发现的素材候选。可修改后保存到素材库，或忽略；只有确认保存的才会入库。
            提取时可在「文件管理 → 小说提取」中选择素材类型与关注点。
          </div>
          <CandidateReview ref="reviewRef" @changed="onCandidatesChanged" />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <MaterialEditor v-model="editor.visible" :material="editor.material" :default-category="category || 'world'" @saved="refreshAll" @deleted="refreshAll" />
  </div>
</template>

<script setup>
import { computed, onActivated, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Collection, MagicStick, Plus, Search } from '@element-plus/icons-vue'
import CandidateReview from '@/components/material/CandidateReview.vue'
import MaterialEditor from '@/components/material/MaterialEditor.vue'
import {
  categoryOf, getMaterialCategories, getMaterialTags, pendingCandidateCount, searchMaterials, semanticSearch
} from '@/api/material'
import { errorMessage } from '@/api/request'

const tab = ref('library')
const categories = ref([])
const category = ref('')
const tagCloud = ref([])
const pending = ref(0)

const mode = ref('keyword')
const keyword = ref('')
const selectedTags = ref([])
const tagMode = ref('all')
const page = ref(1)
const pageSize = 24
const total = ref(0)
const records = ref([])
const loading = ref(false)

const semanticQuery = ref('')
const semantic = ref(null)
const semanticLoading = ref(false)

const reviewRef = ref()
const editor = reactive({ visible: false, material: null })

const totalCount = computed(() => categories.value.reduce((s, c) => s + c.count, 0))
const displayList = computed(() =>
  mode.value === 'semantic' ? semantic.value?.results || [] : records.value.map((m) => ({ material: m, score: null, reason: '' }))
)
const emptyText = computed(() =>
  mode.value === 'semantic' ? (semantic.value ? '没有找到相关素材' : '输入需求后点击「AI 检索」') : totalCount.value ? '没有符合条件的素材' : '素材库还是空的：在「小说提取」中开启素材提取，或手动新建'
)

const pickAttrs = (attrs) => Object.fromEntries(Object.entries(attrs || {}).slice(0, 3))

async function call(promise, fallback) {
  const res = await promise
  if (res.code !== 0) throw new Error(res.message || fallback)
  return res.data
}

async function loadMeta() {
  try {
    const [c, t, p] = await Promise.all([
      call(getMaterialCategories(), '加载分类失败'), call(getMaterialTags(category.value || undefined), '加载标签失败'),
      call(pendingCandidateCount(), '加载候选失败')
    ])
    categories.value = c
    tagCloud.value = t
    pending.value = p
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载素材库失败'))
  }
}

async function search(p = 1) {
  page.value = p
  loading.value = true
  try {
    const data = await call(searchMaterials({
      category: category.value || undefined, tags: selectedTags.value, tagMode: tagMode.value,
      keyword: keyword.value.trim() || undefined, page: p, size: pageSize
    }), '检索失败')
    records.value = data.records
    total.value = data.total
  } catch (e) {
    ElMessage.error(errorMessage(e, '检索失败'))
  } finally {
    loading.value = false
  }
}

async function runSemantic() {
  if (!semanticQuery.value.trim()) return
  semanticLoading.value = true
  try {
    semantic.value = await call(semanticSearch({
      query: semanticQuery.value.trim(), category: category.value || undefined, tags: selectedTags.value, limit: 20
    }), 'AI 检索失败')
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, 'AI 检索失败'), duration: 6000 })
  } finally {
    semanticLoading.value = false
  }
}

function setCategory(code) {
  category.value = code
  selectedTags.value = []
  getMaterialTags(code || undefined).then((r) => r.code === 0 && (tagCloud.value = r.data))
  if (mode.value === 'keyword') search(1)
  else if (semantic.value) runSemantic()
}

function toggleTag(tag) {
  const i = selectedTags.value.indexOf(tag)
  if (i >= 0) selectedTags.value.splice(i, 1)
  else selectedTags.value.push(tag)
  search(1)
}

function openEditor(m) {
  Object.assign(editor, { visible: true, material: m })
}

async function refreshAll() {
  await loadMeta()
  if (mode.value === 'keyword') await search(page.value)
  else semantic.value = null
}

async function onCandidatesChanged() {
  await refreshAll()
}

watch(mode, (m) => {
  if (m === 'keyword') search(1)
})

onActivated(async () => {
  await loadMeta()
  if (mode.value === 'keyword') search(page.value)
  reviewRef.value?.reload()
})
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.lib-grid {
  display: grid;
  grid-template-columns: 170px minmax(0, 1fr);
  gap: 18px;
}
.cat-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 2px;
  font-size: 14px;
  border-radius: 6px;
  cursor: pointer;
}
.cat-item:hover {
  background: #f5f7fa;
}
.cat-item.is-active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}
.cat-item span:nth-child(2) {
  flex: 1;
}
.count {
  font-size: 12px;
  font-weight: normal;
  color: #909399;
}
.new-btn {
  width: 100%;
  margin-top: 10px;
}
.search-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.search-input {
  width: 260px;
}
.search-input.wide {
  width: 420px;
}
.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.semantic-info {
  margin-top: 10px;
  font-size: 12px;
  color: #606266;
}
.results {
  min-height: 200px;
  margin-top: 14px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.mat-card {
  padding: 12px 14px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.mat-card:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
}
.mat-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mat-title {
  flex: 1;
  font-weight: 600;
  color: #303133;
}
.score {
  min-width: 32px;
  padding: 1px 6px;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
  color: #fff;
  background: var(--el-color-success);
  border-radius: 10px;
}
.reason {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-success-dark-2);
}
.mat-summary {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
.mat-attrs {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 6px;
  font-size: 12px;
  color: #606266;
}
.mat-foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}
.muted {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}
.pager {
  margin-top: 14px;
  justify-content: center;
}
.pending-tip {
  margin-bottom: 12px;
  font-size: 13px;
  color: #606266;
}
.pending-badge {
  margin-left: 4px;
}
</style>
