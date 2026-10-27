<template>
  <div class="facts-panel">
    <div class="intro muted">
      每章写完后，AI 在写摘要的同一次调用里抽取本章的伏笔、角色状态变化和时间线，合并到这里；写后续章节时，
      未回收的伏笔、本章相关角色的当前状态和最近的时间线会作为「故事账本」放进上下文。
      条目都可以手动修改（改过的标「手动」，AI 之后只追加经过、不改它的内容和状态）；删除最后一章会回滚该章的记录。
      <el-button link type="primary" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>
    <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" class="mt" />

    <!-- 伏笔 -->
    <div class="section-head">
      <span class="col-title">伏笔（未回收 {{ openCount }} / 共 {{ facts.foreshadows.length }}）</span>
      <el-radio-group v-model="fsFilter" size="small">
        <el-radio-button value="open">未回收</el-radio-button>
        <el-radio-button value="resolved">已回收</el-radio-button>
        <el-radio-button value="all">全部</el-radio-button>
      </el-radio-group>
      <el-button size="small" :icon="Plus" :disabled="locked" @click="editForeshadow(null)">新增伏笔</el-button>
    </div>
    <el-table :data="shownForeshadows" size="small" empty-text="暂无伏笔">
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column label="内容" min-width="220">
        <template #default="{ row }">
          {{ row.text }}
          <el-tag v-if="row.manual" size="small" type="info" effect="plain">手动</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="86">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'open' ? 'warning' : 'success'">{{ row.status === 'open' ? '未回收' : '已回收' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="埋下" width="80">
        <template #default="{ row }">{{ row.plantedIn ? `第${row.plantedIn}章` : '-' }}</template>
      </el-table-column>
      <el-table-column label="经过" min-width="240">
        <template #default="{ row }">
          <div v-for="(h, i) in row.history" :key="i" class="history-line">
            第{{ h.chapter }}章 {{ ACTION[h.action] }}<template v-if="h.note && h.note !== row.text">：{{ h.note }}</template>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190">
        <template #default="{ row }">
          <el-button link type="primary" size="small" :disabled="locked" @click="editForeshadow(row)">编辑</el-button>
          <el-button link size="small" :disabled="locked" @click="toggleResolved(row)">{{ row.status === 'open' ? '标为已回收' : '重新打开' }}</el-button>
          <el-button link type="danger" size="small" :disabled="locked" @click="remove('foreshadows', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 角色状态 -->
    <div class="section-head">
      <span class="col-title">角色状态（{{ characterRows.length }}）</span>
      <el-button size="small" :icon="Plus" :disabled="locked" @click="editCharacter(null)">新增角色状态</el-button>
    </div>
    <el-table :data="characterRows" size="small" empty-text="暂无角色状态">
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          {{ row.name }}
          <el-tag v-if="row.manual" size="small" type="info" effect="plain">手动</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="state" label="当前状态" min-width="240" />
      <el-table-column label="更新于" width="80">
        <template #default="{ row }">{{ row.updatedIn ? `第${row.updatedIn}章` : '-' }}</template>
      </el-table-column>
      <el-table-column label="变化经过" min-width="240">
        <template #default="{ row }">
          <div v-for="(h, i) in row.history" :key="i" class="history-line">第{{ h.chapter }}章：{{ h.change }}</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button link type="primary" size="small" :disabled="locked" @click="editCharacter(row)">编辑</el-button>
          <el-button link type="danger" size="small" :disabled="locked" @click="remove('characters', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 时间线 -->
    <div class="section-head">
      <span class="col-title">时间线（{{ facts.timeline.length }}）</span>
      <el-button size="small" :icon="Plus" :disabled="locked" @click="editTimeline(null)">新增事件</el-button>
    </div>
    <el-table :data="timelineRows" size="small" empty-text="暂无时间线">
      <el-table-column label="章节" width="80">
        <template #default="{ row }">{{ row.chapter ? `第${row.chapter}章` : '-' }}</template>
      </el-table-column>
      <el-table-column prop="when" label="故事内时间" width="140" />
      <el-table-column label="事件" min-width="300">
        <template #default="{ row }">
          {{ row.event }}
          <el-tag v-if="row.manual" size="small" type="info" effect="plain">手动</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button link type="primary" size="small" :disabled="locked" @click="editTimeline(row)">编辑</el-button>
          <el-button link type="danger" size="small" :disabled="locked" @click="remove('timeline', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="locked" class="muted mt">章节生成 / 处理中，账本暂不能修改</div>

    <!-- 编辑 -->
    <el-dialog v-model="dlg.visible" :title="dlg.title" width="560px">
      <el-form label-width="90px">
        <template v-if="dlg.kind === 'foreshadows'">
          <el-form-item label="伏笔内容" required>
            <el-input v-model="dlg.form.text" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" maxlength="300" show-word-limit />
          </el-form-item>
          <el-form-item label="埋下于">
            第 <el-input-number v-model="dlg.form.plantedIn" :min="0" :max="9999" size="small" controls-position="right" /> 章
          </el-form-item>
          <el-form-item label="状态">
            <el-radio-group v-model="dlg.form.status">
              <el-radio value="open">未回收</el-radio>
              <el-radio value="resolved">已回收</el-radio>
            </el-radio-group>
          </el-form-item>
        </template>
        <template v-else-if="dlg.kind === 'characters'">
          <el-form-item label="角色名" required>
            <el-input v-model="dlg.form.name" maxlength="40" />
          </el-form-item>
          <el-form-item label="当前状态" required>
            <el-input v-model="dlg.form.state" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" maxlength="300" show-word-limit />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="章节">
            第 <el-input-number v-model="dlg.form.chapter" :min="0" :max="9999" size="small" controls-position="right" /> 章
          </el-form-item>
          <el-form-item label="故事内时间">
            <el-input v-model="dlg.form.when" maxlength="60" placeholder="如：入门第三天（可空）" />
          </el-form-item>
          <el-form-item label="事件" required>
            <el-input v-model="dlg.form.event" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" maxlength="300" show-word-limit />
          </el-form-item>
        </template>
      </el-form>
      <div class="muted">保存后此条标记为「手动」：AI 之后只追加经过，不再改它的内容{{ dlg.kind === 'foreshadows' ? '和状态' : '' }}。</div>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDialog">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { getFacts, updateFacts } from '@/api/novelGen'
