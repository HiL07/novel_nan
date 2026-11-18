<template>
  <div class="persona-editor">
    <el-alert v-if="draft.uncertain?.length" type="warning" :closable="false" class="block" title="需要作者判断">
      <ul class="plain">
        <li v-for="(u, i) in draft.uncertain" :key="i">{{ u }}</li>
      </ul>
    </el-alert>

    <el-form label-width="84px" size="small">
      <el-form-item label="一句话">
        <el-input v-model="draft.summary" maxlength="200" placeholder="这个人最本质的是什么" />
      </el-form-item>
    </el-form>

    <h4>特征 <span class="muted">核心 = 换了世界也不变；可变 = 适配时可以改；锁定 = 一个字都不改。出处由系统判定，改过的标为「作者」</span></h4>
    <TraitItem v-for="(t, i) in draft.traits" :key="t.id || i" :trait="t" @remove="draft.traits.splice(i, 1)" />
    <el-button size="small" :icon="Plus" @click="addTrait">添加特征</el-button>

    <h4>行为规则 <span class="muted">在这些情境下他会怎么做、为什么</span></h4>
    <div v-if="missingSituations.length" class="muted warn">还没有规则的情境：{{ missingSituations.join('、') }}</div>
    <div v-for="(r, i) in draft.rules" :key="r.id || i" class="rule">
      <div class="head">
        <el-select v-model="r.situation" size="small" filterable allow-create class="sit" placeholder="情境">
          <el-option v-for="s in SITUATIONS" :key="s" :label="s" :value="s" />
        </el-select>
        <el-tag size="small" :type="(PROVENANCE[r.provenance] || PROVENANCE.inferred).type">{{ (PROVENANCE[r.provenance] || PROVENANCE.inferred).label }}</el-tag>
        <span v-if="r.traitRefs?.length" class="muted">依据特征：{{ r.traitRefs.map(traitText).join('；') }}</span>
        <span class="spacer" />
        <el-button link size="small" type="danger" @click="draft.rules.splice(i, 1)">删除</el-button>
      </div>
      <el-input v-model="r.reaction" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="300" placeholder="他会怎么做" />
      <el-input v-model="r.reasoning" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="300" placeholder="为什么（内在逻辑）" class="mt" />
    </div>
    <el-button size="small" :icon="Plus" @click="addRule">添加规则</el-button>

    <h4>专业能力</h4>
    <el-form label-width="84px" size="small">
      <el-form-item v-for="k in EXPERTISE" :key="k.key" :label="k.label">
        <el-input v-model="draft.expertise[k.key]" maxlength="300" />
      </el-form-item>
      <el-form-item label="原世界专属">
        <el-select v-model="draft.expertise.worldBound" multiple filterable allow-create default-first-option class="full"
                   placeholder="只属于原世界的术语 / 知识（适配时不能出现，或要换成新世界的说法）" />
      </el-form-item>
    </el-form>

    <h4>说话方式</h4>
    <el-form label-width="84px" size="small">
      <el-form-item v-for="k in VOICE" :key="k.key" :label="k.label">
        <el-input v-model="draft.voice[k.key]" maxlength="200" />
      </el-form-item>
    </el-form>
    <div v-if="draft.lines?.length" class="lines">
      <div class="muted">原文台词（{{ draft.lines.length }}，已核实）</div>
      <q v-for="(l, i) in draft.lines.slice(0, showAllLines ? 200 : 6)" :key="i" :title="l.observation">{{ l.line }}</q>
      <el-button v-if="draft.lines.length > 6" link size="small" @click="showAllLines = !showAllLines">{{ showAllLines ? '收起' : '全部' }}</el-button>
    </div>

    <h4>成长弧线 / 辨识度</h4>
    <el-form label-width="84px" size="small">
      <el-form-item label="塑造经历">
        <div class="col">
          <div v-for="(f, i) in draft.arc.formative" :key="i" class="row">
            <el-input v-model="f.experience" placeholder="经历" maxlength="120" />
            <el-input v-model="f.change" placeholder="带来的改变" maxlength="120" />
            <el-button link size="small" @click="draft.arc.formative.splice(i, 1)">移除</el-button>
          </div>
          <el-button link size="small" @click="draft.arc.formative.push({ experience: '', change: '' })">+ 经历</el-button>
        </div>
      </el-form-item>
      <el-form-item label="可能成长"><el-input v-model="draft.arc.growth" maxlength="200" /></el-form-item>
      <el-form-item label="可能堕落"><el-input v-model="draft.arc.fall" maxlength="200" /></el-form-item>
      <el-form-item label="必须保留">
        <el-select v-model="draft.signature.mustKeep" multiple class="full" placeholder="辨识度：少了它就不是这个人">
          <el-option v-for="t in draft.traits" :key="t.id" :label="t.text" :value="t.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="容易丢的">
        <el-select v-model="draft.signature.easyToLose" multiple filterable allow-create default-first-option class="full"
                   placeholder="改写时最容易被写没的细节" />
      </el-form-item>
    </el-form>

    <h4>经历记忆 <span class="muted">试聊时按话题检索</span></h4>
    <div v-for="(m, i) in draft.memories" :key="i" class="row mem">
      <el-input v-model="m.scene" placeholder="场景" maxlength="120" />
      <el-input v-model="m.thought" placeholder="当时怎么想" maxlength="200" />
      <el-input v-model="m.action" placeholder="怎么做" maxlength="300" />
      <el-button link size="small" @click="draft.memories.splice(i, 1)">移除</el-button>
    </div>
    <el-button size="small" :icon="Plus" @click="draft.memories.push({ scene: '', thought: '', action: '' })">添加记忆</el-button>

    <div v-if="draft.holdout?.length" class="muted mt">另有 {{ draft.holdout.length }} 条证据留给辨识度测试的评委（不参与生成）</div>

    <div class="save">
      <el-checkbox v-model="draft.coreConfirmed">已确认核心 / 可变（确认后才能生成适配版本）</el-checkbox>
      <el-input v-model="note" size="small" maxlength="200" placeholder="这次改了什么（可选）" class="note" />
      <el-button type="primary" :loading="saving" @click="save">保存为新版本</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { PROVENANCE, SITUATIONS, saveVersion } from '@/api/persona'
