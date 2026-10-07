<script setup>
import { computed, onMounted, ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { ChevronRight, ClipboardList, FileSearch, FileText, LibraryBig, MessageCircle, MessageCirclePlus, Radar, SlidersHorizontal, Trash2 } from '@lucide/vue'
import { equipmentApi } from '@/apis/equipment_api'
import { formatRelative } from '@/utils/time'

const loading = ref(false)
const deletingRunId = ref('')
const portal = ref({ stats: {}, recent_runs: [], recent_queries: [], shortcuts: [] })

const stats = computed(() => [
  { label: '研究任务', value: portal.value.stats?.runs || 0, path: '/equipment/runs', icon: Radar },
  {
    label: '已完成报告',
    value: portal.value.stats?.completed_runs || 0,
    path: '/equipment/reports',
    icon: FileText
  },
  {
    label: '需求 Query',
    value: portal.value.stats?.queries || 0,
    path: '/equipment/queries',
    icon: FileSearch
  },
  {
    label: '深研对话',
    value: portal.value.stats?.deep_sessions || 0,
    path: '/equipment/deep-thinking',
    icon: MessageCircle
  },
  {
    label: '能力画像',
    value: portal.value.stats?.capabilities || 0,
    path: '/equipment/capabilities',
    icon: ClipboardList
  }
])

const iconByPath = {
  '/extensions': LibraryBig,
  '/agent': MessageCirclePlus,
  '/models': SlidersHorizontal
}

const shortcutHints = {
  '/extensions': '检索文档与技能',
  '/agent': '打开研究助手',
  '/models': '配置研究模型'
}

const shortcutItems = computed(() => {
  const covered = new Set(stats.value.map((item) => item.path))
  return (portal.value.shortcuts || [])
    .filter((item) => item?.path && !covered.has(item.path))
    .map((item) => ({
      ...item,
      icon: iconByPath[item.path] || FileText,
      hint: shortcutHints[item.path] || '进入对应工作区'
    }))
})

const load = async () => {
  loading.value = true
  try {
    const payload = await equipmentApi.getPortal()
    portal.value = payload?.stats ? payload : payload?.data || payload
  } catch (error) {
    message.error(error.message || '知识门户加载失败')
  } finally {
    loading.value = false
  }
}

const statusMap = {
  completed: '已完成',
  published: '已发布',
  draft: '草稿',
  archived: '已归档',
  failed: '失败',
  researching: '研究中'
}

const statusTone = {
  completed: 'success',
  published: 'success',
  draft: 'muted',
  archived: 'muted',
  failed: 'danger',
  researching: 'accent'
}

const statusText = (value) => statusMap[value] || value || ''
const toneOf = (value) => statusTone[value] || 'muted'
const formatCount = (value) => Number(value || 0).toLocaleString('zh-CN')
const timeText = (value) => {
  const text = formatRelative(value)
  return text && text !== '-' ? text : ''
}

const confirmDelete = (run) => new Promise((resolve) => {
  Modal.confirm({
    title: '永久删除研究草稿',
    content: `确定删除“${run.topic}”吗？草稿数据删除后无法恢复。`,
    okText: '永久删除',
    cancelText: '取消',
    okButtonProps: { danger: true },
    onOk: () => resolve(true),
    onCancel: () => resolve(false)
  })
})

const deleteDraftRun = async (run) => {
  if (run.status !== 'draft' || deletingRunId.value) return
  if (!await confirmDelete(run)) return
  deletingRunId.value = run.run_id
  try {
    await equipmentApi.deleteRun(run.run_id)
    message.success('研究草稿已删除')
    await load()
  } catch (error) {
    message.error(error.message || '研究草稿删除失败')
  } finally {
    deletingRunId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="knowledge-portal">
    <header class="kp-hero">
      <p class="kp-kicker">知识总览</p>
      <h1>领域知识总门户</h1>
      <p class="kp-lead">当前身份可见的研究任务、需求 Query、能力画像与知识库入口。</p>
    </header>

    <a-spin :spinning="loading">
      <section class="kp-stats" aria-label="研究资产概览">
        <router-link
          v-for="item in stats"
          :key="item.label"
          :to="item.path"
          class="kp-stat"
          :aria-label="`${item.label} ${formatCount(item.value)}`"
        >
          <span class="kp-stat-icon" aria-hidden="true">
            <component :is="item.icon" :size="18" />
          </span>
          <span class="kp-stat-copy">
            <span class="kp-stat-value">{{ formatCount(item.value) }}</span>
            <span class="kp-stat-label">{{ item.label }}</span>
          </span>
        </router-link>
      </section>

      <nav v-if="shortcutItems.length" class="kp-actions" aria-label="其他入口">
        <router-link
          v-for="item in shortcutItems"
          :key="item.path"
          :to="item.path"
          class="kp-stat"
        >
          <span class="kp-stat-icon" aria-hidden="true">
            <component :is="item.icon" :size="18" />
          </span>
          <span class="kp-stat-copy">
            <span class="kp-stat-value">{{ item.name }}</span>
            <span class="kp-stat-label">{{ item.hint }}</span>
          </span>
          <ChevronRight class="kp-row-arrow" :size="16" aria-hidden="true" />
        </router-link>
      </nav>

      <div class="kp-panels">
        <section class="kp-panel">
          <header class="kp-panel-head">
            <h2>最近研究任务</h2>
            <router-link class="kp-more" to="/equipment/runs">全部</router-link>
          </header>
          <div v-if="!portal.recent_runs?.length" class="kp-empty">还没有研究任务</div>
          <ul v-else class="kp-list">
            <li v-for="run in portal.recent_runs" :key="run.run_id" class="kp-run-row">
              <router-link class="kp-row" :to="`/equipment/runs/${run.run_id}`">
                <span class="kp-row-body">
                  <span class="kp-row-title">{{ run.topic }}</span>
                  <span v-if="timeText(run.updated_at)" class="kp-row-meta">{{
                    timeText(run.updated_at)
                  }}</span>
                </span>
                <span class="kp-badge" :data-tone="toneOf(run.status)">{{
                  statusText(run.status)
                }}</span>
                <ChevronRight class="kp-row-arrow" :size="16" aria-hidden="true" />
              </router-link>
              <button
                v-if="run.status === 'draft'"
                type="button"
                class="kp-delete-run"
                :disabled="deletingRunId === run.run_id"
                :aria-label="`删除研究草稿 ${run.topic}`"
                title="永久删除研究草稿"
                @click="deleteDraftRun(run)"
              >
                <Trash2 :size="15" aria-hidden="true" />
              </button>
            </li>
          </ul>
        </section>

        <section class="kp-panel">
          <header class="kp-panel-head">
            <h2>最近需求 Query</h2>
            <router-link class="kp-more" to="/equipment/queries">全部</router-link>
          </header>
          <div v-if="!portal.recent_queries?.length" class="kp-empty">还没有 Query</div>
          <ul v-else class="kp-list">
            <li v-for="item in portal.recent_queries" :key="item.query_id">
              <router-link class="kp-row" to="/equipment/queries">
                <span class="kp-row-body">
                  <span class="kp-row-title">{{ item.query }}</span>
                  <span v-if="timeText(item.updated_at)" class="kp-row-meta">{{
                    timeText(item.updated_at)
                  }}</span>
                </span>
                <span class="kp-badge" :data-tone="toneOf(item.status)">{{
                  statusText(item.status)
                }}</span>
                <ChevronRight class="kp-row-arrow" :size="16" aria-hidden="true" />
              </router-link>
            </li>
          </ul>
        </section>
      </div>
    </a-spin>
  </div>
</template>

<style scoped>
.knowledge-portal {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
  padding: 20px 16px 32px;
  background:
    radial-gradient(1200px 280px at 12% -10%, color-mix(in srgb, var(--main-50) 80%, transparent), transparent 70%),
    var(--gray-25);
}

.kp-hero {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 2px 2px;
}

.kp-kicker {
  margin: 0;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--main-color);
}

.kp-hero h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--gray-900);
}

