<template>
  <div class="inspire-page">
    <!-- 左：墙列表 -->
    <el-card class="walls" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">灵感墙</span>
          <el-button size="small" type="primary" :icon="Plus" @click="openWallDialog()">新建</el-button>
        </div>
      </template>
      <el-empty v-if="!walls.length" description="还没有灵感墙，先新建一面" :image-size="60" />
      <div
        v-for="w in walls"
        :key="w.id"
        class="wall-item"
        :class="{ active: w.id === wallId }"
        @click="selectWall(w.id)"
      >
        <div class="wall-name">{{ w.name }}</div>
        <div class="muted">
          {{ w.ideaCount || 0 }} 个思路 · {{ w.materialCount || 0 }} 条素材
          <template v-if="w.novelId"> · 关联《{{ novelTitle(w.novelId) }}》</template>
        </div>
      </div>
    </el-card>

    <!-- 右：当前墙 -->
    <el-card v-if="wall" class="main" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <span class="card-title">{{ wall.name }}</span>
            <span v-if="wall.novelId" class="muted"> · 关联工作区《{{ novelTitle(wall.novelId) }}》：构思会带上它的设定、大纲和已写章节</span>
            <span v-else class="muted"> · 没有关联工作区</span>
          </div>
          <div>
            <el-button size="small" @click="openWallDialog(wall)">设置</el-button>
            <el-button size="small" type="danger" plain @click="removeWall">删除</el-button>
          </div>
        </div>
      </template>

      <el-tabs v-model="tab">
        <!-- ===================== 构思 ===================== -->
        <el-tab-pane label="构思" name="compose">
          <el-form label-width="76px" class="composer">
            <el-form-item label="想写什么">
              <el-input
                v-model="form.request"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 5 }"
                maxlength="1000"
                show-word-limit
                placeholder="可以空着。如：主角去冒险，途中遇到一个改变他命运的人"
              />
            </el-form-item>
            <el-form-item label="生成什么">
              <el-radio-group v-model="form.target" size="small">
                <el-radio-button v-for="t in TARGETS" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="补充条件">
              <el-input v-model="form.conditions" maxlength="1000" placeholder="可以空着。如：北方冰原；不要修仙元素；主角是法师" />
            </el-form-item>
            <el-form-item label="故事阶段">
              <el-select v-model="stage.phase" size="small" style="width: 150px" @change="onPhase">
                <el-option v-if="wall?.novelId" label="自动（按工作区）" value="auto" />
                <el-option v-for="p in PHASES" :key="p.value" :label="p.label" :value="p.value" />
              </el-select>
              <template v-if="stage.phase !== 'auto' && stage.phase !== 'any'">
                <span class="label">对手上限</span>
                <el-select v-model="stage.tierMax" size="small" style="width: 190px">
                  <el-option v-for="t in TIERS" :key="t.value" :label="t.label" :value="t.value" :title="t.desc" />
                </el-select>
                <el-input v-model="stage.protagonist" size="small" maxlength="100" placeholder="主角现在的实力 / 处境（可空）" style="width: 240px; margin-left: 8px" />
              </template>
              <span class="muted tip-inline">
                {{ stage.phase === 'auto' ? '按工作区的阶段表 / 已写章数定量级上限' : stage.phase === 'any' ? '不按阶段过滤素材' : '和主角正面冲突的素材不超过这个量级，更强的最多带 2 条当背景' }}
              </span>
            </el-form-item>
            <el-form-item label="怎么跑">
              <el-radio-group v-model="form.mode" size="small">
                <el-radio-button value="auto" title="AI 自己拆需求、检索素材、出思路">一键出思路</el-radio-button>
                <el-radio-button value="review" title="拆需求、检索素材后先停下，你勾选素材后再生成">先看素材</el-radio-button>
              </el-radio-group>
              <span class="label">思路数</span>
              <el-input-number v-model="form.count" :min="1" :max="5" size="small" style="width: 90px" />
              <span class="label">模型</span>
              <el-select v-model="modelKey" size="small" style="width: 220px">
                <el-option v-for="c in configs" :key="'api' + c.id" :label="`大模型 · ${c.name}`" :value="`api:${c.id}`" />
                <el-option :label="llama ? `GGUF · ${llama.name}` : 'GGUF（llama.cpp 未运行）'" value="gguf" :disabled="!llama" />
                <el-option v-for="m in localModels" :key="'local' + m.id" :label="`本地 · ${m.name}`" :value="`local:${m.id}`" />
              </el-select>
              <el-button type="primary" :icon="MagicStick" :loading="!!busy" :disabled="!modelKey" @click="start">开始构思</el-button>
            </el-form-item>
            <div v-if="modelKey && !modelKey.startsWith('api')" class="muted tip-line">
              本地小模型一次写多个思路时格式不太稳定，效果不好可以换大模型（一次构思用 DeepSeek 大约几分钱）。
            </div>
          </el-form>

          <el-steps :active="stepIndex" finish-status="success" simple class="steps">
            <el-step title="拆需求" />
            <el-step title="检索素材" />
            <el-step title="生成思路" />
          </el-steps>
          <div v-if="busy" class="busy muted">{{ BUSY_TEXT[busy] }}</div>

          <!-- ① 需求拆解（可改） -->
          <div v-if="plan" class="block">
            <div class="block-head">
              <b>需求拆解</b>
              <span class="muted">{{ plan.summary }}</span>
              <el-checkbox v-model="plan.explore" size="small">随机探索</el-checkbox>
              <el-button size="small" link type="primary" :disabled="!!busy" @click="addNeed">+ 加一条</el-button>
              <el-button size="small" :disabled="!!busy || !plan.needs.length" @click="retrieve(true)">按这些需求检索</el-button>
            </div>
            <div v-if="plan.stage && plan.stage.phase !== 'any'" class="stage-line">
              <el-tag size="small" type="warning" effect="plain">{{ phaseLabel(plan.stage.phase) }}</el-tag>
              <span>对手上限 {{ tierLabel(plan.stage.tierMax) }}</span>
              <span v-if="plan.stage.protagonist" class="muted">· 主角：{{ plan.stage.protagonist }}</span>
              <span class="muted">（{{ STAGE_SOURCES[plan.stage.source] || '' }}<template v-if="plan.stage.chapter">，下一章第 {{ plan.stage.chapter }} 章</template>）</span>
              <el-button link size="small" type="primary" @click="editStage">修改</el-button>
            </div>
            <div v-for="(n, i) in plan.needs" :key="i" class="need">
              <el-select v-model="n.category" size="small" style="width: 110px">
                <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
              </el-select>
              <el-input v-model="n.query" size="small" placeholder="检索词，空格隔开" class="need-query" />
              <el-input-number v-model="n.count" :min="1" :max="6" size="small" style="width: 90px" />
              <el-select v-model="n.role" size="small" placeholder="用途" style="width: 116px" title="只有对手 / 场景 / 道具受量级上限约束；背景传说可以用更强的">
                <el-option v-for="r in ROLES" :key="r.value" :label="r.label" :value="r.value" />
              </el-select>
              <span class="muted need-why">{{ n.why }}</span>
              <el-button link type="danger" :icon="Delete" @click="plan.needs.splice(i, 1)" />
            </div>
          </div>

          <!-- ② 候选素材（可勾选） -->
          <div v-if="groups.length" class="block">
            <div class="block-head">
              <b>素材</b>
              <span class="muted">已选 {{ chosen.length }} 条（最多 24 条）；多版本素材可以选用法</span>
              <el-button size="small" link type="primary" @click="pickExtra">+ 从素材库加</el-button>
              <el-button size="small" type="primary" :disabled="!!busy || !chosen.length" @click="generate">用这些素材生成思路</el-button>
            </div>
            <div v-for="(g, gi) in groups" :key="gi" class="group">
              <div class="muted group-head">
                <template v-if="g.need.category">{{ categoryOf(g.need.category)?.label }} · {{ g.need.query }}</template>
                {{ g.need.why }}
                <template v-if="!g.items.length">（没找到合适的）</template>
                <template v-if="g.hidden">
                  · 已按阶段挡掉 {{ g.hidden }} 条超量级的
                  <el-button link size="small" type="primary" :disabled="!!busy" @click="lookAnyway(g)">也看看</el-button>
                </template>
                <template v-if="g.relaxed"> · 合适的不够，带了超一级的</template>
              </div>
              <div class="cands">
                <div v-for="c in g.items" :key="c.material.id" class="cand" :class="{ off: !c.checked }">
                  <el-checkbox v-model="c.checked" />
                  <div class="cand-body" @click="openMaterial(c.material.id)">
                    <div>
                      <b>{{ c.material.title }}</b>
                      <span class="muted">{{ c.material.sourceBook ? `《${c.material.sourceBook}》` : '手动' }}</span>
                      <el-tag v-if="c.from === 'wall'" size="small" type="warning">灵感墙</el-tag>
                      <el-tag v-else-if="c.from === 'explore'" size="small" type="success">随机</el-tag>
                      <span v-if="c.score != null" class="muted">相关度 {{ c.score }}</span>
                      <el-tag v-if="c.fit && FITS[c.fit]" size="small" :type="FITS[c.fit].type" effect="plain" :title="FITS[c.fit].tip">{{ FITS[c.fit].label }}</el-tag>
                      <el-tag v-else-if="c.tier" size="small" type="info" effect="plain" :title="tierLabel(c.tier)">量级 {{ c.tier }}</el-tag>
                    </div>
                    <div class="cand-summary">{{ c.material.summary }}</div>
                  </div>
                  <el-select v-if="isMultiVersion(c.material)" v-model="c.variant" size="small" class="variant" @click.stop>
                    <el-option label="让 AI 选" value="auto" />
                    <el-option v-for="v in c.material.source.variants" :key="v.id" :label="`只用 ${v.label || v.title}`" :value="String(v.id)" />
                    <el-option label="融合" value="blend" />
                  </el-select>
                </div>
              </div>
            </div>
          </div>

          <!-- ③ 思路 -->
          <div v-if="run" class="block">
            <div class="block-head">
              <b>思路</b>
              <span class="muted">{{ run.createTime }} · {{ run.usage?.model }} · {{ (run.usage?.promptTokens || 0) + (run.usage?.completionTokens || 0) }} tokens</span>
            </div>
            <div class="ideas">
              <IdeaCard
                v-for="(idea, i) in run.ideas"
                :ref="(el) => (cardRefs[i] = el)"
                :key="i"
                :idea="idea"
                :saved="!!idea.savedItemId"
                :can-apply="!!wall.novelId"
                :busy="ideaBusy[i] || ''"
                @collect="collect(idea)"
                @refine="(ask) => refine(i, ask)"
                @revise="(r) => revise(i, r)"
                @undo="undo(i)"
                @apply="openApply(idea)"
                @dismiss="dismiss(i)"
                @open-material="openMaterial"
                @pick-materials="pickFor"
              />
            </div>
          </div>
        </el-tab-pane>

        <!-- ===================== 墙上 ===================== -->
        <el-tab-pane :label="`墙上（${items.length}）`" name="wall">
          <el-empty v-if="!items.length" description="收藏的思路和钉的素材会出现在这里" :image-size="60" />
          <div class="wall-grid">
            <template v-for="it in items" :key="it.id">
              <IdeaCard
                v-if="it.type === 'idea'"
                :ref="(el) => (wallRefs[it.id] = el)"
                :idea="{ ...it.content, title: it.title, sourceRefs: it.sources }"
                saved
                :can-apply="!!wall.novelId"
                :busy="itemBusy[it.id] || ''"
                @refine="(ask) => refineItem(it, ask)"
                @revise="(r) => reviseItem(it, r)"
                @undo="undoItem(it)"
                @apply="openApply({ ...it.content, title: it.title })"
                @dismiss="removeItem(it)"
                @open-material="openMaterial"
                @pick-materials="pickFor"
              />
              <div v-else class="pinned">
                <div class="pinned-head">
                  <el-tag size="small" effect="plain">{{ categoryOf(it.material?.category)?.label || '素材' }}</el-tag>
                  <b @click="it.material && openMaterial(it.material.id)">{{ it.material?.title || it.title }}</b>
                  <span class="muted">{{ it.material?.sourceBook ? `《${it.material.sourceBook}》` : '' }}</span>
                  <el-button link type="danger" size="small" class="unpin" @click="removeItem(it)">取下</el-button>
                </div>
                <div class="cand-summary">{{ it.material ? it.material.summary : '（素材已删除）' }}</div>
              </div>
            </template>
          </div>
        </el-tab-pane>

        <!-- ===================== 逛素材 ===================== -->
        <el-tab-pane label="逛素材" name="browse">
          <div class="browse-bar">
            <el-radio-group v-model="browseCat" size="small" @change="browse">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="c in MATERIAL_CATEGORIES" :key="c.code" :value="c.code">{{ c.label }}</el-radio-button>
            </el-radio-group>
            <el-button size="small" :icon="Refresh" :loading="browsing" @click="browse">换一批</el-button>
            <span class="muted">跨书随机，每本书最多 2 条；不花 token</span>
          </div>
          <div class="browse-grid">
            <div v-for="m in browseList" :key="m.id" class="pinned">
              <div class="pinned-head">
                <el-tag size="small" effect="plain">{{ categoryOf(m.category)?.label }}</el-tag>
                <b @click="openMaterial(m.id)">{{ m.title }}</b>
                <span class="muted">{{ m.sourceBook ? `《${m.sourceBook}》` : '手动' }}</span>
                <el-button link size="small" type="primary" class="unpin" :disabled="pinnedIds.has(m.id)" @click="pin(m)">
                  {{ pinnedIds.has(m.id) ? '已钉' : '钉到墙上' }}
                </el-button>
              </div>
              <div class="cand-summary">{{ m.summary }}</div>
            </div>
          </div>
        </el-tab-pane>

        <!-- ===================== 构思记录 ===================== -->
        <el-tab-pane label="构思记录" name="runs" lazy>
          <el-table :data="runs" size="small" empty-text="还没有构思过" @row-click="loadRun">
            <el-table-column prop="createTime" label="时间" width="160" />
            <el-table-column label="生成什么" width="100">
              <template #default="{ row }">{{ targetLabel(row.request?.target) }}</template>
            </el-table-column>
            <el-table-column label="需求" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">{{ [row.request?.request, row.request?.conditions].filter(Boolean).join(' · ') || '（没写需求）' }}</template>
            </el-table-column>
            <el-table-column label="思路" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">{{ (row.ideas || []).map((i) => i.title).join('、') }}</template>
            </el-table-column>
          </el-table>
          <p class="muted">点一行可以回到当时的思路，继续收藏、细化或修改。</p>
        </el-tab-pane>
      </el-tabs>
    </el-card>
    <el-card v-else class="main" shadow="never">
      <el-empty description="选一面墙，或者新建一面" />
    </el-card>

    <!-- 墙设置 -->
    <el-dialog v-model="wallDlg.visible" :title="wallDlg.id ? '灵感墙设置' : '新建灵感墙'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="wallDlg.name" maxlength="60" placeholder="如：西幻法师冒险" /></el-form-item>
        <el-form-item label="关联工作区">
          <el-select v-model="wallDlg.novelId" clearable placeholder="不关联" style="width: 100%">
            <el-option v-for="n in novels" :key="n.id" :label="n.title" :value="n.id" />
          </el-select>
          <span class="muted">关联后，构思会带上这本书的设定、大纲和已写章节，并且可以把思路写进这个工作区</span>
        </el-form-item>
        <el-form-item label="屏蔽来源书">
          <BlockedBooksSelect v-model="wallDlg.excludeBooks" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="wallDlg.note" type="textarea" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="wallDlg.visible = false">取消</el-button>
        <el-button type="primary" :disabled="!wallDlg.name.trim()" @click="saveWallDlg">保存</el-button>
      </template>
    </el-dialog>

    <ApplyDialog v-model="apply.visible" :idea="apply.idea" :novel-id="wall?.novelId || ''" />
    <MaterialPicker
      v-model="picker.visible"
      pick-only
      title="选素材"
      :exclude-books="wall?.excludeBooks || []"
      @apply="onPicked"
    />
    <MaterialEditor v-model="editor.visible" :material="editor.material" @saved="() => {}" @deleted="() => {}" />
  </div>
