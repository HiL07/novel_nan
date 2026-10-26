<template>
  <div class="character-cards">
    <!-- 创建：一句话让 AI 设计 / 空白卡 / 批量生成 -->
    <div class="cc-create">
      <template v-if="ai?.enabled.value">
        <el-input
          v-model="concept"
          class="cc-concept"
          maxlength="200"
          clearable
          placeholder="一句话描述角色，AI 帮你写完整角色卡。如：表面玩世不恭、其实背负血仇的少年刀客，主角的宿敌"
          @keyup.enter="createFromConcept"
        >
          <template #prefix><el-icon><MagicStick /></el-icon></template>
        </el-input>
        <el-button type="primary" :loading="creating" :disabled="newLocked && !creating" @click="createFromConcept">
          AI 创建角色
        </el-button>
        <el-dropdown trigger="click" :disabled="newLocked" @command="genMany">
          <el-button :disabled="newLocked">
            批量生成<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="n in [1, 2, 3, 5]" :key="n" :command="n">AI 生成 {{ n }} 个角色</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </template>
      <el-button :icon="Plus" @click="addBlank">空白角色卡</el-button>
      <el-button v-if="editMode" :icon="Plus" @click="addGroupField">为每个角色添加字段</el-button>
    </div>

    <el-empty v-if="!value.length" :image-size="64" description="还没有角色：用一句话让 AI 创建，或新建空白角色卡" />

    <div v-for="(item, i) in value" :key="item._id" class="cc-card" :class="{ 'is-open': open.has(item._id) }">
      <div class="cc-head" @click="toggle(item)">
        <div class="cc-avatar" :style="{ background: colorOf(item) }">{{ initialOf(item) }}</div>
        <div class="cc-id">
          <div class="cc-name-line">
            <span class="cc-name">{{ item.name || `未命名角色 ${i + 1}` }}</span>
            <el-tag v-for="r in labelsOf('role', item)" :key="r" size="small" :type="r.includes('主角') ? 'danger' : r.includes('反派') ? 'warning' : ''" effect="plain">{{ r }}</el-tag>
            <span class="cc-meta">{{ [...labelsOf('gender', item), ...labelsOf('age', item)].join(' · ') }}</span>
            <el-tag v-if="item._fromMaterial" size="small" type="success" effect="plain">来自素材库</el-tag>
          </div>
          <div class="cc-tagline">{{ item.tagline || '（还没有一句话人设）' }}</div>
        </div>
        <div class="cc-ops" @click.stop>
          <el-button
            v-if="ai?.enabled.value"
            size="small"
            type="primary"
            plain
            :icon="ChatDotRound"
            :disabled="!item.name"
            :title="item.name ? '和这个角色聊几句，检验性格与口吻' : '先填写姓名'"
            @click="openChat(item)"
          >
            试聊
          </el-button>
          <el-button
            v-if="ai?.enabled.value"
            size="small"
            :icon="MagicStick"
            :loading="ai.loading(`item:${item._id}`)"
            :disabled="ai.locked(itemPath(item, i))"
            title="AI 补全这个角色还没填的项"
            @click="fillItem(item, i)"
          >
            AI 补全
          </el-button>
          <el-button link size="small" :icon="CopyDocument" title="复制" @click="duplicate(i)" />
          <el-button link size="small" type="danger" :icon="Delete" title="删除" @click="remove(i)" />
          <el-icon class="cc-arrow"><ArrowDown v-if="!open.has(item._id)" /><ArrowUp v-else /></el-icon>
        </div>
      </div>

      <!-- 收起时：性格 / 说话 / 开场白速览 -->
      <div v-if="!open.has(item._id)" class="cc-preview" @click="toggle(item)">
        <div class="cc-chips">
          <el-tag v-for="p in labelsOf('personality', item)" :key="p" size="small" type="info">{{ p }}</el-tag>
          <el-tag v-for="s in labelsOf('speech', item)" :key="s" size="small" type="info" effect="plain">说话：{{ s }}</el-tag>
          <el-tag v-for="c in (item.catchphrases || []).slice(0, 3)" :key="c" size="small" effect="plain">“{{ c }}”</el-tag>
        </div>
        <div v-if="item.greeting" class="cc-greeting">“{{ clip(item.greeting, 90) }}”</div>
        <div v-else-if="item.goal" class="cc-greeting">目标：{{ clip(item.goal, 90) }}</div>
        <div class="cc-progress">已填 {{ filledOf(item) }}/{{ field.fields.length }} 项 · 点击展开编辑</div>
      </div>

      <!-- 展开：按分页编辑 -->
      <el-tabs v-else v-model="tabOf[item._id]" class="cc-tabs">
        <el-tab-pane v-for="s in sectionsOf()" :key="s.key" :name="s.key">
          <template #label>{{ s.label }}<span class="cc-tab-count">{{ sectionFilled(s, item) }}/{{ s.fields.length }}</span></template>
          <OptionField
            v-for="child in s.fields"
            :key="child.key"
            :field="child"
            :container="item"
            :siblings="field.fields"
            :path="itemPath(item, i)"
            :depth="depth + 1"
          />
        </el-tab-pane>
      </el-tabs>
    </div>

    <CharacterChat v-if="chat.item" v-model="chat.visible" :item="chat.item" :field="field" />
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowUp, ChatDotRound, CopyDocument, Delete, MagicStick, Plus } from '@element-plus/icons-vue'
import OptionField from './OptionField.vue'
import CharacterChat from './CharacterChat.vue'
import { clone, isFilled, newGroupItem, uid } from '@/novel-options/schema'
import { useOptionEditor } from '@/novel-options/editor'
import { NEW_ITEMS } from '@/novel-options/aiFill'

