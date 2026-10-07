<template>
  <section class="knowledge-workflow" aria-labelledby="knowledge-workflow-title">
    <header class="knowledge-workflow-header">
      <div class="knowledge-workflow-heading">
        <span class="knowledge-workflow-icon" aria-hidden="true">
          <Workflow :size="18" />
        </span>
        <div>
          <div class="knowledge-workflow-title-row">
            <h2 id="knowledge-workflow-title">知识入库与质量链路</h2>
            <span class="knowledge-health" :data-tone="health.tone">{{ health.label }}</span>
          </div>
          <p>{{ health.description }}</p>
        </div>
      </div>
      <button
        v-if="primaryAction"
        type="button"
        class="knowledge-primary-action"
        :disabled="busy"
        @click="runPrimaryAction"
      >
        <LoaderCircle v-if="busy" :size="15" class="knowledge-spin" />
        <component :is="primaryAction.icon" v-else :size="15" />
        <span>{{ primaryAction.label }}</span>
      </button>
    </header>

    <ol class="knowledge-pipeline" aria-label="知识库处理进度">
      <li
        v-for="(step, index) in pipelineSteps"
        :key="step.key"
        class="knowledge-pipeline-step"
        :data-state="step.state"
      >
        <div class="knowledge-step-topline">
          <span class="knowledge-step-number" aria-hidden="true">
            <Check v-if="step.state === 'done'" :size="13" />
            <LoaderCircle v-else-if="step.state === 'running'" :size="13" class="knowledge-spin" />
            <span v-else>{{ index + 1 }}</span>
          </span>
          <span class="knowledge-step-label">{{ step.label }}</span>
        </div>
        <strong>{{ step.value }}</strong>
        <span class="knowledge-step-hint">{{ step.hint }}</span>
        <button
          v-if="step.action"
          type="button"
          class="knowledge-step-action"
          :disabled="step.disabled || busy"
          @click="runStepAction(step.action)"
        >
          {{ step.action.label }}
          <ChevronRight :size="13" />
        </button>
      </li>
    </ol>

    <div class="knowledge-workflow-footer">
      <dl class="knowledge-config-summary" aria-label="知识库配置摘要">
        <div>
          <dt>解析与分块</dt>
          <dd :title="chunkStrategy">{{ chunkStrategy }}</dd>
        </div>
        <div>
          <dt>向量模型</dt>
          <dd :title="embeddingModel">{{ embeddingModel }}</dd>
        </div>
        <div>
          <dt>召回策略</dt>
          <dd>{{ retrievalStrategy }}</dd>
        </div>
        <div>
          <dt>可见范围</dt>
          <dd :title="permissionDetail">{{ permissionLabel }}</dd>
        </div>
      </dl>

      <nav class="knowledge-workflow-links" aria-label="知识库质量工具">
        <button type="button" @click="emit('navigate', 'query')">
          <Search :size="14" />检索验证
        </button>
        <button type="button" @click="emit('navigate', 'graph')">
          <Network :size="14" />知识图谱
        </button>
        <button v-if="canManage" type="button" @click="emit('navigate', 'evaluation')">
          <BarChart3 :size="14" />RAG 评估
        </button>
        <button v-if="canManage" type="button" @click="emit('configure')">
          <Settings2 :size="14" />配置
        </button>
      </nav>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import {
  BarChart3,
  Check,
  ChevronRight,
  Database,
  FileSearch,
  FileUp,
  LoaderCircle,
  Network,
  Search,
  Settings2,
  Workflow
} from '@lucide/vue'

const props = defineProps({
  stats: { type: Object, default: () => ({}) },
  canManage: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  chunkStrategy: { type: String, default: '默认分块策略' },
  embeddingModel: { type: String, default: '未配置' },
  retrievalStrategy: { type: String, default: '向量召回' },
  permissionLabel: { type: String, default: '个人知识库' },
  permissionDetail: { type: String, default: '' }
})

const emit = defineEmits(['upload', 'parse', 'index', 'navigate', 'configure'])

const count = (key) => Math.max(Number(props.stats?.[key] || 0), 0)
const formatCount = (value) => Number(value || 0).toLocaleString('zh-CN')

const health = computed(() => {
  if (count('processing_count') > 0) {
    return {
      tone: 'running',
      label: '处理中',
      description: `${formatCount(count('processing_count'))} 个文档正在后台处理，完成后会自动刷新。`
    }
  }
  if (count('failed_count') > 0) {
    return {
      tone: 'warning',
      label: '需要处理',
      description: `${formatCount(count('failed_count'))} 个文档处理失败，可在文件列表按状态定位并重试。`
    }
  }
  if (count('pending_parse_count') > 0 || count('pending_index_count') > 0) {
    return {
      tone: 'warning',
      label: '待完成',
      description: '仍有文档等待解析或入库，完成后才能稳定参与检索。'
    }
  }
  if (count('indexed_count') > 0) {
    return {
      tone: 'ready',
      label: '可检索',
      description: '向量索引已就绪，建议通过检索测试和 RAG 评估持续校验质量。'
    }
  }
  return {
    tone: 'empty',
    label: '待入库',
    description: '上传资料后，按解析、分块、向量入库的顺序完成知识准备。'
  }
})

