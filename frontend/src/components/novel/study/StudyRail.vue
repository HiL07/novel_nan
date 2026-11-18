<template>
  <!-- 书房右侧的竖排图标栏：一个分区一个图标（图标在上、小字在下），点了切换分区 -->
  <nav class="study-rail">
    <div
      v-for="t in items"
      :key="t.name"
      class="rail-item"
      :class="{ 'is-active': t.name === modelValue }"
      :title="t.label"
      @click="emit('update:modelValue', t.name)"
    >
      <el-badge :value="t.badge || 0" :hidden="!t.badge && !t.dot" :is-dot="!t.badge && !!t.dot" type="warning" class="rail-badge">
        <el-icon class="rail-icon"><component :is="t.icon" /></el-icon>
      </el-badge>
      <span class="rail-label">{{ t.label }}</span>
    </div>
  </nav>
</template>

<script setup>
defineProps({
  /** [{ name, label, icon, badge?: number, dot?: boolean }] */
  items: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])
</script>

<style scoped>
.study-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 64px;
  flex: 0 0 64px;
  padding: 12px 0;
  background: var(--ws-glass);
  border-left: 1px solid var(--ws-line);
  backdrop-filter: blur(6px);
}
.rail-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 52px;
  padding: 9px 0 7px;
  color: var(--ws-side-text);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  user-select: none;
}
.rail-item:hover {
  color: var(--ws-ink);
  background: var(--ws-side-hover);
}
.rail-item.is-active {
  color: var(--ws-accent);
  background: var(--ws-side-active-bg);
}
/* 激活项右侧一道赭红竖条（和应用侧栏的激活样式对应，方向相反） */
.rail-item.is-active::after {
  content: '';
  position: absolute;
  right: -6px;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 2px 0 0 2px;
  background: var(--ws-accent);
}
.rail-icon {
  font-size: 19px;
}
.rail-label {
  font-size: 11px;
  line-height: 1.2;
  white-space: nowrap;
}
.rail-badge :deep(.el-badge__content) {
  transform: translate(60%, -40%) scale(0.85);
}
</style>
