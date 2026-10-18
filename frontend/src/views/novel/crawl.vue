<template>
  <div class="crawl-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">小说抓取</span>
          <div class="header-ops">
            <el-radio-group v-model="mode" size="small" @change="onModeChange">
              <el-radio-button value="book">单本（目录页）</el-radio-button>
              <el-radio-button value="site">整站（分类 → 所有书）</el-radio-button>
            </el-radio-group>
            <el-button @click="router.push('/file/manage')">文件管理</el-button>
          </div>
        </div>
      </template>

      <el-alert type="info" :closable="false" show-icon class="tip" :title="tipText" />

      <el-form label-width="104px" @submit.prevent>
        <el-form-item :label="mode === 'book' ? '目录页地址' : '站点地址'">
          <div class="url-row">
            <el-input
              v-model="form.url"
              :placeholder="mode === 'book' ? 'https://example.com/book/123/' : 'https://example.com/（站点首页或分类列表页）'"
              clearable
              @keyup.enter="mode === 'book' ? doPreview() : doDiscover()"
            />
            <el-button v-if="mode === 'book'" type="primary" :loading="previewing" :disabled="!form.url" @click="doPreview">
              解析目录
            </el-button>
            <el-button v-else type="primary" :loading="discovering" :disabled="!form.url" @click="doDiscover">
              发现书籍
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="抓取规则">
          <el-select v-model="form.preset" style="width: 260px">
            <el-option label="按域名自动选择" value="" />
            <el-option v-for="p in presets" :key="p.key" :label="p.name" :value="p.key" />
          </el-select>
          <span class="hint">{{ currentPreset?.description || '命中预设域名用对应规则，否则自动识别' }}</span>
        </el-form-item>

        <template v-if="mode === 'site'">
          <el-form-item label="整站上限">
            <el-input-number v-model="site.maxBooks" :min="1" :max="120" />
            <span class="unit">本</span>
            <span class="hint">一次最多发现 / 抓取多少本（copybook 是全站无上限，这里默认 20 本，避免把对方站点抓空）</span>
          </el-form-item>
          <el-form-item label="分类范围">
            <el-input-number v-model="site.maxCategories" :min="1" :max="30" />
            <span class="unit">个分类</span>
            <el-input-number v-model="site.maxListPages" :min="1" :max="20" />
            <span class="unit">页 / 分类</span>
          </el-form-item>
          <el-form-item label="只要分类">
            <el-input v-model="site.categoriesText" placeholder="留空 = 全部分类；多个用逗号分隔，如：玄幻,都市" clearable />
          </el-form-item>
          <el-form-item label="每本最多">
            <el-input-number v-model="site.maxChaptersPerBook" :min="0" :max="5000" />
            <span class="unit">章</span>
            <span class="hint">0 = 全书。建议先用 3~10 章试跑，确认规则没问题再抓全书</span>
            <el-switch v-model="site.verify" active-text="发现时解析每本目录" class="switch" />
          </el-form-item>
        </template>

        <el-collapse v-model="advancedOpen" class="advanced">
          <el-collapse-item title="高级选项（自定义 XPath / 限速 / robots）" name="adv">
            <el-form-item label="请求间隔">
              <el-input-number v-model="form.delayMs" :min="300" :max="30000" :step="500" />
              <span class="hint">毫秒，两次请求之间至少间隔这么久</span>
            </el-form-item>
            <el-form-item label="robots.txt">
              <el-switch v-model="form.respectRobots" active-text="遵守" />
            </el-form-item>
            <p class="hint block">
              以下留空 = 使用所选规则的值（灰色占位符），都为空则自动识别。
              <template v-if="mode === 'site'">
                整站模式先按「分类链接」进入分类页，再按「书籍链接」找书，按「目录链接」从详情页跳到目录。
              </template>
              其余字段与单本相同：章节链接 XPath 选中 &lt;a&gt; 元素，正文 XPath 选中正文容器。
            </p>
            <el-form-item v-for="f in ruleFields" :key="f.key" :label="f.label">
              <el-input v-model="form.rule[f.key]" :placeholder="presetRule[f.key] || f.placeholder" clearable />
            </el-form-item>
            <el-form-item label="删除行">
              <el-input
                v-model="form.removeText"
                type="textarea"
                :rows="2"
                placeholder="每行一个正则，正文中匹配的行会被删除（内置已去除常见网址 / 引流广告）"
              />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
      </el-form>

      <!-- 单本：目录预览 -->
      <div v-if="mode === 'book' && preview" class="preview">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="书名">{{ preview.bookName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="作者">{{ preview.author || '-' }}</el-descriptions-item>
          <el-descriptions-item label="章节数">{{ preview.chapterCount }}（目录 {{ preview.tocPages }} 页）</el-descriptions-item>
          <el-descriptions-item label="使用规则">{{ presetName(preview.preset) }}</el-descriptions-item>
          <el-descriptions-item label="首章" :span="2">{{ preview.chapters[0]?.title }}</el-descriptions-item>
          <el-descriptions-item label="简介" :span="3">
            <div class="intro">{{ preview.intro || '-' }}</div>
          </el-descriptions-item>
        </el-descriptions>

        <div class="sample">
          <div class="sample-title">
            试抓首章：{{ preview.sample?.title }}
            <el-tag v-if="preview.sample?.error" type="danger" size="small">失败</el-tag>
            <el-tag v-else :type="preview.sample?.chars < 200 ? 'warning' : 'success'" size="small">
              {{ preview.sample?.chars }} 字
            </el-tag>
          </div>
          <el-alert v-if="preview.sample?.error" type="error" :closable="false" :title="preview.sample.error" />
          <el-alert
            v-else-if="preview.sample?.chars < 200"
            type="warning"
            :closable="false"
            title="正文很短，可能没识别到正文区块，建议在高级选项中填写正文 XPath 后重新解析"
          />
          <pre v-if="preview.sample?.text" class="sample-text">{{ preview.sample.text }}</pre>
        </div>

        <el-form label-width="96px" class="range">
          <el-form-item label="抓取范围">
            <el-input-number v-model="range.start" :min="1" :max="preview.chapterCount" />
            <span class="range-sep">至</span>
            <el-input-number v-model="range.end" :min="range.start" :max="preview.chapterCount" />
            <span class="hint">
              {{ preview.chapters[range.start - 1]?.title }} → {{ preview.chapters[range.end - 1]?.title }}
              （共 {{ Math.max(range.end - range.start + 1, 0) }} 章，预计 ≥ {{ estimate }}）
            </span>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="submitting" @click="doSubmit">开始抓取</el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- 整站：发现的书籍清单 -->
      <div v-if="mode === 'site' && siteResult" class="preview">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="站点">{{ siteResult.siteName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ siteResult.categoriesAll?.length || 0 }} 个</el-descriptions-item>
          <el-descriptions-item label="发现书籍">
            {{ siteResult.bookCount }} 本
            <el-tag v-if="siteResult.truncated" size="small" type="warning" class="ml6">已达上限</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="使用规则">{{ presetName(siteResult.preset) }}</el-descriptions-item>
        </el-descriptions>

        <div class="cat-chips">
          <el-tag
            v-for="c in siteResult.categories"
            :key="c.url"
            size="small"
            :type="c.books ? 'success' : 'info'"
          >
            {{ c.name }} · {{ c.books }} 本
          </el-tag>
          <span class="hint">
            已访问 {{ siteResult.categories.length }}/{{ siteResult.categoriesAll?.length || 0 }} 个分类，
            共 {{ siteResult.bookCount }} 本
          </span>
        </div>

        <el-table
          ref="booksTableRef"
          :data="siteResult.books"
          stripe
          max-height="380"
          row-key="sourceUrl"
          @selection-change="onBookSelect"
        >
          <el-table-column type="selection" width="42" :selectable="(b) => !!b.tocUrl" />
          <el-table-column label="书名" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.bookName || '（未解析）' }}</template>
          </el-table-column>
          <el-table-column prop="author" label="作者" width="120" />
          <el-table-column prop="category" label="分类" width="100" />
          <el-table-column label="章节" width="80">
            <template #default="{ row }">{{ row.chapterCount ?? '-' }}</template>
          </el-table-column>
          <el-table-column label="目录页 / 异常" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag v-if="row.error" type="danger" size="small">{{ row.error }}</el-tag>
              <span v-else class="meta">{{ row.tocUrl }}</span>
            </template>
          </el-table-column>
        </el-table>

        <div class="range">
          <el-button type="primary" :loading="submitting" :disabled="!selectedBooks.length" @click="doSubmitSite">
            开始抓取（已选 {{ selectedBooks.length }} 本）
          </el-button>
          <el-button :disabled="!siteResult.books?.length" @click="selectAllBooks">全选</el-button>
          <span class="hint">每本存一个 txt 到文件管理，可单独发起小说提取；整站任务按顺序逐本抓取</span>
        </div>
      </div>
    </el-card>

    <el-card class="box-card tasks" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">抓取任务</span>
          <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
        </div>
      </template>
      <el-empty v-if="!tasks.length" description="暂无抓取任务" />
      <el-table v-else :data="tasks" stripe>
        <el-table-column label="小说" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.bookName || (row.mode === 'site' ? '（整站）' : '（解析中）') }}<span v-if="row.author" class="meta"> · {{ row.author }}</span></div>
            <div class="meta">{{ row.url }}</div>
          </template>
        </el-table-column>
        <el-table-column label="模式" width="76">
          <template #default="{ row }">
            <el-tag size="small" :type="row.mode === 'site' ? 'warning' : 'info'">
              {{ row.mode === 'site' ? '整站' : '单本' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="STATUS[row.status]?.type" size="small">{{ STATUS[row.status]?.label || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="210">
          <template #default="{ row }">
            <el-progress
              :percentage="row.progress || 0"
              :status="row.status === 'SUCCEEDED' ? 'success' : ['FAILED', 'CANCELLED'].includes(row.status) ? 'exception' : ''"
            />
            <div v-if="row.mode === 'site'" class="meta">
              书 {{ row.bookDone || 0 }}/{{ row.bookTotal || 0 }} 本
              <span v-if="row.bookFailed">，失败 {{ row.bookFailed }}</span>
              <span v-if="row.wordCount">，{{ row.wordCount }} 字</span>
            </div>
            <div v-else-if="row.chapterTotal" class="meta">
              {{ row.chapterDone || 0 }}/{{ row.chapterTotal }} 章
              <span v-if="row.chapterFailed">，失败 {{ row.chapterFailed }}</span>
              <span v-if="row.wordCount">，{{ row.wordCount }} 字</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip />
        <el-table-column prop="createTime" label="创建时间" width="170" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-if="isActive(row)" link type="danger" @click="doCancel(row)">取消</el-button>
            <template v-else>
              <el-button v-if="row.mode === 'site'" link type="primary" @click="openBooks(row)">书籍明细</el-button>
              <el-button v-else-if="row.fileId" link type="primary" @click="openExtract(row)">小说提取</el-button>
              <el-button link @click="doRetry(row)">重新抓取</el-button>
              <el-button link @click="reuseOptions(row)">改参数</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 整站任务：逐本明细 -->
    <el-dialog v-model="booksDlg.visible" title="整站任务 · 书籍明细" width="820px">
      <div class="dialog-bar">
        <span class="hint">{{ booksDlg.title }}</span>
        <el-button size="small" :icon="Refresh" :loading="booksDlg.loading" @click="loadBooks">刷新</el-button>
      </div>
      <el-table :data="booksDlg.books" stripe max-height="440" size="small">
        <el-table-column label="书名" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.bookName || row.tocUrl }}</template>
        </el-table-column>
        <el-table-column prop="category" label="分类" width="90" />
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <el-tag :type="STATUS[row.status]?.type" size="small">{{ STATUS[row.status]?.label || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            <el-progress :percentage="row.progress || 0" :stroke-width="10" />
            <div v-if="row.chapterTotal" class="meta">{{ row.chapterDone || 0 }}/{{ row.chapterTotal }} 章</div>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="96">
          <template #default="{ row }">
            <el-button v-if="row.fileId" link type="primary" @click="openExtract(row)">小说提取</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <ExtractOptionsDialog v-model="extractDlg.visible" :file-name="extractDlg.fileName" @confirm="doExtract" />
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onDeactivated, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  cancelCrawl,
  discoverCrawl,
  listCrawlBooks,
  listCrawlPresets,
  listCrawls,
  previewCrawl,
  retryCrawl,
  submitCrawl,
  submitSiteCrawl
} from '@/api/crawl'
import { submitExtract } from '@/api/novel'
import { errorMessage } from '@/api/request'
import ExtractOptionsDialog from '@/components/material/ExtractOptionsDialog.vue'

const STATUS = {
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '抓取中', type: 'warning' },
  SUCCEEDED: { label: '已完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
  CANCELLED: { label: '已取消', type: 'info' }
}
const RULE_FIELDS = [
  { key: 'categoryLinks', label: '分类链接', placeholder: "如 //ul[@class='channel-nav-list']/li/a", siteOnly: true },
  { key: 'bookLinks', label: '书籍链接', placeholder: "如 //ul[@class='seeWell cf']/li/span/a[1]", siteOnly: true },
  { key: 'listNext', label: '分类下一页', placeholder: '分类列表分页：「下一页」的 <a>', siteOnly: true },
  { key: 'tocLink', label: '目录链接', placeholder: "如 //div[@class='b-oper']/a[@class='reader']", siteOnly: true },
  { key: 'chapterLinks', label: '章节链接', placeholder: "如 //div[@id='list']//dd/a" },
  { key: 'content', label: '正文', placeholder: "如 //div[@id='content']" },
  { key: 'bookName', label: '书名', placeholder: '如 //h1/text()' },
  { key: 'author', label: '作者', placeholder: "如 //meta[@property='og:novel:author']/@content" },
  { key: 'intro', label: '简介', placeholder: "如 //div[@id='intro']//text()" },
  { key: 'tocNext', label: '目录下一页', placeholder: '目录分多页时：「下一页」的 @href' },
  { key: 'contentNext', label: '正文下一页', placeholder: '一章分多页时：「下一页」的 @href' },
  { key: 'encoding', label: '编码', placeholder: '留空自动识别，如 gbk' }
]
const POLL_MS = 3000

const router = useRouter()
const mode = ref('book')
const presets = ref([])
const form = reactive(emptyForm())
const site = reactive(emptySite())
const advancedOpen = ref([])
const previewing = ref(false)
const preview = ref(null)
const discovering = ref(false)
const siteResult = ref(null)
const selectedBooks = ref([])
const booksTableRef = ref(null)
const range = reactive({ start: 1, end: 1 })
const submitting = ref(false)
const loading = ref(false)
const tasks = ref([])
const booksDlg = reactive({ visible: false, crawl: null, title: '', books: [], loading: false })
const extractDlg = reactive({ visible: false, fileId: null, fileName: '' })
let timer = null

function emptyForm() {
  return {
    url: '',
    preset: '',
    delayMs: 1000,
    respectRobots: true,
    rule: Object.fromEntries(RULE_FIELDS.map((f) => [f.key, ''])),
    removeText: ''
  }
}

function emptySite() {
  return { maxBooks: 20, maxCategories: 10, maxListPages: 5, maxChaptersPerBook: 0, verify: true, categoriesText: '' }
}

const tipText = computed(() =>
  mode.value === 'book'
    ? '填写一本小说的「章节目录页」地址，抓取后合并为一个 txt 存入文件管理，可直接发起小说提取。请只抓取你有权使用的内容，并保持合理的请求间隔。'
    : '复刻 copybook 的整站采集：填写站点首页（或分类列表页）→ 发现书籍（分类 → 列表翻页 → 书籍详情 → 目录）→ 勾选要抓的书。每本存为一个 txt，请只抓取你有权使用的内容，并保持合理的请求间隔。'
)

const currentPreset = computed(() => presets.value.find((p) => p.key === form.preset))
const presetRule = computed(() => currentPreset.value?.rule || {})
const ruleFields = computed(() => RULE_FIELDS.filter((f) => mode.value === 'site' || !f.siteOnly))
const estimate = computed(() => {
  const secs = Math.max(range.end - range.start + 1, 0) * (form.delayMs / 1000)
  return secs < 120 ? `${Math.ceil(secs)} 秒` : `${Math.ceil(secs / 60)} 分钟`
})

function presetName(key) {
  return presets.value.find((p) => p.key === key)?.name || key
}

/** 表单 → 后端参数：只带非空的自定义规则字段；整站模式带上发现上限 */
function buildOptions() {
  const rule = Object.fromEntries(Object.entries(form.rule).filter(([, v]) => v && v.trim()).map(([k, v]) => [k, v.trim()]))
  const removePatterns = form.removeText.split('\n').map((s) => s.trim()).filter(Boolean)
  if (removePatterns.length) rule.removePatterns = removePatterns
  const options = {
    url: form.url.trim(),
    mode: mode.value,
    preset: form.preset,
    delayMs: form.delayMs,
    respectRobots: form.respectRobots,
    ...(Object.keys(rule).length ? { rule } : {})
  }
  if (mode.value === 'site') {
    options.maxBooks = site.maxBooks
    options.maxCategories = site.maxCategories
    options.maxListPages = site.maxListPages
    options.verify = site.verify
    const categories = site.categoriesText.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
    if (categories.length) options.categories = categories
  }
  return options
}

function onModeChange() {
  preview.value = null
  siteResult.value = null
  selectedBooks.value = []
}

async function loadPresets() {
  try {
    const res = await listCrawlPresets()
    if (res.code === 0) presets.value = res.data || []
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载抓取规则失败（AI 服务是否已启动？）'))
  }
}

async function doPreview() {
  if (!form.url) return
  previewing.value = true
  preview.value = null
  try {
    const res = await previewCrawl(buildOptions())
    if (res.code !== 0) {
      ElMessage.error(res.message || '解析失败')
      return
    }
    preview.value = res.data
    range.start = 1
    range.end = res.data.chapterCount
  } catch (e) {
    ElMessage.error(errorMessage(e, '解析目录失败'))
  } finally {
    previewing.value = false
  }
}

async function doSubmit() {
  submitting.value = true
  try {
    const res = await submitCrawl({ ...buildOptions(), startIndex: range.start, endIndex: range.end })
    if (res.code !== 0) {
      ElMessage.error(res.message || '提交失败')
      return
    }
    ElMessage.success('已开始抓取')
    preview.value = null
    await loadTasks()
    schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交抓取任务失败'))
  } finally {
    submitting.value = false
  }
}

/** 整站：发现书籍（首页 → 分类 → 列表翻页 → 书籍详情 → 目录），同步返回清单 */
async function doDiscover() {
  if (!form.url) return
  discovering.value = true
  siteResult.value = null
  selectedBooks.value = []
  try {
    const res = await discoverCrawl(buildOptions())
    if (res.code !== 0) {
      ElMessage.error(res.message || '发现失败')
      return
    }
    siteResult.value = res.data
    const books = res.data.books || []
    ElMessage.success(`发现 ${books.length} 本书，已默认全选（可取消勾选）`)
    await nextTick()
    books.forEach((b) => {
      if (b.tocUrl) booksTableRef.value?.toggleRowSelection(b, true)
    })
  } catch (e) {
    ElMessage.error(errorMessage(e, '整站发现失败（书多时需要较久，可先调小「整站上限」）'))
  } finally {
    discovering.value = false
  }
}

function onBookSelect(rows) {
  selectedBooks.value = rows.filter((b) => b.tocUrl)
}

function selectAllBooks() {
  (siteResult.value?.books || []).forEach((b) => {
    if (b.tocUrl) booksTableRef.value?.toggleRowSelection(b, true)
  })
}

/** 整站：把勾选的书提交给 Java，逐本抓取、每本一个 txt */
async function doSubmitSite() {
  if (!selectedBooks.value.length) return
  submitting.value = true
  try {
    const books = selectedBooks.value.map((b) => ({
      tocUrl: b.tocUrl,
      bookName: b.bookName,
      author: b.author,
      category: b.category
    }))
    const res = await submitSiteCrawl({
      ...buildOptions(),
      maxChaptersPerBook: site.maxChaptersPerBook,
      books
    })
    if (res.code !== 0) {
      ElMessage.error(res.message || '提交失败')
      return
    }
    ElMessage.success(`已开始整站抓取：${books.length} 本`)
    siteResult.value = null
    selectedBooks.value = []
    await loadTasks()
    schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交整站抓取任务失败'))
  } finally {
    submitting.value = false
  }
}

const isActive = (t) => t.status === 'QUEUED' || t.status === 'RUNNING'

async function loadTasks() {
  loading.value = true
  try {
    const res = await listCrawls()
    if (res.code === 0) tasks.value = res.data || []
    else ElMessage.error(res.message || '加载失败')
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载抓取任务失败'))
  } finally {
    loading.value = false
  }
  // 明细弹窗打开且任务仍在跑时，顺手刷新书籍列表
  if (booksDlg.visible && booksDlg.crawl && isActive(booksDlg.crawl)) {
    const latest = tasks.value.find((t) => t.id === booksDlg.crawl.id)
    if (latest) booksDlg.crawl = latest
    loadBooks()
  }
}

/** 有进行中的任务时定时刷新，全部结束后停止 */
function schedulePoll() {
  stopPoll()
  timer = setTimeout(async () => {
    await loadTasks()
    if (tasks.value.some(isActive)) schedulePoll()
  }, POLL_MS)
}

function stopPoll() {
  if (timer) clearTimeout(timer)
  timer = null
}

async function doCancel(row) {
  try {
    const res = await cancelCrawl(row.id)
    if (res.code !== 0) ElMessage.error(res.message || '取消失败')
    await loadTasks()
  } catch (e) {
    ElMessage.error(errorMessage(e, '取消失败'))
  }
}

async function doRetry(row) {
  try {
    const res = await retryCrawl(row.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '提交失败')
      return
    }
    ElMessage.success('已重新开始抓取')
    await loadTasks()
    schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '重新抓取失败'))
  }
}

