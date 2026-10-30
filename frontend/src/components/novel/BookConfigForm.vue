<template>
  <!-- 写作参数（novel.bookConfig）：自动规划「故事优先」第一步填，每一步提示词都带上；写正文时进【作品定位】 -->
  <el-form label-width="76px" size="small" class="book-config">
    <div class="grid">
      <el-form-item label="平台">
        <el-select v-model="cfg.platform" filterable allow-create default-first-option>
          <el-option v-for="x in PLATFORMS" :key="x" :label="x" :value="x" />
        </el-select>
      </el-form-item>
      <el-form-item label="题材">
        <el-select v-model="cfg.genre" filterable allow-create default-first-option placeholder="如：西幻">
          <el-option v-for="x in GENRES" :key="x" :label="x" :value="x" />
        </el-select>
      </el-form-item>
      <el-form-item label="读者">
        <el-select v-model="cfg.audience" filterable allow-create default-first-option>
          <el-option v-for="x in AUDIENCES" :key="x" :label="x" :value="x" />
        </el-select>
      </el-form-item>
      <el-form-item label="人称">
        <el-select v-model="cfg.pov" filterable allow-create default-first-option>
          <el-option v-for="x in POVS" :key="x" :label="x" :value="x" />
        </el-select>
      </el-form-item>
      <el-form-item label="目标字数">
        <el-select v-model="cfg.targetWords" filterable allow-create default-first-option>
          <el-option v-for="x in TARGET_WORDS" :key="x" :label="x" :value="x" />
        </el-select>
      </el-form-item>
      <el-form-item label="单章字数">
        <el-select v-model="cfg.chapterWords" filterable allow-create default-first-option>
          <el-option v-for="x in CHAPTER_WORDS" :key="x" :label="x" :value="x" />
        </el-select>
      </el-form-item>
    </div>
    <el-form-item label="标签">
      <el-select v-model="cfg.tags" multiple filterable allow-create default-first-option :multiple-limit="10" style="width: 100%"
                 placeholder="可多选，也可以自己输入">
        <el-option v-for="x in STORY_TAGS" :key="x" :label="x" :value="x" />
      </el-select>
    </el-form-item>
    <el-form-item label="核心卖点">
      <el-input v-model="cfg.sellingPoint" maxlength="200" placeholder="可选，如：每一卷探索一座新的浮空城，主角靠偷学禁咒越级" />
    </el-form-item>
    <el-form-item label="文风">
      <el-input v-model="cfg.style" maxlength="60" placeholder="可选，如：轻松幽默 / 细腻 / 冷峻" />
    </el-form-item>
  </el-form>
</template>

<script setup>
import { AUDIENCES, CHAPTER_WORDS, GENRES, PLATFORMS, POVS, STORY_TAGS, TARGET_WORDS } from '@/api/novelPlan'

const cfg = defineModel({ type: Object, required: true })
</script>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); column-gap: 8px; }
.grid :deep(.el-select) { width: 100%; }
</style>
