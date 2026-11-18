<template>
  <section class="conflict-panel" aria-label="知识冲突治理">
    <div class="conflict-toolbar">
      <a-select v-model:value="status" class="status-filter" @change="loadConflicts">
        <a-select-option value="open">待裁决</a-select-option>
        <a-select-option value="resolved">已解决</a-select-option>
        <a-select-option value="dismissed">已忽略</a-select-option>
        <a-select-option value="superseded">已废弃</a-select-option>
      </a-select>
      <a-select
        v-model:value="severity"
        class="severity-filter"
        allow-clear
        placeholder="全部严重度"
        @change="loadConflicts"
      >
        <a-select-option value="critical">严重</a-select-option>
        <a-select-option value="high">高</a-select-option>
        <a-select-option value="medium">中</a-select-option>
        <a-select-option value="low">低</a-select-option>
      </a-select>
      <span class="conflict-count">{{ conflicts.length }} 条冲突</span>
      <a-button size="small" :loading="loading" @click="loadConflicts">
        <RefreshCw :size="14" />
        刷新
      </a-button>
    </div>

    <a-spin :spinning="loading">
      <div v-if="errorMessage" class="conflict-state error" role="alert">
        <CircleAlert :size="18" />
        <span>{{ errorMessage }}</span>
      </div>
      <div v-else-if="!conflicts.length" class="conflict-state">
        <BadgeCheck :size="28" />
        <strong>当前筛选条件下没有冲突</strong>
        <span>人工争议和规则检测到的冲突会进入这里统一裁决。</span>
      </div>
      <div v-else class="conflict-layout">
        <div class="conflict-list" role="listbox" aria-label="冲突列表">
          <button
            v-for="item in conflicts"
            :key="item.conflict_id"
            type="button"
            class="conflict-item"
            :class="{ active: selectedId === item.conflict_id }"
            @click="selectConflict(item)"
          >
            <span class="severity" :data-severity="item.severity">
              {{ severityLabel(item.severity) }}
            </span>
            <strong>{{ item.summary }}</strong>
            <small>{{ item.conflict_type }} · {{ item.left_target_type }}</small>
          </button>
        </div>

        <article v-if="selectedConflict" class="conflict-detail">
          <header>
            <div>
              <span class="eyebrow">{{ selectedConflict.conflict_type }}</span>
              <h3>{{ selectedConflict.summary }}</h3>
            </div>
            <a-tag :color="selectedConflict.status === 'open' ? 'orange' : 'green'">
              {{ statusLabel(selectedConflict.status) }}
            </a-tag>
          </header>
          <dl>
            <div>
              <dt>左侧目标</dt>
              <dd>
                {{ selectedConflict.left_target_type }} / {{ selectedConflict.left_target_id }}
              </dd>
            </div>
            <div v-if="selectedConflict.right_target_id">
              <dt>右侧目标</dt>
              <dd>
                {{ selectedConflict.right_target_type }} / {{ selectedConflict.right_target_id }}
              </dd>
            </div>
            <div>
              <dt>发现方式</dt>
              <dd>{{ selectedConflict.detected_by }}</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{{ formatTime(selectedConflict.created_at) }}</dd>
            </div>
          </dl>
          <pre v-if="hasDetails(selectedConflict.details)" class="conflict-details">{{
            JSON.stringify(selectedConflict.details, null, 2)
          }}</pre>

          <a-form v-if="selectedConflict.status === 'open'" layout="vertical">
            <a-form-item label="裁决结论">
              <a-textarea
                v-model:value="resolution"
                :rows="4"
                :maxlength="4000"
                show-count
                placeholder="记录冲突判断、证据依据和处理结论"
              />
            </a-form-item>
            <div class="resolution-actions">
              <a-button :loading="submitting" @click="submitResolution('dismissed')">忽略</a-button>
              <a-button :loading="submitting" @click="submitResolution('superseded')"
                >废弃</a-button
              >
              <a-button type="primary" :loading="submitting" @click="submitResolution('resolved')"
                >解决</a-button
              >
            </div>
          </a-form>
          <div v-else class="resolution-result">
            <strong>裁决结果</strong>
            <p>{{ selectedConflict.resolution || '未记录' }}</p>
            <small>
              {{ selectedConflict.resolved_by || '未知处理人' }} ·
              {{ formatTime(selectedConflict.resolved_at) }}
            </small>
          </div>
        </article>
      </div>
    </a-spin>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { BadgeCheck, CircleAlert, RefreshCw } from '@lucide/vue'
import { message } from 'ant-design-vue'
import { graphApi } from '@/apis/graph_api'

const props = defineProps({
  active: { type: Boolean, default: false },
  kbId: { type: String, required: true }
})
const emit = defineEmits(['resolved'])

