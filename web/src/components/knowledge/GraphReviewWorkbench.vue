<template>
  <a-modal
    :open="open"
    title="知识图谱人工审核"
    width="1040px"
    :footer="null"
    class="graph-review-modal"
    @cancel="close"
  >
    <a-segmented
      v-model:value="workbenchMode"
      class="workbench-mode"
      :options="[
        { label: '候选审核', value: 'review' },
        { label: '冲突治理', value: 'conflicts' }
      ]"
    />
    <GraphConflictPanel
      v-if="workbenchMode === 'conflicts'"
      :active="open && workbenchMode === 'conflicts'"
      :kb-id="kbId"
      @resolved="emit('reviewed')"
    />
    <template v-else>
      <div class="review-toolbar">
        <a-select v-model:value="reviewStatus" class="status-filter" @change="loadQueue">
          <a-select-option value="pending">待审核</a-select-option>
          <a-select-option value="accepted">已接受</a-select-option>
          <a-select-option value="rejected">已拒绝</a-select-option>
          <a-select-option value="disputed">有争议</a-select-option>
          <a-select-option value="superseded">已废弃</a-select-option>
        </a-select>
        <span class="review-count">{{ items.length }} 条候选</span>
        <a-button size="small" :loading="loading" @click="loadQueue">
          <RefreshCw :size="14" />
          刷新
        </a-button>
      </div>

      <a-spin :spinning="loading">
        <div v-if="errorMessage" class="review-error" role="alert">
          <CircleAlert :size="18" />
          <span>{{ errorMessage }}</span>
        </div>
        <div v-else-if="!items.length" class="review-empty">
          <ClipboardCheck :size="28" />
          <strong>当前筛选条件下没有候选</strong>
          <span>新的实体和关系抽取结果会在这里等待人工复核。</span>
        </div>
        <div v-else class="review-layout">
          <div class="candidate-list" role="listbox" aria-label="图谱候选列表">
            <button
              v-for="item in items"
              :key="`${item.target_type}-${item.target_id}`"
              type="button"
              class="candidate-item"
              :class="{ active: selectedKey === itemKey(item) }"
              @click="selectItem(item)"
            >
              <span class="candidate-kind">
                {{ item.target_type === 'entity_mention' ? '实体' : '关系' }}
              </span>
              <strong>{{ candidateTitle(item) }}</strong>
              <small>{{ candidateSubtitle(item) }}</small>
              <span class="confidence">置信度 {{ formatConfidence(item.confidence) }}</span>
            </button>
          </div>

          <section v-if="selectedItem" class="candidate-detail">
            <header>
              <div>
                <span class="eyebrow">{{ selectedItem.target_type }}</span>
                <h3>{{ candidateTitle(selectedItem) }}</h3>
              </div>
              <a-tag :color="statusColor(selectedItem.review_status)">
                {{ statusLabel(selectedItem.review_status) }}
              </a-tag>
            </header>

            <dl class="candidate-metadata">
              <div>
                <dt>模型</dt>
                <dd>{{ selectedItem.model_version || '未记录' }}</dd>
              </div>
              <div>
                <dt>本体</dt>
                <dd>{{ selectedItem.ontology_version || '未记录' }}</dd>
              </div>
              <div>
                <dt>Chunk</dt>
                <dd>{{ selectedItem.chunk_id }}</dd>
              </div>
              <div>
                <dt>文件</dt>
                <dd>{{ selectedItem.file_id }}</dd>
              </div>
              <div>
                <dt>页码</dt>
                <dd>{{ selectedItem.evidence_location?.page || '未记录' }}</dd>
              </div>
              <div>
                <dt>Block 类型</dt>
                <dd>{{ selectedItem.evidence_location?.block_type || '未记录' }}</dd>
              </div>
              <div>
                <dt>标题路径</dt>
                <dd>{{ selectedItem.evidence_location?.heading_path?.join(' / ') || '未记录' }}</dd>
              </div>
              <div>
                <dt>解析器</dt>
                <dd>
                  {{ selectedItem.evidence_location?.parser || '未记录' }}
                  <template v-if="selectedItem.evidence_location?.parser_version">
                    {{ selectedItem.evidence_location.parser_version }}
                  </template>
                </dd>
              </div>
            </dl>

            <div class="evidence-card">
              <div class="evidence-heading">
                <strong>原文证据</strong>
                <span>字符区间采用 [start, end)</span>
              </div>
              <p class="evidence-text">
                <template v-for="(segment, index) in evidenceSegments" :key="index">
                  <mark v-if="segment.highlight">{{ segment.text }}</mark>
                  <span v-else>{{ segment.text }}</span>
                </template>
              </p>
              <blockquote v-if="selectedItem.evidence_quote">
                {{ selectedItem.evidence_quote }}
              </blockquote>
            </div>

            <div v-if="selectedItem.alignment" class="alignment-card">
              <div class="evidence-heading">
                <strong>实体对齐候选</strong>
                <span>类型硬约束；歧义候选不会自动合并</span>
              </div>
              <p>{{ selectedItem.alignment.reason }}</p>
              <ul v-if="selectedItem.alignment.candidates?.length">
                <li
                  v-for="candidate in selectedItem.alignment.candidates"
                  :key="candidate.entity_id"
                >
                  {{ candidate.name }} · {{ candidate.label }} ·
                  {{ formatConfidence(candidate.score) }}
                </li>
              </ul>
              <ul v-else-if="selectedItem.alignment.candidate_entity_ids?.length">
                <li
                  v-for="candidateId in selectedItem.alignment.candidate_entity_ids"
                  :key="candidateId"
                >
                  {{ candidateId }}
                </li>
              </ul>
            </div>

            <div
              v-if="selectedItem.target_type === 'relation_mention'"
              class="relation-context-card"
            >
              <div class="evidence-heading">
                <strong>关系适用条件与推理边界</strong>
                <span>条件缺失不代表关系可无条件外推</span>
              </div>
              <dl>
                <div>
                  <dt>适用条件</dt>
                  <dd>
                    <ul v-if="selectedItem.applicable_conditions?.length">
                      <li v-for="condition in selectedItem.applicable_conditions" :key="condition">
                        {{ condition }}
                      </li>
                    </ul>
                    <span v-else>未抽取，需人工核实适用边界</span>
                  </dd>
                </div>
                <div>
                  <dt>推理依据</dt>
                  <dd>{{ selectedItem.reasoning_basis || '未记录' }}</dd>
                </div>
                <div>
                  <dt>不确定性</dt>
                  <dd>{{ selectedItem.uncertainty || '未记录' }}</dd>
                </div>
              </dl>
            </div>

            <a-form
              v-if="selectedItem.review_status === 'pending'"
              layout="vertical"
              class="decision-form"
            >
              <a-form-item label="审核说明">
                <a-textarea
                  v-model:value="reason"
                  :rows="3"
                  :maxlength="4000"
                  show-count
                  placeholder="记录接受依据、拒绝原因或争议点"
                />
              </a-form-item>
              <div class="decision-actions">
                <a-button :loading="submitting" danger @click="submitDecision('rejected')"
                  >拒绝</a-button
                >
                <a-button :loading="submitting" @click="submitDecision('disputed')"
                  >标记争议</a-button
                >
                <a-button type="primary" :loading="submitting" @click="submitDecision('accepted')">
                  接受
                </a-button>
              </div>
            </a-form>
          </section>
        </div>
      </a-spin>
    </template>
  </a-modal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { CircleAlert, ClipboardCheck, RefreshCw } from '@lucide/vue'
