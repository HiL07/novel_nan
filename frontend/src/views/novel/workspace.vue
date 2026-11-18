<template>
  <div class="workspace-page study">
    <!-- 工作区「书房」：顶栏（书名 / 作品定位 / 模型 / 字数）· 左栏（当前分区的子目录）· 中间内容卡片 · 右侧分区图标栏 · 底部状态栏 -->
    <StudyHeader
      v-if="novel"
      v-model:title="titleDraft"
      :chips="positionChips"
      :detail="positioningText"
      :chapter-words="chapterWords"
      :total-words="totalWords"
      @exit="router.push('/novel/create')"
      @rename="saveTitle"
      @positioning="openBookConfig"
    >
      <!-- 模型：一个小标签，点开是原来头部的那些设置（来源 / 基础模型 / 适配器 / 上下文窗口 / 加载） -->
      <el-popover placement="bottom-end" :width="560" trigger="click">
        <template #reference>
          <button class="model-chip" type="button" :title="modelStateText">
            <span class="state-dot" :class="`is-${modelState}`" />
            <span class="model-chip-text">{{ modelChipText }}</span>
            <el-icon><ArrowDown /></el-icon>
          </button>
        </template>
        <div class="model-pop">
          <div class="pop-title">本工作区的模型</div>
          <div class="pop-row">
            <span class="pop-label">来源</span>
            <el-select :model-value="novel.model.source" size="small" style="width: 230px" :disabled="busy" @change="changeSource">
              <el-option label="大模型（API）" value="api" />
              <el-option label="本地模型（safetensors · 可训练）" value="local" :disabled="!localModels.length" />
              <el-option :label="llama ? 'GGUF（llama.cpp）' : 'GGUF（llama.cpp · 未启动）'" value="gguf" :disabled="!llama" />
              <el-option label="远程模型（即将支持）" value="remote" disabled />
            </el-select>
          </div>
          <div class="pop-row">
            <span class="pop-label">模型</span>
            <span v-if="isApi" class="pop-value">{{ apiModel ? `${apiModel.name} · ${apiModel.model}` : novel.model.apiName || '当前启用的模型' }}</span>
            <span v-else-if="isGguf" class="pop-value">{{ llama ? llama.name : '—' }}</span>
            <el-select v-else :model-value="novel.model.baseId" size="small" style="width: 230px" :disabled="busy" @change="changeBase">
              <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>
          </div>
          <div v-if="isLocal" class="pop-row">
            <span class="pop-label">适配器</span>
            <el-select
              :model-value="novel.model.adapterId || ''"
              size="small"
              style="width: 230px"
              :disabled="busy || novel.model.source !== 'local'"
              @change="saveAdapter"
            >
              <el-option label="不使用" value="" />
              <el-option v-for="a in baseAdapters" :key="a.id" :label="a.name" :value="a.id" />
            </el-select>
          </div>
          <div v-if="isLocal" class="pop-note muted">LoRA 风格适配器：章节正文用它生成，章节摘要始终用基础模型；切换后点「加载模型」生效（同一基础模型只切换适配器，不重载）</div>
          <div class="pop-row">
            <span class="pop-label">上下文窗口</span>
            <el-select v-model="novel.contextWindow" size="small" style="width: 230px" :disabled="busy" @change="saveWindow">
              <el-option v-for="w in CONTEXT_WINDOWS" :key="w" :label="`${w} tokens`" :value="w" />
            </el-select>
          </div>
          <div class="pop-row">
            <span class="pop-label">状态</span>
            <template v-if="isApi">
              <el-tag :type="apiModel ? 'success' : 'warning'" size="small">{{ apiModel ? '大模型可用' : '没有可用的大模型' }}</el-tag>
              <el-button v-if="!apiModel" size="small" type="primary" @click="router.push('/ai/model')">去配置模型</el-button>
              <el-button v-if="!apiModel" size="small" @click="detectApi">重新检测</el-button>
            </template>
            <template v-else-if="isGguf">
              <el-tag :type="llama ? 'success' : 'warning'" size="small">{{ llama ? 'llama.cpp 运行中' : 'llama.cpp 未启动' }}</el-tag>
              <el-button v-if="!llama" size="small" type="primary" @click="router.push('/ai/llama')">去启动</el-button>
              <el-button v-if="!llama" size="small" @click="detectLlama">重新检测</el-button>
            </template>
            <template v-else>
              <el-tag :type="modelReady ? 'success' : inferState?.status === 'loading' ? 'warning' : 'info'" size="small">
                {{ modelReady ? '模型已加载' : inferState?.status === 'loading' ? '加载中…' : '模型未加载' }}
              </el-tag>
              <el-button v-if="!modelReady" size="small" type="primary" :loading="inferState?.status === 'loading'" :disabled="busy" @click="onLoadModel">加载模型</el-button>
            </template>
          </div>
        </div>
      </el-popover>
    </StudyHeader>

    <div v-if="loadError || inferState?.status === 'error' || (isApi && apiError) || modelMismatch" class="study-alerts">
      <el-alert v-if="loadError" type="error" :closable="false" show-icon :title="loadError" />
      <el-alert v-if="inferState?.status === 'error'" type="error" :closable="false" show-icon :title="`模型加载失败：${inferState.error}`" />
      <el-alert v-if="isApi && apiError" type="warning" :closable="false" show-icon :title="apiError" />
      <el-alert
        v-if="modelMismatch"
        type="info"
        :closable="false"
        show-icon
        :title="`当前加载的模型${inferState.baseId === novel.model.baseId ? '适配器设置' : ''}与本工作区不一致：点顶栏的模型标签，再点「加载模型」切换${inferState.baseId === novel.model.baseId ? '（只切换适配器，不重载基础模型）' : ''}`"
      />
    </div>

    <div v-if="novel" class="study-body">
      <!-- 左栏：当前分区的子目录 -->
      <aside class="study-left" :class="{ 'is-folded': leftFolded }">
        <div class="left-inner">
          <div class="left-head">
            <div class="left-title">{{ SECTIONS[tab]?.label }}</div>
            <div class="left-sub">{{ SECTIONS[tab]?.sub }}</div>
          </div>
          <el-scrollbar class="left-scroll">
            <!-- 自动规划：竖排步骤（PlanWizard expose 的 nav） -->
            <template v-if="tab === 'plan'">
              <template v-if="planRef?.nav">
                <div
                  v-for="(s, i) in planRef.nav.steps"
                  :key="s.key"
                  class="study-nav-item step-item"
                  :class="{ 'is-active': i === planRef.nav.stepIndex, 'is-done': i < planRef.nav.stepIndex, 'is-busy': !!planRef.nav.busy }"
                  @click="planRef.nav.goStep(s.key)"
                >
                  <span class="step-no">{{ i < planRef.nav.stepIndex ? '✓' : i + 1 }}</span>
                  <span>{{ s.title }}</span>
                </div>
              </template>
              <p class="left-tip">先搭框架：参数 · 灵感 → 设定 → 全书骨架。写进工作区后，设定 / AI 构思 / 写作 / 故事账本 / 世界书会出现在右侧</p>
            </template>

            <!-- 设定：分类目录（SettingsEditor expose 的 nav） -->
            <SettingsNav v-else-if="tab === 'settings'" :nav="editorRef?.nav" />

            <!-- 写作：章节目录 -->
            <template v-else-if="tab === 'write'">
              <div class="chapter-item new-item" :class="{ 'is-active': view === 'new' }" @click="view = 'new'">
                <el-icon><EditPen /></el-icon> 写下一章（第{{ nextIndex }}章）
              </div>
              <div class="chapter-count">已写 {{ novel.chapters.length }} 章</div>
              <div
                v-for="c in novel.chapters"
                :key="c.index"
                class="chapter-item"
                :class="{ 'is-active': view === c.index }"
                @click="openChapter(c.index)"
              >
                <div class="chapter-line">
                  <span class="chapter-name">第{{ c.index }}章 {{ c.title }}</span>
                  <span class="chapter-tags">
                    <el-tooltip v-if="c.reviewIssues" :content="`一致性检查发现 ${c.reviewIssues} 个问题`" placement="top">
                      <el-tag size="small" type="danger" effect="plain">{{ c.reviewIssues }}</el-tag>
                    </el-tooltip>
                    <el-tag v-if="c.status !== 'done'" size="small" :type="CH_STATUS[c.status]?.type">{{ CH_STATUS[c.status]?.label || c.status }}</el-tag>
                  </span>
                </div>
                <div class="muted">{{ c.chars }} 字<template v-if="c.totals"> · {{ c.totals.promptTokens + c.totals.completionTokens }} tokens</template></div>
              </div>
              <div v-if="novel.arcSummary" class="totals">
                <div class="col-title">
                  前情概要（已合并至第 {{ novel.arcUpTo }} 章）
                  <el-button link type="primary" size="small" :icon="EditPen" :disabled="busy" @click="openArcEdit">修改</el-button>
                </div>
                <div class="muted arc-text">{{ novel.arcSummary }}</div>
              </div>
            </template>

            <!-- AI 构思 / 故事账本 / 世界书：内容里带 data-anchor 的小节 -->
            <AnchorNav v-else :root="anchorRoot" :scroller="centerEl" :empty="SECTIONS[tab]?.empty" />
          </el-scrollbar>
        </div>
        <button class="fold-handle" type="button" :title="leftFolded ? '展开左栏' : '收起左栏'" @click="toggleLeft">
          <el-icon><component :is="leftFolded ? 'ArrowRight' : 'ArrowLeft'" /></el-icon>
        </button>
      </aside>

      <!-- 中间：左 = 内容卡片（分区面板都常驻、标签头藏起来：写进工作区时要用设定编辑器）；右 = 设定页的素材库 -->
      <div class="study-center">
      <main ref="centerEl" class="center-main">
      <el-tabs v-model="tab" class="ws-tabs">
        <!-- ===================== 设定 ===================== -->
        <el-tab-pane name="settings">
          <template #label><span>设定</span><el-badge v-if="settingsDirty" is-dot class="dirty-dot" /></template>
          <el-dialog v-model="bookConfigDialog.visible" title="作品定位 / 写作参数" width="720px" append-to-body>
            <BookConfigForm v-if="bookConfigDialog.cfg" v-model="bookConfigDialog.cfg" />
            <template #footer>
              <el-button @click="bookConfigDialog.visible = false">取消</el-button>
              <el-button type="primary" :loading="bookConfigDialog.saving" @click="saveBookConfig">保存</el-button>
            </template>
          </el-dialog>
          <SettingsEditor
            :key="novel.id"
            ref="editorRef"
            :config="novel.settings.config"
            :novel-id="novel.id"
            :ai="{ apiModel, localModels, adapters, llama, model: novel.model }"
            external-nav
            @change="settingsDirty = true"
          >
            <template #actions>
              <el-button type="primary" :icon="Check" :loading="savingSettings" @click="saveSettings()">保存设定</el-button>
            </template>
          </SettingsEditor>
        </el-tab-pane>

        <!-- ===================== 自动规划 ===================== -->
        <el-tab-pane v-if="planning" label="自动规划" name="plan" lazy>
          <!-- :key = 工作区 id：页面是 keep-alive 复用的，切换工作区时必须整个重建，否则会带着上一个工作区的草稿（还会存进新工作区） -->
          <div class="study-card">
          <el-alert type="info" show-icon :closable="false" class="frame-tip"
                    title="新工作区：先在「自动规划」里搭好框架（参数 · 灵感 → 设定 → 全书骨架），写进工作区后，设定 / AI 构思 / 写作 / 故事账本 / 世界书会出现" />
          <PlanWizard
            :key="novel.id"
            ref="planRef"
            external-steps
            :novel-id="novel.id"
            :chapter-count="novel.chapters.length ? Math.max(...novel.chapters.map((c) => c.index)) : 0"
            :initial-premise="String(route.query.plan || '')"
            :apply-settings="applyPlanSettings"
            :book="novel.book || null"
            :book-config="novel.bookConfig || null"
            @applied="onPlanApplied"
          />
          </div>
        </el-tab-pane>

        <!-- ===================== 构思 ===================== -->
        <el-tab-pane name="ideas" lazy>
          <template #label><span>AI 构思</span></template>
          <!-- 同上：构思结果、大纲草稿、勾选记录都是按工作区的，切换工作区要重建 -->
          <div ref="ideasBox" class="study-card">
          <IdeaPanel
            :key="novel.id"
            ref="ideaRef"
            :novel="novel"
            :read-settings="readSettings"
            :local-models="localModels"
            :adapters="adapters"
            :api-model="apiModel"
            :llama="llama"
            :next-index="nextIndex"
            @updated="onNovelUpdated"
            @use-chapter="useChapterIdea"
            @detect-api="detectApi"
          />
          </div>
        </el-tab-pane>

        <!-- ===================== 写作 ===================== -->
        <el-tab-pane name="write">
          <template #label><span>写作</span></template>
          <div class="study-card write-card">
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
                    <!-- 「按全书骨架规划接下来 10 章」依赖自动规划的大纲步骤，大纲步骤先拿掉了，按钮一起隐藏（docs/待办.md「待定」） -->
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
                <el-form-item label="写作流程">
                  <div class="polish-row">
                    <el-tooltip content="动笔前把本章拆成 3~6 个节拍 + 章末钩子，分段写时每段按节拍推进（多 1 次调用）" placement="top">
                      <el-checkbox :model-value="flow.planChapter" :disabled="busy" @change="(v) => saveFlow('planChapter', v)">先规划节拍</el-checkbox>
                    </el-tooltip>
                    <el-tooltip content="写摘要时同时抽取伏笔 / 角色状态 / 时间线，记入「故事账本」，后续章节自动参考（与摘要同一次调用）" placement="top">
                      <el-checkbox :model-value="flow.extractFacts" :disabled="busy" @change="(v) => saveFlow('extractFacts', v)">提取故事事实</el-checkbox>
                    </el-tooltip>
                    <el-tooltip content="写完对照设定、故事账本和前情检查矛盾，只报告不改稿（多 1 次调用；本地小模型默认关闭，查得不准）" placement="top">
                      <el-checkbox :model-value="flow.reviewChapter" :disabled="busy" @change="(v) => saveFlow('reviewChapter', v)">写完检查一致性</el-checkbox>
                    </el-tooltip>
                  </div>
                </el-form-item>
                <el-form-item>
                  <el-button :icon="View" :loading="previewing" :disabled="!form.goal.trim()" @click="onPreview">预览上下文</el-button>
                  <el-button v-if="!busy" type="primary" :icon="VideoPlay" :disabled="!form.goal.trim() || !canGenerate" @click="onStart">开始生成</el-button>
                  <el-button v-else type="danger" :icon="VideoPause" @click="onCancel">取消</el-button>
                  <span v-if="!canGenerate && !busy" class="muted hint">{{ isApi ? '请先在「模型配置」中启用大模型' : isGguf ? '请先到「llama.cpp」页启动 GGUF 模型' : '请先加载模型' }}</span>
                </el-form-item>
              </el-form>

              <template v-if="job && job.kind === 'chapter'">
                <div class="progress-row">
                  <el-tag :type="JOB_STATUS[job.status].type">{{ JOB_STATUS[job.status].label }}</el-tag>
                  <span>{{ phaseText(job) }}</span>
                  <el-progress v-if="job.phase === 'polish'" class="progress-bar" :percentage="pct(job.polishDone, job.polishTotal)" />
                  <el-progress v-else class="progress-bar" :percentage="pct(liveChapter?.text.length || 0, liveChapter?.targetChars || form.targetChars)" />
                  <span class="muted">{{ liveChapter?.text.length || 0 }} / {{ liveChapter?.targetChars || form.targetChars }} 字</span>
                </div>
                <el-alert v-if="job.error" type="error" :closable="false" show-icon :title="job.error" class="mt" />
                <ChapterInsight
                  v-if="liveChapter?.plan || liveChapter?.planError"
                  :key="`live-${liveChapter.index}`"
                  :chapter="liveChapter"
                  live
                  :current-beat="job.phase === 'writing' ? beatAt(liveChapter) : -1"
                />
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
              <ChapterInsight
                v-if="viewChapter.status === 'done'"
                :key="`view-${viewChapter.index}`"
                :chapter="viewChapter"
                :can-run="!busy && canGenerate"
                @recheck="onRecheck"
                @ignore="onIgnoreReview"
                @jump="jumpToQuote"
              />
              <div v-if="recheckJob" class="progress-row mt">
                <el-tag type="warning">{{ recheckJob.phase === 'review' ? '一致性检查中' : '提取事实中' }}</el-tag>
                <span class="muted">第{{ recheckJob.chapterIndex }}章</span>
                <el-button size="small" type="danger" :icon="VideoPause" @click="onCancel">取消</el-button>
              </div>
              <pre class="chapter-text"><template v-if="highlight.parts">{{ highlight.parts[0] }}<mark ref="markEl" class="quote-mark">{{ highlight.parts[1] }}</mark>{{ highlight.parts[2] }}</template><template v-else>{{ shownText }}</template></pre>
              </template>
              <CallTable v-if="viewChapter.calls?.length" :calls="viewChapter.calls" :totals="viewChapter.totals" />
            </div>
          </div>
        </el-tab-pane>

        <!-- ===================== 故事账本 ===================== -->
        <el-tab-pane name="facts">
          <template #label>
            <span>故事账本</span><el-badge v-if="openForeshadows" :value="openForeshadows" type="warning" class="facts-badge" />
          </template>
          <div ref="factsBox" class="study-card">
            <FactsPanel :novel-id="novel.id" :locked="!!busy" :reload-key="factsKey" @open-count="(n) => (openForeshadows = n)" />
          </div>
        </el-tab-pane>

        <!-- ===================== 世界书 ===================== -->
        <el-tab-pane name="worldbook" lazy>
          <template #label><span>世界书</span></template>
          <div ref="worldBox" class="study-card">
            <WorldBook :novel-id="novel.id" :reload-key="factsKey" />
          </div>
        </el-tab-pane>
      </el-tabs>
      </main>
      <MaterialDock
        v-if="tab === 'settings' && editorRef?.nav"
        :novel-id="novel.id"
        :category="editorRef.nav.materialCategory"
        :categories="editorRef.nav.allCategories"
        :context-query="editorRef.nav.contextQuery"
        :used-ids="editorRef.nav.usedMaterialIds"
        :apply="editorRef.nav.applyMaterials"
      />
      </div>

      <!-- 右侧：分区图标栏 -->
      <StudyRail v-model="tab" :items="navTabs" />
    </div>

    <!-- 底部状态栏 -->
    <footer v-if="novel" class="study-status">
      <span class="status-item">
        <span class="state-dot" :class="`is-${modelState}`" />{{ modelStateText }}
      </span>
      <span class="status-item">上下文 {{ novel.contextWindow }} tokens</span>
      <span v-if="busy && job" class="status-item is-job">
        <el-icon class="is-loading"><Loading /></el-icon>
        {{ job.kind === 'polish' ? '润色' : job.kind === 'recheck' ? '重新检查' : `第${job.chapterIndex}章` }} · {{ phaseText(job) }}
        <template v-if="job.kind === 'chapter' && job.phase !== 'polish'"> · {{ pct(liveChapter?.text.length || 0, liveChapter?.targetChars || form.targetChars) }}%</template>
        <el-button link type="primary" size="small" @click="goJob">查看</el-button>
      </span>
      <span class="status-spacer" />
      <span v-if="settingsDirty" class="status-item is-dirty">
        设定未保存 <el-button link type="primary" size="small" :loading="savingSettings" @click="saveSettings()">保存</el-button>
      </span>
      <span class="status-item">累计 token：输入 {{ novel.tokenTotals.promptTokens }} · 输出 {{ novel.tokenTotals.completionTokens }} · {{ novel.tokenTotals.calls }} 次调用</span>
    </footer>

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
import { ArrowDown, Check, CopyDocument, Delete, EditPen, Loading, MagicStick, VideoPause, VideoPlay, View } from '@element-plus/icons-vue'
import SettingsEditor from '@/components/novel-options/SettingsEditor.vue'
import IdeaPanel from '@/components/novel/IdeaPanel.vue'
import FactsPanel from '@/components/novel/FactsPanel.vue'
import WorldBook from '@/components/novel/WorldBook.vue'
import PlanWizard from '@/components/novel/PlanWizard.vue'
import BookConfigForm from '@/components/novel/BookConfigForm.vue'
import { blankBookConfig } from '@/api/novelPlan'
import ChapterInsight from '@/components/novel/ChapterInsight.vue'
import StudyHeader from '@/components/novel/study/StudyHeader.vue'
import StudyRail from '@/components/novel/study/StudyRail.vue'
import SettingsNav from '@/components/novel/study/SettingsNav.vue'
import AnchorNav from '@/components/novel/study/AnchorNav.vue'
import MaterialDock from '@/components/material/MaterialDock.vue'
import {
  CONTEXT_WINDOWS, cancelGenJob, deleteChapter, editChapter, getChapter, getGenJob, getGenStatus, getNovel, ignoreReview,
  loadNovelModel, polishChapter, previewContext, recheckChapter, revertPolish, startChapter, updateNovel
} from '@/api/novelGen'
import { isGenerationModel, listAdapters, listModels, runningLlama } from '@/api/localModel'
import { listModels as listAiModels } from '@/api/aiModel'
import { errorMessage } from '@/api/request'
import { APPLY_KEY as INSPIRE_KEY } from '@/api/inspire'

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
const LAYER_LABEL = {
  L0_core: 'L0 核心规则', L1_cards: 'L1 按需设定', L1b_facts: 'L1b 故事账本', L2_story: 'L2 前情', L3_recent: 'L3 最近正文',
  L4_task: 'L4 本次任务'
}

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
          r.included.facts ? '；含故事账本' : '',
          r.included.nextPreview ? '；含下一章预告' : '',
          `；最近正文 ${r.included.recentChars} 字`
        ]),
        r.dropped.cards.length || r.dropped.summaries.length || r.dropped.facts || r.dropped.nextPreview
          ? h('div', { class: 'muted' }, `未放入（不相关或超出预算）：${[...r.dropped.cards, ...r.dropped.summaries.map((i) => `第${i}章摘要`),
            ...(r.dropped.facts ? ['故事账本'] : []), ...(r.dropped.nextPreview ? ['下一章预告'] : [])].join('、')}`)
          : null
      ])
    }
  }
})

