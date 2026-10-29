<template>
  <div class="adapt-panel">
    <div class="new">
      <h4>生成适配版本 <span class="muted">把原型放进另一个世界观：核心 / 锁定的特征由代码原样复制，AI 只写「在新世界里怎么体现」</span></h4>
      <el-alert v-if="!coreConfirmed" type="info" :closable="false" title="先在「原型卡」里确认核心 / 可变并保存，才能生成适配版本" />
      <el-form v-else label-width="84px" size="small">
        <el-form-item label="目标世界">
          <el-radio-group v-model="form.target">
            <el-radio-button value="novel">某个工作区的设定</el-radio-button>
            <el-radio-button value="text">手写世界观</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.target === 'novel'" label="工作区">
          <el-select v-model="form.novelId" filterable placeholder="选择小说工作区" class="w300">
            <el-option v-for="n in novels" :key="n.id" :label="n.title" :value="n.id" :disabled="!n.hasSettings" />
          </el-select>
          <span class="muted">（没保存过设定的工作区不能选）</span>
        </el-form-item>
        <el-form-item v-else label="世界观">
          <el-input v-model="form.world" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" maxlength="8000"
                    placeholder="如：蒸汽朋克的魔法王国，炼金术由行会垄断，平民不能识字……" />
        </el-form-item>
        <el-form-item label="作者期望">
          <el-input v-model="form.wish" maxlength="500" placeholder="可选：如：让他成为王国唯一的女性炼金师" />
        </el-form-item>
        <el-form-item label="模型">
          <ModelPicker v-model="model" />
          <el-button type="primary" :loading="adapting" class="ml" @click="adapt">生成</el-button>
        </el-form-item>
      </el-form>
    </div>

    <el-tabs v-if="list.length" v-model="currentId" type="card" class="tabs">
      <el-tab-pane v-for="a in list" :key="a.id" :name="String(a.id)">
        <template #label>
          {{ a.name }} <el-tag size="small" :type="a.status === 'CONFIRMED' ? 'success' : 'info'">{{ a.status === 'CONFIRMED' ? '已确认' : '草稿' }}</el-tag>
        </template>
      </el-tab-pane>
    </el-tabs>

    <div v-if="current" class="edit">
      <el-alert v-if="current.prototypeUpdated" type="warning" :closable="false" show-icon class="block"
                :title="`原型卡已有新版本（这个适配基于 v${current.baseVersion}）：可以用新版本重新生成`" />
      <el-alert :type="checks.ok ? 'success' : 'warning'" :closable="false" class="block"
                :title="checks.ok ? '检查通过：核心特征都有体现、锁定的没被改、没有原世界知识泄漏' : '检查发现问题（保存后重新检查）'">
        <div v-if="checks.missingManifest?.length">还没写「在新世界里怎么体现」的核心特征：{{ checks.missingManifest.join('；') }}</div>
        <div v-if="checks.changedLocked?.length">锁定的特征被改了：{{ checks.changedLocked.join('；') }}</div>
        <div v-if="checks.leaks?.length">出现了原世界专属的知识 / 术语：{{ checks.leaks.join('、') }}</div>
        <div v-if="checks.missingSituations?.length">没有行为规则的情境：{{ checks.missingSituations.join('、') }}</div>
      </el-alert>

      <el-tabs v-model="sub">
        <el-tab-pane label="适配内容" name="content">
          <el-form label-width="84px" size="small">
            <el-form-item label="名字"><el-input v-model="draft.name" maxlength="40" class="w300" /></el-form-item>
            <el-form-item label="新身份"><el-input v-model="draft.identity" type="textarea" autosize maxlength="300" /></el-form-item>
          </el-form>
          <h4>人物内核 <span class="muted">特征文字不能改（来自原型），只写在新世界里的具体体现</span></h4>
          <div v-for="c in draft.core" :key="c.traitId" class="core">
            <div class="ct">{{ c.text }} <el-tag v-if="c.locked" size="small" type="warning">锁定</el-tag></div>
            <el-input v-model="c.inWorld" type="textarea" autosize maxlength="300" placeholder="在新世界里怎么体现（具体行为 / 习惯）" />
          </div>
          <h4 v-if="draft.adaptedTraits?.length">改写的可变特征</h4>
          <div v-for="(a, i) in draft.adaptedTraits" :key="i" class="core">
            <div class="ct muted">原：{{ a.original }}</div>
            <el-input v-model="a.adapted" type="textarea" autosize maxlength="300" />
          </div>
          <h4>行为规则</h4>
          <div v-for="(r, i) in draft.rules" :key="i" class="row">
            <el-input v-model="r.situation" maxlength="100" class="w160" />
            <el-input v-model="r.reaction" maxlength="300" placeholder="怎么做" />
            <el-button link size="small" @click="draft.rules.splice(i, 1)">移除</el-button>
          </div>
          <el-button link size="small" @click="draft.rules.push({ situation: '', reaction: '', reasoning: '' })">+ 规则</el-button>
          <h4>专业能力映射</h4>
          <div v-for="(e, i) in draft.expertiseMap" :key="i" class="row">
            <el-input v-model="e.original" maxlength="120" placeholder="原世界" />
            <el-input v-model="e.inWorld" maxlength="200" placeholder="新世界里对应的" />
            <el-input v-model="e.constraint" maxlength="200" placeholder="限制" />
          </div>
          <el-form label-width="84px" size="small" class="mt">
            <el-form-item label="说话方式"><el-input v-model="draft.voice" type="textarea" autosize maxlength="400" /></el-form-item>
            <el-form-item label="他不知道">
              <el-select v-model="draft.unknowns" multiple filterable allow-create default-first-option class="full"
                         placeholder="原世界的知识 / 术语，正文里出现会被一致性检查标出" />
            </el-form-item>
            <el-form-item label="禁止">
              <el-select v-model="draft.forbidden" multiple filterable allow-create default-first-option class="full" placeholder="他绝不会做的事" />
            </el-form-item>
          </el-form>
          <h4>示例台词</h4>
          <div v-for="(e, i) in draft.examples" :key="i" class="row">
            <el-input v-model="e.context" maxlength="80" placeholder="情境" class="w160" />
            <el-input v-model="e.line" maxlength="200" />
            <el-tag v-if="e.fromChat" size="small">试聊</el-tag>
            <el-button link size="small" @click="draft.examples.splice(i, 1)">移除</el-button>
          </div>
          <el-button link size="small" @click="draft.examples.push({ context: '', line: '' })">+ 台词</el-button>
          <h4>角色卡字段 <span class="muted">用于工作区「主要角色」</span></h4>
          <el-form label-width="84px" size="small">
            <el-form-item v-for="k in CARD_FIELDS" :key="k.key" :label="k.label">
              <el-input v-model="draft.card[k.key]" type="textarea" autosize maxlength="400" />
            </el-form-item>
          </el-form>
          <el-collapse class="mt">
            <el-collapse-item title="写作时给模型看的人物内核（由代码生成，保存后更新）" name="brief">
              <pre class="brief">{{ current.content.brief }}</pre>
            </el-collapse-item>
          </el-collapse>
          <div class="save">
            <el-button type="primary" :loading="saving" @click="save">保存并检查</el-button>
            <el-button :disabled="current.status === 'CONFIRMED'" @click="confirm">确认</el-button>
            <el-select v-model="applyNovelId" size="small" filterable placeholder="用于工作区" class="w200">
              <el-option v-for="n in novels" :key="n.id" :label="n.title" :value="n.id" />
            </el-select>
            <el-input v-model="applyRole" size="small" placeholder="定位：主角 / 配角…" maxlength="40" class="w140" />
            <el-button :disabled="current.status !== 'CONFIRMED' || !applyNovelId" @click="apply">用于工作区</el-button>
            <span class="spacer" />
            <el-button link type="danger" @click="remove">删除</el-button>
          </div>
          <div v-if="current.applied?.length" class="muted mt">
            已用于：<span v-for="x in current.applied" :key="x.novelId">{{ novelTitle(x.novelId) }}（{{ x.role || '未定' }}，{{ x.at }}） </span>
          </div>
        </el-tab-pane>
        <el-tab-pane label="辨识度测试" name="test">
          <IdentityTest :adaptation="current" @update="replace" />
        </el-tab-pane>
        <el-tab-pane label="试聊" name="chat" lazy>
          <ChatPanel :adaptation-id="current.id" :name="current.name" :model="chatModel" />
          <ModelPicker v-model="chatModel" store-key="nan_novel.persona.chatModel" class="mt" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adaptPersona, applyAdaptation, confirmAdaptation, deleteAdaptation, listAdaptations, saveAdaptation
} from '@/api/persona'
import { listNovels } from '@/api/novelGen'
import { errorMessage } from '@/api/request'
import ModelPicker from './ModelPicker.vue'
import IdentityTest from './IdentityTest.vue'
import ChatPanel from './ChatPanel.vue'