</template>

<script setup>
import { computed, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, MagicStick, Plus, Refresh } from '@element-plus/icons-vue'
import IdeaCard from '@/components/inspire/IdeaCard.vue'
import ApplyDialog from '@/components/inspire/ApplyDialog.vue'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import MaterialEditor from '@/components/material/MaterialEditor.vue'
import BlockedBooksSelect from '@/components/material/BlockedBooksSelect.vue'
import { MATERIAL_CATEGORIES, TIERS, categoryOf, getMaterial, isMultiVersion, tierLabel } from '@/api/material'
import {
  FITS,
  PHASES,
  ROLES,
  STAGE_SOURCES,
  TARGETS,
  browseMaterials,
  deleteItem,
  deleteWall,
  generateInspiration,
  listItems,
  listRuns,
  listWalls,
  pinMaterial,
  planInspiration,
  refineIdea,
  retrieveMaterials,
  reviseIdea,
  saveItem,
  saveWall,
  phaseLabel,
  targetLabel,
  updateRun
} from '@/api/inspire'
import { listModels as listConfigs } from '@/api/aiModel'
import { isGenerationModel, listModels as listLocalModels, runningLlama } from '@/api/localModel'
import { listNovels } from '@/api/novelGen'
import { errorMessage } from '@/api/request'

