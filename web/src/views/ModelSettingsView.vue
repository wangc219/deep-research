<script setup>
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import ModelProviderManagePanel from '@/components/model-management/ModelProviderManagePanel.vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import EmbeddingModelSelector from '@/components/EmbeddingModelSelector.vue'
import RerankModelSelector from '@/components/RerankModelSelector.vue'
import { useConfigStore } from '@/stores/config'
import { useUserStore } from '@/stores/user'

const providerPanelRef = ref(null)
const configStore = useConfigStore()
const userStore = useUserStore()
const loading = computed(() => providerPanelRef.value?.loading || providerPanelRef.value?.saving || false)
const stats = computed(() => providerPanelRef.value?.stats || {})

const setOption = (key, spec) => {
  if (typeof spec === 'string' && spec) configStore.setConfigValue(key, spec)
}

onMounted(() => {
  configStore.refreshConfig().catch(() => {})
})
</script>

<template>
  <div class="model-settings-view">
    <PageHeader title="模型设置" :loading="loading" :show-border="true" aria-label="模型设置">
      <template #info>
        <div class="summary-strip">
          <span>{{ stats.total || 0 }} 个供应商</span>
          <span>{{ stats.enabled || 0 }} 个启用</span>
          <span v-if="stats.warning > 0" class="warning-count">{{ stats.warning }} 个凭证缺失</span>
          <span>{{ stats.models || 0 }} 个模型</span>
        </div>
      </template>
    </PageHeader>
    <div class="model-settings-content">
      <p class="page-lead">
        在本页管理供应商与模型。智能对话、装备研究任务、需求 Query 生成和深研对话都会使用这里启用的聊天模型；请勿再通过
        <code>.env</code> 配置模型 ID 或 API Key。
      </p>
      <section v-if="userStore.isSuperAdmin" class="defaults-card">
        <h2>系统默认模型</h2>
        <p>
          在此页添加供应商、填写 API Key、启用聊天模型，再指定系统默认模型。智能对话、装备研究任务（S1–S6）、需求 Query 生成和深研对话共用这套配置，请不要再把模型 ID 或密钥写进
          <code>.env</code>。Embedding / Re-Ranker 仅用于知识库。
        </p>
        <div class="defaults-grid">
          <label>
            默认对话 / 装备研究 / Query / 深研对话
            <ModelSelectorComponent
              :model_spec="configStore.config?.default_model"
              placeholder="请选择默认聊天模型"
              size="middle"
              @select-model="(spec) => setOption('default_model', spec)"
            />
          </label>
          <label>
            Embedding
            <EmbeddingModelSelector
              :value="configStore.config?.embed_model"
              placeholder="请选择 Embedding 模型"
              @change="(spec) => setOption('embed_model', spec)"
            />
          </label>
          <label>
            Re-Ranker
            <RerankModelSelector
              :value="configStore.config?.reranker"
              placeholder="请选择 Re-Ranker"
              @change="(spec) => setOption('reranker', spec)"
            />
          </label>
        </div>
      </section>
      <ModelProviderManagePanel ref="providerPanelRef" />
    </div>
  </div>
</template>

<style lang="less" scoped>
.model-settings-view {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--gray-0);
  color: var(--gray-1000);
}

.model-settings-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.page-lead {
  margin: 16px 24px 0;
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.55;
}

.defaults-card {
  margin: 16px 24px 0;
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);

  h2 {
    margin: 0 0 6px;
    font-size: 15px;
  }

  p {
    margin: 0 0 12px;
    color: var(--gray-600);
    font-size: 13px;
  }
}

.defaults-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;

  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    color: var(--gray-700);
  }
}

.summary-strip {
  display: flex;
  gap: 8px;

  span {
    padding: 6px 10px;
    border: 1px solid var(--gray-100);
    border-radius: 7px;
    background: var(--gray-10);
    color: var(--gray-700);
    font-size: 12px;
    line-height: 18px;
  }

  .warning-count {
    background: var(--color-warning-50);
    border-color: var(--color-warning-100);
    color: var(--color-warning-700);
  }
}
</style>