const props = defineProps({ card: { type: Object, required: true } })

const CARD_FIELDS = [
  { key: 'tagline', label: '一句话人设' }, { key: 'role', label: '定位' }, { key: 'personality', label: '性格' },
  { key: 'speech', label: '说话方式' }, { key: 'goal', label: '目标' }, { key: 'fear', label: '恐惧' },
  { key: 'secret', label: '秘密' }, { key: 'bottomLine', label: '底线' }, { key: 'abilities', label: '能力' },
  { key: 'background', label: '背景' }, { key: 'arc', label: '成长' }
]

const list = ref([])
const currentId = ref('')
const novels = ref([])
const form = ref({ target: 'novel', novelId: '', world: '', wish: '' })
const model = ref({ source: 'api', configId: null, baseId: '' })
const chatModel = ref({ source: 'api', configId: null, baseId: '' })
const adapting = ref(false)
const saving = ref(false)
const sub = ref('content')
const draft = ref({})
const applyNovelId = ref('')
const applyRole = ref('')

const coreConfirmed = computed(() => !!props.card.content?.coreConfirmed)
const current = computed(() => list.value.find((a) => String(a.id) === currentId.value))
const checks = computed(() => current.value?.content?.checks || {})
const novelTitle = (id) => novels.value.find((n) => n.id === id)?.title || id

