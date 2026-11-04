<template>
  <!-- 一张卡片：查看 / 手改（名称、细分类型、概括、详细、属性、标签、量级）/ 换回历史版本；依据（事实、章节）只读 -->
  <div v-if="card" class="ce">
    <div class="ce-head">
      <el-tag size="small" effect="plain">{{ KIND_LABEL[card.kind] || card.kind }}</el-tag>
      <el-tag size="small" type="info">{{ categoryOf(card.category)?.label || card.category }}</el-tag>
      <el-tag v-if="card.edited" size="small" type="warning">手改过</el-tag>
      <el-tag v-if="card.status === 'SAVED'" size="small" type="success">已存进素材库</el-tag>
      <el-tag v-else-if="card.status === 'SKIPPED'" size="small" type="info">已跳过</el-tag>
      <span class="muted">第 {{ card.version }} 版</span>
      <el-dropdown v-if="card.history?.length" trigger="click" @command="restore">
        <el-button link size="small">历史版本（{{ card.history.length }}）</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="h in card.history" :key="h.version" :command="h.version">
              第 {{ h.version }} 版 · {{ h.by === 'user' ? '手改' : 'AI' }} · {{ h.time }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <span class="spacer" />
      <template v-if="!readonly">
        <el-button v-if="!editing" size="small" :icon="EditPen" @click="startEdit">修改</el-button>
        <template v-else>
          <el-button size="small" type="primary" :loading="saving" @click="save">保存</el-button>
          <el-button size="small" @click="editing = null">取消</el-button>
        </template>
      </template>
    </div>

    <!-- 编辑 -->
    <el-form v-if="editing" label-width="72px" size="small" class="ce-form">
      <el-form-item label="名称"><el-input v-model="editing.title" maxlength="100" /></el-form-item>
      <el-form-item label="分类">
        <el-select v-model="editing.category" style="width: 140px">
          <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
        </el-select>
        <el-input v-model="editing.subtype" placeholder="细分类型" maxlength="32" style="width: 160px; margin-left: 8px" />
        <el-select v-model="editing.tier" clearable placeholder="量级" style="width: 150px; margin-left: 8px">
          <el-option v-for="t in TIERS" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="概括"><el-input v-model="editing.summary" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" maxlength="300" /></el-form-item>
      <el-form-item label="详细"><el-input v-model="editing.detail" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" maxlength="2000" /></el-form-item>
      <el-form-item label="属性">
        <div class="attrs-edit">
          <div v-for="(a, i) in editing.attrs" :key="i" class="attr-row">
            <el-input v-model="a.k" placeholder="属性" style="width: 110px" />
            <el-input v-model="a.v" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" placeholder="内容" />
            <el-button link type="danger" :icon="Delete" @click="editing.attrs.splice(i, 1)" />
          </div>
          <el-button link type="primary" :icon="Plus" @click="editing.attrs.push({ k: '', v: '' })">添加属性</el-button>
        </div>
      </el-form-item>
      <el-form-item label="标签"><el-input-tag v-model="editing.tags" placeholder="回车添加" /></el-form-item>
    </el-form>

    <!-- 查看 -->
    <template v-else>
      <h3 class="ce-title">{{ card.title }}<span v-if="d.subtype" class="muted"> · {{ d.subtype }}</span></h3>
      <div class="ce-meta">
        <span v-if="tierLabelOf(d.tier)">量级：{{ tierLabelOf(d.tier) }}</span>
        <span v-for="t in d.tags || []" :key="t" class="tag">#{{ t }}</span>
      </div>
      <p v-if="d.summary" class="ce-summary">{{ d.summary }}</p>
      <p v-if="d.detail" class="ce-detail">{{ d.detail }}</p>
      <el-descriptions v-if="attrList.length && card.kind !== 'resonance'" :column="1" border size="small" class="ce-attrs">
        <el-descriptions-item v-for="[k, v] in attrList" :key="k" :label="k">{{ v }}</el-descriptions-item>
      </el-descriptions>
    </template>

    <!-- 共鸣素材：关系图 / 说明 / 3D -->
    <ResonanceView v-if="card.kind === 'resonance' && !editing" :data="d" class="ce-block" @pick-card="(id) => emit('pick-card', id)" />

    <!-- 写法卡：规律（每条引用的章可以点，跳回提取工作区那一章）+ 代码算的数字和例子 -->
    <div v-if="card.kind === 'craft' && d.rules?.length" class="ce-block">
      <div class="ce-block-title">写法规律</div>
      <div v-for="(r, i) in d.rules" :key="i" class="rule">
        <span>{{ i + 1 }}. {{ r.text }}</span>
        <el-button v-for="n in r.chapters" :key="n" link type="primary" size="small" @click="emit('jump', n)">第{{ n }}章</el-button>
      </div>
    </div>
    <div v-if="card.kind === 'craft' && d.examples?.length" class="ce-block">
      <div class="ce-block-title">依据的例子（代码挑的）</div>
      <div v-for="(e, i) in d.examples" :key="i" class="fact">
        <el-button link type="primary" size="small" @click="emit('jump', e.n)">第{{ e.n }}章《{{ e.title }}》</el-button>
        <span>{{ e.text }}</span>
      </div>
    </div>
    <!-- 世界观卡：成员（点了看对应的实体卡）+ 关系 -->
    <div v-if="card.kind === 'world' && d.members?.length" class="ce-block">
      <div class="ce-block-title">成员（{{ d.members.length }}）</div>
      <el-tag v-for="(k, i) in d.members" :key="k" size="small" class="member" @click="emit('pick-entity', k)">{{ d.memberNames?.[i] || k }}</el-tag>
    </div>
    <div v-if="card.kind === 'world' && d.related?.length" class="ce-block">
      <div class="ce-block-title">关系</div>
      <div v-for="(r, i) in d.related" :key="i" class="fact">{{ card.title }} —{{ r.relation }}→ {{ r.target }}</div>
    </div>

    <!-- 依据 -->
    <div v-if="d.facts?.length" class="ce-block">
      <div class="ce-block-title">依据的事实（{{ d.facts.length }}）</div>
      <div v-for="(f, i) in d.facts" :key="i" class="fact">
        <span v-if="f.entity" class="muted">【{{ f.entity }}】</span>
        <span>{{ f.fact }}</span>
        <span v-if="f.chapter" class="muted">（{{ f.chapter }}）</span>
        <div v-if="f.quote" class="quote">「{{ f.quote }}」</div>
      </div>
    </div>
    <div v-if="d.chapters?.length" class="ce-block">
      <div class="ce-block-title">出现章节（{{ d.chapters.length }}）</div>
      <div class="muted">{{ d.chapters.slice(0, 30).join('、') }}{{ d.chapters.length > 30 ? '…' : '' }}</div>
    </div>
    <div v-if="d.parts?.length" class="ce-block">
      <div class="ce-block-title">体系成员</div>
      <div class="muted">{{ d.parts.join('、') }}</div>
    </div>
  </div>
  <el-empty v-else description="选一张卡片" :image-size="60" />
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, EditPen, Plus } from '@element-plus/icons-vue'
import { MATERIAL_CATEGORIES, TIERS, categoryOf } from '@/api/material'
import { restoreCard, updateCard } from '@/api/novel'
import ResonanceView from './ResonanceView.vue'
import { errorMessage } from '@/api/request'

