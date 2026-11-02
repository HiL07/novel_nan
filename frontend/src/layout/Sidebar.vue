<template>
  <aside class="sidebar" :class="{ 'is-collapse': isCollapse }">
    <!-- 菜单由路由表驱动（取带 meta.title 的路由项，见 docx/fronted_vue3/router/router.md）。工作区页面不显示侧栏（书房布局自带顶栏 / 右侧图标栏，见 layout/index.vue） -->
    <div class="sidebar-header">
      <span v-show="!isCollapse" class="sidebar-title">小说工坊</span>
      <el-icon class="collapse-btn" @click="isCollapse = !isCollapse">
        <component :is="isCollapse ? 'Expand' : 'Fold'" />
      </el-icon>
    </div>

    <el-scrollbar>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        :unique-opened="true"
        router
        class="sidebar-menu"
      >
        <template v-for="item in menuItems" :key="item.path">
          <!-- meta.children：带子菜单的项（如「小说抓取」），子项各自是一个路由地址 -->
          <el-sub-menu v-if="item.meta?.children" :index="item.path">
            <template #title>
              <el-icon v-if="item.meta.icon">
                <component :is="item.meta.icon" />
              </el-icon>
              <span>{{ item.meta.title }}</span>
            </template>
            <el-menu-item v-for="child in item.meta.children" :key="child.path" :index="child.path">
              <el-icon v-if="child.icon">
                <component :is="child.icon" />
              </el-icon>
              <template #title>{{ child.title }}</template>
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="item.path">
            <el-icon v-if="item.meta?.icon">
              <component :is="item.meta.icon" />
            </el-icon>
            <template #title>{{ item.meta?.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>
    </el-scrollbar>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const isCollapse = ref(false)

const menuItems = computed(() => router.options.routes.filter((r) => r.meta?.title))
const activeMenu = computed(() => route.path)
</script>

<style scoped>
/* 颜色取 styles/ink-theme.css 的 --ws-side-*（宣纸白侧栏，激活项 = 浅赭红底 + 左侧赭红竖条） */
.sidebar {
  width: 220px;
  flex: 0 0 220px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--ws-side);
  border-right: 1px solid var(--ws-line);
  transition: width 0.2s;
}
.sidebar.is-collapse {
  width: 64px;
  flex-basis: 64px;
}

.sidebar-header {
  flex: 0 0 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  color: var(--ws-ink);
}
.sidebar.is-collapse .sidebar-header {
  justify-content: center;
  padding: 0;
}
.sidebar-title {
  font-family: var(--ws-font-title);
  font-size: 20px;
  font-weight: 400;
  letter-spacing: 0.12em;
  white-space: nowrap;
  color: var(--ws-ink);
}
.collapse-btn {
  font-size: 18px;
  color: var(--ws-side-text);
  cursor: pointer;
}
.collapse-btn:hover {
  color: var(--ws-accent);
}

.sidebar :deep(.el-scrollbar) {
  flex: 1;
  min-height: 0;
}

.sidebar-menu {
  --el-menu-bg-color: transparent;
  --el-menu-text-color: var(--ws-side-text);
  --el-menu-active-color: var(--ws-accent);
  --el-menu-hover-bg-color: var(--ws-side-hover);
  --el-menu-hover-text-color: var(--ws-ink);
  --el-menu-item-height: 48px;
  --el-menu-sub-item-height: 44px;
  border-right: none;
  background: transparent;
  padding: 0 8px;
}
.sidebar.is-collapse .sidebar-menu {
  padding: 0;
}
.sidebar-menu :deep(.el-menu-item),
.sidebar-menu :deep(.el-sub-menu__title) {
  position: relative;
  margin: 2px 0;
  border-radius: 8px;
}
.sidebar-menu :deep(.el-menu-item:hover),
.sidebar-menu :deep(.el-sub-menu__title:hover) {
  background-color: var(--ws-side-hover);
  color: var(--ws-ink);
}
.sidebar-menu :deep(.el-menu-item.is-active) {
  background-color: var(--ws-side-active-bg);
  color: var(--ws-accent);
  font-weight: 600;
}
.sidebar-menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 2px 2px 0;
  background: var(--ws-accent);
}
.sidebar-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--ws-accent);
}
.sidebar-menu :deep(.el-menu--inline) {
  background-color: transparent;
}
</style>
