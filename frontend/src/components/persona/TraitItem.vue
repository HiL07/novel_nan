<template>
  <div class="trait" :class="{ core: trait.kind === 'core', locked: trait.locked }">
    <div class="head">
      <el-select v-model="trait.layer" size="small" class="layer">
        <el-option v-for="l in LAYERS" :key="l.code" :label="l.label" :value="l.code" />
      </el-select>
      <el-radio-group v-model="trait.kind" size="small">
        <el-radio-button value="core" title="跨世界不变的内核">核心</el-radio-button>
        <el-radio-button value="adaptable" title="换了世界可以改变的表层">可变</el-radio-button>
      </el-radio-group>
      <el-checkbox v-model="trait.locked" size="small" title="锁定：适配时一个字都不改">锁定</el-checkbox>
      <el-tooltip :content="prov.tip" placement="top">
        <el-tag size="small" :type="prov.type">{{ prov.label }}</el-tag>
      </el-tooltip>
      <el-tag v-if="trait.confidence && trait.provenance !== 'user'" size="small" effect="plain"
              :type="trait.confidence === 'low' ? 'danger' : 'info'">置信度 {{ CONF[trait.confidence] || trait.confidence }}</el-tag>
      <span class="spacer" />
      <el-button link size="small" type="danger" @click="$emit('remove')">删除</el-button>
    </div>
    <el-input v-model="trait.text" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" maxlength="200" />
    <div v-if="trait.aiText && trait.aiText !== trait.text" class="ai-text">AI 原文：{{ trait.aiText }}</div>
    <div v-if="trait.evidence?.length" class="evidence">
      <el-button link size="small" @click="open = !open">{{ open ? '收起' : '查看' }}证据（{{ trait.evidence.length }}）</el-button>
      <ul v-if="open">
        <li v-for="e in trait.evidence" :key="e.id"><b>{{ e.id }}</b> {{ e.observation }} <q>{{ e.quote }}</q></li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { LAYERS, PROVENANCE } from '@/api/persona'

const props = defineProps({ trait: { type: Object, required: true } })
defineEmits(['remove'])
const CONF = { high: '高', medium: '中', low: '低' }
const open = ref(false)
const prov = computed(() => PROVENANCE[props.trait.provenance] || PROVENANCE.inferred)
</script>

<style scoped>
.trait { padding: 8px 10px; margin-bottom: 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }
.trait.core { border-left: 3px solid var(--el-color-primary); }
.trait.locked { background: #fdf6ec; }
.head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.layer { width: 110px; }
.spacer { flex: 1; }
.ai-text { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); }
.evidence ul { margin: 4px 0 0; padding-left: 18px; font-size: 12px; color: var(--el-text-color-regular); }
.evidence q { color: var(--el-color-success); }
</style>
