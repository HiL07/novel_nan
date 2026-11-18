<template>
  <!-- 「这次 AI 依据什么」：一小段 Markdown（只认 - 列表、两级缩进、**加粗**、换行），列出会影响这次生成 / 修改的选项和当前取值 -->
  <div class="ai-basis">
    <div v-if="title" class="head"><el-icon><InfoFilled /></el-icon>{{ title }}</div>
    <template v-for="(b, i) in blocks" :key="i">
      <ul v-if="b.list" class="list">
        <li v-for="(it, j) in b.items" :key="j" :class="{ sub: it.sub }">
          <span v-for="(p, k) in it.parts" :key="k" :class="{ b: p.bold }">{{ p.text }}</span>
        </li>
      </ul>
      <p v-else class="para"><span v-for="(p, k) in b.parts" :key="k" :class="{ b: p.bold }">{{ p.text }}</span></p>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'

const props = defineProps({
  md: { type: String, default: '' },
  title: { type: String, default: '' }
})

/** **加粗** → [{text, bold}] */
function inline(text) {
  return String(text).split(/(\*\*[^*]+\*\*)/).filter(Boolean)
    .map((t) => (t.startsWith('**') && t.endsWith('**') ? { text: t.slice(2, -2), bold: true } : { text: t, bold: false }))
}

const blocks = computed(() => {
  const out = []
  for (const line of String(props.md || '').split('\n')) {
    if (!line.trim()) continue
    const m = line.match(/^(\s*)[-*]\s+(.*)$/)
    if (m) {
      let last = out.at(-1)
      if (!last?.list) out.push((last = { list: true, items: [] }))
      last.items.push({ sub: m[1].length >= 2, parts: inline(m[2]) })
    } else {
      out.push({ list: false, parts: inline(line.trim()) })
    }
  }
  return out
})
</script>

<style scoped>
.ai-basis { padding: 8px 10px; background: var(--el-fill-color-light); border-radius: 6px; font-size: 12px; line-height: 1.7;
  color: var(--el-text-color-regular); }
.head { font-weight: 600; margin-bottom: 2px; display: flex; align-items: center; gap: 4px; }
.list { margin: 0; padding-left: 18px; }
.list li.sub { margin-left: 16px; list-style: circle; }
.para { margin: 0 0 2px; }
.b { font-weight: 600; color: var(--el-text-color-primary); }
</style>
