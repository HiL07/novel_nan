<template>
  <section class="app-main" :class="{ 'is-study': study }">
    <router-view v-slot="{ Component }">
      <transition name="fade" mode="out-in">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </transition>
    </router-view>
  </section>
</template>

<script setup>
defineProps({
  /** 工作区书房：页面自己管滚动（中间栏滚动），这里不留边距、不滚动 */
  study: { type: Boolean, default: false }
})
</script>

<style scoped>
.app-main {
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow-y: auto;
  box-sizing: border-box;
  padding: 16px;
  /* 纸色底和纸纹在 styles/ink-theme.css 的 .app-main 里 */
}
.app-main.is-study {
  padding: 0;
  overflow: hidden;
}
</style>
