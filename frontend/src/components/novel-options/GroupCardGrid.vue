<template>
  <!-- 分组（世界背景卡、阶段表、关键情节节点、怪物 / 势力列表…）的卡片网格：每项一张卡只显示内容，点一下在下面展开编辑 -->
  <div class="group-cards">
    <div class="gc-head">
      <span class="gc-title">{{ field.label }}</span>
      <span class="gc-count">{{ value.length }}</span>
      <span v-if="field.desc" class="gc-desc">{{ field.desc }}</span>
      <span class="gc-actions">
        <el-dropdown
          v-if="ai?.enabled.value"
          split-button
          size="small"
          :disabled="ai.locked([...path, field.label, NEW_ITEMS])"
          @click="ai.genItems(field, value, path, 3)"
          @command="(n) => ai.genItems(field, value, path, n)"
        >
          <el-icon v-if="!ai.loading(ai.busyKeyOf(path, field))"><MagicStick /></el-icon>
          <el-icon v-else class="is-loading"><Loading /></el-icon>
          AI 生成 3 个
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="n in [1, 2, 5]" :key="n" :command="n">AI 生成 {{ n }} 个{{ itemLabel }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </span>
    </div>

    <div class="gc-grid">
      <div
        v-for="(item, i) in value"
        :key="item._id"
        class="gc-card"
        :class="{ 'is-active': editing === item._id }"
        title="点击修改"
        @click="toggle(item)"
      >
        <div class="gc-name">
          <span class="gc-no">{{ i + 1 }}</span>
          <span class="gc-text">{{ itemName(item) || `未命名${itemLabel}` }}</span>
          <el-tag v-if="item._appear?.from > 1" size="small" type="info" effect="plain">第 {{ item._appear.from }} 章起</el-tag>
          <el-tag v-if="item._fromMaterial" size="small" type="success" effect="plain">素材库</el-tag>
        </div>
        <div v-for="line in previewOf(item)" :key="line.label" class="gc-line">
          <span class="gc-label">{{ line.label }}</span>{{ line.text }}
        </div>
        <div v-if="!previewOf(item).length" class="gc-empty">（还没填内容，点开填写）</div>
      </div>
      <div class="gc-card gc-add" @click="add">
        <el-icon><Plus /></el-icon>添加{{ itemLabel }}
      </div>
    </div>

    <!-- 正在编辑的那一项：完整表单，在网格下面展开 -->
    <div v-if="current" class="gc-editor">
      <div class="gc-editor-head">
        <b>{{ itemLabel }} {{ currentIndex + 1 }}{{ itemName(current) ? `：${itemName(current)}` : '' }}</b>
        <span class="gc-editor-ops">
          <AppearEditor v-if="field.key !== 'stages'" :item="current" />
          <el-button link size="small" :icon="CopyDocument" @click="duplicate">复制</el-button>
          <el-button link size="small" type="danger" :icon="Delete" @click="remove">删除</el-button>
          <el-button size="small" type="primary" plain :icon="Check" @click="editing = ''">完成</el-button>
        </span>
      </div>
      <OptionField
        v-for="child in field.fields || []"
        :key="child.key"
        :field="child"
        :container="current"
        :siblings="field.fields"
        :path="[...path, field.label, `${itemLabel} ${currentIndex + 1}${itemName(current) ? '：' + itemName(current) : ''}`]"
        :depth="1"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Check, CopyDocument, Delete, Loading, MagicStick, Plus } from '@element-plus/icons-vue'
import OptionField from './OptionField.vue'
import AppearEditor from './AppearEditor.vue'
import { clone, ensureValue, newGroupItem, summarizeFields, uid } from '@/novel-options/schema'
import { useOptionEditor } from '@/novel-options/editor'
import { NEW_ITEMS } from '@/novel-options/aiFill'

const props = defineProps({
  field: { type: Object, required: true },
  container: { type: Object, required: true },
  path: { type: Array, default: () => [] }
})

const { ai } = useOptionEditor()
const value = computed(() => ensureValue(props.container, props.field))
const itemLabel = computed(() => props.field.itemLabel || '项')
const editing = ref('')
const currentIndex = computed(() => value.value.findIndex((x) => x._id === editing.value))
const current = computed(() => value.value[currentIndex.value] || null)

const nameField = computed(() => (props.field.fields || []).find((f) => f.type === 'text'))
const itemName = (item) => (nameField.value ? String(item[nameField.value.key] || '').trim() : '')

/** 卡片上的速览：除名称外前 2 项已填的内容，每项截 60 字 */
function previewOf(item) {
  const fields = (props.field.fields || []).filter((f) => f !== nameField.value)
  return summarizeFields(fields, item)
    .filter((x) => x.display)
    .slice(0, 2)
    .map((x) => ({ label: x.label, text: x.display.length > 60 ? `${x.display.slice(0, 60)}…` : x.display }))
}

function toggle(item) {
  editing.value = editing.value === item._id ? '' : item._id
}
function add() {
  const item = newGroupItem(props.field)
  value.value.push(item)
  editing.value = item._id
}
function duplicate() {
  const copy = clone(current.value)
  copy._id = uid('item')
  value.value.splice(currentIndex.value + 1, 0, copy)
  editing.value = copy._id
}
function remove() {
  value.value.splice(currentIndex.value, 1)
  editing.value = ''
}
</script>

<style scoped>
.gc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.gc-title { font-size: 13px; font-weight: 600; color: var(--se-sub, #909399); }
.gc-count { font-size: 12px; color: var(--se-sub, #909399); }
.gc-desc { font-size: 12px; color: var(--se-sub, #909399); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.gc-actions { margin-left: auto; flex-shrink: 0; }
.gc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.gc-card {
  min-width: 0;
  padding: 10px 12px;
  background: var(--se-soft, #f7f8fa);
  border: 1px solid transparent;
  border-radius: var(--se-radius, 10px);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.gc-card:hover { border-color: var(--el-color-primary-light-5); }
.gc-card.is-active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.gc-name { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.gc-no {
  width: 18px; height: 18px; flex-shrink: 0; font-size: 11px; line-height: 18px; text-align: center;
  color: #fff; background: var(--el-color-primary-light-3); border-radius: 50%;
}
.gc-text { flex: 1; min-width: 0; font-weight: 600; color: var(--se-ink, #303133); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gc-line { font-size: 12px; line-height: 1.6; color: var(--se-ink, #303133); word-break: break-all; }
.gc-label { margin-right: 4px; color: var(--se-sub, #909399); }
.gc-label::after { content: '：'; }
.gc-empty { font-size: 12px; color: var(--se-sub, #909399); }
.gc-add {
  display: flex; align-items: center; justify-content: center; gap: 4px; min-height: 64px;
  color: var(--se-sub, #909399); background: transparent; border: 1px dashed var(--se-line, #e8e9ed);
}
.gc-add:hover { color: var(--el-color-primary); }
.gc-editor {
  margin-top: 12px; padding: 4px 14px 8px;
  border: 1px solid var(--el-color-primary-light-5); border-radius: var(--se-radius, 10px);
  box-shadow: 0 0 0 3px var(--el-color-primary-light-9);
}
.gc-editor-head { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--se-line, #e8e9ed); }
.gc-editor-ops { display: flex; align-items: center; gap: 4px; margin-left: auto; }
</style>
