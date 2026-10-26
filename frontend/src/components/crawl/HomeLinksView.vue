<template>
  <!-- AI 解析：首页链接规律（首页上每一类链接的地址规律、显示文字规律、数量、例子） -->
  <div class="home-links">
    <el-empty v-if="!homeLinks?.groups?.length" :image-size="48" description="这条记录没有首页链接规律（旧记录，或首页没打开）；重新解析一次即可看到" />
    <template v-else>
      <div class="meta head">首页共 {{ homeLinks.total }} 个链接，按「类型 + 地址规律」归类：</div>
      <el-table :data="homeLinks.groups" size="small" class="table">
        <el-table-column label="类型" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="ROLE_TYPE[row.role] || 'info'">{{ row.label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数量" width="64">
          <template #default="{ row }">{{ row.count }}</template>
        </el-table-column>
        <el-table-column label="地址规律" min-width="230">
          <template #default="{ row }">
            <span class="mono">{{ row.pattern }}</span>
            <div v-if="row.areas?.length" class="meta">在 {{ row.areas.join('、') }}</div>
          </template>
        </el-table-column>
        <el-table-column label="显示文字规律" min-width="220">
          <template #default="{ row }">{{ row.textRule }}</template>
        </el-table-column>
        <el-table-column label="例子（文字 → 地址）" min-width="300">
          <template #default="{ row }">
            <div class="examples">
              <el-tooltip v-for="(e, i) in row.examples" :key="i" :content="e.url" placement="top">
                <a v-if="e.url.startsWith('http')" :href="e.url" target="_blank" rel="noopener noreferrer" class="chip">{{ e.text || '[图片]' }}</a>
                <span v-else class="chip">{{ e.text || '[图片]' }}</span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup>
defineProps({ homeLinks: { type: Object, default: null } })

const ROLE_TYPE = { category: 'success', book: 'primary', chapter: 'warning', list: 'info', nav: 'info', external: 'info', script: 'danger' }
</script>

<style scoped>
.head {
  margin-bottom: 8px;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.mono {
  font-family: Consolas, monospace;
  word-break: break-all;
}
.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.chip {
  display: inline-block;
  max-width: 220px;
  padding: 0 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  font-size: 12px;
  line-height: 20px;
  color: #606266;
  text-decoration: none;
}
a.chip:hover {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary);
}
</style>
