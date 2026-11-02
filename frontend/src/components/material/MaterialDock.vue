<template>
  <!-- 书房「设定」页中间右半边的素材库：跟着当前设定分类列出素材，关键词 / 语义检索，一键加进设定（不用打开抽屉） -->
  <aside class="material-dock" :class="{ 'is-folded': folded }">
    <!-- 收起：一条竖排的「素材库」 -->
    <button v-if="folded" class="dock-strip" type="button" title="展开素材库" @click="setFolded(false)">
      <el-icon><ArrowLeft /></el-icon>
      <span class="strip-text">素材库</span>
    </button>

    <template v-else>
      <div class="dock-head">
        <span class="dock-title">素材库</span>
        <el-select v-model="cat" size="small" class="cat-select" placeholder="全部分类" clearable @change="onCatPicked">
          <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
        </el-select>
        <span class="dock-total">{{ mode === 'keyword' ? `${total} 条` : vector ? `${rows.length} 条` : '' }}</span>
        <button class="dock-fold" type="button" title="收起素材库" @click="setFolded(true)">
          <el-icon><ArrowRight /></el-icon>
        </button>
      </div>

      <div class="dock-search">
        <el-input
          v-model="query"
          size="small"
          clearable
          :placeholder="mode === 'keyword' ? '关键词：名称 / 概括 / 标签' : '描述想要的素材，本地语义检索'"
          @keyup.enter="runSearch"
          @clear="runSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-radio-group v-model="mode" size="small" @change="runSearch">
          <el-radio-button value="keyword">关键词</el-radio-button>
          <el-radio-button value="vector">语义</el-radio-button>
        </el-radio-group>
      </div>
      <div class="dock-tools">
        <el-button size="small" :icon="MagicStick" :disabled="!contextQuery" :loading="loading && mode === 'vector'" @click="findRelated"
                   title="用当前分类已填的内容做本地语义检索（向量 + 重排，不用大模型、不花 token）">
          按当前设定找相关
        </el-button>
        <span v-if="blocked.length" class="muted" :title="blocked.map((b) => `《${b}》`).join('')">已屏蔽 {{ blocked.length }} 本书</span>
      </div>
      <div v-if="mode === 'vector' && vector" class="dock-info muted">
        {{ vector.reranked ? `按相关度排序，${RERANK_MIN} 分以上一般算相关` : '没有重排，分数只看相对高低' }} · {{ vector.ms }} ms
      </div>

      <div v-loading="loading" class="dock-list">
        <el-empty v-if="!rows.length && !loading" :image-size="60" :description="emptyText" />
        <div
          v-for="r in rows"
          :key="r.material.id"
          class="m-card"
          :class="{ 'is-open': openId === r.material.id }"
        >
          <div class="m-head" @click="toggle(r.material.id)">
            <!-- 选了分类时不重复显示分类 -->
            <span v-if="!cat" class="m-cat">{{ categoryOf(r.material.category)?.label }}</span>
            <span class="m-title">{{ r.material.title }}</span>
            <span v-if="r.score != null" class="m-score" :class="{ weak: vector?.reranked && r.score < RERANK_MIN }">{{ r.score }}</span>
          </div>
          <div class="m-meta" @click="toggle(r.material.id)">
            <span v-if="r.material.subtype">{{ r.material.subtype }}</span>
            <span>{{ r.material.sourceBook ? `《${r.material.sourceBook}》` : '手动添加' }}</span>
            <el-tag v-if="usedIds.has(r.material.id)" size="small" type="success" effect="plain">已用</el-tag>
            <el-tag v-if="isMultiVersion(r.material)" size="small" type="success">{{ r.material.source.variants.length }} 种写法</el-tag>
            <el-tag v-if="r.matchedLabel" size="small" type="warning">命中：{{ r.matchedLabel }}</el-tag>
            <el-tag v-if="r.fit === 'far'" size="small" type="danger" effect="plain" title="远超主角现在的量级：只适合当传说 / 背景 / 伏笔">远景</el-tag>
            <el-tag v-else-if="tierOf(r.material)" size="small" type="info" effect="plain" :title="tierLabel(tierOf(r.material))">量级 {{ tierOf(r.material) }}</el-tag>
          </div>
          <div class="m-summary" :class="{ clamp: openId !== r.material.id }" @click="toggle(r.material.id)">{{ r.material.summary }}</div>

          <!-- 展开：属性 / 详细 / 加到哪 / 多版本用法 -->
          <template v-if="openId === r.material.id">
            <div v-if="attrLines(r.material).length" class="m-attrs">
              <div v-for="a in attrLines(r.material)" :key="a.k"><span class="m-attr-k">{{ a.k }}</span>{{ a.v }}</div>
            </div>
            <div v-if="r.material.detail" class="m-detail">{{ r.material.detail }}</div>
            <div v-if="isMultiVersion(r.material)" class="m-versions">
              <span class="muted">用法：</span>
              <el-radio-group v-model="variants[r.material.id]" size="small">
                <el-radio-button value="auto" title="各版本都写进设定，自己挑">各版本都列出</el-radio-button>
                <el-radio-button v-for="(v, i) in r.material.source.variants" :key="v.id" :value="String(v.id)" :title="v.note || v.title">
                  只用{{ MARKS[i] }}{{ v.label || v.title }}
                </el-radio-button>
              </el-radio-group>
            </div>
            <div class="m-target muted">将加到：{{ describeTarget(r.material, categories) }}</div>
          </template>

          <div class="m-foot">
            <span class="m-tags">
              <span v-for="t in (r.material.tags || []).slice(0, 4)" :key="t" class="m-tag">{{ t }}</span>
            </span>
            <el-button size="small" type="primary" plain :loading="applying === r.material.id" @click="add(r)">加入设定</el-button>
          </div>
        </div>
        <div v-if="mode === 'keyword' && rows.length < total" class="dock-more">
          <el-button size="small" link type="primary" :loading="loading" @click="loadMore">加载更多（还有 {{ total - rows.length }} 条）</el-button>
        </div>
      </div>
    </template>
  </aside>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, MagicStick, Search } from '@element-plus/icons-vue'