listNovels().then((res) => (novels.value = res.code === 0 ? res.data || [] : [])).catch(() => {})

async function load(selectId) {
  const res = await listAdaptations(props.card.id)
  list.value = res.code === 0 ? res.data : []
  if (selectId) currentId.value = String(selectId)
  else if (!current.value) currentId.value = list.value[0] ? String(list.value[0].id) : ''
}

watch(() => props.card.id, () => load(), { immediate: true })
watch(current, (a) => {
  if (!a) return
  const d = JSON.parse(JSON.stringify(a.content || {}))
  for (const k of ['core', 'adaptedTraits', 'rules', 'expertiseMap', 'unknowns', 'forbidden', 'examples', 'memories']) d[k] ||= []
  d.card ||= {}
  d.name ||= a.name
  draft.value = d
  applyNovelId.value = a.novelId || applyNovelId.value
  applyRole.value = d.card.role || applyRole.value
}, { immediate: true })

function replace(a) {
  const i = list.value.findIndex((x) => x.id === a.id)
  if (i >= 0) list.value.splice(i, 1, a)
}

function modelBody(m) {
  return m.source === 'local' ? { source: 'local', baseId: m.baseId } : m.source === 'gguf' ? { source: 'gguf' } : { source: 'api', configId: m.configId }
}

async function adapt() {
  const f = form.value
  if (f.target === 'novel' ? !f.novelId : !f.world.trim()) return ElMessage.warning('请选择工作区或写世界观')
  adapting.value = true
  try {
    const res = await adaptPersona(props.card.id, {
      novelId: f.target === 'novel' ? f.novelId : undefined, world: f.target === 'text' ? f.world : '', wish: f.wish, model: modelBody(model.value)
    })
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success('已生成适配版本（草稿），检查后确认')
    await load(res.data.id)
    sub.value = 'content'
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '生成失败'), duration: 8000 })
  } finally {
    adapting.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res = await saveAdaptation(current.value.id, draft.value)
    if (res.code !== 0) throw new Error(res.message)
    replace(res.data)
    ElMessage.success(res.data.content.checks?.ok ? '已保存，检查通过' : '已保存，检查发现问题，见上方')
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function confirm() {
  const res = await confirmAdaptation(current.value.id)
  if (res.code !== 0) return ElMessage.error(res.message)
  replace(res.data)
}

async function apply() {
  try {
    const res = await applyAdaptation(current.value.id, { novelId: applyNovelId.value, role: applyRole.value })
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(`已写入「${novelTitle(res.data.novelId)}」的人物内核：写作时进入${(res.data.role || '').includes('主角') ? '核心设定' : '相关人物卡片'}、规划和一致性检查`)
    await load(current.value.id)
  } catch (e) {
    ElMessage.error(errorMessage(e, '用于工作区失败'))
  }
}

async function remove() {
  await ElMessageBox.confirm('删除这个适配版本（和它的试聊记录）？已写进工作区的快照不受影响。', '删除', { type: 'warning' })
  await deleteAdaptation(current.value.id)
  currentId.value = ''
  await load()
}
</script>

<style scoped>
h4 { margin: 16px 0 8px; }
.muted { font-size: 12px; font-weight: normal; color: #909399; }
.block { margin-bottom: 10px; }
.tabs { margin-top: 16px; }
.w300 { width: 300px; }
.w200 { width: 200px; }
.w160 { width: 160px; flex-shrink: 0; }
.w140 { width: 140px; }
.ml { margin-left: 8px; }
.mt { margin-top: 10px; }
.full { width: 100%; }
.core { margin-bottom: 8px; }
.ct { margin-bottom: 4px; font-size: 13px; font-weight: 600; }
.row, .save { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.save { margin-top: 16px; padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter); }
.spacer { flex: 1; }
.brief { white-space: pre-wrap; font-size: 12px; background: #f5f7fa; padding: 8px; border-radius: 4px; }
</style>
