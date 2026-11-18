<template>
  <div class="xw">
    <!-- 顶栏 -->
    <header class="xw-head">
      <el-button text :icon="ArrowLeft" @click="router.push('/novel/extract')">退出</el-button>
      <span class="xw-title" :title="fileName">{{ title || bookName }}</span>
      <el-dropdown v-if="taskId" trigger="click" @command="onCommand">
        <el-button text size="small" :icon="MoreFilled" title="改名 / 删除" />
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="rename" :icon="EditPen">改名</el-dropdown-item>
            <el-dropdown-item command="delete" :icon="Delete" divided>删除工作区</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <template v-if="started">
        <!-- 三个工作区：提取（原文 / 逐章 / 全书实体）→ 卡片整理 → 素材选择 -->
        <el-radio-group v-model="mode" class="xw-mode">
          <el-radio-button value="extract">提取工作区</el-radio-button>
          <el-radio-button value="cards">卡片整理</el-radio-button>
          <el-radio-button value="materials">素材选择</el-radio-button>
        </el-radio-group>
        <el-tag :type="statusTag.type" size="small">{{ statusTag.label }}</el-tag>
        <el-progress v-if="task.status !== 'SUCCEEDED'" class="xw-progress" :percentage="task.progress || 0" :stroke-width="6" />
        <span class="xw-msg" :title="task.message">{{ task.message }}</span>
        <template v-if="mode === 'extract'">
        <el-radio-group v-if="hasCards" v-model="view" size="small">
          <el-radio-button value="chapter">逐章</el-radio-button>
          <el-radio-button value="breakdown">全书实体</el-radio-button>
        </el-radio-group>
        <el-switch v-if="isActive && view === 'chapter'" v-model="live.follow.value" size="small" active-text="跟随最新章" />
        <el-popover v-if="canExtend" v-model:visible="extendOpen" placement="bottom-end" :width="380" trigger="click">
          <template #reference>
            <el-button size="small" title="已读的章不重读，接着往后读">继续提取…</el-button>
          </template>
          <div class="extend-box">
            <div class="extend-row">
              读到第 <el-input-number v-model="extendTo" :min="rangeEnd + 1" :max="total" size="small" controls-position="right" /> 章
            </div>
            <div class="range-quick">
              <el-button v-for="n in [50, 200]" v-show="rangeEnd + n < total" :key="n" size="small" link type="primary" @click="extendTo = rangeEnd + n">
                再读 {{ n }} 章
              </el-button>
              <el-button size="small" link type="primary" @click="extendTo = total">读到最后（第 {{ total }} 章）</el-button>
            </div>
            <p class="muted">{{ extendText }}</p>
            <p class="muted warn">已读的第 {{ range.from }}–{{ rangeEnd }} 章不重读，伏笔编号、主角状态、实体档案接着往下走；结果会重新生成，之前「写回实体档案」的合并和手动修改会被替换（合并选择还记着，读完可以再写回一次）。已有的卡片不会丢，读完后在「卡片整理」里再整理一次即可更新。</p>
            <el-button type="primary" size="small" :loading="busy === 'extend'" @click="doExtend">继续提取</el-button>
          </div>
        </el-popover>
        <template v-if="task.status === 'INTERRUPTED'">
          <el-button size="small" type="primary" :loading="busy === 'resume'" @click="act('resume')">继续</el-button>
          <el-button size="small" type="danger" plain :loading="busy === 'cancel'" @click="act('cancel')">取消</el-button>
        </template>
        <template v-else-if="isActive">
          <el-button size="small" :loading="busy === 'pause'" @click="act('pause')">暂停</el-button>
          <el-button size="small" type="danger" plain :loading="busy === 'cancel'" @click="act('cancel')">取消</el-button>
        </template>
        <el-button v-if="resultObj" size="small" title="章节分析：摘要 / 人物 / 事件 / 伏笔 / 文风，可修改、下载 JSON" @click="resultOpen = true">
          提取结果
        </el-button>
        </template>
      </template>
      <template v-else-if="taskId">
        <el-tag type="info" size="small">未开始</el-tag>
        <span class="xw-msg">
          在左边选要提取的章节范围，右边设置好后「开始提取」；中间可以先翻原文看看分章对不对。设置会自动保存{{ draftSaved ? '（已保存）' : '' }}，
          退出后在「小说提取 → 提取中」里还能找到
        </span>
      </template>
    </header>

    <div v-show="!started || mode === 'extract'" class="xw-body">
      <!-- 左：章节 -->
      <aside class="xw-left">
        <div class="range-box">
          <template v-if="!started && live.chapters.value.length">
            <div class="range-row">
              第 <el-input-number v-model="pick.from" :min="1" :max="total" size="small" controls-position="right" @change="fixRange('from')" />
              – <el-input-number v-model="pick.to" :min="1" :max="total" size="small" controls-position="right" @change="fixRange('to')" /> 章
            </div>
            <div class="range-quick">
              <el-button size="small" link type="primary" @click="setPick(1, total)">全书</el-button>
              <el-button v-for="n in QUICK.filter((q) => q < total)" :key="n" size="small" link type="primary" @click="setPick(1, n)">
                前 {{ n }} 章
              </el-button>
            </div>
            <div class="muted">共 {{ total }} 章，选了 {{ pick.to - pick.from + 1 }} 章 · 约 {{ Math.round(pickChars / 1000) }} 千字。悬停一章可设为起点 / 终点</div>
          </template>
          <div v-else-if="started" class="muted">
            {{ rangeText }}<template v-if="liveReady">，已读 {{ doneCount }} 章</template>
          </div>
          <div v-if="canReread" class="reread-row">
            <el-switch v-model="rereadMode" size="small" active-text="重新提取" title="勾选要重新提取的章（可全选），其他章不动" />
            <template v-if="rereadMode">
              <el-button size="small" link type="primary" @click="pickAllReread">{{ rereadPick.length && rereadPick.length === rereadable.length ? '全不选' : '全选' }}</el-button>
              <el-button size="small" type="primary" plain :disabled="!rereadPick.length" :loading="busy === 'reread'" @click="doReread">
                重新提取选中（{{ rereadPick.length }}）
              </el-button>
            </template>
          </div>
          <div v-if="split.warnings.length" class="muted warn">{{ split.warnings.join('；') }}</div>
          <div v-if="split.error" class="muted warn">{{ split.error }}</div>
        </div>
        <div ref="listEl" class="ch-list">
          <div v-if="split.loading" class="muted pad">正在分章…</div>
          <div
            v-for="c in live.chapters.value"
            :key="c.idx"
            class="ch-item"
            :class="{ active: c.idx === live.selected.value, out: !inPick(c.idx) }"
            :data-idx="c.idx"
            @click="live.select(c.idx, true)"
          >
            <span class="dot" :class="`s-${chState(c.idx)}`" :title="STATE_LABELS[chState(c.idx)]">
              <el-icon v-if="chState(c.idx) === 'reading'" class="is-loading"><Loading /></el-icon>
            </span>
            <el-checkbox
              v-if="rereadMode && ['done', 'failed', 'partial'].includes(chState(c.idx))"
              :model-value="rereadPick.includes(c.idx)"
              size="small"
              @click.stop
              @change="toggleReread(c.idx)"
            />
            <span class="ch-title" :title="c.title">{{ c.idx + 1 }}. {{ c.title }}</span>
            <span v-if="started && live.badges(c.idx)" class="ch-badges">{{ live.badges(c.idx) }}</span>
            <span v-if="!started" class="ch-pick">
              <el-button size="small" link type="primary" title="从这一章开始" @click.stop="setPick(c.idx + 1, Math.max(pick.to, c.idx + 1))">起</el-button>
              <el-button size="small" link type="primary" title="读到这一章为止" @click.stop="setPick(Math.min(pick.from, c.idx + 1), c.idx + 1)">止</el-button>
            </span>
          </div>
        </div>
      </aside>

      <!-- 拆书视图：占中间和右栏 -->
      <main v-if="view === 'breakdown'" class="xw-breakdown">
        <BreakdownView
          :pacing="live.pacing.value"
          :threads="live.threads.value"
          :rows="live.rows"
          :chapters="live.chapters.value"
          :base="(live.range.value?.from || 1) - 1"
          :entities="live.entities.value"
          :appear="live.appear.value"
          :extract-id="taskId"
          :can-apply="!!resultObj"
          @jump="jump"
          @apply="applyEntities"
        />
      </main>

      <!-- 中：原文 -->
      <main v-show="view === 'chapter'" ref="textEl" class="xw-text">
        <div v-if="live.textLoading.value" class="muted">正在读取原文…</div>
        <div v-else-if="live.textError.value" class="muted warn">{{ live.textError.value }}</div>
        <template v-else-if="live.paragraphs.value.length">
          <h2 class="text-title">{{ live.chapterText.value.title }}</h2>
          <div v-if="!started && !inPick(live.selected.value)" class="muted out-tip">这一章不在要提取的范围里</div>
          <div
            v-for="(p, pi) in live.paragraphs.value"
            :key="pi"
            class="para"
            :class="p.node != null ? `node node-${p.node % 2}` : ''"
          >
            <div v-if="p.nodeHead" class="node-head" :class="{ hot: p.nodeHead.hot }">
              {{ p.nodeHead.title }}<span class="node-text">{{ p.nodeHead.text }}</span>
            </div>
            <template v-for="(seg, si) in p.segs" :key="si">
              <span
                v-if="seg.mark"
                class="mark"
                :class="[`m-${seg.mark.kind}`, { on: seg.mark.id === live.activeMark.value }]"
                :data-mark="seg.mark.id"
                :title="seg.mark.label"
                @click="live.pickMark(seg.mark.id, 'text')"
              >{{ seg.text }}</span>
              <template v-else>{{ seg.text }}</template>
            </template>
          </div>
        </template>
        <div v-else class="muted">点左边的章看原文</div>
      </main>

      <!-- 右：设置 / 本章 -->
      <aside v-show="view === 'chapter'" class="xw-right">
        <el-tabs v-model="rightTab" class="xw-tabs">
          <el-tab-pane label="提取设置" name="opts">
            <template v-if="!started">
              <ExtractOptionsForm ref="formRef" :chars="pickChars" @change="queueSave" />
              <div v-if="formRef && !formRef.enabled" class="muted warn">不记录设定实体时做的是旧版章节分析：读全书，章节范围不起作用，也没有逐章卡片</div>
              <el-button type="primary" class="start-btn" :disabled="!formRef?.canStart || !fileId" :loading="starting" @click="start">
                开始提取（第 {{ pick.from }}–{{ pick.to }} 章）
              </el-button>
            </template>
            <el-descriptions v-else :column="1" border size="small">
              <el-descriptions-item label="提取模型">{{ modelText(options?.model) }}</el-descriptions-item>
              <el-descriptions-item label="素材提取">{{ materialText(options?.materials) }}</el-descriptions-item>
              <el-descriptions-item label="创建 / 更新">{{ task.createTime }} / {{ task.updateTime }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
          <el-tab-pane label="本章" name="card" :disabled="!started">
            <div class="card-pane">
              <div class="legend">
                <span v-for="(k, code) in KINDS" :key="code" class="mark" :class="`m-${code}`">{{ k }}</span>
              </div>
              <el-alert v-if="live.liveError.value" type="warning" :closable="false" :title="live.liveError.value" />
              <el-alert
                v-if="live.row.value?.status === 'failed'"
                type="error"
                :closable="false"
                show-icon
                :title="`这一章提取失败：${live.row.value.error || '未知原因'}`"
              />
              <template v-if="live.card.value">
                <div v-if="live.card.value.oneLine" class="one-line">{{ live.card.value.oneLine }}</div>
                <div class="tags">
                  <el-tag v-if="live.card.value.function" size="small">{{ live.card.value.function }}</el-tag>
                  <span v-if="live.emotionText.value" class="muted">情绪：{{ live.emotionText.value }}</span>
                  <span v-if="live.row.value?.status === 'partial'" class="muted">（超长章，还在读后面几份）</span>
                </div>
                <section v-if="live.card.value.events?.length">
                  <h4>关键事件</h4>
                  <ol class="events"><li v-for="(e, i) in live.card.value.events" :key="i">{{ e }}</li></ol>
                </section>
                <section v-for="sec in live.sections.value" :key="sec.title">
                  <h4>{{ sec.title }}（{{ sec.items.length }}）</h4>
                  <div
                    v-for="it in sec.items"
                    :key="it.id"
                    class="item"
                    :class="{ on: it.id === live.activeMark.value, clickable: it.mark, unverified: it.unverified }"
                    :data-item="it.id"
                    @click="it.mark && live.pickMark(it.id, 'card')"
                  >
                    <span class="item-head mark" :class="`m-${it.kind}`">{{ it.head }}</span>
                    <span>{{ it.text }}</span>
                    <div v-if="it.quote" class="quote">「{{ it.quote }}」</div>
                    <div v-else-if="it.unverified" class="quote">原文对不上，未核实</div>
                  </div>
                </section>
                <section v-if="live.card.value.golden">
                  <h4>黄金三章</h4>
                  <p class="golden"><b>开头钩子</b>{{ live.card.value.golden.hook300 }}</p>
                  <p class="golden"><b>人设</b>{{ live.card.value.golden.establish }}</p>
                  <p class="golden"><b>核心困境</b>{{ live.card.value.golden.dilemma }}</p>
                </section>
              </template>
              <div v-else-if="live.row.value?.status !== 'failed'" class="muted">{{ emptyCardText }}</div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </aside>
    </div>

    <!-- 卡片整理工作区 -->
    <!-- 卡片整理 / 素材选择：第一次打开时才挂载，之后切换只显示 / 隐藏（卡片多时重建一次要好几秒），切回来时刷新数据 -->
    <div v-if="started && visited.cards" v-show="mode === 'cards'" class="xw-pane xw-fixed">
      <CompileWorkspace
        ref="cardsRef"
        :key="taskId"
        :extract-id="taskId"
        :file-name="fileName"
        :chapter-count="resultObj?.chapterCount || range.to - range.from + 1 || total"
        :result="resultObj"
        :live-entities="task.status === 'INTERRUPTED' ? live.entities.value || [] : []"
        :read-chapters="doneCount"
        :total-chapters="range.to - range.from + 1"
        :extracting="task.status !== 'SUCCEEDED'"
        :status="task.status"
        :message="task.message"
        @saved="loadTask(taskId)"
        @go-extract="mode = 'extract'"
        @jump="(n) => ((mode = 'extract'), jump(n - 1))"
      />
    </div>

    <!-- 素材选择工作区：从卡片里挑 → 存进素材库（同书已有同名的逐条选：更新已有 / 作为可选版本） -->
    <div v-if="started && visited.materials" v-show="mode === 'materials'" class="xw-pane xw-fixed">
      <MaterialSelect ref="materialsRef" :key="taskId" :extract-id="taskId" />
    </div>

    <el-drawer v-model="resultOpen" :title="`提取结果 · ${bookName}`" size="60%" destroy-on-close>
      <ExtractResultPanel v-if="resultObj" :extract-id="taskId" :file-name="fileName" :result="resultObj" @saved="loadTask(taskId)" />
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onDeactivated, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Delete, EditPen, Loading, MoreFilled } from '@element-plus/icons-vue'
import { deleteWorkspace, renameWorkspace } from '@/components/material/extractWorkspaces'
import BreakdownView from '@/components/material/BreakdownView.vue'
import MaterialSelect from '@/components/material/MaterialSelect.vue'
import CompileWorkspace from '@/components/material/CompileWorkspace.vue'
import ExtractResultPanel from '@/components/material/ExtractResultPanel.vue'
import { estimateRead, fmtDuration } from '@/components/material/extractEstimate'
import ExtractOptionsForm from '@/components/material/ExtractOptionsForm.vue'
import { KINDS, STATE_LABELS, useExtractLive } from '@/components/material/extractLive'
import {
  bookOf,
  cancelExtract,
  getExtract,
  createExtractDraft,
  extendExtract,
  rereadExtract,
  pauseExtract,
  resumeExtract,
  saveExtractDraft,
  splitPreview,
  startExtract,
  updateExtractResult
} from '@/api/novel'
import { errorMessage } from '@/api/request'

