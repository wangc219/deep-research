<template>
  <a-modal
    :open="open"
    title="图谱版本与变更历史"
    width="1080px"
    :footer="null"
    :destroy-on-close="true"
    @cancel="close"
  >
    <div class="history-toolbar">
      <p>读取 PostgreSQL 权威 revision 与不可变 change event，不依赖 Neo4j 投影。</p>
      <a-button size="small" :loading="history.revisionLoading.value" @click="refresh">
        <RefreshCw :size="14" />
        刷新
      </a-button>
    </div>

    <a-alert
      v-if="history.revisionError.value"
      type="error"
      show-icon
      :message="history.revisionError.value"
    />
    <div v-else class="history-layout">
      <section class="revision-column" aria-label="图谱 revision 列表">
        <header>
          <span>图谱 Revision</span>
          <small>{{ history.revisionCount.value }} 个版本</small>
        </header>

        <div v-if="history.revisionLoading.value" class="history-state">
          <Loader2 :size="16" class="spin" />
          正在读取版本历史
        </div>
        <a-empty
          v-else-if="!history.revisions.value.length"
          :image="simpleImage"
          description="尚未登记图谱 revision"
        />
        <div v-else class="revision-list">
          <button
            v-for="revision in history.revisions.value"
            :key="revision.revision_id"
            type="button"
            class="revision-card"
            :class="{
              active: revision.revision_id === history.selectedRevision.value?.revision_id
            }"
            @click="history.selectRevision(revision)"
          >
            <span class="revision-id">{{ revision.revision_id }}</span>
            <span>{{ revision.reason || '未记录变更原因' }}</span>
            <small>{{ formatDateTime(revision.created_at) }}</small>
            <small>{{ revision.ontology_version }} · {{ revision.created_by || 'system' }}</small>
          </button>
        </div>

        <a-pagination
          v-if="history.revisionCount.value > history.revisionPageSize"
          size="small"
          :current="history.revisionPage.value"
          :page-size="history.revisionPageSize"
          :total="history.revisionCount.value"
          :show-size-changer="false"
          @change="history.setRevisionPage"
        />
      </section>

      <section class="change-column" aria-label="不可变变更事件列表">
        <template v-if="history.selectedRevision.value">
          <header class="change-header">
            <div>
              <span>不可变 Change Event</span>
              <small>{{ history.changeCount.value }} 条事件</small>
            </div>
            <a-tag color="blue">{{ history.selectedRevision.value.revision_id }}</a-tag>
          </header>

          <dl class="revision-summary">
            <div>
              <dt>父版本</dt>
              <dd>{{ history.selectedRevision.value.parent_revision_id || '初始版本' }}</dd>
            </div>
            <div>
              <dt>本体版本</dt>
              <dd>{{ history.selectedRevision.value.ontology_version }}</dd>
            </div>
            <div v-if="hasPayload(history.selectedRevision.value.summary)" class="summary-wide">
              <dt>版本摘要</dt>
              <dd>
                <code>{{ inlineJson(history.selectedRevision.value.summary) }}</code>
              </dd>
            </div>
          </dl>

          <form class="change-filters" @submit.prevent="history.applyFilters">
            <a-select
              v-model:value="history.targetType.value"
              aria-label="变更目标类型"
              size="small"
              class="type-filter"
              :options="targetTypeOptions"
            />
            <a-input
              v-model:value="history.targetId.value"
              aria-label="变更目标 ID"
              size="small"
              allow-clear
              placeholder="按目标 ID 精确筛选"
            />
            <a-button size="small" html-type="submit" :loading="history.changeLoading.value">
              筛选
            </a-button>
          </form>

          <a-alert
            v-if="history.changeError.value"
            type="error"
            show-icon
            :message="history.changeError.value"
          />
          <div v-else-if="history.changeLoading.value" class="history-state">
            <Loader2 :size="16" class="spin" />
            正在读取变更事件
          </div>
          <a-empty
            v-else-if="!history.changes.value.length"
            :image="simpleImage"
            description="当前版本及筛选条件下没有变更事件"
          />
          <div v-else class="change-list">
            <article v-for="event in history.changes.value" :key="event.event_id">
              <header>
                <div>
                  <a-tag size="small" :color="eventColor(event.event_type)">
                    {{ event.event_type }}
                  </a-tag>
                  <strong>{{ event.target_type }} · {{ event.target_id }}</strong>
                </div>
                <time>{{ formatDateTime(event.created_at) }}</time>
              </header>
              <p v-if="event.reason">{{ event.reason }}</p>
              <div class="event-meta">
                <span>事件 {{ event.event_id }}</span>
                <span>操作人 {{ event.created_by || 'system' }}</span>
              </div>
              <details v-if="hasPayload(event.before) || hasPayload(event.after)">
                <summary>查看变更前后数据</summary>
                <div class="payload-grid">
                  <section>
                    <h4>Before</h4>
                    <pre>{{ prettyJson(event.before) }}</pre>
                  </section>
                  <section>
                    <h4>After</h4>
                    <pre>{{ prettyJson(event.after) }}</pre>
                  </section>
                </div>
              </details>
              <details v-if="hasPayload(event.source_ref)">
                <summary>查看来源引用</summary>
                <pre>{{ prettyJson(event.source_ref) }}</pre>
              </details>
            </article>
          </div>

          <a-pagination
            v-if="history.changeCount.value > history.changePageSize"
            size="small"
            :current="history.changePage.value"
            :page-size="history.changePageSize"
            :total="history.changeCount.value"
            :show-size-changer="false"
            @change="history.setChangePage"
          />
        </template>
        <a-empty v-else :image="simpleImage" description="请选择图谱 revision" />
      </section>
    </div>
  </a-modal>
