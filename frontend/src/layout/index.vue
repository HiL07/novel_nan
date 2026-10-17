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
.app-wrapper {
  display: flex;
  min-height: 100vh;
}
</style>
