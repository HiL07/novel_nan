<template>
  <aside class="sidebar" :class="{ 'is-collapse': isCollapse }">
    <div class="sidebar-header">
      <span v-show="!isCollapse" class="sidebar-title">文件管理</span>
      <el-icon class="collapse-btn" @click="isCollapse = !isCollapse">
        <component :is="isCollapse ? 'Expand' : 'Fold'" />
      </el-icon>
    </div>

    <el-scrollbar>
      <!-- 菜单由路由表驱动：取带 meta.title 的路由项（见 docx/fronted_vue3/router/router.md） -->
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        :unique-opened="true"
        router
        class="sidebar-menu"
        background-color="#001529"
        text-color="#a6adb4"
        active-text-color="#ffffff"
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
.sidebar {
  width: 220px;
  flex: 0 0 220px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #001529;
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
  color: #ffffff;
}
.sidebar.is-collapse .sidebar-header {
  justify-content: center;
  padding: 0;
}
.sidebar-title {
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}
.collapse-btn {
  font-size: 18px;
  cursor: pointer;
}
.collapse-btn:hover {
  color: var(--el-color-primary);
}

.sidebar :deep(.el-scrollbar) {
  flex: 1;
  min-height: 0;
}

.sidebar-menu {
  border-right: none;
}
.sidebar-menu :deep(.el-menu-item:hover) {
  background-color: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}
.sidebar-menu :deep(.el-menu-item.is-active) {
  background-color: var(--el-color-primary);
  color: #ffffff;
}
/* 子菜单：标题与普通菜单项同色，展开后的子项背景略深 */
.sidebar-menu :deep(.el-sub-menu__title:hover) {
  background-color: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}
.sidebar-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: #ffffff;
}
.sidebar-menu :deep(.el-menu--inline) {
  background-color: #000c17;
}
</style>
