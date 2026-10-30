<template>
  <div class="plan-wizard">
    <div class="mode-bar">
      <el-radio-group v-model="st.mode" size="small" :disabled="!!busy" @change="onMode">
        <el-radio-button value="story">故事优先（不需要素材库）</el-radio-button>
        <el-radio-button value="material" :disabled="libraryEmpty">素材优先</el-radio-button>
      </el-radio-group>
      <span v-if="libraryEmpty" class="muted">素材库是空的，只能走故事优先</span>
    </div>
    <div class="intro muted">
      <template v-if="story">
        先定<b>写作参数</b>和<b>故事灵感</b>，AI 搭出<b>全书骨架</b>（分卷 + 阶段：目标、起止状态、必须发生的事），再从骨架推出设定（世界背景卡、力量体系、人物、势力地点…），
        最后按当前阶段规划 {{ CHAPTERS }} 章大纲和伏笔。<b>不用素材库也能完整走下来</b>；素材库里有合适的，可以在「素材点睛」给设定补细节。
      </template>
      <template v-else>
        从一句构思出发，AI 按素材库给你选配角色 / 世界观 / 势力地点物品 / 阶段表，再规划 {{ CHAPTERS }} 章大纲和伏笔、定时事件计划。
      </template>
      <b>只生成写小说用的规划，不写正文</b>；每一步都可以改、可以重来，最后确认才写进工作区（设定 → 设定页，大纲 → AI 构思页的已采用大纲，伏笔计划 → 故事账本「计划中」）。
      <template v-if="startIndex > 1">这本书已经写到第 {{ startIndex - 1 }} 章：规划第 {{ startIndex }}~{{ startIndex + CHAPTERS - 1 }} 章，只补新元素，不套开篇规则。</template>
      <template v-else>工作区还没有章节 = <b>开篇</b>：前 3 章按开篇规则规划（开场冲突、主角欲望与缺陷、核心卖点、人物逐个登场、章末钩子）。</template>
    </div>

    <el-steps :active="stepIndex" finish-status="success" simple class="steps">
      <el-step v-for="s in steps" :key="s.key" :title="s.title" @click="goStep(s.key)" />
    </el-steps>

    <!-- 故事优先 ① 写作参数 + 灵感 -->
    <div v-show="st.step === 'idea'" class="pane">
      <div class="section-head"><span class="col-title">写作参数</span><span class="muted">每一步都会带上；写正文时作为「作品定位」</span></div>
      <BookConfigForm v-model="st.bookConfig" />
      <div class="section-head"><span class="col-title">创作方向</span><span class="muted">可选，点选几个</span></div>
      <div class="chips">
        <el-check-tag v-for="d in DIRECTIONS" :key="d" :checked="st.directions.includes(d)" @change="toggleDirection(d)">{{ d }}</el-check-tag>
      </div>
      <el-form label-width="76px" size="small" class="mt">
        <el-form-item label="你的想法">
          <el-input v-model="st.premise" type="textarea" :rows="2" maxlength="500" show-word-limit
                    placeholder="一句话就行，如：法师，西幻冒险；也可以留空让 AI 按参数自由构思" />
        </el-form-item>
        <el-form-item label="基调"><el-input v-model="st.tone" maxlength="200" placeholder="可选，如：轻松幽默、热血、压抑悬疑" /></el-form-item>
        <el-form-item label="补充要求">
          <el-input v-model="st.conditions" type="textarea" :rows="2" maxlength="500" placeholder="可选，如：不要后宫；主角是女性" />
        </el-form-item>
        <el-form-item label="模型"><ModelPicker v-model="model" store-key="nan_novel.plan.model" /></el-form-item>
      </el-form>
      <div class="ops">
        <el-button type="primary" :loading="busy === 'idea'" :disabled="!!busy" @click="run(runIdea)">生成 3 个故事灵感</el-button>
        <el-button :loading="busy === 'auto'" :disabled="!!busy" @click="runAuto">一键全自动（停在写入前）</el-button>
        <el-button v-if="hasDraft" link type="danger" :disabled="!!busy" @click="resetDraft">清空这次规划</el-button>
        <span class="muted">约 5 次模型调用、2~3 分钟（大模型几分钱）</span>
      </div>
      <div v-if="autoLog.length" class="auto-log"><div v-for="(l, i) in autoLog" :key="i">{{ l }}</div></div>
      <template v-if="st.ideas?.length">
        <div class="section-head"><span class="col-title">选一个灵感</span><span class="muted">选中的可以直接改</span></div>
        <div class="idea-grid">
          <div v-for="(it, i) in st.ideas" :key="i" class="card idea" :class="{ on: st.ideaPick === i }" @click="pickIdea(i)">
            <b>{{ it.title || `灵感 ${i + 1}` }}</b>
            <div class="hook">{{ it.hook }}</div>
            <div class="muted">{{ it.core }}</div>
          </div>
        </div>
        <el-form v-if="st.idea" label-width="76px" size="small" class="mt">
          <el-form-item v-for="[k, lab] in IDEA_FIELDS" :key="k" :label="lab">
            <el-input v-model="st.idea[k]" type="textarea" :autosize="{ minRows: 1 }" maxlength="300" />
          </el-form-item>
        </el-form>
        <div class="ops">
          <el-button type="primary" :loading="busy === 'book'" :disabled="!!busy || !st.idea" @click="run(() => runBook(false))">下一步：搭全书骨架</el-button>
        </div>
      </template>
    </div>

    <!-- 故事优先 ② 全书骨架 -->
    <div v-show="st.step === 'book'" class="pane">
      <template v-if="bookObj">
        <IssueList :issues="st.book.issues" />
        <el-form label-width="84px" size="small" class="mt">
          <el-form-item label="书名">
            <el-select v-model="st.bookTitle" filterable allow-create default-first-option style="width: 300px">
              <el-option v-for="t in bookObj.titleOptions" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
        </el-form>
        <BookSkeleton :book="bookObj" />
        <div class="ops">
          <el-button :loading="busy === 'book'" :disabled="!!busy" @click="run(() => runBook(false))">重新生成骨架</el-button>
          <el-button v-if="startIndex > 1" :loading="busy === 'book'" :disabled="!!busy" @click="run(() => runBook(true))">往后延长 1~2 卷</el-button>
          <el-button type="primary" :loading="busy === 'settings'" :disabled="!!busy" @click="run(runSettings)">下一步：从骨架生成设定</el-button>
        </div>
      </template>
    </div>

    <!-- 素材优先 ① 构思 -->
    <div v-show="st.step === 'premise'" class="pane">
      <el-form label-width="84px">
        <el-form-item label="一句构思">
          <el-input v-model="st.premise" type="textarea" :rows="2" maxlength="500" show-word-limit
                    placeholder="如：法师喜欢冒险 / 废柴少年靠收破烂逆袭 / 被退婚的女主开了家侦探社" />
        </el-form-item>
        <el-form-item label="基调"><el-input v-model="st.tone" maxlength="200" placeholder="可选，如：轻松幽默、热血、压抑悬疑" /></el-form-item>
        <el-form-item label="补充要求">
          <el-input v-model="st.conditions" type="textarea" :rows="2" maxlength="500"
                    placeholder="可选，如：不要后宫；主角是女性；舞台是海岛群" />
        </el-form-item>
        <el-form-item label="模型"><ModelPicker v-model="model" store-key="nan_novel.plan.model" /></el-form-item>
        <el-form-item label="屏蔽来源书">
          <el-select v-model="st.excludeBooks" multiple filterable allow-create clearable placeholder="这些书的素材不用（可选）" style="width: 420px">
            <el-option v-for="b in sourceBooks" :key="b" :label="b" :value="b" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="ops">
        <el-button type="primary" :loading="busy === 'needs'" :disabled="!!busy || !st.premise.trim()" @click="run(runNeeds)">下一步：拆出需要的素材</el-button>
        <el-button :loading="busy === 'auto'" :disabled="!!busy || !st.premise.trim()" @click="runAuto">一键全自动（AI 自己选完，停在写入前）</el-button>
        <el-button v-if="hasDraft" link type="danger" :disabled="!!busy" @click="resetDraft">清空这次规划</el-button>
        <span class="muted">约 4 次模型调用、1~2 分钟（大模型几分钱）；检索素材在本机，不花 token</span>
      </div>
      <div v-if="autoLog.length" class="auto-log"><div v-for="(l, i) in autoLog" :key="i">{{ l }}</div></div>
    </div>

    <!-- 素材优先 ② 选素材 -->
    <div v-show="st.step === 'materials'" class="pane">
      <template v-if="st.needs">
        <div class="muted">AI 的理解：{{ st.needs.summary }}（{{ stageText }}）</div>
        <div class="section-head"><span class="col-title">检索需求</span><span class="muted">可以改检索词 / 数量、删掉、加一条，再「检索素材」</span></div>
        <div v-for="(n, i) in st.needs.needs" :key="i" class="need-row">
          <el-select v-model="n.category" size="small" style="width: 100px">
            <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
          </el-select>
          <el-input v-model="n.query" size="small" style="flex: 1" />
          <el-input-number v-model="n.count" size="small" :min="1" :max="6" style="width: 96px" />
          <span class="muted why">{{ n.why }}</span>
          <el-button link type="danger" size="small" @click="st.needs.needs.splice(i, 1)">删除</el-button>
        </div>
        <div class="ops">
          <el-button size="small" @click="st.needs.needs.push({ category: 'character', query: '', count: 3, role: '', why: '' })">加一条</el-button>
          <el-button type="primary" size="small" :loading="busy === 'retrieve'" :disabled="!!busy" @click="run(runRetrieve)">检索素材</el-button>
        </div>
      </template>
      <template v-if="st.groups">
        <div class="section-head"><span class="col-title">候选素材（已选 {{ pickedIds.length }}）</span>
          <span class="muted">勾选要用的；「相关度低」= 这条需求没有素材过相关度线，给了最接近的，自己判断</span></div>
        <div v-for="(g, gi) in st.groups" :key="gi" class="group">
          <div class="group-head">{{ categoryOf(g.need.category)?.label || '' }} · {{ g.need.query || g.need.why }}
            <span class="muted">{{ g.need.why }}</span>
            <span v-if="g.hidden" class="muted">（挡掉 {{ g.hidden }} 条超出阶段量级的）</span>
          </div>
          <div v-if="!g.items.length" class="muted">没有找到，设定里这部分由 AI 自己构思</div>
          <div v-for="it in g.items" :key="it.material.id" class="mat" :class="{ on: st.picked[it.material.id] }">
            <el-checkbox v-model="st.picked[it.material.id]" />
            <div class="mat-body">
              <b>{{ it.material.title }}</b>
              <el-tag v-if="it.from === 'weak'" size="small" type="warning" effect="plain">相关度低</el-tag>
              <el-tag v-if="it.score != null" size="small" effect="plain">相关 {{ it.score }}</el-tag>
              <el-tag v-if="it.tier" size="small" type="info" effect="plain">量级 {{ it.tier }}</el-tag>
              <el-tag v-if="it.fit === 'stretch'" size="small" type="warning" effect="plain">略超阶段</el-tag>
              <span v-if="it.material.sourceBook" class="muted">《{{ it.material.sourceBook }}》</span>
              <div class="muted">{{ it.material.summary }}</div>
            </div>
          </div>
        </div>
        <div class="ops">
          <el-button type="primary" :loading="busy === 'settings'" :disabled="!!busy" @click="run(runSettings)">
            下一步：用 {{ pickedIds.length }} 条素材生成设定草案
          </el-button>
        </div>
      </template>
    </div>

    <!-- 设定草案（两条路线共用） -->
    <div v-show="st.step === 'settings'" class="pane">
      <template v-if="draft">
        <IssueList :issues="st.settings.issues" />
        <el-form label-width="84px" class="mt">
          <el-form-item label="书名"><el-input v-model="draft.title" maxlength="40" style="width: 300px" /></el-form-item>
          <el-form-item label="世界规则">
            <div class="list-edit">
              <div v-for="(r, i) in draft.world.rules" :key="i" class="row">
                <el-input v-model="draft.world.rules[i]" size="small" />
                <el-button link type="danger" size="small" @click="draft.world.rules.splice(i, 1)">删</el-button>
              </div>
              <el-button link size="small" @click="draft.world.rules.push('')">+ 规则</el-button>
            </div>
          </el-form-item>
          <el-form-item label="世界观补充"><el-input v-model="draft.world.note" type="textarea" :rows="2" /></el-form-item>
        </el-form>

        <template v-if="story">
          <div class="section-head"><span class="col-title">世界背景卡（{{ (draft.world.cards || []).length }}）</span>
            <el-button link size="small" @click="(draft.world.cards ||= []).push({ title: '', content: '', tags: [] })">+ 背景卡</el-button></div>
          <div class="card-grid">
            <div v-for="(c, i) in draft.world.cards" :key="'w' + i" class="card">
              <div class="card-head"><el-input v-model="c.title" size="small" style="flex: 1" />
                <el-button link type="danger" size="small" @click="draft.world.cards.splice(i, 1)">删</el-button></div>
              <el-input v-model="c.content" type="textarea" :autosize="{ minRows: 2 }" size="small" />
            </div>
          </div>
          <div class="section-head"><span class="col-title">力量体系</span></div>
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
                <el-button link size="small" @click="(draft.world[k] ||= []).push({ title: '', desc: '' })">+ 一条</el-button></div>
              <div v-for="(x, i) in draft.world[k]" :key="k + i" class="need-row">
                <el-input v-model="x.title" size="small" style="width: 110px" />
                <el-input v-model="x.desc" size="small" style="flex: 1" />
                <el-button link type="danger" size="small" @click="draft.world[k].splice(i, 1)">删</el-button>
              </div>
            </div>
          </div>
        </template>

        <div class="section-head"><span class="col-title">人物（{{ draft.characters.length }}）</span>
          <el-button link size="small" @click="draft.characters.push(blankCharacter())">+ 人物</el-button></div>
        <div v-for="(c, i) in draft.characters" :key="'c' + i" class="card">
          <div class="card-head">
            <el-input v-model="c.name" size="small" style="width: 110px" placeholder="名字" />
            <el-select v-model="c.role" size="small" style="width: 110px">
              <el-option v-for="r in ROLE_LABELS" :key="r" :label="r" :value="r" />
            </el-select>
            <span class="muted">第</span><el-input-number v-model="c.appearFrom" size="small" :min="1" :max="999" controls-position="right" style="width: 80px" /><span class="muted">章登场</span>
            <el-input v-model="c.tagline" size="small" style="flex: 1" placeholder="一句话人设" />
            <el-button link type="danger" size="small" @click="draft.characters.splice(i, 1)">删除</el-button>
          </div>
          <div class="grid3">
            <el-input v-model="c.goal" size="small"><template #prepend>想要</template></el-input>
            <el-input v-model="c.fear" size="small"><template #prepend>缺陷 / 恐惧</template></el-input>
            <el-input v-model="c.secret" size="small"><template #prepend>秘密</template></el-input>
          </div>
          <el-collapse class="more"><el-collapse-item title="更多（性格、能力、背景、成长、与主角关系）">
            <div class="grid2">
              <el-input :model-value="c.personality.join('、')" size="small" @update:model-value="c.personality = splitList($event)"><template #prepend>性格</template></el-input>
              <el-input :model-value="c.abilities.join('、')" size="small" @update:model-value="c.abilities = splitList($event)"><template #prepend>能力</template></el-input>
              <el-input v-model="c.relationToLead" size="small"><template #prepend>与主角</template></el-input>
              <el-input v-model="c.arc" size="small"><template #prepend>成长弧光</template></el-input>
            </div>
            <el-input v-model="c.background" type="textarea" :rows="2" size="small" placeholder="背景故事" class="mt" />
          </el-collapse-item></el-collapse>
          <SourceLine :sources="c.sources" :adapted="c.adapted" :titles="materialTitles" />
        </div>

        <div class="section-head"><span class="col-title">势力 / 地点 / 物品 / 怪物（{{ draft.elements.length }}）</span></div>
        <div v-for="(e, i) in draft.elements" :key="'e' + i" class="card">
          <div class="card-head">
            <el-tag size="small">{{ ELEMENT_LABELS[e.category] }}</el-tag>
            <el-input v-model="e.name" size="small" style="width: 150px" />
            <span class="muted">量级</span><el-input-number v-model="e.tier" size="small" :min="1" :max="5" controls-position="right" style="width: 76px" />
            <span class="muted">第</span><el-input-number v-model="e.appearFrom" size="small" :min="1" :max="999" controls-position="right" style="width: 80px" /><span class="muted">章登场</span>
            <el-button link type="danger" size="small" @click="draft.elements.splice(i, 1)">删除</el-button>
          </div>
          <div v-for="(v, k) in e.fields" :key="k" class="field-line">
            <span class="muted">{{ FIELD_LABELS[k] || k }}：</span>
            <el-input :model-value="Array.isArray(v) ? v.join('、') : v" size="small"
                      @update:model-value="e.fields[k] = Array.isArray(v) ? splitList($event) : $event" />
          </div>
          <SourceLine :sources="e.sources" :adapted="e.adapted" :titles="materialTitles" />
        </div>

        <div class="section-head"><span class="col-title">阶段表</span>
          <span v-if="story && bookObj" class="muted">由全书骨架算出（改骨架后重新生成设定会更新）</span>
          <el-button link size="small" @click="draft.stages.push({ range: '', power: '', tierMax: 2, note: '' })">+ 阶段</el-button></div>
        <div v-for="(s, i) in draft.stages" :key="'s' + i" class="need-row">
          <el-input v-model="s.range" size="small" style="width: 90px" placeholder="1-10" />
          <el-input v-model="s.power" size="small" style="flex: 1" placeholder="主角实力" />
          <span class="muted">对手上限</span><el-input-number v-model="s.tierMax" size="small" :min="1" :max="5" style="width: 90px" />
          <el-input v-model="s.note" size="small" style="flex: 1" placeholder="备注" />
          <el-button link type="danger" size="small" @click="draft.stages.splice(i, 1)">删</el-button>
        </div>
        <div class="ops">
          <el-button :loading="busy === 'settings'" :disabled="!!busy" @click="run(runSettings)">重新生成设定</el-button>
          <el-button v-if="story" type="primary" :disabled="!!busy" @click="st.step = 'enrich'">下一步：素材点睛（可跳过）</el-button>
          <el-button :type="story ? '' : 'primary'" :loading="busy === 'outline'" :disabled="!!busy" @click="run(runOutline)">
            {{ story ? '跳过点睛，' : '下一步：' }}规划 {{ CHAPTERS }} 章
          </el-button>
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
      <template v-if="draft && outline">
        <div class="summary">
          <el-checkbox v-model="applyOpts.settings">
            设定：{{ draft.characters.length }} 个人物、{{ draft.elements.length }} 个元素、{{ draft.world.rules.length }} 条世界规则<template v-if="story">、{{ (draft.world.cards || []).length }} 张背景卡、力量体系</template>、{{ draft.stages.length }} 行阶段表（追加进设定页，不覆盖已有的）
          </el-checkbox>
          <el-checkbox v-model="applyOpts.outline">大纲：第 {{ outline.chapters[0]?.index }}~{{ outline.chapters.at(-1)?.index }} 章（替换这些章节的已采用大纲）+ {{ outline.foreshadows.length }} 条伏笔、{{ outline.clocks.length }} 个定时事件写进故事账本「计划中」</el-checkbox>
          <el-checkbox v-if="story && bookObj" v-model="applyOpts.book">全书骨架（{{ bookObj.volumes.length }} 卷）和写作参数：写完这 {{ CHAPTERS }} 章后，写作页可以一键按骨架规划接下来 {{ CHAPTERS }} 章</el-checkbox>
          <el-checkbox v-model="applyOpts.title">书名改成《{{ applyTitle }}》</el-checkbox>
        </div>
        <div class="ops">
          <el-button type="primary" :loading="busy === 'apply'" :disabled="!!busy || (!applyOpts.settings && !applyOpts.outline)" @click="runApply()">写进工作区</el-button>
          <span v-if="st.appliedAt" class="muted">已于 {{ st.appliedAt }} 写入过一次（再写会重复追加设定）</span>
        </div>
      </template>
      <div v-else class="muted">先完成设定草案和大纲</div>
    </div>

    <div v-if="autoLog.length && !['idea', 'premise'].includes(st.step)" class="auto-log mt"><div v-for="(l, i) in autoLog" :key="i">{{ l }}</div></div>
    <TokenUsageBar v-if="usage.calls" :usage="usage" class="mt" />
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'
import { ElButton, ElInput, ElMessage, ElMessageBox, ElTag } from 'element-plus'
import ModelPicker from '@/components/persona/ModelPicker.vue'
import TokenUsageBar from '@/components/ai/TokenUsageBar.vue'
import BookConfigForm from '@/components/novel/BookConfigForm.vue'
import BookSkeleton from '@/components/novel/BookSkeleton.vue'
import { MATERIAL_CATEGORIES, categoryOf, getMaterialSources } from '@/api/material'
import {
  ACTION_LABELS, DIRECTIONS, ELEMENT_LABELS, ROLE_LABELS, applyPlan, blankBookConfig, bookLayout, getPlanDraft, planBook,
  planEnrich, planIdea, planNeeds, planOutline, planRetrieve, planReview, planSettings, savePlanDraft
} from '@/api/novelPlan'
import { errorMessage } from '@/api/request'

