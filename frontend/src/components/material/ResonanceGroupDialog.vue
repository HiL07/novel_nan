<template>
  <!-- 共鸣素材分组：AI 按主题给卡片分组（只是建议）→ 改主题名 / 增删卡片 / 不要整组 / 手动新建 → 下一步生成 -->
  <el-dialog :model-value="modelValue" title="共鸣素材：按主题关联卡片" width="780px" @update:model-value="close">
    <p class="intro">
      把同一个主题下相关的卡片放一组（比如魔法体系：环级、施法材料、精神力、法师组织、魔法书籍……），每组会生成一张共鸣素材：
      关系图、联动规则（改了一个其他哪些要跟着改）、综合描述，以及融入别的世界观的指南。AI 的分组只是建议，用启用中的大模型；每组至少 2 张卡。
    </p>
    <div class="bar">
      <el-button type="primary" plain :loading="proposing" @click="propose">{{ groups.length ? '重新提议' : '让 AI 提议分组' }}</el-button>
      <el-button :icon="Plus" @click="addGroup">新建空组</el-button>
      <span class="muted">可用 {{ cards.length }} 张卡（世界观卡 / 体系卡 / 实体卡）</span>
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
          <el-tag v-for="id in g.cardIds" :key="id" size="small" closable @close="g.cardIds = g.cardIds.filter((x) => x !== id)">
            {{ byId[id]?.title || id }}<span class="cat"> · {{ kindText(byId[id]) }}</span>
          </el-tag>
          <el-select
            size="small"
            filterable
            placeholder="加卡片"
            style="width: 180px"
            :model-value="null"
            @update:model-value="(id) => id && !g.cardIds.includes(id) && g.cardIds.push(id)"
          >
            <el-option v-for="c in cards" :key="c.id" :label="`${c.title}（${kindText(c)}）`" :value="c.id" />
          </el-select>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :disabled="!chosen.length" @click="next">下一步：生成选中的 {{ chosen.length }} 组</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { categoryOf } from '@/api/material'
import { resonanceGroups } from '@/api/novel'
import { errorMessage } from '@/api/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  extractId: { type: Number, required: true },
  cards: { type: Array, default: () => [] } // 可以关联的卡片（世界观卡 / 体系卡 / 实体卡）
})
const emit = defineEmits(['update:modelValue', 'confirm'])

const KIND = { world: '世界观卡', system: '体系卡', entity: '实体' }
const kindText = (c) => (c ? (c.kind === 'entity' ? `实体·${categoryOf(c.category)?.label || c.category}` : KIND[c.kind] || c.kind) : '')
const groups = ref([]) // [{uid, name, cardIds, reason, on}]
const proposing = ref(false)
let uid = 0
const byId = computed(() => Object.fromEntries(props.cards.map((c) => [c.id, c])))
const chosen = computed(() => groups.value.filter((g) => g.on && g.name.trim() && g.cardIds.length >= 2))

function close() {
  emit('update:modelValue', false)
}

async function propose() {
  proposing.value = true
  try {
    const res = await resonanceGroups(props.extractId)
    if (res.code !== 0) throw new Error(res.message)
    const list = (res.data?.groups || []).map((g) => ({ uid: ++uid, name: g.name, cardIds: [...g.cardIds], reason: g.reason || '', on: true }))
    groups.value = list
    ElMessage.success(list.length ? `AI 提议了 ${list.length} 个主题，看看哪些合适` : 'AI 没找到合适的主题，可以自己新建')
  } catch (e) {
    ElMessage.error(errorMessage(e, '共鸣分组失败'))
  } finally {
    proposing.value = false
  }
}

function addGroup() {
  groups.value.unshift({ uid: ++uid, name: '', cardIds: [], reason: '手动新建', on: true })
}

function next() {
  emit('confirm', chosen.value.map((g) => ({ name: g.name.trim(), cardIds: [...g.cardIds] })))
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