</template>

<script setup>
import { Empty } from 'ant-design-vue'
import { Loader2, RefreshCw } from '@lucide/vue'
import { watch } from 'vue'
import { unifiedApi } from '@/apis/graph_api'
import { useGraphRevisionHistory } from '@/composables/useGraphRevisionHistory'

const props = defineProps({
  open: Boolean,
  kbId: { type: String, default: '' }
})

const emit = defineEmits(['update:open'])
const history = useGraphRevisionHistory(unifiedApi)
const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE
const targetTypeOptions = [
  { value: '', label: '全部目标类型' },
  { value: 'entity', label: '实体' },
  { value: 'relation', label: '关系' },
  { value: 'hypothesis', label: '探索性假设' }
]

watch(
  () => [props.open, props.kbId],
  ([open, kbId]) => {
    if (open && kbId) {
      history.reset()
      void history.loadRevisions({ kbId, offset: 0 })
    } else {
      history.reset()
    }
  },
  { immediate: true }
)

const close = () => emit('update:open', false)
const refresh = () =>
  history.loadRevisions({
    kbId: props.kbId,
    offset: (history.revisionPage.value - 1) * history.revisionPageSize
  })

const formatDateTime = (value) => {
  if (!value) return '未记录时间'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

const hasPayload = (value) => {
  if (value == null) return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return String(value).length > 0
}

const prettyJson = (value) => JSON.stringify(value ?? null, null, 2)
const inlineJson = (value) => JSON.stringify(value ?? {})
const eventColor = (eventType) => {
  if (String(eventType).includes('rejected')) return 'red'
  if (String(eventType).includes('reviewed')) return 'green'
  if (String(eventType).includes('redirect')) return 'orange'
  return 'blue'
}
</script>

<style scoped lang="less">
.history-toolbar,
.revision-column > header,
.change-header,
.change-header > div,
.change-list article > header,
.change-list article > header > div,
.event-meta {
  display: flex;
  align-items: center;
}

.history-toolbar {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;

  p {
    margin: 0;
    color: var(--gray-600);
    font-size: 12px;
  }
}

.history-layout {
  display: grid;
  grid-template-columns: 310px minmax(0, 1fr);
  min-height: 560px;
  overflow: hidden;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
}

.revision-column,
.change-column {
  min-width: 0;
  padding: 14px;
}

.revision-column {
  border-right: 1px solid var(--gray-150);
  background: var(--gray-25);

  > header {
    justify-content: space-between;
    margin-bottom: 10px;
    color: var(--gray-900);
    font-weight: 600;

    small {
      color: var(--gray-500);
      font-weight: 400;
    }
  }
}

.revision-list,
.change-list {
  display: grid;
  gap: 8px;
  max-height: 475px;
  overflow-y: auto;
}

.revision-list {
  margin-bottom: 12px;
}

.revision-card {
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 10px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--color-bg-container);
  color: var(--gray-700);
  cursor: pointer;
  font: inherit;
  text-align: left;

  &:hover,
  &.active {
    border-color: var(--primary-color);
  }

  &.active {
    background: var(--main-0);
  }

  .revision-id {
    color: var(--gray-900);
    font-family: monospace;
    font-size: 11px;
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  small {
    color: var(--gray-500);
  }
}

.change-header {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;

  > div {
    gap: 8px;
  }

  span {
    color: var(--gray-900);
    font-weight: 600;
  }

  small {
    color: var(--gray-500);
  }
}

.revision-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 18px;
  margin: 0 0 12px;
  padding: 10px;
  border-radius: 6px;
  background: var(--gray-25);

  > div {
    display: grid;
    grid-template-columns: 70px minmax(0, 1fr);
    gap: 6px;
  }

  .summary-wide {
    grid-column: 1 / -1;
  }

  dt,
  dd {
    margin: 0;
    font-size: 12px;
  }

  dt {
    color: var(--gray-500);
  }

  dd {
    color: var(--gray-800);
    overflow-wrap: anywhere;
  }
}