const WALL_KEY = 'nan_novel.inspire.wall'
const MODEL_KEY = 'nan_novel.inspire.model'
const MAX_MATERIALS = 24
const BUSY_TEXT = {
  plan: '正在拆需求…',
  retrieve: '正在检索素材（本地，不花 token）…',
  generate: '正在生成思路，大模型约半分钟到一分钟，本地模型会更久…'
}

const walls = ref([])
const wallId = ref(null)
const wall = computed(() => walls.value.find((w) => w.id === wallId.value) || null)
const novels = ref([])
const items = ref([])
const tab = ref('compose')

const form = reactive({ request: '', target: 'adventure', conditions: '', mode: 'auto', count: 3 })
// 故事阶段：auto = 关联了工作区时由后端按阶段表 / 已写章数算；其他 = 作者指定（source = user）
const stage = reactive({ phase: 'any', tierMax: null, protagonist: '' })
const modelKey = ref(readLocal(MODEL_KEY) || '')
const configs = ref([])
const localModels = ref([])
const llama = ref(null)
const busy = ref('')
const plan = ref(null)
const groups = ref([])
const run = ref(null)
const ideaBusy = reactive({})
const itemBusy = reactive({})
const cardRefs = reactive({})
const wallRefs = reactive({})
const runs = ref([])
const browseCat = ref('')
const browseList = ref([])
const browsing = ref(false)
const wallDlg = reactive({ visible: false, id: null, name: '', novelId: '', excludeBooks: [], note: '' })
const apply = reactive({ visible: false, idea: null })
const picker = reactive({ visible: false, cb: null })
const editor = reactive({ visible: false, material: null })

