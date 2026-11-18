<template>
  <a-modal
    :open="open"
    title="文档知识审计"
    width="min(1120px, calc(100vw - 32px))"
    :footer="null"
    @cancel="$emit('update:open', false)"
  >
    <a-alert
      class="audit-notice"
      type="info"
      show-icon
      message="研究链与知识卡仅归纳 PostgreSQL 权威记录；待审核关系和推断不会被展示成已确认事实。"
    />
    <div v-if="!loading && cards.length" class="audit-summary" aria-label="知识审计概览">
      <div>
        <FileText :size="18" />
        <span
          ><strong>{{ cards.length }}</strong> 篇知识卡</span
        >
      </div>
      <div>
        <Sparkles :size="18" />
        <span
          ><strong>{{ highValueCount }}</strong> 篇重点复抽</span
        >
      </div>
      <div>
        <Clock3 :size="18" />
        <span
          ><strong>{{ pendingCount }}</strong> 篇待审核</span
        >
      </div>
    </div>
    <div class="audit-layout">
      <section class="card-list">
        <div class="list-toolbar">
          <a-input
            v-model:value="searchText"
            allow-clear
            placeholder="搜索标题、技术或能力"
            aria-label="搜索文档知识卡"
          >
            <template #prefix><Search :size="14" /></template>
          </a-input>
          <a-select v-model:value="status" allow-clear placeholder="全部状态" @change="loadCards">
            <a-select-option value="pending">待审核</a-select-option>
            <a-select-option value="accepted">已接受</a-select-option>
            <a-select-option value="disputed">有争议</a-select-option>
          </a-select>
          <a-button :loading="loading" aria-label="刷新知识卡" @click="loadCards">
            <RefreshCw :size="15" />
          </a-button>
        </div>
        <label class="focus-filter">
          <a-switch v-model:checked="highValueOnly" size="small" />
          仅看高价值重点复抽
        </label>
        <div v-if="loading" class="state-row"><Loader2 :size="18" class="spin" />加载知识卡</div>
        <div v-else-if="loadError" class="error-state">
          <a-alert type="error" show-icon :message="loadError" />
          <a-button @click="loadCards">重新加载</a-button>
        </div>
        <a-empty v-else-if="!cards.length" description="暂无文档知识卡，请先完成 v2 图谱构建。" />
        <a-empty
          v-else-if="!filteredCards.length"
          description="没有符合当前搜索和筛选条件的知识卡。"
        />
        <button
          v-for="card in filteredCards"
          v-else
          :key="card.card_id"
          class="card-item"
          :class="{ active: card.card_id === selectedId }"
          type="button"
          :aria-pressed="card.card_id === selectedId"
          @click="selectCard(card.card_id)"
        >
          <span class="card-item-title">
            <strong>{{ card.title }}</strong>
            <a-tag :color="governanceColor(card.governance_status)">
              {{ governanceLabel(card.governance_status) }}
            </a-tag>
          </span>
          <span>{{ card.content_overview }}</span>
          <span class="card-item-meta">
            <a-tag>{{ militaryValueLabel(card.triage?.military_value_level) }}</a-tag>
            <a-tag v-if="card.triage?.focused_reextraction_recommended" color="purple">
              <Sparkles :size="12" /> 高价值重点复抽
            </a-tag>
          </span>
        </button>
      </section>

      <section class="card-detail">
        <div v-if="detailLoading" class="state-row">
          <Loader2 :size="18" class="spin" />加载详情
        </div>
        <div v-else-if="detailError" class="error-state">
          <a-alert type="error" show-icon :message="detailError" />
          <a-button :disabled="!selectedId" @click="selectCard(selectedId)">重新加载</a-button>
        </div>
        <a-empty v-else-if="!detail" description="选择左侧知识卡查看研究链和证据引用。" />
        <template v-else>
          <header>
            <div>
              <span class="detail-kicker">文档知识卡</span>
              <h3>{{ detail.title }}</h3>
              <p>{{ detail.content_overview }}</p>
            </div>
            <a-tag :color="governanceColor(detail.governance_status)">
              {{ governanceLabel(detail.governance_status) }}
            </a-tag>
          </header>
          <div class="audit-flow" role="list" aria-label="知识形成与审核流程">
            <div class="flow-step is-complete" role="listitem">
              <CircleCheck :size="18" />
              <span><strong>价值分流</strong><small>已判断复抽优先级</small></span>
            </div>
            <div
              class="flow-step"
              :class="{ 'is-complete': detail.evidence_refs?.length }"
              role="listitem"
            >
              <Sparkles :size="18" />
              <span><strong>模型抽取</strong><small>实体、关系与 Span 已生成</small></span>
            </div>
            <div
              class="flow-step"
              :class="{
                'is-complete': detail.governance_status === 'accepted',
                'is-current': detail.governance_status !== 'accepted'
              }"
              role="listitem"
            >
              <UserCheck :size="18" />
              <span>
                <strong>人工复核</strong>
                <small>{{
                  detail.governance_status === 'accepted' ? '已接受' : '等待确认候选'
                }}</small>
              </span>
            </div>
          </div>
          <a-descriptions size="small" :column="2" bordered>
            <a-descriptions-item label="资料分流">
              {{ detail.triage?.document_kind }} / {{ detail.triage?.triage_level }}
            </a-descriptions-item>
            <a-descriptions-item label="军事价值">
              {{ detail.triage?.military_value_level || 'Uncertain' }}
              <a-tag v-if="detail.triage?.military_value_review_required" color="orange">
                需专家复核
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="研判依据" :span="2">
              {{ detail.triage?.military_value_reason || '暂无研判依据' }}
            </a-descriptions-item>
            <a-descriptions-item
              v-if="detail.triage?.value_routing"
              label="轻量化 RAG 技术价值"
              :span="2"
            >
              <a-tag :color="detail.triage.focused_reextraction_recommended ? 'red' : 'default'">
                {{
                  detail.triage.focused_reextraction_recommended ? '高价值重点复抽' : '常规抽取预算'
                }}
              </a-tag>
              <span class="routing-summary">
                {{ relevanceLabel(detail.triage.value_routing.military_relevance) }} /
                {{ noveltyLabel(detail.triage.value_routing.novelty) }}
              </span>
              <div class="routing-confidence">
                <span>价值路由置信度</span>
                <strong>{{ routingConfidence }}%</strong>
                <a-progress
                  :percent="routingConfidence"
                  :show-info="false"
                  size="small"
                  :stroke-color="
                    detail.triage.focused_reextraction_recommended ? '#7c3aed' : undefined
                  "
                />
              </div>
              <div class="value-routing-dimensions">
                <a-tag
                  v-for="dimension in detail.triage.value_routing.dimensions || []"
                  :key="dimension"
                  color="purple"
                >
                  {{ dimension }}
                </a-tag>
              </div>
              <p>{{ detail.triage.value_routing.reason || '未提供价值判别理由' }}</p>
              <small class="routing-boundary">
                <ShieldCheck :size="13" />
                该结果只调整复抽预算，不作为事实、人工 Gold 或正式验收结论。
              </small>
            </a-descriptions-item>
            <a-descriptions-item label="成熟度">
              {{ detail.maturity?.stage || 'unknown' }}（Inference）
            </a-descriptions-item>
            <a-descriptions-item label="创新潜力">
              {{ Number(detail.innovation_potential?.score || 0).toFixed(2) }}（Inference）
            </a-descriptions-item>
            <a-descriptions-item label="迁移潜力">
              {{ Number(detail.transfer_potential?.score || 0).toFixed(2) }}（Inference）
            </a-descriptions-item>
            <a-descriptions-item label="受信路径">
              {{ detail.graph_rag_hints?.trusted_path_count || 0 }} 条
            </a-descriptions-item>
            <a-descriptions-item label="证据引用">
              {{ detail.evidence_refs?.length || 0 }} 个 Span
            </a-descriptions-item>
          </a-descriptions>
          <nav class="detail-shortcuts" aria-label="知识卡快速导航">
            <span>快速查看</span>
            <a-button size="small" @click="scrollToSection('audit-analysis')">分析报告</a-button>
            <a-button size="small" @click="scrollToSection('audit-threads')">研究链</a-button>
            <a-button size="small" @click="scrollToSection('audit-evidence')">
              原文证据 {{ detail.evidence_refs?.length || 0 }}
            </a-button>
          </nav>
          <div class="tag-section">
            <h4>技术族</h4>
            <a-tag v-for="item in detail.technology_families" :key="item">{{ item }}</a-tag>
          </div>
          <div class="tag-section">
            <h4>能力与应用</h4>
            <a-tag v-for="item in detail.capability_gains" :key="`cap-${item}`" color="blue">
              {{ item }}
            </a-tag>
            <a-tag v-for="item in detail.application_directions" :key="`app-${item}`" color="cyan">
              {{ item }}
            </a-tag>
          </div>
          <div class="tag-section">
            <h4>关键指标</h4>
            <a-empty v-if="!detail.key_metrics?.length" description="尚未抽取可核验指标" />
            <a-tag
              v-for="item in detail.key_metrics"
              v-else
              :key="item.entity_id"
              :color="item.review_status === 'accepted' ? 'green' : 'orange'"
            >
              {{ item.name }} · {{ item.review_status }}
            </a-tag>
          </div>
          <section id="audit-analysis" class="profile-section">
            <h4>证据化分析报告</h4>
            <p><strong>军事价值：</strong>{{ detail.narrative_report?.military_value }}</p>
            <p><strong>创新价值：</strong>{{ detail.narrative_report?.innovation_value }}</p>
            <p><strong>技术链：</strong>{{ detail.narrative_report?.technical_chain }}</p>
            <p><strong>应用场景：</strong>{{ detail.narrative_report?.application_scenarios }}</p>
            <p>
              <strong>证据与不确定性：</strong
              >{{ detail.narrative_report?.evidence_and_uncertainty }}
            </p>
            <p><strong>下一步：</strong>{{ detail.narrative_report?.recommended_next_step }}</p>
          </section>
          <section class="profile-section">
            <h4>GraphRAG 检索提示</h4>
            <div class="profile-tags">
              <a-tag
                v-for="item in detail.graph_rag_hints?.seed_entities || []"
                :key="item.entity_id"
                :color="item.accepted_evidence ? 'blue' : 'default'"
              >
                {{ item.type }} · {{ item.name }}
              </a-tag>
            </div>
            <p v-for="query in detail.graph_rag_hints?.follow_up_queries || []" :key="query">
              {{ query }}
            </p>
            <a-alert
              v-if="detail.graph_rag_hints?.edge_prediction_candidate_ids?.length"
              type="warning"
              :message="`${detail.graph_rag_hints.edge_prediction_candidate_ids.length} 条创新边仅为待审核候选，不进入默认事实查询。`"
              show-icon
            />
          </section>
          <section id="audit-threads" class="thread-list">
            <h4>研究主线 / 辅线</h4>
            <article v-for="thread in detail.threads" :key="thread.thread_id">
              <div class="thread-title">
                <strong>{{ thread.title }}</strong>
                <a-tag>{{ thread.thread_type }}</a-tag>
                <span>置信度 {{ Math.round(thread.confidence * 100) }}%</span>
              </div>
              <p v-if="thread.technical_line?.length">
                技术：{{ thread.technical_line.join(' → ') }}
              </p>
              <p v-if="thread.capability_direction?.length">
                能力：{{ thread.capability_direction.join('、') }}
              </p>
              <p v-if="thread.application_direction?.length">
                应用：{{ thread.application_direction.join('、') }}
              </p>
              <small>{{ thread.uncertainty }}</small>
            </article>
          </section>
          <section id="audit-evidence" class="evidence-list">
            <div class="section-heading">
              <div>
                <h4>原文证据 Span</h4>
                <small>
                  {{ rebuildableEvidenceCount }}/{{ detail.evidence_refs?.length || 0 }} 可回切 ·
                  当前展示
                  {{ Math.min(evidenceVisibleLimit, detail.evidence_refs?.length || 0) }} 条
                </small>
              </div>
              <a-tag
                :color="
                  rebuildableEvidenceCount === (detail.evidence_refs?.length || 0)
                    ? 'green'
                    : 'orange'
                "
              >
                {{ evidenceIntegrityLabel }}
              </a-tag>
            </div>
            <a-empty
              v-if="!detail.evidence_refs?.length"
              description="当前知识卡没有可定位证据。"
            />
            <article
              v-for="(evidence, index) in detail.evidence_refs?.slice(0, evidenceVisibleLimit)"
              v-else
              :key="`${evidence.block_id}-${evidence.start}-${evidence.end}`"
            >
              <div class="evidence-location">
                <strong>证据 {{ index + 1 }}</strong>
                <span>
                  第 {{ evidence.page || '?' }} 页 · Block {{ evidence.block_id || '?' }} · [{{
                    evidence.start
                  }}, {{ evidence.end }})
                </span>
                <a-tag :color="evidence.rebuildable ? 'green' : 'red'">
                  {{ evidence.rebuildable ? '可回切' : '待修复' }}
                </a-tag>
              </div>
              <p v-if="evidence.heading_path?.length">
                {{ evidence.heading_path.join(' / ') }}
              </p>
              <blockquote v-if="evidence.text">{{ evidence.text }}</blockquote>
              <small>
                关联实体 {{ evidence.entity_ids?.length || 0 }} 个，关系
                {{ evidence.triple_ids?.length || 0 }} 条
              </small>
              <div v-if="evidence.supports?.length" class="evidence-supports">
                <div
                  v-for="support in evidence.supports"
                  :key="`${support.kind}-${support.id}`"
                  class="evidence-support"
                >
                  <a-tag :color="support.kind === 'relation' ? 'purple' : 'blue'">
                    {{ support.evidence_use_label }}
                  </a-tag>
                  <span v-if="support.claim_level">{{ support.claim_level }}</span>
                  <span>{{ support.review_status }}</span>
                  <span v-if="support.confidence != null">
                    置信度 {{ Math.round(support.confidence * 100) }}%
                  </span>
                  <span>{{ support.extraction_method }}</span>
                  <span v-if="support.model_version">模型 {{ support.model_version }}</span>
                </div>
              </div>
            </article>
            <div v-if="detail.evidence_refs?.length > evidenceVisibleLimit" class="evidence-more">
              <a-button @click="evidenceVisibleLimit += 10">
                再显示 {{ Math.min(10, detail.evidence_refs.length - evidenceVisibleLimit) }} 条
              </a-button>
              <small>剩余 {{ detail.evidence_refs.length - evidenceVisibleLimit }} 条</small>
            </div>
          </section>
          <a-alert type="warning" :message="detail.uncertainty" show-icon />
        </template>
      </section>
    </div>
  </a-modal>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  CircleCheck,
  Clock3,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  UserCheck
} from '@lucide/vue'
import { message } from 'ant-design-vue'
import { unifiedApi } from '@/apis/graph_api'