/**
 * 提取工作区（/novel/extract/<任务id>，一本书一个；?tab=cards / materials 切到另两个工作区）：
 * 提取工作区：左 = 全书分章（开始前选范围，开始后看每章状态），中 = 原文（读完的章高亮摘抄），右 = 提取设置 / 本章卡；
 * 卡片整理：实体档案 → 这个工作区的卡片（CompileWorkspace，卡片 ≠ 素材）；素材选择：从卡片挑 → 素材库（MaterialSelect）。
 */
const route = useRoute()
const router = useRouter()
const QUICK = [10, 50, 200]

const taskId = ref(null)
const fileId = ref(null)
const fileName = ref('')
const task = reactive({ status: '', progress: 0, message: '', createTime: '', updateTime: '' })
const title = ref('') // 顶栏标题：「工作区名 · 《书名》」（没起名 = 空，显示书名）
let rawTitle = '' // 工作区名本身
const options = ref(null)
const rightTab = ref('opts')
const busy = ref('')
const starting = ref(false)
const formRef = ref(null)
const listEl = ref(null)
const textEl = ref(null)
const liveReady = ref(false)

const split = reactive({ fileId: null, loading: false, error: '', warnings: [] })
const pick = reactive({ from: 1, to: 1 })

const live = useExtractLive({
  fileId,
  onStatus: (d) => Object.assign(task, { status: d.status, progress: d.progress, message: d.message }),
  onFinished: () => {
    ElMessage.success('提取完成')
    loadTask(taskId.value)
  }
})

