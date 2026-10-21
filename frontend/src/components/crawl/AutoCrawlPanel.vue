<template>
  <div class="auto-crawl">
    <el-empty v-if="!siteRules.length" :image-size="64" description="还没有 AI 解析过的站点：全自动爬虫基于 AI 解析出的站点规律">
      <el-button type="success" :icon="MagicStick" @click="emit('open-ai')">去 AI 解析一本书</el-button>
    </el-empty>

    <template v-else>
      <!-- 站点（AI 解析出的规则） -->
      <el-form label-width="104px" @submit.prevent>
        <el-form-item label="站点规律">
          <div class="row">
            <el-select v-model="ruleId" class="rule-select" placeholder="选择 AI 解析出的站点" @change="onRuleChange">
              <el-option v-for="r in siteRules" :key="r.id" :value="r.id" :label="ruleLabel(r)">
                <div class="rule-option">
                  <span>{{ r.siteName || r.host }}</span>
                  <el-tag v-if="r.status !== 'CONFIRMED'" size="small" type="warning">待确认</el-tag>
                  <el-tag v-if="catalogOf(r)" size="small" :type="DECISION[catalogOf(r).decision]?.type">
                    {{ DECISION[catalogOf(r).decision]?.label }} · {{ catalogOf(r).bookCount || 0 }} 本
                  </el-tag>
                  <span class="meta">{{ homeOf(r) }}</span>
                </div>
              </el-option>
            </el-select>
            <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
            <el-button v-if="catalog" type="danger" plain :disabled="running" @click="removeCatalog">删除书目数据</el-button>
          </div>
          <div v-if="rule" class="meta block">
            首页 <a :href="homeOf(rule)" target="_blank" rel="noopener noreferrer">{{ homeOf(rule) }}</a>
            · 书籍地址规律 <span class="mono">{{ rule.bookUrlPattern || '-' }}</span>
            <template v-if="rule.siteMap?.items"> · AI 解析时掌握 {{ rule.siteMap.mastered }}/{{ rule.siteMap.total }} 项</template>
            <el-tag v-if="rule.status !== 'CONFIRMED'" size="small" type="warning" class="ml6">规则待确认（试用）</el-tag>
          </div>
        </el-form-item>
      </el-form>

      <el-steps :active="step" finish-status="success" simple class="steps">
        <el-step title="测试规律" />
        <el-step title="决定是否使用" />
        <el-step title="筛选并抓取" />
      </el-steps>

      <!-- 1. 测试 -->
      <div class="section">
        <div class="section-title">
          1. 测试规律：能否找到多本书，能否取到目录 / 简介 / 标签 / 正文
          <span class="meta">（书目只存简介 / 标签 / 目录，不存正文；同一首页的数据存在 data/{{ catalog?.catalogDir || 'site-catalog/<域名>' }}/）</span>
        </div>
        <el-form :inline="true" size="small" @submit.prevent>
          <el-form-item label="测试书数"><el-input-number v-model="test.maxBooks" :min="2" :max="30" /></el-form-item>
          <el-form-item label="抽检正文"><el-input-number v-model="test.contentSamples" :min="0" :max="10" /> 本</el-form-item>
          <el-form-item label="分类">
            <el-input-number v-model="test.maxCategories" :min="1" :max="50" /> 个 ×
            <el-input-number v-model="test.maxListPages" :min="1" :max="50" /> 页
          </el-form-item>
          <el-form-item>
            <el-button v-if="running" type="danger" plain @click="doCancel">取消</el-button>
            <el-button v-else type="primary" :disabled="!rule" @click="doStart('test')">
              {{ catalog?.report ? '重新测试' : '开始测试' }}
            </el-button>
          </el-form-item>
        </el-form>

        <div v-if="catalog && (running || catalog.status !== 'IDLE')" class="status">
          <el-progress
            :percentage="catalog.progress || 0"
            :status="catalog.status === 'SUCCEEDED' ? 'success' : ['FAILED', 'CANCELLED'].includes(catalog.status) ? 'exception' : ''"
          />
          <div class="meta">
            <el-tag size="small" :type="STATUS[catalog.status]?.type">{{ catalog.phase === 'scan' ? '扩充书目' : '测试' }} · {{ STATUS[catalog.status]?.label }}</el-tag>
            {{ catalog.message }}
          </div>
        </div>

        <template v-if="report">
          <el-alert :type="VERDICT[report.verdict]?.type" :closable="false" show-icon class="report-head" :title="report.summary">
            <template v-if="report.problems?.length" #default>
              <div v-for="p in report.problems" :key="p">· {{ p }}</div>
            </template>
          </el-alert>
          <el-descriptions :column="4" border size="small" class="report">
            <el-descriptions-item label="找到书籍">{{ report.books }} 本</el-descriptions-item>
            <el-descriptions-item label="站点分类">发现 {{ report.categoriesFound }} 个</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ report.seconds }} 秒</el-descriptions-item>
            <el-descriptions-item label="认书规律"><span class="mono">{{ report.bookPattern || '列表页启发式' }}</span></el-descriptions-item>
            <el-descriptions-item v-for="item in reportItems" :key="item.label" :label="item.label">
              <el-tag size="small" :type="rateType(item.rate)">{{ item.text }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <div class="cat-chips">
            <el-tag v-for="c in report.categoriesVisited" :key="c.name" size="small" :type="c.error ? 'danger' : c.books ? 'success' : 'info'">
              {{ c.name }} · {{ c.pages }} 页 · {{ c.books }} 本
            </el-tag>
          </div>
          <el-table v-if="sampleBooks.length" :data="sampleBooks" size="small" max-height="300" class="sample-table">
            <el-table-column label="书名" min-width="140" show-overflow-tooltip>
              <template #default="{ row }"><a :href="row.bookUrl" target="_blank" rel="noopener noreferrer">{{ row.bookName }}</a></template>
            </el-table-column>
            <el-table-column prop="author" label="作者" width="100" show-overflow-tooltip />
            <el-table-column label="标签" min-width="150">
              <template #default="{ row }"><TagList :book="row" /></template>
            </el-table-column>
            <el-table-column label="目录" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.tocOk" size="small" type="success">{{ row.chapterCount }} 章</el-tag>
                <el-tag v-else size="small" type="danger">未取到</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="首章正文" width="96">
              <template #default="{ row }">
                <span v-if="row.contentOk == null" class="meta">未抽检</span>
                <el-tag v-else size="small" :type="row.contentOk ? 'success' : 'danger'">{{ row.contentChars || 0 }} 字</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="简介 / 异常" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.error" class="err">{{ row.error }}</span>
                <span v-else>{{ row.intro || '（无简介）' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </div>

      <!-- 2. 决定 -->
      <div v-if="report" class="section">
        <div class="section-title">2. 是否使用这套规律</div>
        <div class="row">
          <template v-if="catalog.decision === 'PENDING'">
            <el-button type="success" @click="decide('USED')">使用此规律（筛选并抓取）</el-button>
            <el-button type="danger" plain @click="decide('REJECTED')">不使用</el-button>
            <span class="meta">看过上面的测试结果再决定；不使用的站点可以以后重新测试</span>
          </template>
          <template v-else>
            <el-tag :type="DECISION[catalog.decision]?.type">{{ DECISION[catalog.decision]?.label }}</el-tag>
            <el-button v-if="catalog.decision === 'REJECTED'" size="small" @click="decide('USED')">改为使用</el-button>
            <el-button v-else size="small" @click="decide('PENDING')">撤销决定</el-button>
          </template>
        </div>
      </div>

      <!-- 3. 书目：扩充 / 筛选 / 抓取 -->
      <div v-if="catalog && catalog.decision === 'USED'" class="section">
        <div class="section-title">3. 书目（共 {{ catalog.bookCount || 0 }} 本）：选择要抓取的小说</div>

        <el-form :inline="true" size="small" class="scan-form" @submit.prevent>
          <el-form-item label="扩充书目">
            <el-input-number v-model="scan.maxBooks" :min="1" :max="500" /> 本（已采集的跳过）
          </el-form-item>
          <el-form-item label="分类">
            <el-input-number v-model="scan.maxCategories" :min="1" :max="50" /> 个 ×
            <el-input-number v-model="scan.maxListPages" :min="1" :max="50" /> 页
          </el-form-item>
          <el-form-item>
            <el-button :disabled="running" :loading="running && catalog.phase === 'scan'" @click="doStart('scan')">采集更多书目</el-button>
          </el-form-item>
        </el-form>

        <!-- 搜索：书名 / 作者（模糊）、类型（标签模糊）、具体情节（AI 选标签 · 省 token / AI 读简介 · 耗 token） -->
        <div class="search-box">
          <el-autocomplete
            v-model="search.text"
            class="search-input"
            :fetch-suggestions="suggestSearch"
            :trigger-on-focus="search.field === 'type'"
            :placeholder="SEARCH_FIELDS[search.field].placeholder"
            clearable
            @select="doSearch"
            @keyup.enter="doSearch"
          >
            <template #prepend>
              <el-select v-model="search.field" class="search-field" @change="onSearchFieldChange">
                <el-option v-for="(f, k) in SEARCH_FIELDS" :key="k" :label="f.label" :value="k" />
              </el-select>
            </template>
          </el-autocomplete>
          <template v-if="search.field === 'plot'">
            <el-radio-group v-model="search.plotMode">
              <el-radio-button value="tags">AI 选标签 · 省 token</el-radio-button>
              <el-radio-button value="intro">AI 读简介 · 耗 token</el-radio-button>
            </el-radio-group>
            <el-checkbox v-if="search.plotMode === 'intro'" v-model="search.introScoped">只分析当前筛选出的书</el-checkbox>
          </template>
          <el-button type="primary" :icon="Search" :loading="searching" @click="doSearch">搜索</el-button>
          <el-button @click="resetFilter">重置</el-button>
        </div>
        <div class="meta search-hint">{{ SEARCH_FIELDS[search.field].hint }}</div>

        <el-form :inline="true" size="small" class="filter" @submit.prevent="applyFilter">
          <el-form-item label="分类">
            <el-select v-model="filter.category" clearable placeholder="全部" style="width: 120px" @change="applyFilter">
              <el-option v-for="c in tagInfo.categories" :key="c.name" :label="`${c.name}（${c.count}）`" :value="c.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="标签">
            <el-select v-model="filter.tags" multiple filterable collapse-tags collapse-tags-tooltip clearable placeholder="选择标签" style="width: 220px" @change="applyFilter">
              <el-option v-for="t in tagInfo.tags" :key="t.tag" :label="`${t.tag}（${t.count}）`" :value="t.tag">
                <span>{{ t.tag }}</span>
                <span class="meta">（{{ t.count }}{{ t.ai && !t.site ? ' · AI' : '' }}）</span>
              </el-option>
            </el-select>
            <el-radio-group v-model="filter.tagMode" class="ml6" @change="applyFilter">
              <el-radio-button value="any">任一</el-radio-button>
              <el-radio-button value="all">全部</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item>
            <el-switch v-model="filter.usable" active-text="只看目录可用" @change="applyFilter" />
          </el-form-item>
          <el-form-item>
            <el-button :loading="aiTagging" @click="doAiTag">
              AI 补标签<span v-if="untagged">（{{ untagged }} 本没有 AI 标签）</span>
            </el-button>
          </el-form-item>
        </el-form>

        <!-- 当前搜索说明 -->
        <el-alert v-if="introResult" type="success" :closable="false" class="ai-banner">
          <template #title>
            AI 读简介「{{ introResult.query }}」：{{ introResult.results.length }} 本相关（分析了 {{ introResult.analyzed }} 本简介，{{ introResult.model }}）
            <el-button link type="primary" class="ml6" @click="clearIntro">回到书目列表</el-button>
          </template>
          <TokenUsageBar :usage="introResult.usage" />
          <div v-if="introResult.failedBatches" class="err">{{ introResult.failedBatches }}/{{ introResult.batches }} 批调用失败，这部分书没有分析：{{ introResult.errors?.[0] }}</div>
          <div v-if="introResult.truncated" class="meta">筛选出 {{ introResult.matched }} 本，一次最多分析 1000 本</div>
        </el-alert>
        <el-alert v-else-if="searchInfo" type="info" :closable="false" class="ai-banner">
          <template #title>
            {{ searchInfo.title }}
            <el-button link type="primary" class="ml6" @click="resetFilter">清除搜索</el-button>
          </template>
          <template v-if="searchInfo.kind === 'plotTags'">
            <div v-if="searchInfo.reason" class="meta">AI 理解：{{ searchInfo.reason }}</div>
            <div class="chip-row">
              <span class="meta">按标签（任一）筛选，可点 × 去掉：</span>
              <el-tag v-for="t in filter.tags" :key="t" closable size="small" type="success" @close="removeTag(t)">{{ t }}</el-tag>
              <span v-if="!filter.tags.length" class="meta">（已全部去掉）</span>
            </div>
            <div v-if="searchInfo.suggested?.length" class="chip-row">
              <span class="meta">书目里没有、但相关的标签：</span>
              <el-tag v-for="t in searchInfo.suggested" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
              <span class="meta">（可先「AI 补标签」，或改用「AI 读简介」）</span>
            </div>
            <TokenUsageBar v-if="searchInfo.usage" :usage="searchInfo.usage" />
          </template>
        </el-alert>

        <el-table
          ref="tableRef"
          v-loading="loadingBooks"
          :data="rows"
          row-key="id"
          size="small"
          max-height="520"
          class="books"
          @selection-change="(list) => (selected = list)"
        >
          <el-table-column type="selection" width="40" reserve-selection :selectable="(b) => !!b.tocUrl" />
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="book-detail">
                <div class="intro">{{ row.intro || '（无简介）' }}</div>
                <div class="meta">
                  首章：{{ row.firstChapter || '-' }} · 最新：{{ row.latestChapter || '-' }} ·
                  <a :href="row.bookUrl" target="_blank" rel="noopener noreferrer">书籍页</a> ·
                  <a v-if="row.tocUrl" :href="row.tocUrl" target="_blank" rel="noopener noreferrer">目录页</a>
                </div>
                <div v-if="row.error" class="err">{{ row.error }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="书名" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.bookName }}</template>
          </el-table-column>
          <el-table-column prop="author" label="作者" width="110" show-overflow-tooltip />
          <el-table-column prop="category" label="分类" width="80" show-overflow-tooltip />
          <el-table-column label="标签" min-width="200">
            <template #default="{ row }"><TagList :book="row" /></template>
          </el-table-column>
          <el-table-column v-if="introResult" label="相关度" min-width="180">
            <template #default="{ row }">
              <el-tag size="small" :type="row.score >= 70 ? 'success' : row.score >= 40 ? 'warning' : 'info'">{{ row.score }}</el-tag>
              <span class="meta"> {{ row.reason }}</span>
            </template>
          </el-table-column>
          <el-table-column label="目录" width="96">
            <template #default="{ row }">
              <el-button v-if="row.tocOk" link type="primary" size="small" @click="openToc(row)">{{ row.chapterCount }} 章</el-button>
              <el-tag v-else size="small" type="danger">未取到</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="抓取" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.crawl" size="small" :type="STATUS[row.crawl.status]?.type">{{ CRAWL_LABEL[row.crawl.status] || row.crawl.status }}</el-tag>
              <span v-else class="meta">未抓</span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="!introResult && total > page.size"
          v-model:current-page="page.current"
          v-model:page-size="page.size"
          :total="total"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next"
          small
          class="pager"
          @current-change="loadBooks"
          @size-change="loadBooks"
        />

        <div class="submit-row">
          <span>已选 <b>{{ selected.length }}</b> 本</span>
          <span class="unit">每本最多</span>
          <el-input-number v-model="maxChaptersPerBook" :min="0" :max="5000" size="small" />
          <span class="unit">章（0 = 全书）</span>
          <el-button type="primary" :loading="submitting" :disabled="!selected.length" @click="doSubmit">开始抓取（已选 {{ selected.length }} 本）</el-button>
          <el-button size="small" :disabled="!rows.length" @click="selectPage">选中本页</el-button>
          <el-button size="small" :disabled="!selected.length" @click="tableRef?.clearSelection()">清空选择</el-button>
          <span class="meta">逐本抓取，每本一个 txt 进文件管理；建议先用 3~10 章试跑</span>
        </div>
      </div>
    </template>

    <!-- 目录 -->
    <el-dialog v-model="tocDlg.visible" :title="`目录 · ${tocDlg.title}`" width="640px" append-to-body>
      <div v-loading="tocDlg.loading">
        <div v-if="tocDlg.data" class="meta">共 {{ tocDlg.data.chapterCount }} 章，采集于 {{ tocDlg.data.savedAt }} · {{ tocDlg.data.tocUrl }}</div>
        <el-table v-if="tocDlg.data" :data="tocDlg.data.chapters" size="small" max-height="460">
          <el-table-column type="index" label="#" width="60" />
          <el-table-column label="章节" show-overflow-tooltip>
            <template #default="{ row }"><a :href="row.url" target="_blank" rel="noopener noreferrer">{{ row.title }}</a></template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { MagicStick, Refresh, Search } from '@element-plus/icons-vue'
import {
  aiTagCatalog,
  cancelCatalog,
  decideCatalog,
  deleteCatalog,
  getCatalog,
  getCatalogBookToc,
  getCatalogTags,
  listCatalogBooks,
  listCatalogs,
  introMatchCatalog,
  plotTagsCatalog,
  startCatalog,
  submitSiteCrawl
} from '@/api/crawl'
import { errorMessage } from '@/api/request'
import TokenUsageBar from '@/components/ai/TokenUsageBar.vue'
import { costOf, formatCost, priceOf } from '@/utils/modelPricing'

const props = defineProps({
  rules: { type: Array, default: () => [] }, // AI 解析出的站点规则（crawl.vue 的 learnedRules）
  preferRuleId: { type: Number, default: null }, // 外部指定的规则（解析管理「全自动抓取」/ 地址管理）
  delayMs: { type: Number, default: 1000 },
  respectRobots: { type: Boolean, default: true }
})
const emit = defineEmits(['submitted', 'open-ai'])

const STATUS = {
  IDLE: { label: '未开始', type: 'info' },
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '进行中', type: 'warning' },
  SUCCEEDED: { label: '完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
  CANCELLED: { label: '已取消', type: 'info' }
}
const CRAWL_LABEL = { QUEUED: '排队中', RUNNING: '抓取中', SUCCEEDED: '已抓取', FAILED: '失败', CANCELLED: '已取消' }
const DECISION = {
  PENDING: { label: '待决定', type: 'warning' },
  USED: { label: '使用中', type: 'success' },
  REJECTED: { label: '不使用', type: 'info' }
}
const VERDICT = { usable: { type: 'success' }, partial: { type: 'warning' }, unusable: { type: 'error' } }
const RULE_KEY = 'nan_novel.crawl.autoRule'
const POLL_MS = 2000
// 搜索框的类型：书名 / 作者模糊匹配，类型 = 标签模糊匹配，具体情节 = AI（选标签 / 读简介）
const SEARCH_FIELDS = {
  name: { label: '书名', placeholder: '书名关键词，模糊匹配，空格分隔多个词', hint: '书名模糊匹配：包含输入的每个词即可' },
  author: { label: '作者', placeholder: '作者名，模糊匹配', hint: '作者名模糊匹配' },
  type: { label: '类型', placeholder: '如 玄幻、修仙、都市、重生（可从下拉的已有标签里选）', hint: '按标签搜索：站点标签 / AI 标签 / 分类里含这个词即可（多个词用空格分隔，任一命中）' },
  plot: {
    label: '具体情节',
    placeholder: '描述想看的情节，如「废柴少年被退婚后逆袭，宗门修炼，带系统」',
    hint: 'AI 选标签：大模型理解描述后从书目已有标签里挑出相关标签再筛书（一次调用，省 token）；AI 读简介：大模型逐本阅读简介打分（准确，但每本都要消耗 token，开始前会先估算）'
  }
}

/** 标签：站点标签实心，AI 标签虚线 */
const TagList = defineComponent({
  props: { book: { type: Object, required: true } },
  setup(p) {
    return () => {
      const site = p.book.tags || []
      const ai = (p.book.aiTags || []).filter((t) => !site.includes(t))
      return h('div', { class: 'tag-list' }, [
        ...site.map((t) => h(ElTag, { size: 'small', type: 'info', key: `s${t}` }, () => t)),
        ...ai.map((t) => h(ElTag, { size: 'small', effect: 'plain', class: 'ai-tag', key: `a${t}`, title: 'AI 标签' }, () => t))
      ])
    }
  }
})

const catalogs = ref([])
const ruleId = ref(readRuleId())
const catalog = ref(null)
const sampleBooks = ref([])
const rows = ref([])
const total = ref(0)
const selected = ref([])
const tableRef = ref(null)
const loadingBooks = ref(false)
const submitting = ref(false)
const tagInfo = reactive({ tags: [], categories: [], total: 0, aiTagged: 0 })
const test = reactive({ maxBooks: 8, contentSamples: 3, maxCategories: 10, maxListPages: 3 })
const scan = reactive({ maxBooks: 50, maxCategories: 10, maxListPages: 5 })
const filter = reactive(emptyFilter())
const page = reactive({ current: 1, size: 50 })
const maxChaptersPerBook = ref(0)
const search = reactive({ field: 'name', text: '', plotMode: 'tags', introScoped: true })
const searching = ref(false)
// 当前搜索的说明（书名 / 作者 / 类型 / AI 选标签），AI 读简介的结果另放 introResult（表格改显示结果，带相关度）
const searchInfo = ref(null)
const introResult = ref(null)
const aiTagging = ref(false)
const tocDlg = reactive({ visible: false, title: '', loading: false, data: null })
let timer = null

function emptyFilter() {
  return { keyword: '', author: '', tagKeyword: '', category: '', tags: [], tagMode: 'any', usable: false }
}

function readRuleId() {
  try {
    return Number(localStorage.getItem(RULE_KEY)) || null
  } catch {
    return null
  }
}

/** 有站点首页（或学习样例）的规则才能用：已确认在前 */
const siteRules = computed(() =>
  props.rules
    .filter((r) => r.status !== 'FAILED' && homeOf(r))
    .slice()
    .sort((a, b) => (a.status === 'CONFIRMED' ? 0 : 1) - (b.status === 'CONFIRMED' ? 0 : 1))
)
const rule = computed(() => siteRules.value.find((r) => r.id === ruleId.value) || null)
const running = computed(() => catalog.value?.status === 'RUNNING')
const report = computed(() => catalog.value?.report || null)
const untagged = computed(() => Math.max(tagInfo.total - tagInfo.aiTagged, 0))
const step = computed(() => {
  if (!report.value) return 0
  if (catalog.value.decision !== 'USED') return 1
  return 2
})

const reportItems = computed(() => {
  const r = report.value
  if (!r) return []
  const c = r.counts || {}
  const n = r.books || 0
  const items = [
    { label: '书籍页', n: c.detail, total: n },
    { label: '目录', n: c.toc, total: n },
    { label: '简介', n: c.intro, total: n },
    { label: '标签', n: c.tags, total: n },
    { label: '作者', n: c.author, total: n }
  ]
  if (c.contentChecked) items.push({ label: '首章正文', n: c.content, total: c.contentChecked })
  else items.push({ label: '首章正文', n: 0, total: 0 })
  return items.map((i) => ({
    label: i.label,
    rate: i.total ? i.n / i.total : null,
    text: i.total ? `${i.n}/${i.total}` : '未抽检'
  }))
})

function rateType(rate) {
  if (rate == null) return 'info'
  return rate >= 0.8 ? 'success' : rate >= 0.5 ? 'warning' : 'danger'
}

function homeOf(r) {
  if (r.homeUrl) return r.homeUrl
  try {
    const u = new URL(r.sampleUrl)
    return `${u.protocol}//${u.host}/`
  } catch {
    return ''
  }
}

function ruleLabel(r) {
  return `${r.siteName || r.host}${r.status === 'CONFIRMED' ? '' : '（待确认）'}`
}

/** 与后端一致：同一首页一份书目 */
function catalogOf(r) {
  const home = homeOf(r)
  return catalogs.value.find((c) => c.homeUrl === home) || null
}

async function loadCatalogs() {
  try {
    const res = await listCatalogs()
    if (res.code === 0) catalogs.value = res.data || []
  } catch {
    // 后端没起时不影响其它功能
  }
}

/** 切换站点：载入该首页的书目（没有就等用户点「开始测试」） */
async function onRuleChange() {
  try {
    localStorage.setItem(RULE_KEY, String(ruleId.value || ''))
  } catch {
    // ignore
  }
  introResult.value = null
  searchInfo.value = null
  search.text = ''
  tableRef.value?.clearSelection()
  Object.assign(filter, emptyFilter())
  page.current = 1
  catalog.value = rule.value ? catalogOf(rule.value) : null
  await refreshCatalog(true)
}

/** 重新取书目状态；结束 / 切换时刷新样本、书目、标签 */
async function refreshCatalog(full) {
  stopPoll()
  if (!catalog.value) {
    sampleBooks.value = []
    rows.value = []
    total.value = 0
    return
  }
  try {
    const res = await getCatalog(catalog.value.id)
    if (res.code !== 0) {
      catalog.value = null
      return
    }
    const wasRunning = running.value
    catalog.value = res.data
    if (full || (wasRunning && !running.value) || running.value) {
      await Promise.all([loadSample(), catalog.value.decision === 'USED' ? loadBooks() : null, loadTags()])
    }
  } catch (e) {
    if (e?.response?.status === 404) catalog.value = null
  }
  if (running.value) schedulePoll()
}

function schedulePoll() {
  stopPoll()
  timer = setTimeout(async () => {
    const before = running.value
    await refreshCatalog(false)
    if (before && !running.value) {
      await loadCatalogs()
      const st = catalog.value?.status
      if (st === 'SUCCEEDED') ElMessage.success(catalog.value.message || '采集完成')
      else if (st === 'FAILED') ElMessage.error(catalog.value.message || '采集失败')
    }
  }, POLL_MS)
}

function stopPoll() {
  if (timer) clearTimeout(timer)
  timer = null
}

/** 测试结果的样本：书目里前 30 本 */
async function loadSample() {
  try {
    const res = await listCatalogBooks(catalog.value.id, { page: 1, size: 30 })
    if (res.code === 0) sampleBooks.value = res.data.records || []
  } catch {
    sampleBooks.value = []
  }
}

async function loadBooks() {
  if (!catalog.value || introResult.value) return
  loadingBooks.value = true
  try {
    const f = filterParams()
    const res = await listCatalogBooks(catalog.value.id, {
      ...f,
      tags: f.tags.length ? f.tags.join(',') : undefined,
      page: page.current,
      size: page.size
    })
    if (res.code === 0) {
      rows.value = res.data.records || []
      total.value = res.data.total || 0
    } else ElMessage.error(res.message || '加载书目失败')
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载书目失败'))
  } finally {
    loadingBooks.value = false
  }
}

async function loadTags() {
  try {
    const res = await getCatalogTags(catalog.value.id)
    if (res.code === 0) Object.assign(tagInfo, res.data)
  } catch {
    // ignore
  }
}

/** 当前筛选（书目列表与「只分析当前筛选出的书」共用） */
function filterParams() {
  return {
    keyword: filter.keyword.trim() || undefined,
    author: filter.author.trim() || undefined,
    tagKeyword: filter.tagKeyword.trim() || undefined,
    category: filter.category || undefined,
    tags: [...filter.tags],
    tagMode: filter.tagMode,
    usable: filter.usable || undefined
  }
}

function applyFilter() {
  introResult.value = null
  page.current = 1
  loadBooks()
}

function resetFilter() {
  Object.assign(filter, emptyFilter())
  searchInfo.value = null
  search.text = ''
  applyFilter()
}

function onSearchFieldChange() {
  search.text = ''
}

/** 类型：下拉提示书目已有的标签 / 分类（含输入的字） */
function suggestSearch(query, cb) {
  if (search.field !== 'type') return cb([])
  const q = (query || '').trim()
  const names = [...tagInfo.tags.map((t) => ({ value: t.tag, count: t.count })), ...tagInfo.categories.map((c) => ({ value: c.name, count: c.count }))]
  const seen = new Set()
  cb(
    names
      .filter((n) => (!q || n.value.includes(q)) && !seen.has(n.value) && seen.add(n.value))
      .slice(0, 30)
      .map((n) => ({ value: n.value, label: `${n.value}（${n.count}）` }))
  )
}

/** 按搜索框的类型搜索：书名 / 作者 / 类型改筛选条件；具体情节走 AI */
async function doSearch() {
  if (!catalog.value || searching.value) return
  const text = search.text.trim()
  introResult.value = null
  if (search.field === 'plot') {
    if (!text) {
      ElMessage.warning('先描述想看的情节')
      return
    }
    return search.plotMode === 'intro' ? searchByIntro(text) : searchByPlotTags(text)
  }
  // 书名 / 作者 / 类型三选一：换类型搜索时清掉另外两个，免得条件叠加看不懂
  Object.assign(filter, { keyword: '', author: '', tagKeyword: '' })
  const key = { name: 'keyword', author: 'author', type: 'tagKeyword' }[search.field]
  filter[key] = text
  searchInfo.value = text ? { kind: search.field, title: `${SEARCH_FIELDS[search.field].label}包含「${text}」` } : null
  applyFilter()
}

/** 具体情节 · AI 选标签：模型从书目已有标签里挑，结果写进标签筛选（任一），可再手动增删 */
async function searchByPlotTags(text) {
  searching.value = true
  try {
    const res = await plotTagsCatalog(catalog.value.id, text)
    if (res.code !== 0) {
      ElMessage.error(res.message || 'AI 选标签失败')
      return
    }
    const d = res.data
    Object.assign(filter, { keyword: '', author: '', tagKeyword: '', tags: d.tags || [], tagMode: 'any' })
    searchInfo.value = {
      kind: 'plotTags',
      title: d.tags?.length ? `具体情节「${text}」→ AI 选了 ${d.tags.length} 个标签` : `具体情节「${text}」：书目已有标签里没有相关的`,
      reason: d.reason,
      suggested: d.suggested,
      usage: d.usage
    }
    if (!d.tags?.length) {
      ElMessage.warning('书目里没有匹配的标签：可以先「AI 补标签」，或改用「AI 读简介」')
      return
    }
    applyFilter()
  } catch (e) {
    ElMessage.error(errorMessage(e, 'AI 选标签失败（需要「模型配置」里有已验证的大模型）'))
  } finally {
    searching.value = false
  }
}

/** 具体情节 · AI 读简介：先估算本数 / token / 费用并确认，再让模型逐本读简介打分 */
async function searchByIntro(text) {
  const filterBody = search.introScoped ? filterParams() : null
  searching.value = true
  try {
    const est = await introMatchCatalog(catalog.value.id, { query: text, filter: filterBody, estimate: true })
    if (est.code !== 0) {
      ElMessage.error(est.message || '估算失败')
      return
    }
    const e = est.data
    if (!e.books) {
      ElMessage.warning('当前筛选下没有书可以分析')
      return
    }
    const price = priceOf(e.modelId)
    const cost = price ? `，约 ${formatCost(costOf(e, price), price.currency)}` : ''
    try {
      await ElMessageBox.confirm(
        `将让大模型（${e.model}）逐本阅读 ${e.books} 本书的简介（${search.introScoped ? '当前筛选出的书' : '整个书目'}${e.truncated ? `，共 ${e.matched} 本，一次最多 1000 本` : ''}），` +
          `分 ${e.batches} 批调用，预计消耗约 ${(e.promptTokens + e.completionTokens).toLocaleString()} tokens` +
          `（输入 ${e.promptTokens.toLocaleString()} / 输出 ${e.completionTokens.toLocaleString()}${cost}）。` +
          (search.introScoped ? '' : '想省 token 可以先用分类 / 标签缩小范围，再勾选「只分析当前筛选出的书」。') +
          '继续吗？',
        'AI 读简介 · 消耗 token 较多',
        { type: 'warning', confirmButtonText: '开始分析' }
      )
    } catch {
      return
    }
    const res = await introMatchCatalog(catalog.value.id, { query: text, filter: filterBody })
    if (res.code !== 0) {
      ElMessage.error(res.message || 'AI 读简介失败')
      return
    }
    introResult.value = { ...res.data, query: text }
    searchInfo.value = null
    rows.value = res.data.results || []
    if (!rows.value.length) ElMessage.info('没有找到情节相符的书，换个说法试试，或先「采集更多书目」')
  } catch (e) {
    ElMessage.error(errorMessage(e, 'AI 读简介失败（需要「模型配置」里有已验证的大模型）'))
  } finally {
    searching.value = false
  }
}

function clearIntro() {
  introResult.value = null
  loadBooks()
}

/** AI 选出的标签去掉一个后重新筛选 */
function removeTag(tag) {
  filter.tags = filter.tags.filter((t) => t !== tag)
  applyFilter()
}

async function doStart(phase) {
  if (!rule.value) return
  const opts = phase === 'test' ? test : scan
  try {
    const res = await startCatalog({
      ruleId: rule.value.id,
      phase,
      maxBooks: opts.maxBooks,
      maxCategories: opts.maxCategories,
      maxListPages: opts.maxListPages,
      contentSamples: phase === 'test' ? test.contentSamples : 0,
      delayMs: props.delayMs,
      respectRobots: props.respectRobots
    })
    if (res.code !== 0) {
      ElMessage.error(res.message || '提交失败')
      return
    }
    catalog.value = res.data
    await loadCatalogs()
    ElMessage.success(phase === 'test' ? '开始测试：按规律找书、取目录 / 简介 / 标签并抽检正文' : '开始采集更多书目')
    schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交失败（AI 服务是否已启动？）'))
  }
}

async function doCancel() {
  try {
    const res = await cancelCatalog(catalog.value.id)
    if (res.code === 0) catalog.value = res.data
    schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '取消失败'))
  }
}

