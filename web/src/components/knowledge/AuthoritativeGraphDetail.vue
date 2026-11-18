<template>
  <section class="authority-section" :aria-label="sectionTitle">
    <header class="authority-header">
      <span>{{ sectionTitle }}</span>
      <a-tag v-if="detail" color="green" size="small">已接受</a-tag>
    </header>

    <div v-if="loading" class="authority-state">
      <Loader2 :size="15" class="spin" />
      正在读取权威证据
    </div>
    <a-alert v-else-if="error" type="warning" show-icon :message="error" />
    <template v-else-if="detail">
      <template v-if="type === 'node'">
        <dl class="authority-summary">
          <div>
            <dt>标准名</dt>
            <dd>{{ detail.entity?.name || '-' }}</dd>
          </div>
          <div>
            <dt>实体类型</dt>
            <dd>{{ detail.entity?.type || '-' }}</dd>
          </div>
          <div>
            <dt>证据数</dt>
            <dd>{{ detail.evidence_count ?? detail.evidence?.length ?? 0 }}</dd>
          </div>
          <div v-if="detail.entity?.lifecycle_status">
            <dt>生命周期</dt>
            <dd>{{ detail.entity.lifecycle_status }}</dd>
          </div>
        </dl>
        <div v-if="detail.aliases?.length" class="authority-aliases">
          <span>别名与中英文映射</span>
          <div>
            <a-tag v-for="alias in detail.aliases" :key="aliasKey(alias)" size="small">
              {{ alias.alias }}<small v-if="alias.language"> · {{ alias.language }}</small>
            </a-tag>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="relation-route">
          <strong>{{ detail.source?.name || detail.relation?.source_entity_id }}</strong>
          <span>{{ detail.relation?.type }}</span>
          <strong>{{ detail.target?.name || detail.relation?.target_entity_id }}</strong>
        </div>
        <dl class="authority-summary">
          <div>
            <dt>声明级别</dt>
            <dd>{{ (detail.claim_levels || []).join('、') || '-' }}</dd>
          </div>
          <div>
            <dt>证据数</dt>
            <dd>{{ detail.evidence_count ?? detail.evidence?.length ?? 0 }}</dd>
          </div>
          <div>
            <dt>生命周期</dt>
            <dd>{{ detail.relation?.lifecycle_status || 'active' }}</dd>
          </div>
          <div>
            <dt>关系版本</dt>
            <dd>{{ detail.relation?.relation_version || 1 }}</dd>
          </div>
          <div v-if="detail.relation?.superseded_by_triple_id" class="summary-wide">
            <dt>替代关系</dt>
            <dd>{{ detail.relation.superseded_by_triple_id }}</dd>
          </div>
          <div v-if="detail.applicable_conditions?.length" class="summary-wide">
            <dt>适用条件</dt>
            <dd>{{ detail.applicable_conditions.join('；') }}</dd>
          </div>
        </dl>
      </template>

      <div class="authority-evidence-list">
        <article
          v-for="evidence in detail.evidence || []"
          :key="evidence.mention_id"
          class="authority-evidence"
        >
          <header>
            <span>{{ evidence.filename || evidence.file_id || '未命名来源' }}</span>
            <a-tag v-if="evidence.claim_level" size="small" color="blue">
              {{ evidence.claim_level }}
            </a-tag>
          </header>
          <p class="evidence-location">{{ evidenceLocation(evidence) }}</p>
          <p class="evidence-span">Span {{ evidenceSpanLabel(evidence) }}</p>
          <p class="evidence-text">
            <template
              v-for="(segment, index) in evidenceSegments(evidence)"
              :key="`${evidence.mention_id}-${index}`"
            >
              <mark v-if="segment.highlight">{{ segment.text }}</mark>
              <template v-else>{{ segment.text }}</template>
            </template>
          </p>
          <dl v-if="type === 'edge'" class="evidence-boundaries">
            <div v-if="evidence.applicable_conditions?.length">
              <dt>适用条件</dt>
              <dd>{{ evidence.applicable_conditions.join('；') }}</dd>
            </div>
            <div v-if="evidence.uncertainty">
              <dt>不确定性</dt>
              <dd>{{ evidence.uncertainty }}</dd>
            </div>
            <div v-if="evidence.reasoning_basis">
              <dt>推理依据</dt>
              <dd>{{ evidence.reasoning_basis }}</dd>
            </div>
          </dl>
          <footer>
            <span v-if="evidence.confidence != null"
              >置信度 {{ confidenceLabel(evidence.confidence) }}</span
            >
            <span v-if="evidence.model_version">{{ evidence.model_version }}</span>
            <span v-if="evidence.ontology_version">{{ evidence.ontology_version }}</span>
            <span v-if="evidence.pipeline_revision">{{ evidence.pipeline_revision }}</span>
          </footer>
        </article>
      </div>

      <div v-if="detail.evidence_count" class="authority-evidence-progress">
        <span>
          已展示 {{ detail.evidence?.length || 0 }} / {{ detail.evidence_count }} 条权威证据
        </span>
        <a-button
          v-if="canLoadMore"
          size="small"
          type="link"
          :loading="loadingMore"
          @click="$emit('load-more')"
        >
          加载更多证据
        </a-button>
      </div>
      <a-alert
        v-if="loadMoreError"
        class="authority-load-more-error"
        type="warning"
        show-icon
        :message="loadMoreError"
      />

      <p v-if="detail.history?.length" class="authority-history">
        已记录 {{ detail.history.length }} 条不可变变更事件
      </p>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { Loader2 } from '@lucide/vue'