const props = defineProps({
  novelId: { type: String, required: true },
  chapterCount: { type: Number, default: 0 },          // 已写章数（0 = 开篇）
  initialPremise: { type: String, default: '' },       // 新建工作区时带来的一句构思
  applySettings: { type: Function, required: true },   // (items) => Promise<{done, failed}>：写进设定编辑器并保存
  book: { type: Object, default: null },               // 工作区已保存的全书骨架（novel.book）
  bookConfig: { type: Object, default: null },         // 工作区已保存的写作参数（novel.bookConfig）
  continueSignal: { type: Number, default: 0 }         // 写作页「按骨架规划接下来 10 章」：变化一次 = 自动续规划一次
})
const emit = defineEmits(['applied'])

const CHAPTERS = 10
const MODE_KEY = 'nan_novel.plan.mode'
const STORY_STEPS = [['idea', '写作参数 · 灵感'], ['book', '全书骨架'], ['settings', '设定'], ['enrich', '素材点睛'],
  ['outline', `${CHAPTERS} 章大纲`], ['review', '审稿'], ['apply', '写进工作区']]
const MATERIAL_STEPS = [['premise', '构思'], ['materials', '选素材'], ['settings', '设定草案'], ['outline', `${CHAPTERS} 章大纲`],
  ['review', '审稿'], ['apply', '写进工作区']]
