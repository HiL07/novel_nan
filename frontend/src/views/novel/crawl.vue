<template>
  <div class="crawl-page">
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">小说抓取</span>
          <div class="header-ops">
            <el-radio-group v-model="mode" size="small" @change="onModeChange">
              <el-radio-button value="book">单本（目录页）</el-radio-button>
              <el-radio-button value="site">全自动（按 AI 解析的站点规律）</el-radio-button>
            </el-radio-group>
            <el-button @click="router.push('/file/manage')">文件管理</el-button>
          </div>
        </div>
      </template>

      <el-alert type="info" :closable="false" show-icon class="tip" :title="tipText" />

      <el-form label-width="104px" @submit.prevent>
        <el-form-item v-if="mode === 'book'" label="目录页地址">
          <div class="url-row">
            <el-autocomplete
              v-model="form.url"
              class="url-input"
              :fetch-suggestions="suggestUrls"
              placeholder="https://example.com/book/123/"
              clearable
              @keyup.enter="doPreview"
            >
              <template #default="{ item }">
                <div class="url-option">
                  <span>{{ item.label }}</span>
                  <span class="meta">{{ item.value }}</span>
                </div>
              </template>
            </el-autocomplete>
            <el-button type="primary" :loading="previewing" :disabled="!form.url" @click="doPreview">
              解析目录
            </el-button>
            <el-badge :value="pendingRules.length" :hidden="!pendingRules.length" class="ai-entry">
              <el-button type="success" plain :icon="MagicStick" @click="openAiDialog(pendingRules.length && !aiRunning ? 'rules' : 'analyze')">
                {{ aiRunning ? `AI 解析中 ${aiJob.attempts?.length || 0}/${aiJob.maxAttempts}` : 'AI 解析' }}
              </el-button>
            </el-badge>
            <el-button :icon="Collection" @click="openSavedDialog">地址管理<span v-if="savedUrls.length" class="count">（{{ savedUrls.length }}）</span></el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="mode === 'book'" label="抓取规则">
          <el-select v-model="form.preset" style="width: 260px">
            <el-option label="按域名自动选择" value="" />
            <el-option-group v-if="confirmedRules.length" label="AI 解析规则（已确认）">
              <el-option
                v-for="r in confirmedRules"
                :key="r.id"
                :label="`${r.siteName || r.host}（AI 解析）`"
                :value="`learned:${r.id}`"
              />
            </el-option-group>
            <el-option-group v-if="pendingRules.length" label="AI 解析规则（待确认，只在手动选择时使用）">
              <el-option
                v-for="r in pendingRules"
                :key="r.id"
                :label="`${r.siteName || r.host}（待确认）`"
                :value="`learned:${r.id}`"
              />
            </el-option-group>
            <el-option-group label="内置规则">
              <el-option v-for="p in presets" :key="p.key" :label="p.name" :value="p.key" />
            </el-option-group>
          </el-select>
          <span class="hint">{{ presetHint }}</span>
        </el-form-item>

        <el-form-item v-else label="站点">
          <el-badge :value="pendingRules.length" :hidden="!pendingRules.length" class="ai-entry">
            <el-button type="success" plain :icon="MagicStick" @click="openAiDialog(pendingRules.length && !aiRunning ? 'rules' : 'analyze')">
              {{ aiRunning ? `AI 解析中 ${aiJob.attempts?.length || 0}/${aiJob.maxAttempts}` : 'AI 解析新站点' }}
            </el-button>
          </el-badge>
          <el-button :icon="Collection" class="ml12" @click="openSavedDialog">地址管理<span v-if="savedUrls.length" class="count">（{{ savedUrls.length }}）</span></el-button>
        </el-form-item>

        <el-collapse v-model="advancedOpen" class="advanced">
          <el-collapse-item :title="mode === 'book' ? '高级选项（自定义 XPath / 限速 / robots）' : '高级选项（限速 / robots）'" name="adv">
            <el-form-item label="请求间隔">
              <el-input-number v-model="form.delayMs" :min="300" :max="30000" :step="500" />
              <span class="hint">毫秒，两次请求之间至少间隔这么久</span>
            </el-form-item>
            <el-form-item label="robots.txt">
              <el-switch v-model="form.respectRobots" active-text="遵守" />
            </el-form-item>
            <template v-if="mode === 'book'">
            <p class="hint block">
              以下留空 = 使用所选规则的值（灰色占位符），都为空则自动识别。章节链接 XPath 选中 &lt;a&gt; 元素，正文 XPath 选中正文容器。
            </p>
            <el-form-item v-for="f in RULE_FIELDS" :key="f.key" :label="f.label">
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
            </template>
          </el-collapse-item>
        </el-collapse>
      </el-form>

      <!-- AI 解析状态（详情在「AI 解析」弹窗里） -->
      <div v-if="aiJob" class="ai-strip">
        <el-tag :type="AI_STATUS[aiJob.status]?.type" size="small">AI 解析 · {{ AI_STATUS[aiJob.status]?.label || aiJob.status }}</el-tag>
        <span class="ai-strip-msg">{{ aiJob.error || aiJob.message }}</span>
        <TokenUsageBar :usage="aiJob.usage" :live="aiRunning" class="ai-strip-usage" />
        <el-button link type="primary" @click="openAiDialog('analyze')">查看过程</el-button>
        <el-button v-if="!aiRunning" link @click="clearAiJob">收起</el-button>
      </div>

      <!-- 单本：目录预览 -->
      <div v-if="mode === 'book' && preview" class="preview">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="书名">{{ preview.bookName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="作者">{{ preview.author || '-' }}</el-descriptions-item>
          <el-descriptions-item label="章节数">{{ preview.chapterCount }}（目录 {{ preview.tocPages }} 页）</el-descriptions-item>
          <el-descriptions-item label="使用规则">{{ ruleLabel(preview) }}</el-descriptions-item>
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

      <!-- 全自动：按 AI 解析的规律测试 → 决定 → 筛选书目并抓取 -->
      <AutoCrawlPanel
        v-if="mode === 'site'"
        :rules="usableRules"
        :prefer-rule-id="autoRuleId"
        :delay-ms="form.delayMs"
        :respect-robots="form.respectRobots"
        @submitted="onAutoSubmitted"
        @open-ai="openAiDialog('analyze')"
      />
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
            <div>{{ row.bookName || (row.mode === 'site' ? '（全自动）' : '（解析中）') }}<span v-if="row.author" class="meta"> · {{ row.author }}</span></div>
            <div class="meta">{{ row.url }}</div>
          </template>
        </el-table-column>
        <el-table-column label="模式" width="76">
          <template #default="{ row }">
            <el-tag size="small" :type="row.mode === 'site' ? 'warning' : 'info'">
              {{ row.mode === 'site' ? '全自动' : '单本' }}
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
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button v-if="isActive(row)" link type="danger" @click="doCancel(row)">取消</el-button>
            <template v-else>
              <el-button v-if="row.mode === 'site'" link type="primary" @click="openBooks(row)">书籍明细</el-button>
              <el-button v-else-if="row.fileId" link type="primary" @click="openExtract(row)">小说提取</el-button>
              <el-button v-if="canResume(row)" link type="warning" @click="openResume(row)">继续抓取</el-button>
              <el-button link @click="doRetry(row)">从头重抓</el-button>
              <el-button link @click="reuseOptions(row)">改参数</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 整站任务：逐本明细 -->
    <el-dialog v-model="booksDlg.visible" title="全自动任务 · 书籍明细" width="820px">
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

    <!-- 断点续抓 -->
    <el-dialog v-model="resumeDlg.visible" title="从断点继续抓取" width="560px">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="任务">{{ resumeDlg.task?.bookName || resumeDlg.task?.url }}</el-descriptions-item>
        <el-descriptions-item label="当前地址">{{ resumeDlg.task?.url }}</el-descriptions-item>
        <el-descriptions-item label="已保存进度">
          <span v-if="resumeDlg.loading">查询中…</span>
          <span v-else-if="!resumeDlg.info">（AI 服务未启动，暂时查不到断点；继续抓取时会自动使用）</span>
          <template v-else-if="resumeDlg.task?.mode === 'site'">
            已完成 {{ resumeDlg.task.bookDone || 0 }}/{{ resumeDlg.task.bookTotal || 0 }} 本；
            未完成的 {{ resumeDlg.info.booksPending }} 本中 {{ resumeDlg.info.booksWithCheckpoint }} 本有断点，
            共已保存 {{ resumeDlg.info.chapterSaved }} 章
          </template>
          <template v-else-if="resumeDlg.info.chapterTotal">
            已保存 {{ resumeDlg.info.chapterSaved }}/{{ resumeDlg.info.chapterTotal }} 章（这些章节不会重抓）
          </template>
          <span v-else>还没有断点（目录尚未解析成功），将从目录页开始</span>
        </el-descriptions-item>
      </el-descriptions>
      <el-form label-width="112px" class="resume-form" @submit.prevent>
        <el-form-item label="站点换地址了？">
          <el-input
            v-model="resumeDlg.newOrigin"
            placeholder="可空。如 https://www.new-domain.com（协议 + 域名 / IP[:端口]）"
            clearable
          />
          <div class="meta">
            站点换了域名或 IP、但页面路径不变时填写：任务地址和断点里的章节地址会整体换到新站点。
            断点里存有完整章节清单，即使目录页已经打不开，也能把剩下的章节抓完。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resumeDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="resumeDlg.submitting" @click="doResume">继续抓取</el-button>
      </template>
    </el-dialog>

    <!-- AI 解析：配置 + 过程 / 已学规则 -->
    <el-dialog v-model="aiDlg.visible" title="AI 解析" width="min(1240px, 94vw)" top="4vh">
      <el-tabs v-model="aiDlg.tab">
        <el-tab-pane label="AI 解析地址" name="analyze">
          <el-form label-width="96px" @submit.prevent>
            <el-form-item label="入口地址">
              <div class="url-row">
                <el-autocomplete
                  v-model="ai.url"
                  class="url-input"
                  :fetch-suggestions="suggestUrls"
                  placeholder="一本书的详情页或目录页，如 https://example.com/book/123/"
                  clearable
                  @keyup.enter="doAiAnalyze"
                >
                  <template #default="{ item }">
                    <div class="url-option">
                      <span>{{ item.label }}</span>
                      <span class="meta">{{ item.value }}</span>
                    </div>
                  </template>
                </el-autocomplete>
                <el-button v-if="aiRunning" type="danger" plain @click="doAiCancel">取消</el-button>
                <el-button v-else type="success" :icon="MagicStick" :disabled="!ai.url.trim()" @click="doAiAnalyze">开始解析</el-button>
              </div>
            </el-form-item>
            <el-form-item label="最多尝试">
              <el-input-number v-model="ai.maxAttempts" :min="1" :max="10" size="small" />
              <span class="unit">次</span>
              <el-switch v-model="ai.useKnown" active-text="先试该站点已学到的规则" class="switch" />
              <el-switch v-model="ai.autoStart" active-text="成功后直接抓全书" class="switch" />
            </el-form-item>
            <el-form-item label="补充说明">
              <el-input v-model="ai.hint" placeholder="可空，如：正文在 id=content 的 div 里；目录在「查看全部章节」页" clearable />
            </el-form-item>
            <div class="meta block ai-desc">
              先试已学到的 / 内置规则，失败再由大模型看页面结构写 XPath，每次都真实试抓目录 + 两章正文；
              成功后总结地址规律并按域名存入「已学规则」，以后同站点「按域名自动选择」会自动套用。
              请求间隔与 robots 沿用主页面「高级选项」。需要「模型配置」里有已验证的大模型。
            </div>
          </el-form>
          <div v-if="aiJob" class="preview">
            <div class="sample-title">
              {{ aiJob.url }}
              <el-tag :type="AI_STATUS[aiJob.status]?.type" size="small">{{ AI_STATUS[aiJob.status]?.label || aiJob.status }}</el-tag>
              <el-button v-if="aiJob.status === 'succeeded' && preview" size="small" type="primary" @click="aiDlg.visible = false">
                去确认目录并抓取
              </el-button>
            </div>
            <el-progress
              :percentage="aiJob.progress || 0"
              :status="aiJob.status === 'succeeded' ? 'success' : ['failed', 'cancelled'].includes(aiJob.status) ? 'exception' : ''"
            />
            <div class="meta">{{ aiJob.error || aiJob.message }}</div>
            <TokenUsageBar :usage="aiJob.usage" :live="aiRunning" />
            <AttemptTable v-if="aiJob.attempts?.length" :attempts="aiJob.attempts" class="attempts" />
            <div v-if="aiJob.savedRuleId && ruleById(aiJob.savedRuleId) && !aiRunning" class="ai-result">
              <el-button size="small" type="primary" plain @click="openRuleDetail(ruleById(aiJob.savedRuleId))">
                {{ aiJob.status === 'failed' ? '已记入解析管理（失败），查看详情' : '在解析管理中查看详情' }}
              </el-button>
            </div>
            <el-descriptions v-if="aiJob.result" :column="1" border size="small" class="ai-result">
              <el-descriptions-item label="站点">
                {{ aiJob.result.siteName || aiJob.result.host }}
                <template v-if="aiJob.savedRuleId">
                  <el-tag v-if="ruleById(aiJob.savedRuleId)?.status === 'CONFIRMED'" size="small" type="success" class="ml6">
                    已确认，同站点自动套用
                  </el-tag>
                  <template v-else-if="ruleById(aiJob.savedRuleId)">
                    <el-tag size="small" type="warning" class="ml6">已存为待确认</el-tag>
                    <el-button size="small" type="success" link class="ml6" @click="confirmRule(ruleById(aiJob.savedRuleId))">确认</el-button>
                    <el-button size="small" type="danger" link @click="rejectRule(ruleById(aiJob.savedRuleId))">不确认</el-button>
                  </template>
                </template>
              </el-descriptions-item>
              <el-descriptions-item label="总结">{{ aiJob.result.summary }}</el-descriptions-item>
              <el-descriptions-item label="规则">
                <span class="rule-line">{{ ruleText(aiJob.result.rule) || '内置规则 / 自动识别即可' }}</span>
              </el-descriptions-item>
            </el-descriptions>
            <div v-if="aiJob.result" class="ai-result">
              <div class="sample-title">站点结构与跳转规律</div>
              <SiteMapView :site-map="aiJob.result.siteMap" :home-url="aiJob.result.homeUrl" />
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane name="rules">
          <template #label>
            解析管理
            <el-badge v-if="pendingRules.length" :value="pendingRules.length" class="tab-badge" />
          </template>
          <div class="rules-bar">
            <el-radio-group v-model="rulesFilter">
              <el-radio-button value="PENDING">待确认 {{ pendingRules.length }}</el-radio-button>
              <el-radio-button value="CONFIRMED">已确认 {{ confirmedRules.length }}</el-radio-button>
              <el-radio-button value="FAILED">解析失败 {{ failedRules.length }}</el-radio-button>
              <el-radio-button value="">全部 {{ learnedRules.length }}</el-radio-button>
            </el-radio-group>
            <div class="bar-left">
              <el-input v-model="rulesQuery" class="rules-search" placeholder="搜索站点 / 域名 / 书名" clearable :prefix-icon="Search" />
              <el-button :icon="Refresh" @click="loadRules">刷新</el-button>
            </div>
          </div>
          <p class="meta rules-tip">
            点击任意一行查看这次解析的完整过程：每次尝试是成功还是失败、失败原因、站点结构、规则和抓取样本。
            成功的先进入「待确认」，确认后该站点「按域名自动选择」时自动套用；失败的只作记录，可重新解析。
          </p>
          <el-empty
            v-if="!shownRules.length"
            :description="rulesQuery ? '没有匹配的记录' : rulesFilter === 'PENDING' ? '没有待确认的解析' : rulesFilter === 'FAILED' ? '没有解析失败的记录' : '还没有解析记录：在「AI 解析地址」页输入一本书的地址并开始解析'"
          />
          <el-table
            v-else
            :data="shownRules"
            max-height="560"
            class="rules-table"
            :row-class-name="({ row }) => `rule-row rule-${row.status}`"
            @row-click="openRuleDetail"
          >
            <el-table-column label="状态" width="92">
              <template #default="{ row }">
                <el-tag :type="RULE_STATUS[row.status]?.type" effect="dark">{{ RULE_STATUS[row.status]?.label || row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="站点 / 解析的书" min-width="250">
              <template #default="{ row }">
                <div class="rule-site">{{ row.siteName || row.host }}</div>
                <div class="meta ellipsis">{{ row.bookName ? `《${row.bookName}》` : '' }}{{ row.sampleUrl }}</div>
              </template>
            </el-table-column>
            <el-table-column label="解析结果" min-width="300">
              <template #default="{ row }">
                <div v-if="row.status === 'FAILED'" class="err clamp2">{{ row.error || '解析失败' }}</div>
                <template v-else>
                  <div>
                    第 {{ row.attempts }} 次抓通（{{ AI_STRATEGY[row.strategy] || row.strategy }}）· 目录 {{ row.chapterCount || 0 }} 章
                  </div>
                  <div class="meta">
                    站点规律
                    <el-tag v-if="row.siteMap?.items" size="small" :type="row.siteMap.failed ? 'warning' : 'success'">
                      掌握 {{ row.siteMap.mastered }}/{{ row.siteMap.total }} 项
                    </el-tag>
                    <span v-else>未验证</span>
                  </div>
                </template>
              </template>
            </el-table-column>
            <el-table-column label="每次尝试" width="170">
              <template #default="{ row }">
                <div v-if="row.attemptLog?.attempts?.length" class="attempt-dots">
                  <el-tooltip
                    v-for="t in row.attemptLog.attempts"
                    :key="t.index"
                    :content="`第 ${t.index} 次 · ${AI_STRATEGY[t.strategy] || t.strategy} · ${t.ok ? '成功' : '失败：' + (t.error || '')}`"
                    placement="top"
                  >
                    <span class="dot" :class="t.ok ? 'dot-ok' : 'dot-fail'">{{ t.ok ? '✓' : '✗' }}</span>
                  </el-tooltip>
                </div>
                <span v-else class="meta">{{ row.attempts || 0 }} 次（旧记录）</span>
              </template>
            </el-table-column>
            <el-table-column prop="updateTime" label="时间" width="160" />
            <el-table-column label="操作" width="210" fixed="right">
              <template #default="{ row }">
                <div @click.stop>
                  <el-button link type="primary" @click="openRuleDetail(row)">详情</el-button>
                  <template v-if="row.status === 'CONFIRMED'">
                    <el-button link @click="useRuleForSite(row)">全自动抓取</el-button>
                    <el-button link type="danger" @click="removeRule(row)">删除</el-button>
                  </template>
                  <template v-else-if="row.status === 'PENDING'">
                    <el-button link type="success" @click="confirmRule(row)">确认</el-button>
                    <el-button link type="danger" @click="rejectRule(row)">不确认</el-button>
                  </template>
                  <template v-else>
                    <el-button link type="warning" @click="reanalyze(row)">重新解析</el-button>
                    <el-button link type="danger" @click="rejectRule(row)">删除</el-button>
                  </template>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <!-- 解析管理：一次解析的详情（每次尝试成败 / 站点结构 / 规则 / 样本） -->
    <RuleDetailDialog v-model="ruleDlg.visible" :rule="ruleDlg.rule" @action="onRuleAction" />

    <!-- 地址管理：收藏的可抓取网址（增 / 改 / 删 / 使用 / AI 解析） -->
    <el-dialog v-model="savedDlg.visible" title="地址管理" width="900px">
      <div class="dialog-bar">
        <div class="bar-left">
          <el-button type="primary" size="small" :icon="Plus" @click="startAddSaved">添加地址</el-button>
          <el-input v-model="savedDlg.query" size="small" class="saved-search" placeholder="搜索描述 / 地址" clearable />
        </div>
        <el-badge :value="pendingRules.length" :hidden="!pendingRules.length">
          <el-button size="small" :icon="MagicStick" @click="openAiDialog('rules')">AI 解析管理</el-button>
        </el-badge>
      </div>

      <el-form v-if="savedDlg.editing" label-width="56px" class="saved-form" @submit.prevent>
        <el-form-item label="地址">
          <el-input v-model="savedDlg.editing.url" placeholder="https://… 书籍详情页 / 目录页 / 站点首页" clearable />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="savedDlg.editing.name" placeholder="这个地址是什么，如：某某小说目录 / 某某书站首页" clearable />
        </el-form-item>
        <el-form-item>
          <el-radio-group v-model="savedDlg.editing.mode" size="small">
            <el-radio-button value="book">单本</el-radio-button>
            <el-radio-button value="site">整站（全自动）</el-radio-button>
          </el-radio-group>
          <el-button type="primary" size="small" class="ml12" :loading="savedDlg.saving" :disabled="!savedDlg.editing.url.trim()" @click="submitSaved">
            {{ savedDlg.editing.id ? '保存修改' : '添加' }}
          </el-button>
          <el-button size="small" @click="savedDlg.editing = null">取消</el-button>
        </el-form-item>
      </el-form>

      <el-empty v-if="!filteredSavedUrls.length" :description="savedUrls.length ? '没有匹配的地址' : '还没有地址：点「添加地址」'" />
      <el-table v-else :data="filteredSavedUrls" size="small" max-height="440">
        <el-table-column label="描述" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag size="small" :type="row.mode === 'site' ? 'warning' : 'info'" class="mr6">{{ row.mode === 'site' ? '整站' : '单本' }}</el-tag>
            {{ row.name || '（未填写）' }}
          </template>
        </el-table-column>
        <el-table-column prop="url" label="地址" min-width="260" show-overflow-tooltip />
        <el-table-column label="使用" width="64">
          <template #default="{ row }">{{ row.useCount || 0 }} 次</template>
        </el-table-column>
        <el-table-column label="操作" width="210">
          <template #default="{ row }">
            <el-button link type="primary" @click="pickSavedUrl(row.id)">使用</el-button>
            <el-button link type="success" @click="aiFromSaved(row)">AI 解析</el-button>
            <el-button link @click="startEditSaved(row)">修改</el-button>
            <el-button link type="danger" @click="removeSavedUrl(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <ExtractOptionsDialog v-model="extractDlg.visible" :file-name="extractDlg.fileName" @confirm="doExtract" />
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onDeactivated, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, MagicStick, Plus, Refresh, Search } from '@element-plus/icons-vue'
import {
  analyzeCrawlUrl,
  cancelCrawl,
  cancelCrawlAiJob,
  confirmCrawlRule,
  deleteCrawlRule,
  deleteSavedUrl,
  getCrawlAiJob,
  getCrawlCheckpoint,
  listCrawlBooks,
  listCrawlPresets,
  listCrawlRules,
  listCrawls,
  listSavedUrls,
  previewCrawl,
  rejectCrawlRule,
  resumeCrawl,
  retryCrawl,
  saveSavedUrl,
  submitCrawl,
  useSavedUrl
} from '@/api/crawl'
import { submitExtract } from '@/api/novel'
import { errorMessage } from '@/api/request'
import ExtractOptionsDialog from '@/components/material/ExtractOptionsDialog.vue'
import TokenUsageBar from '@/components/ai/TokenUsageBar.vue'
import SiteMapView from '@/components/crawl/SiteMapView.vue'
import AutoCrawlPanel from '@/components/crawl/AutoCrawlPanel.vue'
import AttemptTable from '@/components/crawl/AttemptTable.vue'
import RuleDetailDialog from '@/components/crawl/RuleDetailDialog.vue'

const STATUS = {
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '抓取中', type: 'warning' },
  SUCCEEDED: { label: '已完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
  CANCELLED: { label: '已取消', type: 'info' }
}
const AI_STATUS = {
  queued: { label: '排队中', type: 'info' },
  running: { label: '分析中', type: 'warning' },
  succeeded: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' }
}
const AI_STRATEGY = { learned: '已学到的规则', preset: '内置规则', ai: 'AI 写规则' }
const RULE_STATUS = {
  PENDING: { label: '待确认', type: 'warning' },
  CONFIRMED: { label: '已确认', type: 'success' },
  FAILED: { label: '失败', type: 'danger' }
}
const RULE_FIELDS = [
  { key: 'tocLink', label: '目录链接', placeholder: "详情页 → 目录页的 <a>，如 //div[@class='b-oper']/a[@class='reader']" },
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
const advancedOpen = ref([])
const previewing = ref(false)
const preview = ref(null)
// 全自动模式要选中的站点规则（解析管理「全自动抓取」/ 地址管理选整站地址 / 任务「改参数」时指定）
const autoRuleId = ref(null)
const range = reactive({ start: 1, end: 1 })
const submitting = ref(false)
const loading = ref(false)
const tasks = ref([])
const booksDlg = reactive({ visible: false, crawl: null, title: '', books: [], loading: false })
const extractDlg = reactive({ visible: false, fileId: null, fileName: '' })
const resumeDlg = reactive({ visible: false, task: null, info: null, loading: false, newOrigin: '', submitting: false })
const ai = reactive({ url: '', maxAttempts: 5, hint: '', autoStart: false, useKnown: true })
const aiJob = ref(null)
const learnedRules = ref([])
const aiDlg = reactive({ visible: false, tab: 'analyze' })
const rulesFilter = ref('PENDING')
const rulesQuery = ref('')
const ruleDlg = reactive({ visible: false, rule: null })
const savedUrls = ref([])
// editing：null = 不在编辑；{id?, url, name, mode} = 添加 / 修改中
const savedDlg = reactive({ visible: false, query: '', editing: null, saving: false })
let timer = null
let aiTimer = null

// 本机浏览器里记住表单草稿与最近用过的地址（刷新 / 关页面后还在）；已提交任务的地址另存在数据库的任务表里
const DRAFT_KEY = 'nan_novel.crawl.draft'
// 解析目录 / AI 解析的结果：切到别的页面、刷新浏览器后回来还在，直到重新解析或开始抓取
const RESULT_KEY = 'nan_novel.crawl.result'
const RECENT_KEY = 'nan_novel.crawl.recentUrls'
const MAX_RECENT = 30
const recentUrls = ref(readJson(RECENT_KEY, []))

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 隐私模式 / 存储被禁用：不影响使用
  }
}

/** 记住用过的地址（解析时），最近的在前 */
function rememberUrl(url, label) {
  if (!url) return
  const rest = recentUrls.value.filter((r) => r.url !== url)
  const old = recentUrls.value.find((r) => r.url === url)
  recentUrls.value = [{ url, label: label || old?.label || '', mode: mode.value }, ...rest].slice(0, MAX_RECENT)
  writeJson(RECENT_KEY, recentUrls.value)
}

/** 地址框候选：本机最近用过的 + 数据库里所有抓取任务的地址（含失败 / 中断的） */
function suggestUrls(query, cb) {
  const seen = new Set()
  const items = []
  const push = (url, label) => {
    if (!url || seen.has(url)) return
    seen.add(url)
    items.push({ value: url, label })
  }
  savedUrls.value.forEach((u) => push(u.url, `★ ${u.name || '收藏'}`))
  recentUrls.value.forEach((r) => push(r.url, r.label || '最近使用'))
  tasks.value
    .filter((t) => t.mode !== 'site')
    .forEach((t) => push(t.url, `${t.bookName || '任务'} · ${STATUS[t.status]?.label || t.status}`))
  const q = (query || '').trim().toLowerCase()
  cb(q ? items.filter((i) => i.value.toLowerCase().includes(q) || i.label.toLowerCase().includes(q)) : items)
}

function restoreDraft() {
  const d = readJson(DRAFT_KEY, null)
  if (!d) return
  if (d.mode === 'site' || d.mode === 'book') mode.value = d.mode
  if (d.form) {
    const { saveDir, ...rest } = d.form // saveDir：旧版「保存目录」，已改成常用地址
    Object.assign(form, emptyForm(), rest, { rule: { ...emptyForm().rule, ...(d.form.rule || {}) } })
    if (Object.values(form.rule).some(Boolean) || form.removeText) advancedOpen.value = ['adv']
  }
  if (d.ai) Object.assign(ai, d.ai)
}

/** 恢复上次的解析结果（目录预览 / AI 解析过程），进行中的 AI 解析继续轮询 */
function restoreResult() {
  const r = readJson(RESULT_KEY, null)
  if (!r) return
  preview.value = r.preview || null
  if (r.range) Object.assign(range, r.range)
  aiJob.value = r.aiJob || null
  if (aiJob.value && ['queued', 'running'].includes(aiJob.value.status)) scheduleAiPoll()
}

function saveResult() {
  writeJson(RESULT_KEY, {
    preview: preview.value,
    range: { ...range },
    aiJob: aiJob.value
  })
}

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

restoreDraft()
restoreResult()
watch([mode, form, ai], () => writeJson(DRAFT_KEY, { mode: mode.value, form, ai }), { deep: true })
watch([preview, aiJob, () => range.start, () => range.end], saveResult)

const tipText = computed(() =>
  mode.value === 'book'
    ? '填写一本小说的「章节目录页」地址，抓取后合并为一个 txt 存入文件管理，可直接发起小说提取。请只抓取你有权使用的内容，并保持合理的请求间隔。'
    : '全自动爬虫：选一个 AI 解析过的站点 → 按学到的规律测试能否找到多本书、取到目录 / 简介 / 标签 / 正文（书目存本地，不存正文）→ 决定是否使用 → 按书名 / 作者 / 标签 / AI 检索筛选后逐本抓取，每本一个 txt。请只抓取你有权使用的内容，并保持合理的请求间隔。'
)

const currentPreset = computed(() => presets.value.find((p) => p.key === form.preset))
const presetRule = computed(() => currentPreset.value?.rule || {})
const estimate = computed(() => {
  const secs = Math.max(range.end - range.start + 1, 0) * (form.delayMs / 1000)
  return secs < 120 ? `${Math.ceil(secs)} 秒` : `${Math.ceil(secs / 60)} 分钟`
})

function presetName(key) {
  return presets.value.find((p) => p.key === key)?.name || key
}

/** 预览结果用的规则：套用了 AI 学到的规则时标明站点 */
function ruleLabel(data) {
  const lr = data?.learnedRule
  if (lr) return `AI 学到的规则（${lr.siteName || lr.host}）`
  return presetName(data?.preset)
}

function hostOf(url) {
  try {
    return new URL(url.trim()).hostname.toLowerCase()
  } catch {
    return ''
  }
}

/** 与后端 CrawlRuleService.findForUrl 同口径：精确域名，或忽略 www. / m. / wap. 前缀 */
const matchedRule = computed(() => {
  const host = hostOf(form.url)
  if (!host) return null
  const bare = host.replace(/^(www|m|wap)\./, '')
  return (
    confirmedRules.value.find((r) => r.host === host) ||
    confirmedRules.value.find((r) => [bare, `www.${bare}`, `m.${bare}`].includes(r.host)) ||
    null
  )
})

/** 地址所在站点的 AI 解析规则（已确认优先，其次待确认），全自动模式用 */
function ruleForUrl(url) {
  const host = hostOf(url || '')
  if (!host) return null
  const bare = host.replace(/^(www|m|wap)\./, '')
  const hosts = [host, bare, `www.${bare}`, `m.${bare}`]
  const all = [...confirmedRules.value, ...pendingRules.value]
  return all.find((r) => r.host === host) || all.find((r) => hosts.includes(r.host)) || null
}

const presetHint = computed(() => {
  if (form.preset.startsWith('learned:')) {
    const r = learnedRules.value.find((x) => `learned:${x.id}` === form.preset)
    if (r?.status === 'PENDING') return `待确认的 AI 解析规则（试用）：${r.summary || ''}`
    return r?.summary || '使用 AI 解析出的规则'
  }
  if (!form.preset && matchedRule.value) {
    return `该站点有已确认的 AI 解析规则（${matchedRule.value.siteName || matchedRule.value.host}），将自动套用`
  }
  return currentPreset.value?.description || '命中预设域名用对应规则，否则自动识别'
})

function ruleText(rule) {
  return Object.entries(rule || {})
    .filter(([, v]) => v && (!Array.isArray(v) || v.length))
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' | ') : v}`)
    .join('；')
}

/** 表单 → 后端参数（单本）：只带非空的自定义规则字段 */
function buildOptions() {
  const rule = Object.fromEntries(Object.entries(form.rule).filter(([, v]) => v && v.trim()).map(([k, v]) => [k, v.trim()]))
  const removePatterns = form.removeText.split('\n').map((s) => s.trim()).filter(Boolean)
  if (removePatterns.length) rule.removePatterns = removePatterns
  const options = {
    url: form.url.trim(),
    mode: 'book',
    preset: form.preset,
    delayMs: form.delayMs,
    respectRobots: form.respectRobots,
    ...(Object.keys(rule).length ? { rule } : {})
  }
  return options
}

// 切换模式不清空结果：单本的目录预览留在本地，全自动的书目在后端
function onModeChange() {}

/** 全自动：选中的书已提交为抓取任务 */
async function onAutoSubmitted() {
  await loadTasks()
  schedulePoll()
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
  rememberUrl(form.url.trim())
  previewing.value = true
  preview.value = null
  try {
    const res = await previewCrawl(buildOptions())
    if (res.code !== 0) {
      ElMessage.error(res.message || '解析失败')
      return
    }
    preview.value = res.data
    rememberUrl(form.url.trim(), res.data.bookName)
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

// ---------------------------------------------------------------- AI 解析地址

const aiRunning = computed(() => !!aiJob.value && ['queued', 'running'].includes(aiJob.value.status))

/** 打开「AI 解析」弹窗；入口地址为空时带上主页面的地址 */
function openAiDialog(tab) {
  if (!ai.url.trim() && !aiRunning.value) ai.url = form.url.trim()
  savedDlg.visible = false
  if (tab === 'rules' && pendingRules.value.length === 0 && rulesFilter.value === 'PENDING') rulesFilter.value = ''
  aiDlg.tab = tab
  aiDlg.visible = true
  loadRules()
}

async function doAiAnalyze() {
  const url = ai.url.trim()
  if (!url || aiRunning.value) return
  rememberUrl(url)
  try {
    const res = await analyzeCrawlUrl({
      url,
      maxAttempts: ai.maxAttempts,
      delayMs: form.delayMs,
      respectRobots: form.respectRobots,
      hint: ai.hint.trim(),
      useKnown: ai.useKnown
    })
    if (res.code !== 0) {
      ElMessage.error(res.message || 'AI 解析提交失败')
      return
    }
    aiJob.value = res.data
    preview.value = null
    scheduleAiPoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, 'AI 解析提交失败（需要「模型配置」里有已验证的大模型）'))
  }
}

/** AI 解析在后台跑：离开本页也继续轮询（结果存在本地，回来就能看到） */
function scheduleAiPoll() {
  if (aiTimer) clearTimeout(aiTimer)
  aiTimer = setTimeout(pollAi, 2000)
}

async function pollAi() {
  aiTimer = null
  const jobId = aiJob.value?.jobId
  if (!jobId) return
  try {
    const res = await getCrawlAiJob(jobId)
    if (res.code !== 0) {
      aiJob.value = { ...aiJob.value, status: 'failed', error: res.message || '查询失败' }
      return
    }
    aiJob.value = res.data
  } catch (e) {
    if (e?.response?.status === 404) {
      aiJob.value = { ...aiJob.value, status: 'failed', error: 'AI 服务已重启，任务中断，请重新解析' }
      return
    }
    scheduleAiPoll() // 网络抖动 / 服务暂时不可达：继续等
    return
  }
  if (aiRunning.value) {
    scheduleAiPoll()
    return
  }
  if (aiJob.value.status === 'succeeded') await onAiSucceeded()
  else if (aiJob.value.status === 'failed') await loadRules()
}

/** 成功：载入学到的规则与目录预览（可直接「开始抓取」），开启了自动抓取则直接提交 */
async function onAiSucceeded() {
  const r = aiJob.value.result
  await loadRules()
  form.url = r.tocUrl || form.url
  form.preset = aiJob.value.savedRuleId ? `learned:${aiJob.value.savedRuleId}` : ''
  RULE_FIELDS.forEach((f) => (form.rule[f.key] = ''))
  rememberUrl(form.url, r.preview?.bookName)
  if (r.preview) {
    preview.value = { ...r.preview, learnedRule: { host: r.host, siteName: r.siteName } }
    range.start = 1
    range.end = r.preview.chapterCount
  }
  if (ai.autoStart && preview.value) {
    ElMessage.success('AI 解析成功，开始抓取全书')
    aiDlg.visible = false
    await doSubmit()
  } else {
    ElMessage.success('AI 解析成功：规则已存为「待确认」，可先确认目录并抓取，再到「解析管理」确认 / 不确认')
  }
}

async function doAiCancel() {
  try {
    await cancelCrawlAiJob(aiJob.value.jobId)
  } catch (e) {
    ElMessage.error(errorMessage(e, '取消失败'))
  }
}

function clearAiJob() {
  aiJob.value = null
}

// ---------------------------------------------------------------- 学到的规则

async function loadRules() {
  try {
    const res = await listCrawlRules()
    if (res.code === 0) learnedRules.value = res.data || []
  } catch {
    // 后端没起时不影响其它功能
  }
}

const confirmedRules = computed(() => learnedRules.value.filter((r) => r.status === 'CONFIRMED'))
const pendingRules = computed(() => learnedRules.value.filter((r) => r.status === 'PENDING'))
const failedRules = computed(() => learnedRules.value.filter((r) => r.status === 'FAILED'))
// 能当规则用的（规则下拉框 / 全自动）：失败记录没有规则
const usableRules = computed(() => learnedRules.value.filter((r) => r.status !== 'FAILED'))
const shownRules = computed(() => {
  const byStatus = rulesFilter.value ? learnedRules.value.filter((r) => r.status === rulesFilter.value) : learnedRules.value
  const q = rulesQuery.value.trim().toLowerCase()
  if (!q) return byStatus
  return byStatus.filter((r) =>
    [r.siteName, r.host, r.bookName, r.sampleUrl, r.homeUrl].some((v) => (v || '').toLowerCase().includes(q))
  )
})

function openRuleDetail(row) {
  if (!row) return
  ruleDlg.rule = row
  ruleDlg.visible = true
}

/** 详情弹窗里的按钮：与列表一致；改动后刷新，弹窗跟着显示最新状态（删除了就关掉） */
async function onRuleAction(name, row) {
  const handlers = {
    confirm: confirmRule,
    reject: rejectRule,
    remove: removeRule,
    use: useRule,
    auto: useRuleForSite,
    reanalyze
  }
  await handlers[name]?.(row)
  if (['use', 'auto', 'reanalyze'].includes(name)) {
    ruleDlg.visible = false
    return
  }
  const latest = ruleById(row.id)
  if (latest) ruleDlg.rule = latest
  else ruleDlg.visible = false
}

/** 重新解析：入口地址填这条记录解析过的书，回到「AI 解析地址」页 */
function reanalyze(row) {
  if (aiRunning.value) {
    ElMessage.warning('已有 AI 解析在进行中，请等它结束或取消后再试')
  } else {
    ai.url = row.sampleUrl || ''
  }
  aiDlg.tab = 'analyze'
  aiDlg.visible = true
}
const ruleById = (id) => learnedRules.value.find((r) => r.id === id)

async function confirmRule(row) {
  if (!row) return
  const replaced = confirmedRules.value.find((r) => r.host === row.host && r.id !== row.id)
  if (replaced) {
    try {
      await ElMessageBox.confirm(`「${row.host}」已有一条已确认的规则，确认这条会替换它。继续？`, '确认解析规则', { type: 'warning' })
    } catch {
      return
    }
  }
  try {
    const res = await confirmCrawlRule(row.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '确认失败')
      return
    }
    ElMessage.success('已确认：该站点「按域名自动选择」时会自动套用')
    if (replaced && form.preset === `learned:${replaced.id}`) form.preset = `learned:${row.id}`
    await loadRules()
  } catch (e) {
    ElMessage.error(errorMessage(e, '确认失败'))
  }
}

async function rejectRule(row) {
  if (!row) return
  try {
    await ElMessageBox.confirm(
      row.status === 'FAILED'
        ? `删除「${row.siteName || row.host}」这条解析失败的记录？`
        : `不确认「${row.siteName || row.host}」这次的解析？规则会被丢弃（规则文件一并删除）。`,
      row.status === 'FAILED' ? '删除记录' : '不确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const res = await rejectCrawlRule(row.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '操作失败')
      return
    }
    if (form.preset === `learned:${row.id}`) form.preset = ''
    await loadRules()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

/** 用这条规则的站点规律走全自动爬虫：测试 → 决定 → 筛选书目并抓取 */
function useRuleForSite(row) {
  mode.value = 'site'
  autoRuleId.value = row.id
  aiDlg.visible = false
  ElMessage.success('已切到全自动模式：先「开始测试」看看这套规律能否找到多本书')
}

function useRule(row) {
  form.preset = `learned:${row.id}`
  if (!form.url && row.sampleUrl) form.url = row.sampleUrl
  aiDlg.visible = false
}

async function removeRule(row) {
  try {
    await ElMessageBox.confirm(`删除「${row.siteName || row.host}」学到的规则？之后该站点回到内置规则 / 自动识别。`, '删除规则', {
      type: 'warning'
    })
  } catch {
    return
  }
  try {
    const res = await deleteCrawlRule(row.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '删除失败')
      return
    }
    if (form.preset === `learned:${row.id}`) form.preset = ''
    await loadRules()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

// ---------------------------------------------------------------- 常用地址

const filteredSavedUrls = computed(() => {
  const q = savedDlg.query.trim().toLowerCase()
  return q ? savedUrls.value.filter((u) => `${u.name || ''} ${u.url}`.toLowerCase().includes(q)) : savedUrls.value
})

async function loadSavedUrls() {
  try {
    const res = await listSavedUrls()
    if (res.code === 0) savedUrls.value = res.data || []
  } catch {
    // 后端没起时不影响其它功能
  }
}

/** 选中收藏的地址：单本填入地址框；整站切到全自动并选中该站点的 AI 解析规则 */
async function pickSavedUrl(id) {
  const u = savedUrls.value.find((x) => x.id === id)
  if (!u) return
  if (u.mode === 'site') {
    const r = ruleForUrl(u.url)
    if (!r) {
      ElMessage.warning('这个站点还没有 AI 解析出的规律：先用「AI 解析」解析该站一本书的地址')
      return
    }
    mode.value = 'site'
    autoRuleId.value = r.id
  } else {
    mode.value = 'book'
    form.url = u.url
  }
  savedDlg.visible = false
  try {
    await useSavedUrl(u.id)
    await loadSavedUrls()
  } catch {
    // 计数失败不影响使用
  }
}

async function openSavedDialog() {
  savedDlg.visible = true
  savedDlg.editing = null
  await loadSavedUrls()
}

/** 添加：地址默认取主页面当前地址，描述默认取解析出的书名 / 站点名 */
function startAddSaved() {
  const url = form.url.trim()
  const known = savedUrls.value.some((u) => u.url === url)
  const name = mode.value === 'book' ? preview.value?.bookName : 
  savedDlg.editing = { url: known ? '' : url, name: known ? '' : name || '', mode: mode.value }
}

function startEditSaved(row) {
  savedDlg.editing = { id: row.id, url: row.url, name: row.name || '', mode: row.mode || 'book', note: row.note }
}

async function submitSaved() {
  const e = savedDlg.editing
  if (!e?.url.trim()) return
  savedDlg.saving = true
  try {
    const res = await saveSavedUrl({ ...e, url: e.url.trim(), name: (e.name || '').trim() })
    if (res.code !== 0) {
      ElMessage.error(res.message || '保存失败')
      return
    }
    ElMessage.success(e.id ? '已修改' : '已添加')
    savedDlg.editing = null
    await loadSavedUrls()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    savedDlg.saving = false
  }
}

/** 对收藏的地址发起 AI 解析：与主页面「AI 解析」相同（单本模式，弹窗里确认参数后开始） */
function aiFromSaved(row) {
  if (aiRunning.value) {
    ElMessage.warning('已有 AI 解析在进行中，请等它结束或取消后再试')
    openAiDialog('analyze')
    return
  }
  ai.url = row.url
  openAiDialog('analyze')
}

async function removeSavedUrl(row) {
  try {
    await ElMessageBox.confirm(`删除收藏「${row.name || row.url}」？`, '删除常用地址', { type: 'warning' })
  } catch {
    return
  }
  try {
    const res = await deleteSavedUrl(row.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '删除失败')
      return
    }
    await loadSavedUrls()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
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

/** 失败 / 取消 / 中断的任务，以及还有书没抓完的整站任务，可以从断点继续 */
function canResume(row) {
  if (row.status === 'FAILED' || row.status === 'CANCELLED') return true
  return row.mode === 'site' && row.status === 'SUCCEEDED' && (row.bookDone || 0) < (row.bookTotal || 0)
}

async function openResume(row) {
  Object.assign(resumeDlg, { visible: true, task: row, info: null, loading: true, newOrigin: '', submitting: false })
  try {
    const res = await getCrawlCheckpoint(row.id)
    if (res.code === 0) resumeDlg.info = res.data
  } catch {
    // AI 服务没启动时查不到断点，不影响继续
  } finally {
    resumeDlg.loading = false
  }
}

async function doResume() {
  resumeDlg.submitting = true
  try {
    const res = await resumeCrawl(resumeDlg.task.id, resumeDlg.newOrigin.trim())
    if (res.code !== 0) {
      ElMessage.error(res.message || '继续抓取失败')
      return
    }
    ElMessage.success('已从断点继续抓取')
    resumeDlg.visible = false
    await loadTasks()
    schedulePoll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '继续抓取失败'))
  } finally {
    resumeDlg.submitting = false
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

/** 把旧任务的参数填回表单（可改规则 / 范围后再解析）；全自动任务回到该站点的书目重新选书 */
function reuseOptions(row) {
  const o = row.options || {}
  if (o.mode === 'site') {
    const r = (o.learnedRuleId && learnedRules.value.find((x) => x.id === o.learnedRuleId)) || ruleForUrl(o.url || row.url)
    if (!r) {
      ElMessage.warning('该站点没有 AI 解析出的规律（可能已删除），请先重新 AI 解析该站的一本书')
      return
    }
    mode.value = 'site'
    autoRuleId.value = r.id
    window.scrollTo({ top: 0, behavior: 'smooth' })
    return
  }
  mode.value = 'book'
  const learned = o.learnedRuleId && learnedRules.value.some((r) => r.id === o.learnedRuleId)
  Object.assign(form, emptyForm(), {
    url: o.url || row.url,
    preset: learned ? `learned:${o.learnedRuleId}` : o.learnedRuleId ? '' : o.preset || '',
    delayMs: o.delayMs || 1000,
    respectRobots: o.respectRobots !== false
  })
  // 套用学到的规则时，存档里的 rule 是合并后的结果：规则交给下拉框，不再填进高级选项
  const rule = o.learnedRuleId ? {} : o.rule || {}
  RULE_FIELDS.forEach((f) => (form.rule[f.key] = rule[f.key] || ''))
  form.removeText = (rule.removePatterns || []).join('\n')
  if (Object.keys(rule).length) advancedOpen.value = ['adv']
  preview.value = null
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

// 页面被 keep-alive 缓存：进入时拉取并按需轮询，离开时停止任务列表轮询（AI 解析的轮询不停）
onActivated(async () => {
  if (!presets.value.length) loadPresets()
  loadRules()
  loadSavedUrls()
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
.url-input {
  flex: 1;
}
.url-option {
  display: flex;
  flex-direction: column;
  padding: 4px 0;
  line-height: 1.4;
}
.resume-form {
  margin-top: 16px;
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
.meta.block {
  width: 100%;
  line-height: 1.6;
}
.attempts,
.ai-result {
  margin-top: 12px;
}
.err {
  color: #f56c6c;
}
.rule-line {
  font-family: Consolas, monospace;
  word-break: break-all;
}
.rule-detail {
  padding: 4px 48px;
  line-height: 1.8;
  color: #606266;
  font-size: 13px;
}
.ai-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  margin: 4px 0 8px;
  padding: 8px 12px;
  background: #f4fbf6;
  border: 1px solid #e1f3d8;
  border-radius: 6px;
  font-size: 13px;
}
.ai-strip-msg {
  color: #606266;
}
.ai-strip-usage {
  margin: 0;
}
.ai-desc {
  margin: -6px 0 4px 96px;
  width: auto;
}
.mr6 {
  margin-right: 6px;
}
.ml12 {
  margin-left: 12px;
}
.count {
  color: #909399;
}
.bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.saved-search {
  width: 240px;
}
.saved-form {
  margin-bottom: 8px;
  padding: 12px 12px 0;
  background: #f7f8fa;
  border-radius: 4px;
}
.rules-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.rules-search {
  width: 260px;
}
.rules-tip {
  margin: 0 0 10px;
}
.rules-table :deep(.rule-row) {
  cursor: pointer;
}
.rules-table :deep(.rule-FAILED) {
  background: #fef8f8;
}
.rules-table :deep(.rule-PENDING) {
  background: #fffaf0;
}
.rule-site {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.clamp2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
}
.attempt-dots {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.dot-ok {
  background: #67c23a;
}
.dot-fail {
  background: #f56c6c;
}
.tab-badge {
  margin-left: 4px;
  vertical-align: middle;
}
</style>