function readLocal(k) {
  try {
    return localStorage.getItem(k)
  } catch {
    return null
  }
}
function writeLocal(k, v) {
  try {
    localStorage.setItem(k, v)
  } catch {
    // 隐私模式：不记住也能用
  }
}

const novelTitle = (id) => novels.value.find((n) => n.id === id)?.title || id
const stepIndex = computed(() => (run.value ? 3 : groups.value.length ? 2 : plan.value ? 1 : 0))
const chosen = computed(() => groups.value.flatMap((g) => g.items).filter((c) => c.checked).slice(0, MAX_MATERIALS))
const pinnedIds = computed(() => new Set(items.value.filter((i) => i.type === 'material').map((i) => i.materialId)))

function modelBody() {
  const k = modelKey.value
  if (k === 'gguf') return { source: 'gguf' }
  if (k.startsWith('local:')) return { source: 'local', baseId: k.slice(6) }
  return { source: 'api', configId: Number(k.slice(4)) || undefined }
}

async function call(p, fail) {
  const res = await p
  if (res.code !== 0) throw new Error(res.message || fail)
  return res.data
}

// ------------------------------------------------------------------ 墙

async function loadWalls() {
  try {
    walls.value = await call(listWalls(), '加载灵感墙失败')
    const saved = Number(readLocal(WALL_KEY))
    if (!walls.value.some((w) => w.id === wallId.value)) {
      wallId.value = walls.value.some((w) => w.id === saved) ? saved : walls.value[0]?.id ?? null
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载灵感墙失败'))
  }
}

function selectWall(id) {
  if (id === wallId.value) return
  wallId.value = id
  plan.value = null
  groups.value = []
  run.value = null
}

// 关联了工作区：阶段默认按工作区自动算；没关联：默认不限
watch(() => wall.value?.novelId, (nid) => {
  if (nid && stage.phase === 'any') stage.phase = 'auto'
  if (!nid && stage.phase === 'auto') stage.phase = 'any'
}, { immediate: true })

watch(wallId, (id) => {
  if (!id) return
  writeLocal(WALL_KEY, String(id))
  loadItems()
  loadRuns()
})

async function loadItems() {
  if (!wallId.value) return
  try {
    items.value = await call(listItems(wallId.value), '加载墙上的内容失败')
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载墙上的内容失败'))
  }
}

async function loadRuns() {
  try {
    runs.value = await call(listRuns(wallId.value), '加载构思记录失败')
  } catch {
    runs.value = []
  }
}

function openWallDialog(w) {
  Object.assign(wallDlg, {
    visible: true,
    id: w?.id || null,
    name: w?.name || '',
    novelId: w?.novelId || '',
    excludeBooks: [...(w?.excludeBooks || [])],
    note: w?.note || ''
  })
}

async function saveWallDlg() {
  try {
    const w = await call(saveWall({ id: wallDlg.id || undefined, name: wallDlg.name.trim(), novelId: wallDlg.novelId || '',
      excludeBooks: wallDlg.excludeBooks, note: wallDlg.note }), '保存失败')
    wallDlg.visible = false
    await loadWalls()
    wallId.value = w.id
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存灵感墙失败'))
  }
}

async function removeWall() {
  try {
    await ElMessageBox.confirm(`删除灵感墙「${wall.value.name}」？墙上的思路和构思记录会一起删除，素材库不受影响。`, '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await call(deleteWall(wallId.value), '删除失败')
    wallId.value = null
    await loadWalls()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除灵感墙失败'))
  }
}

// ------------------------------------------------------------------ 构思三步

/** 本次用的阶段：作者指定的优先，否则用拆需求时后端算出来的 */
function effectiveStage() {
  if (stage.phase !== 'auto') {
    return { phase: stage.phase, tierMax: stage.phase === 'any' ? null : stage.tierMax, protagonist: stage.protagonist.trim(), source: 'user' }
  }
  return plan.value?.stage || null
}
const reqBody = () => ({ request: form.request.trim(), target: form.target, conditions: form.conditions.trim(), model: modelBody(),
  stage: effectiveStage() || undefined })

function onPhase(v) {
  const p = PHASES.find((x) => x.value === v)
  if (p?.tierMax) stage.tierMax = p.tierMax
}

/** 把后端算出的阶段改成作者指定 */
function editStage() {
  const s = plan.value?.stage
  if (!s) return
  Object.assign(stage, { phase: s.phase, tierMax: s.tierMax, protagonist: s.protagonist || '' })
  ElMessage.info('已把阶段放到上面的「故事阶段」里，改好后点「按这些需求检索」')
}

/** 「也看看」：这一组不按阶段过滤，重新检索 */
async function lookAnyway(g) {
  const need = plan.value?.needs.find((n) => n.category === g.need.category && n.query === g.need.query)
  if (!need) return
  need.ignoreStage = true
  await retrieve(false)
}

async function start() {
  writeLocal(MODEL_KEY, modelKey.value)
  plan.value = null
  groups.value = []
  run.value = null
  busy.value = 'plan'
  try {
    const p = await call(planInspiration(wallId.value, reqBody()), '拆需求失败')
    plan.value = { summary: p.summary, needs: p.needs, explore: p.explore, stage: p.stage, usage: p.usage }
  } catch (e) {
    ElMessage.error(errorMessage(e, '拆需求失败'))
    busy.value = ''
    return
  }
  busy.value = ''
  await retrieve(form.mode === 'auto')
}

/** ② 检索；auto = 检索完直接生成（一键出思路），否则停下给作者勾选 */
async function retrieve(auto) {
  busy.value = 'retrieve'
  run.value = null
  try {
    const r = await call(retrieveMaterials(wallId.value, { needs: plan.value.needs, explore: plan.value.explore,
      stage: effectiveStage() || undefined }), '检索素材失败')
    groups.value = r.groups.map((g) => ({ ...g, items: g.items.map((c) => ({ ...c, checked: true })) }))
  } catch (e) {
    ElMessage.error(errorMessage(e, '检索素材失败'))
    busy.value = ''
    return
  }
  busy.value = ''
  if (!chosen.value.length) {
    ElMessage.warning('素材库里没找到合适的素材：改改检索词，或者先往素材库里多存一些素材')
    return
  }
  if (auto === true && form.mode === 'auto') await generate()
}

function variantsOf(list) {
  const out = {}
  for (const c of list) {
    if (c.variant && c.variant !== 'auto') out[c.material.id] = c.variant
  }
  return out
}

async function generate() {
  busy.value = 'generate'
  try {
    const list = chosen.value
    run.value = await call(generateInspiration(wallId.value, {
      ...reqBody(), count: form.count, plan: plan.value,
      materialIds: list.map((c) => c.material.id), materialVariants: variantsOf(list)
    }), '生成思路失败')
    loadRuns()
  } catch (e) {
    ElMessage.error(errorMessage(e, '生成思路失败'))
  } finally {
    busy.value = ''
  }
}

function addNeed() {
  plan.value.needs.push({ category: 'location', query: '', count: 3, role: 'scene', why: '手动添加' })
}

function pickExtra() {
  pickFor((list) => {
    const have = new Set(groups.value.flatMap((g) => g.items).map((c) => c.material.id))
    const extra = list.filter((m) => !have.has(m.id)).map((m) => ({ material: m, score: null, from: 'manual', checked: true,
      variant: isMultiVersion(m) ? m.variant || 'auto' : null }))
    if (extra.length) groups.value.push({ need: { category: '', query: '', why: '手动添加的素材' }, items: extra })
  })
}

// ------------------------------------------------------------------ 思路的出口

/** 本次构思的素材（细化 / 修改时一起交给模型） */
function runMaterials(r = run.value) {
  return { materialIds: (r?.materials || []).map((m) => m.materialId),
    materialVariants: Object.fromEntries((r?.materials || []).filter((m) => m.variant && m.variant !== 'auto').map((m) => [m.materialId, m.variant])) }
}

async function collect(idea) {
  try {
    const { sourceRefs, savedItemId, history, ...content } = idea
    const it = await call(saveItem({ wallId: wallId.value, type: 'idea', title: idea.title, content: { ...content, history: history || [] },
      sources: sourceRefs || [] }), '收藏失败')
    idea.savedItemId = it.id
    persistRun()
    ElMessage.success('已收藏到灵感墙')
    loadItems()
    loadWalls()
  } catch (e) {
    ElMessage.error(errorMessage(e, '收藏失败'))
  }
}

async function refine(i, ask) {
  const idea = run.value.ideas[i]
  ideaBusy[i] = 'refine'
  try {
    const r = await call(refineIdea({ wallId: wallId.value, idea, instruction: ask, target: idea.target, model: modelBody(), ...runMaterials() }), '细化失败')
    idea.detail = r.detail
    cardRefs[i]?.closeRefine()
    persistRun()
  } catch (e) {
    ElMessage.error(errorMessage(e, '细化失败'))
  } finally {
    ideaBusy[i] = ''
  }
}

/** 修改：去掉 / 换上的素材也算进本次可用的素材 */
function reviseMaterials(base, r) {
  const ids = base.materialIds.filter((id) => !r.removed.includes(id))
  r.added.forEach((m) => !ids.includes(m.id) && ids.push(m.id))
  const variants = { ...base.materialVariants }
  r.added.forEach((m) => m.variant && m.variant !== 'auto' && (variants[m.id] = m.variant))
  return { materialIds: ids, materialVariants: variants }
}

async function revise(i, r) {
  const idea = run.value.ideas[i]
  ideaBusy[i] = 'revise'
  try {
    const mats = reviseMaterials(runMaterials(), r)
    const res = await call(reviseIdea({ wallId: wallId.value, idea, instruction: r.instruction, target: idea.target,
      history: (idea.history || []).map((h) => h.instruction), model: modelBody(), ...mats }), '修改失败')
    const { history, savedItemId, ...prev } = idea
    run.value.ideas[i] = { ...res.idea, history: [...(history || []), { instruction: r.instruction, idea: prev }], savedItemId }
    if (r.added.length) mergeRunMaterials(r.added)
    cardRefs[i]?.resetRevise()
    persistRun()
  } catch (e) {
    ElMessage.error(errorMessage(e, '修改失败'))
  } finally {
    ideaBusy[i] = ''
  }
}

function mergeRunMaterials(added) {
  const have = new Set(run.value.materials.map((m) => m.materialId))
  added.filter((m) => !have.has(m.id)).forEach((m) => run.value.materials.push({ materialId: m.id, title: m.title,
    book: m.sourceBook || '', category: m.category, variant: m.variant || null }))
}

function undo(i) {
  const idea = run.value.ideas[i]
  const last = idea.history?.[idea.history.length - 1]
  if (!last) return
  run.value.ideas[i] = { ...last.idea, history: idea.history.slice(0, -1), savedItemId: idea.savedItemId }
  persistRun()
}

function dismiss(i) {
  run.value.ideas.splice(i, 1)
  persistRun()
}

async function persistRun() {
  try {
    await updateRun(run.value.id, run.value.ideas)
  } catch {
    // 只是记录，不影响当前页面
  }
}

// 墙上的思路：细化 / 修改直接存回墙上的条目
const itemMaterials = (it) => ({ materialIds: (it.sources || []).map((s) => s.materialId),
  materialVariants: Object.fromEntries((it.sources || []).filter((s) => s.variant && s.variant !== 'auto').map((s) => [s.materialId, s.variant])) })

async function refineItem(it, ask) {
  itemBusy[it.id] = 'refine'
  try {
    const idea = { ...it.content, title: it.title }
    const r = await call(refineIdea({ wallId: wallId.value, idea, instruction: ask, target: it.content?.target, model: modelBody(), ...itemMaterials(it) }), '细化失败')
    await call(saveItem({ id: it.id, content: { ...it.content, detail: r.detail } }), '保存失败')
    wallRefs[it.id]?.closeRefine()
    loadItems()
  } catch (e) {
    ElMessage.error(errorMessage(e, '细化失败'))
  } finally {
    itemBusy[it.id] = ''
  }
}

async function reviseItem(it, r) {
  itemBusy[it.id] = 'revise'
  try {
    const idea = { ...it.content, title: it.title }
    const mats = reviseMaterials(itemMaterials(it), r)
    const res = await call(reviseIdea({ wallId: wallId.value, idea, instruction: r.instruction, target: it.content?.target,
      history: (it.content?.history || []).map((h) => h.instruction), model: modelBody(), ...mats }), '修改失败')
    const { history, ...prev } = idea
    const { sourceRefs, ...next } = res.idea
    await call(saveItem({ id: it.id, title: next.title, content: { ...next, history: [...(history || []), { instruction: r.instruction, idea: prev }] },
      sources: sourceRefs || it.sources }), '保存失败')
    wallRefs[it.id]?.resetRevise()
    loadItems()
  } catch (e) {
    ElMessage.error(errorMessage(e, '修改失败'))
  } finally {
    itemBusy[it.id] = ''
  }
}

async function undoItem(it) {
  const last = it.content?.history?.[it.content.history.length - 1]
  if (!last) return
  try {
    await call(saveItem({ id: it.id, title: last.idea.title, content: { ...last.idea, history: it.content.history.slice(0, -1) } }), '退回失败')
    loadItems()
  } catch (e) {
    ElMessage.error(errorMessage(e, '退回失败'))
  }
}

async function removeItem(it) {
  try {
    await call(deleteItem(it.id), '移除失败')
    if (run.value) run.value.ideas.forEach((i) => i.savedItemId === it.id && delete i.savedItemId)
    loadItems()
    loadWalls()
  } catch (e) {
    ElMessage.error(errorMessage(e, '移除失败'))
  }
}

function openApply(idea) {
  apply.idea = idea
  apply.visible = true
}

function loadRun(row) {
  run.value = row
  plan.value = row.plan ? { ...row.plan } : null
  groups.value = []
  if (row.request) Object.assign(form, { request: row.request.request || '', target: row.request.target || 'free', conditions: row.request.conditions || '' })
  tab.value = 'compose'
}

// ------------------------------------------------------------------ 逛素材 / 钉素材 / 选素材

async function browse() {
  browsing.value = true
  try {
    browseList.value = await call(browseMaterials({ wallId: wallId.value, category: browseCat.value || undefined, count: 12 }), '加载失败')
  } catch (e) {
    ElMessage.error(errorMessage(e, '逛素材失败'))
  } finally {
    browsing.value = false
  }
}

async function pin(m) {
  try {
    await call(pinMaterial(wallId.value, m.id), '钉素材失败')
    ElMessage.success(`已把「${m.title}」钉到墙上，之后构思会优先用它`)
    loadItems()
    loadWalls()
  } catch (e) {
    ElMessage.error(errorMessage(e, '钉素材失败'))
  }
}

function pickFor(cb) {
  picker.cb = cb
  picker.visible = true
}

function onPicked(list) {
  picker.cb?.(list)
  picker.cb = null
}

async function openMaterial(id) {
  try {
    editor.material = await call(getMaterial(id), '打开素材失败')
    editor.visible = true
  } catch (e) {
    ElMessage.error(errorMessage(e, '打开素材失败（可能已被删除）'))
  }
}

watch(tab, (t) => {
  if (t === 'browse' && !browseList.value.length) browse()
  if (t === 'runs') loadRuns()
})

// ------------------------------------------------------------------ 模型 / 工作区列表

async function loadModels() {
  try {
    const res = await listConfigs()
    configs.value = res.code === 0 ? (res.data || []).filter((c) => c.status === 'VERIFIED') : []
  } catch {
    configs.value = []
  }
  runningLlama().then((l) => (llama.value = l))
  try {
    const res = await listLocalModels()
    localModels.value = res.code === 0 ? (res.data || []).filter(isGenerationModel) : []
  } catch {
    localModels.value = [] // AI 服务没开：本地模型不可选
  }
  const valid = (k) => (k?.startsWith('api:') && configs.value.some((c) => `api:${c.id}` === k)) || (k === 'gguf') ||
    (k?.startsWith('local:') && localModels.value.some((m) => `local:${m.id}` === k))
  if (!valid(modelKey.value)) {
    const active = configs.value.find((c) => c.active) || configs.value[0]
    modelKey.value = active ? `api:${active.id}` : ''
  }
}

async function loadNovels() {
  try {
    const res = await listNovels()
    novels.value = res.code === 0 ? res.data || [] : []
  } catch {
    novels.value = []
  }
}

onMounted(() => {
  loadModels()
  loadNovels()
})
onActivated(loadWalls)
</script>

<style scoped>
.stage-line { display: flex; align-items: center; gap: 8px; margin: 4px 0 8px; font-size: 13px; }
.tip-inline { margin-left: 8px; font-size: 12px; }
.inspire-page {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 12px;
  align-items: start;
}
.walls,
.main {
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
.wall-item {
  padding: 8px 10px;
  margin-bottom: 6px;
  border-radius: 6px;
  cursor: pointer;
}
.wall-item:hover {
  background: #f5f7fa;
}
.wall-item.active {
  background: #ecf5ff;
}
.wall-name {
  font-weight: 600;
  color: #303133;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.label {
  margin: 0 6px 0 14px;
  font-size: 12px;
  color: #606266;
}
.composer .el-button {
  margin-left: 12px;
}
.tip-line {
  margin: -6px 0 8px 76px;
}
.steps {
  margin: 4px 0 10px;
}
.busy {
  margin-bottom: 8px;
}
.block {
  margin-top: 14px;
}
.block-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.need {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.need-query {
  flex: 1;
}
.need-why {
  width: 160px;
}
.group {
  margin-bottom: 10px;
}
.group-head {
  margin-bottom: 4px;
}
.cands,
.browse-grid,
.wall-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 8px;
}
.wall-grid {
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
}
.cand,
.pinned {
  display: flex;
  gap: 8px;
  padding: 8px;
  background: #fafafa;
  border-radius: 6px;
  font-size: 13px;
}
.pinned {
  flex-direction: column;
  gap: 4px;
}
.cand.off {
  opacity: 0.5;
}
.cand-body {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.cand-summary {
  margin-top: 2px;
  line-height: 1.6;
  color: #606266;
}
.variant {
  width: 130px;
}
.ideas {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 10px;
}
.pinned-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pinned-head b {
  cursor: pointer;
}
.unpin {
  margin-left: auto;
}
.browse-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
@media (max-width: 900px) {
  .inspire-page {
    grid-template-columns: 1fr;
  }
}
</style>
