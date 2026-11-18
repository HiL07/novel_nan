<template>
  <div class="persona-page">
    <aside class="side">
      <div class="side-top">
        <el-input v-model="keyword" size="small" clearable placeholder="名字 / 简介" :prefix-icon="Search" @change="load" />
        <el-button type="primary" size="small" :icon="Plus" @click="openExtract(null)">新建</el-button>
      </div>
      <el-empty v-if="!cards.length" description="还没有角色卡：从资料提取一个人物的原型" :image-size="70" />
      <div v-for="c in cards" :key="c.id" class="card" :class="{ active: c.id === currentId }" @click="select(c.id)">
        <div class="name">{{ c.name }} <span v-if="c.kind" class="muted">· {{ c.kind }}</span></div>
        <div class="summary">{{ c.summary || c.message || '' }}</div>
        <div class="meta">
          <el-tag size="small" :type="STATUS[c.status]?.type">{{ STATUS[c.status]?.label || c.status }}</el-tag>
          <span v-if="c.currentVersion" class="muted">v{{ c.currentVersion }} · {{ c.adaptationCount || 0 }} 个适配</span>
        </div>
        <el-progress v-if="c.status === 'EXTRACTING'" :percentage="c.progress || 0" :stroke-width="4" :show-text="false" />
      </div>
    </aside>

    <main v-if="card" class="main">
      <div class="head">
        <h2>{{ card.name }}</h2>
        <span v-if="card.aliases?.length" class="muted">又称 {{ card.aliases.join('、') }}</span>
        <span class="spacer" />
        <el-button v-if="card.status === 'EXTRACTING'" size="small" @click="stop">停止</el-button>
        <el-button v-if="['INTERRUPTED', 'FAILED'].includes(card.status)" size="small" type="primary" @click="resume">继续提取</el-button>
        <el-button size="small" type="danger" plain @click="remove">删除</el-button>
      </div>
      <div v-if="card.message" class="muted msg">{{ card.message }}</div>
      <el-progress v-if="card.status === 'EXTRACTING'" :percentage="card.progress || 0" />

      <el-tabs v-if="card.content" v-model="tab">
        <el-tab-pane label="原型卡" name="proto">
          <PersonaEditor :card-id="card.id" :content="card.content" @saved="onSaved" />
        </el-tab-pane>
        <el-tab-pane :label="`版本（${card.versionCount || 0}）`" name="versions" lazy>
          <VersionHistory :card-id="card.id" :current="card.currentVersion" :content="card.content" @restored="onSaved" />
        </el-tab-pane>
        <el-tab-pane :label="`适配版本（${card.adaptationCount || 0}）`" name="adapt" lazy>
          <AdaptPanel :card="card" />
        </el-tab-pane>
        <el-tab-pane label="试聊原型" name="chat" lazy>
          <div class="muted">和原型本人聊（原世界里的他）。想看他在新世界里的样子，到「适配版本」里试聊。</div>
          <ChatPanel :card-id="card.id" :name="card.name" :model="chatModel" />
          <ModelPicker v-model="chatModel" store-key="nan_novel.persona.chatModel" class="mt" />
          <div v-if="feedback.examples?.length" class="feedback">
            <h4>「不像他」反馈（{{ feedback.examples.length }}）<span class="muted">可以据此补行为规则</span></h4>
            <div v-for="(n, r) in feedback.reasons" :key="r" class="muted">{{ r }} × {{ n }}</div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </main>
    <main v-else class="main empty">
      <el-empty description="跨世界观角色卡：从传记 / 小说里提取一个人的思维方式、价值观和行为规则（每条带原文证据），再把他放进你的世界观里" />
    </main>

    <ExtractDialog v-model="extractOpen" :entity="entity" @started="onStarted" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { deletePersona, feedbackSummary, getPersona, listPersonas, resumePersona, stopPersona } from '@/api/persona'