const IDEA_FIELDS = [['title', '暂定名'], ['core', '核心设定'], ['situation', '主角处境'], ['conflict', '核心冲突'], ['payoff', '爽点方向'], ['hook', '一句话卖点']]
const FIELD_LABELS = { stance: '立场', feature: '特点', kind: '类型', detail: '描述', effect: '作用', appearance: '外形',
  abilities: '能力', weakness: '弱点', habitat: '栖息地' }
const CHARACTER_LABELS = { tagline: '一句话人设', goal: '想要', fear: '缺陷 / 恐惧', secret: '秘密', background: '背景', arc: '成长弧光' }
const PHASES = { opening: '开篇', early: '前期', mid: '中期', late: '后期', any: '不限' }

const savedMode = () => {
  try {
    return localStorage.getItem(MODE_KEY) === 'material' ? 'material' : 'story'
  } catch {
    return 'story'
  }
}
const blankState = () => ({
  mode: savedMode(), step: savedMode() === 'story' ? 'idea' : 'premise',
  premise: '', tone: '', conditions: '', excludeBooks: [],
  // 故事优先
  bookConfig: blankBookConfig(), directions: [], ideas: null, ideaPick: -1, idea: null, book: null, bookTitle: '',
  enrich: null, enrichOriginals: {},
  // 素材优先
  needs: null, groups: null, picked: {},
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

const story = computed(() => st.mode === 'story')
const steps = computed(() => (story.value ? STORY_STEPS : MATERIAL_STEPS).map(([key, title]) => ({ key, title })))
const stepIndex = computed(() => Math.max(0, steps.value.findIndex((s) => s.key === st.step)))
const startIndex = computed(() => props.chapterCount + 1)
const opening = computed(() => startIndex.value === 1)
const draft = computed(() => st.settings?.draft)
const outline = computed(() => st.outline?.outline)
const bookObj = computed(() => st.book?.book)
const power = computed(() => draft.value.world.power)
const abilities = computed(() => draft.value.world.abilities)
/** 故事优先的设定一定有力量体系 / 能力两块（模型没给也留出空位，方便手填） */
function ensureWorldSlots() {
  const w = draft.value?.world
  if (!story.value || !w) return
  w.power ||= { intro: '', realms: [], beyond: '' }
  w.abilities ||= { innate: '', acquired: '', dimensions: [] }
}
const hasDraft = computed(() => !!(st.needs || st.settings || st.outline || st.ideas || st.book))
const stageText = computed(() => {
  const s = st.needs?.stage
  return s ? `${PHASES[s.phase] || s.phase}${s.tierMax ? `，对手不超过量级 ${s.tierMax}` : ''}` : ''
})
const allItems = computed(() => (st.groups || []).flatMap((g) => g.items))
const pickedIds = computed(() => (story.value ? [] : allItems.value.filter((it) => st.picked[it.material.id]).map((it) => it.material.id)))
const enrichTitles = computed(() => Object.fromEntries((st.enrich?.materials || []).map((m) => [m.id, `${m.title}${m.book ? `（《${m.book}》）` : ''}`])))
const materialTitles = computed(() => ({ ...Object.fromEntries(allItems.value.map((it) => [it.material.id, it.material.title])), ...enrichTitles.value }))
const applyTitle = computed(() => (story.value && st.bookTitle) || outline.value?.title || draft.value?.title || '')
const splitList = (s) => String(s || '').split(/[、,，;；]/).map((x) => x.trim()).filter(Boolean)
const chapterOf = (i) => outline.value?.chapters.find((c) => c.index === i)
const blankCharacter = () => ({ name: '', role: '配角', tagline: '', personality: [], goal: '', fear: '', secret: '', abilities: [],
  background: '', arc: '', relationToLead: '', appearFrom: startIndex.value, sources: [], adapted: '' })
const clone = (x) => JSON.parse(JSON.stringify(x))

/* ---------- 草稿：每步之后存一次，刷新不丢 ---------- */
let saveTimer = null
function persist() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => savePlanDraft(props.novelId, clone(st)).catch(() => {}), 800)
}

