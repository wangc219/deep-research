<template>
  <a-modal
    :open="open"
    class="database-create-flow-modal"
    :width="840"
    :closable="false"
    :mask-closable="!creating"
    :keyboard="!creating"
    :footer="null"
    destroy-on-close
    @cancel="handleCancel"
  >
    <div class="create-flow-shell">
      <header class="create-flow-header">
        <div class="header-left">
          <div class="create-flow-icon"><DatabaseZap :size="18" /></div>
          <h2>新建知识库</h2>
        </div>
        <div class="header-right">
          <div class="step-indicator-pill">
            <span class="step-indicator-num">{{ zhipuSelected ? '1/1' : `${currentStep + 1}/${stepLabels.length}` }}</span>
            <span class="step-divider">·</span>
            <span class="step-indicator-label">{{ zhipuSelected ? '连接' : stepLabels[currentStep] }}</span>
          </div>
          <button
            type="button"
            class="modal-close-btn"
            :disabled="creating"
            aria-label="关闭"
            @click="handleCancel"
          >
            <X :size="16" />
          </button>
        </div>
      </header>

      <main class="create-flow-body">
        <section v-if="currentStep === 0" class="flow-section">
          <div v-if="!zhipuSelected" class="form-section">
            <label for="database-create-name">知识库名称 <b>*</b></label>
            <a-input
              id="database-create-name"
              v-model:value="form.name"
              placeholder="例如：产品资料库"
            />
          </div>
          <div v-if="!zhipuSelected" class="form-section classification-section">
            <div class="classification-heading">
              <div>
                <label>知识库主分类</label>
                <small>按组织分类树选择一级或子级分类；后续来源和文档只能挂在该分支内。</small>
              </div>
              <a-button
                v-if="userStore.isAdmin"
                size="small"
                :disabled="categoryLoading"
                @click="openCategoryCreate"
              >
                新建分类节点
              </a-button>
            </div>
            <a-tree-select
              v-model:value="form.category_id"
              allow-clear
              show-search
              tree-default-expand-all
              tree-node-filter-prop="title"
              :loading="categoryLoading"
              :tree-data="categoryTreeData"
              class="full-width"
              placeholder="选择主分类；暂不确定可留空"
            />
            <small v-if="selectedCategoryLabel" class="selected-category-path">
              当前分类：{{ selectedCategoryLabel }}
            </small>
            <a-alert
              v-if="categoryLoadError"
              type="error"
              show-icon
              message="分类树加载失败"
              description="可重试加载；也可以暂时留空，知识库将归入未分类。"
            >
              <template #action>
                <a-button size="small" :loading="categoryLoading" @click="loadCategories">
                  重试
                </a-button>
              </template>
            </a-alert>
            <a-alert
              v-else-if="!categoryLoading && !categoryTreeData.length"
              type="warning"
              show-icon
              message="组织尚未建立分类树"
              :description="userStore.isAdmin ? '可点击“新建分类节点”后直接选择；留空创建则归入未分类。' : '请联系管理员建立分类树；留空创建则归入未分类。'"
            />
          </div>
          <div class="form-section">
            <label>知识库类型 <b>*</b></label>
            <div class="type-options" role="radiogroup" aria-label="知识库类型">
              <button
                v-for="(typeInfo, typeKey) in orderedKbTypes"
                :key="typeKey"
                type="button"
                class="type-option"
                :class="{ selected: typeKey === 'zhipu' ? zhipuSelected : !zhipuSelected && form.kb_type === typeKey }"
                role="radio"
                :aria-checked="typeKey === 'zhipu' ? zhipuSelected : !zhipuSelected && form.kb_type === typeKey"
                @click="typeKey === 'zhipu' ? zhipuSelected = true : selectType(typeKey)"
              >
                <div class="type-header">
                  <component :is="typeKey === 'zhipu' ? FileSearch : getKbTypeIcon(typeKey)" :size="20" class="type-icon" />
                  <strong class="type-title">{{ typeKey === 'zhipu' ? typeInfo.name : getKbTypeLabel(typeKey) || typeInfo.name }}</strong>
                </div>
                <small class="type-desc">{{
                  typeInfo.description || '连接并检索该类型的知识数据。'
                }}</small>
                <span class="type-badge">
                  {{ typeKey === 'zhipu' ? '连接已有知识库' : typeInfo.supports_documents === false ? '只读连接' : '支持文档' }}
                </span>
              </button>
            </div>
          </div>
          <a-alert v-if="zhipuSelected" type="info" show-icon message="连接智谱知识库" description="进入后连接服务并选择已授权的智谱知识库。云端库授权由管理员配置。" />
        </section>

        <section v-else-if="currentStep === 1" class="flow-section">
          <div class="section-heading">
            <strong>配置 {{ selectedTypeLabel }}</strong>
            <span>填写当前类型需要的连接或索引参数。</span>
          </div>
          <div v-if="selectedTypeInfo?.requires_embedding_model" class="form-grid">
            <div class="form-section">
              <label>嵌入模型 <b>*</b></label>
              <EmbeddingModelSelector
                v-model:value="form.embedding_model_spec"
                class="full-width"
                placeholder="请选择嵌入模型"
              />
            </div>
            <div class="form-section">
              <label>分块策略</label>
              <a-select
                v-model:value="form.chunk_preset_id"
                :options="chunkPresetOptions"
                :loading="chunkPresetLoading"
                class="full-width"
              />
              <small>{{ selectedPresetDescription }}</small>
            </div>
          </div>
          <div v-if="createParamOptions.length" class="form-grid">
            <div v-for="field in createParamOptions" :key="field.key" class="form-section">
              <label :for="`database-param-${field.key}`">
                {{ field.label || field.key }} <b v-if="field.required">*</b>
              </label>
              <a-input-password
                v-if="field.type === 'password'"
                :id="`database-param-${field.key}`"
                v-model:value="form.additional_params[field.key]"
                :placeholder="field.placeholder"
              />
              <a-input-number
                v-else-if="field.type === 'number'"
                :id="`database-param-${field.key}`"
                v-model:value="form.additional_params[field.key]"
                :min="field.min"
                :max="field.max"
                :step="field.step"
                class="full-width"
              />
              <a-switch
                v-else-if="field.type === 'boolean'"
                v-model:checked="form.additional_params[field.key]"
              />
              <a-select
                v-else-if="field.type === 'select'"
                :id="`database-param-${field.key}`"
                v-model:value="form.additional_params[field.key]"
                :options="field.options || []"
                class="full-width"
              />
              <a-input
                v-else
                :id="`database-param-${field.key}`"
                v-model:value="form.additional_params[field.key]"
                :placeholder="field.placeholder"
              />
              <small v-if="field.description">{{ field.description }}</small>
            </div>
          </div>
          <div class="form-section">
            <label>知识库描述</label>
            <small>描述会帮助智能体判断何时使用这个知识库。</small>
            <AiTextarea
              v-model="form.description"
              :name="form.name"
              placeholder="说明包含的内容、适用任务和使用限制"
              :auto-size="{ minRows: 3, maxRows: 8 }"
            />
          </div>
        </section>

        <section v-else class="flow-section">
          <div class="summary-card">
            <div class="summary-header">
              <div class="summary-main">
                <div class="summary-type-avatar">
                  <component :is="getKbTypeIcon(form.kb_type)" :size="18" />
                </div>
                <div class="summary-info">
                  <span class="summary-name" :title="form.name">{{ form.name }}</span>
                  <span class="summary-type-tag">{{ selectedTypeLabel }}</span>
                </div>
              </div>
            </div>

            <div class="summary-grid">
              <div v-if="selectedTypeInfo?.requires_embedding_model" class="summary-item">
                <span class="summary-label">嵌入模型</span>
                <span class="summary-value" :title="form.embedding_model_spec">{{
                  form.embedding_model_spec || '-'
                }}</span>
              </div>
              <div
                v-if="selectedTypeInfo?.requires_embedding_model && selectedPresetLabel"
                class="summary-item"
              >
                <span class="summary-label">分块策略</span>
                <span class="summary-value">{{ selectedPresetLabel }}</span>
              </div>
              <div v-if="createParamOptions.length" class="summary-item">
                <span class="summary-label">连接配置</span>
                <span class="summary-value"
                  >{{ configuredParamCount }}/{{ createParamOptions.length }} 项已填写</span
                >
              </div>
              <div v-if="form.description?.trim()" class="summary-item full-span">
                <span class="summary-label">描述</span>
                <span class="summary-value desc">{{ form.description.trim() }}</span>
              </div>
              <div v-if="selectedCategoryLabel" class="summary-item">
                <span class="summary-label">组织主分类</span>
                <span class="summary-value">{{ selectedCategoryLabel }}</span>
              </div>
            </div>
          </div>
          <a-alert
            v-if="personalOnly"
            type="info"
            show-icon
            message="个人知识库"
            description="仅你本人和超级管理员可见；普通用户不能把个人知识库改为公共知识库。"
          />
          <ShareConfigForm
            v-else
            ref="shareConfigFormRef"
            v-model="shareConfig"
            :auto-select-user-dept="true"
            :require-read-scope="true"
          />
          <label v-if="selectedTypeInfo?.supports_documents !== false" class="create-next-step">
            <a-checkbox v-model:checked="continueWithUpload" />
            <span>
              <strong>创建后立即上传资料</strong>
              <small>自动进入新知识库并打开上传窗口；上传时可一并完成解析、分块和向量入库。</small>
            </span>
          </label>
        </section>
      </main>

      <footer class="create-flow-footer">
        <span>{{ footerSummary }}</span>
        <div class="footer-actions">
          <a-button v-if="currentStep === 0" @click="handleCancel">取消</a-button>
          <a-button v-else :disabled="creating" @click="currentStep--">上一步</a-button>
          <a-button v-if="zhipuSelected" type="primary" @click="emit('connect-zhipu')">进入智谱配置</a-button>
          <a-button v-else-if="currentStep < 2" type="primary" @click="goNext">下一步</a-button>
          <a-button v-else type="primary" :loading="creating" @click="handleCreate">
            创建知识库
          </a-button>
        </div>
      </footer>
    </div>
  </a-modal>

  <a-modal
    v-model:open="categoryCreateOpen"
    title="新建组织分类节点"
    ok-text="创建并选择"
    cancel-text="取消"
    destroy-on-close
    :closable="!categoryCreating"
    :mask-closable="!categoryCreating"
    :keyboard="!categoryCreating"
    :confirm-loading="categoryCreating"
    @ok="saveCategory"
  >
    <div class="category-create-form">
      <div class="form-section">
        <label for="category-create-name">分类名称 <b>*</b></label>
        <a-input
          id="category-create-name"
          v-model:value="categoryForm.name"
          placeholder="例如：新质作战技术"
          @press-enter="saveCategory"
        />
      </div>
      <div class="form-section">
        <label>父分类</label>
        <a-tree-select
          v-model:value="categoryForm.parent_id"
          allow-clear
          show-search
          tree-default-expand-all
          tree-node-filter-prop="title"
          :tree-data="categoryTreeData"
          class="full-width"
          placeholder="留空表示一级分类"
        />
        <small>选中父分类后，新节点会成为它的下一级分类。</small>
      </div>
      <div class="form-section">
        <label for="category-create-description">分类说明</label>
        <a-textarea
          id="category-create-description"
          v-model:value="categoryForm.description"
          :rows="3"
          placeholder="说明适用领域、边界或归类口径"
        />
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { DatabaseZap, FileSearch, X } from '@lucide/vue'
import AiTextarea from '@/components/AiTextarea.vue'
import EmbeddingModelSelector from '@/components/EmbeddingModelSelector.vue'
import ShareConfigForm from '@/components/ShareConfigForm.vue'
import { useChunkPresetOptions } from '@/composables/useChunkPresetOptions'
import { useConfigStore } from '@/stores/config'
import { useDatabaseStore } from '@/stores/database'
import { useUserStore } from '@/stores/user'
import { knowledgeGovernanceApi } from '@/apis/knowledge_governance_api'
import { getKbTypeIcon, getKbTypeLabel } from '@/utils/kb_utils'
import {
  buildCategoryPathMap,
  buildCategoryTreeData,
  buildDatabaseRequest,
  createDefaultShareConfig,
  createEmptyDatabaseForm,
  selectDatabaseType,
  validateDatabaseConfig
} from '@/utils/databaseCreateForm'

