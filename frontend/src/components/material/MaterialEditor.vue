<template>
  <el-drawer :model-value="modelValue" :title="isPortable ? '编辑架空版' : form.id ? '编辑素材' : '新建素材'" :size="isPortable ? '640px' : '560px'" @update:model-value="close">
    <el-alert v-if="isPortable" :type="originNote.type" :closable="false" show-icon class="port-alert">
      <template #title>
        架空版 · 架空工作区「<el-button link type="primary" :disabled="!form.source.workspaceId" @click="goWorkspace(form.source.workspaceId)">{{ form.source.workspaceTitle || '已删除' }}</el-button>」由原素材「<el-button link type="primary" :disabled="form.originState === 'deleted'" @click="emit('open-material', form.source.originId)">{{ form.source.originTitle }}</el-button>」生成
        <template v-if="form.source.originBook">（{{ /^《/.test(form.source.originBook) ? form.source.originBook : `《${form.source.originBook}》` }}）</template>
      </template>
      <div>{{ originNote.text }}</div>
    </el-alert>
    <el-form label-width="80px">
      <el-form-item label="分类" required>
        <el-select v-model="form.category" style="width: 160px">
          <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
        </el-select>
        <el-input v-model="form.subtype" placeholder="细分类型（可选）" maxlength="32" style="width: 180px; margin-left: 8px" />
      </el-form-item>
      <el-form-item label="名称" required><el-input v-model="form.title" maxlength="100" /></el-form-item>
      <el-form-item v-if="!isPortable" label="概括"><el-input v-model="form.summary" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" maxlength="300" show-word-limit /></el-form-item>
      <el-form-item v-if="!isPortable" label="属性"><AttributeEditor v-model="form.attributes" :category="form.category" style="width: 100%" /></el-form-item>
      <el-form-item label="标签"><el-input-tag v-model="form.tags" placeholder="回车添加" :max="12" /></el-form-item>
      <el-form-item label="量级">
        <el-select v-model="tier" clearable placeholder="未标（可在素材库「补全量级」）" style="width: 240px">
          <el-option v-for="t in TIERS" :key="t.value" :label="t.label" :value="t.value" :title="t.desc" />
        </el-select>
        <span class="tier-note">
          <template v-if="form.profile?.tierBy === 'user'">作者手改，AI 不会覆盖</template>
          <template v-else-if="form.profile?.tierReason">AI：{{ form.profile.tierReason }}</template>
          <template v-if="form.profile?.bookPos != null"> · 原书 {{ Math.round(form.profile.bookPos * 100) }}% 处首次出现</template>
        </span>
      </el-form-item>
      <el-form-item label="来源书">
        <el-input v-model="form.sourceBook" placeholder="空 = 手动添加；填书名可按书筛选 / 屏蔽 / 删除" maxlength="100" style="width: 280px" />
        <el-checkbox v-model="form.pinned" class="pin-check">保留</el-checkbox>
        <div class="pin-tip">保留的素材不会被「按来源书删除」删掉，在 AI 生成中屏蔽它的来源书时也照常可用</div>
      </el-form-item>
      <el-form-item v-if="!isPortable" label="详细">
        <el-input v-model="form.detail" type="textarea" :autosize="{ minRows: 4, maxRows: 12 }" placeholder="详细描述、备注、用法设想…" />
      </el-form-item>
      <el-form-item v-if="isPortable" label="架空档案">
        <div class="port">
          <div class="muted-line">名称、概括、详细和属性都由这份档案生成，改完点下面的「保存」</div>
          <PortableEditor v-model="portable" :card="portCard" />
        </div>
      </el-form-item>
      <el-form-item v-else-if="form.id" label="架空版">
        <div class="port">
          <div v-for="p in form.portables || []" :key="p.id" class="port-head">
            <el-button link type="primary" @click="emit('open-material', p.id)">{{ p.title }}</el-button>
            <span class="muted-line">来自架空工作区「{{ p.workspaceTitle || '已删除' }}」</span>
          </div>
          <div v-if="!form.portables?.length" class="muted-line">还没有架空版：加入一个架空工作区，在那里加工（原素材不动；不同工作区的架空版互相独立）</div>
          <div class="port-head">
            <el-select v-model="joinWs" size="small" placeholder="加入架空工作区…" style="width: 220px" @visible-change="(v) => v && loadWs()">
              <el-option v-for="w in wsList" :key="w.id" :label="w.title" :value="w.id" />
            </el-select>
            <el-button size="small" :disabled="!joinWs" :loading="joining" @click="joinWorkspace">加入待加工</el-button>
          </div>
        </div>
      </el-form-item>
      <el-form-item v-if="form.source?.resonance" label="关系图">
        <ResonanceView :data="resonanceData" :portable="isPortable ? portable : null" style="width: 100%" />
      </el-form-item>
      <el-form-item v-if="form.source && form.source.type === 'extract'" label="来源">
        <div class="source">
          <div>{{ form.source.fileName }}<template v-if="form.source.chapters?.length"> · {{ form.source.chapters.join('、') }}</template></div>
          <div v-if="form.source.excerpt && !form.source.facts?.length" class="excerpt">“{{ form.source.excerpt }}”</div>
          <FactList v-if="form.source.facts?.length" :facts="form.source.facts" />
        </div>
      </el-form-item>
      <el-form-item v-if="form.source && form.source.type === 'merge'" label="可选版本">
        <div class="variants">
          <div class="muted-line">
            由 {{ form.source.variants?.length || 0 }} 条素材合并而来：上面是共性，下面每条是一种写法（成员不再单独出现在素材库里；「拆分」可还原）。
            AI 使用时可以让它选一个版本、只用某一版，或把几种写法融合
          </div>
          <div v-for="(v, i) in form.source.variants || []" :key="v.id" class="variant">
            <div class="variant-head" @click="openVariant[v.id] = !openVariant[v.id]">
              <el-icon><component :is="openVariant[v.id] ? 'ArrowDown' : 'ArrowRight'" /></el-icon>
              <b>{{ MARKS[i] || i + 1 }} {{ v.label || `版本 ${i + 1}` }}</b>
              <span class="book">{{ v.book ? `《${v.book}》` : '手动' }}</span>
              <span>{{ v.note || memberOf(v.id)?.summary || '' }}</span>
            </div>
            <div v-if="openVariant[v.id]" class="variant-body">
              <template v-if="memberOf(v.id)">
                <div><b>{{ memberOf(v.id).title }}</b>：{{ memberOf(v.id).summary || '（无概括）' }}</div>
                <div v-for="(val, k) in memberOf(v.id).attributes || {}" :key="k" class="muted-line">
                  {{ k }}：{{ Array.isArray(val) ? val.join('、') : val }}
                </div>
                <div v-if="memberOf(v.id).detail" class="muted-line">{{ memberOf(v.id).detail }}</div>
                <FactList v-if="memberOf(v.id).source?.facts?.length" :facts="memberOf(v.id).source.facts" />
              </template>
              <span v-else class="muted-line">原素材已删除</span>
            </div>
          </div>
        </div>
      </el-form-item>
      <el-form-item v-if="form.id" label="使用">已应用到写作设定 {{ form.useCount || 0 }} 次 · 更新于 {{ form.updateTime }}</el-form-item>
    </el-form>
    <template #footer>
      <el-button v-if="form.id" type="danger" plain :icon="Delete" @click="onDelete">删除</el-button>
      <el-button v-if="form.source?.type === 'merge'" plain @click="onUnmerge">拆分</el-button>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import AttributeEditor from './AttributeEditor.vue'