/** 每次模型调用的 token 明细 */
const CallTable = defineComponent({
  props: { calls: Array, totals: Object },
  setup(props) {
    const TYPE = { segment: '正文分段', summary: '章节摘要', arc: '前情合并', plan: '章节规划', digest: '摘要+事实', review: '一致性检查', polish: '润色' }
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
// 工作区搭好框架了没有：有全书骨架、保存过设定、或已经写过章节。没搭好之前只能用「自动规划」
const framed = computed(() => !!(novel.value?.book || novel.value?.settings?.spec?.length || novel.value?.chapters?.length))
// 规划中：打开时还没搭框架。只显示「自动规划」；第一次「写进工作区」后关掉（不直接用 framed：写进时设定先保存，framed 会提前变）
const planning = ref(false)
watch([tab, planning], ([t, p]) => {
  if (!novel.value) return
  if (p && t !== 'plan') tab.value = 'plan'
  else if (!p && t === 'plan') tab.value = 'settings'
})
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
const canGenerate = computed(() => (isApi.value ? !!apiModel.value : isGguf.value ? !!llama.value : modelReady.value))

/* ---- GGUF：「llama.cpp」页启动的模型（没在运行时不能选、不能生成；本地直连 Python，不经 Java） ---- */
const isGguf = computed(() => novel.value?.model.source === 'gguf')
const isLocal = computed(() => novel.value?.model.source === 'local')
const llama = ref(null)
async function detectLlama() {
  llama.value = await runningLlama()
}
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
const localModels = computed(() => models.value.filter((m) => m.exists && isGenerationModel(m)))
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
  if (j.phase === 'plan') return '正在规划本章节拍…'
  if (j.phase === 'review') return '正在检查一致性…'
  if (j.phase === 'summary') return flow.value.extractFacts ?'正在写摘要并提取故事事实…' : '正在生成章节摘要…'
  return `第 ${j.segment} 段`
}

/* ---- 写作流程：规划节拍 / 提取故事事实 / 一致性检查（存在工作区 params；reviewChapter 为 null = 大模型开、本地关） ---- */
const flow = computed(() => {
  const p = novel.value?.params || {}
  return {
    planChapter: p.planChapter ?? true,
    extractFacts: p.extractFacts ?? true,
    reviewChapter: p.reviewChapter ?? isApi.value
  }
})
async function saveFlow(key, value) {
  try {
    const n = await call(updateNovel(novel.value.id, { params: { [key]: value } }), '保存失败')
    novel.value = { ...novel.value, params: n.params }
  } catch (e) {
    ElMessage.error(e.message)
  }
}
/** 与后端 prompts.beat_at 相同：按已写字数占比估计当前节拍 */
function beatAt(c) {
  const n = c?.plan?.beats?.length
  if (!n) return -1
  return Math.min(n - 1, Math.floor(((c.text?.length || 0) / Math.max(c.targetChars || 1, 1)) * n))
}

/* ---- 故事账本 / 重新提取 / 一致性检查 ---- */
const factsKey = ref(0)
const openForeshadows = ref(0)
const recheckJob = computed(() => (busy.value && job.value?.kind === 'recheck' && job.value.chapterIndex === viewChapter.value?.index ? job.value : null))
async function onRecheck({ digest, review }) {
  try {
    job.value = await call(recheckChapter(novel.value.id, viewChapter.value.index, { digest, review }, isApi.value), '启动失败')
    liveChapter.value = null
    if (!busy.value) await openChapter(viewChapter.value.index)
    schedule()
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  }
}
async function onIgnoreReview(ignored) {
  try {
    viewChapter.value = await call(ignoreReview(novel.value.id, viewChapter.value.index, ignored), '操作失败')
    await loadNovel()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
/* 一致性问题定位：把摘录的原句高亮并滚动到可见 */
const markEl = ref()
const highlight = reactive({ quote: '', parts: null })
const shownText = computed(() => {
  const c = viewChapter.value
  if (!c) return ''
  if (showOriginal.value && c.originalText) return c.originalText
  return (busy.value && job.value?.kind === 'polish' && job.value.chapterIndex === c.index && liveChapter.value?.polishDraft) || c.text
})
watch(shownText, () => Object.assign(highlight, { quote: '', parts: null }))
async function jumpToQuote(quote) {
  const text = shownText.value
  const i = text.indexOf(quote)
  if (i < 0) return ElMessage.warning(showOriginal.value ? '原文中找不到这句（问题针对的是当前正文）' : '正文中找不到这句（可能已修改）')
  Object.assign(highlight, { quote, parts: [text.slice(0, i), quote, text.slice(i + quote.length)] })
  await nextTick()
  markEl.value?.scrollIntoView({ block: 'center', behavior: 'smooth' })
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
    detectLlama()
    if (first) {
      initPolish(n)
      settingsDirty.value = false
      view.value = 'new'
      viewChapter.value = null
      form.targetChars = n.defaultTargetChars || 2000
      form.title = ''
      form.goal = ''
      fillFromOutline()
      planning.value = !framed.value
      tab.value = planning.value ? 'plan' : n.settings.spec?.length ? 'write' : 'settings'
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

/* ---- 作品定位（写作参数 novel.bookConfig）：写正文进【作品定位】；全书骨架写完 10 章后一键续规划 ---- */
const POSITION_KEYS = ['platform', 'genre', 'audience', 'sellingPoint', 'pov', 'style']
const positioningText = computed(() => {
  const c = novel.value?.bookConfig
  if (!c) return ''
  return [...POSITION_KEYS.slice(0, 3).map((k) => c[k]), c.tags?.join('、'), ...POSITION_KEYS.slice(3).map((k) => c[k])]
    .filter(Boolean).join(' · ')
})
const bookConfigDialog = reactive({ visible: false, saving: false, cfg: null })
function openBookConfig() {
  bookConfigDialog.cfg = { ...blankBookConfig(), ...(novel.value.bookConfig || {}) }
  bookConfigDialog.visible = true
}
async function saveBookConfig() {
  bookConfigDialog.saving = true
  try {
    novel.value = { ...novel.value, ...(await call(updateNovel(novel.value.id, { bookConfig: bookConfigDialog.cfg }), '保存失败')) }
    bookConfigDialog.visible = false
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    bookConfigDialog.saving = false
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
  if (source === 'gguf') {
    await detectLlama()
    if (!llama.value) return ElMessage.warning('llama.cpp 没有运行：请先到「llama.cpp」页启动一个 GGUF 模型')
    return saveModel({ source: 'gguf' }, `已切换为 GGUF：${llama.value.name}`)
  }
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
    if (viewChapter.value.factsStale && canGenerate.value && !busy.value) {
      try {
        await ElMessageBox.confirm('正文改过了，要重新提取本章的摘要和故事事实吗？（会替换故事账本里本章的记录，调用一次模型）',
          '重新提取本章事实', { confirmButtonText: '重新提取', cancelButtonText: '以后再说', type: 'info' })
      } catch {
        return
      }
      await onRecheck({ digest: true, review: false })
    }
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
    factsKey.value++ // 账本已回滚该章的记录
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
          if (rest.kind !== 'polish') factsKey.value++ // 章节完成 / 重新提取后账本可能变了
          if (rest.status === 'failed' && rest.kind === 'recheck') {
            ElMessage.error({ message: `第${rest.chapterIndex}章处理失败：${rest.error}`, duration: 6000 })
          } else if (rest.status === 'succeeded' && rest.kind === 'recheck') {
            ElMessage.success(`第${rest.chapterIndex}章${rest.phase === 'review' ? '一致性检查' : '事实提取'}完成`)
          } else if (rest.status === 'succeeded' && rest.kind === 'polish') {
            ElMessage.success(`第${rest.chapterIndex}章润色完成`)
          } else if (rest.status === 'succeeded') {
            ElMessage.success(`第${rest.chapterIndex}章完成${rest.phase === 'polish' ? '（已润色）' : ''}`)
            form.title = ''
            form.goal = ''
          }
          await loadNovel()
          if (rest.status === 'succeeded' && rest.kind === 'chapter') fillFromOutline() // 有大纲时自动填入下一章
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

/** 自动规划「写进工作区」的设定部分：写进设定编辑器（设定页不是懒加载，编辑器总在）并保存 */
async function applyPlanSettings(items) {
  if (!editorRef.value) throw new Error('设定编辑器还没加载好，稍后再试')
  const r = editorRef.value.applyPlan(items)
  settingsDirty.value = true
  await saveSettings(true)
  return r
}

/** 写入后：大纲 / 书名 / 账本都变了 */
async function onPlanApplied() {
  await loadNovel()
  factsKey.value++
  // 写设定时 spec 已经先保存了（framed 那时就变了），所以按「是不是还在规划中」判断
  if (planning.value && framed.value) {
    planning.value = false   // 第一次写进框架：自动规划消失，其他页出现，带作者去设定页看看
    tab.value = 'settings'
    ElMessage.success('框架已写进工作区，设定 / AI 构思 / 写作等页面已出现；设定页里每一项都能继续改')
  }
}

/** 灵感墙「写进工作区」：设定元素 → 设定页按素材应用；构思方向 → AI 构思页的构思方向框（sessionStorage 交接，读完即删） */
async function applyInspire() {
  let payload = null
  try {
    payload = JSON.parse(sessionStorage.getItem(INSPIRE_KEY) || 'null')
  } catch {
    return
  }
  if (!payload || payload.novelId !== novel.value?.id) return
  try {
    sessionStorage.removeItem(INSPIRE_KEY)
  } catch {
    // 删不掉也只是下次再提示一次
  }
  if (Date.now() - (payload.at || 0) > 10 * 60 * 1000) return
  tab.value = payload.to === 'hint' ? 'ideas' : 'settings'
  // AI 构思页是懒加载的：等它渲染出来再填
  for (let i = 0; i < 20 && !(payload.to === 'hint' ? ideaRef.value : editorRef.value); i++) {
    await nextTick()
    await new Promise((r) => setTimeout(r, 50))
  }
  if (payload.to === 'hint') {
    ideaRef.value?.setHint(payload.hint)
    ElMessage.success('已把灵感墙的思路填进「构思方向」')
  } else if (editorRef.value) {
    const list = (payload.elements || []).map((e) => ({
      id: null, category: e.category, subtype: '', title: e.name, attributes: {}, tags: [], detail: '',
      summary: [e.desc, e.change ? `（相对原素材的改动：${e.change}）` : ''].filter(Boolean).join('')
    }))
    await editorRef.value.applyExternal(list)
    settingsDirty.value = true
    ElMessage.info('元素已加进设定，确认后记得「保存设定」')
  }
}

watch(() => route.params.id, (id) => id && route.name === 'novelWorkspace' && loadNovel().then(applyInspire).then(schedule))
// 新建工作区时填了一句构思（?plan=…）：直接打开自动规划
watch(() => route.query.plan, (p) => { if (p) tab.value = 'plan' }, { immediate: true })
onActivated(() => loadNovel().then(applyInspire).then(schedule))
onDeactivated(() => clearTimeout(timer))

/* ---------------- 书房布局：右侧图标栏 / 左栏 / 顶栏 / 状态栏 ---------------- */

/** 左栏标题 + 一句说明；empty = 小节目录为空时的提示 */
const SECTIONS = {
  plan: { label: '自动规划', sub: '一句构思 → 设定 → 全书骨架' },
  settings: { label: '设定', sub: '只有填过 / 选过的内容才会写进提示词' },
  ideas: { label: 'AI 构思', sub: '书名、大纲、章节方案、后续走向', empty: '还没有构思结果' },
  write: { label: '写作', sub: '写下一章，或打开已写的章节' },
  facts: { label: '故事账本', sub: '伏笔 / 角色状态 / 时间线', empty: '账本还是空的' },
  worldbook: { label: '世界书', sub: 'AI 写作时看到的人物局面和设定', empty: '世界书还是空的' }
}

// 图标栏：分区 + 角标（写作 = 未读的一致性问题，账本 = 未回收伏笔，设定 = 未保存）
const navTabs = computed(() => {
  if (!novel.value) return []
  if (planning.value) return [{ name: 'plan', label: '自动规划', icon: 'Guide' }]
  const issues = (novel.value.chapters || []).reduce((n, c) => n + (c.reviewIssues || 0), 0)
  return [
    { name: 'settings', label: '设定', icon: 'Tickets', dot: settingsDirty.value },
    { name: 'ideas', label: 'AI 构思', icon: 'MagicStick' },
    { name: 'write', label: '写作', icon: 'EditPen', badge: issues },
    { name: 'facts', label: '故事账本', icon: 'Notebook', badge: openForeshadows.value },
    { name: 'worldbook', label: '世界书', icon: 'Collection' }
  ]
})

// 左栏：AI 构思 / 账本 / 世界书的小节目录在各自内容里找 [data-anchor]
const centerEl = ref()
const planRef = ref()
const ideasBox = ref()
const factsBox = ref()
const worldBox = ref()
const anchorRoot = computed(() => ({ ideas: ideasBox.value, facts: factsBox.value, worldbook: worldBox.value })[tab.value] || null)
// 换分区回到顶部（各分区内容长短不一，停在上一个分区的滚动位置没有意义）
watch(tab, () => nextTick(() => centerEl.value?.scrollTo({ top: 0 })))

const LEFT_KEY = 'nan_novel.study.leftFolded'
const leftFolded = ref(false)
try {
  leftFolded.value = localStorage.getItem(LEFT_KEY) === '1'
} catch {
  // 读不到就默认展开
}
function toggleLeft() {
  leftFolded.value = !leftFolded.value
  try {
    localStorage.setItem(LEFT_KEY, leftFolded.value ? '1' : '0')
  } catch {
    // 存不了只是下次不记得
  }
}

// 顶栏：作品定位短标签、字数
const positionChips = computed(() => {
  const c = novel.value?.bookConfig
  if (!c) return []
  return [c.platform, c.genre, c.audience, ...(c.tags || [])].filter(Boolean)
})
const totalWords = computed(() => (novel.value?.chapters || []).reduce((n, c) => n + (c.chars || 0), 0))
const chapterWords = computed(() => {
  if (tab.value !== 'write') return null
  if (view.value === 'new') return busy.value && job.value?.kind === 'chapter' ? liveChapter.value?.text?.length || 0 : null
  return viewChapter.value?.text?.length ?? null
})

// 模型标签 / 状态栏：ok 可以生成，busy 加载中，off 不可用
const modelMismatch = computed(() => isLocal.value && inferState.value?.status === 'loaded' && !modelReady.value)
const modelState = computed(() => {
  if (canGenerate.value) return 'ok'
  if (isLocal.value && inferState.value?.status === 'loading') return 'busy'
  return 'off'
})
const modelChipText = computed(() => {
  const m = novel.value?.model
  if (!m) return ''
  if (m.source === 'api') return `大模型 · ${apiModel.value?.model || '未配置'}`
  if (m.source === 'gguf') return `GGUF · ${llama.value?.name || '未启动'}`
  const a = adapters.value.find((x) => x.id === m.adapterId)
  return `本地 · ${modelName.value || '未选择'}${a ? ` + ${a.name}` : ''}`
})
const modelStateText = computed(() => {
  if (isApi.value) return apiModel.value ? `大模型可用：${apiModel.value.name} · ${apiModel.value.model}` : '没有可用的大模型'
  if (isGguf.value) return llama.value ? `llama.cpp 运行中：${llama.value.name}` : 'llama.cpp 未启动'
  if (modelReady.value) return `本地模型已加载：${modelChipText.value.replace(/^本地 · /, '')}`
  return inferState.value?.status === 'loading' ? '本地模型加载中…' : modelMismatch.value ? '已加载的模型与本工作区不一致' : '本地模型未加载'
})

/** 状态栏「查看」：回到正在跑的任务 */
function goJob() {
  tab.value = 'write'
  const j = job.value
  if (!j) return
  if (j.kind === 'chapter') view.value = 'new'
  else if (j.chapterIndex) openChapter(j.chapterIndex)
}

</script>

<style scoped>

/* ================= 书房布局（背景水墨 / 毛玻璃变量在 styles/ink-theme.css） ================= */
.study {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.study-alerts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 16px 0;
}
.study-body {
  flex: 1;
  min-height: 0;
  display: flex;
}

/* 左栏 */
.study-left {
  position: relative;
  width: 248px;
  flex: 0 0 248px;
  background: var(--ws-glass);
  border-right: 1px solid var(--ws-line);
  backdrop-filter: blur(6px);
  transition: width 0.2s, flex-basis 0.2s;
}
.study-left.is-folded {
  width: 0;
  flex-basis: 0;
  border-right-color: transparent;
}
.left-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.study-left.is-folded .left-inner {
  visibility: hidden;
}
.left-head {
  flex: 0 0 auto;
  padding: 16px 16px 10px;
  border-bottom: 1px dashed var(--ws-line);
}
.left-title {
  font-family: var(--ws-font-title);
  font-size: 18px;
  color: var(--ws-ink);
}
.left-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ws-sub);
}
.left-scroll {
  flex: 1;
  min-height: 0;
}
.left-scroll :deep(.el-scrollbar__view) {
  padding: 10px 8px 16px;
}
.left-tip {
  margin: 12px 10px 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ws-sub);
}
/* 左栏右缘的收起把手（参考 EasyWriting 书房） */
.fold-handle {
  position: absolute;
  top: 50%;
  right: -13px;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 13px;
  height: 40px;
  padding: 0;
  color: var(--ws-sub);
  background: var(--ws-card);
  border: 1px solid var(--ws-line);
  border-left: none;
  border-radius: 0 6px 6px 0;
  cursor: pointer;
  transform: translateY(-50%);
}
.fold-handle:hover {
  color: var(--ws-accent);
}

/* 自动规划的竖排步骤 */
.step-item.is-busy {
  cursor: progress;
}
.step-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 12px;
  font-weight: 400;
  color: var(--ws-sub);
  border: 1px solid var(--el-border-color-darker);
  border-radius: 50%;
}
.step-item.is-active .step-no {
  color: var(--el-color-white);
  background: var(--ws-accent);
  border-color: var(--ws-accent);
}
.step-item.is-done .step-no {
  color: var(--el-color-success);
  border-color: var(--el-color-success-light-5);
}

/* 中间栏：左边内容（只有它滚动，内容放在纸色卡片里）+ 右边素材库（设定页，自己滚动） */
.study-center {
  flex: 1;
  min-width: 0;
  display: flex;
}
.center-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 18px 24px 28px;
}
.study-card {
  padding: 18px 20px;
  background: var(--ws-card);
  border: 1px solid var(--ws-line);
  border-radius: var(--ws-radius);
  box-shadow: 0 1px 3px rgba(60, 40, 20, 0.04);
}
.ws-tabs :deep(.el-tabs__content) {
  overflow: visible;
}

/* 顶栏的模型标签 + 弹出的设置 */
.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 300px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--ws-side-text);
  background: var(--ws-card);
  border: 1px solid var(--ws-line);
  border-radius: 14px;
  cursor: pointer;
}
.model-chip:hover {
  color: var(--ws-ink);
  border-color: var(--el-color-primary-light-7);
}
.model-chip-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.state-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
}
.state-dot.is-ok {
  background: var(--el-color-success);
}
.state-dot.is-busy {
  background: var(--el-color-warning);
}
.model-pop .pop-title {
  margin-bottom: 10px;
  font-family: var(--ws-font-title);
  font-size: 15px;
}
.pop-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
}
.pop-label {
  width: 72px;
  flex-shrink: 0;
  color: var(--ws-sub);
}
.pop-value {
  color: var(--ws-ink);
}
.pop-note {
  margin: -4px 0 10px 80px;
  line-height: 1.5;
}

