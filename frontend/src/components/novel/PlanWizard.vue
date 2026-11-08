<template>
  <div class="plan-wizard">
    <div class="intro muted">
      先定<b>写作参数</b>和<b>故事灵感</b> → AI 生成<b>设定</b>（世界规则、力量体系、世界机制、关键资源和主角）→
      在设定的基础上搭<b>全书骨架</b>（分卷 + 阶段），同时按骨架配好<b>配角、势力 / 地点 / 物品 / 怪物和阶段表</b> → <b>写进工作区</b>。
      每一步进入时 AI 先自动生成，每一块都能直接改、也能给个方向让 AI 重来；写进工作区之后在「设定」页里也都能继续改。
      <b>不用素材库也能完整走下来</b>（想用的话，第一步可以挑几条架空素材作补充），只生成框架，不写正文。
    </div>

    <el-steps v-if="!externalSteps" :active="stepIndex" finish-status="success" simple class="steps">
      <el-step v-for="s in steps" :key="s.key" :title="s.title" @click="goStep(s.key)" />
    </el-steps>

    <!-- 故事优先 ① 写作参数 + 灵感 -->
    <div v-show="st.step === 'idea'" class="pane">
      <div class="section-head"><span class="col-title">架空素材</span><span class="muted">可选，最多 {{ MAX_PLAN_MATERIALS }} 条；这一步的 AI 会参考它们，但始终以你填的内容为主</span></div>
      <div class="chips">
        <el-tag v-for="(m, i) in st.materials" :key="m.id" closable class="mat-chip" :type="m.portability === 'direct' ? 'success' : ''" effect="plain"
                :title="m.portability === 'direct' ? '直接可用（点击查看）' : '需要适配（点击查看）'" @click="openMaterial(m.id)" @close="st.materials.splice(i, 1)">
          {{ m.title }}
        </el-tag>
        <el-button size="small" @click="openMatPicker(false)">挑选…</el-button>
        <el-button size="small" title="按写作参数、创作方向和你的想法检索架空版，预选最相关的几条，确认后才放进来" @click="openMatPicker(true)">按参数推荐</el-button>
      </div>
      <MaterialPicker v-model="matPicker.visible" pick-only kind="portable" title="挑选架空素材（只列架空版）" :initial-selected="st.materials"
                      :vector-query="matPicker.query" :auto-vector="matPicker.auto" @apply="applyMaterials" />
      <MaterialEditor v-model="matEditor.visible" :material="matEditor.material" @open-material="openMaterial" />
      <div class="section-head"><span class="col-title">写作参数</span><span class="muted">每一步都会带上；写正文时作为「作品定位」</span></div>
      <BookConfigForm v-model="st.bookConfig" :assist="assistFn" :material-count="st.materials.length" :use-materials="st.useMaterials" />
      <div class="section-head"><span class="col-title">创作方向</span><span class="muted">可选，点选几个；也可以描述你想写的，让 AI 提炼一个</span></div>
      <div class="chips">
        <el-check-tag v-for="d in allDirections" :key="d" :checked="st.directions.includes(d)" @change="toggleDirection(d)">{{ d }}</el-check-tag>
        <AiShortGen :run="(d) => assistFn('direction', d)" title="描述你想写的内容，AI 提炼成一个创作方向" text="自定义"
                    placeholder="如：主角守着一座破法师塔，靠经营和改造法师塔一步步变强" use-text="加进来并选中" @use="addDirection" />
      </div>
      <el-form label-width="76px" size="small" class="mt">
        <el-form-item label="你的想法">
          <AiWandInput v-model="st.premise" :run="(t) => assistFn('premise', t)" :maxlength="500"
                       :allow-empty="matOn('premise')" empty-tip="先写几句，AI 再帮你润色；带上架空素材时空着也能点"
                       placeholder="一句话就行，如：法师，西幻冒险；也可以留空让 AI 按参数自由构思" />
          <el-checkbox v-if="st.materials.length" v-model="st.useMaterials.premise" size="small">润色时带上架空素材（{{ st.materials.length }}）</el-checkbox>
        </el-form-item>
        <el-form-item label="补充要求">
          <AiWandInput v-model="st.conditions" :run="(t) => assistFn('conditions', t)" :maxlength="500" tip="AI 整理成一条条要求"
                       done-text="整理" empty-tip="随手写几句你的要求，AI 帮你整理成一条条"
                       :allow-empty="matOn('conditions')"
                       placeholder="可选，如：不要后宫；主角是女性。也可以随手写一段话，点右下角魔术棒整理" />
          <el-checkbox v-if="st.materials.length" v-model="st.useMaterials.conditions" size="small">整理时把素材的「一定保留」也列进来（{{ st.materials.length }}）</el-checkbox>
        </el-form-item>
        <el-form-item label="模型"><ModelPicker v-model="model" store-key="nan_novel.plan.model" /></el-form-item>
      </el-form>
      <div class="idea-ops">
        <div class="ops">
          <el-button type="primary" :loading="busy === 'idea' && !regenOpen" :disabled="!!busy" @click="run(() => runIdea(false))">
            {{ st.ideas?.length ? '换一批灵感' : '生成 3 个故事灵感' }}
          </el-button>
          <el-button v-if="st.ideas?.length" :disabled="!!busy" @click="openRegen">不满意，说说原因再生成…</el-button>
          <el-button :loading="busy === 'auto'" :disabled="!!busy" @click="runAuto">一键全自动（停在写入前）</el-button>
          <el-checkbox v-if="st.materials.length" v-model="st.useMaterials.idea" size="small">带上架空素材（{{ st.materials.length }}）</el-checkbox>
          <span class="muted">约 5 次模型调用、2~3 分钟（大模型几分钱）</span>
        </div>
        <div class="basis muted idea-basis">
          <el-icon><InfoFilled /></el-icon>
          灵感根据这些生成：<b>写作参数</b>（平台 / 题材 / 标签 / 读者 / 卖点 / 人称 / 文风 / 字数）、勾选的<b>创作方向</b>、
          <b>你的想法</b>（空着 = AI 按参数自由发挥）、<b>补充要求</b>（必须满足）；用「说说原因再生成」时还会带上你写过的所有反馈。
          <template v-if="matOn('idea')"><b>架空素材</b>只作补充：每个灵感至少用上一条，核心仍来自你填的内容。</template>
          <template v-else>不用素材库。</template>不看这个工作区已有的设定和章节。
          <el-button v-if="lastRun" link type="primary" size="small" @click="logicOpen = true">查看这批的生成逻辑</el-button>
        </div>
      </div>
      <div v-if="autoLog.length" class="auto-log"><div v-for="(l, i) in autoLog" :key="i">{{ l }}</div></div>
      <template v-if="st.ideas?.length">
        <div class="section-head"><span class="col-title">选一个灵感</span><span class="muted">选中的可以直接改</span></div>
        <div class="idea-grid">
          <div v-for="(it, i) in st.ideas" :key="i" class="card idea" :class="{ on: st.ideaPick === i }" @click="pickIdea(i)">
            <b>{{ it.title || `灵感 ${i + 1}` }}</b>
            <div class="hook">{{ it.hook }}</div>
            <div class="muted">{{ it.core }}</div>
            <div v-if="it.materials" class="idea-mats">
              <template v-if="it.materials.length">
                用了：<el-button v-for="m in it.materials" :key="m.id" link type="primary" size="small" @click.stop="openMaterial(m.id)">{{ m.title }}</el-button>
                <span v-if="it.materials[0].used" class="muted">（{{ it.materials[0].used }}）</span>
              </template>
              <span v-else class="muted">没用上素材</span>
            </div>
          </div>
        </div>
        <el-form v-if="st.idea" label-width="76px" size="small" class="mt">
          <el-form-item v-for="[k, lab] in IDEA_FIELDS" :key="k" :label="lab">
            <el-input v-model="st.idea[k]" type="textarea" :autosize="{ minRows: 1 }" maxlength="300" />
          </el-form-item>
        </el-form>
        <div class="ops">
          <el-button type="primary" :loading="busy === 'settings'" :disabled="!!busy || !st.idea" @click="run(enterSettings)">下一步：生成设定</el-button>
        </div>
      </template>

      <!-- 带反馈的重新生成：不满意哪里 + 希望是什么，都记下来，以后每次重新生成都带上 -->
      <el-dialog v-model="regenOpen" title="说说哪里不满意，再生成一批" width="560px" append-to-body>
        <el-form label-position="top" size="small">
          <el-form-item label="对这批灵感哪里不满意">
            <el-input v-model="regenForm.dislike" type="textarea" :rows="2" maxlength="300" show-word-limit
                      placeholder="如：都太套路，主角都是被动卷进事件的" />
          </el-form-item>
          <el-form-item label="希望是什么样的">
            <el-input v-model="regenForm.want" type="textarea" :rows="2" maxlength="300" show-word-limit
                      placeholder="如：主角一开始就有明确的野心，故事核心是经营一座法师塔" />
          </el-form-item>
        </el-form>
        <div v-if="st.ideaFeedback.length" class="fb-history">
          <div class="muted">之前写过的反馈（会一起带上）：</div>
          <div v-for="(f, i) in st.ideaFeedback" :key="i" class="fb-row">
            <span class="muted">{{ f.at }}</span>
            <span v-if="f.dislike">不满意：{{ f.dislike }}</span>
            <span v-if="f.want">希望：{{ f.want }}</span>
            <el-button link type="danger" size="small" @click="st.ideaFeedback.splice(i, 1)">删除</el-button>
          </div>
        </div>
        <template #footer>
          <el-button @click="regenOpen = false">取消</el-button>
          <el-button type="primary" :loading="busy === 'idea'" :disabled="!regenForm.dislike.trim() && !regenForm.want.trim()" @click="submitRegen">
            记下来并重新生成
          </el-button>
        </template>
      </el-dialog>

      <!-- 这批灵感实际用到的输入（生成那一刻的快照） -->
      <el-dialog v-model="logicOpen" title="这批灵感的生成逻辑" width="600px" append-to-body>
        <template v-if="lastRun">
          <div class="muted">生成时间：{{ lastRun.at }}{{ lastRun.feedback?.length ? '（重新生成，带反馈）' : '' }}</div>
          <el-descriptions :column="1" border size="small" class="mt">
            <el-descriptions-item label="写作参数">{{ configText(lastRun.inputs.bookConfig) || '（没填）' }}</el-descriptions-item>
            <el-descriptions-item label="创作方向">{{ lastRun.inputs.directions?.join('、') || '（没选）' }}</el-descriptions-item>
            <el-descriptions-item label="你的想法">{{ lastRun.inputs.premise || '（空着，AI 按参数自由发挥）' }}</el-descriptions-item>
            <el-descriptions-item label="补充要求">{{ lastRun.inputs.conditions || '（没填）' }}</el-descriptions-item>
            <el-descriptions-item label="架空素材">{{ lastRun.materials?.join('、') || '（没带）' }}</el-descriptions-item>
            <template v-for="(f, i) in lastRun.feedback || []" :key="i">
              <el-descriptions-item :label="`反馈 ${i + 1} · 不满意`">{{ f.dislike || '—' }}</el-descriptions-item>
              <el-descriptions-item :label="`反馈 ${i + 1} · 希望`">{{ f.want || '—' }}</el-descriptions-item>
              <el-descriptions-item v-if="f.rejected?.length" :label="`反馈 ${i + 1} · 否掉的灵感`">{{ f.rejected.join('；') }}</el-descriptions-item>
            </template>
          </el-descriptions>
        </template>
      </el-dialog>
    </div>

    <!-- 故事优先 ② 全书骨架 -->
    <div v-show="st.step === 'book'" class="pane">
      <AiBasis :md="bookBasis" title="骨架根据这些生成" />
      <RunSnapshot run-key="book" />
      <el-form label-width="84px" size="small" class="mt">
        <el-form-item label="卷数">
          <el-select v-model="st.volumeCount" style="width: 140px">
            <el-option :value="0" label="AI 决定（2~4 卷）" />
            <el-option v-for="n in 6" :key="n" :value="n" :label="`${n} 卷`" />
          </el-select>
          <span class="muted gap">全书约 {{ plannedChapters }} 章（按写作参数的字数算）</span>
        </el-form-item>
        <el-form-item label="节奏">
          <el-radio-group v-model="st.pace">
            <el-radio-button v-for="p in PACES" :key="p.value" :value="p.value" :title="p.desc">{{ p.label }}</el-radio-button>
          </el-radio-group>
          <span class="muted gap">{{ PACES.find((p) => p.value === st.pace)?.desc }}</span>
        </el-form-item>
        <el-form-item label="分卷方向">
          <div class="list-edit">
            <div v-for="(v, i) in st.volumePlan" :key="i" class="row">
              <span class="muted vol-no">第 {{ i + 1 }} 卷</span>
              <el-input v-model="st.volumePlan[i]" maxlength="200" placeholder="这一卷大致写什么，如：初到法师塔，从学徒熬出头" />
              <el-button link type="danger" @click="st.volumePlan.splice(i, 1)">删</el-button>
            </div>
            <el-button link size="small" @click="st.volumePlan.push('')">+ 写一卷的方向</el-button>
            <span class="muted gap">可选。例：第 1~3 卷都写「在法师塔」，骨架就不会第二卷就跳到浮空城</span>
          </div>
        </el-form-item>
      </el-form>
      <div class="ops">
        <el-button :type="bookObj ? '' : 'primary'" :loading="busy === 'book'" :disabled="!!busy || !draft" @click="run(runBookAll)">
          {{ bookObj ? '按上面的卷数 / 节奏 / 分卷方向重新生成骨架' : '生成全书骨架' }}
        </el-button>
        <span v-if="!draft" class="muted">先完成上一步的设定</span>
      </div>
      <template v-if="bookObj">
        <IssueList :issues="st.book.issues" />
        <el-form label-width="84px" size="small" class="mt">
          <el-form-item label="书名">
            <el-select v-model="st.bookTitle" filterable allow-create default-first-option style="width: 300px">
              <el-option v-for="t in titleChoices" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
        </el-form>
        <BookSkeleton :book="bookObj" :regen-busy="busy === 'regen' ? regenIndex : -1" :disabled="!!busy" :regen-basis="volumeBasis" @regen="regenVolume" />

        <!-- 按骨架配的配角、势力 / 地点 / 物品 / 怪物、阶段表 -->
        <template v-if="draft">
          <div class="section-head"><span class="col-title">人物与元素</span>
            <el-button size="small" :loading="busy === 'cast'" :disabled="!!busy" @click="run(runCast)">
              {{ st.castAt ? '按骨架重新配人物和元素' : '按骨架配人物和元素' }}</el-button></div>
          <AiBasis :md="castBasis" title="人物和元素根据这些生成" />
          <RunSnapshot run-key="cast" />
          <IssueList :issues="st.castIssues" />
          <div class="section-head"><span class="col-title">配角（{{ castChars.length }}）</span>
            <el-button link size="small" @click="draft.characters.push(blankCharacter())">+ 配角</el-button>
            <PartRegen module="characters" /></div>
          <PlanCastCard v-for="c in castChars" :key="'c' + draft.characters.indexOf(c)" :item="c" :stage-name="stageOf(c.appearFrom)"
                        @remove="draft.characters.splice(draft.characters.indexOf(c), 1)" />
          <div class="section-head"><span class="col-title">势力 / 地点 / 物品 / 怪物（{{ draft.elements.length }}）</span>
            <el-button v-for="(lab, cat) in ELEMENT_LABELS" :key="'add' + cat" link size="small" @click="addElement(cat)">+ {{ lab }}</el-button>
            <PartRegen v-for="(lab, cat) in ELEMENT_LABELS" :key="cat" module="elements" :category="cat" /></div>
          <PlanCastCard v-for="(e, i) in draft.elements" :key="'e' + i" kind="element" :item="e" :stage-name="stageOf(e.appearFrom)"
                        @remove="draft.elements.splice(i, 1)" />
          <div class="section-head"><span class="col-title">阶段表</span>
            <span class="muted">由全书骨架算出（重新生成骨架会更新）；写作时按它控制主角实力和对手上限</span></div>
          <div v-for="(s, i) in draft.stages" :key="'s' + i" class="need-row">
            <el-input v-model="s.range" size="small" style="width: 90px" placeholder="1-10" />
            <el-input v-model="s.power" size="small" style="flex: 1" placeholder="主角实力" />
            <span class="muted">对手上限</span><el-input-number v-model="s.tierMax" size="small" :min="1" :max="5" style="width: 90px" />
            <el-input v-model="s.note" size="small" style="flex: 1" placeholder="备注" />
            <el-button link type="danger" size="small" @click="draft.stages.splice(i, 1)">删</el-button>
          </div>
        </template>
        <div class="ops">
          <el-button type="primary" :disabled="!!busy" @click="st.step = 'apply'">下一步：写进工作区</el-button>
        </div>
      </template>
    </div>

    <!-- 设定（世界 + 主角） -->
    <div v-show="st.step === 'settings'" class="pane">
      <template v-if="draft">
        <AiBasis :md="settingsBasis" title="设定根据这些生成" />
        <RunSnapshot run-key="settings" />
        <div class="muted mt">每一块都可以直接改；不满意的块点「AI 重新生成」单独重来——可以给一句方向，也可以勾「参考已有内容」在原来的基础上补充。
          写进工作区之后在「设定」页里也能继续改。</div>
        <IssueList :issues="st.settings.issues" />
        <!-- 按方向重写了一块后，模型指出其他块里和方向矛盾的句子：提醒一起改，免得设定前后矛盾（骨架会照着设定写） -->
        <div v-if="st.related?.items?.length" class="related">
          <div>刚才的方向「{{ st.related.direction }}」和其他块里的这些说法有矛盾，可以用同样的方向重来那一块（或者手改）：</div>
          <div class="related-items">
            <span v-for="it in st.related.items" :key="it.module + it.category" class="related-item">
              {{ it.label }}：「{{ it.term }}」
              <el-button link type="primary" size="small" :disabled="!!busy"
                         @click="regenPart(it.module, it.category, { direction: st.related.direction, keep: true })">用同样的方向重来</el-button>
            </span>
            <el-button link size="small" @click="st.related = null">知道了</el-button>
          </div>
        </div>
        <el-form label-width="84px" class="mt">
          <!-- 书名在全书骨架那一步选（灵感的暂定名是候选之一） -->
          <el-form-item label="世界规则">
            <div class="list-edit">
              <div v-for="(r, i) in draft.world.rules" :key="i" class="row">
                <el-input v-model="draft.world.rules[i]" size="small" />
                <el-button link type="danger" size="small" @click="draft.world.rules.splice(i, 1)">删</el-button>
              </div>
              <el-button link size="small" @click="draft.world.rules.push('')">+ 规则</el-button>
              <PartRegen module="rules" />
              <div class="muted field-tip">不能违反的硬性规则，一句话一条；每一章写作都会带上，AI 不会写出和它冲突的内容。如：法师塔必须建在地脉节点上</div>
            </div>
          </el-form-item>
          <el-form-item label="世界观补充">
            <div class="list-edit">
              <el-input v-model="draft.world.note" type="textarea" :rows="2" />
              <PartRegen module="note" />
            </div>
          </el-form-item>
        </el-form>

        <!-- 不生成世界背景卡（和世界规则重叠；设定页里的「世界背景卡」照旧可以自己加） -->
        <div class="section-head"><span class="col-title">力量体系 · 能力</span>
          <PartRegen module="power" /><PartRegen module="abilities" /></div>
        <div v-if="power && abilities" class="card">
          <el-input v-model="power.intro" type="textarea" :autosize="{ minRows: 1 }" size="small" placeholder="怎么获得、怎么变强" />
          <div v-for="(r, i) in power.realms" :key="'r' + i" class="need-row mt">
            <el-tag size="small" effect="plain">{{ i + 1 }}</el-tag>
            <el-input v-model="r.name" size="small" style="width: 120px" placeholder="境界" />
            <el-input v-model="r.desc" size="small" style="flex: 2" placeholder="能做到什么" />
            <el-input v-model="r.cost" size="small" style="flex: 1" placeholder="突破的门槛 / 代价" />
            <el-button link type="danger" size="small" @click="power.realms.splice(i, 1)">删</el-button>
          </div>
          <el-button link size="small" @click="power.realms.push({ name: '', desc: '', cost: '' })">+ 境界</el-button>
          <el-input v-model="power.beyond" size="small" class="mt"><template #prepend>更高层次</template></el-input>
          <div class="grid2 mt">
            <el-input v-model="abilities.innate" size="small"><template #prepend>先天</template></el-input>
            <el-input v-model="abilities.acquired" size="small"><template #prepend>后天</template></el-input>
          </div>
        </div>
        <div class="grid2">
          <div v-for="[k, lab] in [['mechanics', '世界机制'], ['resources', '关键资源']]" :key="k">
            <div class="section-head"><span class="col-title">{{ lab }}</span>
              <el-button link size="small" @click="(draft.world[k] ||= []).push({ title: '', desc: '' })">+ 一条</el-button>
              <PartRegen :module="k" /></div>
            <div v-if="k === 'mechanics'" class="muted field-tip mech-tip">这个世界怎么运转：制度、交易、周期性现象的具体做法和数字；每一章写作也都会带上。如：塔税按副本收益的 30% 征收。和世界规则写的是同一件事时只留一处</div>
            <div v-for="(x, i) in draft.world[k]" :key="k + i" class="need-row">
              <el-input v-model="x.title" size="small" style="width: 110px" />
              <el-input v-model="x.desc" size="small" style="flex: 1" />
              <el-button link type="danger" size="small" @click="draft.world[k].splice(i, 1)">删</el-button>
            </div>
          </div>
        </div>

        <!-- 设定这一步只有主角；配角、势力地点…、阶段表按骨架的阶段安排，在骨架那一步 -->
        <div class="section-head"><span class="col-title">主角</span><PartRegen module="lead" />
          <span class="muted">配角、势力 / 地点 / 物品 / 怪物、阶段表在下一步按全书骨架安排</span></div>
        <PlanCastCard v-for="c in leadChars" :key="'lead' + draft.characters.indexOf(c)" :item="c" lead />
        <el-button v-if="!leadChars.length" link size="small" @click="draft.characters.unshift({ ...blankCharacter(), role: '主角', appearFrom: 1 })">+ 主角</el-button>
        <div class="ops">
          <el-button :loading="busy === 'settings'" :disabled="!!busy" @click="run(runSettings)">整份重新生成设定</el-button>
          <el-button type="primary" :loading="busy === 'book' || busy === 'cast'" :disabled="!!busy" @click="run(enterBook)">下一步：生成全书骨架</el-button>
        </div>
      </template>
    </div>

    <!-- 故事优先 ④ 素材点睛（可选） -->
    <div v-show="st.step === 'enrich'" class="pane">
      <div class="muted">
        可选。按设定里的每个人物 / 元素去素材库找相近的（本机检索，不花 token），过了相关度线的才交给 AI，
        给几条「补细节」的建议（不改名字、不推翻设定）；你逐条决定采不采用。素材库里没有合适的就直接跳过。
      </div>
      <el-form label-width="84px" size="small" class="mt">
        <el-form-item label="屏蔽来源书">
          <el-select v-model="st.excludeBooks" multiple filterable allow-create clearable placeholder="这些书的素材不用（可选）" style="width: 420px">
            <el-option v-for="b in sourceBooks" :key="b" :label="b" :value="b" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="ops">
        <el-button type="primary" :loading="busy === 'enrich'" :disabled="!!busy || libraryEmpty || !draft" @click="run(runEnrich)">从素材库找点睛建议</el-button>
        <span v-if="libraryEmpty" class="muted">素材库是空的</span>
      </div>
      <template v-if="st.enrich">
        <div v-if="!st.enrich.suggestions?.length" class="muted">
          {{ st.enrich.materials?.length ? 'AI 觉得这些素材没有让设定更好的地方' : `检索了 ${st.enrich.searched || 0} 个对象，素材库里没有足够相关的` }}，可以直接下一步。
        </div>
        <div v-for="(s, i) in st.enrich.suggestions" :key="i" class="card" :class="{ adopted: st.enrichOriginals[i] }">
          <div class="card-head">
            <el-tag size="small">{{ ELEMENT_LABELS[s.kind] || '人物' }}</el-tag><b>{{ s.name }}</b>
            <span>{{ s.suggestion }}</span>
            <el-tag v-if="st.enrichOriginals[i]" size="small" type="success" effect="dark">已采用</el-tag>
          </div>
          <div v-for="(v, k) in s.fields" :key="k" class="field-line">
            <span class="muted">{{ FIELD_LABELS[k] || CHARACTER_LABELS[k] || k }}：</span>
            <span>{{ Array.isArray(v) ? v.join('、') : v }}</span>
          </div>
          <div class="muted source">来源：{{ s.sources.map((id) => enrichTitles[id] || `素材 ${id}`).join('、') || '—' }}</div>
          <div v-if="s.leaks?.length" class="warn">· 用了素材原名：{{ s.leaks.join('、') }}（采用前最好改掉）</div>
          <el-button v-if="!st.enrichOriginals[i]" link type="primary" size="small" @click="adoptSuggestion(i)">采用</el-button>
          <el-button v-else link size="small" @click="revertSuggestion(i)">撤销</el-button>
        </div>
      </template>
      <div class="ops">
        <el-button type="primary" :loading="busy === 'outline'" :disabled="!!busy || !draft" @click="run(runOutline)">下一步：规划 {{ CHAPTERS }} 章</el-button>
      </div>
    </div>

    <!-- 大纲 + 伏笔计划 -->
    <div v-show="st.step === 'outline'" class="pane">
      <template v-if="outline">
        <div v-if="st.outline.bookStage" class="muted">
          按全书骨架：第 {{ st.outline.bookStage.volume + 1 }} 卷《{{ st.outline.bookStage.volumeTitle }}》·
          {{ st.outline.bookStage.title }}（第 {{ st.outline.bookStage.start }}~{{ st.outline.bookStage.end }} 章）：{{ st.outline.bookStage.goal }}
        </div>
        <IssueList :issues="st.outline.issues" />
        <el-form label-width="84px" class="mt">
          <el-form-item label="一句话"><el-input v-model="outline.logline" /></el-form-item>
          <el-form-item label="梗概"><el-input v-model="outline.synopsis" type="textarea" :rows="3" /></el-form-item>
        </el-form>
        <ChapterCard v-for="c in outline.chapters" :key="c.index" :chapter="c" :foreshadows="outline.foreshadows" :clocks="outline.clocks"
                     :opening="opening && c.index < startIndex + 3" />
        <div class="section-head"><span class="col-title">伏笔计划（写进故事账本「计划中」）</span>
          <el-button link size="small" @click="addForeshadow">+ 伏笔</el-button></div>
        <div v-for="(f, i) in outline.foreshadows" :key="f.key" class="need-row">
          <el-tag size="small">{{ f.key }}</el-tag>
          <el-input v-model="f.text" size="small" style="flex: 1" />
          <span class="muted">第</span><el-input-number v-model="f.plantIn" size="small" :min="0" :max="999" controls-position="right" style="width: 80px" /><span class="muted">章埋</span>
          <span class="muted">第</span><el-input-number v-model="f.payoffIn" size="small" :min="0" :max="999" controls-position="right" style="width: 80px" /><span class="muted">章收（0 = 之后）</span>
          <el-button link type="danger" size="small" @click="outline.foreshadows.splice(i, 1)">删</el-button>
        </div>
        <div class="section-head"><span class="col-title">定时事件</span></div>
        <div v-for="(k, i) in outline.clocks" :key="k.key" class="need-row">
          <el-tag size="small" type="warning">{{ k.key }}</el-tag>
          <el-input v-model="k.text" size="small" style="flex: 1" />
          <el-input v-model="k.due" size="small" style="width: 110px" placeholder="期限" />
          <span class="muted">第</span><el-input-number v-model="k.setIn" size="small" :min="0" :max="999" controls-position="right" style="width: 80px" /><span class="muted">章定下，第</span>
          <el-input-number v-model="k.dueIn" size="small" :min="0" :max="999" controls-position="right" style="width: 80px" /><span class="muted">章到期</span>
          <el-button link type="danger" size="small" @click="outline.clocks.splice(i, 1)">删</el-button>
        </div>
        <div class="ops">
          <el-button :loading="busy === 'outline'" :disabled="!!busy" @click="run(runOutline)">重新规划</el-button>
          <el-button type="primary" :loading="busy === 'review'" :disabled="!!busy" @click="run(runReview)">下一步：AI 审稿</el-button>
          <el-button :disabled="!!busy" @click="st.step = 'apply'">跳过审稿</el-button>
        </div>
      </template>
    </div>

    <!-- 审稿 -->
    <div v-show="st.step === 'review'" class="pane">
      <template v-if="st.review">
        <el-alert v-if="st.review.error" type="warning" :closable="false" show-icon class="mt"
                  :title="`AI 审稿没成功（${st.review.error}），下面只有代码检查的结果；可以「重新审稿」，也可以直接写进工作区`" />
        <div v-if="st.review.overall?.length" class="overall">
          <b>整体意见</b>
          <div v-for="(o, i) in st.review.overall" :key="i">· {{ o }}</div>
        </div>
        <IssueList :issues="st.review.codeIssues" />
        <div v-for="r in st.review.chapters" :key="r.index" class="card">
          <div class="card-head"><b>第 {{ r.index }} 章《{{ chapterOf(r.index)?.title }}》</b>
            <el-tag v-if="!r.problems.length" size="small" type="success">没问题</el-tag>
            <el-tag v-if="st.originals[r.index]" size="small" type="success" effect="dark">已采用修正</el-tag>
          </div>
          <div v-for="(p, i) in r.problems" :key="i" class="warn">· {{ p }}</div>
          <div v-if="r.revised" class="revised">
            <div><b>修正版：</b>《{{ r.revised.title }}》{{ r.revised.goal }}</div>
            <div class="muted">节拍：{{ r.revised.beats.join('；') }}｜钩子：{{ r.revised.hook }}</div>
            <el-button v-if="!st.originals[r.index]" link type="primary" size="small" @click="adoptRevision(r)">采用修正</el-button>
            <el-button v-else link size="small" @click="revertRevision(r.index)">恢复原版</el-button>
          </div>
        </div>
        <div class="ops">
          <el-button size="small" @click="adoptAll">全部采用修正</el-button>
          <el-button :loading="busy === 'review'" :disabled="!!busy" @click="run(runReview)">重新审稿</el-button>
          <el-button type="primary" @click="st.step = 'apply'">下一步：写进工作区</el-button>
        </div>
      </template>
    </div>

    <!-- 写进工作区 -->
    <div v-show="st.step === 'apply'" class="pane">
      <template v-if="draft && bookObj">
        <div class="summary">
          <el-checkbox v-model="applyOpts.settings">
            设定：{{ draft.characters.length }} 个人物、{{ draft.elements.length }} 个元素、{{ draft.world.rules.length }} 条世界规则、力量体系、世界机制、关键资源、{{ draft.stages.length }} 行阶段表（追加进设定页，不覆盖已有的；之后都能在设定页里改）
          </el-checkbox>
          <el-checkbox v-model="applyOpts.book">全书骨架（{{ bookObj.volumes.length }} 卷）和写作参数（写正文时作为「作品定位」）</el-checkbox>
          <el-checkbox v-model="applyOpts.title">书名改成《{{ applyTitle }}》</el-checkbox>
        </div>
        <div class="ops">
          <el-button type="primary" :loading="busy === 'apply'" :disabled="!!busy || (!applyOpts.settings && !applyOpts.book && !applyOpts.title)" @click="runApply()">写进工作区</el-button>
          <span v-if="st.appliedAt" class="muted">已于 {{ st.appliedAt }} 写入过一次（再写会重复追加设定）</span>
        </div>
      </template>
      <div v-else class="muted">先完成设定和全书骨架</div>
    </div>

    <div v-if="autoLog.length && st.step !== 'idea'" class="auto-log mt"><div v-for="(l, i) in autoLog" :key="i">{{ l }}</div></div>
    <TokenUsageBar v-if="usage.calls" :usage="usage" class="mt" />
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'
import { ElButton, ElInput, ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import AiBasis from '@/components/ai/AiBasis.vue'
import AiRegenButton from '@/components/ai/AiRegenButton.vue'
import AiShortGen from '@/components/ai/AiShortGen.vue'
import AiWandInput from '@/components/ai/AiWandInput.vue'
import ModelPicker from '@/components/persona/ModelPicker.vue'
import TokenUsageBar from '@/components/ai/TokenUsageBar.vue'
import BookConfigForm from '@/components/novel/BookConfigForm.vue'
import BookSkeleton from '@/components/novel/BookSkeleton.vue'
import PlanCastCard from '@/components/novel/PlanCastCard.vue'
import MaterialEditor from '@/components/material/MaterialEditor.vue'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import { getMaterial, getMaterialSources } from '@/api/material'
import {
  ACTION_LABELS, DIRECTIONS, ELEMENT_LABELS, PACES, applyPlan, blankBookConfig, bookLayout, bookStages, getPlanDraft,
  planAssist, planBook, planCast, planEnrich, planIdea, planOutline, planReview, planSettings, planSettingsPart,
  savePlanDraft
} from '@/api/novelPlan'
import { errorMessage } from '@/api/request'

const props = defineProps({
  novelId: { type: String, required: true },
  chapterCount: { type: Number, default: 0 },          // 已写章数（0 = 开篇）
  initialPremise: { type: String, default: '' },       // 新建工作区时带来的一句构思
  applySettings: { type: Function, required: true },   // (items) => Promise<{done, failed}>：写进设定编辑器并保存
  book: { type: Object, default: null },               // 工作区已保存的全书骨架（novel.book）
  bookConfig: { type: Object, default: null },         // 工作区已保存的写作参数（novel.bookConfig）
  continueSignal: { type: Number, default: 0 },        // 写作页「按骨架规划接下来 10 章」：变化一次 = 自动续规划一次
  externalSteps: { type: Boolean, default: false }     // 步骤条由外面画（工作区书房左栏，用 expose 的 nav）
})
const emit = defineEmits(['applied'])

const CHAPTERS = 10
// 故事优先到全书骨架为止就写进工作区（素材点睛 / 10 章大纲 / 审稿的代码还在，先不放进流程，见 docs/待办.md「待定」）
const STORY_STEPS = [['idea', '参数 · 灵感'], ['settings', '设定'], ['book', '全书骨架'], ['apply', '写进工作区']]
const IDEA_FIELDS = [['title', '暂定名'], ['core', '核心设定'], ['situation', '主角处境'], ['conflict', '核心冲突'], ['payoff', '爽点方向'], ['hook', '一句话卖点']]
const FIELD_LABELS = { stance: '立场', feature: '特点', kind: '类型', detail: '描述', effect: '作用', appearance: '外形',
  abilities: '能力', weakness: '弱点', habitat: '栖息地' }
const CHARACTER_LABELS = { tagline: '一句话人设', goal: '想要', fear: '缺陷 / 恐惧', secret: '秘密', background: '背景', arc: '成长弧光' }

const blankState = () => ({
  step: 'idea',
  premise: '', tone: '', conditions: '', excludeBooks: [],
  bookConfig: blankBookConfig(), directions: [], ideas: null, ideaPick: -1, idea: null, book: null, bookTitle: '',
  enrich: null, enrichOriginals: {},
  volumePlan: [], volumeCount: 0, pace: 'normal', partUndo: {}, related: null,
  customDirections: [], ideaFeedback: [], ideaRuns: [],
  // 架空素材篮（[{id, title, category, portability}]）和这一步 5 处 AI 各自的开关
  materials: [], useMaterials: { sellingPoint: true, style: true, premise: true, conditions: true, idea: true },
  castIssues: [], castAt: '', runs: {}, sig: {},   // 骨架这一步的人物 / 元素检查；每次 AI 生成的依据快照；生成时输入的指纹（改过才问要不要重来）   // 自定义创作方向；重新生成时的反馈（全部记录）；每批灵感的输入快照   // 骨架的分卷方向 / 卷数 / 节奏；设定分模块重来的撤销
  settings: null, outline: null, review: null, originals: {}, appliedAt: ''
})
const st = reactive(blankState())
const model = ref({ source: 'api', configId: null, baseId: null })
const busy = ref('')
const autoLog = ref([])
const sourceBooks = ref([])
const libraryEmpty = ref(false)
const usage = reactive({ source: 'api', calls: 0, promptTokens: 0, completionTokens: 0 })
const applyOpts = reactive({ settings: true, outline: true, book: true, title: props.chapterCount === 0 })

const steps = STORY_STEPS.map(([key, title]) => ({ key, title }))
const stepIndex = computed(() => Math.max(0, steps.findIndex((s) => s.key === st.step)))
const startIndex = computed(() => props.chapterCount + 1)
const opening = computed(() => startIndex.value === 1)
const draft = computed(() => st.settings?.draft)
const outline = computed(() => st.outline?.outline)
const bookObj = computed(() => st.book?.book)
// 全书章数（与 Python planner.planned_chapters 同一算法：目标字数 ÷ 单章字数，没填 = 300）
const plannedChapters = computed(() => {
  const words = (v) => {
    const m = String(v || '').match(/(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K)?/)
    return m ? Number(m[1]) * ({ 万: 10000, w: 10000, W: 10000, 千: 1000, k: 1000, K: 1000 }[m[2]] || 1) : 0
  }
  const total = words(st.bookConfig?.targetWords)
  return total ? Math.max(30, Math.min(2000, Math.round(total / (words(st.bookConfig?.chapterWords) || 3000)))) : 300
})
const regenIndex = ref(-1)
const partBusy = ref('')
const power = computed(() => draft.value.world.power)
const abilities = computed(() => draft.value.world.abilities)
/** 设定一定有力量体系 / 能力两块（模型没给也留出空位，方便手填） */
function ensureWorldSlots() {
  const w = draft.value?.world
  if (!w) return
  w.power ||= { intro: '', realms: [], beyond: '' }
  w.abilities ||= { innate: '', acquired: '', dimensions: [] }
}
const enrichTitles = computed(() => Object.fromEntries((st.enrich?.materials || []).map((m) => [m.id, `${m.title}${m.book ? `（《${m.book}》）` : ''}`])))
const applyTitle = computed(() => st.bookTitle || st.idea?.title || outline.value?.title || '')
// 书名候选：骨架给的 3 个 + 选中灵感的暂定名（去重）；也可以自己输入
const titleChoices = computed(() => [...new Set([...(bookObj.value?.titleOptions || []), st.idea?.title].filter(Boolean))])
const chapterOf = (i) => outline.value?.chapters.find((c) => c.index === i)
const blankCharacter = () => ({ name: '', role: '配角', tagline: '', personality: [], goal: '', fear: '', secret: '', abilities: [],
  background: '', arc: '', relationToLead: '', appearFrom: startIndex.value, sources: [], adapted: '' })
const clone = (x) => JSON.parse(JSON.stringify(x))

/* ---------- 草稿：每步之后存一次，刷新不丢 ---------- */
let saveTimer = null
let draftOwner = ''   // 草稿是从哪个工作区读出来的：只往这个工作区存（防止切换工作区后把别的工作区的草稿存进来）
function persist() {
  clearTimeout(saveTimer)
  const owner = draftOwner
  if (!owner || owner !== props.novelId) return
  saveTimer = setTimeout(() => savePlanDraft(owner, clone(st)).catch(() => {}), 800)
}

onMounted(async () => {
  const id = props.novelId
  try {
    const res = await getPlanDraft(id)
    // 读到了（有草稿或确实没有）才允许往这个工作区存；读失败就不存，免得拿空白草稿把已有的覆盖掉
    if (res.code === 0) draftOwner = id
    if (res.code === 0 && res.data) {
      const d = res.data
      if (typeof d.step === 'number' || d.mode === 'material') {
        // 素材优先路线已删除：它的草稿（设定结构不同）不再读进来，只留构思和补充要求；下次自动保存会覆盖
        st.premise = d.premise || ''
        st.conditions = d.conditions || ''
        ElMessage.info('「素材优先」路线已经删掉了，之前那份规划草稿不再使用，请重新规划')
      } else {
        delete d.mode
        Object.assign(st, blankState(), d)
        // 流程到骨架为止：停在点睛 / 大纲 / 审稿的旧草稿回到骨架
        if (['enrich', 'outline', 'review'].includes(st.step)) st.step = 'book'
      }
    }
  } catch {
    // 没有草稿
  }
  if (props.bookConfig && !st.bookConfig?.genre) st.bookConfig = { ...blankBookConfig(), ...props.bookConfig }
  if (st.tone?.trim()) {
    if (!st.bookConfig.style?.trim()) st.bookConfig.style = st.tone.trim().slice(0, 60)
    st.tone = ''
  }
  if (props.book && !st.book) st.book = { book: clone(props.book), issues: [] }
  if (props.initialPremise && !st.premise) st.premise = props.initialPremise
  ensureWorldSlots()
  watch(st, persist, { deep: true })
  try {
    const res = await getMaterialSources()
    const books = res.code === 0 ? res.data || [] : []
    sourceBooks.value = books.map((s) => s.book)
    libraryEmpty.value = res.code === 0 && !books.length
  } catch {
    // 拿不到来源书不影响规划
  }
  if (props.continueSignal) autoContinue()
})

let handledSignal = props.continueSignal
watch(() => props.continueSignal, (v) => {
  if (v && v !== handledSignal) autoContinue()
})

function goStep(key) {
  if (busy.value) return
  // 点步骤 = 进入那一步（还没生成过就自动生成；上一步改过会问要不要重新生成）
  if (key === 'settings' && st.idea) return run(enterSettings)
  if (key === 'book' && st.settings) return run(enterBook)
  if (key === 'apply' && st.settings && st.book) st.step = key
  if (key === 'idea') st.step = key
}

/* ---------- 进入一步时自动生成；上一步改过才问要不要重来（不覆盖手改） ---------- */
const settingsSig = computed(() => JSON.stringify([st.bookConfig, st.directions, st.premise.trim(), st.conditions.trim(), st.idea]))
const bookSig = computed(() => JSON.stringify([settingsSig.value, draft.value?.world, leadChars.value, st.volumePlan, st.volumeCount, st.pace]))
const askRegen = (msg) => ElMessageBox.confirm(msg, '上一步改过了', { confirmButtonText: '重新生成', cancelButtonText: '保留现在的', type: 'warning' })
  .then(() => true).catch(() => false)

async function enterSettings() {
  if (!st.settings) return runSettings()
  if (st.sig.settings && st.sig.settings !== settingsSig.value &&
      await askRegen('参数 · 灵感改过了，要按新的内容重新生成设定吗？（设定这一步手改过的内容会被覆盖）')) return runSettings()
  st.step = 'settings'
}

async function enterBook() {
  if (!st.book) return runBookAll()
  if (st.sig.book && st.sig.book !== bookSig.value &&
      await askRegen('设定（或参数 · 灵感）改过了，要按新的内容重新生成全书骨架和人物 / 元素吗？（骨架这一步手改过的内容会被覆盖）')) return runBookAll()
  st.step = 'book'
}

/** 骨架 + 按骨架配人物 / 元素（阶段表由骨架算出） */
async function runBookAll() {
  await runBook(false)
  await runCast()
}

async function runCast() {
  const lead = leadChars.value.map(clone)
  const data = await step('cast', () => planCast(props.novelId, { ...base(), settings: { ...draft.value, characters: lead, elements: [], stages: [] },
    book: bookObj.value }))
  draft.value.characters = [...lead, ...(data.characters || [])]
  draft.value.elements = data.elements || []
  if (data.stages?.length) draft.value.stages = data.stages
  st.castIssues = data.issues || []
  st.castAt = new Date().toLocaleString()
  snapshot('cast', castBasis.value)
}

const leadChars = computed(() => (draft.value?.characters || []).filter((c) => c.role === '主角'))
const castChars = computed(() => (draft.value?.characters || []).filter((c) => c.role !== '主角'))
function stageOf(n) {
  const r = bookObj.value && bookLayout(bookObj.value).find((x) => x.start <= (n || 1) && (n || 1) <= x.end)
  return r ? `${r.volumeTitle}·${r.title || '阶段'}，对手上限 ${r.tierMax || '—'}` : ''
}
function addElement(category) {
  draft.value.elements.push({ category, name: '', fields: {}, tier: 1, appearFrom: 1, sources: [], adapted: '' })
}

/* ---------- 每次 AI 生成 / 修改的依据（Markdown，AiBasis 渲染）+ 生成那一刻的快照 ---------- */
const clip = (t, n = 60) => { const x = String(t || '').trim().replace(/\s+/g, ' '); return x.length > n ? `${x.slice(0, n)}…` : x }
function inputsMd() {
  return [
    `- **写作参数**：${clip(configText(st.bookConfig), 120) || '（没填）'}（其中**文风**决定语气）`,
    `- **创作方向**：${st.directions.join('、') || '（没选）'}`,
    `- **选定的灵感**：${st.idea ? `《${st.idea.title}》${clip(st.idea.core || st.idea.hook, 50)}` : '（没选）'}`,
    `- **你的想法**：${clip(st.premise) || '（空）'}`,
    `- **补充要求**：${clip(st.conditions) || '（没填）'}`
  ]
}
function settingsMd() {
  const w = draft.value?.world
  if (!w) return '- **设定**：（还没有）'
  const lead = leadChars.value[0]
  return `- **设定**：世界规则 ${w.rules.filter(Boolean).length} 条、力量体系 ${(w.power?.realms || []).length} 个境界、` +
    `世界机制 ${(w.mechanics || []).length} 条、关键资源 ${(w.resources || []).length} 种、主角${lead ? `「${lead.name}」` : '（没有）'}` +
    '\n  - 只能用设定里有的规则和等级，不会自己发明'
}
const settingsBasis = computed(() => [...inputsMd(), '- 改了上面这些再进入这一步，会先问你要不要重新生成'].join('\n'))
const bookBasis = computed(() => [...inputsMd(), settingsMd(),
  `- **卷数**：${st.volumeCount ? `${st.volumeCount} 卷` : 'AI 决定（2~4 卷）'}；**节奏**：${PACES.find((x) => x.value === st.pace)?.label || '正常'}；` +
  `**全书约** ${plannedChapters.value} 章`,
  `- **分卷方向**：${st.volumePlan.filter((x) => x.trim()).map((x, i) => `第 ${i + 1} 卷 ${clip(x, 30)}`).join('；') || '（没写，AI 安排）'}`
].join('\n'))
const castBasis = computed(() => [
  `- **全书骨架**：${bookObj.value ? `${bookObj.value.volumes.length} 卷、${bookLayout(bookObj.value).length} 个阶段` : '（还没有）'}` +
  '\n  - 登场章节落在需要它的阶段里，对手量级不超过那个阶段的上限，骨架「必须发生」里点名的都要有卡',
  settingsMd(), `- **写作参数 / 灵感**：${clip(configText(st.bookConfig), 60) || '（没填）'}；${st.idea ? `《${st.idea.title}》` : ''}`
].join('\n'))
const volumeBasis = computed(() => [
  '- **这一卷原来的内容**和**前后卷的起止状态**（只改这一卷，其余卷不动）',
  '- **你写的要求**（弹框里的输入）', settingsMd(), `- **写作参数**：${clip(configText(st.bookConfig), 60) || '（没填）'}`
].join('\n'))
function partBasis(module, category) {
  const others = [module !== 'lead' && '主角', !['rules', 'note', 'power', 'abilities', 'mechanics', 'resources'].includes(module) && '世界设定']
  const lines = ['- **方向**和**参考已有内容**：在下面填 / 勾选', '- **其余设定**：其他各块都会带上，新内容要和它们一致' +
    (others.filter(Boolean).length ? `（含${others.filter(Boolean).join('、')}）` : '')]
  if (['characters', 'elements'].includes(module) && bookObj.value) {
    lines.push('- **全书骨架**：登场章节、对手量级按各阶段安排')
  }
  lines.push(`- **写作参数 / 灵感**：${clip(configText(st.bookConfig), 50) || '（没填）'}；${st.idea ? `《${st.idea.title}》` : ''}`)
  return lines.join('\n')
}
function snapshot(key, md) {
  st.runs[key] = { at: new Date().toLocaleString(), md }
}
/** 「上次生成实际用了什么」：生成那一刻的依据快照（之后改了输入也不变） */
const RunSnapshot = defineComponent({
  props: { runKey: { type: String, required: true } },
  setup(p) {
    const open = ref(false)
    return () => {
      const r = st.runs?.[p.runKey]
      if (!r) return null
      return h('div', { class: 'snapshot' }, [
        h(ElButton, { link: true, size: 'small', onClick: () => (open.value = !open.value) },
          () => (open.value ? '收起' : `查看上次生成（${r.at}）实际用了什么`)),
        open.value ? h(AiBasis, { md: r.md }) : null
      ])
    }
  }
})

function toggleDirection(d) {
  const i = st.directions.indexOf(d)
  if (i >= 0) st.directions.splice(i, 1)
  else st.directions.push(d)
}

/* ---------- 每一步 ---------- */
const base = () => {
  const b = { premise: st.premise.trim(), tone: st.tone.trim(), conditions: st.conditions.trim(), model: model.value,
    bookConfig: st.bookConfig, idea: st.idea || undefined }
  // 续规划时可能没有灵感：拿骨架的一句话当构思
  if (!b.premise && !st.idea) b.premise = bookObj.value?.logline || ''
  return b
}

const withBook = () => bookObj.value || undefined

function addUsage(u) {
  if (!u) return
  usage.calls++
  usage.promptTokens += u.promptTokens || 0
  usage.completionTokens += u.completionTokens || 0
  usage.source = model.value.source === 'api' ? 'api' : 'local'
}

/** 按钮调用：失败的提示已在 step() 里弹出，这里只吞掉 Promise 拒绝 */
function run(fn) {
  fn().catch(() => {})
}

async function step(name, fn) {
  busy.value = busy.value === 'auto' ? 'auto' : name
  try {
    const res = await fn()
    if (res.code !== 0) throw new Error(res.message)
    addUsage(res.data?.usage)
    return res.data
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '失败'), duration: 8000 })
    throw e
  } finally {
    if (busy.value !== 'auto') busy.value = ''
  }
}

