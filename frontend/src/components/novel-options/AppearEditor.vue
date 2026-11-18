<template>
  <!-- 出场条件（借鉴世界书的 延迟 / 持续 / 排除词，按章节算）：存在条目的 _appear 上，只给生成用 -->
  <el-popover placement="bottom-end" :width="320" trigger="click">
    <template #reference>
      <el-button link size="small" :type="summary ? 'warning' : ''" :icon="Timer" @click.stop>
        {{ summary || '出场条件' }}
      </el-button>
    </template>
    <div class="appear" @click.stop>
      <div class="tip">
        控制这条设定从第几章起才进入写作提示词。没到章节时，正文、规划、一致性检查都不会提前写到它，
        灵感墙 / AI 构思只把它当伏笔。都不填 = 一直可用。
      </div>
      <div class="row">
        <span class="label">从第</span>
        <el-input-number v-model="from" :min="0" :max="99999" size="small" controls-position="right" />
        <span class="label">章起登场</span>
      </div>
      <div class="row">
        <span class="label">登场后持续</span>
        <el-input-number v-model="span" :min="0" :max="999" size="small" controls-position="right" />
        <span class="label">章</span>
      </div>
      <div class="hint">持续：最近 N 章的摘要里提到过它，这一章即使没提也带上，不会突然被遗忘。</div>
      <div class="row col">
        <span class="label">排除词（逗号隔开）</span>
        <el-input v-model="exclude" size="small" placeholder="如：梦境，回忆（出现这些词时不带这条设定）" />
      </div>
      <div class="ops">
        <el-button size="small" text @click="clear">清空</el-button>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { computed } from 'vue'
import { Timer } from '@element-plus/icons-vue'

const props = defineProps({
  /** 分组条目（直接改它的 _appear） */
  item: { type: Object, required: true }
})

function get(key) {
  return props.item._appear?.[key]
}
function set(key, v) {
  props.item._appear = { ...(props.item._appear || {}), [key]: v }
}

const from = computed({ get: () => get('from') || 0, set: (v) => set('from', v || 0) })
const span = computed({ get: () => get('span') || 0, set: (v) => set('span', v || 0) })
const exclude = computed({ get: () => get('exclude') || '', set: (v) => set('exclude', v) })

const summary = computed(() => {
  const parts = []
  if (from.value > 0) parts.push(`第 ${from.value} 章起`)
  if (span.value > 0) parts.push(`持续 ${span.value} 章`)
  if (String(exclude.value).trim()) parts.push('有排除词')
  return parts.join(' · ')
})

function clear() {
  delete props.item._appear
}
</script>

<style scoped>
.appear { display: flex; flex-direction: column; gap: 8px; }
.tip, .hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; }
.row { display: flex; align-items: center; gap: 6px; }
.row.col { flex-direction: column; align-items: stretch; }
.label { font-size: 13px; white-space: nowrap; }
.ops { display: flex; justify-content: flex-end; }
</style>