async function openBooks(row) {
  booksDlg.visible = true
  booksDlg.crawl = row
  booksDlg.title = `${row.url} · ${row.bookDone || 0}/${row.bookTotal || 0} 本已完成`
  await loadBooks()
}

async function loadBooks() {
  if (!booksDlg.crawl) return
  booksDlg.loading = true
  try {
    const res = await listCrawlBooks(booksDlg.crawl.id)
    if (res.code === 0) booksDlg.books = res.data || []
    else ElMessage.error(res.message || '加载书籍明细失败')
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载书籍明细失败'))
  } finally {
    booksDlg.loading = false
  }
}

/** 把旧任务的参数填回表单（可改规则 / 范围后再解析） */
function reuseOptions(row) {
  const o = row.options || {}
  mode.value = o.mode === 'site' ? 'site' : 'book'
  Object.assign(form, emptyForm(), {
    url: o.url || row.url,
    preset: o.preset || '',
    delayMs: o.delayMs || 1000,
    respectRobots: o.respectRobots !== false
  })
  Object.assign(site, emptySite(), {
    maxBooks: o.maxBooks || 20,
    maxCategories: o.maxCategories || 10,
    maxListPages: o.maxListPages || 5,
    maxChaptersPerBook: o.maxChaptersPerBook || 0,
    verify: o.verify !== false,
    categoriesText: (o.categories || []).join(',')
  })
  const rule = o.rule || {}
  RULE_FIELDS.forEach((f) => (form.rule[f.key] = rule[f.key] || ''))
  form.removeText = (rule.removePatterns || []).join('\n')
  if (Object.keys(rule).length) advancedOpen.value = ['adv']
  preview.value = null
  siteResult.value = null
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function openExtract(row) {
  const name = row.bookName || '抓取小说'
  Object.assign(extractDlg, { visible: true, fileId: row.fileId, fileName: `${name}.txt` })
}

async function doExtract(options) {
  try {
    const res = await submitExtract(extractDlg.fileId, options)
    if (res.code !== 0) {
      ElMessage.error(res.message || '提交失败')
      return
    }
    ElMessage.success('已提交提取任务')
    router.push({ path: '/novel/extract', query: { id: res.data.id } })
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交提取任务失败'))
  }
}

// 页面被 keep-alive 缓存：进入时拉取并按需轮询，离开时停止轮询
onActivated(async () => {
  if (!presets.value.length) loadPresets()
  await loadTasks()
  if (tasks.value.some(isActive)) schedulePoll()
})
onDeactivated(stopPoll)
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.tasks {
  margin-top: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-ops {
  display: flex;
  align-items: center;
  gap: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.tip {
  margin-bottom: 16px;
}
.url-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.unit {
  margin-left: 6px;
  color: #606266;
  font-size: 13px;
}
.hint {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}
.hint.block {
  margin: 0 0 12px 104px;
}
.switch {
  margin-left: 16px;
}
.advanced {
  margin: 0 0 12px;
}
.preview {
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}
.cat-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 12px 0;
}
.intro {
  max-height: 80px;
  overflow: auto;
  white-space: pre-wrap;
}
.sample {
  margin: 16px 0;
}
.sample-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-weight: 600;
  color: #303133;
}
.sample-text {
  max-height: 200px;
  overflow: auto;
  margin: 8px 0 0;
  padding: 10px 12px;
  background: #f7f8fa;
  border-radius: 4px;
  white-space: pre-wrap;
  font-family: inherit;
  line-height: 1.7;
}
.range {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}
.range-sep {
  margin: 0 8px;
}
.dialog-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.ml6 {
  margin-left: 6px;
}
</style>