const props = defineProps({
  open: { type: Boolean, default: false },
  supportedKbTypes: { type: Object, default: () => ({}) },
  personalOnly: { type: Boolean, default: false }
})
const emit = defineEmits(['update:open', 'completed', 'connect-zhipu'])
const configStore = useConfigStore()
const databaseStore = useDatabaseStore()
const userStore = useUserStore()
const {
  chunkPresetSelectOptions: chunkPresetOptions,
  chunkPresetLoading,
  loadChunkPresetOptions,
  getChunkPresetDescription
} = useChunkPresetOptions()

const orderedKbTypes = computed(() => ({
  ...(props.supportedKbTypes.milvus ? { milvus: props.supportedKbTypes.milvus } : {}),
  zhipu: { name: '智谱知识库', description: '借助智谱的知识检索能力，连接已授权的云端知识库。' },
  ...Object.fromEntries(Object.entries(props.supportedKbTypes).filter(([key]) => key !== 'milvus'))
}))

const stepLabels = ['基础与分类', '配置', '权限']
const currentStep = ref(0)
const zhipuSelected = ref(false)
const form = reactive(createEmptyDatabaseForm(configStore.config?.embed_model))
const shareConfig = ref(createDefaultShareConfig())
const shareConfigFormRef = ref(null)
const categoryLoading = ref(false)
const categoryLoadError = ref(false)
const categoryTreeData = ref([])
const categoryPathMap = ref(new Map())
const categoryCreateOpen = ref(false)
const categoryCreating = ref(false)
const continueWithUpload = ref(true)
const categoryForm = reactive({ name: '', parent_id: null, description: '' })
const creating = computed(() => databaseStore.state.creating)
const selectedTypeInfo = computed(() => props.supportedKbTypes[form.kb_type] || null)
const selectedTypeLabel = computed(
  () => getKbTypeLabel(form.kb_type) || selectedTypeInfo.value?.name || form.kb_type
)
const createParamOptions = computed(() => selectedTypeInfo.value?.create_params?.options || [])
const selectedPresetDescription = computed(() => getChunkPresetDescription(form.chunk_preset_id))
const selectedPresetLabel = computed(() => {
  const match = chunkPresetOptions.value?.find((o) => o.value === form.chunk_preset_id)
  return match?.label || form.chunk_preset_id
})
const selectedCategoryLabel = computed(
  () => categoryPathMap.value.get(form.category_id) || ''
)
const configuredParamCount = computed(
  () =>
    createParamOptions.value.filter((field) => {
      const value = form.additional_params[field.key]
      return value !== undefined && value !== null && String(value).trim() !== ''
    }).length
)
const footerSummary = computed(() => {
  if (zhipuSelected.value) return '智谱知识库 · 连接与检索'
  if (currentStep.value === 0) {
    const typeText = selectedTypeLabel.value
      ? `已选 ${selectedTypeLabel.value}`
      : '请选择知识库类型'
    const classification = selectedCategoryLabel.value || '未分类'
    return form.name.trim()
      ? `${form.name.trim()} · ${classification} · ${typeText}`
      : `${classification} · ${typeText}`
  }
  if (currentStep.value === 1) return `${selectedTypeLabel.value} · ${form.name.trim()}`
  return `${selectedTypeLabel.value} · ${form.name.trim()}`
})

