<template>
  <div class="chat-panel">
    <div class="bar">
      <el-select v-model="chatId" size="small" placeholder="会话" class="sessions" @change="load">
        <el-option v-for="s in sessions" :key="s.id" :value="s.id"
                   :label="`${modeLabel(s.mode)} · ${s.updateTime?.slice(5, 16) || ''}`" />
      </el-select>
      <el-button size="small" :icon="Plus" @click="create">新会话</el-button>
      <el-radio-group v-if="chat" v-model="chat.mode" size="small" @change="saveMeta">
        <el-radio-button v-for="m in CHAT_MODES" :key="m.value" :value="m.value">{{ m.label }}</el-radio-button>
      </el-radio-group>
      <el-switch v-if="chat" v-model="chat.innerOn" size="small" active-text="显示内心" @change="saveMeta" />
      <el-button v-if="chat" link type="danger" size="small" @click="remove">删除会话</el-button>
    </div>

    <div v-if="chat && chat.mode === 'scene'" class="scene">
      <el-input v-model="scene.description" size="small" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500"
                placeholder="场景：如：雨夜的破庙，追兵就在门外" />
      <div v-for="(o, i) in scene.others" :key="i" class="other">
        <el-input v-model="o.name" size="small" placeholder="在场的人" maxlength="20" class="o-name" />
        <el-input v-model="o.motive" size="small" placeholder="他想要什么（动机）" maxlength="100" />
        <el-button link size="small" @click="scene.others.splice(i, 1)">移除</el-button>
      </div>
      <div class="scene-ops">
        <el-button link size="small" @click="scene.others.push({ name: '', motive: '' })">+ 在场人物</el-button>
        <el-checkbox v-model="scene.narrator" size="small">AI 旁白推进场景</el-checkbox>
        <el-button size="small" @click="saveMeta">保存场景</el-button>
      </div>
    </div>
    <div v-else-if="chat && chat.mode === 'interview'" class="hint">采访模式：问他对一件事怎么看、为什么——他会讲出自己的想法和原因，用来检查内核是否到位。</div>
    <div v-if="chat && chat.mode !== 'scene' && userRoleEditable" class="scene">
      <el-input v-model="userRole" size="small" maxlength="100" placeholder="你扮演谁（可选）：如：主角林远 / 一个陌生的路人" @change="saveRole" />
    </div>

    <el-alert v-if="chat?.drift?.drift" type="warning" :closable="false" show-icon class="drift">
      <template #title>
        第 {{ chat.drift.turn }} 条时检查：角色有点走偏 —— {{ (chat.drift.issues || []).join('；') || '和人物内核不太一致' }}
        <el-checkbox v-model="boost" size="small" class="boost">下一句加强人物提醒</el-checkbox>
      </template>
    </el-alert>

    <div ref="listRef" class="messages">
      <div v-if="!chat" class="empty">点「新会话」开始</div>
      <div v-else-if="!chat.messages?.length" class="empty">还没有对话，直接说点什么吧</div>
      <div v-for="(m, i) in chat?.messages || []" :key="i" class="msg" :class="m.role">
        <div v-if="m.role === 'assistant'" class="avatar">{{ (name || '?').slice(0, 1) }}</div>
        <div class="bubble-wrap">
          <div class="bubble">{{ m.content }}</div>
          <div v-if="m.inner && chat.innerOn" class="inner">〔{{ m.inner }}〕</div>
          <div v-if="m.role === 'assistant'" class="rate">
            <el-button link size="small" :type="m.rating === 'good' ? 'success' : ''" @click="rate(i, m.rating === 'good' ? null : 'good')">
              像他{{ adaptationId ? '（存为示例）' : '' }}
            </el-button>
            <el-button link size="small" :type="m.rating === 'bad' ? 'danger' : ''" @click="rateBad(i, m)">不像他</el-button>
            <span v-if="m.rating === 'bad' && m.reason" class="reason">{{ m.reason }}</span>
          </div>
        </div>
      </div>
      <div v-if="sending" class="msg assistant">
        <div class="avatar">{{ (name || '?').slice(0, 1) }}</div>
        <div class="bubble typing">正在回复…</div>
      </div>
    </div>

    <div class="composer">
      <el-input v-model="input" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" maxlength="1000" :disabled="!chat"
                placeholder="说的话；动作写在（）里。Enter 发送，Shift+Enter 换行" @keydown.enter.exact.prevent="send" />
      <div class="ops">
        <el-button type="primary" :icon="Promotion" :loading="sending" :disabled="!chat || !input.trim()" @click="send">发送</el-button>
        <el-button :icon="Refresh" :disabled="sending || !canRegenerate" @click="regenerate">换个回复</el-button>
        <slot name="ops" :chat="chat" :sending="sending" />
        <span v-if="chat?.summary" class="hint" :title="chat.summary">更早的对话已压成摘要</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Promotion, Refresh } from '@element-plus/icons-vue'