const props = defineProps({
  open: { type: Boolean, default: false },
  kbId: { type: String, required: true }
})
defineEmits(['update:open'])

const status = ref()
const cards = ref([])
const loading = ref(false)
const loadError = ref('')
const searchText = ref('')
const highValueOnly = ref(false)
const selectedId = ref('')
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const evidenceVisibleLimit = ref(10)

const filteredCards = computed(() => {
  const query = searchText.value.trim().toLocaleLowerCase()
  return cards.value.filter((card) => {
    if (highValueOnly.value && !card.triage?.focused_reextraction_recommended) return false
    if (!query) return true
    const searchable = [
      card.title,
      card.content_overview,
      ...(card.technology_families || []),
      ...(card.capability_gains || []),
      ...(card.application_directions || [])
    ]
      .filter(Boolean)
      .join(' ')
      .toLocaleLowerCase()
    return searchable.includes(query)
  })
})

const highValueCount = computed(
  () => cards.value.filter((card) => card.triage?.focused_reextraction_recommended).length
)
const pendingCount = computed(
  () => cards.value.filter((card) => card.governance_status === 'pending').length
)
const routingConfidence = computed(() =>
  Math.round(Number(detail.value?.triage?.value_routing?.confidence || 0) * 100)
)
const rebuildableEvidenceCount = computed(
  () => detail.value?.evidence_refs?.filter((item) => item.rebuildable).length || 0
)
const evidenceIntegrityLabel = computed(() => {
  const total = detail.value?.evidence_refs?.length || 0
  if (!total) return '暂无证据'
  return rebuildableEvidenceCount.value === total ? '全部可回切' : '部分待修复'
})