/** 生成一批灵感；withFeedback = 带上作者写过的所有反馈（「说说原因再生成」）。每批记一份输入快照（「查看生成逻辑」） */
/* ---------- 架空素材篮：这一步的 AI 参考，只作补充 ---------- */
const MAX_PLAN_MATERIALS = 8
const matOn = (key) => !!st.materials.length && !!st.useMaterials[key]
const matIds = (key) => (matOn(key) ? st.materials.map((m) => m.id) : [])
const matPicker = reactive({ visible: false, query: '', auto: false })
function openMatPicker(recommend) {
  const query = recommend ? [configText(st.bookConfig), st.directions.join('、'), st.premise.trim(), st.conditions.trim()].filter(Boolean).join('；').slice(0, 500) : ''
  if (recommend && !st.bookConfig.genre && !st.bookConfig.tags?.length && !st.directions.length && !st.premise.trim()) {
    ElMessage.warning('先填题材 / 标签、创作方向或你的想法，才知道要推荐什么')
    return
  }
  Object.assign(matPicker, { visible: true, query, auto: recommend })
}
function applyMaterials(list) {
  if (list.length > MAX_PLAN_MATERIALS) ElMessage.warning(`最多 ${MAX_PLAN_MATERIALS} 条，只保留前 ${MAX_PLAN_MATERIALS} 条`)
  st.materials = list.slice(0, MAX_PLAN_MATERIALS).map((m) => ({ id: m.id, title: m.title, category: m.category,
    portability: m.profile?.portable?.portability || m.portability || 'adapt' }))
}
const matEditor = reactive({ visible: false, material: null })
async function openMaterial(id) {
  try {
    const res = await getMaterial(id)
    if (res.code !== 0) throw new Error(res.message)
    Object.assign(matEditor, { visible: true, material: res.data })
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取素材失败'))
  }
}