const reset = () => {
  Object.assign(form, createEmptyDatabaseForm(configStore.config?.embed_model))
  const firstType = Object.keys(props.supportedKbTypes)[0] || ''
  zhipuSelected.value = !firstType
  Object.assign(form, selectDatabaseType(form, firstType, props.supportedKbTypes[firstType]))
  shareConfig.value = props.personalOnly
    ? { version: 2, read_scope: null, manage_scope: null }
    : createDefaultShareConfig()
  currentStep.value = 0
  continueWithUpload.value = true
  categoryCreateOpen.value = false
  Object.assign(categoryForm, { name: '', parent_id: null, description: '' })
}

const selectType = (type) => {
  zhipuSelected.value = false
  Object.assign(form, selectDatabaseType(form, type, props.supportedKbTypes[type]))
}
const handleCancel = () => {
  if (creating.value) return
  emit('update:open', false)
}
const loadCategories = async () => {
  categoryLoading.value = true
  categoryLoadError.value = false
  try {
    const result = await knowledgeGovernanceApi.categories()
    categoryTreeData.value = buildCategoryTreeData(result.items || [])
    categoryPathMap.value = buildCategoryPathMap(result.items || [])
  } catch {
    categoryTreeData.value = []
    categoryPathMap.value = new Map()
    categoryLoadError.value = true
  } finally {
    categoryLoading.value = false
  }
}
const openCategoryCreate = () => {
  Object.assign(categoryForm, {
    name: '',
    parent_id: form.category_id || null,
    description: ''
  })
  categoryCreateOpen.value = true
}
const saveCategory = async () => {
  const name = categoryForm.name.trim()
  if (!name) {
    message.warning('请输入分类名称')
    return
  }
  categoryCreating.value = true
  try {
    const created = await knowledgeGovernanceApi.createCategory({
      name,
      parent_id: categoryForm.parent_id || null,
      description: categoryForm.description.trim(),
      sort_order: 0,
      active: true
    })
    await loadCategories()
    form.category_id = created.id
    categoryCreateOpen.value = false
    message.success('分类已创建并选中')
  } catch (cause) {
    message.error(cause.message || '分类创建失败')
  } finally {
    categoryCreating.value = false
  }
}
const goNext = () => {
  if (currentStep.value === 0) {
    if (!form.name?.trim()) {
      message.warning('请输入知识库名称')
      return
    }
    if (!selectedTypeInfo.value) {
      message.warning('请选择知识库类型')
      return
    }
  }
  if (currentStep.value === 1) {
    const error = validateDatabaseConfig(form, selectedTypeInfo.value)
    if (error) {
      message.warning(error)
      return
    }
  }
  currentStep.value++
}
const handleCreate = async () => {
  const error = validateDatabaseConfig(form, selectedTypeInfo.value)
  if (error) {
    if (!form.name?.trim()) {
      currentStep.value = 0
    } else {
      currentStep.value = 1
    }
    message.warning(error)
    return
  }
  const shareValidation = shareConfigFormRef.value?.validate()
  if (shareValidation && !shareValidation.valid) {
    message.warning(shareValidation.message)
    return
  }
  const request = buildDatabaseRequest(
    form,
    selectedTypeInfo.value,
    shareConfig.value,
    configStore.config?.embed_model
  )
  try {
    const result = await databaseStore.createDatabase(request)
    if (!result) return
    emit('completed', result, {
      openUpload: continueWithUpload.value && selectedTypeInfo.value?.supports_documents !== false
    })
    emit('update:open', false)
  } catch {
    // Store 已展示错误，保留当前步骤和输入供用户修正。
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    reset()
    loadChunkPresetOptions()
    loadCategories()
  }
)
watch(
  () => props.supportedKbTypes,
  () => {
    if (props.open && !zhipuSelected.value && !selectedTypeInfo.value) reset()
  },
  { deep: true }
)
</script>