const props = defineProps({
  card: { type: Object, default: null },
  readonly: { type: Boolean, default: false }
})
const emit = defineEmits(['saved', 'jump', 'pick-entity', 'pick-card']) // saved = 新的卡片对象；jump = 全书章号（1 起）；pick-entity = 实体键

const KIND_LABEL = { entity: '实体卡', system: '体系卡', arc: '剧情段', craft: '写法卡', world: '世界观卡', resonance: '共鸣素材' }
const d = computed(() => props.card?.data || {})
const attrList = computed(() => Object.entries(d.value.attributes || {}).filter(([, v]) => v))
const tierLabelOf = (t) => TIERS.find((x) => x.value === t)?.label || ''

const editing = ref(null)
const saving = ref(false)
watch(() => props.card?.id, () => (editing.value = null))

function startEdit() {
  const x = d.value
  editing.value = {
    title: props.card.title,
    category: props.card.category,
    subtype: x.subtype || '',
    tier: x.tier ?? null,
    summary: x.summary || '',
    detail: x.detail || '',
    attrs: Object.entries(x.attributes || {}).map(([k, v]) => ({ k, v: String(v ?? '') })),
    tags: [...(x.tags || [])]
  }
}

async function save() {
  const e = editing.value
  if (!e.title.trim()) {
    ElMessage.warning('名称不能为空')
    return
  }
  const attributes = {}
  e.attrs.filter((a) => a.k.trim() && a.v.trim()).forEach((a) => (attributes[a.k.trim()] = a.v.trim()))
  saving.value = true
  try {
    const res = await updateCard(props.card.id, {
      title: e.title.trim(), category: e.category, subtype: e.subtype.trim(), tier: e.tier ?? null,
      summary: e.summary.trim(), detail: e.detail.trim(), attributes, tags: e.tags
    })
    if (res.code !== 0) throw new Error(res.message)
    editing.value = null
    ElMessage.success('卡片已保存')
    emit('saved', res.data)
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存卡片失败'))
  } finally {
    saving.value = false
  }
}

async function restore(version) {
  try {
    const res = await restoreCard(props.card.id, version)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(`已换回第 ${version} 版的内容`)
    emit('saved', res.data)
  } catch (err) {
    ElMessage.error(errorMessage(err, '换回版本失败'))
  }
}
</script>

<style scoped>
.ce-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.spacer {
  flex: 1;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ce-title {
  margin: 4px 0 6px;
  font-size: 17px;
  color: var(--el-text-color-primary);
}
.ce-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.tag {
  color: var(--el-color-primary);
}
.ce-summary {
  margin: 10px 0 6px;
  font-weight: 600;
  line-height: 1.7;
}
.ce-detail {
  margin: 0 0 10px;
  line-height: 1.8;
  white-space: pre-wrap;
}
.ce-attrs {
  margin-bottom: 10px;
}
.ce-block {
  margin-top: 14px;
}
.ce-block-title {
  margin-bottom: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
}
.fact {
  margin-bottom: 6px;
  font-size: 13px;
  line-height: 1.6;
}
.quote {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.rule {
  margin-bottom: 6px;
  font-size: 13px;
  line-height: 1.6;
}
.member {
  margin: 0 6px 6px 0;
  cursor: pointer;
}
.attrs-edit {
  width: 100%;
}
.attr-row {
  display: flex;
  gap: 6px;
  margin-bottom: 4px;
}
</style>
