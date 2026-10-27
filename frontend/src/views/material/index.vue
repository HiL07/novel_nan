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

              <!-- 来源书：按书筛选 / 按书删除 -->
              <div class="side-title">来源书</div>
              <div class="cat-item" :class="{ 'is-active': !sourceBook && !pinnedOnly }" @click="setSource('')">
                <el-icon><Reading /></el-icon><span>全部来源</span>
              </div>
              <div class="cat-item" :class="{ 'is-active': pinnedOnly }" @click="setPinnedOnly">
                <el-icon><StarFilled /></el-icon><span>保留的</span><span class="count">{{ pinnedCount }}</span>
              </div>
              <div
                v-for="s in sources"
                :key="s.book ?? MANUAL_BOOK"
                class="cat-item source-item"
                :class="{ 'is-active': sourceBook === (s.book ?? MANUAL_BOOK) }"
                :title="s.book ? `《${s.book}》：${s.count} 条，保留 ${s.pinned} 条${s.pending ? `，待确认候选 ${s.pending} 条` : ''}` : '手动添加的素材'"
                @click="setSource(s.book ?? MANUAL_BOOK)"
              >
                <el-icon><Notebook /></el-icon>
                <span class="source-name">{{ s.book ? `《${s.book}》` : '手动添加' }}</span>
                <span class="count">{{ s.count }}</span>
                <el-icon v-if="s.book" class="source-del" title="按来源书删除" @click.stop="openSourceDelete(s)"><Delete /></el-icon>
              </div>
            </div>

            <div class="main-col">
              <!-- 检索 -->
              <div class="search-bar">
                <el-radio-group v-model="mode" size="small">
                  <el-radio-button value="keyword">关键词检索</el-radio-button>
                  <el-radio-button value="semantic">AI 语义检索</el-radio-button>
                  <el-radio-button value="vector">本地检索</el-radio-button>
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
                <template v-else-if="mode === 'vector'">
                  <el-select
                    v-model="vectorModelId"
                    placeholder="默认向量模型"
                    clearable
                    style="width: 190px"
                    :no-data-text="embeddingModelsError || '没有向量模型：去「本地模型」下载 bge-small-zh-v1.5'"
                    @visible-change="(v) => v && loadEmbeddingModels()"
                    @change="onVectorModel"
                  >
                    <el-option v-for="m in embeddingModels" :key="m.id" :label="m.name" :value="m.id" :disabled="!m.exists" />
                  </el-select>
                  <el-input
                    v-model="vectorQuery"
                    placeholder="描述想要的素材，本地向量模型按语义相似度排序（不用大模型、不花 token）"
                    clearable
                    class="search-input wide"
                    @keyup.enter="runVector"
                  />
                  <el-select v-model="selectedTags" multiple filterable collapse-tags placeholder="限定标签（可选）" style="width: 200px">
                    <el-option v-for="t in tagCloud" :key="t.tag" :label="t.tag" :value="t.tag" />
                  </el-select>
                  <el-select v-model="vectorMode" style="width: 150px" title="对比不同检索方式的效果">
                    <el-option label="混合 + 重排（推荐）" value="hybrid+rerank" />
                    <el-option label="混合（向量 + 关键词）" value="hybrid" />
                    <el-option label="只用向量" value="vector" />
                  </el-select>
                  <el-button type="primary" :icon="Search" :loading="vectorLoading" :disabled="!vectorQuery.trim()" @click="runVector">检索</el-button>
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

              <!-- 向量检索：向量化进度 + 本次检索说明 -->
              <div v-if="mode === 'vector'" class="semantic-info">
                <div class="vector-index">
                  <template v-if="vectorIdx">
                    已向量化 <b>{{ vectorIdx.cached }}</b> / {{ vectorIdx.total }} 条素材（{{ vectorIdx.model }}，{{ vectorIdx.device === 'cuda' ? 'GPU' : 'CPU' }}）
                    <template v-if="vectorIdx.encoded">，本次新向量化 {{ vectorIdx.encoded }} 条，用时 {{ vectorIdx.ms }} ms</template>
                  </template>
                  <span v-else-if="vectorIdxError" class="danger">{{ vectorIdxError }}</span>
                  <span v-else>正在统计向量化情况（首次会加载向量模型）…</span>
                  <el-button size="small" :loading="vectorIdxLoading" :disabled="!!vectorIdx && !vectorIdx.pending" @click="runVectorIndex(true)">
                    {{ vectorIdx && !vectorIdx.pending ? '已全部向量化' : '全部向量化' }}
                  </el-button>
                  <span class="muted-tip">没向量化的素材在检索时也会顺便向量化；修改过的素材会重新向量化</span>
                </div>
                <div v-if="vector">
                  {{ vector.model }}（{{ vector.device === 'cuda' ? 'GPU' : 'CPU' }}）{{ vector.mode === 'hybrid' ? '+ 关键词' : '' }}比较了 {{ vector.considered }} 条素材
                  <template v-if="vector.total > vector.considered">（共 {{ vector.total }} 条，只取使用最多的 {{ vector.considered }} 条）</template>
                  <template v-if="vector.encoded">，新向量化 {{ vector.encoded }} 条</template>，用时 {{ vector.ms }} ms
                  <template v-if="vector.queryTokens?.length">；关键词：{{ vector.queryTokens.join(' / ') }}</template>。
                  <template v-if="vector.reranked">已用 {{ vector.rerankModel }} 重排（{{ vector.rerankMs }} ms），分数 = 相关度，30 以上一般算相关。</template>
                  <template v-else>没有重排{{ vector.rerankSkipped ? `（${vector.rerankSkipped}）` : '' }}，分数 = 相似度，只看相对高低。</template>
                </div>
              </div>

              <!-- 结果 -->
              <div v-loading="loading || semanticLoading || vectorLoading" class="results">
                <el-empty v-if="!displayList.length" :description="emptyText" :image-size="80" />
                <div v-else class="card-grid">
                  <div v-for="r in displayList" :key="r.material.id" class="mat-card" @click="openResult(r)">
                    <div class="mat-head">
                      <el-tag size="small" effect="plain">{{ categoryOf(r.material.category)?.label }}</el-tag>
                      <span class="mat-title">{{ r.material.title }}</span>
                      <span v-if="r.score != null" class="score" :title="r.reason || rankTip(r)">{{ r.score }}</span>
                      <el-icon
                        class="pin"
                        :class="{ 'is-pinned': r.material.pinned }"
                        :title="r.material.pinned ? '已保留（点击取消）：按书删除 / 屏蔽来源书都不影响它' : '保留：按书删除 / 屏蔽来源书时不受影响'"
                        @click.stop="togglePin(r.material)"
                      >
                        <StarFilled v-if="r.material.pinned" /><Star v-else />
                      </el-icon>
                    </div>
                    <div v-if="r.reason" class="reason">匹配理由：{{ r.reason }}</div>
                    <div class="mat-summary">{{ r.material.summary || '（无概括）' }}</div>
                    <div class="mat-attrs">
                      <span v-for="(v, k) in pickAttrs(r.material.attributes)" :key="k"><b>{{ k }}</b>：{{ Array.isArray(v) ? v.join('、') : v }}</span>
                    </div>
                    <div class="mat-foot">
                      <el-tag v-for="t in (r.material.tags || []).slice(0, 5)" :key="t" size="small" type="info">{{ t }}</el-tag>
                      <span class="muted">
                        {{ r.material.sourceBook ? `《${r.material.sourceBook}》` : '手动' }}
                        <template v-if="r.material.subtype"> · {{ r.material.subtype }}</template>
                        <template v-if="r.material.useCount"> · 已用 {{ r.material.useCount }} 次</template>
                      </span>
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
        <!-- lazy：首次切到「待确认」才渲染候选列表，进入素材库页面不必等它 -->
        <el-tab-pane name="pending" lazy>
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

    <el-dialog v-model="sourceDel.visible" title="按来源书删除素材" width="460px">
      <p>
        删除来自《{{ sourceDel.source?.book }}》的素材：共 {{ sourceDel.source?.count }} 条，
        其中<b>保留的 {{ sourceDel.source?.pinned || 0 }} 条不会删除</b>，将删除
        <b class="danger">{{ (sourceDel.source?.count || 0) - (sourceDel.source?.pinned || 0) }}</b> 条。
      </p>
      <el-checkbox v-if="sourceDel.source?.pending" v-model="sourceDel.withCandidates">
        同时忽略这本书的 {{ sourceDel.source.pending }} 条待确认候选
      </el-checkbox>
      <p class="muted-tip">已应用到工作区设定的内容是复制过去的，不受影响。删除后无法恢复。</p>
      <template #footer>
        <el-button @click="sourceDel.visible = false">取消</el-button>
        <el-button type="danger" :loading="sourceDel.loading" @click="doSourceDelete">删除</el-button>
      </template>
    </el-dialog>

    <MaterialEditor v-model="editor.visible" :material="editor.material" :default-category="category || 'world'" @saved="refreshAll" @deleted="refreshAll" />
  </div>
