<template>
  <div class="versions">
    <div class="muted">版本只追加：每次保存都是新版本，旧版本不会被改动；「恢复」= 把旧版本另存为最新版本。</div>
    <el-table :data="list" size="small" class="tbl" highlight-current-row @current-change="view">
      <el-table-column label="版本" width="70">
        <template #default="{ row }">v{{ row.versionNo }}<el-tag v-if="row.versionNo === current" size="small" class="cur">当前</el-tag></template>
      </el-table-column>
      <el-table-column label="来源" width="70">
        <template #default="{ row }">{{ row.author === 'ai' ? 'AI' : '作者' }}</template>
      </el-table-column>
      <el-table-column prop="note" label="说明" min-width="160" show-overflow-tooltip />
      <el-table-column prop="createTime" label="时间" width="150" />
      <el-table-column width="80">
        <template #default="{ row }">
          <el-button v-if="row.versionNo !== current" link size="small" type="primary" @click.stop="restore(row)">恢复</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="shown" class="preview">
      <h4>v{{ shown.versionNo }} · {{ shown.content.summary || '' }}</h4>
      <div v-if="diff" class="diff">
        <div v-for="d in diff" :key="d.key" :class="d.type">{{ d.type === 'add' ? '＋' : d.type === 'del' ? '－' : '～' }} {{ d.text }}</div>
        <div v-if="!diff.length" class="muted">和当前版本的特征 / 规则相同</div>
      </div>
      <ul>
        <li v-for="t in shown.content.traits || []" :key="t.id">[{{ t.kind === 'core' ? '核心' : '可变' }}] {{ t.text }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getVersion, listVersions, restoreVersion } from '@/api/persona'

const props = defineProps({ cardId: { type: Number, required: true }, current: { type: Number, default: null }, content: { type: Object, default: null } })
const emit = defineEmits(['restored'])
const list = ref([])
const shown = ref(null)

async function load() {
  const res = await listVersions(props.cardId)
  list.value = res.code === 0 ? res.data : []
}

async function view(row) {
  if (!row) return
  const res = await getVersion(props.cardId, row.versionNo)
  if (res.code === 0) shown.value = res.data
}

/** 和当前版本比：按特征 / 规则文字 */
const diff = computed(() => {
  if (!shown.value || !props.content || shown.value.versionNo === props.current) return null
  const items = (c) => new Map([...(c.traits || []).map((t) => [`t:${t.id}`, t.text]), ...(c.rules || []).map((r) => [`r:${r.id}`, `${r.situation}：${r.reaction}`])])
  const a = items(props.content)
  const b = items(shown.value.content)
  const out = []
  for (const [k, v] of b) {
    if (!a.has(k)) out.push({ key: k, type: 'del', text: v })
    else if (a.get(k) !== v) out.push({ key: k, type: 'chg', text: `${v} → ${a.get(k)}` })
  }
  for (const [k, v] of a) if (!b.has(k)) out.push({ key: k, type: 'add', text: v })
  return out
})

async function restore(row) {
  await ElMessageBox.confirm(`把 v${row.versionNo} 另存为最新版本？`, '恢复版本', { type: 'warning' })
  const res = await restoreVersion(props.cardId, row.versionNo)
  if (res.code !== 0) return ElMessage.error(res.message)
  ElMessage.success(`已恢复为 v${res.data.currentVersion}`)
  emit('restored', res.data)
  await load()
}

watch(() => [props.cardId, props.current], load, { immediate: true })
</script>

<style scoped>
.muted { font-size: 12px; color: var(--el-text-color-secondary); }
.tbl { margin-top: 8px; }
.cur { margin-left: 4px; }
.preview { margin-top: 12px; padding: 10px; background: var(--el-fill-color-light); border-radius: 6px; font-size: 13px; }
.diff .add { color: var(--el-color-success); }
.diff .del { color: var(--el-color-danger); }
.diff .chg { color: var(--el-color-warning); }
</style>
