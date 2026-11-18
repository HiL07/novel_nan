<template>
  <!-- 书房顶栏：退出 · 书名（可改）· 作品定位 ………… 模型（插槽）· 本章 / 总字数 -->
  <header class="study-header">
    <div class="head-left">
      <button class="exit-btn" type="button" title="回到工作区列表" @click="emit('exit')">
        <el-icon><ArrowLeft /></el-icon><span>退出</span>
      </button>
      <span class="head-sep" />
      <el-input
        :model-value="title"
        class="title-input"
        maxlength="100"
        placeholder="未命名"
        @update:model-value="(v) => emit('update:title', v)"
        @change="emit('rename')"
      />
      <div class="chips" :title="detail ? `作品定位：${detail}（点击修改）` : '作品定位：平台 / 题材 / 读者 / 卖点…，写正文时会带上（点击填写）'" @click="emit('positioning')">
        <span v-for="c in chips.slice(0, 4)" :key="c" class="chip">{{ c }}</span>
        <span v-if="chips.length > 4" class="chip">+{{ chips.length - 4 }}</span>
        <span v-if="!chips.length" class="chip is-empty">填写作品定位</span>
      </div>
    </div>
    <div class="head-right">
      <slot />
      <span class="words">
        <el-icon><Histogram /></el-icon>
        <template v-if="chapterWords !== null">本章 {{ chapterWords }}</template>
        <span>总字数 {{ totalWords }}</span>
      </span>
    </div>
  </header>
</template>

<script setup>
import { ArrowLeft, Histogram } from '@element-plus/icons-vue'

defineProps({
  title: { type: String, default: '' },
  /** 作品定位短标签（平台 / 题材 / 读者 / 标签 …） */
  chips: { type: Array, default: () => [] },
  /** 作品定位全文（悬停提示） */
  detail: { type: String, default: '' },
  /** 当前打开章节的字数；null = 没打开章节 */
  chapterWords: { type: Number, default: null },
  totalWords: { type: Number, default: 0 }
})
const emit = defineEmits(['exit', 'update:title', 'rename', 'positioning'])
</script>

<style scoped>
.study-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 54px;
  flex: 0 0 54px;
  padding: 0 16px 0 12px;
  background: var(--ws-glass);
  border-bottom: 1px solid var(--ws-line);
  backdrop-filter: blur(6px);
}
.head-left,
.head-right {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.head-right {
  flex-shrink: 0;
}
.exit-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  font-size: 13px;
  color: var(--ws-side-text);
  background: none;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.exit-btn:hover {
  color: var(--ws-accent);
  background: var(--ws-side-hover);
}
.head-sep {
  width: 1px;
  height: 18px;
  background: var(--ws-line);
}
/* 书名：平时像标题，悬停 / 聚焦才看得出是输入框 */
.title-input {
  width: 220px;
  flex-shrink: 0;
}
.title-input :deep(.el-input__wrapper) {
  background: transparent;
  box-shadow: none;
}
.title-input :deep(.el-input__wrapper:hover),
.title-input :deep(.el-input__wrapper.is-focus) {
  background: var(--ws-card);
  box-shadow: 0 0 0 1px var(--el-border-color) inset;
}
.title-input :deep(.el-input__inner) {
  font-family: var(--ws-font-title);
  font-size: 20px;
  color: var(--ws-ink);
}
.chips {
  display: flex;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  cursor: pointer;
}
.chip {
  padding: 1px 8px;
  font-size: 12px;
  line-height: 20px;
  white-space: nowrap;
  color: var(--ws-side-text);
  background: var(--ws-soft);
  border: 1px solid var(--ws-line);
  border-radius: 3px;
}
.chip.is-empty {
  color: var(--ws-sub);
  border-style: dashed;
}
.chips:hover .chip {
  border-color: var(--el-color-primary-light-7);
}
.words {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--ws-sub);
  white-space: nowrap;
}
</style>