import { errorMessage } from '@/api/request'
import TraitItem from './TraitItem.vue'

const props = defineProps({ cardId: { type: Number, required: true }, content: { type: Object, default: null } })
const emit = defineEmits(['saved'])

const EXPERTISE = [
  { key: 'knowledge', label: '知识' }, { key: 'methods', label: '方法' }, { key: 'intuition', label: '直觉' }, { key: 'logic', label: '推理习惯' }
]
const VOICE = [
  { key: 'style', label: '语言风格' }, { key: 'argumentation', label: '论证方式' }, { key: 'tendencies', label: '表达倾向' }, { key: 'emotion', label: '情绪表达' }
]

const draft = ref(normalize(props.content))
const note = ref('')
const saving = ref(false)
const showAllLines = ref(false)

watch(() => props.content, (c) => (draft.value = normalize(c)))

function normalize(c) {
  const d = JSON.parse(JSON.stringify(c || {}))
  d.traits ||= []
  d.rules ||= []
  d.expertise = { knowledge: '', methods: '', intuition: '', logic: '', worldBound: [], ...(d.expertise || {}) }
  d.voice = { style: '', argumentation: '', tendencies: '', emotion: '', ...(d.voice || {}) }
  d.arc = { formative: [], growth: '', fall: '', ...(d.arc || {}) }
  d.signature = { mustKeep: [], easyToLose: [], ...(d.signature || {}) }
  d.memories ||= []
  return d
}

const missingSituations = computed(() => SITUATIONS.filter((s) => !draft.value.rules.some((r) => (r.situation || '').includes(s))))
const traitText = (id) => draft.value.traits.find((t) => t.id === id)?.text || id

function nextId(list, prefix) {
  const n = Math.max(0, ...list.map((x) => parseInt(String(x.id || '').replace(/\D/g, ''), 10) || 0))
  return `${prefix}${n + 1}`
}

function addTrait() {
  draft.value.traits.push({ id: nextId(draft.value.traits, 't'), layer: 'personality', text: '', kind: 'adaptable', locked: false })
}

function addRule() {
  draft.value.rules.push({ id: nextId(draft.value.rules, 'r'), situation: missingSituations.value[0] || '', reaction: '', reasoning: '', traitRefs: [] })
}

async function save() {
  const d = draft.value
  d.traits = d.traits.filter((t) => (t.text || '').trim())
  d.rules = d.rules.filter((r) => (r.reaction || '').trim())
  saving.value = true
  try {
    const res = await saveVersion(props.cardId, d, note.value)
    if (res.code !== 0) throw new Error(res.message)
    note.value = ''
    ElMessage.success(`已保存为 v${res.data.currentVersion}`)
    emit('saved', res.data)
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
h4 { margin: 18px 0 8px; }
.muted { font-size: 12px; font-weight: normal; color: var(--el-text-color-secondary); }
.warn { color: var(--el-color-warning); margin-bottom: 6px; }
.block { margin-bottom: 12px; }
.plain { margin: 0; padding-left: 18px; }
.rule { padding: 8px 10px; margin-bottom: 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }
.head, .row, .save { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.head { margin-bottom: 6px; }
.sit { width: 180px; }
.spacer { flex: 1; }
.mt { margin-top: 6px; }
.full { width: 100%; }
.col { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.mem { margin-bottom: 6px; }
.lines q { display: inline-block; margin: 4px 8px 0 0; padding: 2px 8px; font-size: 13px; background: var(--el-color-success-light-9); border-radius: 4px; }
.save { position: sticky; bottom: 0; margin-top: 20px; padding: 10px 0; background: var(--el-bg-color); border-top: 1px solid var(--el-border-color-lighter); }
.note { width: 260px; }
</style>
