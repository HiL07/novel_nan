<template>
  <!-- 架空档案编辑（素材选择的卡片 / 素材编辑共用）：每一项都能手改；示例里的原作专名实时标红 -->
  <div class="pe">
    <div class="pe-row">
      <span class="pe-label">可移植度</span>
      <el-radio-group v-model="p.portability" size="small" @change="emitChange">
        <el-radio-button value="direct">直接可用</el-radio-button>
        <el-radio-button value="adapt">需要适配</el-radio-button>
      </el-radio-group>
      <span class="muted">有「依赖设定」类绑定时 AI 判为需要适配，可以改</span>
    </div>

    <div class="pe-label">可移植内核</div>
    <el-input v-model="p.core" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" maxlength="160" show-word-limit @input="emitChange" />

    <div class="pe-label">
      原作绑定
      <el-button link type="primary" size="small" @click="add('bindings', { term: '', kind: '专名', note: '' })">添加</el-button>
    </div>
    <div v-for="(b, i) in p.bindings" :key="'b' + i" class="pe-line">
      <el-input v-model="b.term" size="small" placeholder="原文里的词" style="width: 130px" @input="emitChange" />
      <el-select v-model="b.kind" size="small" style="width: 100px" @change="emitChange">
        <el-option label="专名" value="专名" />
        <el-option label="依赖设定" value="依赖设定" />
      </el-select>
      <el-input v-model="b.note" size="small" placeholder="绑定在原作的什么上" @input="emitChange" />
      <el-button link type="danger" size="small" @click="remove('bindings', i)">删</el-button>
    </div>
    <div v-if="!p.bindings.length" class="muted">没有绑定原作的词</div>

    <div class="pe-label">
      叙事用途
      <el-button link type="primary" size="small" @click="add('uses', '')">添加</el-button>
    </div>
    <div v-for="(u, i) in p.uses" :key="'u' + i" class="pe-line">
      <el-input v-model="p.uses[i]" size="small" @input="emitChange" />
      <el-button link type="danger" size="small" @click="remove('uses', i)">删</el-button>
    </div>

    <div class="pe-label">
      换世界时替换
      <el-button link type="primary" size="small" @click="add('replace', { from: '', to: '' })">添加</el-button>
    </div>
    <div v-for="(r, i) in p.replace" :key="'r' + i" class="pe-line">
      <el-input v-model="r.from" size="small" placeholder="原作里的东西" style="width: 160px" @input="emitChange" />
      <span class="arrow">→</span>
      <el-input v-model="r.to" size="small" placeholder="换成什么样的东西" @input="emitChange" />
      <el-button link type="danger" size="small" @click="remove('replace', i)">删</el-button>
    </div>

    <div class="pe-label">
      一定保留
      <el-button link type="primary" size="small" @click="add('keep', '')">添加</el-button>
    </div>
    <div v-for="(k, i) in p.keep" :key="'k' + i" class="pe-line">
      <el-input v-model="p.keep[i]" size="small" @input="emitChange" />
      <el-button link type="danger" size="small" @click="remove('keep', i)">删</el-button>
    </div>

    <template v-if="p.nodeMap">
      <div class="pe-label">节点对应（整张关系网一起架空）</div>
      <div v-for="(n, i) in p.nodeMap" :key="'n' + i" class="pe-line">
        <span class="node-title" :title="n.title">{{ n.title || n.node }}</span>
        <el-input v-model="n.role" size="small" placeholder="通用角色 / 功能" style="width: 160px" @input="emitChange" />
        <span class="arrow">→</span>
        <el-input v-model="n.replaceWith" size="small" placeholder="在示例世界里换成" @input="emitChange" />
      </div>
      <div class="pe-label">
        通用联动规则
        <el-button link type="primary" size="small" @click="add('rules', { if: '', then: '' })">添加</el-button>
      </div>
      <div v-for="(r, i) in p.rules" :key="'ru' + i" class="pe-line">
        <el-input v-model="r.if" size="small" placeholder="某类节点怎么变" @input="emitChange" />
        <span class="arrow">→</span>
        <el-input v-model="r.then" size="small" placeholder="其他节点跟着怎么变" @input="emitChange" />
        <el-button link type="danger" size="small" @click="remove('rules', i)">删</el-button>
      </div>
    </template>

    <div class="pe-label">
      架空示例
      <el-input v-model="p.exampleWorld" size="small" placeholder="示例世界" style="width: 200px; margin-left: 8px" @input="emitChange" />
    </div>
    <el-input v-model="p.example" type="textarea" :autosize="{ minRows: 5, maxRows: 14 }" maxlength="1200" show-word-limit @input="emitChange" />
    <div v-if="leaks.length" class="leaks">
      示例里还有原作专名：<el-tag v-for="t in leaks" :key="t" size="small" type="danger" effect="plain">{{ t }}</el-tag>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'

/** v-model = 架空档案 {core, bindings, uses, replace, keep, portability, exampleWorld, example, nodeMap?, rules?, ...}；
 *  card = 来源卡片 / 素材（{title, category, data?: {aliases, nodes}}），用来查示例里的原作专名 */
const props = defineProps({
  modelValue: { type: Object, default: null },
  card: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue'])

// 名称本身是原作专名的分类（同 Python material_portable.NAMED_CATS）
const NAMED_CATS = ['character', 'faction', 'location', 'item', 'monster']

const p = reactive(blank())
// 先声明：下面的 watch(immediate) 一挂载就会读它（自己发出去的值回传时不重置表单）
let lastEmitted = null
function blank() {
  return { core: '', bindings: [], uses: [], replace: [], keep: [], portability: 'adapt', exampleWorld: '', example: '' }
}
watch(
  () => props.modelValue,
  (v) => {
    if (v === lastEmitted) return
    const src = JSON.parse(JSON.stringify(v || {}))
    Object.keys(p).forEach((k) => delete p[k])
    Object.assign(p, blank(), src)
  },
  { immediate: true }
)

const leakTerms = computed(() => {
  const c = props.card || {}
  const d = c.data || {}
  const terms = p.bindings.filter((b) => b.kind === '专名').map((b) => b.term)
  if (NAMED_CATS.includes(c.category)) terms.push(c.title, ...(d.aliases || []))
  ;(d.nodes || []).forEach((n) => NAMED_CATS.includes(n.category) && terms.push(n.title))
  return [...new Set(terms.map((t) => String(t || '').trim()).filter((t) => t.length >= 2))]
})
const leaks = computed(() => {
  const text = (p.example || '') + ' ' + (p.rules || []).map((r) => r.then).join(' ')
  return leakTerms.value.filter((t) => text.includes(t))
})

function emitChange() {
  lastEmitted = { ...JSON.parse(JSON.stringify(p)), leaks: leaks.value }
  emit('update:modelValue', lastEmitted)
}
function add(key, v) {
  p[key] = [...(p[key] || []), v]
  emitChange()
}
function remove(key, i) {
  p[key].splice(i, 1)
  emitChange()
}
</script>

<style scoped>
.pe {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pe-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pe-label {
  margin-top: 8px;
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.pe-row .pe-label {
  margin-top: 0;
}
.pe-line {
  display: flex;
  align-items: center;
  gap: 6px;
}
.arrow {
  color: var(--el-text-color-secondary);
}
.node-title {
  width: 110px;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.leaks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-color-danger);
}
</style>