import { MATERIAL_CATEGORIES, categoryOf, isMultiVersion, searchMaterials, tierLabel, tierOf, vectorSearch } from '@/api/material'
import { useBlockedBooks } from '@/components/material/blockedBooks'
import { describeTarget } from '@/novel-options/materialApply'
import { errorMessage } from '@/api/request'

const props = defineProps({
  novelId: { type: String, default: '' },
  /** 当前设定分类对应的素材分类（world / character / monster …；空 = 全部） */
  category: { type: String, default: '' },
  /** 设定的分类（预览「将加到」哪里） */
  categories: { type: Array, default: () => [] },
  /** 「按当前设定找相关」的检索文本 */
  contextQuery: { type: String, default: '' },
  /** 已经加进设定的素材 id */
  usedIds: { type: Object, default: () => new Set() },
  /** (list) => Promise：把素材加进设定（SettingsEditor 的 applyMaterials） */
  apply: { type: Function, required: true }
})

const MARKS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫'
/** 重排后的相关度达到这个分才算相关（与 Java MaterialService.RERANK_MIN_SCORE 一致） */
const RERANK_MIN = 30
const PAGE = 20

const blocked = useBlockedBooks(props.novelId)

/* ---- 收起 / 展开：记在本机；窗口太窄时默认收起 ---- */
const FOLD_KEY = 'nan_novel.study.dockFolded'
const folded = ref(false)
try {
  const saved = localStorage.getItem(FOLD_KEY)
  folded.value = saved === null ? window.innerWidth < 1280 : saved === '1'
} catch {
  folded.value = window.innerWidth < 1280
}
function setFolded(v) {
  folded.value = v
  try {
    localStorage.setItem(FOLD_KEY, v ? '1' : '0')
  } catch {
    // 存不了只是下次不记得
  }
  if (!v && !rows.value.length) runSearch()
}

/* ---- 检索 ---- */
const cat = ref(props.category)
const mode = ref('keyword')
const query = ref('')
const loading = ref(false)
const records = ref([])   // 关键词结果（素材）
const total = ref(0)
const page = ref(1)
const vector = ref(null)  // 语义结果 {results, reranked, ms}
const rows = computed(() => (mode.value === 'vector'
  ? vector.value?.results || []
  : records.value.map((m) => ({ material: m }))))
const emptyText = computed(() => (mode.value === 'vector' && !vector.value ? '输入描述后回车，或点「按当前设定找相关」' : '没有找到素材'))

// 设定换了分类：素材分类跟着换（作者手动选过的也重置），重新列一遍
watch(() => props.category, (c) => {
  cat.value = c
  if (mode.value === 'vector' && !query.value.trim()) vector.value = null
  if (!folded.value) runSearch()
})
watch(blocked, () => !folded.value && runSearch(), { deep: true })

function onCatPicked() {
  runSearch()
}

async function runSearch() {
  if (mode.value === 'vector') {
    if (query.value.trim()) await runVector(query.value.trim())
    else vector.value = null
    return
  }
  page.value = 1
  await runKeyword(false)
}

async function runKeyword(append) {
  loading.value = true
  try {
    const res = await searchMaterials({
      category: cat.value || undefined, keyword: query.value.trim() || undefined,
      excludeBooks: blocked.value, page: page.value, size: PAGE
    })
    if (res.code !== 0) throw new Error(res.message)
    records.value = append ? [...records.value, ...res.data.records] : res.data.records
    total.value = res.data.total
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载素材失败'))
  } finally {
    loading.value = false
  }
}

function loadMore() {
  page.value++
  runKeyword(true)
}