/* 底部状态栏 */
.study-status {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 30px;
  flex: 0 0 30px;
  padding: 0 16px;
  font-size: 12px;
  color: var(--ws-sub);
  background: var(--ws-glass);
  border-top: 1px solid var(--ws-line);
  backdrop-filter: blur(6px);
  white-space: nowrap;
  overflow: hidden;
}
.status-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.status-item.is-job {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--ws-accent);
}
.status-item.is-dirty {
  color: var(--el-color-warning);
}
.status-spacer {
  flex: 1;
}

/* 写作：左栏章节目录 */
.new-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.chapter-count {
  margin: 10px 10px 4px;
  font-size: 12px;
  color: var(--ws-sub);
}
.chapter-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.arc-text {
  line-height: 1.6;
}

@media (max-width: 1200px) {
  .study-left:not(.is-folded) {
    width: 210px;
    flex-basis: 210px;
  }
  .center-main {
    padding: 14px 16px 24px;
  }
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
.frame-tip { margin-bottom: 10px; }
/* 分页头在右侧图标栏；规划中只给「自动规划」，其他面板留着不卸载（写进工作区要用设定编辑器） */
.ws-tabs > :deep(.el-tabs__header) { display: none; }
.dirty-dot {
  margin-left: 4px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.hint {
  margin-left: 10px;
}
.col-title {
  margin: 8px 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.chapter-item {
  padding: 8px 10px;
  margin-bottom: 4px;
  font-size: 13px;
  border-radius: 6px;
  cursor: pointer;
}
.chapter-item:hover {
  background: var(--ws-side-hover);
}
.chapter-item.is-active {
  background: var(--ws-side-active-bg);
  color: var(--ws-accent);
}
.chapter-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.chapter-tags {
  display: inline-flex;
  flex-shrink: 0;
  gap: 4px;
}
.facts-badge {
  margin-left: 4px;
}
.quote-mark {
  padding: 0 2px;
  background: #fde2e2;
  border-radius: 2px;
}
.totals {
  margin-top: 14px;
  padding-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  border-top: 1px solid var(--el-border-color-lighter);
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
  color: var(--el-text-color-primary);
}
.goal {
  margin-top: 6px;
}
.summary {
  margin-top: 10px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.7;
  background: var(--el-color-primary-light-9);
  border-left: 3px solid var(--el-color-primary-light-5);
}
.chapter-text {
  max-height: 60vh;
  margin: 12px 0 0;
  padding: 14px 16px;
  overflow: auto;
  font-family: var(--ws-font-prose);
  font-size: 16px;
  line-height: 1.95;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--ws-card);
  border: 1px solid var(--ws-line);
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
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
}
</style>
