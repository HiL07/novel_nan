<template>
  <el-dialog
    :model-value="modelValue"
    :title="`试聊 · ${item.name}`"
    width="640px"
    class="character-chat"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <div class="chat-bar">
      <span class="muted">{{ modelText }} · 按角色卡扮演，满意的回合可存为「示例对话」固定口吻</span>
      <el-button link size="small" @click="showScene = !showScene">{{ showScene ? '收起场景' : '设定场景' }}</el-button>
    </div>
    <div v-if="showScene" class="scene">
      <el-input v-model="state.scene" size="small" maxlength="300" placeholder="当前场景（可选）：如：雨夜的破庙里，两人第一次见面" />
      <el-input v-model="state.userRole" size="small" maxlength="100" placeholder="你扮演谁（可选）：如：主角林远 / 一个陌生的路人" />
    </div>

    <div ref="listRef" class="messages">
      <div v-if="!state.messages.length" class="empty muted">
        还没有对话。{{ item.greeting ? '' : '可以在角色卡「性格与说话」里写一段开场白，角色会先开口。' }}直接说点什么吧。
      </div>
      <div v-for="(m, i) in state.messages" :key="i" class="msg" :class="m.role">
        <div v-if="m.role === 'assistant'" class="avatar">{{ (item.name || '?').slice(0, 1) }}</div>
        <div class="bubble">{{ m.content }}</div>
      </div>
      <div v-if="sending" class="msg assistant">
        <div class="avatar">{{ (item.name || '?').slice(0, 1) }}</div>
        <div class="bubble typing">正在回复…</div>
      </div>
    </div>

    <div class="composer">
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 5 }"
        maxlength="1000"
        placeholder="对角色说的话，动作可写在（）里。Enter 发送，Shift+Enter 换行"
        @keydown.enter.exact.prevent="send"
      />
      <div class="composer-ops">
        <el-button type="primary" :icon="Promotion" :loading="sending" :disabled="!input.trim()" @click="send">发送</el-button>
        <el-button :icon="Refresh" :disabled="sending || !canRegenerate" @click="regenerate">换个回复</el-button>
        <el-button :disabled="sending || !hasExchange" @click="saveAsExample">存为示例对话</el-button>
        <el-button link type="danger" :disabled="sending" @click="reset">清空</el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script>
import { reactive } from 'vue'

// 每个角色的对话（按角色卡 _id），本次打开页面期间保留：关掉弹窗、切换角色再回来都还在
const histories = new Map()

function conversationOf(item) {
  if (!histories.has(item._id)) {
    histories.set(item._id, reactive({
      messages: item.greeting ? [{ role: 'assistant', content: item.greeting }] : [], scene: '', userRole: ''
    }))
  }
  return histories.get(item._id)
}
</script>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Promotion, Refresh } from '@element-plus/icons-vue'
import { currentValues } from '@/novel-options/aiFill'
import { useOptionEditor } from '@/novel-options/editor'

/** 角色试聊（character.ai 式）：item = 角色卡取值，field = 「主要角色」分组字段（用来把取值转成文字） */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, required: true },
  field: { type: Object, required: true }
})
const emit = defineEmits(['update:modelValue'])
const { ai } = useOptionEditor()

const state = computed(() => conversationOf(props.item))
const input = ref('')
const sending = ref(false)
const showScene = ref(false)
const listRef = ref()

const modelText = computed(() => {
  const c = ai.cfg
  if (c.source === 'local') return `本地模型${c.adapterId ? ' + 适配器' : ''}`
  return ai.apiModel.value ? `大模型 ${ai.apiModel.value.name}` : '大模型'
})
const canRegenerate = computed(() => {
  const list = state.value.messages
  return list.length >= 2 && list.at(-1).role === 'assistant'
})
const hasExchange = computed(() => state.value.messages.some((m) => m.role === 'user') && state.value.messages.some((m) => m.role === 'assistant'))

watch(() => [props.modelValue, props.item], ([open]) => open && scrollDown(), { immediate: true })

function scrollDown() {
  nextTick(() => listRef.value && (listRef.value.scrollTop = listRef.value.scrollHeight))
}

/** 角色卡 → {name, card: {字段名: 文字}}（试聊、示例对话本身不重复带上开场白） */
function character() {
  const card = currentValues(props.field.fields, props.item)
  return { name: props.item.name, card }
}

/** 以角色开场时补一句占位，兼容要求 user 先说话的接口 */
function payload(messages) {
  return messages[0]?.role === 'assistant' ? [{ role: 'user', content: '（对话开始）' }, ...messages] : messages
}

async function ask() {
  const conv = state.value
  sending.value = true
  scrollDown()
  try {
    const reply = await ai.chat(character(), payload(conv.messages), { scene: conv.scene, userRole: conv.userRole })
    if (reply) conv.messages.push({ role: 'assistant', content: reply })
    return !!reply
  } finally {
    sending.value = false
    scrollDown()
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  const conv = state.value
  conv.messages.push({ role: 'user', content: text })
  input.value = ''
  if (!(await ask())) {
    // 失败：把话放回输入框，避免对话里留下没有回复的一句
    conv.messages.pop()
    input.value = text
  }
}

async function regenerate() {
  const conv = state.value
  const last = conv.messages.pop()
  if (!(await ask())) conv.messages.push(last)
}

/** 最近几个来回（最多 3 轮）追加到「示例对话」 */
function saveAsExample() {
  const name = props.item.name
  const turns = []
  for (const m of state.value.messages.slice(-6)) {
    turns.push(`${m.role === 'user' ? '对方' : name}：${m.content}`)
  }
  const block = turns.join('\n')
  props.item.dialogue = props.item.dialogue?.trim() ? `${props.item.dialogue.trim()}\n\n${block}` : block
  ElMessage.success('已追加到角色卡的「示例对话」，记得保存设定')
}

function reset() {
  state.value.messages = props.item.greeting ? [{ role: 'assistant', content: props.item.greeting }] : []
}
</script>

<style scoped>
.chat-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: -8px;
}
.scene {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.messages {
  height: 380px;
  margin-top: 10px;
  padding: 12px;
  overflow-y: auto;
  background: #f5f7fa;
  border-radius: 8px;
}
.empty {
  margin-top: 140px;
  text-align: center;
}
.msg {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
}
.msg.user {
  justify-content: flex-end;
}
.avatar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-weight: 600;
  color: #fff;
  background: var(--el-color-primary);
  border-radius: 50%;
}
.bubble {
  max-width: 78%;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.msg.user .bubble {
  color: #fff;
  background: var(--el-color-primary);
}
.typing {
  color: #909399;
}
.composer {
  margin-top: 10px;
}
.composer-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
</style>