async function runVector(text) {
  loading.value = true
  try {
    const res = await vectorSearch({
      query: text, category: cat.value || undefined, excludeBooks: blocked.value, limit: PAGE, novelId: props.novelId || undefined
    })
    if (res.code !== 0) throw new Error(res.message)
    vector.value = res.data
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '语义检索失败'), duration: 6000 })
  } finally {
    loading.value = false
  }
}

function findRelated() {
  mode.value = 'vector'
  query.value = props.contextQuery.replace(/\n/g, ' ')
  runVector(props.contextQuery)
}

/* ---- 卡片 ---- */
const openId = ref(null)
const variants = reactive({}) // 多版本素材的用法：auto | 成员 id
function toggle(id) {
  openId.value = openId.value === id ? null : id
}
function attrLines(m) {
  return Object.entries(m.attributes || {})
    .map(([k, v]) => ({ k, v: Array.isArray(v) ? v.join('、') : String(v ?? '') }))
    .filter((a) => a.v.trim())
}

const applying = ref(null)
async function add(r) {
  const m = r.material
  const item = isMultiVersion(m)
    ? { ...m, variant: variants[m.id] || (r.matchedVariant ? String(r.matchedVariant) : 'auto') }
    : m
  applying.value = m.id
  try {
    await props.apply([item])
  } finally {
    applying.value = null
  }
}

if (!folded.value) runSearch()
</script>

<style scoped>
.material-dock {
  display: flex;
  flex-direction: column;
  width: clamp(300px, 26vw, 380px);
  flex: 0 0 auto;
  min-height: 0;
  background: var(--ws-glass);
  border-left: 1px solid var(--ws-line);
  backdrop-filter: blur(6px);
}
.material-dock.is-folded {
  width: 36px;
}
.dock-strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 100%;
  padding: 14px 0;
  color: var(--ws-side-text);
  background: none;
  border: none;
  cursor: pointer;
}
.dock-strip:hover {
  color: var(--ws-accent);
  background: var(--ws-side-hover);
}
.strip-text {
  writing-mode: vertical-rl;
  letter-spacing: 0.3em;
  font-family: var(--ws-font-title);
  font-size: 14px;
}

.dock-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 12px 8px;
}
.dock-title {
  font-family: var(--ws-font-title);
  font-size: 17px;
  color: var(--ws-ink);
}
.cat-select {
  width: 110px;
}
.dock-total {
  margin-left: auto;
  font-size: 12px;
  color: var(--ws-sub);
}
.dock-fold {
  display: flex;
  padding: 4px;
  color: var(--ws-sub);
  background: none;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.dock-fold:hover {
  color: var(--ws-accent);
  background: var(--ws-side-hover);
}
.dock-search {
  display: flex;
  gap: 6px;
  padding: 0 12px;
}
.dock-search .el-input {
  flex: 1;
  min-width: 0;
}
.dock-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 6px;
}
.dock-info {
  padding: 0 12px 6px;
}
.muted {
  font-size: 12px;
  color: var(--ws-sub);
}

.dock-list {
  flex: 1;
  min-height: 120px;
  overflow-y: auto;
  padding: 4px 12px 16px;
  border-top: 1px dashed var(--ws-line);
}
.m-card {
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--ws-card);
  border: 1px solid var(--ws-line);
  border-radius: 8px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.m-card:hover {
  border-color: var(--el-color-primary-light-7);
}
.m-card.is-open {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 2px 10px rgba(60, 40, 20, 0.06);
}
.m-head,
.m-meta,
.m-summary {
  cursor: pointer;
}
.m-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.m-cat {
  padding: 0 6px;
  font-size: 11px;
  line-height: 18px;
  color: var(--ws-accent);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 3px;
}
.m-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--ws-font-title);
  font-size: 15px;
  color: var(--ws-ink);
}
.m-score {
  font-size: 12px;
  font-weight: 600;
  color: var(--ws-accent);
}
.m-score.weak {
  color: var(--ws-sub);
  font-weight: 400;
}
.m-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--ws-sub);
}
.m-summary {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--el-text-color-regular);
}
.m-summary.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.m-attrs {
  margin-top: 8px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.7;
  background: var(--ws-soft);
  border-radius: 6px;
}
.m-attr-k {
  margin-right: 6px;
  color: var(--ws-sub);
}
.m-attr-k::after {
  content: '：';
}
.m-detail {
  margin-top: 8px;
  font-family: var(--ws-font-prose);
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  color: var(--ws-ink);
}
.m-versions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.m-target {
  margin-top: 8px;
}
.m-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.m-tags {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}
.m-tag {
  padding: 0 6px;
  font-size: 11px;
  line-height: 18px;
  color: var(--ws-side-text);
  background: var(--ws-soft);
  border-radius: 3px;
}
.dock-more {
  padding: 10px 0 0;
  text-align: center;
}
</style>
