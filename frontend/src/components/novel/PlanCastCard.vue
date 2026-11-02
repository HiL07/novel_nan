<template>
  <!-- 自动规划里的一张人物卡 / 元素卡（设定这一步的主角、骨架这一步的配角和势力地点…共用） -->
  <div class="card">
    <template v-if="kind === 'character'">
      <div class="card-head">
        <el-input v-model="item.name" size="small" style="width: 110px" placeholder="名字" />
        <el-tag v-if="lead" size="small" type="danger" effect="plain">主角</el-tag>
        <el-select v-else v-model="item.role" size="small" style="width: 110px">
          <el-option v-for="r in ROLE_LABELS.filter((x) => x !== '主角')" :key="r" :label="r" :value="r" />
        </el-select>
        <template v-if="!lead">
          <span class="muted">第</span>
          <el-input-number v-model="item.appearFrom" size="small" :min="1" :max="9999" controls-position="right" style="width: 86px" />
          <span class="muted">章登场</span>
          <span v-if="stageName" class="muted">（{{ stageName }}）</span>
        </template>
        <el-input v-model="item.tagline" size="small" style="flex: 1; min-width: 160px" placeholder="一句话人设" />
        <el-button v-if="!lead" link type="danger" size="small" @click="$emit('remove')">删除</el-button>
      </div>
      <div class="grid3">
        <el-input v-model="item.goal" size="small"><template #prepend>想要</template></el-input>
        <el-input v-model="item.fear" size="small"><template #prepend>缺陷 / 恐惧</template></el-input>
        <el-input v-model="item.secret" size="small"><template #prepend>秘密</template></el-input>
      </div>
      <el-collapse class="more"><el-collapse-item :title="lead ? '更多（性格、能力、背景、成长）' : '更多（性格、能力、背景、成长、与主角关系）'">
        <div class="grid2">
          <el-input :model-value="(item.personality || []).join('、')" size="small" @update:model-value="item.personality = split($event)">
            <template #prepend>性格</template></el-input>
          <el-input :model-value="(item.abilities || []).join('、')" size="small" @update:model-value="item.abilities = split($event)">
            <template #prepend>能力</template></el-input>
          <el-input v-if="!lead" v-model="item.relationToLead" size="small"><template #prepend>与主角</template></el-input>
          <el-input v-model="item.arc" size="small"><template #prepend>成长弧光</template></el-input>
        </div>
        <el-input v-model="item.background" type="textarea" :rows="2" size="small" placeholder="背景故事" class="mt" />
      </el-collapse-item></el-collapse>
    </template>

    <template v-else>
      <div class="card-head">
        <el-tag size="small">{{ ELEMENT_LABELS[item.category] }}</el-tag>
        <el-input v-model="item.name" size="small" style="width: 150px" />
        <span class="muted">量级</span>
        <el-input-number v-model="item.tier" size="small" :min="1" :max="5" controls-position="right" style="width: 76px" />
        <span class="muted">第</span>
        <el-input-number v-model="item.appearFrom" size="small" :min="1" :max="9999" controls-position="right" style="width: 86px" />
        <span class="muted">章登场</span>
        <span v-if="stageName" class="muted">（{{ stageName }}）</span>
        <el-button link type="danger" size="small" @click="$emit('remove')">删除</el-button>
      </div>
      <div v-for="(v, k) in item.fields" :key="k" class="field-line">
        <span class="muted">{{ FIELD_LABELS[k] || k }}：</span>
        <el-input :model-value="Array.isArray(v) ? v.join('、') : v" size="small"
                  @update:model-value="item.fields[k] = Array.isArray(v) ? split($event) : $event" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ELEMENT_LABELS, ROLE_LABELS } from '@/api/novelPlan'

defineProps({
  item: { type: Object, required: true },
  kind: { type: String, default: 'character' },   // character | element
  lead: { type: Boolean, default: false },         // 主角：不显示登场章节、角色固定
  stageName: { type: String, default: '' }         // 登场章节落在骨架的哪个阶段
})
defineEmits(['remove'])

const FIELD_LABELS = { stance: '立场', feature: '特点', kind: '类型', detail: '描述', effect: '作用', appearance: '外形',
  abilities: '能力', weakness: '弱点', habitat: '栖息地' }
const split = (s) => String(s || '').split(/[、,，;；]/).map((x) => x.trim()).filter(Boolean)
</script>

<style scoped>
.card { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px; margin-bottom: 10px; }
.card-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }
.grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.grid2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.more { margin-top: 6px; }
.mt { margin-top: 8px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.field-line { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.field-line .muted { width: 60px; flex-shrink: 0; }
</style>
