<template>
  <ul class="spec-tree" :class="{ 'is-root': root, 'is-compact': compact }">
    <li v-for="it in items" :key="it.key">
      <!-- compact：卡片标题已经是字段名，第一层只显示内容 -->
      <span v-if="!(compact && root)" class="spec-label">{{ it.label }}</span>
      <span v-if="it.display" class="spec-value">{{ it.display }}</span>
      <SpecTree v-if="it.children.length" :items="it.children" />
    </li>
  </ul>
</template>

<script setup>
/** 递归展示 buildSpec 产出的设定摘要 */
defineProps({
  items: { type: Array, required: true },
  root: { type: Boolean, default: false },
  compact: { type: Boolean, default: false }
})
</script>

<style scoped>
.spec-tree {
  margin: 2px 0 0;
  padding-left: 14px;
  list-style: none;
  border-left: 1px solid var(--el-border-color-lighter);
}
.spec-tree.is-root {
  padding-left: 0;
  border-left: none;
}
li {
  padding: 2px 0;
  font-size: 13px;
  line-height: 1.6;
}
.spec-label {
  color: var(--el-text-color-secondary);
}
.spec-label::after {
  content: '：';
}
.spec-value {
  color: var(--el-text-color-primary);
  font-family: var(--ws-font-prose);
  word-break: break-all;
  white-space: pre-wrap;
}
.is-compact.is-root > li > .spec-value {
  font-size: 14px;
  line-height: 1.75;
}
</style>