const bookName = computed(() => (fileName.value ? `《${bookOf(fileName.value)}》` : '小说提取'))
const total = computed(() => live.chapters.value.length)
const pickChars = computed(() => live.chapters.value.slice(pick.from - 1, pick.to).reduce((n, c) => n + (c.chars || 0), 0))
const isActive = computed(() => ['QUEUED', 'RUNNING'].includes(task.status))
// 已开始（不是「未开始」草稿）：左栏显示每章状态、右栏是本章卡；草稿时左栏选范围、右栏是设置
const started = computed(() => !!task.status && task.status !== 'DRAFT')
// 逐章（原文 + 本章卡）/ 拆书（全书统计）；只有记录了设定实体（有章节卡）的提取才有拆书视图
const view = ref('chapter')
const hasCards = computed(() => started.value && !!options.value?.materials)
watch(hasCards, (v) => !v && (view.value = 'chapter'))
const resultObj = ref(null) // 提取成功的结果（写回合并后的实体档案用）
const resultOpen = ref(false)
/* 顶部三个工作区，记在地址 ?tab= 里（刷新 / 返回保持） */
const MODES = ['extract', 'cards', 'materials']
const mode = ref(MODES.includes(route.query.tab) ? route.query.tab : 'extract')
const visited = reactive({ cards: false, materials: false }) // 打开过的工作区保留着，不再重建
const cardsRef = ref(null)
const materialsRef = ref(null)
watch(
  mode,
  (m, old) => {
    if (m === 'extract') return
    if (!visited[m]) {
      visited[m] = true // 第一次打开：组件挂载时自己加载
      return
    }
    if (old !== m) (m === 'cards' ? cardsRef : materialsRef).value?.reload?.() // 切回来：两边会互相改卡片状态，刷新一下
  },
  { immediate: true }
)
watch(taskId, () => {
  visited.cards = mode.value === 'cards'
  visited.materials = mode.value === 'materials'
})
watch(mode, (m) => {
  if (route.name !== 'extractWorkspace' || (route.query.tab || 'extract') === m) return
  router.replace({ query: { ...route.query, tab: m === 'extract' ? undefined : m } })
})
watch(
  () => route.query.tab,
  (t) => route.name === 'extractWorkspace' && (mode.value = MODES.includes(t) ? t : 'extract')
)

