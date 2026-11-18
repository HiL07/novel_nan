<template>
  <el-dialog :model-value="modelValue" title="写进工作区" width="680px" @update:model-value="close" @open="onOpen">
    <p class="muted">写进关联的工作区「{{ novelTitle || novelId }}」。</p>
    <el-radio-group v-model="to" class="targets">
      <el-radio-button value="outline">追加为大纲章节</el-radio-button>
      <el-radio-button value="elements" :disabled="!idea?.elements?.length">加进设定</el-radio-button>
      <el-radio-button value="hint">填进构思方向</el-radio-button>
    </el-radio-group>

    <template v-if="to === 'outline'">
      <p class="muted">
        思路的每一段变成一章，追加在大纲第 {{ startIndex - 1 > 0 ? startIndex - 1 : 0 }} 章之后；写作页会按大纲自动填入下一章的标题和目标。可以先改再保存。
      </p>
      <div v-for="(c, i) in rows" :key="i" class="row">
        <span class="idx">第 {{ c.index }} 章</span>
        <el-input v-model="c.title" size="small" maxlength="60" placeholder="章节标题" class="row-title" />
        <el-input v-model="c.goal" size="small" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" maxlength="2000" placeholder="本章目标" />
        <el-button link type="danger" :icon="Delete" @click="rows.splice(i, 1); renumber()" />
      </div>
    </template>
    <template v-else-if="to === 'elements'">
      <p class="muted">把思路里的元素（地点 / 怪物 / 势力 / 物品…）加进工作区设定的对应列表。会打开工作区的设定页，加完记得「保存设定」。</p>
      <el-checkbox-group v-model="pickedElements" class="elements">
        <el-checkbox v-for="(e, i) in idea?.elements || []" :key="i" :value="i">
          <el-tag v-if="e.category" size="small" effect="plain">{{ categoryOf(e.category)?.label }}</el-tag>
          {{ e.name }}：{{ e.desc }}
        </el-checkbox>
      </el-checkbox-group>
    </template>
    <template v-else>
      <p class="muted">把思路正文填进工作区「AI 构思」页的「构思方向」框（会替换原来的内容），之后可以接着生成大纲 / 后续走向。</p>
      <el-input :model-value="hintText" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" readonly />
    </template>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="to === 'outline' ? !rows.length : to === 'elements' ? !pickedElements.length : false" @click="confirm">
        {{ to === 'outline' ? `追加 ${rows.length} 章并保存大纲` : '打开工作区' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { categoryOf } from '@/api/material'
import { getNovel, updateNovel } from '@/api/novelGen'
import { errorMessage } from '@/api/request'
import { APPLY_KEY } from '@/api/inspire'

/** 灵感墙的思路 → 工作区：大纲章节（直接保存）/ 设定元素、构思方向（经 sessionStorage 交给工作区页面处理） */

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  idea: { type: Object, default: null },
  novelId: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])
const router = useRouter()

const to = ref('outline')
const rows = ref([])
const startIndex = ref(1)
const novelTitle = ref('')
const outline = ref(null)
const pickedElements = ref([])
const saving = ref(false)

const hintText = computed(() => {
  const i = props.idea
  if (!i) return ''
  const lines = [`${i.title}：${i.pitch}`]
  for (const s of i.sections || []) lines.push(`${s.heading ? s.heading + '：' : ''}${s.text}`)
  if (i.twist) lines.push(`反转：${i.twist}`)
  return lines.join('\n').slice(0, 3000)
})

async function onOpen() {
  to.value = 'outline'
  pickedElements.value = (props.idea?.elements || []).map((_, i) => i)
  try {
    const res = await getNovel(props.novelId)
    if (res.code !== 0) throw new Error(res.message)
    const n = res.data
    novelTitle.value = n.title
    outline.value = n.outline
    const lastOutline = Math.max(0, ...(n.outline?.chapters || []).map((c) => c.index))
    const lastWritten = Math.max(0, ...(n.chapters || []).map((c) => c.index))
    startIndex.value = Math.max(lastOutline, lastWritten) + 1
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取工作区失败'))
    startIndex.value = 1
  }
  const sections = props.idea?.detail?.sections?.length ? props.idea.detail.sections : props.idea?.sections || []
  rows.value = sections.map((s, i) => ({ index: startIndex.value + i, title: s.heading || '', goal: s.text || '' }))
}

function renumber() {
  rows.value.forEach((c, i) => (c.index = startIndex.value + i))
}

function close() {
  emit('update:modelValue', false)
}

async function confirm() {
  if (to.value === 'outline') {
    saving.value = true
    try {
      const base = outline.value || { logline: props.idea.pitch || props.idea.title, synopsis: '', chapters: [], materials: [] }
      const chapters = [...(base.chapters || []), ...rows.value.filter((c) => c.goal.trim()).map((c) => ({ ...c, materials: [] }))]
      const res = await updateNovel(props.novelId, { outline: { ...base, chapters } })
      if (res.code !== 0) throw new Error(res.message)
      ElMessage.success(`已追加 ${rows.value.length} 章到大纲`)
      close()
    } catch (e) {
      ElMessage.error(errorMessage(e, '保存大纲失败'))
    } finally {
      saving.value = false
    }
    return
  }
  // 设定元素 / 构思方向：交给工作区页面（那里才有设定编辑器和 AI 构思面板）
  const payload = { novelId: props.novelId, to: to.value, at: Date.now() }
  if (to.value === 'elements') {
    payload.elements = pickedElements.value.map((i) => props.idea.elements[i])
  } else {
    payload.hint = hintText.value
  }
  try {
    sessionStorage.setItem(APPLY_KEY, JSON.stringify(payload))
  } catch {
    ElMessage.error('浏览器不允许暂存数据，无法传给工作区')
    return
  }
  close()
  router.push(`/novel/workspace/${props.novelId}`)
}
</script>

<style scoped>
.muted {
  margin: 6px 0 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.targets {
  margin-bottom: 8px;
}
.row {
  display: grid;
  grid-template-columns: 70px 180px 1fr 30px;
  gap: 6px;
  align-items: start;
  margin-bottom: 6px;
}
.idx {
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 24px;
}
.elements {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
