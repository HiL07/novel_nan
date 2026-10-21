<template>
  <div class="site-map">
    <div class="head">
      <span>站点根地址：</span>
      <a v-if="homeUrl" :href="homeUrl" target="_blank" rel="noopener noreferrer">{{ homeUrl }}</a>
      <span v-else class="meta">未记录</span>
      <template v-if="siteMap?.items?.length">
        <el-tag size="small" :type="siteMap.failed ? 'warning' : 'success'" class="ml8">
          已掌握 {{ siteMap.mastered }}/{{ siteMap.total }} 项
        </el-tag>
        <el-tag v-if="siteMap.failed" size="small" type="danger" class="ml8">未掌握 / 部分掌握 {{ siteMap.failed }} 项</el-tag>
      </template>
    </div>
    <el-empty
      v-if="!siteMap?.items?.length"
      :image-size="48"
      description="这条规则是旧版解析的，没有做站点结构验证；重新 AI 解析一次即可补上"
    />
    <el-table v-else :data="siteMap.items" size="small" class="items">
      <el-table-column label="层级" width="130">
        <template #default="{ row }">{{ row.label }}</template>
      </el-table-column>
      <el-table-column label="是否掌握" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS[row.status]?.type">{{ STATUS[row.status]?.label || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="地址规律" min-width="220">
        <template #default="{ row }">
          <span v-if="row.pattern" class="mono">{{ row.pattern }}</span>
          <span v-else class="meta">-</span>
        </template>
      </el-table-column>
      <el-table-column label="说明 / 例子" min-width="280">
        <template #default="{ row }">
          <div :class="{ err: row.status === 'failed' }">{{ row.detail }}</div>
          <div v-if="row.example && row.example !== row.pattern" class="meta mono">{{ row.example }}</div>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
// AI 解析得到的站点结构：根地址（首页）+ 每层跳转规律（首页 / 分类 / 书籍 / 目录 / 分页 / 章节 / 换一本书验证）及是否掌握
defineProps({
  siteMap: { type: Object, default: null },
  homeUrl: { type: String, default: '' }
})

const STATUS = {
  ok: { label: '已掌握', type: 'success' },
  partial: { label: '部分掌握', type: 'warning' },
  failed: { label: '未掌握', type: 'danger' },
  na: { label: '本站无此结构', type: 'info' },
  skipped: { label: '未验证', type: 'info' }
}
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  font-size: 13px;
}
.ml8 {
  margin-left: 8px;
}
.mono {
  font-family: Consolas, monospace;
  word-break: break-all;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.err {
  color: #f56c6c;
}
</style>