import { buildEvidenceSegments } from '@/utils/graphReview'

const props = defineProps({
  type: { type: String, required: true },
  detail: { type: Object, default: null },
  loading: Boolean,
  loadingMore: Boolean,
  canLoadMore: Boolean,
  loadMoreError: { type: String, default: '' },
  error: { type: String, default: '' }
})

defineEmits(['load-more'])

const sectionTitle = computed(() =>
  props.type === 'node' ? 'PostgreSQL 权威实体' : 'PostgreSQL 权威关系'
)

const aliasKey = (alias) => `${alias.language || ''}:${alias.normalized_alias || alias.alias}`

const confidenceLabel = (value) => `${Math.round(Number(value || 0) * 100)}%`

const evidenceSpans = (evidence) =>
  props.type === 'node' ? (evidence.span ? [evidence.span] : []) : evidence.evidence_spans || []

const evidenceSegments = (evidence) =>
  buildEvidenceSegments(evidence.evidence_text, evidenceSpans(evidence))

const evidenceSpanLabel = (evidence) => {
  const spans = evidenceSpans(evidence)
  return spans.length ? spans.map((span) => `[${span.start}, ${span.end})`).join('、') : '-'
}

const evidenceLocation = (evidence) => {
  const location = evidence.location || {}
  const parts = []
  if (location.page != null) parts.push(`第 ${location.page} 页`)
  if (location.heading_path?.length) parts.push(location.heading_path.join(' > '))
  if (location.parser) {
    parts.push(`${location.parser}${location.parser_version ? ` ${location.parser_version}` : ''}`)
  }
  return parts.join(' · ') || '未记录定位信息'
}
</script>

<style scoped lang="less">
.authority-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--gray-200);
}

.authority-header,
.authority-evidence > header,
.authority-evidence > footer {
  display: flex;
  align-items: center;
  gap: 6px;
}

.authority-header {
  justify-content: space-between;
  color: var(--gray-900);
  font-size: 12px;
  font-weight: 600;
}

.authority-state {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 12px 0;
  color: var(--gray-600);
  font-size: 12px;
}

.authority-summary,
.evidence-boundaries {
  display: grid;
  gap: 7px;
  margin: 10px 0 0;

  > div {
    display: grid;
    grid-template-columns: 72px minmax(0, 1fr);
    gap: 8px;
  }

  dt,
  dd {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
  }

  dt {
    color: var(--gray-500);
  }

  dd {
    color: var(--gray-800);
    overflow-wrap: anywhere;
  }
}

.authority-aliases {
  margin-top: 10px;

  > span {
    display: block;
    margin-bottom: 6px;
    color: var(--gray-500);
    font-size: 12px;
  }

  > div {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  small {
    color: var(--gray-500);
  }
}

.relation-route {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  padding: 9px;
  border-radius: 6px;
  background: var(--gray-50);
  text-align: center;

  strong {
    color: var(--gray-900);
    overflow-wrap: anywhere;
  }

  span {
    color: var(--main-700);
    font-size: 11px;
  }
}

.authority-evidence-list {
  display: grid;
  gap: 9px;
  margin-top: 12px;
}

.authority-evidence {
  padding: 9px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-25);

  > header {
    justify-content: space-between;
    color: var(--gray-800);
    font-size: 12px;
    font-weight: 600;
  }

  > footer {
    flex-wrap: wrap;
    margin-top: 8px;
    color: var(--gray-500);
    font-size: 10px;

    span:not(:last-child)::after {
      margin-left: 6px;
      content: '·';
    }
  }
}

.evidence-location,
.evidence-span,
.evidence-text {
  margin: 6px 0 0;
}

.evidence-location,
.evidence-span {
  color: var(--gray-500);
  font-size: 10px;
}

.evidence-text {
  color: var(--gray-800);
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;

  mark {
    padding: 1px 2px;
    border-radius: 2px;
    background: var(--color-warning-100);
    color: inherit;
  }
}

.evidence-boundaries {
  padding-top: 7px;
  border-top: 1px dashed var(--gray-150);
}

.authority-history {
  margin: 10px 0 0;
  color: var(--gray-500);
  font-size: 11px;
}

.authority-evidence-progress {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 9px;
  color: var(--gray-500);
  font-size: 11px;
}

.authority-load-more-error {
  margin-top: 8px;
}

.spin {
  animation: authority-spin 1s linear infinite;
}

@keyframes authority-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