import FactList from './FactList.vue'
import PortableEditor from './PortableEditor.vue'
import ResonanceView from './ResonanceView.vue'
import { useRouter } from 'vue-router'
import { MATERIAL_CATEGORIES, TIERS, deleteMaterial, listPortableWs, portableWsEnqueue, saveMaterial, unmergeMaterial } from '@/api/material'
import { errorMessage } from '@/api/request'

/** material 为空则新建（可通过 defaultCategory 指定分类） */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  material: { type: Object, default: null },
  defaultCategory: { type: String, default: 'world' }
})
const emit = defineEmits(['update:modelValue', 'saved', 'deleted', 'open-material'])

const blank = () => ({
  id: null, category: props.defaultCategory || 'world', subtype: '', title: '', summary: '', attributes: {}, tags: [], detail: '',
  source: null, sourceBook: '', pinned: false, members: [], profile: null, portables: [], originState: null
})
const form = reactive(blank())
const MARKS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫'
const openVariant = reactive({})
const memberOf = (id) => (form.members || []).find((m) => m.id === id)
const saving = ref(false)
// 量级：改了就记作者手改（tierBy = user，Java 端再按「和原来不同」判断一次）
const tier = computed({
  get: () => form.profile?.tier ?? null,
  set: (v) => {
    form.profile = { ...(form.profile || {}), tier: v || null, tierBy: 'user' }
  }
})