const primaryAction = computed(() => {
  if (!props.canManage || count('processing_count') > 0) return null
  if (count('pending_parse_count') > 0) {
    return { event: 'parse', label: `解析 ${formatCount(count('pending_parse_count'))} 个文档`, icon: FileSearch }
  }
  if (count('pending_index_count') > 0) {
    return { event: 'index', label: `入库 ${formatCount(count('pending_index_count'))} 个文档`, icon: Database }
  }
  if (count('file_count') === 0) {
    return { event: 'upload', label: '上传资料', icon: FileUp }
  }
  if (count('indexed_count') > 0) {
    return { event: 'navigate', label: '验证检索质量', icon: Search }
  }
  return null
})

const pipelineSteps = computed(() => {
  const files = count('file_count')
  const pendingParse = count('pending_parse_count')
  const pendingIndex = count('pending_index_count')
  const processing = count('processing_count')
  const indexed = count('indexed_count')

  return [
    {
      key: 'source',
      label: '资料',
      value: `${formatCount(files)} 个文件`,
      hint: files ? '原始资料已进入知识库' : '支持文档、表格、演示稿与网页',
      state: files ? 'done' : 'pending',
      action: props.canManage && !files ? { event: 'upload', label: '上传资料' } : null
    },
    {
      key: 'parse',
      label: '解析与分块',
      value: processing ? `${formatCount(processing)} 个处理中` : `${formatCount(pendingParse)} 个待解析`,
      hint: pendingParse ? '提取正文、图片与表格并生成 Chunk' : files ? '暂无待解析文档' : '等待上传资料',
      state: processing ? 'running' : files && !pendingParse ? 'done' : 'pending',
      action: props.canManage && pendingParse ? { event: 'parse', label: '开始解析' } : null
    },
    {
      key: 'index',
      label: '向量入库',
      value: `${formatCount(indexed)} 个已入库`,
      hint: pendingIndex ? `${formatCount(pendingIndex)} 个等待建立索引` : indexed ? '向量索引可参与召回' : '等待完成解析',
      state: processing ? 'running' : indexed && !pendingIndex ? 'done' : 'pending',
      action: props.canManage && pendingIndex ? { event: 'index', label: '开始入库' } : null
    },
    {
      key: 'verify',
      label: '检索验证',
      value: indexed ? '可开始验证' : '尚未就绪',
      hint: '检查召回片段、相似度与重排序效果',
      state: indexed ? 'ready' : 'pending',
      action: indexed ? { event: 'navigate', label: '测试检索', tab: 'query' } : null
    },
    {
      key: 'evaluate',
      label: '持续评估',
      value: indexed ? '建立评估基线' : '等待索引',
      hint: '用问答集量化召回与回答质量',
      state: indexed ? 'ready' : 'pending',
      action: props.canManage && indexed
        ? { event: 'navigate', label: '进入评估', tab: 'evaluation' }
        : null
    }
  ]
})

const runStepAction = (action) => {
  if (action.event === 'navigate') {
    emit('navigate', action.tab)
    return
  }
  emit(action.event)
}

const runPrimaryAction = () => {
  if (!primaryAction.value) return
  if (primaryAction.value.event === 'navigate') {
    emit('navigate', 'query')
    return
  }
  emit(primaryAction.value.event)
}
</script>

<style lang="less" scoped>
.knowledge-workflow {
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
}

.knowledge-workflow-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px 12px;
}

.knowledge-workflow-heading {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 10px;

  h2,
  p {
    margin: 0;
  }

  h2 {
    color: var(--gray-900);
    font-size: 14px;
    font-weight: 650;
    line-height: 20px;
  }

  p {
    margin-top: 2px;
    color: var(--gray-500);
    font-size: 12px;
    line-height: 18px;
  }
}

.knowledge-workflow-icon {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: var(--main-color);
  background: var(--main-30);
}

.knowledge-workflow-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.knowledge-health {
  padding: 2px 7px;
  border-radius: 999px;
  color: var(--gray-600);
  background: var(--gray-100);
  font-size: 11px;
  font-weight: 600;
  line-height: 17px;

  &[data-tone='ready'] {
    color: var(--color-success-700);
    background: var(--color-success-50);
  }

  &[data-tone='warning'] {
    color: var(--color-warning-900);
    background: var(--color-warning-50);
  }

  &[data-tone='running'] {
    color: var(--main-700);
    background: var(--main-50);
  }
}