onMounted(async () => {
  try {
    const res = await getPlanDraft(props.novelId)
    if (res.code === 0 && res.data) {
      const d = res.data
      if (typeof d.step === 'number') {   // 旧草稿（只有素材优先，步骤是序号）
        d.mode = 'material'
        d.step = MATERIAL_STEPS[d.step]?.[0] || 'premise'
      }
      Object.assign(st, blankState(), d)
    }
  } catch {
    // 没有草稿
  }
  if (props.bookConfig && !st.bookConfig?.genre) st.bookConfig = { ...blankBookConfig(), ...props.bookConfig }
  if (props.book && !st.book) st.book = { book: clone(props.book), issues: [] }
  if (props.initialPremise && !st.premise) st.premise = props.initialPremise
  ensureWorldSlots()
  watch(st, persist, { deep: true })
  try {
    const res = await getMaterialSources()
    const books = res.code === 0 ? res.data || [] : []
    sourceBooks.value = books.map((s) => s.book)
    libraryEmpty.value = res.code === 0 && !books.length
    if (libraryEmpty.value && !story.value && !st.needs) onMode('story')
  } catch {
    // 拿不到来源书不影响规划
  }
  if (props.continueSignal) autoContinue()
})

let handledSignal = props.continueSignal
watch(() => props.continueSignal, (v) => {
  if (v && v !== handledSignal) autoContinue()
})