const governanceLabels = {
  pending: '待审核',
  accepted: '已接受',
  disputed: '有争议',
  rejected: '已拒绝'
}
const governanceColors = {
  pending: 'orange',
  accepted: 'green',
  disputed: 'gold',
  rejected: 'red'
}
const militaryValueLabels = {
  Military: '军事技术',
  DualUse: '军民两用',
  Civilian: '民用技术',
  Uncertain: '待判定'
}
const relevanceLabels = {
  direct: '直接军事应用',
  dual_use: '军民两用',
  adjacent: '军事邻近技术',
  none: '无明确军事关联',
  uncertain: '关联待判定'
}
const noveltyLabels = {
  breakthrough: '突破性技术',
  emerging: '新兴技术',
  incremental: '渐进改进',
  established: '成熟技术',
  unknown: '新颖性待判定'
}

const governanceLabel = (value) => governanceLabels[value] || value || '未分级'
const governanceColor = (value) => governanceColors[value] || 'default'
const militaryValueLabel = (value) => militaryValueLabels[value] || value || '未分级'
const relevanceLabel = (value) => relevanceLabels[value] || value || '关联待判定'
const noveltyLabel = (value) => noveltyLabels[value] || value || '新颖性待判定'

const loadCards = async () => {
  if (!props.kbId) return
  loading.value = true
  loadError.value = ''
  try {
    const response = await unifiedApi.getDocumentCards(props.kbId, {
      governance_status: status.value || '',
      limit: 100
    })
    cards.value = response?.data?.items || []
    if (selectedId.value && !cards.value.some((item) => item.card_id === selectedId.value)) {
      selectedId.value = ''
      detail.value = null
    }
    if (!selectedId.value && cards.value.length) {
      await selectCard(cards.value[0].card_id)
    }
  } catch (error) {
    console.error('Failed to load document knowledge cards:', error)
    loadError.value = '知识卡加载失败，请检查连接后重试。'
    message.error(loadError.value)
  } finally {
    loading.value = false
  }
}