/* ---------- 接着读 / 重读这几章（提取成功或已暂停、记录了实体；断点不在时后端会提示） ---------- */
const range = computed(() => live.range.value || { from: 1, to: total.value, total: total.value })
const rangeEnd = computed(() => Math.min(total.value, options.value?.materials?.toChapter || total.value))
const canExtend = computed(() =>
  ['SUCCEEDED', 'INTERRUPTED'].includes(task.status) && !!options.value?.materials && !!options.value.materials.toChapter && rangeEnd.value < total.value
)
const canReread = computed(() => ['SUCCEEDED', 'INTERRUPTED'].includes(task.status) && !!options.value?.materials)
const extendOpen = ref(false)
const extendTo = ref(1)
watch(extendOpen, (v) => v && (extendTo.value = Math.min(total.value, rangeEnd.value + 50)))
const extendText = computed(() => {
  const add = live.chapters.value.slice(rangeEnd.value, extendTo.value)
  const chars = add.reduce((n, c) => n + (c.chars || 0), 0)
  const m = options.value?.materials || {}
  const src = options.value?.model?.source || 'api'
  const est = estimateRead(chars, { source: src, depth: m.depth, rounds: m.rounds })
  const tok = src === 'api' ? `，约 ${((est.input + est.output) / 1e6).toFixed(2)}M tokens` : ''
  return `新读 ${add.length} 章、约 ${Math.round(chars / 1000)} 千字，预计 ${fmtDuration(est.seconds)}${tok}（按这次提取的档位 / 遍数估算）`
})
async function doExtend() {
  busy.value = 'extend'
  try {
    const res = await extendExtract(taskId.value, extendTo.value >= total.value ? 0 : extendTo.value)
    if (res.code !== 0) throw new Error(res.message)
    extendOpen.value = false
    ElMessage.success('已开始继续提取')
    view.value = 'chapter'
    await loadTask(taskId.value)
  } catch (e) {
    ElMessage.error(errorMessage(e, '继续提取失败'))
  } finally {
    busy.value = ''
  }
}
const rereadMode = ref(false)
const rereadPick = ref([])
function toggleReread(idx) {
  rereadPick.value = rereadPick.value.includes(idx) ? rereadPick.value.filter((x) => x !== idx) : [...rereadPick.value, idx]
}
watch(rereadMode, (v) => !v && (rereadPick.value = []))
const rereadable = computed(() => live.chapters.value.map((c) => c.idx).filter((i) => ['done', 'failed', 'partial'].includes(chState(i))))
function pickAllReread() {
  rereadPick.value = rereadPick.value.length === rereadable.value.length ? [] : [...rereadable.value]
}
async function doReread() {
  const base = (range.value.from || 1) - 1
  const picked = [...rereadPick.value].sort((a, b) => a - b)
  try {
    await ElMessageBox.confirm(
      `重新提取${picked.length > 12 ? ` ${picked.length} 章（第 ${picked[0] + 1}–${picked[picked.length - 1] + 1} 章中选中的）` : `第 ${picked.map((i) => i + 1).join('、')} 章`}？只重读这几章，其他章不动；` +
        '结果会重新生成（之前写回的合并和手动修改会被替换）。后面章节对这几章旧伏笔的推进可能会丢失。已有的卡片不会丢，之后再整理一次即可更新。',
      '重新提取',
      { type: 'warning' }
    )
  } catch {
    return
  }
  busy.value = 'reread'
  try {
    const res = await rereadExtract(taskId.value, picked.map((idx) => idx - base))
    if (res.code !== 0) throw new Error(res.message)
    rereadMode.value = false
    ElMessage.success('已开始重新提取')
    view.value = 'chapter'
    await loadTask(taskId.value)
  } catch (e) {
    ElMessage.error(errorMessage(e, '重新提取失败'))
  } finally {
    busy.value = ''
  }
}