import { message } from 'ant-design-vue'
import { graphApi } from '@/apis/graph_api'
import GraphConflictPanel from '@/components/knowledge/GraphConflictPanel.vue'
import {
  buildEvidenceSegments,
  graphReviewCandidateSubtitle,
  graphReviewCandidateTitle,
  graphReviewConfidence,
  graphReviewItemKey,
  graphReviewStatusColor,
  graphReviewStatusLabel
} from '@/utils/graphReview'

const props = defineProps({
  open: { type: Boolean, default: false },
  kbId: { type: String, required: true }
})
const emit = defineEmits(['update:open', 'reviewed'])

const items = ref([])
const loading = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
const reviewStatus = ref('pending')
const selectedKey = ref('')
const reason = ref('')
const workbenchMode = ref('review')

const itemKey = graphReviewItemKey
const selectedItem = computed(
  () => items.value.find((item) => itemKey(item) === selectedKey.value) || items.value[0] || null
)

const evidenceSegments = computed(() =>
  buildEvidenceSegments(selectedItem.value?.evidence_text, selectedItem.value?.evidence_spans)
)
const candidateTitle = graphReviewCandidateTitle
const candidateSubtitle = graphReviewCandidateSubtitle
const formatConfidence = graphReviewConfidence
const statusLabel = graphReviewStatusLabel
const statusColor = graphReviewStatusColor

const selectItem = (item) => {
  selectedKey.value = itemKey(item)
  reason.value = ''
}

