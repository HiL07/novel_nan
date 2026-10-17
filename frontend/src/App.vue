<template>
  <layout />
</template>

<script setup>
import Layout from '@/layout/index.vue'
</script>

<style>
html,
body,
#app {
  margin: 0;
  padding: 0;
  height: 100%;
}

/* 页面切换过渡（见 docx/fronted_vue3/router/router.md） */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