import { errorMessage } from '@/api/request'
import PersonaEditor from '@/components/persona/PersonaEditor.vue'
import VersionHistory from '@/components/persona/VersionHistory.vue'
import AdaptPanel from '@/components/persona/AdaptPanel.vue'
import ChatPanel from '@/components/persona/ChatPanel.vue'
import ModelPicker from '@/components/persona/ModelPicker.vue'
import ExtractDialog from '@/components/persona/ExtractDialog.vue'

const STATUS = {
  EXTRACTING: { label: '提取中', type: 'warning' },
  INTERRUPTED: { label: '已中断', type: 'info' },
  READY: { label: '就绪', type: 'success' },
  FAILED: { label: '失败', type: 'danger' }
}

const route = useRoute()
const router = useRouter()
const cards = ref([])
const keyword = ref('')
const currentId = ref(null)
const card = ref(null)
const tab = ref('proto')
const extractOpen = ref(false)
const entity = ref(null)
const chatModel = ref({ source: 'api', configId: null, baseId: '' })
const feedback = ref({})
let timer = null

async function load() {
  try {
    const res = await listPersonas({ keyword: keyword.value })
    cards.value = res.code === 0 ? res.data : []
  } catch (e) {
    ElMessage.error(errorMessage(e, '读取角色卡失败'))
  }
}

async function select(id) {
  currentId.value = id
  const res = await getPersona(id)
  if (res.code !== 0) return ElMessage.error(res.message)
  card.value = res.data
  feedbackSummary({ cardId: id }).then((r) => (feedback.value = r.code === 0 ? r.data : {})).catch(() => {})
}

function openExtract(e) {
  entity.value = e
  extractOpen.value = true
}

async function onStarted(c) {
  await load()
  await select(c.id)
}

async function onSaved(c) {
  card.value = c
  await load()
}

async function stop() {
  const res = await stopPersona(card.value.id)
  if (res.code === 0) card.value = res.data
}

async function resume() {
  const res = await resumePersona(card.value.id)
  if (res.code !== 0) return ElMessage.error(res.message)
  card.value = res.data
  await load()
}

async function remove() {
  await ElMessageBox.confirm(`删除「${card.value.name}」和它的全部版本、适配版本、试聊记录？已写进工作区的快照不受影响。`, '删除', { type: 'warning' })
  const res = await deletePersona(card.value.id)
  if (res.code !== 0) return ElMessage.error(res.message)
  card.value = null
  currentId.value = null
  await load()
}

/** 提取中：每 3 秒刷新列表和当前卡 */
async function tick() {
  if (!cards.value.some((c) => c.status === 'EXTRACTING')) return
  await load()
  if (card.value?.status === 'EXTRACTING') await select(card.value.id)
}

watch(() => route.query.entityKey, (key) => {
  if (key) {
    openExtract({ extractId: route.query.extractId, entityKey: key, name: route.query.name })
    router.replace({ path: '/persona' })
  }
}, { immediate: true })

onMounted(() => {
  load()
  timer = setInterval(tick, 3000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.persona-page { display: flex; gap: 16px; min-height: calc(100vh - 100px); }
.side { flex-shrink: 0; width: 260px; }
.side-top { display: flex; gap: 8px; margin-bottom: 10px; }
.card { padding: 10px; margin-bottom: 8px; cursor: pointer; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-bg-color); }
.card.active { border-color: var(--el-color-primary); }
.name { font-weight: 600; }
.summary { margin: 4px 0; font-size: 12px; color: var(--el-text-color-regular); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { display: flex; align-items: center; gap: 6px; }
.main { flex: 1; min-width: 0; padding: 12px 16px; background: var(--el-bg-color); border-radius: 6px; }
.main.empty { display: flex; align-items: center; justify-content: center; }
.head { display: flex; align-items: center; gap: 10px; }
.head h2 { margin: 0; }
.spacer { flex: 1; }
.muted { font-size: 12px; color: var(--el-text-color-secondary); }
.msg { margin: 6px 0; }
.mt { margin-top: 10px; }
.feedback { margin-top: 16px; }
</style>