.kp-lead {
  margin: 0;
  max-width: 42em;
  color: var(--gray-600);
  font-size: 14px;
  line-height: 1.55;
}

.kp-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.kp-actions {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.kp-stat,
.kp-row,
.kp-more {
  color: inherit;
  text-decoration: none;
}

.kp-stat {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 92px;
  padding: 16px;
  text-align: left;
  cursor: pointer;
  border: 1px solid var(--gray-200);
  border-radius: 14px;
  background: var(--gray-0);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--gray-900) 4%, transparent);
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    transform 0.16s ease,
    background 0.16s ease;
}

.kp-stat:hover {
  border-color: color-mix(in srgb, var(--main-color) 40%, var(--gray-200));
  background: var(--main-10);
  box-shadow: 0 8px 20px color-mix(in srgb, var(--main-color) 10%, transparent);
  transform: translateY(-1px);
}

.kp-stat:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 2px;
}

.kp-stat-icon {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: var(--main-color);
  background: var(--main-50);
}

.kp-stat-copy {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 4px;
}

.kp-stat-value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.03em;
  color: var(--gray-900);
}

.kp-actions .kp-stat-value {
  font-size: 16px;
  letter-spacing: 0;
  white-space: nowrap;
}

.kp-actions .kp-stat-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kp-stat-label {
  font-size: 13px;
  color: var(--gray-600);
}