async function runIdea(withFeedback = false) {
  const inputs = { premise: st.premise.trim(), directions: [...st.directions], bookConfig: clone(st.bookConfig),
    conditions: st.conditions.trim() }
  const feedback = withFeedback ? clone(st.ideaFeedback) : []
  const materialIds = matIds('idea')
  const data = await step('idea', () => planIdea(props.novelId, { ...inputs, tone: '', feedback, count: 3, materialIds, model: model.value }))
  st.ideas = data.ideas || []
  st.ideaRuns.push({ at: new Date().toLocaleString(), inputs, feedback, materials: materialIds.length ? st.materials.map((m) => m.title) : [] })
  if (st.ideaRuns.length > 20) st.ideaRuns.splice(0, st.ideaRuns.length - 20)
  pickIdea(0)
}

const lastRun = computed(() => st.ideaRuns.at(-1) || null)
const regenOpen = ref(false)
const logicOpen = ref(false)
const regenForm = reactive({ dislike: '', want: '' })
function openRegen() {
  Object.assign(regenForm, { dislike: '', want: '' })
  regenOpen.value = true
}
async function submitRegen() {
  st.ideaFeedback.push({ at: new Date().toLocaleString(), dislike: regenForm.dislike.trim(), want: regenForm.want.trim(),
    rejected: (st.ideas || []).map((i) => `${i.title}：${i.hook || i.core}`.slice(0, 80)) })
  try {
    await runIdea(true)
    regenOpen.value = false
  } catch {
    // 提示已在 step() 里弹出；反馈已经记下了，可以直接再点一次
  }
}

