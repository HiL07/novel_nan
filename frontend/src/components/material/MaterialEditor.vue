<template>
  <el-drawer :model-value="modelValue" :title="form.id ? '编辑素材' : '新建素材'" size="560px" @update:model-value="close">
    <el-form label-width="80px">
      <el-form-item label="分类" required>
        <el-select v-model="form.category" style="width: 160px">
          <el-option v-for="c in MATERIAL_CATEGORIES" :key="c.code" :label="c.label" :value="c.code" />
        </el-select>
        <el-input v-model="form.subtype" placeholder="细分类型（可选）" maxlength="32" style="width: 180px; margin-left: 8px" />
      </el-form-item>
      <el-form-item label="名称" required><el-input v-model="form.title" maxlength="100" /></el-form-item>
      <el-form-item label="概括"><el-input v-model="form.summary" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" maxlength="300" show-word-limit /></el-form-item>
      <el-form-item label="属性"><AttributeEditor v-model="form.attributes" :category="form.category" style="width: 100%" /></el-form-item>
      <el-form-item label="标签"><el-input-tag v-model="form.tags" placeholder="回车添加" :max="12" /></el-form-item>
      <el-form-item label="来源书">
        <el-input v-model="form.sourceBook" placeholder="空 = 手动添加；填书名可按书筛选 / 屏蔽 / 删除" maxlength="100" style="width: 280px" />
        <el-checkbox v-model="form.pinned" class="pin-check">保留</el-checkbox>
        <div class="pin-tip">保留的素材不会被「按来源书删除」删掉，在 AI 生成中屏蔽它的来源书时也照常可用</div>
      </el-form-item>
      <el-form-item label="详细">
        <el-input v-model="form.detail" type="textarea" :autosize="{ minRows: 4, maxRows: 12 }" placeholder="详细描述、备注、用法设想…" />
      </el-form-item>
      <el-form-item v-if="form.source && form.source.type === 'extract'" label="来源">
        <div class="source">
          <div>{{ form.source.fileName }}<template v-if="form.source.chapters?.length"> · {{ form.source.chapters.join('、') }}</template></div>
          <div v-if="form.source.excerpt" class="excerpt">“{{ form.source.excerpt }}”</div>
        </div>
      </el-form-item>
      <el-form-item v-if="form.id" label="使用">已应用到写作设定 {{ form.useCount || 0 }} 次 · 更新于 {{ form.updateTime }}</el-form-item>
    </el-form>
    <template #footer>
      <el-button v-if="form.id" type="danger" plain :icon="Delete" @click="onDelete">删除</el-button>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-drawer>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import AttributeEditor from './AttributeEditor.vue'
import { MATERIAL_CATEGORIES, deleteMaterial, saveMaterial } from '@/api/material'
import { errorMessage } from '@/api/request'

/** material 为空则新建（可通过 defaultCategory 指定分类） */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  material: { type: Object, default: null },
  defaultCategory: { type: String, default: 'world' }
})
const emit = defineEmits(['update:modelValue', 'saved', 'deleted'])

const blank = () => ({
  id: null, category: props.defaultCategory || 'world', subtype: '', title: '', summary: '', attributes: {}, tags: [], detail: '',
  source: null, sourceBook: '', pinned: false
})
const form = reactive(blank())
const saving = ref(false)

watch(() => props.modelValue, (open) => {
  if (open) Object.assign(form, blank(), props.material ? JSON.parse(JSON.stringify(props.material)) : {})
})

function close() {
  emit('update:modelValue', false)
}

async function onSave() {
  if (!form.title.trim()) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    const res = await saveMaterial({ ...form, tags: form.tags || [], sourceBook: form.sourceBook || '', pinned: !!form.pinned })
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

async function onDelete() {
  try {
    await ElMessageBox.confirm(`删除素材「${form.title}」？已应用到工作区的内容不受影响。`, '删除', { type: 'warning' })
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
.source {
  font-size: 13px;
  color: #606266;
}
.pin-check {
  margin-left: 12px;
}
.pin-tip {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}
.excerpt {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
</style>