.kp-panels {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.kp-panel {
  overflow: hidden;
  border: 1px solid var(--gray-200);
  border-radius: 14px;
  background: var(--gray-0);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--gray-900) 4%, transparent);
}

.kp-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px 8px;
}

.kp-panel-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--gray-900);
}

.kp-more {
  padding: 0;
  border: 0;
  background: none;
  color: var(--main-color);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.kp-more:hover,
.kp-more:focus-visible {
  text-decoration: underline;
}

.kp-list {
  list-style: none;
  margin: 0;
  padding: 4px 8px 10px;
}

.kp-run-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 34px;
  align-items: center;
  gap: 2px;
}

.kp-delete-run {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--gray-500);
  cursor: pointer;
}

.kp-delete-run:hover,
.kp-delete-run:focus-visible {
  background: var(--color-error-50);
  color: var(--color-error-700);
}

.kp-delete-run:focus-visible {
  outline: 2px solid var(--color-error-500);
  outline-offset: 1px;
}

.kp-delete-run:disabled {
  cursor: wait;
  opacity: 0.45;
}

.kp-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 16px;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 8px;
  border: 0;
  border-radius: 12px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.kp-row:hover,
.kp-row:focus-visible {
  background: var(--main-30);
}

.kp-row:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: -2px;
}

.kp-row-body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.kp-row-title {
  display: -webkit-box;
  overflow: hidden;
  color: var(--gray-900);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.kp-row-meta {
  color: var(--gray-500);
  font-size: 12px;
}

.kp-badge {
  flex: 0 0 auto;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.5;
  white-space: nowrap;
  background: var(--gray-100);
  color: var(--gray-700);
}

.kp-badge[data-tone='success'] {
  background: var(--color-success-50);
  color: var(--color-success-700);
}

.kp-badge[data-tone='accent'] {
  background: var(--main-50);
  color: var(--main-700);
}

.kp-badge[data-tone='danger'] {
  background: var(--color-error-50);
  color: var(--color-error-700);
}

.kp-row-arrow {
  flex: 0 0 auto;
  color: var(--main-400);
}

.kp-empty {
  padding: 28px 16px 32px;
  color: var(--gray-500);
  font-size: 14px;
  text-align: center;
}

@media (min-width: 720px) {
  .knowledge-portal {
    padding: 24px 24px 40px;
    gap: 20px;
  }

  .kp-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .kp-actions {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .kp-panels {
    grid-template-columns: 1fr 1fr;
    align-items: start;
  }
}

@media (min-width: 1100px) {
  .kp-stats {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }

  .kp-stat {
    flex-direction: column;
    align-items: flex-start;
    min-height: 124px;
    padding: 18px;
  }

  .kp-actions .kp-stat {
    flex-direction: row;
    align-items: center;
    min-height: 96px;
  }

  .kp-stat-value {
    font-size: 28px;
  }

  .kp-actions .kp-stat-value {
    font-size: 16px;
  }
}
</style>
