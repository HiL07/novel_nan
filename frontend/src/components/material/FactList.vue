<template>
  <div class="fact-list">
    <div class="fact-head" @click="open = !open">
      <el-icon><component :is="open ? 'ArrowDown' : 'ArrowRight'" /></el-icon>
      事实依据 {{ facts.length }} 条（均已核对原文）
    </div>
    <ol v-if="open" class="facts">
      <li v-for="(f, i) in facts" :key="i">
        <span>{{ f.fact }}</span>
        <span class="quote">“{{ f.quote }}”<template v-if="f.chapter"> · {{ f.chapter }}</template></span>
      </li>
    </ol>
  </div>
</template>

<script setup>
import { ref } from 'vue'

/** 新版素材提取的事实依据：[{fact, quote, chapter}]，默认折叠 */
defineProps({
  facts: { type: Array, default: () => [] }
})
const open = ref(false)
</script>

<style scoped>
.fact-list {
  margin-top: 6px;
  font-size: 12px;
  color: #606266;
}
.fact-head {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #409eff;
}
.facts {
  margin: 4px 0 0;
  padding-left: 18px;
  max-height: 220px;
  overflow-y: auto;
}
.facts li {
  margin-bottom: 4px;
  line-height: 1.5;
}
.quote {
  display: block;
  color: #909399;
}
</style>