/* 架空版（source.type = portable）：档案 profile.portable 是唯一来源，名称 / 概括 / 详细 / 属性由后端从档案拼出 */
const isPortable = computed(() => form.source?.type === 'portable')
const ORIGIN_NOTE = {
  ok: { type: 'info', text: '原素材不动；在架空工作区里对原素材点「重做」会更新这一条。' },
  changed: { type: 'warning', text: '原素材在生成架空版之后改过，档案可能对不上，可以在架空工作区里重做。' },
  merged: { type: 'warning', text: '原素材已经并入别的条目（精炼合并），可以把合并后的条目加入架空工作区再加工。' },
  deleted: { type: 'warning', text: '原素材已删除。' }
}
const originNote = computed(() => ORIGIN_NOTE[form.originState] || ORIGIN_NOTE.ok)
const resonanceData = computed(() => ({ ...(form.source?.resonance || {}), summary: form.summary }))
const portable = computed({
  get: () => form.profile?.portable || null,
  set: (v) => {
    form.profile = { ...(form.profile || {}), portable: v }
  }
})
const portCard = computed(() => ({ title: form.title, category: form.category, data: { nodes: form.source?.resonance?.nodes || [] } }))
/* 原素材：加入某个架空工作区的待加工 */
const router = useRouter()
const wsList = ref([])
const joinWs = ref(null)
const joining = ref(false)
async function loadWs() {
  try {
    const res = await listPortableWs()
    wsList.value = res.code === 0 ? res.data || [] : []
  } catch {
    wsList.value = []
  }
}
async function joinWorkspace() {
  joining.value = true
  try {
    const res = await portableWsEnqueue(joinWs.value, { ids: [form.id], redo: true })
    if (res.code !== 0) throw new Error(res.message)
    const title = wsList.value.find((w) => w.id === joinWs.value)?.title
    ElMessage.success(res.data.added || res.data.requeued ? `已加入「${title}」的待加工，去工作区点「开始」` : `「${title}」里已经有这条了`)
  } catch (e) {
    ElMessage.error(errorMessage(e, '加入失败'))
  } finally {
    joining.value = false
  }
}
function goWorkspace(id) {
  close()
  router.push(`/material/portable/${id}`)
}

watch(() => props.modelValue, (open) => {
  if (open) Object.assign(form, blank(), props.material ? JSON.parse(JSON.stringify(props.material)) : {})
})
// 打开着的时候换了一条（原素材 ↔ 架空版互相跳转）
watch(() => props.material, (m) => {
  if (props.modelValue && m) Object.assign(form, blank(), JSON.parse(JSON.stringify(m)))
})

function close() {
  emit('update:modelValue', false)
}

async function onSave() {
  if (!form.title.trim()) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    const { members, portables, originState, ...body } = form // 成员 / 架空信息只用于展示，不提交
    if (isPortable.value && body.profile?.portable) body.profile = { ...body.profile, portable: { ...body.profile.portable, title: form.title } }
    const res = await saveMaterial({ ...body, tags: form.tags || [], sourceBook: form.sourceBook || '', pinned: !!form.pinned })
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success('已保存')
    emit('saved', res.data)
    close()
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function onUnmerge() {
  try {
    await ElMessageBox.confirm(`拆分「${form.title}」？主条目会删除，${form.source.variants?.length || 0} 条成员回到素材库。`, '拆分', { type: 'warning' })
  } catch {
    return
  }
  try {
    const res = await unmergeMaterial(form.id)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success(`已拆分，${res.data.restored} 条素材回到素材库`)
    emit('deleted', form.id)
    close()
  } catch (e) {
    ElMessage.error(errorMessage(e, '拆分失败'))
  }
}

async function onDelete() {
  try {
    await ElMessageBox.confirm(
      `删除素材「${form.title}」？已应用到工作区的内容不受影响。` + (form.source?.type === 'merge' ? '它的成员会回到素材库。' : ''),
      '删除',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const res = await deleteMaterial(form.id)
    if (res.code !== 0) throw new Error(res.message)
    ElMessage.success('已删除')
    emit('deleted', form.id)
    close()
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}
</script>

<style scoped>
.tier-note { margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.variants {
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.variant {
  margin-top: 4px;
}
.variant-head {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.variant-body {
  margin: 2px 0 6px 20px;
  padding: 6px 8px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
}
.variant .book {
  color: var(--el-color-primary);
  font-size: 12px;
}
.muted-line {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.source {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.pin-check {
  margin-left: 12px;
}
.pin-tip {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}
.excerpt {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.port {
  width: 100%;
}
.port-alert {
  margin-bottom: 12px;
}
.port-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
</style>