import { CHAT_MODES, chatFeedback, deleteChat, getChat, listChats, regenerateChat, sendChat, startChat, updateChat } from '@/api/persona'
import { errorMessage } from '@/api/request'

/**
 * 试聊（会话存在 Java persona_chat）。对象三选一：cardId（原型卡）/ adaptationId（适配版本）/ novelId + character（工作区角色卡）。
 * model = {source: api|gguf|local, configId?, baseId?}
 */
const props = defineProps({
  cardId: { type: Number, default: null },
  adaptationId: { type: Number, default: null },
  novelId: { type: String, default: '' },
  character: { type: Object, default: null },
  name: { type: String, default: '' },
  model: { type: Object, required: true },
  userRoleEditable: { type: Boolean, default: true }
})

const sessions = ref([])
const chatId = ref(null)
const chat = ref(null)
const scene = reactive({ description: '', others: [], narrator: false })
const userRole = ref('')
const input = ref('')
const sending = ref(false)
const boost = ref(false)
const listRef = ref()

const modeLabel = (m) => CHAT_MODES.find((x) => x.value === m)?.label || m
const canRegenerate = computed(() => {
  const list = chat.value?.messages || []
  return list.length >= 2 && list.at(-1).role === 'assistant'
})
const owner = computed(() =>
  props.adaptationId ? { adaptationId: props.adaptationId } : props.cardId ? { cardId: props.cardId }
    : { novelId: props.novelId, name: props.character?.name })

function modelBody() {
  const m = props.model || {}
  if (m.source === 'local') return { source: 'local', baseId: m.baseId }
  if (m.source === 'gguf') return { source: 'gguf' }
  return m.configId ? { source: 'api', configId: m.configId } : { source: 'api' }
}