const allDirections = computed(() => [...DIRECTIONS, ...st.customDirections.filter((d) => !DIRECTIONS.includes(d))])
function addDirection(d) {
  if (!d) return
  if (!st.customDirections.includes(d) && !DIRECTIONS.includes(d)) st.customDirections.push(d)
  if (!st.directions.includes(d)) st.directions.push(d)
}

/** 参数这一步的小帮手：kind = direction | style（7 字以内）| conditions（整理成一条条）| premise（润色） */
async function assistFn(kind, text) {
  const res = await planAssist(props.novelId, { kind, text, premise: st.premise.trim(), conditions: st.conditions.trim(), directions: [...st.directions],
    bookConfig: st.bookConfig, materialIds: matIds(kind), model: model.value })
  if (res.code !== 0) throw new Error(res.message)
  addUsage(res.data?.usage)
  return res.data.value
}

const CONFIG_LABELS = { platform: '平台', genre: '题材', tags: '标签', audience: '读者', sellingPoint: '卖点', pov: '人称', style: '文风',
  targetWords: '目标字数', chapterWords: '单章字数' }
const configText = (cfg) => Object.entries(CONFIG_LABELS)
  .map(([k, lab]) => {
    const v = cfg?.[k]
    const t = Array.isArray(v) ? v.join('、') : String(v || '').trim()
    return t ? `${lab}：${t}` : ''
  }).filter(Boolean).join('；')

