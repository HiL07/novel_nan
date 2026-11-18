<template>
  <!-- 世界观分组：AI 提议（只是建议）→ 改组名 / 增删成员 / 不要整组 / 手动新建组 → 下一步整理选中的组 -->
  <el-dialog :model-value="modelValue" title="世界观分组" width="760px" @update:model-value="close">
    <p class="intro">
      把属于同一个主题的实体分成一组（可以跨分类，比如「骑士、骑士侍从、骑士精神、贵族」→ 骑士制度），每组会总结成一张世界观卡。
      AI 的分组只是建议，用的是启用中的大模型；可以改组名、删成员、从下拉里加成员，也可以自己新建一组。
    </p>
    <div class="bar">
      <el-button type="primary" plain :loading="proposing" @click="propose">{{ groups.length ? '重新提议' : '让 AI 提议分组' }}</el-button>
      <el-button :icon="Plus" @click="addGroup">新建空组</el-button>
      <span class="muted">共 {{ entities.length }} 个实体</span>
    </div>
    <el-empty v-if="!groups.length" :description="proposing ? '正在分组…' : '还没有分组'" :image-size="60" />
    <div v-else class="groups">
      <div v-for="(g, i) in groups" :key="g.uid" class="group" :class="{ off: !g.on }">
        <div class="g-head">
          <el-checkbox v-model="g.on" />
          <el-input v-model="g.name" size="small" maxlength="20" placeholder="主题名" style="width: 180px" />
          <span class="muted ellipsis" :title="g.reason">{{ g.reason }}</span>
          <el-button link type="danger" :icon="Delete" @click="groups.splice(i, 1)" />
        </div>
        <div class="g-members">
          <el-tag v-for="k in g.members" :key="k" size="small" closable @close="g.members = g.members.filter((x) => x !== k)">
            {{ nameOf(k) }}<span class="cat"> · {{ catOf(k) }}</span>
          </el-tag>
          <el-select
            size="small"
            filterable
            placeholder="加成员"
            style="width: 160px"
            :model-value="null"
            @update:model-value="(k) => k && !g.members.includes(k) && g.members.push(k)"
          >
            <el-option v-for="e in entities" :key="e.key" :label="`${e.name}（${categoryOf(e.category)?.label || e.category}）`" :value="e.key" />
          </el-select>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :disabled="!chosen.length" @click="next">下一步：整理选中的 {{ chosen.length }} 组</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { categoryOf } from '@/api/material'
import { worldGroups } from '@/api/novel'
import { errorMessage } from '@/api/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  extractId: { type: Number, required: true },
  entities: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:modelValue', 'confirm'])

const groups = ref([]) // [{uid, name, members: [key], reason, on}]
const proposing = ref(false)
let uid = 0
const byKey = computed(() => Object.fromEntries(props.entities.map((e) => [e.key, e])))
const nameOf = (k) => byKey.value[k]?.name || k
const catOf = (k) => categoryOf(byKey.value[k]?.category)?.label || ''
const chosen = computed(() => groups.value.filter((g) => g.on && g.name.trim() && g.members.length))

function close() {
  emit('update:modelValue', false)
}

async function propose() {
  proposing.value = true
  try {
    const res = await worldGroups(props.extractId)
    if (res.code !== 0) throw new Error(res.message)
    const list = (res.data?.groups || []).map((g) => ({ uid: ++uid, name: g.name, members: [...g.members], reason: g.reason || '', on: true }))
    groups.value = list
    ElMessage.success(list.length ? `AI 提议了 ${list.length} 组，看看哪些合适` : 'AI 没找到合适的分组，可以自己新建')
  } catch (e) {
    ElMessage.error(errorMessage(e, '世界观分组失败'))
  } finally {
    proposing.value = false
  }
}

function addGroup() {
  groups.value.unshift({ uid: ++uid, name: '', members: [], reason: '手动新建', on: true })
}

function next() {
  emit('confirm', chosen.value.map((g) => ({ name: g.name.trim(), members: [...g.members] })))
  close()
}
</script>

<style scoped>
.intro {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ellipsis {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.groups {
  max-height: 55vh;
  overflow: auto;
}
.group {
  padding: 8px 10px;
  margin-bottom: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}
.group.off {
  opacity: 0.55;
}
.g-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.g-members {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.cat {
  color: var(--el-text-color-secondary);
}
</style>
