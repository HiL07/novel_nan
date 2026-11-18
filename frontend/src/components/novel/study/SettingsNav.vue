<template>
  <!-- 书房左栏：设定的分类目录（数据来自 SettingsEditor expose 的 nav；编辑器本身只留内容卡片） -->
  <div v-if="nav" class="settings-nav">
    <div class="nav-group-title">基础设定</div>
    <div
      v-for="cat in nav.builtin"
      :key="cat.key"
      class="study-nav-item"
      :class="{ 'is-active': cat.key === nav.activeKey }"
      @click="nav.select(cat.key)"
    >
      <el-icon><component :is="cat.icon || 'Collection'" /></el-icon>
      <span class="nav-label">{{ cat.label }}</span>
      <el-tooltip :content="`已填 ${nav.filledCount(cat)} / ${cat.fields.length} 项`" placement="right" :show-after="300">
        <span class="nav-dot" :class="`is-${nav.progressOf(cat)}`" />
      </el-tooltip>
    </div>

    <div class="nav-group-title">自定义元素</div>
    <div
      v-for="cat in nav.custom"
      :key="cat.key"
      class="study-nav-item"
      :class="{ 'is-active': cat.key === nav.activeKey }"
      @click="nav.select(cat.key)"
    >
      <el-icon><component :is="cat.icon || 'Collection'" /></el-icon>
      <span class="nav-label">{{ cat.label }}</span>
      <el-tooltip :content="`已填 ${nav.filledCount(cat)} / ${cat.fields.length} 项`" placement="right" :show-after="300">
        <span class="nav-dot" :class="`is-${nav.progressOf(cat)}`" />
      </el-tooltip>
    </div>
    <el-button class="nav-add" :icon="Plus" plain type="primary" size="small" @click="nav.add()">添加自定义元素</el-button>
    <p class="nav-tip">如：怪物、势力、种族、法宝……可套用推荐模板或完全自定义</p>
  </div>
  <div v-else class="nav-tip">设定加载中…</div>
</template>

<script setup>
import { Plus } from '@element-plus/icons-vue'

defineProps({
  /** SettingsEditor 的 nav：{ builtin, custom, activeKey, filledCount, progressOf, select, add } */
  nav: { type: Object, default: null }
})
</script>

<style scoped>
.nav-group-title {
  margin: 4px 10px 6px;
  font-size: 12px;
  color: var(--ws-sub);
}
.nav-group-title:not(:first-child) {
  margin-top: 16px;
}
.nav-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nav-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1.5px solid var(--el-color-primary);
}
.nav-dot.is-empty {
  border-color: var(--el-border-color-darker);
}
.nav-dot.is-part {
  background: linear-gradient(90deg, var(--el-color-primary) 50%, transparent 50%);
}
.nav-dot.is-full {
  background: var(--el-color-primary);
}
.nav-add {
  width: calc(100% - 8px);
  margin: 10px 4px 0;
}
.nav-tip {
  margin: 8px 8px 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ws-sub);
}
</style>