async function decide(decision) {
  try {
    const res = await decideCatalog(catalog.value.id, decision)
    if (res.code !== 0) {
      ElMessage.error(res.message || '保存失败')
      return
    }
    catalog.value = res.data
    await loadCatalogs()
    if (decision === 'USED') {
      ElMessage.success('已决定使用：可扩充书目、按书名 / 作者 / 标签 / AI 检索筛选后抓取')
      await Promise.all([loadBooks(), loadTags()])
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  }
}

async function removeCatalog() {
  try {
    await ElMessageBox.confirm(
      `删除「${catalog.value.siteName || catalog.value.host}」的书目数据（${catalog.value.bookCount || 0} 本的简介 / 标签 / 目录）？已抓取的 txt 在文件管理里，不受影响。`,
      '删除书目',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const res = await deleteCatalog(catalog.value.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '删除失败')
      return
    }
    catalog.value = null
    await loadCatalogs()
    await refreshCatalog(true)
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

async function doAiTag() {
  if (!catalog.value) return
  aiTagging.value = true
  try {
    const res = await aiTagCatalog(catalog.value.id, { limit: 40 })
    if (res.code !== 0) {
      ElMessage.error(res.message || 'AI 补标签失败')
      return
    }
    ElMessage.success(`AI 补标签：${res.data.tagged} 本` + (res.data.remaining ? `，还有 ${res.data.remaining} 本，可再点一次` : '，已全部补完'))
    await loadTags()
    if (!introResult.value) await loadBooks()
  } catch (e) {
    ElMessage.error(errorMessage(e, 'AI 补标签失败（需要「模型配置」里有已验证的大模型）'))
  } finally {
    aiTagging.value = false
  }
}

function selectPage() {
  rows.value.forEach((b) => {
    if (b.tocUrl) tableRef.value?.toggleRowSelection(b, true)
  })
}

async function openToc(row) {
  Object.assign(tocDlg, { visible: true, title: row.bookName, loading: true, data: null })
  try {
    const res = await getCatalogBookToc(row.id)
    if (res.code === 0) tocDlg.data = res.data
    else ElMessage.error(res.message || '读取目录失败')
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取目录失败'))
  } finally {
    tocDlg.loading = false
  }
}

/** 选中的书 → 普通整站抓取任务（规则 = 这条 AI 解析规则），逐本抓取 */
async function doSubmit() {
  const books = selected.value
    .filter((b) => b.tocUrl)
    .map((b) => ({ tocUrl: b.tocUrl, bookName: b.bookName, author: b.author, category: b.category }))
  if (!books.length) return
  submitting.value = true
  try {
    const res = await submitSiteCrawl({
      url: catalog.value.homeUrl,
      preset: `learned:${rule.value.id}`,
      delayMs: props.delayMs,
      respectRobots: props.respectRobots,
      maxChaptersPerBook: maxChaptersPerBook.value,
      books
    })
    if (res.code !== 0) {
      ElMessage.error(res.message || '提交失败')
      return
    }
    ElMessage.success(`已开始抓取 ${books.length} 本，进度见下方「抓取任务」`)
    tableRef.value?.clearSelection()
    emit('submitted', res.data)
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交抓取任务失败'))
  } finally {
    submitting.value = false
  }
}

async function reloadAll() {
  await loadCatalogs()
  if (rule.value) catalog.value = catalogOf(rule.value)
  await refreshCatalog(true)
}

/** 默认选中：外部指定 > 上次用的 > 第一条 */
function ensureRule() {
  if (props.preferRuleId && siteRules.value.some((r) => r.id === props.preferRuleId)) {
    if (ruleId.value !== props.preferRuleId) {
      ruleId.value = props.preferRuleId
      return true
    }
    return false
  }
  if (!rule.value && siteRules.value.length) {
    ruleId.value = siteRules.value[0].id
    return true
  }
  return false
}

watch(() => props.preferRuleId, () => {
  if (ensureRule()) onRuleChange()
})
watch(siteRules, () => {
  if (ensureRule()) onRuleChange()
})

// 面板随模式切换 v-if 挂载：挂载时初始化；页面被 keep-alive 缓存，回到本页时只刷新（进行中的采集继续轮询）
let inited = false
onMounted(async () => {
  await loadCatalogs()
  ensureRule()
  await onRuleChange()
  inited = true
})
onActivated(() => {
  if (inited) reloadAll()
})
onDeactivated(stopPoll)
onBeforeUnmount(stopPoll)
</script>

<style scoped>
.row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.rule-select {
  width: 360px;
}
.rule-option {
  display: flex;
  align-items: center;
  gap: 6px;
}
.steps {
  margin: 4px 0 12px;
}
.section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}
.section-title {
  margin-bottom: 10px;
  font-weight: 600;
  color: #303133;
}
.section-title .meta {
  font-weight: normal;
}
.status {
  margin-bottom: 10px;
}
.report-head,
.report {
  margin-bottom: 10px;
}
.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.meta.block {
  width: 100%;
  line-height: 1.6;
}
.mono {
  font-family: Consolas, monospace;
  word-break: break-all;
}
.err {
  color: #f56c6c;
}
.ml6 {
  margin-left: 6px;
}
.unit {
  color: #606266;
  font-size: 13px;
}
.filter,
.scan-form {
  margin-bottom: 0;
}
.search-box {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.search-input {
  width: 520px;
}
.search-field {
  width: 104px;
}
.search-hint {
  margin: 4px 0 10px;
}
.chip-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.ai-banner {
  margin-bottom: 10px;
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.tag-list :deep(.ai-tag) {
  border-style: dashed;
}
.book-detail {
  padding: 4px 48px;
  line-height: 1.7;
  font-size: 13px;
  color: #606266;
}
.book-detail .intro {
  white-space: pre-wrap;
  max-height: 140px;
  overflow: auto;
}
.pager {
  margin-top: 8px;
  justify-content: flex-end;
}
.submit-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
</style>