const selectCard = async (cardId) => {
  selectedId.value = cardId
  detailLoading.value = true
  detailError.value = ''
  evidenceVisibleLimit.value = 10
  try {
    const response = await unifiedApi.getDocumentCard(props.kbId, cardId)
    detail.value = response?.data || null
  } catch (error) {
    console.error('Failed to load document knowledge card:', error)
    detail.value = null
    detailError.value = '知识卡详情加载失败，请稍后重试。'
    message.error(detailError.value)
  } finally {
    detailLoading.value = false
  }
}

const scrollToSection = async (sectionId) => {
  await nextTick()
  document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

watch(
  () => props.open,
  (visible) => {
    if (visible) {
      void loadCards()
    } else {
      searchText.value = ''
      highValueOnly.value = false
      evidenceVisibleLimit.value = 10
    }
  }
)
</script>

<style scoped>
.audit-notice {
  margin-bottom: 16px;
}
.audit-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.audit-summary > div {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  padding: 10px 12px;
  color: var(--text-color-secondary);
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}
.audit-summary svg {
  flex: 0 0 auto;
  color: var(--primary-color);
}
.audit-summary strong {
  color: var(--text-color);
  font-size: 17px;
}
.audit-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.36fr) minmax(0, 0.64fr);
  gap: 16px;
  min-height: 560px;
}
.card-list,
.card-detail {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  overflow: auto;
}
.list-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 112px 34px;
  gap: 8px;
  margin-bottom: 12px;
}
.focus-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: -2px 0 12px;
  color: var(--text-color-secondary);
  font-size: 12px;
}
.card-item {
  width: 100%;
  display: grid;
  gap: 6px;
  padding: 12px;
  margin-bottom: 8px;
  text-align: left;
  color: inherit;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
}
.card-item:hover {
  border-color: color-mix(in srgb, var(--primary-color) 55%, var(--border-color));
  transform: translateY(-1px);
}
.card-item.active {
  border-color: var(--primary-color);
  background: var(--primary-color-light);
  box-shadow: inset 3px 0 0 var(--primary-color);
}
.card-item span {
  color: var(--text-color-secondary);
  line-height: 1.5;
}
.card-item > span:nth-child(2) {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.card-item-title,
.card-item-meta {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.card-item-title strong {
  color: var(--text-color);
  line-height: 1.45;
}
.card-item-title :deep(.ant-tag) {
  flex: 0 0 auto;
  margin-inline-end: 0;
}
.card-item-meta {
  justify-content: flex-start;
  flex-wrap: wrap;
}
.card-item-meta :deep(.ant-tag) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-inline-end: 0;
}
.card-item small,
.thread-title span,
article small {
  color: var(--text-color-secondary);
}
.error-state {
  display: grid;
  gap: 12px;
  justify-items: start;
  padding: 12px 0;
}
.state-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 120px;
}
.card-detail header,
.thread-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.card-detail h3 {
  margin: 0 0 8px;
}
.detail-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--primary-color);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
}
.audit-flow {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 14px 0;
}
.flow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 10px;
  color: var(--text-color-secondary);
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 9px;
}
.flow-step svg {
  flex: 0 0 auto;
}
.flow-step span,
.flow-step strong,
.flow-step small {
  display: block;
}
.flow-step strong {
  color: var(--text-color);
  font-size: 13px;
}
.flow-step small {
  margin-top: 2px;
  font-size: 11px;
}
.flow-step.is-complete {
  color: var(--color-success-500, #22c55e);
  border-color: color-mix(in srgb, var(--color-success-500, #22c55e) 30%, var(--border-color));
}
.flow-step.is-current {
  color: var(--primary-color);
  border-color: color-mix(in srgb, var(--primary-color) 45%, var(--border-color));
  background: var(--primary-color-light);
}
.routing-summary {
  margin-left: 6px;
  color: var(--text-color-secondary);
}
.routing-confidence {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 2px 10px;
  max-width: 360px;
  margin-top: 10px;
  color: var(--text-color-secondary);
  font-size: 12px;
}
.routing-confidence strong {
  color: var(--text-color);
}
.routing-confidence :deep(.ant-progress) {
  grid-column: 1 / -1;
  line-height: 1;
}
.routing-boundary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-color-secondary);
}
.detail-shortcuts {
  position: sticky;
  top: -12px;
  z-index: 2;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  margin: 14px 0;
  padding: 8px;
  background: color-mix(in srgb, var(--bg-color) 92%, transparent);
  border: 1px solid var(--border-color);
  border-radius: 9px;
  backdrop-filter: blur(10px);
}
.detail-shortcuts > span {
  margin: 0 2px 0 4px;
  color: var(--text-color-secondary);
  font-size: 12px;
}
.tag-section {
  margin: 16px 0;
}
.tag-section h4,
.profile-section h4,
.thread-list h4,
.evidence-list h4 {
  margin: 0 0 8px;
}
.thread-list article,
.evidence-list article {
  padding: 12px;
  margin-bottom: 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
}
.profile-section {
  padding: 12px;
  margin: 16px 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
}
.profile-section p {
  margin: 8px 0;
  line-height: 1.6;
}
.profile-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.value-routing-dimensions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}
.value-routing-dimensions + p {
  margin: 8px 0 4px;
}
.thread-list p {
  margin: 8px 0;
}
.evidence-list {
  margin: 16px 0;
  scroll-margin-top: 62px;
}
.profile-section,
.thread-list {
  scroll-margin-top: 62px;
}
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.section-heading h4 {
  margin-bottom: 3px;
}
.section-heading :deep(.ant-tag) {
  flex: 0 0 auto;
  margin-inline-end: 0;
}
.evidence-location {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.evidence-location span,
.evidence-list small,
.evidence-list p {
  color: var(--text-color-secondary);
}
.evidence-list p {
  margin: 8px 0;
}
.evidence-list blockquote {
  margin: 8px 0;
  padding: 10px 12px;
  color: inherit;
  background: var(--bg-color);
  border-left: 3px solid var(--primary-color);
}
.evidence-supports {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}
.evidence-support {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--text-color-secondary);
  font-size: 12px;
}
.evidence-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 8px 0;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 800px) {
  .audit-summary {
    grid-template-columns: 1fr;
  }
  .audit-layout {
    grid-template-columns: 1fr;
  }
  .card-list {
    max-height: 360px;
  }
  .audit-flow {
    grid-template-columns: 1fr;
  }
  .detail-shortcuts {
    top: -12px;
  }
}
@media (max-width: 520px) {
  .list-toolbar {
    grid-template-columns: minmax(0, 1fr) 34px;
  }
  .list-toolbar :deep(.ant-select) {
    grid-column: 1 / -1;
    grid-row: 2;
  }
}
</style>
