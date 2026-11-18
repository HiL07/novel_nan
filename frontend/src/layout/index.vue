<template>
  <div class="app-wrapper">
    <!-- 工作区（书房）和提取工作区是全屏的：自带顶栏 / 左栏 / 右侧图标栏，不显示应用侧栏 -->
    <Sidebar v-if="!inStudy" />
    <AppMain :study="inStudy" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import AppMain from './AppMain.vue'

const route = useRoute()
const inStudy = computed(() => ['novelWorkspace', 'extractWorkspace'].includes(route.name))
</script>

<style scoped>
/* 整体固定一屏高：只有右侧内容区（AppMain）自己滚动，左侧导航栏不跟着动 */
.app-wrapper {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
</style>
