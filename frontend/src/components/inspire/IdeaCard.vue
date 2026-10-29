<template>
  <div class="idea-card" :class="{ uncited: idea.uncited }">
    <div class="idea-head">
      <b class="idea-title">{{ idea.title }}</b>
      <el-tag v-if="idea.uncited" size="small" type="warning" title="这个思路没有引用任何提供的素材">未引用素材</el-tag>
      <el-tag v-if="saved" size="small" type="success">已收藏</el-tag>
      <span v-if="idea.history?.length" class="muted">已修改 {{ idea.history.length }} 次</span>
    </div>
    <div class="pitch">{{ idea.pitch }}</div>

    <div v-for="(s, i) in idea.sections || []" :key="'s' + i" class="section">
      <div class="section-head">
        <b>{{ s.heading || `第 ${i + 1} 段` }}</b>
        <SourceChips :ids="s.sources" :refs="refs" @open="(id) => emit('open-material', id)" />
      </div>
      <div class="section-text">{{ s.text }}</div>
    </div>

    <div v-if="idea.elements?.length" class="elements">
      <div class="muted">用到的元素</div>
      <div v-for="(e, i) in idea.elements" :key="'e' + i" class="element">
        <el-tag v-if="e.category" size="small" effect="plain">{{ categoryOf(e.category)?.label || e.category }}</el-tag>
        <b>{{ e.name }}</b>
        <span>{{ e.desc }}</span>
        <span v-if="e.change" class="muted">（改动：{{ e.change }}）</span>
        <SourceChips :ids="e.sources" :refs="refs" @open="(id) => emit('open-material', id)" />
      </div>
    </div>
    <div v-if="idea.twist" class="twist"><b>反转：</b>{{ idea.twist }}</div>
    <div v-if="idea.questions?.length" class="questions">
      <b>待你决定：</b>
      <span v-for="(q, i) in idea.questions" :key="i">{{ i + 1 }}. {{ q }}　</span>
    </div>

    <!-- 细化后的详细内容 -->
    <div v-if="idea.detail?.sections?.length" class="detail">
      <div class="detail-head" @click="showDetail = !showDetail">
        <el-icon><component :is="showDetail ? 'ArrowDown' : 'ArrowRight'" /></el-icon>
        <b>详细内容</b>
        <span v-if="idea.detail.instruction" class="muted">（要求：{{ idea.detail.instruction }}）</span>
      </div>
      <template v-if="showDetail">
        <div v-for="(s, i) in idea.detail.sections" :key="'d' + i" class="section">
          <div class="section-head">
            <b>{{ s.heading }}</b>
            <SourceChips :ids="s.sources" :refs="refs" @open="(id) => emit('open-material', id)" />
          </div>
          <div class="section-text">{{ s.text }}</div>
        </div>
      </template>
    </div>

    <!-- 追问 / 改 -->
    <div v-if="reviseOpen" class="revise">
      <div v-if="idea.sourceRefs?.length" class="revise-sources">
        <span class="muted">这个思路用的素材（点 × 换掉）：</span>
        <el-tag
          v-for="r in idea.sourceRefs"
          :key="r.materialId"
          size="small"
          :type="removed.includes(r.materialId) ? 'info' : ''"
          :closable="!removed.includes(r.materialId)"
          :class="{ off: removed.includes(r.materialId) }"
          @close="removed.push(r.materialId)"
          @click="removed = removed.filter((x) => x !== r.materialId)"
        >
          {{ r.title }}
        </el-tag>
        <el-button link size="small" type="primary" @click="emit('pick-materials', (list) => (added = list))">
          + 换上素材{{ added.length ? `（${added.length}）` : '' }}
        </el-button>
      </div>
      <el-input
        v-model="instruction"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 4 }"
        maxlength="500"
        placeholder="想怎么改？如：把魔物换成亡灵；第 2 站换成沙漠；主角的动机再私人一点"
      />
      <div class="revise-actions">
        <el-button size="small" @click="reviseOpen = false">收起</el-button>
        <el-button
          size="small"
          type="primary"
          :loading="busy === 'revise'"
          :disabled="!instruction.trim() && !removed.length && !added.length"
          @click="submitRevise"
        >
          按要求修改
        </el-button>
      </div>
    </div>
    <div v-if="refineOpen" class="revise">
      <el-input v-model="refineAsk" size="small" maxlength="300" placeholder="细化要求（可空），如：重点写第 3 站；多写环境和魔物的细节" />
      <div class="revise-actions">
        <el-button size="small" @click="refineOpen = false">收起</el-button>
        <el-button size="small" type="primary" :loading="busy === 'refine'" @click="emit('refine', refineAsk.trim())">细化</el-button>
      </div>
    </div>

    <div class="actions">
      <el-button v-if="!saved" size="small" type="primary" plain :icon="Star" @click="emit('collect')">收藏到墙</el-button>
      <el-button size="small" :icon="Reading" :loading="busy === 'refine'" @click="refineOpen = !refineOpen">细化</el-button>
      <el-button size="small" :icon="ChatLineSquare" @click="reviseOpen = !reviseOpen">追问 / 改</el-button>
      <el-button v-if="idea.history?.length" size="small" link @click="emit('undo')">退回上一版</el-button>
      <el-button size="small" :icon="Promotion" :disabled="!canApply" :title="canApply ? '' : '这面墙还没关联工作区'" @click="emit('apply')">
        写进工作区
      </el-button>
      <el-button size="small" link type="danger" @click="emit('dismiss')">{{ saved ? '从墙上移除' : '不要' }}</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, ref } from 'vue'