function pickIdea(i) {
  st.ideaPick = i
  st.idea = st.ideas?.[i] ? { ...st.ideas[i] } : null
}

/** 全书骨架（在设定之后）：extend = 往后追加卷；regen = {index, instruction} 只重来这一卷 */
async function runBook(extend, regen = null) {
  const body = { ...base(), settings: draft.value, volumePlan: st.volumePlan.map((x) => x.trim()).filter(Boolean),
    volumeCount: st.volumeCount, pace: st.pace, book: extend || regen ? bookObj.value : undefined, regen: regen || undefined }
  const data = await step(regen ? 'regen' : 'book', () => planBook(props.novelId, body))
  st.book = { book: data.book, issues: data.issues || [] }
  if (!extend && !regen) st.bookTitle = data.book.titleOptions?.[0] || st.idea?.title || ''
  if (draft.value) draft.value.stages = data.stages || bookStages(data.book)   // 阶段表跟着骨架走
  if (!extend) Object.assign(st, { outline: null, review: null, originals: {} })
  if (!extend && !regen) {
    st.sig.book = bookSig.value
    snapshot('book', bookBasis.value)
  }
  st.step = 'book'
}

async function regenVolume(index, instruction) {
  regenIndex.value = index
  try {
    await runBook(false, { index, instruction })
    ElMessage.success(`第 ${index + 1} 卷已重新生成，其余卷没动`)
  } catch {
    // 提示已在 step() 里弹出
  } finally {
    regenIndex.value = -1
  }
}

