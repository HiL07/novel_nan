<template>
  <div class="extract-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">小说提取</span>
          <div>
            <el-button @click="router.push('/ai/model')">模型配置</el-button>
            <el-button @click="router.push('/file/manage')">去选择文件</el-button>
            <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="!tasks.length" description="暂无提取任务，请在「文件管理」中选择小说文件后点击「小说提取」" />

      <template v-else>
        <el-tabs v-model="section" class="section-tabs">
          <el-tab-pane :label="`提取中（${groups.active.length}）`" name="active" />
          <el-tab-pane :label="`提取成功（${groups.done.length}）`" name="done" />
          <el-tab-pane :label="`提取失败（${groups.failed.length}）`" name="failed" />
        </el-tabs>

        <!-- 提取中：排队 / 运行 / 中断（中断的可继续或取消） -->
        <template v-if="section === 'active'">
          <p class="section-tip">
            每读完一段都会存断点：服务重启、出错或「暂停」后任务留在这里，点「继续」从断点接着提取（已读完的部分不重做）；
            点「取消」才会移到「提取失败」。
          </p>
          <el-table :data="groups.active" stripe empty-text="没有正在提取的小说">
            <el-table-column prop="fileName" label="文件" min-width="200" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="STATUS[row.status]?.type" size="small">{{ STATUS[row.status]?.label || row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="180">
              <template #default="{ row }">
                <el-progress :percentage="row.progress || 0" :status="row.status === 'INTERRUPTED' ? 'warning' : ''" />
              </template>
            </el-table-column>
            <el-table-column prop="message" label="说明" min-width="240" show-overflow-tooltip />
            <el-table-column prop="createTime" label="创建时间" width="170" />
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <template v-if="row.status === 'INTERRUPTED'">
                  <el-button link type="primary" :loading="busy[row.id] === 'resume'" @click="doResume(row)">继续</el-button>
                  <el-button link type="primary" @click="openDetail(row)">查看</el-button>
                  <el-button link type="danger" :loading="busy[row.id] === 'cancel'" @click="doCancel(row)">取消</el-button>
                </template>
                <template v-else>
                  <el-button
                    link
                    type="primary"
                    :loading="busy[row.id] === 'pause'"
                    :disabled="stopping(row)"
                    title="停下来，保留断点，之后可以继续"
                    @click="doPause(row)"
                  >
                    暂停
                  </el-button>
                  <el-button link type="danger" :loading="busy[row.id] === 'cancel'" :disabled="stopping(row)" @click="doCancel(row)">
                    取消
                  </el-button>
                </template>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <!-- 提取成功：按「整理卡片 → 确认素材」的进度分组 -->
        <template v-else-if="section === 'done'">
          <el-radio-group v-model="doneFilter" size="small" class="sub-filter">
            <el-radio-button value="all">全部（{{ groups.done.length }}）</el-radio-button>
            <el-radio-button v-for="(label, k) in CARD_STATES" :key="k" :value="k">{{ label }}（{{ doneCounts[k] || 0 }}）</el-radio-button>
          </el-radio-group>
          <el-table :data="doneRows" stripe empty-text="没有符合条件的小说">
            <el-table-column prop="fileName" label="文件" min-width="190" show-overflow-tooltip />
            <el-table-column label="字数 / 章节" width="130">
              <template #default="{ row }">{{ wan(row.wordCount) }} · {{ row.chapterCount ?? '-' }} 章</template>
            </el-table-column>
            <el-table-column label="卡片" min-width="230">
              <template #default="{ row }">
                <template v-if="cardState(row) === 'compiling'">
                  <el-tag :type="STATUS[row.latestCompile.status]?.type" size="small">
                    {{ row.latestCompile.status === 'INTERRUPTED' ? '整理中断' : '整理中' }} {{ row.latestCompile.progress || 0 }}%
                  </el-tag>
                  <div class="cell-msg">{{ row.latestCompile.message }}</div>
                </template>
                <template v-else>
                  <el-tag v-if="row.pendingCount > 0" type="warning" size="small">{{ row.pendingCount }} 条待确认</el-tag>
                  <el-tag v-else-if="cardState(row) === 'settled'" type="success" size="small">已全部处理</el-tag>
                  <span v-else-if="!hasEntities(row)" class="chapter-meta">没有记录实体（只做了章节分析）</span>
                  <el-tag v-else type="info" size="small">未整理</el-tag>
                  <span v-if="row.latestCompile?.status === 'SUCCEEDED'" class="chapter-meta">
                    {{ row.latestCompile.cardCount }} 张卡 · {{ row.latestCompile.arcCount }} 个剧情段
                  </span>
                  <span v-else-if="row.latestCompile?.status === 'FAILED'" class="chapter-meta">上次整理已取消</span>
                </template>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="提取说明" min-width="200" show-overflow-tooltip />
            <el-table-column prop="updateTime" label="完成时间" width="160" />
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <template v-if="cardState(row) === 'compiling'">
                  <template v-if="row.latestCompile.status === 'INTERRUPTED'">
                    <el-button link type="primary" :loading="busy[row.id] === 'c-resume'" @click="compileAct(row, 'resume')">继续</el-button>
                    <el-button link type="danger" @click="compileAct(row, 'cancel')">取消</el-button>
                  </template>
                  <template v-else>
                    <el-button link type="primary" :disabled="stopping(row.latestCompile)" @click="compileAct(row, 'pause')">暂停</el-button>
                    <el-button link type="danger" :disabled="stopping(row.latestCompile)" @click="compileAct(row, 'cancel')">取消</el-button>
                  </template>
                </template>
                <el-button v-else-if="hasEntities(row)" link type="primary" @click="openCompile(row)">整理卡片</el-button>
                <el-button v-if="row.pendingCount > 0" link type="primary" @click="openDetail(row, 'materials')">确认素材</el-button>
                <el-button link type="primary" @click="openDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <!-- 提取失败：可查看、可删除 -->
        <template v-else>
          <div class="failed-bar">
            <el-button type="danger" plain size="small" :icon="Delete" :disabled="!failedChecked.length" :loading="deleting" @click="doDelete(failedChecked)">
              删除选中（{{ failedChecked.length }}）
            </el-button>
            <span class="chapter-meta">已取消或无法继续的任务。删除只删任务记录和断点，不影响文件和素材库</span>
          </div>
          <el-table :data="groups.failed" stripe empty-text="没有提取失败的小说" @selection-change="(rows) => (failedChecked = rows.map((r) => r.id))">
            <el-table-column type="selection" width="44" />
            <el-table-column prop="fileName" label="文件" min-width="200" show-overflow-tooltip />
            <el-table-column label="停在" width="150">
              <template #default="{ row }"><el-progress :percentage="row.progress || 0" status="exception" /></template>
            </el-table-column>
            <el-table-column prop="message" label="原因" min-width="240" show-overflow-tooltip />
            <el-table-column prop="updateTime" label="时间" width="170" />
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">查看</el-button>
                <el-button link type="danger" @click="doDelete([row.id])">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </template>
    </el-card>

    <CompileDialog
      v-model="compileVisible"
      :extract-id="compileTarget?.id"
      :file-name="compileTarget?.fileName"
      :entities="compileEntities"
      :selected-keys="compileKeys"
      :chapter-count="compileTarget?.chapterCount || 0"
      @started="onCompileStarted"
    />

    <!-- 中断 / 失败任务的查看 -->
    <el-dialog v-model="infoVisible" :title="info?.fileName" width="600px">
      <el-descriptions v-if="info" :column="1" border size="small">
        <el-descriptions-item label="状态">
          <el-tag :type="STATUS[info.status]?.type" size="small">{{ STATUS[info.status]?.label || info.status }}</el-tag>
          <span class="chapter-meta">进度 {{ info.progress || 0 }}%</span>
        </el-descriptions-item>
        <el-descriptions-item label="说明">{{ info.message || '-' }}</el-descriptions-item>
        <el-descriptions-item label="提取模型">{{ modelText(infoOptions?.model) }}</el-descriptions-item>
        <el-descriptions-item label="素材提取">{{ materialText(infoOptions?.materials) }}</el-descriptions-item>
        <el-descriptions-item label="断点">
          <template v-if="!info.checkpoint">AI 服务不可达，无法读取断点</template>
          <template v-else-if="!info.checkpoint.exists">没有断点（还没开始读，或断点已删除）</template>
          <template v-else>
            <div v-for="(n, k) in info.checkpoint.stages" :key="k">{{ STAGE_LABELS[k] || k }}：{{ n }}</div>
            <div v-if="info.checkpoint.running" class="chapter-meta">AI 服务里这个任务还在运行</div>
          </template>
        </el-descriptions-item>
        <el-descriptions-item label="创建 / 更新">{{ info.createTime }} / {{ info.updateTime }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <template v-if="info?.status === 'INTERRUPTED'">
          <el-button type="primary" :loading="busy[info.id] === 'resume'" @click="doResume(info).then(() => (infoVisible = false))">继续提取</el-button>
          <el-button type="danger" plain @click="doCancel(info).then(() => (infoVisible = false))">取消</el-button>
        </template>
        <el-button v-else-if="info?.status === 'FAILED'" type="danger" plain @click="doDelete([info.id]).then(() => (infoVisible = false))">删除</el-button>
        <el-button @click="infoVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 结果详情 -->
    <el-drawer v-model="drawerVisible" :title="detail?.fileName" size="60%" destroy-on-close>
      <el-tabs v-if="result" v-model="drawerTab">
        <el-tab-pane label="提取结果" name="result">
      <div class="result">
        <div class="result-actions">
          <el-button type="primary" :icon="Download" :disabled="!!draft" @click="downloadJson">下载 JSON</el-button>
          <template v-if="!draft">
            <el-button :icon="EditPen" @click="startEdit">修改结果</el-button>
            <span v-if="result.editedAt" class="chapter-meta">已手动修改 · {{ result.editedAt }}</span>
          </template>
          <template v-else>
            <el-button type="success" :icon="Check" :loading="saving" @click="saveEdit">保存修改</el-button>
            <el-button @click="draft = null">取消</el-button>
            <span class="chapter-meta">AI 提取的摘要、人物、事件、伏笔、文风都可以改；展开章节即可编辑</span>
          </template>
        </div>

        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="总字数">{{ result.wordCount }}</el-descriptions-item>
          <el-descriptions-item label="章节数">{{ result.chapterCount }}</el-descriptions-item>
          <el-descriptions-item label="对话占比">{{ percent(result.style?.dialogRatio) }}</el-descriptions-item>
          <el-descriptions-item v-if="result.model" label="提取模型" :span="3">
            {{ result.model }}
            <el-tag v-if="result.source === 'local'" size="small" type="success">本地 · 免费</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="节奏">
            <el-input v-if="draft" v-model="draft.style.pace" size="small" />
            <template v-else>{{ result.style?.pace || '-' }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="基调">
            <el-input-tag v-if="draft" v-model="draft.style.tones" size="small" />
            <template v-else>{{ (result.style?.tones || []).join('、') || '-' }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="解析失败分块">{{ result.failedChunks }}</el-descriptions-item>
          <el-descriptions-item label="使用模型">{{ result.model || '-' }}</el-descriptions-item>
        </el-descriptions>

        <h4>
          人物（{{ view.characters?.length || 0 }}）
          <el-button v-if="draft" link type="primary" :icon="Plus" @click="draft.characters.unshift({ name: '', role: '', firstAppear: '', chapterCount: 0 })">添加人物</el-button>
        </h4>
        <el-table v-if="draft" :data="draft.characters" size="small" max-height="360">
          <el-table-column label="姓名" width="140">
            <template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
          </el-table-column>
          <el-table-column label="身份 / 首次动作" min-width="220">
            <template #default="{ row }"><el-input v-model="row.role" size="small" /></template>
          </el-table-column>
          <el-table-column label="首次出场" width="160">
            <template #default="{ row }"><el-input v-model="row.firstAppear" size="small" /></template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }"><el-button link type="danger" :icon="Delete" @click="draft.characters.splice($index, 1)" /></template>
          </el-table-column>
        </el-table>
        <el-table v-else :data="result.characters" size="small" max-height="300">
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="role" label="身份 / 首次动作" min-width="200" show-overflow-tooltip />
          <el-table-column prop="firstAppear" label="首次出场" width="160" show-overflow-tooltip />
          <el-table-column prop="chapterCount" label="出场章数" width="90" />
        </el-table>

        <h4>章节（{{ view.chapters?.length || 0 }}）</h4>
        <!-- 分页 + 只渲染展开的章节内容：长篇有数百章、上千条事件，全部渲染会卡 -->
        <el-collapse v-model="openChapters">
          <el-collapse-item v-for="(ch, i) in pagedChapters" :key="chapterOffset + i" :name="chapterOffset + i">
            <template #title>
              <span class="chapter-title">{{ ch.title }}</span>
              <span class="chapter-meta">{{ ch.wordCount }} 字</span>
            </template>
            <el-form v-if="draft && openChapters.includes(chapterOffset + i)" label-width="72px" size="small" class="chapter-edit">
              <el-form-item label="标题"><el-input v-model="ch.title" /></el-form-item>
              <el-form-item label="摘要"><el-input v-model="ch.summary" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" /></el-form-item>
              <el-form-item label="出场人物"><el-input-tag v-model="ch.characters" placeholder="回车添加" /></el-form-item>
              <el-form-item label="关键事件">
                <div class="events-edit">
                  <div v-for="(ev, j) in ch.events" :key="j" class="event-row">
                    <el-input v-model="ev.summary" placeholder="事件" class="ev-summary" />
                    <el-input v-model="ev.location" placeholder="地点" class="ev-meta" />
                    <el-input v-model="ev.time" placeholder="时间" class="ev-meta" />
                    <el-button link type="danger" :icon="Delete" @click="ch.events.splice(j, 1)" />
                  </div>
                  <el-button link type="primary" :icon="Plus" @click="ch.events.push({ summary: '', location: '', time: '' })">添加事件</el-button>
                </div>
              </el-form-item>
              <el-form-item label="伏笔"><el-input-tag v-model="ch.foreshadowing" placeholder="回车添加" /></el-form-item>
            </el-form>
            <template v-else-if="openChapters.includes(chapterOffset + i)">
            <p><b>摘要：</b>{{ ch.summary || '-' }}</p>
            <p><b>出场人物：</b>{{ ch.characters?.join('、') || '-' }}</p>
            <div v-if="ch.events?.length">
              <b>关键事件：</b>
              <ul>
                <li v-for="(ev, j) in ch.events" :key="j">
                  {{ ev.summary }}
                  <span v-if="ev.location || ev.time" class="chapter-meta">（{{ [ev.location, ev.time].filter(Boolean).join('，') }}）</span>
                </li>
              </ul>
            </div>
            <p v-if="ch.foreshadowing?.length"><b>伏笔：</b>{{ ch.foreshadowing.join('；') }}</p>
            </template>
          </el-collapse-item>
        </el-collapse>
        <el-pagination
          v-if="(view.chapters?.length || 0) > CHAPTER_PAGE"
          v-model:current-page="chapterPage"
          class="pager"
          small
          layout="prev, pager, next, total"
          :total="view.chapters.length"
          :page-size="CHAPTER_PAGE"
        />
      </div>
        </el-tab-pane>
        <el-tab-pane v-if="result.entities" :label="`实体档案（${result.entities.length}）`" name="entities" lazy>
          <EntityArchive
            :entities="result.entities"
            :saving="saving"
            @save="saveEntities"
            @compile="(keys) => openCompile(detailRow, keys)"
          />
        </el-tab-pane>
        <el-tab-pane v-if="result.entities" label="整理记录" name="compiles" lazy>
          <el-table :data="compiles" size="small" empty-text="还没有整理过">
            <el-table-column prop="createTime" label="时间" width="160" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="STATUS[row.status]?.type" size="small">{{ STATUS[row.status]?.label || row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="模型 / 范围" min-width="200">
              <template #default="{ row }">{{ compileScope(row) }}</template>
            </el-table-column>
            <el-table-column prop="message" label="结果" min-width="240" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="素材候选" name="materials" lazy>
          <el-alert
            v-if="!result.materials && !result.entities"
            type="info"
            :closable="false"
            show-icon
            title="这次提取没有记录设定实体。可在「文件管理」中重新提取并打开「记录设定实体」，再整理卡片。"
          />
          <CandidateReview v-else :extract-id="detail.id" />
        </el-tab-pane>
      </el-tabs>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, Download, EditPen, Plus, Refresh } from '@element-plus/icons-vue'
import {
  cancelCompile,
  cancelExtract,
  deleteExtracts,
  listCompiles,
  pauseCompile,
  resumeCompile,
  getExtract,
  listExtracts,
  pauseExtract,
  resumeExtract,
  updateExtractResult
} from '@/api/novel'
import CandidateReview from '@/components/material/CandidateReview.vue'
import CompileDialog from '@/components/material/CompileDialog.vue'
import { categoryOf } from '@/api/material'
import EntityArchive from '@/components/material/EntityArchive.vue'
import { errorMessage } from '@/api/request'

const STATUS = {
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '提取中', type: 'warning' },
  INTERRUPTED: { label: '已中断', type: 'warning' },
  SUCCEEDED: { label: '已完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' }
}
const STAGE_LABELS = {
  chunks: '已分析的分块',
  pass1: '第 1 遍已读的块',
  pass2: '第 2 遍已读的块',
  cards: '已整理的素材卡（批）',
  systems: '已整理的体系卡',
  arcs: '已整理的剧情段（窗口）'
}
const POLL_MS = 3000
const CHAPTER_PAGE = 30

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const tasks = ref([])
const drawerVisible = ref(false)
const detail = ref(null)
const drawerTab = ref('result')
const chapterPage = ref(1)
const openChapters = ref([])
let timer = null

const result = computed(() => {
  if (!detail.value?.result) return null
  try {
    return JSON.parse(detail.value.result)
  } catch {
    return null
  }
})

const chapterOffset = computed(() => (chapterPage.value - 1) * CHAPTER_PAGE)
/* 修改结果：draft 为可编辑副本（深层响应式），保存时整体提交；查看时用只读的 result */
const draft = ref(null)
const saving = ref(false)
const view = computed(() => draft.value || result.value)
const pagedChapters = computed(() => view.value?.chapters?.slice(chapterOffset.value, chapterOffset.value + CHAPTER_PAGE) || [])

function startEdit() {
  const d = JSON.parse(JSON.stringify(result.value))
  d.style = d.style || {}
  d.style.tones = d.style.tones || []
  d.characters = d.characters || []
  d.chapters.forEach((ch) => {
    ch.characters = ch.characters || []
    ch.events = ch.events || []
    ch.foreshadowing = ch.foreshadowing || []
  })
  draft.value = d
}

async function saveEdit() {
  saving.value = true
  try {
    const d = draft.value
    d.characters = d.characters.filter((c) => c.name?.trim())
    d.chapters.forEach((ch) => (ch.events = ch.events.filter((ev) => ev.summary?.trim())))
    const res = await updateExtractResult(detail.value.id, d)
    if (res.code !== 0) throw new Error(res.message || '保存失败')
    detail.value = Object.freeze(res.data)
    draft.value = null
    ElMessage.success('提取结果已保存')
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存提取结果失败'))
  } finally {
    saving.value = false
  }
}

const hasActive = () =>
  tasks.value.some(
    (t) => ['QUEUED', 'RUNNING'].includes(t.status) || ['QUEUED', 'RUNNING'].includes(t.latestCompile?.status)
  )

/* 三个分类：提取中（排队 / 运行 / 中断）、提取成功、提取失败 */
const section = ref('active')
const doneFilter = ref('all')
const groups = computed(() => {
  const active = tasks.value.filter((t) => ['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(t.status))
  const done = tasks.value.filter((t) => t.status === 'SUCCEEDED')
  return {
    active,
    done,
    donePending: done.filter((t) => t.pendingCount > 0),
    failed: tasks.value.filter((t) => t.status === 'FAILED')
  }
})
/* 提取成功的小说按卡片进度分组：整理中（含中断）> 有待确认 > 已全部处理 > 未整理 */
const CARD_STATES = { todo: '未整理卡片', compiling: '整理中', pending: '有待确认素材', settled: '已全部处理' }
function hasEntities(row) {
  try {
    return !!JSON.parse(row.options || 'null')?.materials?.enabled
  } catch {
    return false
  }
}
function cardState(row) {
  const st = row.latestCompile?.status
  if (['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(st)) return 'compiling'
  if (row.pendingCount > 0) return 'pending'
  if (st === 'SUCCEEDED' || row.candidateCount > 0) return 'settled'
  return 'todo'
}
const doneCounts = computed(() => {
  const out = {}
  groups.value.done.forEach((t) => (out[cardState(t)] = (out[cardState(t)] || 0) + 1))
  return out
})
const doneRows = computed(() =>
  doneFilter.value === 'all' ? groups.value.done : groups.value.done.filter((t) => cardState(t) === doneFilter.value)
)
const failedChecked = ref([])
const stopping = (row) => ['正在取消…', '正在暂停…'].includes(row?.message)
const wan = (n) => (n ? (n >= 10000 ? `${(n / 10000).toFixed(1)} 万字` : `${n} 字`) : '-')

const busy = ref({})
async function act(row, kind, fn, okText, failText) {
  busy.value[row.id] = kind
  try {
    const res = await fn(row.id)
    if (res.code !== 0) throw new Error(res.message || failText)
    ElMessage.success(okText)
    await loadTasks()
    if (hasActive()) schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, failText))
  } finally {
    busy.value[row.id] = null
  }
}

async function doCancel(row) {
  try {
    await ElMessageBox.confirm(`取消《${row.fileName}》的提取？取消后移到「提取失败」，不能再继续（只能查看或删除）。`, '取消提取', {
      type: 'warning',
      confirmButtonText: '取消提取',
      cancelButtonText: '再想想'
    })
  } catch {
    return
  }
  await act(row, 'cancel', cancelExtract, row.status === 'INTERRUPTED' ? '已取消' : '已请求取消，当前分块结束后停止', '取消提取任务失败')
}

const doPause = (row) => act(row, 'pause', pauseExtract, '已请求暂停，当前分块结束后停下，之后可继续', '暂停失败')
const doResume = (row) => act(row, 'resume', resumeExtract, '已重新排队，从断点接着提取', '继续提取失败')

const deleting = ref(false)
async function doDelete(ids) {
  try {
    await ElMessageBox.confirm(`删除 ${ids.length} 个提取失败的任务？只删任务记录和断点。`, '删除任务', { type: 'warning' })
  } catch {
    return
  }
  deleting.value = true
  try {
    const res = await deleteExtracts(ids)
    if (res.code !== 0) throw new Error(res.message || '删除失败')
    ElMessage.success(`已删除 ${res.data.deleted} 个` + (res.data.skipped ? `，跳过 ${res.data.skipped} 个（不是失败状态）` : ''))
    failedChecked.value = []
    await loadTasks()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除提取任务失败'))
  } finally {
    deleting.value = false
  }
}

/* 整理卡片：需要实体档案，先读提取结果 */
const compileVisible = ref(false)
const compileTarget = ref(null)
const compileEntities = ref([])
const compileKeys = ref([])
async function openCompile(row, keys = []) {
  try {
    let parsed = row.id === detail.value?.id ? result.value : null
    if (!parsed) {
      const res = await getExtract(row.id)
      if (res.code !== 0) throw new Error(res.message || '加载失败')
      parsed = JSON.parse(res.data.result || 'null')
    }
    if (!parsed?.entities?.length) {
      ElMessage.warning('这次提取没有记录实体，无法整理卡片')
      return
    }
    compileTarget.value = row
    compileEntities.value = Object.freeze(parsed.entities)
    compileKeys.value = keys
    compileVisible.value = true
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取实体档案失败'))
  }
}
async function onCompileStarted() {
  await loadTasks()
  schedulePoll()
  if (drawerVisible.value) loadCompiles()
}

async function compileAct(row, kind) {
  const c = row.latestCompile
  if (kind === 'cancel') {
    try {
      await ElMessageBox.confirm('取消这次整理？已整理的部分不会进入待确认，可以重新发起整理。', '取消整理', {
        type: 'warning',
        confirmButtonText: '取消整理',
        cancelButtonText: '再想想'
      })
    } catch {
      return
    }
  }
  const fn = { pause: pauseCompile, resume: resumeCompile, cancel: cancelCompile }[kind]
  const ok = { pause: '已请求暂停，当前这张卡整理完后停下', resume: '已重新排队，从断点接着整理', cancel: '已取消' }[kind]
  busy.value[row.id] = `c-${kind}`
  try {
    const res = await fn(c.id)
    if (res.code !== 0) throw new Error(res.message || '操作失败')
    ElMessage.success(ok)
    await loadTasks()
    if (hasActive()) schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    busy.value[row.id] = null
  }
}

/* 抽屉：实体档案保存、整理记录 */
const detailRow = computed(() => tasks.value.find((t) => t.id === detail.value?.id) || detail.value)
const compiles = ref([])
async function loadCompiles() {
  if (!detail.value) return
  try {
    const res = await listCompiles(detail.value.id)
    compiles.value = res.code === 0 ? res.data || [] : []
  } catch {
    compiles.value = []
  }
}
function compileScope(row) {
  let o = {}
  try {
    o = JSON.parse(row.options || '{}') || {}
  } catch {
    // 参数读不出来：只显示实体数
  }
  const parts = [modelText(o.model)]
  if (o.entityKeys) parts.push(`勾选的 ${o.entityKeys.length} 个`)
  else if (o.topN) parts.push(`事实最多的前 ${o.topN} 个`)
  if (o.categories) parts.push(o.categories.map((c) => categoryOf(c)?.label || c).join('、'))
  parts.push(`${row.entityCount ?? '?'} 个实体`)
  if (o.plot) parts.push('含剧情段')
  return parts.join(' · ')
}

async function saveEntities(entities) {
  saving.value = true
  try {
    const res = await updateExtractResult(detail.value.id, { ...result.value, entities })
    if (res.code !== 0) throw new Error(res.message || '保存失败')
    detail.value = Object.freeze(res.data)
    ElMessage.success(`实体档案已保存（${entities.length} 个实体）`)
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存实体档案失败'))
  } finally {
    saving.value = false
  }
}

/* 中断 / 失败任务的查看 */
const infoVisible = ref(false)
const info = ref(null)
const infoOptions = computed(() => {
  try {
    return info.value?.options ? JSON.parse(info.value.options) : null
  } catch {
    return null
  }
})
function modelText(m) {
  if (!m) return '大模型（启用中的配置）'
  if (m.source === 'gguf') return 'GGUF（llama.cpp）'
  if (m.source === 'local') return `本地模型 ${m.baseId}` + (m.chunkChars ? `，每段 ${m.chunkChars} 字` : '')
  return `大模型${m.configId ? `（配置 #${m.configId}）` : '（启用中的配置）'}`
}
function materialText(mt) {
  if (!mt) return '只做章节分析（不记录设定实体）'
  if (mt.mode === 'v1') return `旧版，每段最多 ${mt.maxPerChunk} 条`
  return `记录设定实体，读 ${mt.rounds ?? 2} 遍，每段 ${mt.chunkChars ?? 3000} 字`
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await listExtracts()
    if (res.code === 0) {
      tasks.value = res.data || []
    } else {
      ElMessage.error(res.message || '加载失败')
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载提取任务失败'))
  } finally {
    loading.value = false
  }
}

/** 有进行中的任务时定时刷新，全部结束后停止 */
function schedulePoll() {
  stopPoll()
  timer = setTimeout(async () => {
    await loadTasks()
    if (hasActive()) schedulePoll()
  }, POLL_MS)
}

function stopPoll() {
  if (timer) clearTimeout(timer)
  timer = null
}

async function openDetail(row, tab) {
  try {
    const res = await getExtract(row.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '加载失败')
      return
    }
    if (res.data.status !== 'SUCCEEDED') {
      info.value = res.data
      infoVisible.value = true
      return
    }
    detail.value = Object.freeze(res.data) // 只读展示：大结果不做深层响应式
    draft.value = null
    chapterPage.value = 1
    openChapters.value = []
    // 有待确认的素材候选时直接打开「素材候选」
    drawerTab.value = tab || (row.pendingCount > 0 ? 'materials' : 'result')
    drawerVisible.value = true
    compiles.value = []
    loadCompiles()
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载提取结果失败'))
  }
}

function downloadJson() {
  const blob = new Blob([JSON.stringify(result.value, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${(detail.value.fileName || 'novel').replace(/\.[^.]+$/, '')}_提取结果.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

function percent(v) {
  return typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : '-'
}

// 页面被 keep-alive 缓存：进入时拉取并按需轮询，离开时停止轮询
onActivated(async () => {
  await loadTasks()
  if (hasActive()) schedulePoll()
  const id = Number(route.query.id)
  const task = tasks.value.find((t) => t.id === id)
  section.value = task
    ? { SUCCEEDED: 'done', FAILED: 'failed' }[task.status] || 'active'
    : groups.value.active.length ? 'active' : 'done'
  if (task?.status === 'SUCCEEDED') openDetail(task)
})
onDeactivated(stopPoll)
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.section-tabs {
  margin-top: -8px;
}
.section-tip {
  margin: 0 0 10px;
  font-size: 12px;
  color: #909399;
}
.sub-filter {
  margin-bottom: 10px;
}
.cell-msg {
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.failed-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.pager {
  margin-top: 10px;
  justify-content: center;
}
.chapter-edit {
  padding-top: 6px;
}
.events-edit {
  width: 100%;
}
.event-row {
  display: flex;
  gap: 6px;
  margin-bottom: 4px;
}
.ev-summary {
  flex: 1;
}
.ev-meta {
  width: 110px;
}
.result-actions {
  margin-bottom: 12px;
}
.result h4 {
  margin: 18px 0 8px;
  color: #303133;
}
.chapter-title {
  font-weight: 600;
}
.chapter-meta {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.result p,
.result ul {
  margin: 4px 0;
  line-height: 1.7;
}
</style>
