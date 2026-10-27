<template>
  <div class="crawl-page">
    <!-- ================= 抓取配置：网站地址 / 常用地址 / AI 解析 / 解析管理 / 抓取设置 ================= -->
    <el-card v-show="section === 'config'" class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">抓取配置</span>
          <span class="meta">网站地址、常用地址、AI 解析出的站点规律，以及请求间隔等抓取设置都在这里</span>
        </div>
      </template>
      <el-tabs v-model="configTab" class="config-tabs">
        <el-tab-pane name="sites">
          <template #label>小说网站<span v-if="sites.length" class="count">（{{ sites.length }}）</span></template>
          <div class="pane-bar">
            <span class="meta">指定要爬取的小说网站：任何站内地址都按首页保存，不同首页各自独立</span>
            <el-button type="primary" :icon="Plus" @click="openSiteDialog()">新增地址</el-button>
          </div>
          <el-empty v-if="!sites.length" :image-size="72" description="目前没有指定网站地址" />
          <div v-else class="site-list">
            <div v-for="s in sites" :key="s.id" class="site-item">
              <div class="site-main">
                <div class="site-name">{{ s.name || s.rule?.siteName || s.host }}</div>
                <a class="site-home" :href="s.homeUrl" target="_blank" rel="noopener noreferrer">{{ s.homeUrl }}</a>
                <div v-if="s.sampleUrl" class="meta ellipsis" :title="s.sampleUrl">样例书：{{ s.sampleUrl }}</div>
                <div v-if="s.note" class="meta">{{ s.note }}</div>
              </div>
              <div class="site-status">
                <div>
                  <span class="meta">站点规律</span>
                  <el-tag size="small" :type="SITE_RULE[s.rule?.status || 'NONE'].type" class="ml6">
                    {{ SITE_RULE[s.rule?.status || 'NONE'].label }}
                  </el-tag>
                  <span v-if="s.rule?.total" class="meta ml6">掌握 {{ s.rule.mastered }}/{{ s.rule.total }} 项</span>
                </div>
                <div v-if="s.rule?.status === 'FAILED' && s.rule.error" class="err clamp2" :title="s.rule.error">{{ s.rule.error }}</div>
                <div>
                  <span class="meta">书目</span>
                  <template v-if="s.catalog">
                    <el-tag size="small" :type="SITE_DECISION[s.catalog.decision]?.type" class="ml6">
                      {{ SITE_DECISION[s.catalog.decision]?.label }} · {{ s.catalog.bookCount || 0 }} 本
                    </el-tag>
                    <el-tag v-if="s.catalog.status === 'RUNNING'" size="small" type="warning" class="ml6">采集中</el-tag>
                  </template>
                  <span v-else class="meta ml6">未采集</span>
                </div>
              </div>
              <div class="site-ops">
                <el-button size="small" type="success" plain :icon="MagicStick" @click="analyzeSite(s)">AI 解析</el-button>
                <el-button size="small" type="primary" :disabled="!s.rule || s.rule.status === 'FAILED'" @click="autoSite(s)">全自动</el-button>
                <el-button v-if="s.rule" size="small" @click="openRuleDetail(ruleById(s.rule.id))">解析详情</el-button>
                <el-button size="small" link @click="openSiteDialog(s)">修改</el-button>
                <el-button size="small" link type="danger" @click="removeSite(s)">删除</el-button>
              </div>
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane name="saved">
          <template #label>常用地址<span v-if="savedUrls.length" class="count">（{{ savedUrls.length }}）</span></template>
          <div class="dialog-bar">
            <div class="bar-left">
              <el-button type="primary" size="small" :icon="Plus" @click="startAddSaved">添加地址</el-button>
              <el-input v-model="savedDlg.query" size="small" class="saved-search" placeholder="搜索描述 / 地址" clearable />
            </div>
            <span class="meta">收藏常用的书籍页 / 目录页 / 站点首页，「使用」会带到单本抓取或全自动抓取</span>
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
        </el-tab-pane>
        <el-tab-pane name="analyze">
          <template #label>
            AI 解析地址
            <el-tag v-if="aiRunning" size="small" type="warning" class="ml6">解析中</el-tag>
          </template>
          <el-form label-width="96px" @submit.prevent>
            <el-form-item label="入口地址">
              <div class="url-row">
                <el-input
                  v-model="ai.url"
                  class="url-input"
                  placeholder="一本书的详情页或目录页，如 https://example.com/book/123/"
                  clearable
                  @keyup.enter="doAiAnalyze"
                />
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
              请求间隔与 robots 沿用「抓取设置」。需要「模型配置」里有已验证的大模型。
            </div>
          </el-form>
          <div v-if="aiJob" class="preview">
            <div class="sample-title">
              {{ aiJob.url }}
              <el-tag :type="AI_STATUS[aiJob.status]?.type" size="small">{{ AI_STATUS[aiJob.status]?.label || aiJob.status }}</el-tag>
              <el-button v-if="aiJob.status === 'succeeded' && preview" size="small" type="primary" @click="goSection('book')">
                去确认目录并抓取
              </el-button>
              <el-button v-if="!aiRunning" size="small" @click="clearAiJob">清空</el-button>
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
            <div v-if="aiJob.result" class="ai-result">
              <div class="sample-title">首页链接规律</div>
              <HomeLinksView :home-links="aiJob.result.siteMap?.homeLinks" />
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
        <el-tab-pane label="抓取设置" name="network">
          <el-form label-width="104px" class="network-form" @submit.prevent>
            <el-form-item label="请求间隔">
              <el-input-number v-model="form.delayMs" :min="300" :max="30000" :step="100" />
              <span class="hint">毫秒，同一站点两次请求之间至少间隔这么久。太快容易被封 IP 或弹出人机验证</span>
            </el-form-item>
            <el-form-item label="robots.txt">
              <el-switch v-model="form.respectRobots" active-text="遵守" />
              <span class="hint">站点的 robots.txt 不允许的页面不抓（建议保持开启）</span>
            </el-form-item>
            <p class="meta block">单本抓取、AI 解析和全自动的默认值都取这里（全自动面板里还可以单独调）。</p>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- ================= 单本抓取 ================= -->
    <el-card v-show="section === 'book'" class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">单本抓取</span>
          <el-button @click="router.push('/file/manage')">文件管理</el-button>
        </div>
      </template>
      <el-alert type="info" :closable="false" show-icon class="tip"
        title="填写一本小说的「章节目录页」地址，抓取后合并为一个 txt 存入文件管理，可直接发起小说提取。请只抓取你有权使用的内容，并保持合理的请求间隔。" />
      <el-form label-width="104px" @submit.prevent>
        <el-form-item label="目录页地址">
          <div class="url-row">
            <el-input
              v-model="form.url"
              class="url-input"
              placeholder="https://example.com/book/123/"
              clearable
              @keyup.enter="doPreview"
            />
            <el-button type="primary" :loading="previewing" :disabled="!form.url" @click="doPreview">
              解析目录
            </el-button>
            <el-button type="success" plain :icon="MagicStick" @click="openAiDialog('analyze')">
              {{ aiRunning ? `AI 解析中 ${aiJob.attempts?.length || 0}/${aiJob.maxAttempts}` : 'AI 解析' }}
            </el-button>
            <el-button :icon="Collection" @click="openSavedDialog">常用地址<span v-if="savedUrls.length" class="count">（{{ savedUrls.length }}）</span></el-button>
          </div>
        </el-form-item>
        <el-form-item label="抓取规则">
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

        <el-collapse v-model="advancedOpen" class="advanced">
          <el-collapse-item title="高级选项（自定义 XPath）" name="adv">
            <template v-if="true">
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
        <el-form-item label="请求设置">
          <span class="hint no-ml">间隔 {{ form.delayMs }} 毫秒 · {{ form.respectRobots ? '遵守' : '不检查' }} robots.txt</span>
          <el-button link type="primary" class="ml6" @click="openConfig('network')">修改</el-button>
        </el-form-item>
      </el-form>

      <!-- AI 解析状态（详情在「抓取配置 · AI 解析地址」） -->
      <div v-if="aiJob" class="ai-strip">
        <el-tag :type="AI_STATUS[aiJob.status]?.type" size="small">AI 解析 · {{ AI_STATUS[aiJob.status]?.label || aiJob.status }}</el-tag>
        <span class="ai-strip-msg">{{ aiJob.error || aiJob.message }}</span>
        <TokenUsageBar :usage="aiJob.usage" :live="aiRunning" class="ai-strip-usage" />
        <el-button link type="primary" @click="openAiDialog('analyze')">查看过程</el-button>
        <el-button v-if="!aiRunning" link @click="clearAiJob">收起</el-button>
      </div>

      <!-- 单本：目录预览 -->
      <div v-if="preview" class="preview">
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

    </el-card>

    <!-- ================= 全自动抓取 ================= -->
    <el-card v-show="section === 'auto'" class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">全自动抓取</span>
          <div class="header-ops">
            <el-button :icon="MagicStick" @click="openAiDialog('analyze')">AI 解析新站点</el-button>
            <el-button @click="router.push('/file/manage')">文件管理</el-button>
          </div>
        </div>
      </template>
      <el-alert type="info" :closable="false" show-icon class="tip"
        title="选一个 AI 解析过的站点 → 按学到的规律测试能否找到多本书、取到目录 / 简介 / 标签 / 正文（书目存本地，不存正文）→ 决定是否使用 → 按书名 / 作者 / 类型 / 情节筛选后逐本抓取，每本一个 txt。请只抓取你有权使用的内容。" />
      <!-- 全自动：按 AI 解析的规律测试 → 决定 → 筛选书目并抓取 -->
      <AutoCrawlPanel
        :rules="usableRules"
        :prefer-rule-id="autoRuleId"
        :delay-ms="form.delayMs"
        :respect-robots="form.respectRobots"
        @submitted="onAutoSubmitted"
        @open-ai="openAiDialog('analyze')"
      />
    </el-card>

    <!-- ================= 抓取进度：一个首页一个工作区（单本抓取 + 整站抓取），每本小说抓到第几章 ================= -->
    <el-card v-show="section === 'progress'" class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">抓取进度</span>
          <span class="meta">一个网站（首页）一个工作区：单本抓取和整站抓取都在里面，「来源」区分；同一网站的抓取依次排队，不同网站同时进行</span>
        </div>
      </template>
      <WorkspacePanel
        ref="workspaceRef"
        :visible="section === 'progress'"
        :prefer-home="workspaceHome"
        @extract="openExtract"
        @resume="openResume"
        @reuse="reuseOptions"
      />
    </el-card>

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

    <!-- 解析管理：一次解析的详情（每次尝试成败 / 站点结构 / 规则 / 样本） -->
    <RuleDetailDialog v-model="ruleDlg.visible" :rule="ruleDlg.rule" @action="onRuleAction" />

    <!-- 小说网站：新增 / 修改 -->
    <el-dialog v-model="siteDlg.visible" :title="siteDlg.form.id ? '修改网站地址' : '新增网站地址'" width="560px">
      <el-form label-width="64px" @submit.prevent>
        <el-form-item label="地址">
          <el-input v-model="siteDlg.form.url" placeholder="站内任意地址：首页、某本书的书籍页 / 目录页都可以" clearable @keyup.enter="submitSite" />
          <div class="meta block">
            <template v-if="siteHomePreview">将保存为首页：<b>{{ siteHomePreview }}</b>（同一首页只保存一个）。</template>
            <template v-else>请输入 http:// 或 https:// 开头的网址。</template>
            填书籍页 / 目录页时，会顺便记作「样例书」，AI 解析直接用它。
          </div>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="siteDlg.form.name" placeholder="可空，如：某某书城（空时显示域名）" clearable />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="siteDlg.form.note" placeholder="可空" clearable />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="siteDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="siteDlg.saving" :disabled="!siteHomePreview" @click="submitSite">保存</el-button>
      </template>
    </el-dialog>

    <ExtractOptionsDialog
      v-model="extractDlg.visible"
      :file-name="extractDlg.fileName"
      :char-count="extractDlg.charCount"
      @confirm="doExtract"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, MagicStick, Plus, Refresh, Search } from '@element-plus/icons-vue'
