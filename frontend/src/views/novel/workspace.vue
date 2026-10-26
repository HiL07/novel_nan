<template>
  <div class="workspace-page">
    <!-- 工作区头部：模型 / 适配器 / 上下文窗口 -->
    <el-card class="box-card head-card" shadow="never">
      <div v-if="novel" class="head-row">
        <el-button :icon="Back" link @click="router.push('/novel/create')">工作区</el-button>
        <el-input v-model="titleDraft" class="title-input" maxlength="100" @change="saveTitle" />
        <span class="head-item">
          模型
          <el-select :model-value="novel.model.source" size="small" style="width: 150px" :disabled="busy" @change="changeSource">
            <el-option label="大模型（API）" value="api" />
            <el-option label="本地模型" value="local" :disabled="!localModels.length" />
            <el-option label="远程模型（即将支持）" value="remote" disabled />
          </el-select>
          <template v-if="isApi">{{ apiModel ? `${apiModel.name} · ${apiModel.model}` : novel.model.apiName || '当前启用的模型' }}</template>
          <el-select v-else :model-value="novel.model.baseId" size="small" style="width: 200px" :disabled="busy" @change="changeBase">
            <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </span>
        <el-tooltip v-if="!isApi" content="LoRA 风格适配器：章节正文用它生成，章节摘要始终用基础模型。切换后点击「加载模型」生效（同一基础模型只切换适配器，不重载）" placement="bottom">
          <el-select
            :model-value="novel.model.adapterId || ''"
            size="small"
            style="width: 180px"
            :disabled="busy || novel.model.source !== 'local'"
            @change="saveAdapter"
          >
            <el-option label="适配器：不使用" value="" />
            <el-option v-for="a in baseAdapters" :key="a.id" :label="`适配器：${a.name}`" :value="a.id" />
          </el-select>
        </el-tooltip>
        <span class="head-item">
          上下文窗口
          <el-select v-model="novel.contextWindow" size="small" style="width: 130px" :disabled="busy" @change="saveWindow">
            <el-option v-for="w in CONTEXT_WINDOWS" :key="w" :label="`${w} tokens`" :value="w" />
          </el-select>
        </span>
        <span v-if="isApi" class="head-item model-state">
          <el-tag :type="apiModel ? 'success' : 'warning'" size="small">{{ apiModel ? '大模型可用' : '没有可用的大模型' }}</el-tag>
          <el-button v-if="!apiModel" size="small" type="primary" @click="router.push('/ai/model')">去配置模型</el-button>
          <el-button v-if="!apiModel" size="small" @click="detectApi">重新检测</el-button>
        </span>
        <span v-else class="head-item model-state">
          <el-tag :type="modelReady ? 'success' : inferState?.status === 'loading' ? 'warning' : 'info'" size="small">
            {{ modelReady ? '模型已加载' : inferState?.status === 'loading' ? '加载中…' : '模型未加载' }}
          </el-tag>
          <el-button v-if="!modelReady" size="small" type="primary" :loading="inferState?.status === 'loading'" :disabled="busy" @click="onLoadModel">加载模型</el-button>
        </span>
      </div>
      <el-alert v-if="loadError" type="error" :closable="false" show-icon :title="loadError" />
      <el-alert v-if="inferState?.status === 'error'" type="error" :closable="false" show-icon :title="`模型加载失败：${inferState.error}`" class="mt" />
      <el-alert v-if="isApi && apiError" type="warning" :closable="false" show-icon :title="apiError" class="mt" />
      <el-alert
        v-if="!isApi && inferState?.status === 'loaded' && !modelReady"
        type="info"
        :closable="false"
        show-icon
        class="mt"
        :title="`当前加载的模型${inferState.baseId === novel.model.baseId ? '适配器设置' : ''}与本工作区不一致，点击「加载模型」切换${inferState.baseId === novel.model.baseId ? '（只切换适配器，不重载基础模型）' : ''}`"
      />
    </el-card>

    <el-card v-if="novel" class="box-card" shadow="never">
      <el-tabs v-model="tab">
        <!-- ===================== 设定 ===================== -->
        <el-tab-pane name="settings">
          <template #label>设定<el-badge v-if="settingsDirty" is-dot class="dirty-dot" /></template>
          <SettingsEditor
            :key="novel.id"
            ref="editorRef"
            :config="novel.settings.config"
            :novel-id="novel.id"
            :ai="{ apiModel, localModels, adapters, model: novel.model }"
            @change="settingsDirty = true"
          >
            <template #actions>
              <el-button type="primary" :icon="Check" :loading="savingSettings" @click="saveSettings()">保存设定</el-button>
            </template>
          </SettingsEditor>
        </el-tab-pane>

        <!-- ===================== 构思 ===================== -->
        <el-tab-pane label="AI 构思" name="ideas" lazy>
          <IdeaPanel
            ref="ideaRef"
            :novel="novel"
            :read-settings="readSettings"
            :local-models="localModels"
            :adapters="adapters"
            :api-model="apiModel"
            :next-index="nextIndex"
            @updated="onNovelUpdated"
            @use-chapter="useChapterIdea"
            @detect-api="detectApi"
          />
        </el-tab-pane>

        <!-- ===================== 写作 ===================== -->
        <el-tab-pane label="写作" name="write">
          <div class="write-grid">
            <!-- 章节列表 -->
            <div class="chapter-col">
              <div class="col-title">章节（{{ novel.chapters.length }}）</div>
              <div class="chapter-item" :class="{ 'is-active': view === 'new' }" @click="view = 'new'">
                <el-icon><EditPen /></el-icon> 写下一章
              </div>
              <div
                v-for="c in novel.chapters"
                :key="c.index"
                class="chapter-item"
                :class="{ 'is-active': view === c.index }"
                @click="openChapter(c.index)"
              >
                <div class="chapter-line">
                  <span>第{{ c.index }}章 {{ c.title }}</span>
                  <el-tag size="small" :type="CH_STATUS[c.status]?.type">{{ CH_STATUS[c.status]?.label || c.status }}</el-tag>
                </div>
                <div class="muted">{{ c.chars }} 字<template v-if="c.totals"> · {{ c.totals.promptTokens + c.totals.completionTokens }} tokens</template></div>
              </div>
              <div class="totals">
                <div class="col-title">本工作区 token 累计</div>
                <div>输入 {{ novel.tokenTotals.promptTokens }} · 输出 {{ novel.tokenTotals.completionTokens }} · 调用 {{ novel.tokenTotals.calls }} 次</div>
                <template v-if="novel.arcSummary">
                  <div class="col-title">
                    前情概要（已合并至第 {{ novel.arcUpTo }} 章）
                    <el-button link type="primary" size="small" :icon="EditPen" :disabled="busy" @click="openArcEdit">修改</el-button>
                  </div>
                  <div class="muted">{{ novel.arcSummary }}</div>
                </template>
              </div>
            </div>

            <!-- 写下一章 -->
            <div v-if="view === 'new'" class="main-col">
              <el-form label-width="90px" class="chapter-form">
                <el-form-item :label="`第${nextIndex}章`">
                  <el-input v-model="form.title" maxlength="60" placeholder="章节标题（可选）" :disabled="busy" />
                </el-form-item>
                <el-form-item v-if="outlineNext || apiModel" label="">
                  <div class="outline-hint">
                    <template v-if="outlineNext">
                      <el-tag size="small" type="success">大纲</el-tag>
                      <span>第{{ outlineNext.index }}章 {{ outlineNext.title }}</span>
                      <el-button link type="primary" :disabled="busy" @click="fillFromOutline">按大纲填入</el-button>
                    </template>
                    <el-button link type="primary" :icon="MagicStick" :disabled="busy" @click="tab = 'ideas'">AI 构思本章（可结合素材库）</el-button>
                  </div>
                </el-form-item>
                <el-form-item label="本章目标" required>
                  <el-input
                    v-model="form.goal"
                    type="textarea"
                    :autosize="{ minRows: 3, maxRows: 8 }"
                    maxlength="2000"
                    placeholder="这一章要发生什么，如：主角初到青云宗，在入门试炼中与宿敌第一次交手，暴露出体内的异常灵根"
                    :disabled="busy"
                  />
                </el-form-item>
                <el-form-item label="目标字数">
                  <el-input-number v-model="form.targetChars" :min="200" :max="20000" :step="500" :disabled="busy" />
                  <span class="muted hint">按模型每段输出上限自动分段生成，每段只带本章末尾而非整章</span>
                </el-form-item>
                <el-form-item label="润色">
                  <div class="polish-row">
                    <el-radio-group v-model="polish.mode" size="small" :disabled="busy">
                      <el-radio-button value="none">不润色</el-radio-button>
                      <el-radio-button value="local" :disabled="!localModels.length">本地 QLoRA</el-radio-button>
                      <el-radio-button value="remote" disabled>远程 QLoRA（即将支持）</el-radio-button>
                    </el-radio-group>
                    <template v-if="polish.mode === 'local'">
                      <el-select v-model="polish.baseId" size="small" style="width: 200px" :disabled="busy" @change="polish.adapterId = polishAdapters[0]?.id || ''">
                        <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" />
                      </el-select>
                      <el-select v-model="polish.adapterId" size="small" style="width: 200px" :disabled="busy" :placeholder="polishAdapters.length ? '不使用适配器' : '该模型没有可用的适配器'">
                        <el-option label="不使用适配器（基础模型）" value="" />
                        <el-option v-for="a in polishAdapters" :key="a.id" :label="`适配器：${a.name}`" :value="a.id" />
                      </el-select>
                    </template>
                    <span class="muted hint">{{ localModels.length ? '生成后逐段改写用词与句式，原文保留可恢复；改动过大的段落自动保留原文' : '没有登记本地模型，无法本地润色' }}</span>
                  </div>
                </el-form-item>
                <el-form-item>
                  <el-button :icon="View" :loading="previewing" :disabled="!form.goal.trim()" @click="onPreview">预览上下文</el-button>
                  <el-button v-if="!busy" type="primary" :icon="VideoPlay" :disabled="!form.goal.trim() || !canGenerate" @click="onStart">开始生成</el-button>
                  <el-button v-else type="danger" :icon="VideoPause" @click="onCancel">取消</el-button>
                  <span v-if="!canGenerate && !busy" class="muted hint">{{ isApi ? '请先在「模型配置」中启用大模型' : '请先加载模型' }}</span>
                </el-form-item>
              </el-form>

              <template v-if="job && job.kind !== 'polish'">
                <div class="progress-row">
                  <el-tag :type="JOB_STATUS[job.status].type">{{ JOB_STATUS[job.status].label }}</el-tag>
                  <span>{{ phaseText(job) }}</span>
                  <el-progress v-if="job.phase === 'polish'" class="progress-bar" :percentage="pct(job.polishDone, job.polishTotal)" />
                  <el-progress v-else class="progress-bar" :percentage="pct(liveChapter?.text.length || 0, liveChapter?.targetChars || form.targetChars)" />
                  <span class="muted">{{ liveChapter?.text.length || 0 }} / {{ liveChapter?.targetChars || form.targetChars }} 字</span>
                </div>
                <el-alert v-if="job.error" type="error" :closable="false" show-icon :title="job.error" class="mt" />
                <pre ref="liveBox" class="chapter-text">{{ (job.phase === 'polish' && liveChapter?.polishDraft) || liveChapter?.text || '（生成中，首段需要几十秒…）' }}</pre>
                <ContextReport v-if="job.lastContext" :report="job.lastContext" title="最近一次调用的上下文" />
                <CallTable v-if="liveChapter?.calls?.length" :calls="liveChapter.calls" :totals="liveChapter.totals" />
              </template>
            </div>

            <!-- 查看已生成章节 -->
            <div v-else-if="viewChapter" class="main-col">
              <div class="chapter-head">
                <span class="chapter-title">第{{ viewChapter.index }}章 {{ viewChapter.title }}</span>
                <el-tag size="small" :type="CH_STATUS[viewChapter.status]?.type">{{ CH_STATUS[viewChapter.status]?.label }}</el-tag>
                <span class="muted">{{ viewChapter.text.length }} 字 / 目标 {{ viewChapter.targetChars }}</span>
                <el-button link :icon="CopyDocument" @click="copy(viewChapter.text)">复制正文</el-button>
                <el-button v-if="!chapterEdit.active" link type="primary" :icon="EditPen" :disabled="busy || viewChapter.status === 'generating'" @click="startChapterEdit">修改本章</el-button>
                <el-tag v-if="viewChapter.edited?.length" size="small" type="info" effect="plain">已手动修改 · {{ viewChapter.editedAt }}</el-tag>
                <el-button v-if="isLast(viewChapter.index)" link type="danger" :icon="Delete" :disabled="busy" @click="onDeleteChapter(viewChapter.index)">删除本章</el-button>
              </div>
              <div v-if="viewChapter.status === 'done'" class="polish-bar">
                <template v-if="viewChapter.polish">
                  <el-tag type="warning" size="small">已润色 · {{ viewChapter.polish.adapterName ? `LoRA ${viewChapter.polish.adapterName}` : '基础模型' }}</el-tag>
                  <span class="muted">改写 {{ viewChapter.polish.changed }} 段，{{ viewChapter.polish.kept }} 段保留原文 · {{ viewChapter.polish.at }}</span>
                  <el-radio-group v-model="showOriginal" size="small">
                    <el-radio-button :value="false">润色后</el-radio-button>
                    <el-radio-button :value="true">原文</el-radio-button>
                  </el-radio-group>
                  <el-button size="small" :disabled="busy" @click="onRevertPolish">恢复原文</el-button>
                </template>
                <el-tooltip :content="localModels.length ? '用「写下一章」里选择的本地模型 / 适配器润色本章（总是基于原文）' : '没有登记本地模型'" placement="top">
                  <el-button size="small" type="warning" plain :disabled="busy || !localModels.length || !polish.baseId" @click="onPolishChapter">
                    {{ viewChapter.polish ? '重新润色' : '用本地模型润色' }}
                  </el-button>
                </el-tooltip>
                <span v-if="localModels.length" class="muted">{{ polishLabel }}</span>
              </div>
              <div v-if="job && job.kind === 'polish' && job.chapterIndex === viewChapter.index && busy" class="progress-row">
                <el-tag type="warning">润色中</el-tag>
                <span>{{ phaseText(job) }}</span>
                <el-progress class="progress-bar" :percentage="pct(job.polishDone, job.polishTotal)" />
                <el-button size="small" type="danger" :icon="VideoPause" @click="onCancel">取消</el-button>
              </div>
              <el-form v-if="chapterEdit.active" label-width="70px" class="chapter-edit">
                <el-form-item label="标题"><el-input v-model="chapterEdit.title" maxlength="60" /></el-form-item>
                <el-form-item label="本章目标"><el-input v-model="chapterEdit.goal" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" maxlength="2000" /></el-form-item>
                <el-form-item label="摘要">
                  <el-input v-model="chapterEdit.summary" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" maxlength="2000" />
                  <span class="muted hint">后续章节会把摘要当作前情；改了正文记得同步改摘要{{ viewChapter.index <= novel.arcUpTo ? '（本章已并入前情概要，概要需在左侧单独修改）' : '' }}</span>
                </el-form-item>
                <el-form-item label="正文">
                  <el-input v-model="chapterEdit.text" type="textarea" :autosize="{ minRows: 12, maxRows: 40 }" />
                  <span class="muted hint">{{ chapterEdit.text.length }} 字{{ viewChapter.originalText ? '；本章润色过：「恢复原文」会丢掉这里的修改' : '' }}</span>
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :icon="Check" :loading="chapterEdit.saving" @click="saveChapterEdit">保存修改</el-button>
                  <el-button @click="chapterEdit.active = false">取消</el-button>
                </el-form-item>
              </el-form>
              <template v-else>
              <div class="muted goal">本章目标：{{ viewChapter.goal }}</div>
              <el-alert v-if="viewChapter.error" type="error" :closable="false" show-icon :title="viewChapter.error" class="mt" />
              <div v-if="viewChapter.summary" class="summary"><b>摘要：</b>{{ viewChapter.summary }}</div>
              <pre class="chapter-text">{{ showOriginal && viewChapter.originalText ? viewChapter.originalText : (busy && job?.kind === 'polish' && job.chapterIndex === viewChapter.index && liveChapter?.polishDraft) || viewChapter.text }}</pre>
              </template>
              <CallTable v-if="viewChapter.calls?.length" :calls="viewChapter.calls" :totals="viewChapter.totals" />
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 前情概要：手动修改 -->
    <el-dialog v-model="arcEdit.visible" title="修改前情概要" width="640px">
      <p class="muted">前情概要由 AI 合并早期章节摘要生成（已合并至第 {{ novel?.arcUpTo }} 章），后续章节都会参考它。</p>
      <el-input v-model="arcEdit.text" type="textarea" :autosize="{ minRows: 6, maxRows: 16 }" maxlength="5000" show-word-limit />
      <template #footer>
        <el-button @click="arcEdit.visible = false">取消</el-button>
        <el-button type="primary" :loading="arcEdit.saving" @click="saveArcEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 上下文预览 -->
    <el-dialog v-model="previewDlg.visible" title="上下文预览（下一章第一段，不调用模型）" width="820px" top="5vh">
      <template v-if="previewDlg.data">
        <div class="muted">
          每段输出上限 {{ previewDlg.data.segmentTokens }} tokens（约 {{ previewDlg.data.segmentChars }} 字），预计 {{ previewDlg.data.estimatedSegments }} 段；
          模型上下文上限 {{ previewDlg.data.modelContextLimit }}；设定卡片 {{ previewDlg.data.cards.total }} 张；
          尚未设定：{{ previewDlg.data.cards.open.join('、') || '无' }}
        </div>
        <ContextReport :report="previewDlg.data.context" title="分层 token 用量" />
        <div v-for="(m, i) in previewDlg.data.messages" :key="i" class="prompt-block">
          <div class="col-title">{{ m.role === 'system' ? 'system（核心规则，始终保留）' : 'user（按需设定 / 前情 / 最近内容 / 任务）' }}</div>
          <pre class="prompt-text">{{ m.content }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onActivated, onDeactivated, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElTable, ElTableColumn, ElTag } from 'element-plus'