<style scoped lang="less">
.create-flow-shell {
  display: flex;
  flex-direction: column;
  max-height: min(82vh, 760px);
}
.create-flow-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--gray-150);
  margin-bottom: 14px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-left h2 {
  margin: 0;
  color: var(--gray-900);
  font-size: 16px;
  font-weight: 600;
  line-height: 22px;
}
.create-flow-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--gray-100);
  color: var(--gray-700);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-indicator-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--gray-100);
  font-size: 12px;
  line-height: 18px;
  user-select: none;
}
.step-indicator-num {
  font-weight: 600;
  color: var(--gray-800);
  font-variant-numeric: tabular-nums;
}
.step-divider {
  color: var(--gray-350, #b4b8be);
  font-size: 10px;
}
.step-indicator-label {
  color: var(--gray-600);
  font-weight: 500;
}
.modal-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-400);
  cursor: pointer;
  transition: all 0.15s ease;
}
.modal-close-btn:hover:not(:disabled) {
  background: var(--gray-100);
  color: var(--gray-700);
}
.modal-close-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.create-flow-body {
  min-height: 320px;
  max-height: min(55vh, 500px);
  overflow-y: auto;
  padding: 16px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-25);
}
.flow-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.section-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.section-heading strong {
  color: var(--gray-900);
  font-size: 15px;
}
.section-heading span,
.form-section small {
  color: var(--gray-500);
  font-size: 12px;
  line-height: 18px;
}
.type-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.type-option {
  display: flex;
  min-width: 0;
  min-height: 120px;
  padding: 14px;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-600);
  cursor: pointer;
  text-align: left;
}
.type-option:hover {
  border-color: var(--gray-300);
  background: var(--gray-25);
}
.type-option.selected {
  border-color: var(--main-500);
  background: var(--main-30);
}
.type-option:focus-visible {
  outline: 2px solid var(--main-400);
  outline-offset: 2px;
}
.type-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.type-icon {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--main-color);
}
.type-title {
  color: var(--gray-900);
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.type-desc {
  margin: 0;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 18px;
}
.type-badge {
  margin-top: auto;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--gray-100);
  color: var(--gray-600);
  font-size: 11px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.form-section {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}
.form-section label {
  color: var(--gray-800);
  font-size: 13px;
  font-weight: 600;
}
.form-section label b {
  color: var(--color-error-500);
}
.classification-section {
  padding: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
}
.classification-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.classification-heading > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.selected-category-path {
  color: var(--main-color) !important;
  font-weight: 500;
}
.category-create-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 4px;
}
.full-width {
  width: 100%;
}
.summary-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-0);
}
.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--gray-150);
}
.summary-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.summary-type-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  background: var(--main-30);
  color: var(--main-color);
}
.summary-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}
.summary-name {
  color: var(--gray-900);
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 360px;
}
.summary-type-tag {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--gray-100);
  color: var(--gray-700);
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
}
.summary-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  min-width: 0;
}
.summary-item.full-span {
  grid-column: 1 / -1;
}
.summary-label {
  flex-shrink: 0;
  color: var(--gray-400);
}
.summary-value {
  color: var(--gray-800);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.summary-value.desc {
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  color: var(--gray-600);
  line-height: 16px;
}
.create-next-step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--main-100);
  border-radius: 8px;
  background: var(--main-10);
  cursor: pointer;
}
.create-next-step > span {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.create-next-step strong {
  color: var(--gray-900);
  font-size: 13px;
}
.create-next-step small {
  color: var(--gray-600);
  font-size: 12px;
  line-height: 18px;
}
.create-flow-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 14px;
  color: var(--gray-500);
  font-size: 12px;
}
.footer-actions {
  display: flex;
  gap: 8px;
}
@media (max-width: 700px) {
  .type-options,
  .form-grid,
  .summary-grid {
    grid-template-columns: 1fr;
  }
  .create-flow-footer {
    align-items: stretch;
    flex-direction: column;
  }
  .classification-heading {
    align-items: stretch;
    flex-direction: column;
  }
  .footer-actions {
    justify-content: flex-end;
    flex-wrap: wrap;
  }
}
</style>

<style lang="less">
@media (max-width: 600px) {
  .database-create-flow-modal {
    top: 0;
    width: 100% !important;
    max-width: none;
    margin: 0;
    padding: 0;
  }
  .database-create-flow-modal .ant-modal-content {
    min-height: 100vh;
    border-radius: 0;
  }
}
</style>