import {
  analyzeCrawlUrl,
  cancelCrawlAiJob,
  confirmCrawlRule,
  deleteCrawlRule,
  deleteSavedUrl,
  deleteSite,
  getCrawlAiJob,
  getCrawlCheckpoint,
  listCrawlPresets,
  listCrawlRules,
  listSavedUrls,
  listSites,
  previewCrawl,
  rejectCrawlRule,
  resumeCrawl,
  saveSavedUrl,
  saveSite,
  submitCrawl,
  useSavedUrl
} from '@/api/crawl'
import { submitExtract } from '@/api/novel'
import { errorMessage } from '@/api/request'
import ExtractOptionsDialog from '@/components/material/ExtractOptionsDialog.vue'
import TokenUsageBar from '@/components/ai/TokenUsageBar.vue'
import SiteMapView from '@/components/crawl/SiteMapView.vue'
import HomeLinksView from '@/components/crawl/HomeLinksView.vue'
import WorkspacePanel from '@/components/crawl/WorkspacePanel.vue'
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
const router = useRouter()
const route = useRoute()
// 四个子页面（侧边栏「小说抓取」的子菜单）：config 抓取配置 / book 单本 / auto 全自动 / progress 抓取进度
const SECTIONS = ['config', 'book', 'auto', 'progress']
// 旧地址：整本抓取进度 / 整站工作区已合并为「抓取进度」
const SECTION_ALIAS = { tasks: 'progress', workspace: 'progress' }
// 提交抓取后要打开的工作区（首页地址）
const workspaceHome = ref('')
const workspaceRef = ref(null)
const section = computed(() => {
  const tab = SECTION_ALIAS[route.params.tab] || route.params.tab
  return SECTIONS.includes(tab) ? tab : 'config'
})
watch(
  () => route.params.tab,
  (tab) => {
    if (SECTION_ALIAS[tab]) router.replace(`/novel/crawl/${SECTION_ALIAS[tab]}`)
  },
  { immediate: true }
)
// 旧代码里的「模式」：单本 = book，全自动 = site
const mode = computed(() => (section.value === 'auto' ? 'site' : 'book'))
// 抓取配置页里的标签：sites 小说网站 / saved 常用地址 / analyze AI 解析地址 / rules 解析管理 / network 抓取设置
const configTab = ref('sites')
const presets = ref([])
const form = reactive(emptyForm())
const advancedOpen = ref([])
const previewing = ref(false)
const preview = ref(null)
// 全自动模式要选中的站点规则（解析管理「全自动抓取」/ 地址管理选整站地址 / 任务「改参数」时指定）
const autoRuleId = ref(null)
/** 让全自动面板选中某条规则：先清空再设，同一条规则再点一次也会生效 */
function preferAutoRule(id) {
  autoRuleId.value = null
  nextTick(() => (autoRuleId.value = id))
}
const range = reactive({ start: 1, end: 1 })
const submitting = ref(false)
const extractDlg = reactive({ visible: false, fileId: null, fileName: '', charCount: 0 })
const resumeDlg = reactive({ visible: false, task: null, info: null, loading: false, newOrigin: '', submitting: false })
const ai = reactive({ url: '', maxAttempts: 5, hint: '', autoStart: false, useKnown: true })
const aiJob = ref(null)
const learnedRules = ref([])
const rulesFilter = ref('PENDING')
const rulesQuery = ref('')
const ruleDlg = reactive({ visible: false, rule: null })
const savedUrls = ref([])
// editing：null = 不在编辑；{id?, url, name, mode} = 添加 / 修改中
const savedDlg = reactive({ visible: false, query: '', editing: null, saving: false })
// 小说网站爬取：用户指定的网站（按首页归一），附解析规则状态与书目概况
const sites = ref([])
const siteDlg = reactive({ visible: false, saving: false, form: { id: null, url: '', name: '', note: '' } })
const SITE_RULE = {
  NONE: { label: '未解析', type: 'info' },
  PENDING: { label: '待确认', type: 'warning' },
  CONFIRMED: { label: '已确认', type: 'success' },
  FAILED: { label: '解析失败', type: 'danger' }
}
const SITE_DECISION = {
  PENDING: { label: '待决定', type: 'warning' },
  USED: { label: '使用中', type: 'success' },
  REJECTED: { label: '不使用', type: 'info' }
}
let aiTimer = null