import { Back, Check, CopyDocument, Delete, EditPen, MagicStick, VideoPause, VideoPlay, View } from '@element-plus/icons-vue'
import SettingsEditor from '@/components/novel-options/SettingsEditor.vue'
import IdeaPanel from '@/components/novel/IdeaPanel.vue'
import {
  CONTEXT_WINDOWS, cancelGenJob, deleteChapter, editChapter, getChapter, getGenJob, getGenStatus, getNovel, loadNovelModel,
  polishChapter, previewContext, revertPolish, startChapter, updateNovel
} from '@/api/novelGen'
import { listAdapters, listModels } from '@/api/localModel'
import { listModels as listAiModels } from '@/api/aiModel'
import { errorMessage } from '@/api/request'

const CH_STATUS = {
  generating: { label: '生成中', type: 'warning' },
  done: { label: '完成', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
  failed: { label: '失败', type: 'danger' }
}
const JOB_STATUS = {
  queued: { label: '排队中', type: 'info' },
  running: { label: '生成中', type: 'warning' },
  succeeded: { label: '完成', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
  failed: { label: '失败', type: 'danger' }
}
const LAYER_LABEL = { L0_core: 'L0 核心规则', L1_cards: 'L1 按需设定', L2_story: 'L2 前情', L3_recent: 'L3 最近正文', L4_task: 'L4 本次任务' }

/** 分层 token 用量展示 */
const ContextReport = defineComponent({
  props: { report: Object, title: String },
  setup(props) {
    return () => {
      const r = props.report
      const rows = Object.entries(r.layers).map(([k, v]) => ({ layer: LAYER_LABEL[k] || k, tokens: v }))
      return h('div', { class: 'ctx-report' }, [
        h('div', { class: 'col-title' }, `${props.title}：输入 ${r.promptTokens} / 预算 ${r.inputBudget} tokens（窗口 ${r.window}，预留输出 ${r.maxNewTokens}）`),
        h(ElTable, { data: rows, size: 'small', style: 'max-width: 420px' }, () => [
          h(ElTableColumn, { prop: 'layer', label: '层', width: 160 }),
          h(ElTableColumn, { prop: 'tokens', label: 'tokens', width: 100 })
        ]),
        h('div', { class: 'muted mt' }, [
          `已放入设定卡片：${r.included.cards.join('、') || '无'}；前情摘要：${r.included.summaries.length ? r.included.summaries.map((i) => `第${i}章`).join('、') : '无'}`,
          r.included.arcSummary ? '（含前情概要）' : '',
          `；最近正文 ${r.included.recentChars} 字`
        ]),
        r.dropped.cards.length || r.dropped.summaries.length
          ? h('div', { class: 'muted' }, `未放入（不相关或超出预算）：${[...r.dropped.cards, ...r.dropped.summaries.map((i) => `第${i}章摘要`)].join('、')}`)
          : null
      ])
    }
  }
})

/** 每次模型调用的 token 明细 */
const CallTable = defineComponent({
  props: { calls: Array, totals: Object },
  setup(props) {
    const TYPE = { segment: '正文分段', summary: '章节摘要', arc: '前情合并' }
    return () => h('div', { class: 'ctx-report' }, [
      h('div', { class: 'col-title' }, `本章 token：输入 ${props.totals.promptTokens} · 输出 ${props.totals.completionTokens} · 调用 ${props.totals.calls} 次`),
      h(ElTable, { data: props.calls, size: 'small' }, () => [
        h(ElTableColumn, { label: '调用', width: 110 }, { default: ({ row }) => `${TYPE[row.type] || row.type}${row.segment ? ' ' + row.segment : ''}` }),
        h(ElTableColumn, { prop: 'promptTokens', label: '输入', width: 80 }),
        h(ElTableColumn, { prop: 'completionTokens', label: '输出', width: 80 }),
        h(ElTableColumn, { label: '结束原因', width: 100 }, { default: ({ row }) => h(ElTag, { size: 'small', type: row.finishReason === 'length' ? 'warning' : 'info' }, () => row.finishReason) }),
        h(ElTableColumn, { prop: 'seconds', label: '秒', width: 70 }),
        h(ElTableColumn, { label: '字数', width: 70 }, { default: ({ row }) => row.chars ?? '-' })
      ])
    ])
  }
})

const route = useRoute()
const router = useRouter()
const novel = ref(null)
const models = ref([])
const inferState = ref(null)
const loadError = ref('')
const tab = ref('write')
const titleDraft = ref('')
const editorRef = ref()
const ideaRef = ref()
const settingsDirty = ref(false)
const savingSettings = ref(false)

/** AI 构思用：设定编辑器里的全部分类（含未保存的新增分类）+ 当前设定（只含有内容的分类） */
function readSettings() {
  const editor = editorRef.value
  const config = editor ? editor.getConfig() : novel.value?.settings.config
  const spec = editor ? editor.getSpec() : novel.value?.settings.spec
  return {
    categories: (config?.categories || []).map((c) => ({ key: c.key, label: c.label, custom: !!c.custom })),
    spec: spec || []
  }
}
watch(tab, (t) => t === 'ideas' && ideaRef.value?.refreshSettings())

const view = ref('new')
const viewChapter = ref(null)
const form = reactive({ title: '', goal: '', targetChars: 2000 })
const job = ref(null)
const liveChapter = ref(null)
const liveBox = ref()
const previewing = ref(false)
const previewDlg = reactive({ visible: false, data: null })

const modelName = computed(() => models.value.find((m) => m.id === novel.value?.model.baseId)?.name || novel.value?.model.baseId)
const adapters = ref([])
/** 能加载到本工作区基础模型上的适配器；已选但现在不兼容的也列出，便于看到并改掉 */
const baseAdapters = computed(() => adapters.value.filter((a) => (a.compat === 'ok' && a.matchedBaseId === novel.value?.model.baseId) || a.id === novel.value?.model.adapterId))
const modelReady = computed(() => inferState.value?.status === 'loaded' && inferState.value.baseId === novel.value?.model.baseId &&
  (inferState.value.adapterId || null) === (novel.value?.model.adapterId || null))

/* ---- 大模型：使用 Java「模型配置」中启用且已验证的模型（打开页面时自动检测） ---- */
const isApi = computed(() => novel.value?.model.source === 'api')
const apiModel = ref(null)
const apiError = ref('')
const canGenerate = computed(() => (isApi.value ? !!apiModel.value : modelReady.value))
async function detectApi() {
  try {
    const list = await call(listAiModels(), '获取模型配置失败')
    apiModel.value = list.find((m) => m.active && m.status === 'VERIFIED') || null
    apiError.value = apiModel.value ? '' : '没有可用的大模型：请在「模型配置」中添加模型并验证通过'
  } catch (e) {
    apiModel.value = null
    apiError.value = `${e.message}（请确认 Java 后端已启动）`
  }
}

/* ---- 润色：本地基础模型 + 可选 LoRA 适配器 ---- */
const localModels = computed(() => models.value.filter((m) => m.exists))
const polish = reactive({ mode: 'none', baseId: '', adapterId: '' }) // mode: none | local | remote（预留）
const polishAdapters = computed(() => adapters.value.filter((a) => a.compat === 'ok' && a.matchedBaseId === polish.baseId))
const polishLabel = computed(() => {
  const base = localModels.value.find((m) => m.id === polish.baseId)?.name || '未选择模型'
  const a = adapters.value.find((x) => x.id === polish.adapterId)
  return `${base}${a ? ` + ${a.name}` : '（无适配器）'}`
})
const polishReq = () => ({ baseId: polish.baseId, adapterId: polish.adapterId || null })
const showOriginal = ref(false)
function initPolish(n) {
  // 默认：本地工作区用它自己的模型 / 适配器；大模型工作区用第一个本地模型及其第一个可用适配器
  const baseId = n.model.source === 'local' ? n.model.baseId : localModels.value[0]?.id || ''
  const adapterId = n.model.source === 'local' && n.model.adapterId ? n.model.adapterId
    : adapters.value.find((a) => a.compat === 'ok' && a.matchedBaseId === baseId)?.id || ''
  Object.assign(polish, { mode: n.model.source === 'api' && adapterId ? 'local' : 'none', baseId, adapterId })
}
/* ---- 大纲 / AI 构思 ---- */
const outlineNext = computed(() => novel.value?.outline?.chapters?.find((c) => c.index === nextIndex.value) || null)
function fillFromOutline() {
  if (!outlineNext.value) return
  form.title = outlineNext.value.title
  form.goal = outlineNext.value.goal
}
function onNovelUpdated(n) {
  novel.value = { ...novel.value, ...n }
  titleDraft.value = novel.value.title
  if (!form.goal.trim()) fillFromOutline()
}
function useChapterIdea({ title, goal }) {
  form.title = title
  form.goal = goal
  view.value = 'new'
  tab.value = 'write'
}

function phaseText(j) {
  if (j.phase === 'polish') return `正在润色 ${j.polishDone || 0} / ${j.polishTotal || '?'} 段（首次需加载本地模型）`
  return j.phase === 'summary' ? '正在生成章节摘要…' : `第 ${j.segment} 段`
}
const busy = computed(() => job.value && ['queued', 'running'].includes(job.value.status))
const nextIndex = computed(() => (novel.value?.chapters.length ? novel.value.chapters[novel.value.chapters.length - 1].index + 1 : 1))
const pct = (a, b) => (b ? Math.min(100, Math.round((a / b) * 100)) : 0)
const isLast = (i) => novel.value?.chapters.length && novel.value.chapters[novel.value.chapters.length - 1].index === i

async function call(promise, fallback) {
  try {
    const res = await promise
    if (res.code !== 0) throw new Error(res.message || fallback)
    return res.data
  } catch (e) {
    throw new Error(errorMessage(e, fallback))
  }
}

async function loadNovel() {
  try {
    const id = route.params.id
    const [n, s, m, a] = await Promise.all([call(getNovel(id), '加载工作区失败'), call(getGenStatus(), '获取状态失败'), call(listModels(), '获取模型失败'),
      call(listAdapters(), '获取适配器失败')])
    const first = novel.value?.id !== n.id
    novel.value = n
    models.value = m
    adapters.value = a
    inferState.value = s.inference
    titleDraft.value = n.title
    loadError.value = ''
    detectApi() // 大模型工作区生成用；所有工作区的「AI 构思」都用它
    if (first) {
      initPolish(n)
      settingsDirty.value = false
      view.value = 'new'
      viewChapter.value = null
      form.targetChars = n.defaultTargetChars || 2000
      form.title = ''
      form.goal = ''
      fillFromOutline()
      tab.value = n.settings.spec ? 'write' : 'settings'
      // 回到页面时接上仍在进行的生成任务
      job.value = s.activeJob && s.activeJob.novelId === n.id ? s.activeJob : null
    }
  } catch (e) {
    loadError.value = e.message
  }
}

async function refreshStatus() {
  try {
    inferState.value = (await call(getGenStatus(), '')).inference
  } catch {
    /* 下次重试 */
  }
}

async function saveTitle() {
  try {
    novel.value = { ...novel.value, ...(await call(updateNovel(novel.value.id, { title: titleDraft.value }), '保存失败')) }
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function saveAdapter(adapterId) {
  try {
    const n = await call(updateNovel(novel.value.id, { model: { ...novel.value.model, adapterId: adapterId || null } }), '保存失败')
    novel.value = { ...novel.value, model: n.model }
    ElMessage.success(adapterId ? '已选择适配器，点击「加载模型」生效' : '已改为只用基础模型，点击「加载模型」生效')
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  }
}

/** 切换模型来源（大模型 / 本地模型）；本地默认用原来的基础模型或第一个已登记的 */
async function changeSource(source) {
  const model = source === 'api'
    ? { source: 'api', apiName: apiModel.value ? `${apiModel.value.name} · ${apiModel.value.model}` : null }
    : { source: 'local', baseId: novel.value.model.baseId || localModels.value[0]?.id, adapterId: null }
  await saveModel(model, source === 'api' ? (apiModel.value ? '已切换为大模型' : '已切换为大模型：请先在「模型配置」中启用一个模型') : '已切换为本地模型，点击「加载模型」生效')
}
async function changeBase(baseId) {
  await saveModel({ source: 'local', baseId, adapterId: null }, '已更换基础模型（适配器已清空），点击「加载模型」生效')
}
async function saveModel(model, msg) {
  try {
    const n = await call(updateNovel(novel.value.id, { model }), '保存失败')
    novel.value = { ...novel.value, model: n.model }
    ElMessage.success(msg)
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  }
}

async function saveWindow(w) {
  try {
    await call(updateNovel(novel.value.id, { contextWindow: w }), '保存失败')
    ElMessage.success(`上下文窗口已设为 ${w}`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function saveSettings(silent = false) {
  if (!editorRef.value) return
  savingSettings.value = true
  try {
    const settings = { config: editorRef.value.getConfig(), spec: editorRef.value.getSpec() }
    const n = await call(updateNovel(novel.value.id, { settings }), '保存设定失败')
    novel.value = { ...novel.value, ...n }
    settingsDirty.value = false
    if (!silent) ElMessage.success('设定已保存')
  } catch (e) {
    ElMessage.error(e.message)
    throw e
  } finally {
    savingSettings.value = false
  }
}

async function onLoadModel() {
  try {
    inferState.value = await call(loadNovelModel(novel.value.id), '加载模型失败')
    schedule()
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  }
}

const chapterReq = () => ({ goal: form.goal.trim(), title: form.title.trim(), targetChars: form.targetChars })

async function onPreview() {
  previewing.value = true
  try {
    if (settingsDirty.value) await saveSettings(true)
    previewDlg.data = await call(previewContext(novel.value.id, chapterReq()), '预览失败')
    previewDlg.visible = true
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    previewing.value = false
  }
}

async function onStart() {
  try {
    if (settingsDirty.value) await saveSettings(true)
    if (!novel.value.settings.spec?.length) {
      await ElMessageBox.confirm('还没有确认任何设定，模型将只根据本章目标自由创作。继续吗？', '提示', { type: 'warning' })
    }
    const body = { ...chapterReq(), polish: polish.mode === 'local' && polish.baseId ? { enabled: true, ...polishReq() } : null }
    job.value = await call(startChapter(novel.value.id, body, isApi.value), '启动生成失败')
    liveChapter.value = null
    if (!busy.value) await loadNovel() // 任务在返回前就已结束（极少见）：直接刷新
    schedule()
  } catch (e) {
    if (e !== 'cancel' && e?.message) ElMessage.error({ message: e.message, duration: 6000 })
  }
}

async function onCancel() {
  try {
    job.value = await call(cancelGenJob(job.value.id), '取消失败')
    ElMessage.info('已请求取消，当前 token 生成后停止')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function onPolishChapter() {
  try {
    job.value = await call(polishChapter(novel.value.id, viewChapter.value.index, polishReq()), '启动润色失败')
    liveChapter.value = null
    showOriginal.value = false
    if (!busy.value) await openChapter(viewChapter.value.index)
    schedule()
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  }
}

async function onRevertPolish() {
  try {
    await ElMessageBox.confirm('恢复为润色前的原文？润色结果将被丢弃。', '恢复原文', { type: 'warning' })
  } catch {
    return
  }
  try {
    viewChapter.value = await call(revertPolish(novel.value.id, viewChapter.value.index), '恢复失败')
    showOriginal.value = false
    ElMessage.success('已恢复原文')
    await loadNovel()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

/* ---- 手动修改：章节（标题 / 目标 / 摘要 / 正文）与前情概要，AI 生成的内容都可以改 ---- */
const chapterEdit = reactive({ active: false, saving: false, title: '', goal: '', summary: '', text: '' })
function startChapterEdit() {
  const c = viewChapter.value
  Object.assign(chapterEdit, { active: true, title: c.title || '', goal: c.goal || '', summary: c.summary || '', text: c.text || '' })
  showOriginal.value = false
}
async function saveChapterEdit() {
  chapterEdit.saving = true
  try {
    const { title, goal, summary, text } = chapterEdit
    viewChapter.value = await call(editChapter(novel.value.id, viewChapter.value.index, { title, goal, summary, text }), '保存失败')
    chapterEdit.active = false
    ElMessage.success('已保存修改')
    await loadNovel()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    chapterEdit.saving = false
  }
}
const arcEdit = reactive({ visible: false, saving: false, text: '' })
function openArcEdit() {
  Object.assign(arcEdit, { visible: true, text: novel.value.arcSummary || '' })
}
async function saveArcEdit() {
  arcEdit.saving = true
  try {
    const n = await call(updateNovel(novel.value.id, { arcSummary: arcEdit.text }), '保存失败')
    novel.value = { ...novel.value, arcSummary: n.arcSummary }
    arcEdit.visible = false
    ElMessage.success('前情概要已更新')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    arcEdit.saving = false
  }
}

async function openChapter(index) {
  if (chapterEdit.active && viewChapter.value?.index !== index) chapterEdit.active = false
  view.value = index
  showOriginal.value = false
  try {
    viewChapter.value = await call(getChapter(novel.value.id, index), '加载章节失败')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function onDeleteChapter(index) {
  try {
    await ElMessageBox.confirm(`删除第${index}章？只能删除最后一章，以保证前情摘要连贯。`, '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await call(deleteChapter(novel.value.id, index), '删除失败')
    view.value = 'new'
    viewChapter.value = null
    await loadNovel()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

/* ---------------- 轮询：生成中 / 模型加载中 ---------------- */
let timer = null
function schedule() {
  clearTimeout(timer)
  const active = busy.value || inferState.value?.status === 'loading'
  if (!active) return
  timer = setTimeout(async () => {
    if (busy.value) {
      try {
        const j = await call(getGenJob(job.value.id), '')
        const { chapter, ...rest } = j
        job.value = rest
        liveChapter.value = chapter
        await nextTick()
        if (liveBox.value) liveBox.value.scrollTop = liveBox.value.scrollHeight
        if (!['queued', 'running'].includes(rest.status)) {
          if (rest.status === 'succeeded' && rest.kind === 'polish') {
            ElMessage.success(`第${rest.chapterIndex}章润色完成`)
          } else if (rest.status === 'succeeded') {
            ElMessage.success(`第${rest.chapterIndex}章完成${rest.phase === 'polish' ? '（已润色）' : ''}`)
            form.title = ''
            form.goal = ''
          }
          await loadNovel()
          if (rest.status === 'succeeded' && rest.kind !== 'polish') fillFromOutline() // 有大纲时自动填入下一章
          if (view.value === rest.chapterIndex) await openChapter(rest.chapterIndex)
        }
      } catch {
        /* 下次重试 */
      }
    }
    await refreshStatus()
    schedule()
  }, 2000)
}

watch(() => route.params.id, (id) => id && route.name === 'novelWorkspace' && loadNovel().then(schedule))
onActivated(() => loadNovel().then(schedule))
onDeactivated(() => clearTimeout(timer))
</script>

<style scoped>
.box-card {
  margin-bottom: 16px;
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.head-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 13px;
  color: #606266;
}
.title-input {
  width: 240px;
}
.title-input :deep(.el-input__inner) {
  font-size: 15px;
  font-weight: 600;
}
.head-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.model-state {
  margin-left: auto;
}
.mt {
  margin-top: 10px;
}
.chapter-edit {
  margin-top: 10px;
}
.outline-hint {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
}
.polish-row,
.polish-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.polish-bar {
  margin: 8px 0;
  font-size: 12px;
}
.dirty-dot {
  margin-left: 4px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.hint {
  margin-left: 10px;
}
.write-grid {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 18px;
}
.col-title {
  margin: 8px 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.chapter-item {
  padding: 8px 10px;
  margin-bottom: 4px;
  font-size: 13px;
  border-radius: 6px;
  cursor: pointer;
}
.chapter-item:hover {
  background: #f5f7fa;
}
.chapter-item.is-active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.chapter-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.totals {
  margin-top: 14px;
  padding-top: 8px;
  font-size: 12px;
  color: #606266;
  border-top: 1px solid #ebeef5;
}
.chapter-form {
  max-width: 820px;
}
.progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.progress-bar {
  flex: 1;
  max-width: 360px;
}
.chapter-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.chapter-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.goal {
  margin-top: 6px;
}
.summary {
  margin-top: 10px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.7;
  background: #f8faff;
  border-left: 3px solid var(--el-color-primary-light-5);
}
.chapter-text {
  max-height: 60vh;
  margin: 12px 0 0;
  padding: 14px 16px;
  overflow: auto;
  font-family: inherit;
  font-size: 15px;
  line-height: 1.9;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fffdf7;
  border: 1px solid #f0e9d8;
  border-radius: 6px;
}
:deep(.ctx-report) {
  margin-top: 14px;
}
.prompt-block {
  margin-top: 12px;
}
.prompt-text {
  max-height: 32vh;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  background: #f7f8fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}
</style>
