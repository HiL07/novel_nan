<template>
  <!-- 全书骨架（novel.book）编辑：卷 → 阶段（目标、起止状态、必须发生、不能发生、对手上限）。直接改传入的对象 -->
  <div class="skeleton">
    <el-form label-width="84px" size="small">
      <el-form-item label="一句话"><el-input v-model="book.logline" maxlength="200" /></el-form-item>
      <el-form-item label="核心钩子"><el-input v-model="book.storyHook" maxlength="200" placeholder="读者最想知道答案的那个问题" /></el-form-item>
      <el-form-item label="卖点">
        <el-input :model-value="(book.sellingPoints || []).join('；')" placeholder="用；分隔"
                  @update:model-value="book.sellingPoints = split($event)" />
      </el-form-item>
      <el-form-item label="世界观要点">
        <div class="list">
          <div v-for="(w, i) in book.worldPoints" :key="i" class="row">
            <el-input v-model="book.worldPoints[i]" />
            <el-button link type="danger" @click="book.worldPoints.splice(i, 1)">删</el-button>
          </div>
          <el-button link @click="(book.worldPoints ||= []).push('')">+ 要点</el-button>
        </div>
      </el-form-item>
    </el-form>

    <div v-for="(v, vi) in book.volumes" :key="vi" class="volume">
      <div class="vol-head">
        <b>第 {{ vi + 1 }} 卷</b>
        <el-input v-model="v.title" size="small" style="width: 180px" />
        <span class="muted">共</span>
        <el-input-number v-model="v.chapters" size="small" :min="0" :max="2000" controls-position="right" style="width: 96px" />
        <span class="muted">章（{{ rangeOf(vi) }}）</span>
        <el-button link type="danger" size="small" @click="book.volumes.splice(vi, 1)">删除本卷</el-button>
      </div>
      <el-input v-model="v.summary" type="textarea" :autosize="{ minRows: 1 }" size="small" placeholder="本卷主线" />
      <div v-for="(s, si) in v.stages" :key="si" class="stage">
        <div class="stage-head">
          <el-tag size="small" effect="plain">阶段 {{ si + 1 }} · 第 {{ rowOf(vi, si)?.start }}~{{ rowOf(vi, si)?.end }} 章</el-tag>
          <el-input v-model="s.title" size="small" style="width: 140px" placeholder="阶段名" />
          <el-input-number v-model="s.chapters" size="small" :min="0" :max="2000" controls-position="right" style="width: 90px" />
          <span class="muted">章　对手上限</span>
          <el-input-number v-model="s.tierMax" size="small" :min="1" :max="5" controls-position="right" style="width: 76px" />
          <el-input v-model="s.power" size="small" style="flex: 1" placeholder="这一阶段主角的实力 / 身份" />
          <el-button link type="danger" size="small" @click="v.stages.splice(si, 1)">删</el-button>
        </div>
        <el-input v-model="s.goal" size="small"><template #prepend>目标</template></el-input>
        <div class="grid2">
          <el-input v-model="s.startState" size="small"><template #prepend>起点</template></el-input>
          <el-input v-model="s.endState" size="small"><template #prepend>终点</template></el-input>
          <el-input :model-value="(s.mustHappen || []).join('；')" size="small" @update:model-value="s.mustHappen = split($event)">
            <template #prepend>必须发生</template>
          </el-input>
          <el-input :model-value="(s.forbidden || []).join('；')" size="small" @update:model-value="s.forbidden = split($event)">
            <template #prepend>不能发生</template>
          </el-input>
        </div>
      </div>
      <el-button link size="small" @click="(v.stages ||= []).push(blankStage())">+ 阶段</el-button>
    </div>
    <el-button link size="small" @click="book.volumes.push({ title: `第${book.volumes.length + 1}卷`, summary: '', chapters: 100, stages: [blankStage()] })">
      + 卷
    </el-button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { bookLayout } from '@/api/novelPlan'

const props = defineProps({ book: { type: Object, required: true } })

const rows = computed(() => bookLayout(props.book))
const rowOf = (vi, si) => rows.value.find((r) => r.volume === vi && r.stage === si)
const rangeOf = (vi) => {
  const rs = rows.value.filter((r) => r.volume === vi)
  return rs.length ? `第 ${rs[0].start}~${rs.at(-1).end} 章` : ''
}
const split = (s) => String(s || '').split(/[；;]/).map((x) => x.trim()).filter(Boolean)
const blankStage = () => ({ title: '', chapters: 0, goal: '', startState: '', endState: '', power: '', mustHappen: [], forbidden: [], tierMax: 2 })
</script>

<style scoped>
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.list { width: 100%; }
.row { display: flex; gap: 6px; margin-bottom: 4px; }
.volume { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px; margin-bottom: 10px; }
.vol-head, .stage-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 6px; }
.stage { margin: 8px 0 4px 12px; padding-left: 10px; border-left: 3px solid var(--el-color-primary-light-7); }
.stage > .el-input { margin-bottom: 4px; }
.grid2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 8px; }
</style>