// 本机浏览器里只记住「设置类」选项（请求间隔、robots 等），不记地址历史；要保存地址请用「常用地址」
const DRAFT_KEY = 'nan_novel.crawl.draft'
// 进行中的 AI 解析任务（刷新后接着显示进度）；结束了的不保留
const RESULT_KEY = 'nan_novel.crawl.result'
// 旧版自动记录的「最近使用地址」，已不再使用：打开页面时删掉
try {
  localStorage.removeItem('nan_novel.crawl.recentUrls')
} catch {
  // 存储被禁用：无所谓
}

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

/** 只恢复「设置类」选项（请求间隔、robots、AI 最多尝试次数等）；地址、规则、补充说明一律留空，由用户自己填 */
function restoreDraft() {
  const d = readJson(DRAFT_KEY, null)
  if (!d) return
  if (d.form) {
    if (d.form.delayMs) form.delayMs = d.form.delayMs
    if (typeof d.form.respectRobots === 'boolean') form.respectRobots = d.form.respectRobots
  }
  if (d.ai) {
    if (d.ai.maxAttempts) ai.maxAttempts = d.ai.maxAttempts
    if (typeof d.ai.useKnown === 'boolean') ai.useKnown = d.ai.useKnown
    if (typeof d.ai.autoStart === 'boolean') ai.autoStart = d.ai.autoStart
  }
}

