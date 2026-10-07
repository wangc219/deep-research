<script setup>
import { computed } from 'vue'
import { Activity, Boxes, Cpu, Gauge, RefreshCw, Settings } from '@lucide/vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  usage: { type: Object, default: null },
  loading: { type: Boolean, default: false }
})
const router = useRouter()
const summary = computed(() => props.usage?.summary || {})
const cards = computed(() => [
  { label: '已记录调用', value: Number(summary.value.call_count || 0).toLocaleString(), icon: Cpu },
  { label: '已上报 Token', value: Number(summary.value.total_tokens || 0).toLocaleString(), icon: Gauge },
  { label: '运行次数', value: Number(summary.value.run_count || 0).toLocaleString(), icon: Activity },
  { label: 'Token 上报率', value: `${summary.value.usage_call_coverage_rate ?? summary.value.coverage_rate ?? 100}%`, icon: Boxes },
  { label: '失败调用', value: Number(summary.value.failed_call_count || 0).toLocaleString(), icon: Activity },
  { label: '平均调用耗时', value: summary.value.average_call_duration_ms == null ? '—' : `${(summary.value.average_call_duration_ms / 1000).toFixed(1)}s`, icon: Gauge },
  { label: '待同步调用', value: Number(summary.value.pending_sync_call_count || 0).toLocaleString(), icon: RefreshCw }
])
</script>

<template>
  <a-card class="dashboard-card model-usage-card" :loading="loading">
    <template #title>
      <div class="usage-title">
        <span>统一模型用量</span>
        <small>对话、Query、研究、反馈与知识库模型调用</small>
      </div>
    </template>
    <template #extra>
      <button class="settings-link" type="button" @click="router.push('/models')">
        <Settings :size="14" /> 模型设置
      </button>
    </template>

    <div class="usage-layout">
      <div class="usage-summary">
        <div v-for="item in cards" :key="item.label" class="usage-metric">
          <component :is="item.icon" :size="16" />
          <div><strong>{{ item.value }}</strong><span>{{ item.label }}</span></div>
        </div>
      </div>

      <div class="usage-table-wrap">
        <table class="usage-table">
          <thead><tr><th>业务入口</th><th>运行</th><th>调用</th><th>Token</th><th>失败调用</th></tr></thead>
          <tbody>
            <tr v-for="item in usage?.by_surface || []" :key="item.surface">
              <td>{{ item.surface }}</td>
              <td>{{ Number(item.run_count || 0).toLocaleString() }}</td>
              <td>{{ Number(item.call_count || 0).toLocaleString() }}</td>
              <td>{{ Number(item.total_tokens || 0).toLocaleString() }}</td>
              <td :class="{ danger: item.failed_call_count }">{{ item.failed_call_count ?? '—' }}</td>
            </tr>
            <tr v-if="!(usage?.by_surface || []).length"><td colspan="5" class="empty">近 30 天暂无调用</td></tr>
          </tbody>
        </table>
      </div>

      <div class="model-ranking">
        <h4>模型分布</h4>
        <div v-for="item in (usage?.by_model || []).slice(0, 5)" :key="item.model_spec" class="model-row">
          <span :title="item.model_spec">{{ item.model_spec }}</span>
          <b>{{ Number(item.total_tokens || 0).toLocaleString() }} tokens</b>
        </div>
        <div v-if="!(usage?.by_model || []).length" class="empty">暂无模型用量</div>
      </div>
    </div>
    <p class="usage-note">
      调用与 Token 为已记录数据；历史任务缺少记录时，0 不代表实际没有消耗。
      Token 上报率仅针对已知调用，失败数与平均耗时仅针对有逐次记录的调用。
      <span v-if="summary.run_count > summary.reported_run_count">
        当前 {{ summary.run_count - summary.reported_run_count }} 次运行尚无 Token 上报。
      </span>
      <span v-if="summary.pending_sync_call_count">
        当前 {{ summary.pending_sync_call_count }} 次调用等待 PostgreSQL 恢复后自动补写。
      </span>
    </p>
  </a-card>
</template>

<style scoped>
.model-usage-card { height: 100%; }
.usage-note { margin: 16px 0 0; color: var(--gray-500); font-size: 12px; line-height: 1.7; }
.usage-title { display: flex; align-items: baseline; gap: 10px; }
.usage-title small { color: var(--gray-500); font-size: 11px; font-weight: 400; }
.settings-link { display: inline-flex; align-items: center; gap: 5px; border: 0; background: transparent; color: var(--main-color); font-size: 12px; cursor: pointer; }
.usage-layout { display: grid; grid-template-columns: 1.1fr 1.25fr .95fr; gap: 20px; align-items: stretch; }
.usage-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.usage-metric { display: flex; align-items: center; gap: 10px; min-height: 70px; padding: 12px; border: 1px solid var(--gray-100); border-radius: 10px; background: var(--gray-25); color: var(--main-color); }
.usage-metric div { display: flex; flex-direction: column; min-width: 0; }.usage-metric strong { color: var(--gray-900); font-size: 18px; }.usage-metric span { color: var(--gray-500); font-size: 11px; }
.usage-table { width: 100%; border-collapse: collapse; font-size: 12px; }.usage-table th { color: var(--gray-500); font-weight: 500; text-align: right; }.usage-table th:first-child, .usage-table td:first-child { text-align: left; }.usage-table td { padding: 9px 0; border-bottom: 1px solid var(--gray-100); color: var(--gray-700); text-align: right; }.usage-table .danger { color: #b4505b; }
.model-ranking h4 { margin: 0 0 9px; font-size: 12px; }.model-row { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--gray-100); font-size: 11px; }.model-row span { overflow: hidden; color: var(--gray-700); text-overflow: ellipsis; white-space: nowrap; }.model-row b { flex: 0 0 auto; color: var(--gray-500); font-weight: 500; }.empty { padding: 18px 0 !important; color: var(--gray-400) !important; text-align: center !important; }
@media (max-width: 1100px) { .usage-layout { grid-template-columns: 1fr; } }
@media (max-width: 600px) {
  .usage-title { flex-direction: column; align-items: flex-start; gap: 4px; white-space: normal; }
  .usage-title small { overflow-wrap: anywhere; }
  .usage-layout > * { min-width: 0; }
  .usage-table-wrap { overflow-x: auto; }
  .usage-table { min-width: 360px; }
  .usage-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .usage-metric { flex-wrap: wrap; padding: 10px; }
  .usage-metric strong { overflow-wrap: anywhere; }
  .model-row { flex-wrap: wrap; gap: 4px; }
}
</style>