const conflicts = ref([])
const loading = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
const status = ref('open')
const severity = ref()
const selectedId = ref('')
const resolution = ref('')
const selectedConflict = computed(
  () =>
    conflicts.value.find((item) => item.conflict_id === selectedId.value) ||
    conflicts.value[0] ||
    null
)

const loadConflicts = async () => {
  if (!props.active || !props.kbId) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await graphApi.getConflicts({
      kb_id: props.kbId,
      status: status.value,
      severity: severity.value || '',
      limit: 100
    })
    conflicts.value = response?.data?.items || []
    selectedId.value = conflicts.value[0]?.conflict_id || ''
    resolution.value = ''
  } catch (error) {
    console.error('Failed to load graph conflicts:', error)
    conflicts.value = []
    errorMessage.value = error?.message || '冲突队列加载失败'
  } finally {
    loading.value = false
  }
}

const selectConflict = (item) => {
  selectedId.value = item.conflict_id
  resolution.value = ''
}

const submitResolution = async (nextStatus) => {
  if (!selectedConflict.value || !resolution.value.trim() || submitting.value) {
    if (!resolution.value.trim()) message.warning('请先填写裁决结论')
    return
  }
  submitting.value = true
  try {
    await graphApi.resolveConflict(props.kbId, selectedConflict.value.conflict_id, {
      status: nextStatus,
      resolution: resolution.value.trim()
    })
    message.success('冲突裁决已保存')
    emit('resolved')
    await loadConflicts()
  } catch (error) {
    console.error('Failed to resolve graph conflict:', error)
    message.error(error?.message || '冲突裁决保存失败')
  } finally {
    submitting.value = false
  }
}

const severityLabel = (value) =>
  ({ critical: '严重', high: '高', medium: '中', low: '低' })[value] || value
const statusLabel = (value) =>
  ({ open: '待裁决', resolved: '已解决', dismissed: '已忽略', superseded: '已废弃' })[value] ||
  value
const hasDetails = (value) => value && Object.keys(value).length > 0
const formatTime = (value) => (value ? new Date(value).toLocaleString() : '未记录')

watch(
  () => [props.active, props.kbId],
  ([active]) => {
    if (active) loadConflicts()
  },
  { immediate: true }
)
</script>

<style scoped>
.conflict-toolbar,
.resolution-actions,
.conflict-detail header,
.conflict-state {
  display: flex;
  align-items: center;
  gap: 10px;
}

.conflict-toolbar {
  margin-bottom: 14px;
}

.status-filter,
.severity-filter {
  width: 140px;
}

.conflict-count {
  flex: 1;
  color: var(--gray-500);
}

.conflict-layout {
  display: grid;
  grid-template-columns: minmax(260px, 0.8fr) minmax(0, 1.7fr);
  min-height: 520px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  overflow: hidden;
}

.conflict-list {
  overflow-y: auto;
  border-right: 1px solid var(--gray-200);
  background: var(--gray-50);
}

.conflict-item {
  width: 100%;
  padding: 14px;
  border: 0;
  border-bottom: 1px solid var(--gray-200);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.conflict-item strong,
.conflict-item small {
  display: block;
  margin-top: 5px;
}

.conflict-item small,
.eyebrow {
  color: var(--gray-500);
}

.conflict-item.active {
  background: var(--color-primary-50);
}

.severity {
  color: var(--color-warning-700);
  font-size: 12px;
  font-weight: 600;
}

.severity[data-severity='critical'],
.severity[data-severity='high'] {
  color: var(--color-error-700);
}

.conflict-detail {
  padding: 20px;
  overflow-y: auto;
}

.conflict-detail header {
  justify-content: space-between;
  align-items: flex-start;
}

.conflict-detail h3 {
  margin: 4px 0 18px;
}

.conflict-detail dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.conflict-detail dt {
  color: var(--gray-500);
  font-size: 12px;
}

.conflict-detail dd {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
}

.conflict-details {
  max-height: 170px;
  margin: 16px 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-50);
  white-space: pre-wrap;
}

.resolution-actions {
  justify-content: flex-end;
}

.resolution-result,
.conflict-state {
  margin-top: 16px;
}

.conflict-state {
  min-height: 360px;
  flex-direction: column;
  justify-content: center;
  color: var(--gray-500);
}

.conflict-state.error {
  min-height: 120px;
  color: var(--color-error-700);
}

@media (max-width: 760px) {
  .conflict-layout,
  .conflict-detail dl {
    grid-template-columns: 1fr;
  }

  .conflict-list {
    max-height: 220px;
    border-right: 0;
    border-bottom: 1px solid var(--gray-200);
  }
}
</style>