/** 恢复上次的 AI 解析任务状态（进行中的继续轮询）；目录预览不恢复（地址框是空的，旧预览会对不上）。
 *  在页面里切换子页面不会丢东西（同一个组件实例被缓存）。 */
function restoreResult() {
  const r = readJson(RESULT_KEY, null)
  if (r?.aiJob && ['queued', 'running'].includes(r.aiJob.status)) {
    aiJob.value = r.aiJob
    scheduleAiPoll()
  }
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
watch([form, ai], () =>
  writeJson(DRAFT_KEY, {
    form: { delayMs: form.delayMs, respectRobots: form.respectRobots },
    ai: { maxAttempts: ai.maxAttempts, useKnown: ai.useKnown, autoStart: ai.autoStart }
  }), { deep: true })
watch([preview, aiJob, () => range.start, () => range.end], saveResult)

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

/** 回到顶部：页面在右侧内容区（.app-main）里滚动，不是整个窗口 */
function scrollMainTop() {
  document.querySelector('.app-main')?.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 切到某个子页面（侧边栏子菜单对应的路由） */
function goSection(tab) {
  if (section.value !== tab) router.push(`/novel/crawl/${tab}`)
}

/** 抓取配置页的某个标签 */
function openConfig(tab) {
  configTab.value = tab
  goSection('config')
}

/** 单本 / 全自动（旧的模式切换） */
function setMode(m) {
  goSection(m === 'site' ? 'auto' : 'book')
}

/** 提交抓取后跳到「抓取进度」，打开该网站的工作区 */
function openProgress(url) {
  try {
    const u = new URL(url || '')
    workspaceHome.value = ''
    nextTick(() => (workspaceHome.value = `${u.protocol}//${u.host.toLowerCase()}/`))
  } catch {
    // 地址异常时只跳页面
  }
  goSection('progress')
}

/** 全自动：选中的书已提交为抓取任务 */
function onAutoSubmitted(task) {
  openProgress(task?.url)
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
    ElMessage.success(res.data?.message?.includes('同一网站') ? res.data.message : '已开始抓取，进度见「抓取进度」')
    preview.value = null
    openProgress(res.data?.url || form.url)
  } catch (e) {
    ElMessage.error(errorMessage(e, '提交抓取任务失败'))
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- AI 解析地址

const aiRunning = computed(() => !!aiJob.value && ['queued', 'running'].includes(aiJob.value.status))

/** 打开「抓取配置 · AI 解析地址 / 解析管理」（入口地址不预填，由用户填写或从某条地址的「AI 解析」带入） */
function openAiDialog(tab) {
  if (tab === 'rules' && pendingRules.value.length === 0 && rulesFilter.value === 'PENDING') rulesFilter.value = ''
  openConfig(tab)
  loadRules()
}

async function doAiAnalyze() {
  const url = ai.url.trim()
  if (!url || aiRunning.value) return
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
  if (r.preview) {
    preview.value = { ...r.preview, learnedRule: { host: r.host, siteName: r.siteName } }
    range.start = 1
    range.end = r.preview.chapterCount
  }
  if (ai.autoStart && preview.value) {
    ElMessage.success('AI 解析成功，开始抓取全书')
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

// ---------------------------------------------------------------- 小说网站爬取

async function loadSites() {
  try {
    const res = await listSites()
    if (res.code === 0) sites.value = res.data || []
  } catch {
    // 后端没起时不影响其它功能
  }
}

/** 与后端 CrawlSiteService.homeOf 同口径：scheme://host[:port]/ */
const siteHomePreview = computed(() => {
  try {
    const u = new URL(siteDlg.form.url.trim())
    if (!['http:', 'https:'].includes(u.protocol)) return ''
    return `${u.protocol}//${u.host.toLowerCase()}/`
  } catch {
    return ''
  }
})

function openSiteDialog(site) {
  siteDlg.form = site
    ? { id: site.id, url: site.sampleUrl || site.homeUrl, name: site.name || '', note: site.note || '' }
    : { id: null, url: '', name: '', note: '' }
  siteDlg.visible = true
}

async function submitSite() {
  if (!siteHomePreview.value) return
  siteDlg.saving = true
  try {
    const exists = !siteDlg.form.id && sites.value.some((x) => x.homeUrl === siteHomePreview.value)
    const res = await saveSite({ ...siteDlg.form, url: siteDlg.form.url.trim(), name: siteDlg.form.name.trim(), note: siteDlg.form.note.trim() })
    if (res.code !== 0) {
      ElMessage.error(res.message || '保存失败')
      return
    }
    ElMessage.success(exists ? `这个网站已经添加过（${res.data.homeUrl}），已更新` : `已保存：${res.data.homeUrl}`)
    siteDlg.visible = false
    await loadSites()
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    siteDlg.saving = false
  }
}

async function removeSite(site) {
  try {
    await ElMessageBox.confirm(`删除网站「${site.name || site.host}」？只删这条地址，已解析的规则和书目不受影响。`, '删除网站', { type: 'warning' })
  } catch {
    return
  }
  try {
    const res = await deleteSite(site.id)
    if (res.code !== 0) {
      ElMessage.error(res.message || '删除失败')
      return
    }
    await loadSites()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

/** AI 解析该站：有样例书就直接填进入口地址；只有首页时提示填一本书的地址（AI 解析要从一本书学规律） */
function analyzeSite(site) {
  if (aiRunning.value) {
    ElMessage.warning('已有 AI 解析在进行中，请等它结束或取消后再试')
    openAiDialog('analyze')
    return
  }
  ai.url = site.sampleUrl || site.homeUrl
  openAiDialog('analyze')
  if (!site.sampleUrl) ElMessage.info('AI 解析要从一本书学规律：请把入口地址换成该站某本书的书籍页或目录页')
}

/** 用该站的规律进入全自动（测试 → 决定 → 书目） */
function autoSite(site) {
  const r = site.rule && ruleById(site.rule.id)
  if (!r) {
    ElMessage.warning('该站点还没有可用的解析规则')
    return
  }
  useRuleForSite(r)
  scrollMainTop()
}

/** 重新解析：入口地址填这条记录解析过的书，回到「AI 解析地址」页 */
function reanalyze(row) {
  if (aiRunning.value) {
    ElMessage.warning('已有 AI 解析在进行中，请等它结束或取消后再试')
  } else {
    ai.url = row.sampleUrl || ''
  }
  openConfig('analyze')
}
const ruleById = (id) => learnedRules.value.find((r) => r.id === id)
watch(learnedRules, loadSites)

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
  setMode('site')
  preferAutoRule(row.id)
  ElMessage.success('已切到全自动模式：先「开始测试」看看这套规律能否找到多本书')
}

function useRule(row) {
  form.preset = `learned:${row.id}`
  if (!form.url && row.sampleUrl) form.url = row.sampleUrl
  setMode('book')
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
    setMode('site')
    preferAutoRule(r.id)
  } else {
    setMode('book')
    form.url = u.url
  }
  try {
    await useSavedUrl(u.id)
    await loadSavedUrls()
  } catch {
    // 计数失败不影响使用
  }
}

async function openSavedDialog() {
  savedDlg.editing = null
  openConfig('saved')
  await loadSavedUrls()
}

/** 添加：地址默认取主页面当前地址，描述默认取解析出的书名 / 站点名 */
function startAddSaved() {
  const url = form.url.trim()
  const known = savedUrls.value.some((u) => u.url === url)
  const name = mode.value === 'book' ? preview.value?.bookName : ''
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

/** 抓取进度里的单本任务：从断点继续（可换站点地址） */
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
    workspaceRef.value?.reloadAll()
  } catch (e) {
    ElMessage.error(errorMessage(e, '继续抓取失败'))
  } finally {
    resumeDlg.submitting = false
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
    setMode('site')
    preferAutoRule(r.id)
    scrollMainTop()
    return
  }
  setMode('book')
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
  scrollMainTop()
}

function openExtract(row) {
  const name = row.bookName || '抓取小说'
  Object.assign(extractDlg, { visible: true, fileId: row.fileId, fileName: `${name}.txt`, charCount: row.wordCount || 0 })
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
  loadSites()
})
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.task-pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.pane-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.network-form {
  max-width: 760px;
  padding-top: 8px;
}
.hint.no-ml {
  margin-left: 0;
}
.site-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.site-item {
  display: grid;
  grid-template-columns: minmax(240px, 1.2fr) minmax(220px, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafbfc;
}
.site-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}
.site-home {
  font-family: Consolas, monospace;
  color: var(--el-color-primary);
  word-break: break-all;
}
.site-status {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.site-ops {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}
@media (max-width: 900px) {
  .site-item {
    grid-template-columns: 1fr;
  }
  .site-ops {
    justify-content: flex-start;
  }
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