/** 全书实体里「写回实体档案」：整个结果写回（同实体档案的保存），done = 清掉已写进去的合并选择 */
async function applyEntities(entities, done, msg) {
  try {
    const res = await updateExtractResult(taskId.value, { ...resultObj.value, entities })
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(msg || `已写回实体档案：${entities.length} 个实体`)
    done?.()
    await loadTask(taskId.value)
    view.value = 'breakdown'
  } catch (e) {
    ElMessage.error(errorMessage(e, '写回实体档案失败'))
  }
}
function jump(idx) {
  view.value = 'chapter'
  live.follow.value = false
  live.select(idx, true)
}
const doneCount = computed(() => Object.values(live.rows).filter((r) => r.status === 'done').length)
const rangeText = computed(() => {
  const r = live.range.value
  if (!r) return options.value?.materials ? '' : '旧版章节分析（读全书，没有逐章卡片）'
  return r.from > 1 || r.to < r.total ? `提取第 ${r.from}–${r.to} 章（全书 ${r.total} 章）` : `提取全书 ${r.total} 章`
})
const statusTag = computed(() => {
  const map = {
    QUEUED: ['info', '排队中'], RUNNING: ['primary', '提取中'], INTERRUPTED: ['warning', '已暂停'],
    SUCCEEDED: ['success', '提取完成'], FAILED: ['danger', '失败 / 已取消']
  }
  const [type, label] = map[task.status] || ['info', task.status || '…']
  return { type, label }
})
const emptyCardText = computed(() => {
  const s = chState(live.selected.value)
  if (s === 'reading') return '正在读这一章…'
  if (s === 'pending') return '还没读到这一章'
  if (s === 'out') return '这一章不在提取范围里'
  if (!options.value?.materials) return '这次提取没有记录设定实体，没有逐章卡片'
  return '这一章没有章节卡'
})