import { ChatLineSquare, Promotion, Reading, Star } from '@element-plus/icons-vue'
import { ElTag } from 'element-plus'
import { categoryOf } from '@/api/material'

/** 灵感墙的一个思路：正文、元素（带来源素材）、反转、待决定的问题、细化内容；收藏 / 细化 / 追问改 / 写进工作区 */
const props = defineProps({
  idea: { type: Object, required: true },
  saved: { type: Boolean, default: false },
  canApply: { type: Boolean, default: false },
  busy: { type: String, default: '' } // 'refine' | 'revise' | ''
})
const emit = defineEmits(['collect', 'refine', 'revise', 'undo', 'apply', 'dismiss', 'open-material', 'pick-materials'])

const showDetail = ref(true)
const reviseOpen = ref(false)
const refineOpen = ref(false)
const instruction = ref('')
const refineAsk = ref('')
const removed = ref([])
const added = ref([])

const refs = computed(() => Object.fromEntries((props.idea.sourceRefs || []).map((r) => [r.materialId, r])))

function submitRevise() {
  const parts = []
  if (instruction.value.trim()) parts.push(instruction.value.trim())
  const names = (props.idea.sourceRefs || []).filter((r) => removed.value.includes(r.materialId)).map((r) => r.title)
  if (names.length) parts.push(`不再使用这些素材：${names.join('、')}`)
  if (added.value.length) parts.push(`改用这些素材：${added.value.map((m) => m.title).join('、')}`)
  emit('revise', { instruction: parts.join('；'), removed: [...removed.value], added: [...added.value] })
}

/** 修改提交后由父组件调用：清空输入 */
function resetRevise() {
  instruction.value = ''
  removed.value = []
  added.value = []
  reviseOpen.value = false
}
defineExpose({ resetRevise, closeRefine: () => (refineOpen.value = false) })

/** 来源素材标签：点开看素材 */
const SourceChips = defineComponent({
  props: { ids: { type: Array, default: () => [] }, refs: { type: Object, default: () => ({}) } },
  emits: ['open'],
  setup(p, { emit: e }) {
    return () =>
      h('span', { class: 'chips' }, (p.ids || []).filter((id) => p.refs[id]).map((id) =>
        h(ElTag, { size: 'small', type: 'info', class: 'chip', onClick: () => e('open', id), title: p.refs[id].book ? `《${p.refs[id].book}》` : '' },
          () => p.refs[id].title)))
  }
})
</script>

<style scoped>
.idea-card {
  padding: 12px 14px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
}
.idea-card.uncited {
  border-color: #f3d19e;
}
.idea-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.idea-title {
  font-size: 15px;
  color: #303133;
}
.pitch {
  margin: 4px 0 8px;
  color: #606266;
}
.section {
  margin-top: 6px;
}
.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.section-text {
  margin-top: 2px;
  line-height: 1.7;
  color: #303133;
  white-space: pre-wrap;
}
.elements {
  margin-top: 8px;
  padding: 6px 8px;
  background: #fafafa;
  border-radius: 6px;
}
.element {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 13px;
}
.twist,
.questions {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
}
.detail {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed #dcdfe6;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.revise {
  margin-top: 8px;
}
.revise-sources {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.revise-sources .off {
  text-decoration: line-through;
  cursor: pointer;
}
.revise-actions {
  margin-top: 6px;
  text-align: right;
}
.actions {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
:deep(.chips) {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
:deep(.chip) {
  cursor: pointer;
}
</style>
