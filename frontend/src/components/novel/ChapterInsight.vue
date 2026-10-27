<template>
  <div class="chapter-insight">
    <el-alert
      v-if="chapter.factsStale"
      type="warning"
      :closable="false"
      show-icon
      class="mt"
      title="正文改过：故事账本里本章的事实和摘要还是修改前的"
    >
      <el-button size="small" type="warning" :disabled="!canRun" @click="$emit('recheck', { digest: true, review: false })">重新提取本章事实</el-button>
    </el-alert>

    <el-collapse v-model="open" class="insight-collapse">
      <!-- 本章规划 -->
      <el-collapse-item v-if="chapter.plan || chapter.planError" name="plan">
        <template #title>
          <span class="item-title">本章规划</span>
          <el-tag v-if="chapter.plan" size="small" effect="plain">{{ chapter.plan.beats.length }} 个节拍</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">未规划</el-tag>
        </template>
        <ol v-if="chapter.plan" class="beats">
          <li v-for="(b, i) in chapter.plan.beats" :key="i" :class="{ current: i === currentBeat }">{{ b }}</li>
        </ol>
        <div v-if="chapter.plan?.foreshadow?.length" class="muted">伏笔安排：{{ chapter.plan.foreshadow.join('；') }}</div>
        <div v-if="chapter.plan?.hook" class="muted">章末钩子：{{ chapter.plan.hook }}</div>
        <div v-if="chapter.planError" class="muted">规划失败，已按本章目标直接写：{{ chapter.planError }}</div>
      </el-collapse-item>

      <!-- 一致性检查 -->
      <el-collapse-item v-if="!live" name="review">
        <template #title>
          <span class="item-title">一致性检查</span>
          <el-tag v-if="!review" size="small" type="info" effect="plain">未检查</el-tag>
          <el-tag v-else-if="review.error" size="small" type="danger" effect="plain">检查失败</el-tag>
          <el-tag v-else-if="!review.issues.length" size="small" type="success">没有发现问题</el-tag>
          <el-tag v-else size="small" :type="review.ignored ? 'info' : review.issues.length > 2 ? 'danger' : 'warning'">
            {{ review.issues.length }} 个问题{{ review.ignored ? '（已忽略）' : '' }}
          </el-tag>
        </template>
        <div v-if="review?.error" class="muted">{{ review.error }}</div>
        <div v-for="(it, i) in review?.issues || []" :key="i" class="issue">
          <div class="issue-head">
            <el-tag size="small" type="danger" effect="plain">{{ TYPES[it.type] || it.type }}</el-tag>
            <span
              v-if="it.quote"
              class="quote"
              :class="{ clickable: it.found }"
              :title="it.found ? '点击定位到正文' : '模型摘录的原句与正文不完全一致，无法定位'"
              @click="it.found && $emit('jump', it.quote)"
            >「{{ it.quote }}」</span>
          </div>
          <div class="issue-detail">{{ it.detail }}</div>
          <div v-if="it.fix" class="issue-fix">建议：{{ it.fix }}</div>
        </div>
        <div class="actions">
          <el-button size="small" :disabled="!canRun" @click="$emit('recheck', { digest: false, review: true })">
            {{ review ? '重新检查' : '检查一致性' }}
          </el-button>
          <el-button v-if="review?.issues?.length" size="small" @click="$emit('ignore', !review.ignored)">
            {{ review.ignored ? '取消忽略' : '忽略（标为已读）' }}
          </el-button>
          <span class="muted">{{ review?.at ? `检查于 ${review.at}${review.model ? ' · ' + review.model : ''}；` : '' }}只报告问题，不会自动改正文；可用「修改本章」手动修改</span>
        </div>
      </el-collapse-item>

      <!-- 本章事实变化 -->
      <el-collapse-item v-if="!live" name="facts">
        <template #title>
          <span class="item-title">本章事实变化</span>
          <el-tag v-if="chapter.facts" size="small" effect="plain">{{ factCount }} 条</el-tag>
          <el-tag v-else-if="chapter.factsError" size="small" type="warning" effect="plain">抽取失败</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">未抽取</el-tag>
        </template>
        <template v-if="chapter.facts">
          <div v-for="(f, i) in chapter.facts.foreshadow" :key="'f' + i" class="fact-line">
            <el-tag size="small" :type="f.action === 'resolve' ? 'success' : f.action === 'plant' ? 'warning' : ''" effect="plain">
              {{ ACTION[f.action] }}伏笔 {{ f.id }}
            </el-tag>
            {{ f.text }}<span v-if="f.note && f.note !== f.text" class="muted"> — {{ f.note }}</span>
          </div>
          <div v-for="(c, i) in chapter.facts.characters" :key="'c' + i" class="fact-line">
            <el-tag size="small" type="info" effect="plain">{{ c.name }}</el-tag> {{ c.change }}
          </div>
          <div v-for="(t, i) in chapter.facts.timeline" :key="'t' + i" class="fact-line">
            <el-tag size="small" type="info" effect="plain">时间线</el-tag> {{ t.when ? t.when + '：' : '' }}{{ t.event }}
          </div>
          <div v-if="!factCount" class="muted">本章没有新的伏笔、角色状态变化或时间线事件</div>
        </template>
        <div v-if="chapter.factsError" class="muted">抽取失败，已改为只写摘要：{{ chapter.factsError }}</div>
        <div class="actions">
          <el-button size="small" :disabled="!canRun" @click="$emit('recheck', { digest: true, review: false })">
            {{ chapter.facts ? '重新提取' : '提取本章事实' }}
          </el-button>
          <span class="muted">重新提取会替换故事账本里本章的记录，并重写本章摘要</span>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  chapter: { type: Object, required: true },
  canRun: { type: Boolean, default: true }, // 模型可用且没有任务在跑
  live: { type: Boolean, default: false }, // 生成中：只显示规划并高亮当前节拍
  currentBeat: { type: Number, default: -1 }
})
defineEmits(['recheck', 'ignore', 'jump'])

const TYPES = { setting: '设定冲突', character: '人物不符', timeline: '时间线', foreshadow: '伏笔', logic: '逻辑漏洞' }
const ACTION = { plant: '埋下', advance: '推进', resolve: '回收' }
const review = computed(() => props.chapter.review || null)
const factCount = computed(() => {
  const f = props.chapter.facts
  return f ? f.foreshadow.length + f.characters.length + f.timeline.length : 0
})
// 生成中默认展开规划；查看章节时有问题就展开检查结果
const open = ref(props.live ? ['plan'] : props.chapter.review?.issues?.length && !props.chapter.review.ignored ? ['review'] : [])
</script>

<style scoped>
.mt {
  margin-top: 10px;
}
.insight-collapse {
  margin-top: 10px;
}
.item-title {
  margin-right: 8px;
  font-weight: 600;
}
.beats {
  margin: 0 0 6px;
  padding-left: 22px;
  font-size: 13px;
  line-height: 1.8;
}
.beats li.current {
  color: var(--el-color-primary);
  font-weight: 600;
}
.issue {
  padding: 8px 10px;
  margin-bottom: 8px;
  font-size: 13px;
  line-height: 1.7;
  background: #fef6f6;
  border-radius: 6px;
}
.issue-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.quote {
  color: #606266;
}
.quote.clickable {
  color: var(--el-color-primary);
  cursor: pointer;
  text-decoration: underline dotted;
}
.issue-fix {
  color: #67c23a;
}
.fact-line {
  margin-bottom: 4px;
  font-size: 13px;
  line-height: 1.7;
}
.actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
</style>