/** 「主要角色」分组的角色卡视图（schema 中 display: 'characterCards'）：value 为角色数组，字段按 section 分页 */
const props = defineProps({
  field: { type: Object, required: true },
  value: { type: Array, required: true },
  path: { type: Array, default: () => [] },
  depth: { type: Number, default: 0 }
})

const { editMode, addField, ai } = useOptionEditor()

const SECTIONS = [
  { key: 'basic', label: '基本信息' },
  { key: 'persona', label: '性格与说话' },
  { key: 'inner', label: '内心' },
  { key: 'story', label: '经历与能力' },
  { key: 'other', label: '其他' }
]
const AVATAR_COLORS = ['#5b8ff9', '#e8684a', '#5ad8a6', '#f6bd16', '#9270ca', '#ff9d4d', '#269a99', '#e86452']

const open = reactive(new Set())
const tabOf = reactive({})
const concept = ref('')
const creating = ref(false)
const chat = reactive({ visible: false, item: null })

function sectionsOf() {
  const known = new Set(SECTIONS.map((s) => s.key))
  return SECTIONS.map((s) => ({
    ...s,
    fields: props.field.fields.filter((f) => (known.has(f.section) && f.section !== 'other' ? f.section === s.key : s.key === 'other'))
  })).filter((s) => s.fields.length)
}

const sectionFilled = (s, item) => s.fields.filter((f) => isFilled(f, item)).length
const filledOf = (item) => props.field.fields.filter((f) => isFilled(f, item)).length
const clip = (t, n) => (t.length > n ? `${t.slice(0, n)}…` : t)

/** 选择类字段选中项的文字 */
function labelsOf(key, item) {
  const f = props.field.fields.find((x) => x.key === key)
  const v = item[key]
  if (!f || !v?.selected) return []
  return v.selected.map((s) => (f.options || []).find((o) => o.value === s)?.label).filter(Boolean)
}

function initialOf(item) {
  return (item.name || '?').trim().slice(0, 1) || '?'
}

function colorOf(item) {
  const s = item.name || item._id
  let h = 0
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

/** 新建角色（一句话创建 / 批量生成）只往列表里追加：大模型时不影响补全已有角色 */
const newLocked = computed(() => !!ai?.enabled.value && ai.locked([...props.path, props.field.label, NEW_ITEMS]))

function itemPath(item, i) {
  return [...props.path, props.field.label, `${props.field.itemLabel || '角色'} ${i + 1}${item.name ? '：' + item.name : ''}`]
}

function toggle(item) {
  if (open.has(item._id)) open.delete(item._id)
  else {
    open.add(item._id)
    if (!tabOf[item._id]) tabOf[item._id] = sectionsOf()[0]?.key
  }
}

function expand(item) {
  open.add(item._id)
  tabOf[item._id] = sectionsOf()[0]?.key
}

function addBlank() {
  const item = newGroupItem(props.field)
  props.value.push(item)
  expand(item)
}

function duplicate(i) {
  const copy = clone(props.value[i])
  copy._id = uid('item')
  if (copy.name) copy.name = `${copy.name}（副本）`
  props.value.splice(i + 1, 0, copy)
}

async function remove(i) {
  const name = props.value[i].name || `角色 ${i + 1}`
  try {
    await ElMessageBox.confirm(`删除角色「${name}」？`, '删除', { type: 'warning' })
  } catch {
    return
  }
  props.value.splice(i, 1)
}

async function createFromConcept() {
  const text = concept.value.trim()
  if (!text) {
    ElMessage.warning('先用一句话描述想要的角色')
    return
  }
  creating.value = true
  try {
    const added = await ai.genItems(props.field, props.value, props.path, 1, text)
    if (added?.length) {
      concept.value = ''
      added.forEach(expand)
    }
  } finally {
    creating.value = false
  }
}

async function genMany(n) {
  const added = await ai.genItems(props.field, props.value, props.path, n)
  if (added?.length === 1) expand(added[0])
}

function fillItem(item, i) {
  ai.fillItem(props.field, item, itemPath(item, i))
}

function openChat(item) {
  chat.item = item
  chat.visible = true
}

function addGroupField() {
  addField(props.field.fields, { title: `为每个${props.field.itemLabel || '角色'}添加字段` })
}
</script>

<style scoped>
.cc-create {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.cc-concept {
  flex: 1;
  min-width: 280px;
}
.cc-card {
  margin-bottom: 10px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  transition: box-shadow 0.15s, border-color 0.15s;
}
.cc-card:hover {
  border-color: #c6e2ff;
}
.cc-card.is-open {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}
.cc-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  cursor: pointer;
}
.cc-avatar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  font-size: 20px;
  font-weight: 600;
  color: #fff;
  border-radius: 50%;
}
.cc-id {
  flex: 1;
  min-width: 0;
}
.cc-name-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.cc-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.cc-meta {
  font-size: 12px;
  color: #909399;
}
.cc-tagline {
  margin-top: 3px;
  overflow: hidden;
  font-size: 13px;
  color: #606266;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cc-ops {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 4px;
}
.cc-arrow {
  margin-left: 4px;
  color: #909399;
}
.cc-preview {
  padding: 0 14px 12px 70px;
  cursor: pointer;
}
.cc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.cc-greeting {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
.cc-progress {
  margin-top: 6px;
  font-size: 12px;
  color: #c0c4cc;
}
.cc-tabs {
  padding: 0 14px 10px;
}
.cc-tab-count {
  margin-left: 4px;
  font-size: 11px;
  color: #909399;
}
</style>