import { errorMessage } from '@/api/request'

const props = defineProps({
  novelId: { type: String, required: true },
  locked: { type: Boolean, default: false }, // 本工作区有任务在跑：后端会拒绝修改
  reloadKey: { type: [Number, String], default: 0 } // 变化时重新加载（章节完成 / 删除 / 重新提取后）
})
const emit = defineEmits(['open-count'])

const ACTION = { plant: '埋下', advance: '推进', resolve: '回收' }
const facts = ref({ foreshadows: [], characters: {}, timeline: [] })
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const fsFilter = ref('open')

const openCount = computed(() => facts.value.foreshadows.filter((f) => f.status === 'open').length)
watch(openCount, (n) => emit('open-count', n), { immediate: true })
const shownForeshadows = computed(() => facts.value.foreshadows.filter((f) => fsFilter.value === 'all' || f.status === fsFilter.value))
const characterRows = computed(() =>
  Object.entries(facts.value.characters).map(([name, c]) => ({ name, ...c })).sort((a, b) => b.updatedIn - a.updatedIn))
const timelineRows = computed(() => facts.value.timeline.map((t, i) => ({ ...t, _i: i })).reverse())

async function load() {
  loading.value = true
  try {
    const res = await getFacts(props.novelId)
    if (res.code !== 0) throw new Error(res.message)
    facts.value = res.data
    error.value = ''
  } catch (e) {
    error.value = errorMessage(e, '加载故事账本失败')
  } finally {
    loading.value = false
  }
}
watch(() => [props.novelId, props.reloadKey], load, { immediate: true })

