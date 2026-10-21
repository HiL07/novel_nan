<template>
  <!-- AI 解析地址：每次尝试（已学规则 / 内置规则 / AI 写规则）的结果、失败原因、规则、token、耗时 -->
  <el-table :data="attempts" size="small" :row-class-name="({ row }) => (row.ok ? 'ok-row' : 'fail-row')" class="attempt-table">
    <el-table-column prop="index" label="#" width="44" />
    <el-table-column label="方式" width="110">
      <template #default="{ row }">{{ STRATEGY[row.strategy] || row.strategy }}</template>
    </el-table-column>
    <el-table-column label="结果" width="76">
      <template #default="{ row }">
        <el-tag :type="row.ok ? 'success' : 'danger'" size="small" effect="dark">{{ row.ok ? '成功' : '失败' }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="目录 / 首章" width="120">
      <template #default="{ row }">
        <span :class="{ err: !row.chapterCount }">{{ row.chapterCount || 0 }} 章</span> /
        <span :class="{ err: row.sampleChars < 200 }">{{ row.sampleChars || 0 }} 字</span>
      </template>
    </el-table-column>
    <el-table-column label="说明" min-width="320">
      <template #default="{ row }">
        <div v-if="row.reason">{{ row.reason }}</div>
        <div v-if="row.error" class="err">{{ row.error }}</div>
        <div v-if="row.tocUrl" class="meta mono">目录页：{{ row.tocUrl }}</div>
        <div v-if="Object.keys(row.rule || {}).length" class="meta mono">{{ ruleText(row.rule) }}</div>
      </template>
    </el-table-column>
    <el-table-column label="Token（入/出）" width="116">
      <template #default="{ row }">
        <span v-if="row.promptTokens || row.completionTokens">{{ row.promptTokens }} / {{ row.completionTokens }}</span>
        <span v-else class="meta">不调用模型</span>
      </template>
    </el-table-column>
    <el-table-column label="耗时" width="70">
      <template #default="{ row }">{{ row.seconds }} 秒</template>
    </el-table-column>
  </el-table>
</template>

<script setup>
defineProps({ attempts: { type: Array, default: () => [] } })

const STRATEGY = { learned: '已学到的规则', preset: '内置规则', ai: 'AI 写规则' }

function ruleText(rule) {
  return Object.entries(rule || {})
    .filter(([, v]) => v && (!Array.isArray(v) || v.length))
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' | ') : v}`)
    .join('；')
}
</script>

<style scoped>
.err {
  color: #f56c6c;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.mono {
  font-family: Consolas, monospace;
  word-break: break-all;
}
.attempt-table :deep(.fail-row) {
  background: #fef6f6;
}
.attempt-table :deep(.ok-row) {
  background: #f4fbf6;
}
</style>