</template>

<script setup>
import { computed, onActivated, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Collection, Delete, MagicStick, Notebook, Plus, Reading, Search, Star, StarFilled } from '@element-plus/icons-vue'
import CandidateReview from '@/components/material/CandidateReview.vue'
import MaterialEditor from '@/components/material/MaterialEditor.vue'
import {
  MANUAL_BOOK, categoryOf, deleteMaterialSource, getMaterialCategories, getMaterialSources, getMaterialTags,
  getVectorModelId, pendingCandidateCount, pinMaterial, searchMaterials, semanticSearch, setVectorModelId, vectorFeedback,
  vectorIndex, vectorSearch
} from '@/api/material'
import { isEmbeddingModel, listModels } from '@/api/localModel'
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

// 向量检索：本地 embedding 模型（python-service 里 task = embedding 的模型；空 = 服务端默认）
const vectorQuery = ref('')
const vector = ref(null)
const vectorLoading = ref(false)
const vectorModelId = ref(getVectorModelId())
const embeddingModels = ref([])
const embeddingModelsError = ref('')
const vectorIdx = ref(null)
const vectorIdxError = ref('')
const vectorIdxLoading = ref(false)
const vectorMode = ref('hybrid+rerank')
const rankTip = (r) => (r.similarity != null ? `相似度 ${r.similarity}` : '') + (r.vecRank ? ` · 向量第 ${r.vecRank}` : '') + (r.lexRank ? ` · 关键词第 ${r.lexRank}` : '')