function chState(idx) {
  if (!started.value) return inPick(idx) ? 'pending' : 'out'
  return live.stateOf(idx)
}
function inPick(idx) {
  return started.value ? live.inRange(idx) : idx >= pick.from - 1 && idx <= pick.to - 1
}
function setPick(from, to) {
  pick.from = Math.max(1, from)
  pick.to = Math.min(total.value, Math.max(pick.from, to))
}
function fixRange(which) {
  if (pick.from > pick.to) which === 'from' ? (pick.to = pick.from) : (pick.from = pick.to)
}

function modelText(m) {
  if (!m) return '大模型（启用中的配置）'
  if (m.source === 'gguf') return 'GGUF（llama.cpp）'
  if (m.source === 'local') return `本地模型 ${m.baseId}`
  return `大模型${m.configId ? `（配置 #${m.configId}）` : '（启用中的配置）'}`
}
function materialText(mt) {
  if (!mt) return '只做章节分析（不记录设定实体）'
  const depth = { fast: '快速', standard: '标准', deep: '深拆' }[mt.depth] || ''
  const cats = (mt.categories || []).length
  return `记录设定实体${depth ? `，${depth}档` : ''}，读 ${mt.rounds ?? 1} 遍，${cats} 个分类` + (mt.focus ? `，特别关注：${mt.focus}` : '')
}

/* ---------- 加载 ---------- */

async function loadSplit(id) {
  if (split.fileId === id && live.chapters.value.length) return
  Object.assign(split, { fileId: id, loading: true, error: '', warnings: [] })
  live.chapters.value = []
  try {
    const res = await splitPreview(id)
    if (res.code !== 0) throw new Error(res.message)
    live.setBook(res.data.chapters || [])
    split.warnings = res.data.warnings || []
  } catch (e) {
    split.fileId = null
    split.error = errorMessage(e, '分章失败（AI 服务没启动？）')
  } finally {
    split.loading = false
  }
}

async function loadTask(id) {
  try {
    const res = await getExtract(id)
    if (res.code !== 0) throw new Error(res.message)
    const t = res.data
    fileId.value = t.fileId
    fileName.value = t.fileName
    Object.assign(task, { status: t.status, progress: t.progress, message: t.message, createTime: t.createTime, updateTime: t.updateTime })
    title.value = t.title ? `${t.title} · 《${bookOf(t.fileName)}》` : ''
    rawTitle = t.title || ''
    try {
      options.value = t.options ? JSON.parse(t.options) : null
    } catch {
      options.value = null
    }
    await loadSplit(t.fileId)
    live.reset()
    resultObj.value = null
    if (t.status === 'DRAFT') {
      // 未开始：还原草稿里的章节范围和设置
      const m = options.value?.materials
      setPick(m?.fromChapter || 1, m?.toChapter || total.value)
      rightTab.value = 'opts'
      draftSaved.value = false
      await nextTick()
      formRef.value?.restore(options.value)
      if (live.selected.value == null && total.value) live.select(pick.from - 1)
      return
    }
    liveReady.value = !!options.value?.materials
    if (t.status === 'SUCCEEDED' && t.result) {
      let r = null
      try {
        r = JSON.parse(t.result)
      } catch {
        r = null
      }
      resultObj.value = r
      if (r?.chapterCards) live.fromResult(r)
    } else if (options.value?.materials) {
      const m = options.value.materials
      const from = m.fromChapter || 1
      live.range.value = { from, to: m.toChapter || total.value, total: total.value }
      live.startPoll(id)
    }
    if (live.selected.value == null && total.value) live.select(live.range.value ? live.range.value.from - 1 : 0)
    rightTab.value = options.value?.materials ? 'card' : 'opts'
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载提取任务失败'))
  }
}

