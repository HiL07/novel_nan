<template>
  <!-- 解析管理：一条 AI 解析记录的详情（成功 / 失败、每次尝试、站点结构、规则、样本） -->
  <el-dialog :model-value="modelValue" width="1080px" top="4vh" append-to-body class="rule-detail-dlg" @update:model-value="(v) => emit('update:modelValue', v)">
    <template #header>
      <div v-if="rule" class="dlg-head">
        <el-tag :type="STATUS[rule.status]?.type" effect="dark">{{ STATUS[rule.status]?.label || rule.status }}</el-tag>
        <span class="dlg-title">{{ rule.siteName || rule.host }}</span>
        <span class="meta">{{ rule.updateTime }}</span>
      </div>
    </template>

    <template v-if="rule">
      <el-alert v-if="failed" type="error" :closable="false" show-icon class="banner" :title="`解析失败：尝试了 ${rule.attempts || attempts.length} 次都没有抓通`">
        <div class="banner-text">{{ rule.error || '（没有记录失败原因）' }}</div>
      </el-alert>
      <el-alert v-else type="success" :closable="false" show-icon class="banner" :title="successTitle">
        <div v-if="rule.summary" class="banner-text">{{ rule.summary }}</div>
      </el-alert>

      <div class="stats">
        <div class="stat">
          <div class="stat-label">尝试</div>
          <div class="stat-value">
            {{ attempts.length || rule.attempts || 0 }} 次
            <span v-if="attempts.length" class="stat-sub">
              <span class="ok">成功 {{ okCount }}</span> · <span class="err">失败 {{ attempts.length - okCount }}</span>
            </span>
          </div>
        </div>
        <div class="stat">
          <div class="stat-label">目录</div>
          <div class="stat-value" :class="{ err: !rule.chapterCount }">{{ rule.chapterCount || 0 }} 章</div>
          <div class="stat-sub ellipsis">{{ rule.bookName || '-' }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">站点规律掌握</div>
          <div v-if="rule.siteMap?.items" class="stat-value" :class="rule.siteMap.failed ? 'warn' : 'ok'">
            {{ rule.siteMap.mastered }}/{{ rule.siteMap.total }} 项
          </div>
          <div v-else class="stat-value meta">{{ failed ? '未验证' : '旧记录未验证' }}</div>
        </div>
        <div class="stat wide">
          <div class="stat-label">Token</div>
          <TokenUsageBar v-if="log?.usage" :usage="log.usage" />
          <div v-else class="meta">未记录</div>
        </div>
      </div>

      <el-descriptions :column="2" border size="small" class="info">
        <el-descriptions-item label="解析入口">
          <a :href="rule.sampleUrl" target="_blank" rel="noopener noreferrer" class="mono">{{ rule.sampleUrl }}</a>
        </el-descriptions-item>
        <el-descriptions-item label="站点首页">
          <a v-if="rule.homeUrl" :href="rule.homeUrl" target="_blank" rel="noopener noreferrer" class="mono">{{ rule.homeUrl }}</a>
          <span v-else class="meta">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="目录页"><span class="mono">{{ rule.tocUrl || '-' }}</span></el-descriptions-item>
        <el-descriptions-item label="解析方式">
          <template v-if="!failed">{{ STRATEGY[rule.strategy] || rule.strategy || '-' }} · 第 {{ rule.attempts }} 次成功</template>
          <span v-else class="err">未成功</span>
        </el-descriptions-item>
      </el-descriptions>

      <el-tabs v-model="tab" class="tabs">
        <el-tab-pane name="attempts">
          <template #label>
            每次尝试
            <el-tag v-if="attempts.length" size="small" :type="failed ? 'danger' : 'success'" class="ml6">{{ okCount }}/{{ attempts.length }}</el-tag>
          </template>
          <AttemptTable v-if="attempts.length" :attempts="attempts" />
          <el-empty v-else :image-size="56" description="这条是旧记录，当时没有保存每次尝试的过程；重新解析一次即可看到" />
        </el-tab-pane>
        <el-tab-pane name="site" :disabled="failed">
          <template #label>
            站点结构
            <el-tag v-if="rule.siteMap?.items" size="small" :type="rule.siteMap.failed ? 'warning' : 'success'" class="ml6">
              {{ rule.siteMap.mastered }}/{{ rule.siteMap.total }}
            </el-tag>
          </template>
          <SiteMapView :site-map="rule.siteMap" :home-url="rule.homeUrl" />
        </el-tab-pane>
        <el-tab-pane label="规则与地址规律" name="rule" :disabled="failed">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="书籍地址"><span class="mono">{{ rule.bookUrlPattern || '-' }}</span></el-descriptions-item>
            <el-descriptions-item label="目录地址"><span class="mono">{{ rule.tocUrlPattern || '-' }}</span></el-descriptions-item>
            <el-descriptions-item label="章节地址"><span class="mono">{{ rule.chapterUrlPattern || '-' }}</span></el-descriptions-item>
            <el-descriptions-item label="站内搜索">
              <template v-if="rule.siteMap?.search">
                <el-tag size="small" :type="rule.siteMap.search.works ? 'success' : 'warning'">
                  {{ rule.siteMap.search.works ? `已验证：搜「${rule.siteMap.search.testKeyword}」能搜到` : `能提交，但搜「${rule.siteMap.search.testKeyword}」没搜到` }}
                </el-tag>
                <div class="mono">{{ rule.siteMap.search.pattern }}</div>
                <div class="meta">
                  页面编码 {{ rule.siteMap.search.charset || '自动' }}（中文书名按这个编码提交）
                </div>
              </template>
              <span v-else class="meta">{{ searchItem?.detail || '没有学到（旧记录未探查，重新解析一次即可）' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="规则文件">
              <code v-if="rule.ruleFile">data/{{ rule.ruleFile }}</code><span v-else class="meta">-</span>
            </el-descriptions-item>
          </el-descriptions>
          <div class="sub-title">XPath 规则</div>
          <el-table v-if="ruleRows.length" :data="ruleRows" size="small">
            <el-table-column prop="key" label="字段" width="140" />
            <el-table-column label="XPath / 值">
              <template #default="{ row }"><span class="mono">{{ row.value }}</span></template>
            </el-table-column>
          </el-table>
          <div v-else class="meta">内置规则 / 自动识别即可，没有自定义 XPath</div>
        </el-tab-pane>
        <el-tab-pane label="抓取样本" name="sample" :disabled="failed">
          <template v-if="log?.chapterTitles?.length || log?.sample">
            <div v-if="log.chapterTitles?.length" class="chapters">
              <div class="sub-title">目录（{{ rule.chapterCount }} 章）</div>
              <el-tag v-for="(t, i) in log.chapterTitles" :key="i" size="small" type="info">{{ t }}</el-tag>
            </div>
            <div v-if="log.sample" class="sample">
              <div class="sub-title">
                首章：{{ log.sample.title }}
                <el-tag size="small" :type="log.sample.error ? 'danger' : log.sample.chars < 200 ? 'warning' : 'success'">
                  {{ log.sample.error ? '失败' : `${log.sample.chars} 字` }}
                </el-tag>
              </div>
              <div v-if="log.sample.error" class="err">{{ log.sample.error }}</div>
              <pre v-else class="sample-text">{{ log.sample.text }}</pre>
            </div>
          </template>
          <el-empty v-else :image-size="56" description="旧记录没有保存样本；重新解析一次即可看到" />
        </el-tab-pane>
      </el-tabs>
    </template>

    <template #footer>
      <div v-if="rule" class="footer">
        <el-button @click="act('reanalyze')">重新解析</el-button>
        <template v-if="rule.status === 'PENDING'">
          <el-button @click="act('use')">试用（单本）</el-button>
          <el-button @click="act('auto')">全自动</el-button>
          <el-button type="danger" plain @click="act('reject')">不确认</el-button>
          <el-button type="success" @click="act('confirm')">确认</el-button>
        </template>
        <template v-else-if="rule.status === 'CONFIRMED'">
          <el-button type="danger" plain @click="act('remove')">删除</el-button>
          <el-button @click="act('use')">使用（单本）</el-button>
          <el-button type="primary" @click="act('auto')">全自动抓取</el-button>
        </template>
        <el-button v-else type="danger" plain @click="act('reject')">删除记录</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import TokenUsageBar from '@/components/ai/TokenUsageBar.vue'
import AttemptTable from './AttemptTable.vue'
import SiteMapView from './SiteMapView.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  rule: { type: Object, default: null }
})
// action：confirm / reject / remove / use / auto / reanalyze，由父页面处理（与列表里的按钮相同）
const emit = defineEmits(['update:modelValue', 'action'])

const STATUS = {
  PENDING: { label: '待确认', type: 'warning' },
  CONFIRMED: { label: '已确认', type: 'success' },
  FAILED: { label: '解析失败', type: 'danger' }
}
const STRATEGY = { learned: '已学到的规则', preset: '内置规则', ai: 'AI 写规则' }

const tab = ref('attempts')
const failed = computed(() => props.rule?.status === 'FAILED')
const log = computed(() => props.rule?.attemptLog || null)
const attempts = computed(() => log.value?.attempts || [])
const okCount = computed(() => attempts.value.filter((a) => a.ok).length)
const searchItem = computed(() => (props.rule?.siteMap?.items || []).find((i) => i.key === 'search') || null)
const ruleRows = computed(() =>
  Object.entries(props.rule?.rule || {})
    .filter(([, v]) => v && (!Array.isArray(v) || v.length))
    .map(([key, v]) => ({ key, value: Array.isArray(v) ? v.join(' | ') : v }))
)
const successTitle = computed(() => {
  const r = props.rule
  if (!r) return ''
  const sm = r.siteMap?.items ? `；站点规律掌握 ${r.siteMap.mastered}/${r.siteMap.total} 项` : ''
  return `解析成功：第 ${r.attempts || 1} 次尝试抓通（${STRATEGY[r.strategy] || r.strategy || '-'}），目录 ${r.chapterCount || 0} 章${sm}`
})

// 每次打开都回到「每次尝试」
watch(
  () => [props.modelValue, props.rule?.id],
  () => {
    if (props.modelValue) tab.value = 'attempts'
  }
)

function act(name) {
  emit('action', name, props.rule)
}
</script>

<style scoped>
.dlg-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dlg-title {
  font-size: 17px;
  font-weight: 600;
  color: #303133;
}
.banner {
  margin-bottom: 14px;
}
.banner-text {
  margin-top: 4px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
.stats {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 2fr;
  gap: 12px;
  margin-bottom: 14px;
}
.stat {
  padding: 12px 14px;
  background: #f7f8fa;
  border-radius: 8px;
  min-width: 0;
}
.stat-label {
  color: #909399;
  font-size: 12px;
  margin-bottom: 6px;
}
.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
.stat-sub {
  margin-left: 6px;
  font-size: 12px;
  font-weight: normal;
  color: #606266;
}
.stat .stat-sub.ellipsis {
  margin: 4px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.info {
  margin-bottom: 6px;
}
.tabs {
  min-height: 260px;
}
.sub-title {
  margin: 12px 0 8px;
  font-weight: 600;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 8px;
}
.chapters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chapters .sub-title {
  width: 100%;
}
.sample-text {
  max-height: 260px;
  overflow: auto;
  margin: 0;
  padding: 10px 12px;
  background: #f7f8fa;
  border-radius: 4px;
  white-space: pre-wrap;
  font-family: inherit;
  line-height: 1.7;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.mono {
  font-family: Consolas, monospace;
  word-break: break-all;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.ok {
  color: #67c23a;
}
.warn {
  color: #e6a23c;
}
.err {
  color: #f56c6c;
}
.ml6 {
  margin-left: 6px;
}
</style>