async function persist(next, msg = '已保存') {
  saving.value = true
  try {
    const res = await updateFacts(props.novelId, next)
    if (res.code !== 0) throw new Error(res.message)
    facts.value = res.data
    ElMessage.success(msg)
    return true
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
    return false
  } finally {
    saving.value = false
  }
}
const clone = () => JSON.parse(JSON.stringify(facts.value))

const dlg = reactive({ visible: false, kind: '', title: '', target: null, form: {} })
function editForeshadow(row) {
  Object.assign(dlg, { visible: true, kind: 'foreshadows', title: row ? `编辑伏笔 ${row.id}` : '新增伏笔', target: row?.id || null,
    form: row ? { text: row.text, plantedIn: row.plantedIn, status: row.status } : { text: '', plantedIn: 0, status: 'open' } })
}
function editCharacter(row) {
  Object.assign(dlg, { visible: true, kind: 'characters', title: row ? `编辑角色状态：${row.name}` : '新增角色状态', target: row?.name || null,
    form: row ? { name: row.name, state: row.state } : { name: '', state: '' } })
}
function editTimeline(row) {
  Object.assign(dlg, { visible: true, kind: 'timeline', title: row ? '编辑事件' : '新增事件', target: row ? row._i : null,
    form: row ? { chapter: row.chapter, when: row.when, event: row.event } : { chapter: 0, when: '', event: '' } })
}

async function saveDialog() {
  const next = clone()
  const f = dlg.form
  if (dlg.kind === 'foreshadows') {
    if (!f.text.trim()) return ElMessage.warning('请填写伏笔内容')
    const hit = dlg.target && next.foreshadows.find((x) => x.id === dlg.target)
    if (hit) Object.assign(hit, { text: f.text.trim(), plantedIn: f.plantedIn, status: f.status, manual: true })
    else next.foreshadows.push({ id: '', text: f.text.trim(), plantedIn: f.plantedIn, status: f.status, manual: true, history: [] })
  } else if (dlg.kind === 'characters') {
    const name = f.name.trim()
    if (!name || !f.state.trim()) return ElMessage.warning('请填写角色名和当前状态')
    if (name !== dlg.target && next.characters[name]) return ElMessage.warning(`已有角色「${name}」`)
    const old = dlg.target ? next.characters[dlg.target] : null
    if (dlg.target) delete next.characters[dlg.target]
    next.characters[name] = { ...(old || { updatedIn: 0, history: [] }), state: f.state.trim(), manual: true }
  } else {
    if (!f.event.trim()) return ElMessage.warning('请填写事件')
    const item = { chapter: f.chapter, when: f.when.trim(), event: f.event.trim(), manual: true }
    if (dlg.target !== null) next.timeline[dlg.target] = item
    else next.timeline.push(item)
  }
  if (await persist(next)) dlg.visible = false
}

async function toggleResolved(row) {
  const next = clone()
  const hit = next.foreshadows.find((x) => x.id === row.id)
  hit.status = hit.status === 'open' ? 'resolved' : 'open'
  hit.manual = true
  await persist(next, hit.status === 'open' ? '已重新打开' : '已标为回收')
}

async function remove(kind, row) {
  const what = kind === 'foreshadows' ? `伏笔 ${row.id}` : kind === 'characters' ? `角色「${row.name}」的状态` : '这条事件'
  try {
    await ElMessageBox.confirm(`删除${what}？`, '删除', { type: 'warning' })
  } catch {
    return
  }
  const next = clone()
  if (kind === 'foreshadows') next.foreshadows = next.foreshadows.filter((x) => x.id !== row.id)
  else if (kind === 'characters') delete next.characters[row.name]
  else next.timeline.splice(row._i, 1)
  await persist(next, '已删除')
}

defineExpose({ load })
</script>

<style scoped>
.intro {
  line-height: 1.7;
}
.section-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0 6px;
}
.section-head .col-title {
  margin: 0;
}
.col-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.history-line {
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.mt {
  margin-top: 10px;
}
</style>