.knowledge-primary-action,
.knowledge-step-action,
.knowledge-workflow-links button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  font-family: inherit;
  cursor: pointer;
}

.knowledge-primary-action {
  flex: 0 0 auto;
  gap: 6px;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 7px;
  color: white;
  background: var(--main-color);
  font-size: 12px;
  font-weight: 600;

  &:hover:not(:disabled) {
    background: var(--main-bright);
  }

  &:disabled {
    opacity: 0.65;
    cursor: wait;
  }
}

.knowledge-pipeline {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 0 16px 14px;
  list-style: none;
}

.knowledge-pipeline-step {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 104px;
  flex-direction: column;
  align-items: flex-start;
  padding: 11px 12px;
  border: 1px solid var(--gray-150);
  background: var(--gray-25);

  & + & {
    border-left: 0;
  }

  &:first-child {
    border-radius: 9px 0 0 9px;
  }

  &:last-child {
    border-radius: 0 9px 9px 0;
  }

  &[data-state='done'] {
    background: color-mix(in srgb, var(--color-success-50) 58%, var(--gray-0));
  }

  &[data-state='running'] {
    background: color-mix(in srgb, var(--main-50) 64%, var(--gray-0));
  }

  strong {
    margin-top: 8px;
    overflow: hidden;
    color: var(--gray-900);
    font-size: 13px;
    font-weight: 650;
    line-height: 18px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.knowledge-step-topline {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--gray-600);
  font-size: 12px;
  font-weight: 600;
}

.knowledge-step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  color: var(--gray-600);
  background: var(--gray-150);
  font-size: 11px;
}

[data-state='done'] .knowledge-step-number {
  color: var(--color-success-700);
  background: var(--color-success-100);
}

[data-state='running'] .knowledge-step-number,
[data-state='ready'] .knowledge-step-number {
  color: var(--main-700);
  background: var(--main-100);
}

.knowledge-step-hint {
  display: -webkit-box;
  min-height: 32px;
  margin-top: 2px;
  overflow: hidden;
  color: var(--gray-500);
  font-size: 11px;
  line-height: 16px;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.knowledge-step-action {
  gap: 2px;
  margin-top: auto;
  padding: 2px 0 0;
  color: var(--main-color);
  background: transparent;
  font-size: 11px;
  font-weight: 600;

  &:hover:not(:disabled) {
    color: var(--main-700);
  }
}

.knowledge-workflow-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 9px 16px;
  border-top: 1px solid var(--gray-150);
  background: var(--gray-25);
}

.knowledge-config-summary {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0;
  margin: 0;

  div {
    display: flex;
    min-width: 0;
    align-items: baseline;
    gap: 5px;
    padding-right: 12px;
  }

  div + div {
    padding-left: 12px;
    border-left: 1px solid var(--gray-200);
  }

  dt,
  dd {
    margin: 0;
    font-size: 11px;
    line-height: 18px;
  }

  dt {
    flex: 0 0 auto;
    color: var(--gray-500);
  }

  dd {
    min-width: 0;
    max-width: 148px;
    overflow: hidden;
    color: var(--gray-700);
    font-weight: 550;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.knowledge-workflow-links {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;

  button {
    gap: 4px;
    min-height: 28px;
    padding: 0 8px;
    border-radius: 6px;
    color: var(--gray-600);
    background: transparent;
    font-size: 11px;

    &:hover {
      color: var(--gray-900);
      background: var(--gray-100);
    }
  }
}

.knowledge-spin {
  animation: knowledge-spin 0.8s linear infinite;
}

@keyframes knowledge-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1180px) {
  .knowledge-pipeline {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .knowledge-pipeline-step,
  .knowledge-pipeline-step + .knowledge-pipeline-step {
    border: 1px solid var(--gray-150);
    border-radius: 9px;
  }

  .knowledge-workflow-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .knowledge-config-summary {
    width: 100%;
  }
}

@media (max-width: 767px) {
  .knowledge-workflow-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .knowledge-primary-action {
    width: 100%;
  }

  .knowledge-pipeline {
    grid-template-columns: repeat(5, minmax(150px, 1fr));
    overflow-x: auto;
    overscroll-behavior-inline: contain;
    scrollbar-width: thin;
  }

  .knowledge-pipeline-step {
    min-height: 96px;
  }

  .knowledge-config-summary {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px 12px;

    div,
    div + div {
      padding: 0;
      border: 0;
    }
  }

  .knowledge-workflow-links {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