/* 设定的单个模块重新生成（四种方式：给不给方向 × 参考不参考已有） */
const WORLD_PARTS = ['rules', 'note', 'cards', 'power', 'abilities', 'mechanics', 'resources']
const PART_LABELS = { rules: '世界规则', note: '世界观补充', cards: '世界背景卡', power: '力量体系', abilities: '能力',
  mechanics: '世界机制', resources: '关键资源', lead: '主角', characters: '人物' }
const partKey = (module, category) => (category ? `${module}:${category}` : module)
function partValue(module, category) {
  const d = draft.value
  if (!d) return null
  if (WORLD_PARTS.includes(module)) return d.world[module]
  if (module === 'elements') return d.elements.filter((e) => e.category === category)
  if (module === 'lead') return d.characters.filter((c) => c.role === '主角')
  if (module === 'characters') return d.characters.filter((c) => c.role !== '主角')
  return d[module]
}
const filledPart = (v) => (Array.isArray(v) ? v.length > 0 : v && typeof v === 'object' ? Object.values(v).some((x) => (Array.isArray(x) ? x.length : x)) : !!v)
function setPart(module, category, value) {
  const d = draft.value
  if (WORLD_PARTS.includes(module)) d.world[module] = value
  else if (module === 'elements') d.elements = [...d.elements.filter((e) => e.category !== category), ...value]
  else if (module === 'lead') d.characters = [...value, ...d.characters.filter((c) => c.role !== '主角')]
  else if (module === 'characters') d.characters = [...d.characters.filter((c) => c.role === '主角'), ...value]
  else d[module] = value
  if (module === 'power' || module === 'abilities') ensureWorldSlots()
}