async function refresh(selectFirst = true) {
  try {
    const res = await listChats(owner.value)
    sessions.value = res.code === 0 ? res.data || [] : []
    if (selectFirst && sessions.value.length && !sessions.value.some((s) => s.id === chatId.value)) {
      chatId.value = sessions.value[0].id
      await load()
    } else if (!sessions.value.length) {
      chatId.value = null
      chat.value = null
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取会话失败'))
  }
}

async function load() {
  if (!chatId.value) return
  const res = await getChat(chatId.value)
  if (res.code !== 0) return ElMessage.error(res.message)
  setChat(res.data)
}

function setChat(c) {
  chat.value = c
  chatId.value = c.id
  Object.assign(scene, { description: '', others: [], narrator: false }, c.scene || {})
  userRole.value = c.character?.userRole || ''
  scrollDown()
}

async function create() {
  try {
    const res = await startChat({
      ...owner.value, character: props.character || { name: props.name }, mode: chat.value?.mode || 'free', inner: true
    })
    if (res.code !== 0) throw new Error(res.message)
    setChat(res.data)
    await refresh(false)
  } catch (e) {
    ElMessage.error(errorMessage(e, '新建会话失败'))
  }
}

async function saveMeta() {
  if (!chat.value) return
  const res = await updateChat(chat.value.id, {
    mode: chat.value.mode, inner: chat.value.innerOn, scene: { ...scene, others: scene.others.filter((o) => o.name) }
  })
  if (res.code === 0) setChat(res.data)
}

async function saveRole() {
  if (!chat.value) return
  const res = await updateChat(chat.value.id, { character: { ...(chat.value.character || {}), userRole: userRole.value } })
  if (res.code === 0) setChat(res.data)
}

async function remove() {
  await ElMessageBox.confirm('删除这个会话？', '提示', { type: 'warning' })
  await deleteChat(chat.value.id)
  chat.value = null
  chatId.value = null
  await refresh()
}

async function talk(fn) {
  sending.value = true
  scrollDown()
  try {
    const res = await fn()
    if (res.code !== 0) throw new Error(res.message)
    boost.value = false
    setChat(res.data)
    return true
  } catch (e) {
    ElMessage.error({ message: errorMessage(e, '试聊失败'), duration: 8000 })
    return false
  } finally {
    sending.value = false
    scrollDown()
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value || !chat.value) return
  input.value = ''
  chat.value.messages = [...(chat.value.messages || []), { role: 'user', content: text }]
  const ok = await talk(() => sendChat(chat.value.id, { message: text, model: modelBody(), boost: boost.value }))
  if (!ok) {
    chat.value.messages.pop()
    input.value = text
  }
}

function regenerate() {
  return talk(() => regenerateChat(chat.value.id, { model: modelBody(), boost: boost.value }))
}

async function rate(index, rating, reason = '') {
  const res = await chatFeedback(chat.value.id, { index, rating, reason })
  if (res.code !== 0) return ElMessage.error(res.message)
  setChat(res.data)
  if (rating === 'good' && props.adaptationId) ElMessage.success('已存为适配版本的示例台词')
}

async function rateBad(index, m) {
  if (m.rating === 'bad') return rate(index, null)
  const { value } = await ElMessageBox.prompt('哪里不像他？（会汇总给作者补行为规则）', '不像他', {
    inputPlaceholder: '如：他不会这么轻易服软', inputValidator: (v) => (v || '').length <= 200
  }).catch(() => ({ value: null }))
  if (value !== null) await rate(index, 'bad', value)
}

function scrollDown() {
  nextTick(() => listRef.value && (listRef.value.scrollTop = listRef.value.scrollHeight))
}

watch(owner, () => refresh(), { deep: true })
onMounted(() => refresh())
defineExpose({ chat })
</script>

<style scoped>
.bar, .ops, .scene-ops, .other { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sessions { width: 180px; }
.scene { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.o-name { width: 140px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 6px; }
.drift { margin-top: 8px; }
.boost { margin-left: 12px; }
.messages { height: 380px; margin-top: 10px; padding: 12px; overflow-y: auto; background: #f5f7fa; border-radius: 8px; }
.empty { margin-top: 140px; text-align: center; color: #909399; font-size: 13px; }
.msg { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 12px; }
.msg.user { justify-content: flex-end; }
.avatar { display: flex; flex-shrink: 0; align-items: center; justify-content: center; width: 32px; height: 32px;
  font-weight: 600; color: #fff; background: var(--el-color-primary); border-radius: 50%; }
.bubble-wrap { max-width: 78%; }
.bubble { padding: 8px 12px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; background: #fff; border-radius: 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05); }
.msg.user .bubble { color: #fff; background: var(--el-color-primary); }
.inner { margin-top: 4px; font-size: 12px; color: #909399; font-style: italic; }
.rate { display: flex; align-items: center; gap: 4px; }
.reason { font-size: 12px; color: var(--el-color-danger); }
.typing { color: #909399; }
.composer { margin-top: 10px; }
.ops { margin-top: 8px; }
</style>