.change-filters {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr) auto;
  gap: 8px;
  margin-bottom: 12px;

  .type-filter {
    width: 100%;
  }
}

.history-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 160px;
  color: var(--gray-500);
}

.change-list {
  margin-bottom: 12px;

  article {
    padding: 10px;
    border: 1px solid var(--gray-150);
    border-radius: 6px;
    background: var(--color-bg-container);

    > header {
      justify-content: space-between;
      gap: 12px;

      > div {
        min-width: 0;
        gap: 6px;
      }

      strong {
        color: var(--gray-800);
        font-size: 12px;
        overflow-wrap: anywhere;
      }

      time {
        flex: none;
        color: var(--gray-500);
        font-size: 10px;
      }
    }

    > p {
      margin: 8px 0 0;
      color: var(--gray-700);
      font-size: 12px;
    }
  }
}

.event-meta {
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 7px;
  color: var(--gray-500);
  font-size: 10px;
}

details {
  margin-top: 8px;

  summary {
    color: var(--main-700);
    cursor: pointer;
    font-size: 11px;
  }
}

.payload-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 7px;

  h4 {
    margin: 0 0 4px;
    color: var(--gray-500);
    font-size: 10px;
  }
}

pre {
  max-height: 180px;
  margin: 7px 0 0;
  padding: 8px;
  overflow: auto;
  border-radius: 4px;
  background: var(--gray-25);
  color: var(--gray-700);
  font-size: 10px;
  white-space: pre-wrap;
  word-break: break-word;
}

.spin {
  animation: history-spin 1s linear infinite;
}

@keyframes history-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 840px) {
  .history-layout {
    grid-template-columns: 1fr;
    max-height: 70vh;
    overflow-y: auto;
  }

  .revision-column {
    border-right: 0;
    border-bottom: 1px solid var(--gray-150);
  }

  .revision-list,
  .change-list {
    max-height: none;
  }

  .payload-grid,
  .revision-summary {
    grid-template-columns: 1fr;
  }

  .change-filters {
    grid-template-columns: 1fr;
  }
}
</style>
