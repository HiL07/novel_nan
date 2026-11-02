<template>
  <el-dialog
    :model-value="modelValue"
    :title="`试聊 · ${item.name}`"
    width="680px"
    class="character-chat"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <div class="chat-bar">
      <span class="muted">
        {{ modelText }} · 按角色卡扮演{{ hasPersona ? '，并遵循写进本工作区的人物内核' : '' }}；会话会保存，可以回看、继续。
        回复格式：台词（动作）〔内心〕
      </span>
    </div>
    <ChatPanel
      v-if="modelValue && item.name"
      :novel-id="ai.novelId?.value || ''"
      :character="character"
      :name="item.name"
      :model="model"
    >
      <template #ops="{ chat, sending }">
        <el-button :disabled="sending || !hasExchange(chat)" @click="saveAsExample(chat)">存为示例对话</el-button>
      </template>
    </ChatPanel>
    <el-empty v-else-if="!item.name" description="先给角色起个名字再试聊" :image-size="60" />
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { currentValues } from '@/novel-options/aiFill'
import { useOptionEditor } from '@/novel-options/editor'
import { novelPersonas } from '@/api/persona'
import ChatPanel from '@/components/persona/ChatPanel.vue'

/**
 * 角色试聊（character.ai 式）：item = 角色卡取值，field = 「主要角色」分组字段（用来把取值转成文字）。
 * 会话存在 Java（persona_chat）；工作区里有同名的人物内核时按内核扮演（Python 按名字找）。
 */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, required: true },
  field: { type: Object, required: true }
})
const emit = defineEmits(['update:modelValue'])
const { ai } = useOptionEditor()
const personas = ref([])

const modelText = computed(() => {
  const c = ai.cfg
  if (c.source === 'local') return '本地模型（试聊不加载适配器）'
  if (c.source === 'gguf') return 'GGUF（llama.cpp）'
  return ai.apiModel.value ? `大模型 ${ai.apiModel.value.name}` : '大模型'
})
/** 工作区的模型 → 试聊的模型（大模型用启用的配置） */
const model = computed(() => {
  const c = ai.cfg
  return c.source === 'local' ? { source: 'local', baseId: c.baseId } : c.source === 'gguf' ? { source: 'gguf' } : { source: 'api' }
})
/** 角色卡 → {name, card: {字段名: 文字}}（会话保存时的快照；开场白由 Java 作为第一句） */
const character = computed(() => ({
  name: props.item.name, greeting: props.item.greeting || '', card: currentValues(props.field.fields, props.item)
}))
const hasPersona = computed(() => personas.value.some((p) => p.name === props.item.name))

watch(() => props.modelValue, (open) => {
  if (open && ai.novelId?.value) novelPersonas(ai.novelId.value).then((r) => (personas.value = r.code === 0 ? r.data : [])).catch(() => {})
}, { immediate: true })

const hasExchange = (chat) => (chat?.messages || []).some((m) => m.role === 'user') && (chat?.messages || []).some((m) => m.role === 'assistant')

/** 最近几个来回（最多 3 轮）追加到「示例对话」 */
function saveAsExample(chat) {
  const name = props.item.name
  const block = (chat.messages || []).slice(-6).map((m) => `${m.role === 'user' ? '对方' : name}：${m.content}`).join('\n')
  props.item.dialogue = props.item.dialogue?.trim() ? `${props.item.dialogue.trim()}\n\n${block}` : block
  ElMessage.success('已追加到角色卡的「示例对话」，记得保存设定')
}
</script>

<style scoped>
.chat-bar {
  margin-top: -8px;
  margin-bottom: 8px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
