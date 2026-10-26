<template>
  <el-dialog :model-value="modelValue" title="小说提取" width="600px" @update:model-value="close">
    <p class="intro">将使用「模型配置」中当前启用的模型解析《{{ fileName }}》的章节、人物和文风，耗时视篇幅可能需要数分钟。</p>

    <el-form label-width="100px">
      <el-form-item label="提取创作素材">
        <el-switch v-model="opts.enabled" />
        <span class="hint">识别怪物、世界观、情节创意等可复用素材，提取后逐条确认才会存入素材库</span>
      </el-form-item>
      <template v-if="opts.enabled">
        <el-form-item label="素材类型">
          <el-checkbox-group v-model="opts.categories">
            <el-checkbox v-for="c in MATERIAL_CATEGORIES" :key="c.code" :value="c.code">{{ c.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="每段最多">
          <el-input-number v-model="opts.maxPerChunk" :min="1" :max="5" />
          <span class="hint">条 / 段。小说按约 6000 字切段逐段交给模型，每段最多挑出这么多条素材（各类型合计）；越大越全，也越费 token</span>
        </el-form-item>
        <el-form-item label="候选上限">
          <el-input-number v-model="opts.maxCandidates" :min="20" :max="3000" :step="100" />
          <span class="hint">条。全书提取完后同类同名的素材合并为一条，最多放这么多条进「待确认」，超出时保留出现章节最多的；再次提取同一本书时已有的会跳过</span>
        </el-form-item>
        <el-form-item label="特别关注">
          <el-input
            v-model="opts.focus"
            maxlength="300"
            placeholder="可选，如：重点提取怪物的弱点和习性；只要有新意的情节反转"
          />
        </el-form-item>
        <el-alert type="info" :closable="false" show-icon title="开启素材提取后，每段输出约增加 150~250 tokens（DeepSeek 约增加 20%~30% 费用）" />
      </template>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :disabled="opts.enabled && !opts.categories.length" @click="confirm">开始提取</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive } from 'vue'
import { MATERIAL_CATEGORIES } from '@/api/material'

defineProps({
  modelValue: { type: Boolean, default: false },
  fileName: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'confirm'])

// 记住上次的选择（同一会话内）
const opts = reactive({ enabled: true, categories: MATERIAL_CATEGORIES.map((c) => c.code), maxPerChunk: 2, focus: '', maxCandidates: 500 })

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  emit('confirm', opts.enabled ? { materials: { ...opts, categories: [...opts.categories], focus: opts.focus.trim() } } : {})
  close()
}
</script>

<style scoped>
.intro {
  margin: 0 0 14px;
  font-size: 13px;
  color: #606266;
}
.hint {
  flex: 1;
  min-width: 0;
  margin-left: 10px;
  line-height: 1.5;
  font-size: 12px;
  color: #909399;
}
</style>