async function load() {
  if (route.name !== 'extractWorkspace') return
  const id = route.params.id
  live.stopPoll()
  if (id === 'new') {
    // 旧地址 /novel/extract/new?fileId=：换成这个文件「未开始」的提取
    const fid = Number(route.query.fileId)
    if (!fid) {
      split.error = '没有指定文件：请从「文件管理」里点「提取」进来'
      return
    }
    try {
      const res = await createExtractDraft(fid)
      if (res.code !== 0) throw new Error(res.message)
      router.replace(`/novel/extract/${res.data.id}`)
    } catch (e) {
      split.error = errorMessage(e, '打开提取工作区失败')
    }
    return
  }
  taskId.value = Number(id)
  await loadTask(taskId.value)
}

watch(
  () => [route.params.id, route.query.fileId],
  () => load(),
  { immediate: true }
)
onActivated(() => {
  if (taskId.value && route.name === 'extractWorkspace' && ['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(task.status)) loadTask(taskId.value)
})
onDeactivated(() => {
  live.stopPoll()
  flushSave()
})

// 选中的章滚进左栏可见区；换章时原文回到顶部
watch(
  () => live.selected.value,
  (idx) => {
    if (textEl.value) textEl.value.scrollTop = 0
    nextTick(() => listEl.value?.querySelector(`[data-idx="${idx}"]`)?.scrollIntoView({ block: 'nearest' }))
  }
)

/* ---------- 操作 ---------- */

/* 未开始时的草稿：范围 / 设置一改就（800 ms 后）存到这条提取上，退出或刷新后还在 */
const draftSaved = ref(false)
let saveTimer = null
function rangeOf(materials) {
  if (!materials) return materials
  return { ...materials, fromChapter: pick.from, toChapter: pick.to >= total.value ? 0 : pick.to } // 0 = 读到最后
}
function queueSave() {
  if (started.value || !taskId.value || !formRef.value) return
  draftSaved.value = false
  clearTimeout(saveTimer)
  saveTimer = setTimeout(flushSave, 800)
}
async function flushSave() {
  if (!saveTimer) return
  clearTimeout(saveTimer)
  saveTimer = null
  if (started.value || !taskId.value || !formRef.value) return
  const snap = formRef.value.snapshot()
  try {
    const res = await saveExtractDraft(taskId.value, { model: snap.model, materials: rangeOf(snap.materials) })
    draftSaved.value = res.code === 0
  } catch {
    draftSaved.value = false // 下次改动再存
  }
}
watch(() => [pick.from, pick.to], queueSave)

/* 顶栏「⋯」：改名 / 删除工作区（删除带预览二次确认，是这本书最后一个工作区时连同素材，见 extractWorkspaces.js） */
async function onCommand(cmd) {
  const t = { id: taskId.value, title: rawTitle, fileName: fileName.value, status: task.status, options: options.value ? JSON.stringify(options.value) : null }
  if (cmd === 'rename') {
    const v = await renameWorkspace(t)
    if (v !== null) {
      rawTitle = v
      title.value = v ? `${v} · ${bookName.value}` : ''
    }
    return
  }
  clearTimeout(saveTimer)
  saveTimer = null
  if (await deleteWorkspace(t)) router.push('/novel/extract')
}

async function start() {
  const body = formRef.value.build()
  if (body.materials) body.materials = rangeOf(body.materials)
  clearTimeout(saveTimer)
  saveTimer = null
  starting.value = true
  try {
    const res = await startExtract(taskId.value, body)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success('已开始提取')
    await loadTask(taskId.value)
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交提取任务失败'))
  } finally {
    starting.value = false
  }
}

async function act(kind) {
  if (kind === 'cancel') {
    try {
      await ElMessageBox.confirm('取消这次提取？取消后移到「提取失败」，不能再继续。', '取消提取', { type: 'warning' })
    } catch {
      return
    }
  }
  busy.value = kind
  try {
    const fn = { pause: pauseExtract, resume: resumeExtract, cancel: cancelExtract }[kind]
    const res = await fn(taskId.value)
    if (res.code !== 0) throw new Error(res.message)
    await loadTask(taskId.value)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    busy.value = ''
  }
}
</script>

<style scoped>
.xw {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--ws-paper, var(--el-bg-color-page));
  --m-hook: var(--el-color-warning-light-7);
  --m-payoff: var(--el-color-danger-light-8);
  --m-thread: var(--el-color-success-light-7);
  --m-person: #d9e4f0;
  --m-move: #e6dcef;
  --m-fact: var(--el-fill-color-dark);
}
.xw-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--ws-card, var(--el-bg-color));
}
.xw-title {
  font-family: var(--ws-font-title, inherit);
  font-size: 17px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.xw-progress {
  width: 150px;
}
.xw-msg {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.xw-mode {
  flex-shrink: 0;
}
.xw-pane {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.xw-pad {
  padding: 16px 20px;
}
.xw-fixed {
  overflow: hidden;
}
.xw-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr) 380px;
}
.xw-left,
.xw-right {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--ws-card, var(--el-bg-color));
}
.xw-left {
  border-right: 1px solid var(--el-border-color-lighter);
}
.xw-right {
  border-left: 1px solid var(--el-border-color-lighter);
  padding: 0 12px;
}
.range-box {
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
}
.reread-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.extend-box .extend-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.extend-box .extend-row :deep(.el-input-number) {
  width: 110px;
}
.extend-box p {
  margin: 6px 0;
}
.range-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.range-row :deep(.el-input-number) {
  width: 92px;
}
.ch-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.ch-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}
.ch-item:hover {
  background: var(--el-fill-color-light);
}
.ch-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.ch-item.out {
  color: var(--el-text-color-placeholder);
}
.ch-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ch-badges {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.ch-pick {
  display: none;
}
.ch-item:hover .ch-pick {
  display: inline-flex;
}
.ch-pick .el-button + .el-button {
  margin-left: 4px;
}
.dot {
  flex: none;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--el-border-color);
}
.dot.s-out {
  background: transparent;
  border: 1px dashed var(--el-border-color);
}
.dot.s-done {
  background: var(--el-color-success);
}
.dot.s-failed {
  background: var(--el-color-danger);
}
.dot.s-partial {
  background: var(--el-color-warning);
}
.dot.s-reading {
  background: none;
  color: var(--el-color-primary);
}
.xw-breakdown {
  grid-column: 2 / 4;
  overflow-y: auto;
  padding: 16px 28px 40px;
}
.xw-text {
  overflow-y: auto;
  padding: 16px 40px 40px;
  font-family: var(--ws-font-prose, inherit);
  font-size: 16px;
  line-height: 1.95;
}
.text-title {
  margin: 0 0 14px;
  font-family: var(--ws-font-title, inherit);
}
.out-tip {
  margin-bottom: 10px;
}
.para {
  margin: 0 0 6px;
  text-indent: 2em;
}
.para.node {
  padding: 2px 6px;
  border-left: 3px solid var(--el-color-primary-light-5);
}
.para.node-1 {
  border-left-color: var(--el-color-success-light-3);
  background: var(--el-fill-color-lighter);
}
.node-head {
  text-indent: 0;
  font-size: 12px;
  font-family: var(--ws-font-ui, inherit);
  color: var(--el-color-primary);
}
.node-head.hot::after {
  content: ' · 爽点 / 钩子';
}
.node-text {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}
.mark {
  border-radius: 3px;
  cursor: pointer;
}
.m-hook {
  background: var(--m-hook);
}
.m-payoff {
  background: var(--m-payoff);
}
.m-thread {
  background: var(--m-thread);
}
.m-person {
  background: var(--m-person);
}
.m-move {
  background: var(--m-move);
}
.m-fact {
  background: var(--m-fact);
}
.mark.on {
  outline: 2px solid var(--el-color-primary);
}
.xw-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.xw-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 20px;
}
.start-btn {
  width: 100%;
  margin-top: 12px;
}
.card-pane {
  font-size: 13px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
  font-size: 12px;
}
.legend .mark {
  padding: 0 4px;
  cursor: default;
}
.one-line {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 6px;
}
.tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
h4 {
  margin: 14px 0 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.events {
  margin: 0;
  padding-left: 18px;
}
.item {
  padding: 5px 6px;
  margin-bottom: 4px;
  border-radius: 4px;
  border: 1px solid transparent;
}
.item.clickable {
  cursor: pointer;
}
.item.clickable:hover {
  background: var(--el-fill-color-light);
}
.item.on {
  border-color: var(--el-color-primary);
}
.item.unverified {
  color: var(--el-text-color-placeholder);
}
.item-head {
  display: inline-block;
  padding: 0 4px;
  margin-right: 6px;
  font-size: 12px;
  cursor: inherit;
}
.quote {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.golden {
  margin: 4px 0;
}
.golden b {
  margin-right: 6px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.muted.warn {
  color: var(--el-color-warning);
}
.pad {
  padding: 8px;
}
</style>