async function regenPart(module, category, { direction, keep }) {
  const key = partKey(module, category)
  const before = clone(partValue(module, category) ?? null)
  partBusy.value = key
  try {
    const data = await step('part', () => planSettingsPart(props.novelId, { ...base(), settings: draft.value, book: withBook(),
      module, category: category || undefined, direction, keep }))
    setPart(module, category, data.value)
    st.partUndo[key] = before
    // 其他块也提到方向里的东西（如「法师塔」）：提醒一起改；用同样方向重来的那一块从提醒里去掉
    // 同一个方向连着改的：只从原来的提醒里划掉这一块（不再拿新结果去提醒，免得来回提醒）
    const sameDir = !!direction && st.related?.direction === direction
    const items = sameDir ? st.related.items.filter((x) => partKey(x.module, x.category) !== key) : data.related || []
    st.related = items.length ? { direction, items } : null
    ElMessage.success(`「${category ? ELEMENT_LABELS[category] : PART_LABELS[module]}」已重新生成，不满意可以撤销`)
  } catch {
    // 提示已在 step() 里弹出
  } finally {
    partBusy.value = ''
  }
}
function undoPart(module, category) {
  const key = partKey(module, category)
  if (!(key in st.partUndo)) return
  setPart(module, category, st.partUndo[key] ?? (module === 'note' ? '' : module === 'power' || module === 'abilities' ? null : []))
  delete st.partUndo[key]
}

async function runEnrich() {
  const data = await step('enrich', () => planEnrich(props.novelId, { ...base(), settings: draft.value, book: withBook(), excludeBooks: st.excludeBooks }))
  st.enrich = data
  st.enrichOriginals = {}
}

/** 采用一条点睛建议：字段追加到对象上（文字用「；」接在后面，列表合并），记下原样以便撤销 */
function adoptSuggestion(i) {
  const s = st.enrich.suggestions[i]
  const list = s.kind === 'character' ? draft.value.characters : draft.value.elements
  const obj = list[s.index]
  if (!obj || obj.name !== s.name) {
    ElMessage.warning(`设定里找不到「${s.name}」（可能改过名或删掉了）`)
    return
  }
  st.enrichOriginals[i] = clone(obj)
  const target = s.kind === 'character' ? obj : (obj.fields ||= {})
  for (const [k, v] of Object.entries(s.fields)) {
    if (Array.isArray(target[k]) || Array.isArray(v)) {
      target[k] = [...new Set([...(target[k] ? [].concat(target[k]) : []), ...[].concat(v)])]
    } else {
      target[k] = target[k] ? `${target[k]}；${v}` : v
    }
  }
  obj.sources = [...new Set([...(obj.sources || []), ...s.sources])]
}
function revertSuggestion(i) {
  const s = st.enrich.suggestions[i]
  const list = s.kind === 'character' ? draft.value.characters : draft.value.elements
  if (st.enrichOriginals[i]) list.splice(s.index, 1, st.enrichOriginals[i])
  delete st.enrichOriginals[i]
}

async function runSettings() {
  // 新书：设定在骨架之前生成，不带骨架；续规划（已写过章节）带上骨架，只补接下来要用的新东西
  const book = startIndex.value > 1 ? withBook() : undefined
  const data = await step('settings', () => planSettings(props.novelId, { ...base(), book }))
  const prev = draft.value
  Object.assign(st, { settings: data, enrich: null, enrichOriginals: {}, partUndo: {}, outline: null, review: null, originals: {}, step: 'settings' })
  // 设定只重做世界 + 主角：骨架那一步配好的配角 / 元素 / 阶段表先留着（重新生成骨架时会一起更新）
  if (prev) {
    draft.value.characters = [...draft.value.characters.filter((c) => c.role === '主角'), ...prev.characters.filter((c) => c.role !== '主角')]
    draft.value.elements = prev.elements || []
    draft.value.stages = prev.stages || []
  }
  if (bookObj.value && !draft.value.stages.length) draft.value.stages = bookStages(bookObj.value)
  st.sig.settings = settingsSig.value
  snapshot('settings', settingsBasis.value)
  ensureWorldSlots()
}

async function runOutline() {
  const data = await step('outline', () => planOutline(props.novelId, { ...base(), book: withBook(), settings: draft.value, count: CHAPTERS }))
  Object.assign(st, { outline: data, review: null, originals: {}, step: 'outline' })
}

async function runReview() {
  // 审稿看的是当前（可能改过的）大纲；已采用的修正先还原记录
  const data = await step('review', () => planReview(props.novelId, { ...base(), book: withBook(), settings: draft.value, outline: outline.value }))
  Object.assign(st, { review: data, originals: {}, step: 'review' })
}

function adoptRevision(r) {
  const c = chapterOf(r.index)
  if (!c || !r.revised) return
  st.originals[r.index] = { title: c.title, goal: c.goal, beats: [...(c.beats || [])], hook: c.hook }
  Object.assign(c, { title: r.revised.title || c.title, goal: r.revised.goal, beats: r.revised.beats?.length ? r.revised.beats : c.beats,
    hook: r.revised.hook || c.hook })
}
function revertRevision(i) {
  const c = chapterOf(i)
  if (c && st.originals[i]) Object.assign(c, st.originals[i])
  delete st.originals[i]
}
function adoptAll() {
  for (const r of st.review?.chapters || []) if (r.revised && !st.originals[r.index]) adoptRevision(r)
}

function addForeshadow() {
  const n = Math.max(0, ...outline.value.foreshadows.map((f) => Number(String(f.key).replace(/\D/g, '')) || 0)) + 1
  outline.value.foreshadows.push({ key: `P${n}`, text: '', plantIn: startIndex.value, payoffIn: 0 })
}

function autoLogger() {
  autoLog.value = []
  return (s) => autoLog.value.push(`${new Date().toLocaleTimeString()} ${s}`)
}

/** 一键全自动：灵感（没选就用第一个）→ 设定 → 骨架 → 人物 / 元素，停在「写进工作区」 */
async function runAuto() {
  busy.value = 'auto'
  const log = autoLogger()
  try {
    if (!st.idea) {
      log('生成故事灵感…')
      await runIdea()
      log(`用第一个灵感「${st.idea?.title || ''}」；生成设定…`)
    } else log(`用选定的灵感「${st.idea.title || ''}」；生成设定…`)
    await runSettings()
    log(`设定：主角「${leadChars.value[0]?.name || ''}」、${draft.value.world.rules.length} 条世界规则；搭全书骨架…`)
    await runBook(false)
    log(`骨架：${bookObj.value.volumes.length} 卷、${bookLayout(bookObj.value).length} 个阶段；按骨架配人物和元素…`)
    await runCast()
    log(`${castChars.value.length} 个配角、${draft.value.elements.length} 个元素。请检查后「写进工作区」`)
    st.step = 'apply'
  } catch (e) {
    log(`中断：${errorMessage(e, '失败')}（已完成的步骤保留在草稿里，可以从那一步继续）`)
  } finally {
    busy.value = ''
  }
}

/** 写作页「按全书骨架规划接下来 10 章」：骨架写完了先延长 → 补设定 → 大纲 → 审稿（修正全采用）→ 直接写进工作区 */
async function autoContinue() {
  handledSignal = props.continueSignal
  if (busy.value) return
  const bk = props.book || bookObj.value
  if (!bk) {
    ElMessage.warning('这个工作区还没有全书骨架，先做一次自动规划')
    return
  }
  st.book = { book: clone(bk), issues: [] }
  if (props.bookConfig) st.bookConfig = { ...blankBookConfig(), ...props.bookConfig }
  busy.value = 'auto'
  const log = autoLogger()
  try {
    const rows = bookLayout(st.book.book)
    if (!rows.length || rows.at(-1).end < startIndex.value) {
      log('全书骨架已经写完，往后延长 1~2 卷…')
      await runBook(true)
    }
    log(`补充第 ${startIndex.value} 章起要用的设定…`)
    await runSettings()
    log(`规划第 ${startIndex.value}~${startIndex.value + CHAPTERS - 1} 章…`)
    await runOutline()
    log('审稿…')
    await runReview()
    adoptAll()
    log('写进工作区…')
    Object.assign(applyOpts, { settings: true, outline: true, book: true, title: false })
    st.step = 'apply'
    await runApply(true)
    log('完成，回到「写作」页按大纲继续写')
  } catch (e) {
    log(`中断：${errorMessage(e, '失败')}（已完成的步骤保留在草稿里，可以从那一步继续）`)
  } finally {
    busy.value = ''
  }
}

/* ---------- 写进工作区 ---------- */
const pairText = (list) => (list || []).filter((x) => x.title).map((x) => `${x.title}：${x.desc || ''}`).join('\n')

function powerText(w) {
  const p = w.power || {}
  const a = w.abilities || {}
  const realms = (p.realms || []).filter((r) => r.name)
    .map((r, i) => `${i + 1}. ${r.name}${r.desc ? `：${r.desc}` : ''}${r.cost ? `（突破：${r.cost}）` : ''}`)
  return [p.intro, realms.length ? `境界（从低到高）：\n${realms.join('\n')}` : '', p.beyond && `更高层次：${p.beyond}`,
    a.innate && `先天：${a.innate}`, a.acquired && `后天：${a.acquired}`, a.dimensions?.length && `衡量能力：${a.dimensions.join('、')}`]
    .filter(Boolean).join('\n')
}