const loadQueue = async () => {
  if (!props.open || !props.kbId) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await graphApi.getReviewQueue({
      kb_id: props.kbId,
      status: reviewStatus.value,
      limit: 100
    })
    items.value = response?.data?.items || []
    selectedKey.value = items.value[0] ? itemKey(items.value[0]) : ''
    reason.value = ''
  } catch (error) {
    console.error('Failed to load graph review queue:', error)
    items.value = []
    errorMessage.value = error?.message || '审核队列加载失败'
  } finally {
    loading.value = false
  }
}

const submitDecision = async (decision) => {
  if (!selectedItem.value || submitting.value) return
  submitting.value = true
  try {
    await graphApi.submitReviewDecision(props.kbId, {
      target_type: selectedItem.value.target_type,
      target_id: String(selectedItem.value.target_id),
      decision,
      reason: reason.value.trim()
    })
    message.success('审核决定已保存')
    emit('reviewed')
    await loadQueue()
  } catch (error) {
    console.error('Failed to submit graph review decision:', error)
    message.error(error?.message || '审核决定保存失败')
  } finally {
    submitting.value = false
  }
}

const close = () => emit('update:open', false)

watch(
  () => [props.open, props.kbId],
  ([open]) => {
    if (open) loadQueue()
  }
)
</script>

<style scoped>
.review-toolbar,
.decision-actions,
.evidence-heading,
.candidate-detail header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.review-toolbar {
  margin-bottom: 14px;
}

.workbench-mode {
  margin-bottom: 14px;
}

.status-filter {
  width: 140px;
}

.review-count {
  flex: 1;
  color: var(--gray-500);
  font-size: 13px;
}

.review-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.7fr);
  min-height: 520px;
  max-height: 68vh;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  overflow: hidden;
}

.candidate-list {
  overflow-y: auto;
  border-right: 1px solid var(--gray-200);
  background: var(--gray-50);
}

.candidate-item {
  display: grid;
  width: 100%;
  gap: 5px;
  padding: 14px;
  border: 0;
  border-bottom: 1px solid var(--gray-200);
  background: transparent;
  color: var(--gray-900);
  text-align: left;
  cursor: pointer;
}

.candidate-item:hover,
.candidate-item.active {
  background: var(--gray-100);
}

.candidate-item.active {
  box-shadow: inset 3px 0 var(--primary-color);
}

.candidate-kind,
.confidence,
.candidate-item small,
.eyebrow,
.evidence-heading span {
  color: var(--gray-500);
  font-size: 12px;
}

.candidate-detail {
  overflow-y: auto;
  padding: 20px;
}

.candidate-detail header {
  justify-content: space-between;
}

.candidate-detail h3 {
  margin: 4px 0 0;
  font-size: 18px;
}

.candidate-metadata {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 18px 0;
}

.candidate-metadata div,
.evidence-card,
.alignment-card,
.relation-context-card {
  padding: 10px 12px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
}

.alignment-card {
  margin-top: 12px;

  p,
  ul {
    margin: 8px 0 0;
  }
}

.relation-context-card {
  margin-top: 12px;

  dl,
  dd,
  ul {
    margin: 0;
  }

  dl {
    display: grid;
    gap: 10px;
    margin-top: 10px;
  }

  dt {
    color: var(--gray-500);
    font-size: 12px;
  }

  dd {
    margin-top: 4px;
  }
}

.candidate-metadata dt {
  color: var(--gray-500);
  font-size: 12px;
}

.candidate-metadata dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}

.evidence-heading {
  justify-content: space-between;
}

.evidence-text {
  margin: 12px 0 0;
  line-height: 1.9;
  white-space: pre-wrap;
}

.evidence-text mark {
  padding: 2px 0;
  border-radius: 3px;
  background: #fff0a6;
  color: inherit;
}

blockquote {
  margin: 12px 0 0;
  padding-left: 12px;
  border-left: 3px solid var(--primary-color);
  color: var(--gray-600);
}

.decision-form {
  margin-top: 18px;
}

.decision-actions {
  justify-content: flex-end;
}

.review-empty,
.review-error {
  min-height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--gray-500);
}

.review-empty {
  flex-direction: column;
}

.review-empty strong {
  color: var(--gray-800);
}

.review-error {
  color: var(--danger-color, #cf1322);
}

@media (max-width: 820px) {
  .review-layout {
    grid-template-columns: 1fr;
    max-height: none;
  }

  .candidate-list {
    max-height: 240px;
    border-right: 0;
    border-bottom: 1px solid var(--gray-200);
  }

  .candidate-metadata {
    grid-template-columns: 1fr;
  }
}
</style>
