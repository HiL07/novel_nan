<template>
  <section class="app-main">
    <router-view v-slot="{ Component }">
      <transition name="fade" mode="out-in">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </transition>
    </router-view>
  </section>
</template>

<script setup></script>

<style scoped>
.app-main {
  flex: 1;
  min-width: 0;
  padding: 16px;
  background: #f0f2f5;
}
</style>