function settingsItems() {
  const d = draft.value
  const w = d.world
  const items = []
  const lore = (w.cards || []).filter((c) => c.title).map((c) => ({ name: c.title, detail: c.content }))
  if (w.rules.filter(Boolean).length || w.note || lore.length || w.power || w.mechanics?.length || w.resources?.length) {
    items.push({ kind: 'world', rules: w.rules.filter(Boolean), note: w.note, power: powerText(w), lore,
      mechanics: pairText(w.mechanics), resources: pairText(w.resources) })
  }
  for (const c of d.characters.filter((x) => x.name)) {
    items.push({ kind: 'character', appearFrom: c.appearFrom, sources: c.sources,
      fields: { name: c.name, tagline: c.tagline, role: c.role, personality: c.personality, goal: c.goal, fear: c.fear, secret: c.secret,
        abilities: c.abilities, background: c.background, arc: c.arc, relationToLead: c.relationToLead } })
  }
  for (const e of d.elements.filter((x) => x.name)) {
    items.push({ kind: e.category, appearFrom: e.appearFrom, sources: e.sources,
      fields: { name: e.name, ...e.fields, ...(e.tier ? { 量级: `${e.tier}` } : {}) } })
  }
  for (const s of d.stages.filter((x) => x.range)) items.push({ kind: 'stage', fields: { range: s.range, power: s.power, tierMax: s.tierMax, note: s.note } })
  return items
}

async function runApply(quiet = false) {
  const prev = busy.value
  busy.value = prev === 'auto' ? 'auto' : 'apply'
  try {
    const msgs = []
    if (applyOpts.settings) {
      const r = await props.applySettings(settingsItems())
      msgs.push(`设定写入 ${r.done} 条`)
      if (r.failed?.length) ElMessage.error({ message: r.failed.join('；'), duration: 8000 })
    }
    if (applyOpts.book || applyOpts.title) {
      const extra = { title: applyTitle.value, ...(applyOpts.book && bookObj.value ? { book: bookObj.value, bookConfig: st.bookConfig } : {}) }
      const res = await applyPlan(props.novelId, {}, applyOpts.title, extra)
      if (res.code !== 0) throw new Error(res.message)
      msgs.push(res.data.book ? '全书骨架和写作参数已保存' : '书名已更新')
    }
    st.appliedAt = new Date().toLocaleString()
    ElMessage.success(`已写进工作区：${msgs.join('，')}`)
    emit('applied')
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '写入失败'), duration: 8000 })
    if (quiet) throw e
  } finally {
    busy.value = prev === 'auto' ? 'auto' : ''
  }
}

// 书房左栏的竖排步骤：steps / 当前序号 / 跳转（reactive 里的 computed 访问时自动解包）
const nav = reactive({ steps, stepIndex, goStep, busy })
defineExpose({ autoContinue, nav })

/* ---------- 小组件 ---------- */
/** 设定块标题旁的「AI 重新生成」+「撤销」 */
const PartRegen = defineComponent({
  props: { module: { type: String, required: true }, category: { type: String, default: '' } },
  setup(p) {
    return () => {
      const key = partKey(p.module, p.category)
      const label = p.category ? ELEMENT_LABELS[p.category] : PART_LABELS[p.module]
      return h('span', { class: 'part-regen' }, [
        h(AiRegenButton, { label, text: p.category ? `重来${label}` : 'AI 重新生成', hasExisting: filledPart(partValue(p.module, p.category)),
          basis: partBasis(p.module, p.category),
          loading: partBusy.value === key, disabled: !!busy.value && partBusy.value !== key,
          onRun: (o) => regenPart(p.module, p.category, o) }),
        key in st.partUndo ? h(ElButton, { link: true, size: 'small', onClick: () => undoPart(p.module, p.category) }, () => '撤销') : null
      ])
    }
  }
})

const IssueList = defineComponent({
  props: { issues: { type: Array, default: () => [] } },
  setup(p) {
    const TYPE = { leak: '原书名词', tier: '量级', lead: '主角', hook: '钩子', opening: '开篇', early: '提前登场', foreshadow: '伏笔',
      invented: '发明设定',
      thin: '设定偏薄', book: '骨架', stage: '阶段' }
    return () => (p.issues?.length
      ? h('div', { class: 'issues' }, [h('b', '代码检查发现：'), ...p.issues.map((i) =>
        h('div', { class: 'warn' }, `· ${i.chapter ? `第${i.chapter}章 ` : ''}【${TYPE[i.type] || i.type}】${i.detail}`))])
      : null)
  }
})

const ChapterCard = defineComponent({
  props: { chapter: Object, foreshadows: Array, clocks: Array, opening: Boolean },
  setup(p) {
    const showLedger = ref(true)
    return () => {
      const c = p.chapter
      const fs = (c.foreshadow || []).map((r) => {
        const f = p.foreshadows.find((x) => x.key === r.key)
        return h(ElTag, { size: 'small', type: r.action === 'resolve' ? 'success' : r.action === 'plant' ? 'warning' : 'info', effect: 'plain',
          title: f?.text || '' }, () => `${ACTION_LABELS[r.action] || r.action} ${r.key}${f ? '：' + f.text.slice(0, 14) : ''}`)
      })
      const ks = (c.clocks || []).map((k) => {
        const x = p.clocks.find((y) => y.key === k)
        return h(ElTag, { size: 'small', type: 'danger', effect: 'plain' }, () => `⏳ ${x ? x.text.slice(0, 16) : k}`)
      })
      return h('div', { class: 'card' }, [
        h('div', { class: 'card-head' }, [
          h('b', `第 ${c.index} 章`),
          h(ElInput, { modelValue: c.title, size: 'small', style: 'width: 220px', 'onUpdate:modelValue': (v) => (c.title = v) }),
          p.opening ? h(ElTag, { size: 'small', type: 'danger' }, () => '开篇') : null,
          h('span', { class: 'muted' }, `出场：${(c.cast || []).join('、')}`),
          h(ElButton, { link: true, size: 'small', onClick: () => (showLedger.value = !showLedger.value) }, () => (showLedger.value ? '收起故事账本' : '故事账本'))
        ]),
        h(ElInput, { modelValue: c.goal, type: 'textarea', autosize: { minRows: 2 }, size: 'small', 'onUpdate:modelValue': (v) => (c.goal = v) }),
        h(ElInput, { modelValue: (c.beats || []).join('\n'), type: 'textarea', autosize: { minRows: 2 }, size: 'small', class: 'mt',
          placeholder: '节拍（一行一个）', 'onUpdate:modelValue': (v) => (c.beats = v.split('\n').map((x) => x.trim()).filter(Boolean)) }),
        h('div', { class: 'grid2 mt' }, [
          h(ElInput, { modelValue: c.hook, size: 'small', 'onUpdate:modelValue': (v) => (c.hook = v) }, { prepend: () => '章末钩子' }),
          p.opening ? h(ElInput, { modelValue: c.openingNote, size: 'small', 'onUpdate:modelValue': (v) => (c.openingNote = v) }, { prepend: () => '开篇要点' }) : null
        ]),
        showLedger.value ? h('div', { class: 'ledger' }, [h('span', { class: 'muted' }, '故事账本：'),
          ...(fs.length || ks.length ? [...fs, ...ks] : [h('span', { class: 'muted' }, '本章没有伏笔 / 定时事件')])]) : null
      ])
    }
  }
})
</script>

<style scoped>
.intro { font-size: 13px; line-height: 1.7; margin-bottom: 12px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.steps { margin-bottom: 14px; cursor: pointer; }
.steps :deep(.el-step__title) { font-size: 14px; white-space: nowrap; }
.pane { min-height: 200px; }
.ops { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 14px 0; }
.mt { margin-top: 8px; }
.section-head { display: flex; align-items: center; gap: 12px; margin: 16px 0 8px; }
.col-title { font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.idea-grid, .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.idea { cursor: pointer; }
.idea.on, .card.adopted { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.idea .hook { margin: 4px 0; font-size: 13px; }
.need-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.card { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px; margin-bottom: 10px; }
.card-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }
.grid2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.more { margin-top: 6px; }
.field-line { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.field-line .muted { width: 60px; flex-shrink: 0; }
.list-edit { width: 100%; }
.list-edit .row { display: flex; gap: 6px; margin-bottom: 4px; }
.source { margin-top: 6px; }
.issues { padding: 8px 10px; background: var(--el-color-warning-light-9); border-radius: 6px; font-size: 13px; }
.warn { color: var(--el-color-warning-dark-2); font-size: 13px; }
.overall { padding: 8px 10px; background: var(--el-fill-color-light); border-radius: 6px; margin-bottom: 10px; font-size: 13px; line-height: 1.7; }
.revised { margin-top: 6px; padding: 6px 8px; background: var(--el-color-success-light-9); border-radius: 6px; font-size: 13px; }
.ledger { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 8px; }
.summary { display: flex; flex-direction: column; gap: 10px; }
.auto-log { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.8; }
.basis { padding: 8px 10px; background: var(--el-fill-color-light); border-radius: 6px; line-height: 1.7; }
.basis .el-icon { margin-right: 4px; vertical-align: -2px; }
.gap { margin-left: 10px; }
.vol-no { width: 44px; flex-shrink: 0; }
.part-regen { display: inline-flex; align-items: center; gap: 2px; margin-left: 4px; }
.field-tip { margin-top: 2px; line-height: 1.6; }
.mech-tip { margin: -4px 0 8px; }
.idea-ops { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, 40%); gap: 12px; align-items: start; margin: 14px 0; }
.idea-ops .ops { margin: 0; }
.idea-basis { font-size: 12px; }
.fb-history { margin-top: 6px; font-size: 13px; line-height: 1.8; }
:deep(.el-descriptions__label) { width: 120px; white-space: nowrap; }
.fb-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
@media (max-width: 1100px) { .idea-ops { grid-template-columns: 1fr; } }
.related { margin-top: 8px; padding: 8px 10px; font-size: 13px; line-height: 1.7; background: var(--el-color-warning-light-9); border-radius: 6px; }
.snapshot { margin: 4px 0 6px; }
.snapshot .ai-basis { margin-top: 4px; }
.related-items { display: flex; flex-wrap: wrap; gap: 4px 14px; align-items: center; }
.mat-chip { cursor: pointer; }
.idea-mats { margin-top: 4px; font-size: 12px; color: var(--el-text-color-regular); }
</style>
