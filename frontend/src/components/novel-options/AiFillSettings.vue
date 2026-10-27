<template>
  <el-popover placement="bottom-end" :width="460" trigger="click">
    <template #reference>
      <el-button :icon="MagicStick">
        AI 填写设置<span class="ref-hint">{{ summary }}</span>
      </el-button>
    </template>
    <div class="ai-settings">
      <div class="row-title">用哪个模型</div>
      <el-radio-group v-model="cfg.source" size="small">
        <el-radio-button value="api" :disabled="!apiModel">大模型（API）</el-radio-button>
        <el-radio-button value="local" :disabled="!localModels.length">本地模型</el-radio-button>
        <el-radio-button value="gguf" :disabled="!llama" :title="llama ? '' : '先到「llama.cpp」页启动 GGUF 模型'">GGUF</el-radio-button>
        <el-radio-button value="remote" disabled>远程模型（即将支持）</el-radio-button>
      </el-radio-group>
      <div v-if="cfg.source === 'api'" class="muted">{{ apiModel ? `${apiModel.name} · ${apiModel.model}` : '没有可用的大模型：请先在「模型配置」中启用' }}</div>
      <div v-else-if="cfg.source === 'gguf'" class="muted">{{ llama ? `llama.cpp · ${llama.name}` : 'llama.cpp 没有运行：请先到「llama.cpp」页启动' }}</div>
      <div v-else class="row">
        <el-select v-model="cfg.baseId" size="small" style="width: 190px" @change="cfg.adapterId = ''">
          <el-option v-for="m in localModels" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-select v-model="cfg.adapterId" size="small" style="width: 190px" placeholder="不使用适配器">
          <el-option label="不使用适配器（基础模型）" value="" />
          <el-option v-for="a in baseAdapters" :key="a.id" :label="`适配器：${a.name}`" :value="a.id" />
        </el-select>
      </div>

      <div class="muted">
        {{ cfg.source === 'local' || cfg.source === 'gguf' ? '本地模型 / GGUF 一次只能处理一个 AI 请求，其他 AI 按钮会等它完成' : '大模型可以同时生成多处，只有会写到同一处的按钮暂时不可用' }}
      </div>

      <div class="row-title">文本项的两个按钮</div>
      <div class="muted usage">
        <div><b>AI 润色</b>：保留框里已写的内容，在此基础上扩写、补充细节（框里为空时不可用）。</div>
        <div><b>AI 生成</b>：把框里的文字当作大致方向（可以留空），写出新的内容替换。</div>
        <div>两者都会参考其他设定保持一致，写入后可以「撤销」。标签只有「AI 生成」。</div>
        <div><b>单选 / 多选</b>：点「自定义」，在框里写想法，再用 AI 润色 / 生成一个新选项。</div>
        <div><b>每个 AI 按钮</b>（含 AI 生成 N 个、AI 补全、AI 创建角色）点击后都会先弹出素材选择：不选 = 只按框里的内容；选了 = 按素材 + 框里的内容。</div>
      </div>

      <div class="row-title">
        补充要求（可选）
        <el-button link type="primary" size="small" :icon="MagicStick" :loading="suggesting" @click="runSuggest">
          {{ cfg.hint.trim() ? 'AI 细化' : 'AI 给几个方向' }}
        </el-button>
      </div>
      <el-input v-model="cfg.hint" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" maxlength="500" placeholder="如：整体基调压抑、反派要有合理动机、情节多反转" />
      <div v-if="suggestions.length" class="suggestions">
        <div v-for="(d, i) in suggestions" :key="i" class="suggestion" title="点击采用" @click="useSuggestion(d)">
          <b v-if="d.label">{{ d.label }}：</b>{{ d.direction }}
        </div>
      </div>

      <div class="row-title">参考素材</div>
      <div class="row">
        <el-button size="small" :icon="Collection" @click="pickerVisible = true">从素材库选择</el-button>
        <el-switch v-model="cfg.autoMaterials" size="small" active-text="自动匹配" />
      </div>
      <div class="muted">
        这里选的素材会在每次 AI 生成前的素材选择里<b>预先勾上</b>（可以取消）。{{ cfg.autoMaterials ? '自动匹配：按「位置 + 框里内容 + 补充要求」本地检索（向量 + 关键词 + 重排，不花 token），预先勾选相关度够高的最多 5 条' : '' }}
      </div>
      <div v-if="cfg.picked.length" class="chips">
        <el-tag v-for="m in cfg.picked" :key="m.id" size="small" closable @close="cfg.picked = cfg.picked.filter((x) => x.id !== m.id)">
          {{ categoryOf(m.category)?.label }} · {{ m.title }}
        </el-tag>
      </div>
      <BlockedBooksSelect :model-value="blockedBooks" @update:model-value="(v) => emit('update:blockedBooks', v)" />
      <div class="muted">屏蔽的书不参与选择与自动匹配（「保留」的素材除外），与「AI 构思」共用</div>
    </div>
    <MaterialPicker v-model="pickerVisible" pick-only :exclude-books="blockedBooks" @apply="onPick" />
  </el-popover>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Collection, MagicStick } from '@element-plus/icons-vue'