function onMode(m) {
  st.mode = m
  try {
    localStorage.setItem(MODE_KEY, m)
  } catch {
    // 记不住也没关系
  }
  if (!steps.value.some((s) => s.key === st.step)) st.step = steps.value[0].key
}

async function resetDraft() {
  try {
    await ElMessageBox.confirm('清空这次规划的所有步骤？（已经写进工作区的内容不受影响）', '清空', { type: 'warning' })
  } catch {
    return
  }
  Object.assign(st, blankState(), { mode: st.mode, step: steps.value[0].key, premise: st.premise, bookConfig: st.bookConfig })
  autoLog.value = []
}

function goStep(key) {
  const ready = {
    idea: true, premise: true, book: !!st.book, materials: !!st.needs, settings: !!st.settings, enrich: !!st.settings,
    outline: !!st.outline, review: !!st.review, apply: !!(st.settings && st.outline)
  }
  if (ready[key]) st.step = key
}

function toggleDirection(d) {
  const i = st.directions.indexOf(d)
  if (i >= 0) st.directions.splice(i, 1)
  else st.directions.push(d)
}

/* ---------- 每一步 ---------- */
const base = () => {
  const b = { premise: st.premise.trim(), tone: st.tone.trim(), conditions: st.conditions.trim(), stage: st.needs?.stage, model: model.value }
  if (story.value) {
    // 续规划时可能没有灵感：拿骨架的一句话当构思
    if (!b.premise && !st.idea) b.premise = bookObj.value?.logline || draft.value?.title || ''
    Object.assign(b, { mode: 'story', stage: undefined, bookConfig: st.bookConfig, idea: st.idea || undefined, book: bookObj.value || undefined })
  }
  return b
}

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