const reviewRef = ref()
const editor = reactive({ visible: false, material: null })
const sources = ref([])
const sourceBook = ref('')
const pinnedOnly = ref(false)
const sourceDel = reactive({ visible: false, source: null, withCandidates: true, loading: false })
const pinnedCount = computed(() => sources.value.reduce((s, x) => s + (x.pinned || 0), 0))

const totalCount = computed(() => categories.value.reduce((s, c) => s + c.count, 0))
const displayList = computed(() => {
  if (mode.value === 'semantic') return semantic.value?.results || []
  if (mode.value === 'vector') return vector.value?.results || []
  return records.value.map((m) => ({ material: m, score: null, reason: '' }))
})
const emptyText = computed(() => {
  if (mode.value === 'semantic') return semantic.value ? '没有找到相关素材' : '输入需求后点击「AI 检索」'
  if (mode.value === 'vector') return vector.value ? '没有找到相关素材' : '输入需求后点击「向量检索」'
  return totalCount.value ? '没有符合条件的素材' : '素材库还是空的：在「小说提取」中开启素材提取，或手动新建'
})

const pickAttrs = (attrs) => Object.fromEntries(Object.entries(attrs || {}).slice(0, 3))

async function call(promise, fallback) {
  const res = await promise
  if (res.code !== 0) throw new Error(res.message || fallback)
  return res.data
}

async function loadMeta() {
  try {
    const [c, t, p, s] = await Promise.all([
      call(getMaterialCategories(), '加载分类失败'), call(getMaterialTags(category.value || undefined), '加载标签失败'),
      call(pendingCandidateCount(), '加载候选失败'), call(getMaterialSources(), '加载来源失败')
    ])
    categories.value = c
    tagCloud.value = t
    pending.value = p
    sources.value = s.filter((x) => x.count)
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
      keyword: keyword.value.trim() || undefined, sourceBook: sourceBook.value || undefined,
      pinned: pinnedOnly.value || undefined, page: p, size: pageSize
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

async function loadEmbeddingModels() {
  try {
    const list = await call(listModels(), '加载向量模型失败')
    embeddingModels.value = list.filter(isEmbeddingModel)
    embeddingModelsError.value = ''
  } catch (e) {
    embeddingModels.value = []
    embeddingModelsError.value = 'AI 服务不可达：' + errorMessage(e, '加载向量模型失败')
  }
}

function onVectorModel(id) {
  setVectorModelId(id)
  vector.value = null
  runVectorIndex(false)
}

/** encode=false：统计全部素材已向量化多少；true：把没向量化的全部向量化 */
async function runVectorIndex(encode) {
  vectorIdxLoading.value = encode
  vectorIdxError.value = ''
  if (!encode) vectorIdx.value = null
  try {
    const data = await call(vectorIndex(encode), '素材向量化失败')
    vectorIdx.value = { ...data, cached: data.cached + (data.encoded || 0) }
    if (encode) ElMessage.success(`已向量化 ${data.encoded} 条素材，用时 ${(data.ms / 1000).toFixed(1)} 秒`)
  } catch (e) {
    vectorIdxError.value = errorMessage(e, '素材向量化失败')
  } finally {
    vectorIdxLoading.value = false
  }
}

async function runVector() {
  const query = vectorQuery.value.trim()
  if (!query) return
  vectorLoading.value = true
  try {
    vector.value = {
      ...(await call(vectorSearch({
        query, category: category.value || undefined, tags: selectedTags.value, limit: 30,
        mode: vectorMode.value === 'vector' ? 'vector' : 'hybrid', rerank: vectorMode.value === 'hybrid+rerank'
      }), '向量检索失败')),
      query
    }
    if (vector.value.encoded && vectorIdx.value) runVectorIndex(false)
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '向量检索失败'), duration: 6000 })
  } finally {
    vectorLoading.value = false
  }
}

