<template>
  <ul class="spec-tree" :class="{ 'is-root': root }">
    <li v-for="it in items" :key="it.key">
      <span class="spec-label">{{ it.label }}</span>
      <span v-if="it.display" class="spec-value">{{ it.display }}</span>
      <SpecTree v-if="it.children.length" :items="it.children" />
    </li>
  </ul>
</template>

<script setup>
/** 递归展示 buildSpec 产出的设定摘要 */
defineProps({
  items: { type: Array, required: true },
  root: { type: Boolean, default: false }
})
</script>

<style scoped>
.spec-tree {
  margin: 2px 0 0;
  padding-left: 14px;
  list-style: none;
  border-left: 1px solid #ebeef5;
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
  color: #909399;
}
.spec-label::after {
  content: '：';
}
.spec-value {
  color: #303133;
  word-break: break-all;
}
</style>
