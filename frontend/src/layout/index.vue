<template>
  <div class="app-wrapper">
    <Sidebar />
    <AppMain />
  </div>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import AppMain from './AppMain.vue'
</script>

<style scoped>
/* 整体固定一屏高：只有右侧内容区（AppMain）自己滚动，左侧导航栏不跟着动 */
.app-wrapper {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
</style>
