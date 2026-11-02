<template>
  <!-- 书房左栏：当前分区里的小节目录。小节 = 内容里带 data-anchor 的元素（可带 data-anchor-count 显示数字），点了滚过去 -->
  <div class="anchor-nav">
    <div
      v-for="(a, i) in anchors"
      :key="`${i}-${a.label}`"
      class="study-nav-item"
      :class="{ 'is-active': i === current }"
      @click="go(i)"
    >
      <span class="anchor-mark" />
      <span class="nav-label">{{ a.label }}</span>
      <span v-if="a.count !== ''" class="anchor-count">{{ a.count }}</span>
    </div>
    <div v-if="!anchors.length" class="anchor-empty">{{ empty }}</div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  /** 内容根元素（在它里面找 [data-anchor]） */
  root: { type: Object, default: null },
  /** 滚动容器（书房中间栏） */
  scroller: { type: Object, default: null },
  /** 只在分区可见时监听，切走就停 */
  active: { type: Boolean, default: true },
  empty: { type: String, default: '这里还没有内容' }
})

const anchors = ref([])   // [{ el, label, count }]
const current = ref(0)
const OFFSET = 16         // 滚到小节时离中间栏顶部留一点空

function collect() {
  const root = props.root
  if (!root) {
    anchors.value = []
    return
  }
  // offsetParent 为空 = 元素没显示（v-show 藏起来的），不进目录
  anchors.value = [...root.querySelectorAll('[data-anchor]')]
    .filter((el) => el.offsetParent !== null)
    .map((el) => ({ el, label: el.dataset.anchor, count: el.dataset.anchorCount ?? '' }))
  onScroll()
}

/** 当前小节 = 最后一个顶部已经滚到中间栏上沿（附近）的小节 */
function onScroll() {
  const sc = props.scroller
  if (!sc || !anchors.value.length) return
  const top = sc.getBoundingClientRect().top + OFFSET + 24
  let idx = 0
  anchors.value.forEach((a, i) => {
    if (a.el.getBoundingClientRect().top <= top) idx = i
  })
  // 滚到底了：最后一节算当前（短小节永远到不了顶部）
  if (sc.scrollTop > 0 && sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 4) idx = anchors.value.length - 1
  current.value = idx
}

function go(i) {
  const sc = props.scroller
  const a = anchors.value[i]
  if (!sc || !a) return
  const y = a.el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - OFFSET
  sc.scrollTo({ top: Math.max(0, y), behavior: 'smooth' })
  current.value = i
}

// 内容变了（生成结果出现、小节增减、计数变化）就重新收集；合并成一帧一次
let mo = null
let raf = 0
const schedule = () => {
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(collect)
}
function stop() {
  mo?.disconnect()
  mo = null
  props.scroller?.removeEventListener('scroll', onScroll)
}
function start() {
  stop()
  if (!props.active || !props.root) return
  mo = new MutationObserver(schedule)
  mo.observe(props.root, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-anchor', 'data-anchor-count', 'style'] })
  props.scroller?.addEventListener('scroll', onScroll, { passive: true })
  schedule()
}
watch(() => [props.root, props.scroller, props.active], start, { immediate: true })
onBeforeUnmount(() => {
  stop()
  cancelAnimationFrame(raf)
})
</script>

<style scoped>
.nav-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.anchor-mark {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--el-border-color-darker);
}
.study-nav-item.is-active .anchor-mark {
  background: var(--ws-accent);
}
.anchor-count {
  min-width: 20px;
  padding: 0 6px;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
  color: var(--ws-sub);
  background: var(--ws-soft);
  border-radius: 9px;
}
.anchor-empty {
  padding: 8px 10px;
  font-size: 12px;
  color: var(--ws-sub);
}
</style>