function openResult(r) {
  if (mode.value === 'vector' && vector.value) {
    // 「这条需求 → 点开看的素材」，以后微调向量模型用
    vectorFeedback({ query: vector.value.query, modelId: vector.value.modelId || '', context: '素材库页·查看',
      shownIds: vector.value.results.map((x) => x.material.id), pickedIds: [r.material.id] })
  }
  openEditor(r.material)
}

function setCategory(code) {
  category.value = code
  selectedTags.value = []
  getMaterialTags(code || undefined).then((r) => r.code === 0 && (tagCloud.value = r.data))
  if (mode.value === 'keyword') search(1)
  else if (mode.value === 'semantic' && semantic.value) runSemantic()
  else if (mode.value === 'vector' && vector.value) runVector()
}

function setSource(book) {
  sourceBook.value = book
  pinnedOnly.value = false
  mode.value = 'keyword'
  search(1)
}

function setPinnedOnly() {
  sourceBook.value = ''
  pinnedOnly.value = true
  mode.value = 'keyword'
  search(1)
}

async function togglePin(m) {
  try {
    const data = await call(pinMaterial(m.id, !m.pinned), '操作失败')
    m.pinned = data.pinned
    ElMessage.success(m.pinned ? `已保留「${m.title}」：按书删除 / 屏蔽来源书都不影响它` : `已取消保留「${m.title}」`)
    getMaterialSources().then((r) => r.code === 0 && (sources.value = r.data.filter((x) => x.count)))
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

function openSourceDelete(s) {
  Object.assign(sourceDel, { visible: true, source: s, withCandidates: true, loading: false })
}

async function doSourceDelete() {
  sourceDel.loading = true
  try {
    const book = sourceDel.source.book
    const data = await call(deleteMaterialSource(book, sourceDel.withCandidates), '删除失败')
    ElMessage.success(`已删除《${book}》的 ${data.deleted} 条素材` + (data.kept ? `，保留 ${data.kept} 条` : '') +
      (data.candidatesIgnored ? `，忽略候选 ${data.candidatesIgnored} 条` : ''))
    sourceDel.visible = false
    if (sourceBook.value === book && !data.kept) sourceBook.value = ''
    await refreshAll()
    reviewRef.value?.reload()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  } finally {
    sourceDel.loading = false
  }
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
  else if (mode.value === 'vector') {
    runVectorIndex(false)
    if (vector.value) await runVector()
  } else semantic.value = null
}

async function onCandidatesChanged() {
  await refreshAll()
}

watch(mode, (m) => {
  if (m === 'keyword') search(1)
  if (m === 'vector') {
    loadEmbeddingModels()
    if (!vectorIdx.value) runVectorIndex(false)
  }
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
.side-title {
  margin: 18px 0 6px;
  padding-left: 10px;
  font-size: 12px;
  color: #909399;
}
.source-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-del {
  display: none;
  color: var(--el-color-danger);
}
.source-item:hover .source-del {
  display: inline-flex;
}
.source-item:hover .count {
  display: none;
}
.pin {
  font-size: 16px;
  color: #c0c4cc;
  cursor: pointer;
}
.pin:hover,
.pin.is-pinned {
  color: var(--el-color-warning);
}
.danger {
  color: var(--el-color-danger);
}
.muted-tip {
  font-size: 12px;
  color: #909399;
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
.vector-index {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.vector-index .danger {
  color: var(--el-color-danger);
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