/* 故事优先 */
async function runIdea() {
  const data = await step('idea', () => planIdea(props.novelId, { premise: st.premise.trim(), directions: st.directions,
    bookConfig: st.bookConfig, tone: st.tone.trim(), conditions: st.conditions.trim(), count: 3, model: model.value }))
  st.ideas = data.ideas || []
  pickIdea(0)
}

function pickIdea(i) {
  st.ideaPick = i
  st.idea = st.ideas?.[i] ? { ...st.ideas[i] } : null
}

async function runBook(extend) {
  const body = { ...base(), book: extend ? bookObj.value : undefined }
  const data = await step('book', () => planBook(props.novelId, body))
  st.book = { book: data.book, issues: data.issues || [] }
  if (!extend) st.bookTitle = data.book.titleOptions?.[0] || st.idea?.title || ''
  Object.assign(st, { step: 'book' }, extend ? {} : { settings: null, enrich: null, enrichOriginals: {}, outline: null, review: null, originals: {} })
}

async function runEnrich() {
  const data = await step('enrich', () => planEnrich(props.novelId, { ...base(), settings: draft.value, excludeBooks: st.excludeBooks }))
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

/* 素材优先 */
async function runNeeds() {
  const body = { ...base(), stage: undefined }   // 拆需求时阶段由 Python 按工作区算（开篇 = 对手上限 2）
  const data = await step('needs', () => planNeeds(props.novelId, body))
  Object.assign(st, { needs: data, groups: null, picked: {}, settings: null, outline: null, review: null, originals: {}, step: 'materials' })
  if (!(data.needs || []).length) ElMessage.warning('AI 没拆出检索需求，可以手动加')
  else await runRetrieve()
}

async function runRetrieve() {
  const needs = st.needs.needs.filter((n) => n.query.trim())
  const data = await step('retrieve', () => planRetrieve(props.novelId, { needs, stage: st.needs.stage, excludeBooks: st.excludeBooks }))
  st.groups = data.groups || []
  // AI 预选：过了相关度线的都勾上，「相关度低」的不勾
  st.picked = Object.fromEntries(st.groups.flatMap((g) => g.items).map((it) => [it.material.id, it.from !== 'weak']))
  st.step = 'materials'
}

/* 共用 */
async function runSettings() {
  const variants = {}
  if (!story.value) for (const it of allItems.value) if (st.picked[it.material.id] && it.variant) variants[it.material.id] = it.variant
  const data = await step('settings', () => planSettings(props.novelId, { ...base(), materialIds: pickedIds.value, materialVariants: variants }))
  Object.assign(st, { settings: data, enrich: null, enrichOriginals: {}, outline: null, review: null, originals: {}, step: 'settings' })
  ensureWorldSlots()
}

async function runOutline() {
  const data = await step('outline', () => planOutline(props.novelId, { ...base(), settings: draft.value, materialIds: pickedIds.value, count: CHAPTERS }))
  Object.assign(st, { outline: data, review: null, originals: {}, step: 'outline' })
}

async function runReview() {
  // 审稿看的是当前（可能改过的）大纲；已采用的修正先还原记录
  const data = await step('review', () => planReview(props.novelId, { ...base(), settings: draft.value, outline: outline.value }))
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

/** 一键全自动：故事优先 = 灵感（没选就用第一个）→ 骨架 → 设定 → 大纲 → 审稿并采用修正（不做点睛）；
 *  素材优先 = AI 选素材（过了相关度线的全用）→ 设定 → 大纲 → 审稿并采用修正。都停在「写进工作区」 */
async function runAuto() {
  busy.value = 'auto'
  const log = autoLogger()
  try {
    if (story.value) {
      if (!st.idea) {
        log('生成故事灵感…')
        await runIdea()
        log(`用第一个灵感「${st.idea?.title || ''}」；搭全书骨架…`)
      } else log(`用选定的灵感「${st.idea.title || ''}」；搭全书骨架…`)
      await runBook(false)
      log(`骨架：${bookObj.value.volumes.length} 卷、${bookLayout(bookObj.value).length} 个阶段；生成设定…`)
      await runSettings()
      log(`设定：${draft.value.characters.length} 个人物、${draft.value.elements.length} 个元素、${(draft.value.world.cards || []).length} 张背景卡；规划 ${CHAPTERS} 章…`)
    } else {
      log('拆需求…')
      await runNeeds()
      log(`检索到 ${allItems.value.length} 条候选，用 ${pickedIds.value.length} 条；生成设定草案…`)
      await runSettings()
      log(`设定：${draft.value.characters.length} 个人物、${draft.value.elements.length} 个元素；规划 ${CHAPTERS} 章…`)
    }
    await runOutline()
    log('审稿…')
    await runReview()
    adoptAll()
    log(`采用了 ${Object.keys(st.originals).length} 章的修正。请检查后「写进工作区」`)
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
    ElMessage.warning('这个工作区还没有全书骨架，先用「故事优先」做一次规划')
    return
  }
  onMode('story')
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
    if (applyOpts.outline || applyOpts.title) {
      const o = { ...outline.value, title: applyTitle.value }
      const extra = story.value && applyOpts.book && bookObj.value ? { book: bookObj.value, bookConfig: st.bookConfig } : {}
      const res = await applyPlan(props.novelId, o, applyOpts.title, extra)
      if (res.code !== 0) throw new Error(res.message)
      msgs.push(`大纲 ${o.chapters.length} 章，账本计划中伏笔 ${res.data.planned} 条${res.data.book ? '，全书骨架已保存' : ''}`)
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

defineExpose({ autoContinue })

/* ---------- 小组件 ---------- */
const IssueList = defineComponent({
  props: { issues: { type: Array, default: () => [] } },
  setup(p) {
    const TYPE = { leak: '原书名词', tier: '量级', lead: '主角', hook: '钩子', opening: '开篇', early: '提前登场', foreshadow: '伏笔',
      thin: '设定偏薄', book: '骨架', stage: '阶段' }
    return () => (p.issues?.length
      ? h('div', { class: 'issues' }, [h('b', '代码检查发现：'), ...p.issues.map((i) =>
        h('div', { class: 'warn' }, `· ${i.chapter ? `第${i.chapter}章 ` : ''}【${TYPE[i.type] || i.type}】${i.detail}`))])
      : null)
  }
})

const SourceLine = defineComponent({
  props: { sources: { type: Array, default: () => [] }, adapted: { type: String, default: '' }, titles: { type: Object, default: () => ({}) } },
  setup(p) {
    return () => (p.sources?.length || p.adapted
      ? h('div', { class: 'muted source' }, `来源：${(p.sources || []).map((id) => p.titles[id] || `素材 ${id}`).join('、') || '（AI 原创）'}`
        + (p.adapted ? `｜改编：${p.adapted}` : ''))
      : h('div', { class: 'muted source' }, '来源：AI 原创'))
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
.mode-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 10px; }
.intro { font-size: 13px; line-height: 1.7; margin-bottom: 12px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.steps { margin-bottom: 14px; cursor: pointer; }
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
.why { width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.group { margin-bottom: 12px; }
.group-head { font-weight: 500; margin-bottom: 6px; }
.mat { display: flex; gap: 8px; padding: 6px 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; margin-bottom: 6px; }
.mat.on { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.mat-body .el-tag { margin-left: 6px; }
.card { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px; margin-bottom: 10px; }
.card-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }
.grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
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
</style>