import MaterialPicker from '@/components/material/MaterialPicker.vue'
import BlockedBooksSelect from '@/components/material/BlockedBooksSelect.vue'
import { categoryOf } from '@/api/material'

/** AI 填写设定的公共设置：cfg 由 SettingsEditor 持有（reactive），这里直接修改；
 *  blockedBooks：屏蔽的来源书；suggest(当前补充要求) → [{label, direction}]：AI 给补充要求的方向 */
const props = defineProps({
  cfg: { type: Object, required: true },
  apiModel: { type: Object, default: null },
  llama: { type: Object, default: null }, // 运行中的 llama.cpp（GGUF）；null = 没运行，不能选
  localModels: { type: Array, default: () => [] },
  adapters: { type: Array, default: () => [] },
  blockedBooks: { type: Array, default: () => [] },
  suggest: { type: Function, default: null }
})
const emit = defineEmits(['update:blockedBooks'])

const pickerVisible = ref(false)
const suggesting = ref(false)
const suggestions = ref([])

async function runSuggest() {
  if (!props.suggest) return
  suggesting.value = true
  try {
    suggestions.value = await props.suggest(props.cfg.hint)
  } finally {
    suggesting.value = false
  }
}

function useSuggestion(d) {
  props.cfg.hint = (d.label ? `${d.label}：${d.direction}` : d.direction).slice(0, 500)
  suggestions.value = []
}
const baseAdapters = computed(() => props.adapters.filter((a) => a.compat === 'ok' && a.matchedBaseId === props.cfg.baseId))
const summary = computed(() => {
  const c = props.cfg
  const model = c.source === 'api' ? '大模型' : c.source === 'gguf' ? 'GGUF' : `本地${c.adapterId ? '+适配器' : ''}`
  const mats = c.picked.length ? ` · 素材 ${c.picked.length}` : ''
  const blocked = props.blockedBooks.length ? ` · 屏蔽 ${props.blockedBooks.length} 本` : ''
  return `（${model}${mats}${c.autoMaterials ? ' · 自动匹配' : ''}${blocked}）`
})

function onPick(list) {
  const ids = new Set(props.cfg.picked.map((m) => m.id))
  props.cfg.picked.push(...list.filter((m) => !ids.has(m.id)))
}
</script>

<style scoped>
.ref-hint {
  margin-left: 2px;
  font-size: 12px;
  color: #909399;
}
.usage {
  line-height: 1.6;
}
.ai-settings {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.row-title {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.row,
.chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.suggestions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 220px;
  overflow: auto;
}
.suggestion {
  padding: 5px 8px;
  font-size: 12px;
  line-height: 1.5;
  background: #f7f8fa;
  border-radius: 4px;
  cursor: pointer;
}
.suggestion:hover {
  background: var(--el-color-primary-light-9);
}
</style>
