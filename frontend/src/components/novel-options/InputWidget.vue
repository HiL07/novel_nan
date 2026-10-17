<template>
  <div class="input-widget">
    <el-input
      v-if="field.type === 'text'"
      v-model="container[field.key]"
      :placeholder="field.placeholder || `请输入${field.label}`"
      maxlength="200"
      clearable
    />
    <el-input
      v-else-if="field.type === 'textarea'"
      v-model="container[field.key]"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 8 }"
      :placeholder="field.placeholder || `请输入${field.label}`"
      maxlength="2000"
      show-word-limit
    />
    <el-input-number
      v-else-if="field.type === 'number'"
      v-model="container[field.key]"
      :min="field.min ?? 0"
      :max="field.max ?? Number.MAX_SAFE_INTEGER"
      :step="field.step ?? 1"
      controls-position="right"
    />
    <div v-else-if="field.type === 'slider'" class="slider-wrap">
      <el-slider
        v-model="container[field.key]"
        :min="field.min ?? 0"
        :max="field.max ?? 10"
        :step="field.step ?? 1"
        :marks="field.marks"
        show-stops
      />
      <span class="slider-value">{{ container[field.key] }}</span>
    </div>
    <el-input-tag
      v-else-if="field.type === 'tags'"
      v-model="container[field.key]"
      :placeholder="field.placeholder || '输入后回车添加'"
      clearable
      :max="field.max"
    />
    <span v-else class="unknown">未知字段类型：{{ field.type }}</span>
  </div>
</template>

<script setup>
/** 叶子输入控件：直接读写 container[field.key]（container 为响应式取值容器） */
defineProps({
  field: { type: Object, required: true },
  container: { type: Object, required: true }
})
</script>

<style scoped>
.input-widget {
  max-width: 640px;
}
.slider-wrap {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 8px 14px;
}
.slider-wrap .el-slider {
  flex: 1;
}
.slider-value {
  min-width: 28px;
  font-weight: 600;
  color: var(--el-color-primary);
}
.unknown {
  color: var(--el-color-danger);
  font-size: 12px;
}
</style>
