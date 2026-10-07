<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import '@/assets/css/equipment-workbench-live.css'
import '@/assets/css/equipment-research-launch.css'
import '@/assets/css/equipment-workbench-theme.css'
import { useRouter } from 'vue-router'
import { Modal, message } from 'ant-design-vue'
import { storeToRefs } from 'pinia'
import { CheckCircleOutlined, ClockCircleOutlined, DeleteOutlined, ExperimentOutlined, EyeOutlined, InboxOutlined, ReloadOutlined, SearchOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import { Activity, BrainCircuit, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, FileCheck2, Layers3, ListFilter, MessageSquare, Minus, Play, Plus, RefreshCw, Search, ShieldCheck, Sparkles, Trash2, Wrench, X } from '@lucide/vue'
import { equipmentApi } from '@/apis/equipment_api'
import { createIdempotencyKey } from '@/apis/base'
import { useEquipmentStore } from '@/stores/equipment'
import { useProjectsStore } from '@/stores/projects'
import { useUserStore } from '@/stores/user'
import { projectDisplayName } from '@/utils/projectSelection'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { useEquipmentModelPrefill } from '@/composables/useEquipmentModelPrefill'
import { inheritKnowledgeScope, normalizePagedResult } from '@/utils/equipmentQueries'

const RESEARCH_MODE_PROFILES = [
  { id: 'legacy_v1', name: '传统固定编排', short_name: '传统模式', description: '固定流程执行，适合兼容回滚与对照。', badge: '兼容' },
  { id: 'optimized_v2', name: '协同优化编排', short_name: '协同模式', description: '3–4 个业务 Agent 并行，并进入 S1–S6 Cohort。', recommended: true, badge: '推荐' },
  { id: 'swarm_quality_v1', name: '质量残差蜂群', short_name: '质量集群', description: '按质量残差弹性孵化，最多 12 个 Agent。', badge: '高质量' },
  { id: 'winning_swarm_dynamic_v2', name: 'Mission Graph 动态蜂群', short_name: '动态蜂群', description: '8–21 个实例动态孵化，提供最高并发能力。', default: true, badge: '最高并发' }
]

const router = useRouter()
const equipmentStore = useEquipmentStore()
const projectsStore = useProjectsStore()
const userStore = useUserStore()
const { projects } = storeToRefs(projectsStore)
const { resources, loading: resourceLoading } = storeToRefs(equipmentStore)
const runs = computed(() => resources.value.runs)
const loading = computed(() => Boolean(resourceLoading.value.runs))
const creating = ref(false)
const configOpen = ref(false)
const search = ref('')
const status = ref('all')
const actionRunId = ref('')
const selectedRunIds = ref([])
const runtime = ref({ configured_capacity: 4, capacity_limit: 8, active_count: 0, available_slots: 4, pending_count: 0, parallel_enabled: true, can_manage: false, active_tasks: [] })
const runtimeLoading = ref(false)
const runtimeError = ref('')
const capacityDraft = ref(4)
const capacitySaving = ref(false)
const capacityEditing = ref(false)
const recommendations = ref([])
const recommendationLoading = ref(false)
const recommendationError = ref('')
const recommendationIndex = ref(0)
const recommendationPaused = ref(false)
const selectedRecommendationId = ref('')
const selectedRecommendation = computed(() =>
  recommendations.value.find((item) => item.query_id === selectedRecommendationId.value) || null
)
let recommendationTimer = null
let runtimeTimer = null
const form = reactive({
  project_id: '',
  topic: '',
  supplemental_information: '',
  research_route: 'auto',
  execution_profile_id: 'winning_swarm_dynamic_v2',
  model_spec: '',
  source_query_id: '',
  source_query_version: undefined,
  start: true
})
const { hasDefaultModel } = useEquipmentModelPrefill(form)
const selectedResearchMode = computed(() => (
  RESEARCH_MODE_PROFILES.find((item) => item.id === form.execution_profile_id)
  || RESEARCH_MODE_PROFILES.find((item) => item.recommended)
))
const activeStatuses = new Set(['queued', 'planning', 'researching', 'recalling', 'synthesizing', 'reviewing', 'reporting', 'pause_requested'])
const statusLabels = { draft: '草稿', queued: '已排队', planning: '规划中', researching: '研究中', recalling: '再调中', synthesizing: '综合中', reviewing: '审计中', reporting: '报告生成中', completed: '已完成', failed: '失败', paused: '已暂停', cancelled: '已取消', archived: '已归档' }
const counts = computed(() => ({
  current: runs.value.filter((item) => item.status !== 'archived').length,
  active: runs.value.filter((item) => activeStatuses.has(item.status)).length,
  completed: runs.value.filter((item) => item.status === 'completed').length,
  failed: runs.value.filter((item) => item.status === 'failed').length
}))
const visibleRuns = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return runs.value.filter((item) => {
    const matchesStatus = status.value === 'all' ? item.status !== 'archived' : status.value === 'active' ? activeStatuses.has(item.status) : item.status === status.value
    return matchesStatus && (!keyword || `${item.topic || ''} ${item.supplemental_information || ''} ${item.run_id || ''}`.toLowerCase().includes(keyword))
  })
})
const selectedDeletableRuns = computed(() => runs.value.filter((item) => (
  selectedRunIds.value.includes(item.run_id) && !activeStatuses.has(item.status)
)))
const latestCompleted = computed(() => runs.value.find((item) => item.status === 'completed') || null)
const runtimeSlots = computed(() => Array.from(
  { length: Math.max(runtime.value.configured_capacity || 1, runtime.value.active_count || 0) },
  (_, index) => runtime.value.active_tasks?.[index] || null
))
const runById = computed(() => new Map(runs.value.map((item) => [String(item.run_id), item])))
const runtimeTransitionText = computed(() => {
  if (runtime.value.active_count > runtime.value.configured_capacity) {
    return `正在平滑缩容；${runtime.value.active_count - runtime.value.configured_capacity} 个既有任务结束后生效`
  }
  if (runtime.value.pending_count) return `${runtime.value.pending_count} 个任务排队等待空闲槽位`
  return `${runtime.value.available_slots} 个槽位可立即执行新任务`
})
const shuffleRecommendations = (items) => {
  const shuffled = [...items]
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1))
    ;[shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]]
  }
  return shuffled
}
const loadRecommendations = async () => {
  recommendationLoading.value = true
  try {
    const payload = await equipmentApi.listQueries({ limit: 200, offset: 0 })
    const items = normalizePagedResult(payload, 200).items
      .filter((item) => item?.query && item.status !== 'archived')
    recommendations.value = shuffleRecommendations(items)
    recommendationIndex.value = 0
    recommendationError.value = items.length ? '' : '问题库中暂无可推荐 Query'
  } catch {
    recommendationError.value = '问题库暂时无法连接'
  } finally {
    recommendationLoading.value = false
  }
}
const moveRecommendation = (direction) => {
  const total = recommendations.value.length
  if (!total) return
  recommendationIndex.value = (recommendationIndex.value + direction + total) % total
}
const recommendationPosition = (index) => {
  const total = recommendations.value.length
  const forwardOffset = (index - recommendationIndex.value + total) % total
  const offset = forwardOffset > total / 2 ? forwardOffset - total : forwardOffset
  if (Math.abs(offset) > 2) return ''
  if (offset === 0) return 'current'
  if (offset === -1) return 'previous'
  if (offset === 1) return 'next'
  return offset < 0 ? 'far-previous' : 'far-next'
}
const chooseRecommendation = (item, index) => {
  recommendationIndex.value = index
  selectedRecommendationId.value = item.query_id || ''
  form.source_query_id = item.query_id || ''
  form.source_query_version = Number(item.version) || 1
  form.topic = item.query || ''
  form.supplemental_information = item.supplemental_information || ''
}
const clearSelectedRecommendation = () => {
  selectedRecommendationId.value = ''
  form.source_query_id = ''
  form.source_query_version = undefined
}
const clearQuery = () => {
  form.topic = ''
  form.supplemental_information = ''
  clearSelectedRecommendation()
  document.getElementById('research-query-input')?.focus()
}
const openSupplement = () => {
  configOpen.value = true
  requestAnimationFrame(() => document.getElementById('research-query-supplement')?.focus())
}
const selectResearchMode = (event, profileId) => {
  form.execution_profile_id = profileId
  event.currentTarget.closest('details')?.removeAttribute('open')
}
const syncRecommendationTimer = () => {
  if (recommendationTimer) window.clearInterval(recommendationTimer)
  recommendationTimer = null
  if (recommendationPaused.value || recommendations.value.length < 2) return
  recommendationTimer = window.setInterval(() => {
    if (!document.hidden) moveRecommendation(1)
  }, 5000)
}
const loadRuntime = async ({ silent = false } = {}) => {
  if (!silent) runtimeLoading.value = true
  try {
    const data = await equipmentApi.getResearchRuntime()
    runtime.value = data
    capacityDraft.value = data.configured_capacity
    runtimeError.value = ''
  } catch (error) {
    if (!silent) runtimeError.value = error.message || '并行槽位状态加载失败'
  } finally {
    if (!silent) runtimeLoading.value = false
  }
}
const applyResearchCapacity = async () => {
  const capacity = Number(capacityDraft.value)
  if (!Number.isInteger(capacity) || capacity < 1 || capacity > runtime.value.capacity_limit) return
  capacitySaving.value = true
  try {
    runtime.value = await equipmentApi.updateResearchCapacity(capacity)
    capacityDraft.value = runtime.value.configured_capacity
    capacityEditing.value = false
    runtimeError.value = ''
    message.success(`研究任务并行槽位已调整为 ${capacity}`)
  } catch (error) {
    runtimeError.value = error.message || '并行槽位调整失败'
    message.error(runtimeError.value)
  } finally {
    capacitySaving.value = false
  }
}
const startRuntimePolling = () => {
  if (runtimeTimer) window.clearInterval(runtimeTimer)
  runtimeTimer = window.setInterval(() => {
    if (!document.hidden) void loadRuntime({ silent: true })
  }, 5000)
}
const stopRuntimePolling = () => {
  if (runtimeTimer) window.clearInterval(runtimeTimer)
  runtimeTimer = null
}
const artifactCount = (run, key) => Number(run?.artifact_counts?.[key] || run?.result?.[`${key.replace(/s$/, '')}_count`] || 0)
const deepSessionCount = (run) => Math.max(
  artifactCount(run, 'deep_sessions'),
  Number(run?.deep_session_count || run?.result?.deep_session_count || 0)
)
const routeLabel = (value) => ({
  auto: '自动',
  new_winning_mechanism: '新制胜机理',
  traditional_gap: '传统能力缺口',
  war_case_learning: '局部战争案例'
}[value] || value || '自动')
const toggleSelectedRun = (runId) => {
  selectedRunIds.value = selectedRunIds.value.includes(runId)
    ? selectedRunIds.value.filter((item) => item !== runId)
    : [...selectedRunIds.value, runId]
}
const formatUpdatedAt = (value) => {
  if (!value) return '尚无运行记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return `更新于 ${new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)}`
}
const load = async () => {
  try {
    await Promise.all([projectsStore.loadProjects().catch(() => []), equipmentStore.loadResource('runs', {}, { force: true })])
    const availableIds = new Set(runs.value.map((item) => item.run_id))
    selectedRunIds.value = selectedRunIds.value.filter((item) => availableIds.has(item))
    if (!form.project_id && projects.value[0]?.id) form.project_id = projects.value[0].id
  } catch (error) { message.error(error.message || '任务列表加载失败') }
}
const createRun = async () => {
  if (!form.topic.trim() || !form.project_id) return message.warning('请选择项目并填写研究问题')
  if (creating.value) return
  creating.value = true
  let created = null
  try {
    const requestId = createIdempotencyKey('research-run')
    created = await equipmentApi.createResearchRun({
      topic: form.topic.trim(),
      supplemental_information: form.supplemental_information.trim(),
      research_route: form.research_route,
      execution_profile_id: form.execution_profile_id,
      ...(form.model_spec ? { execution: { model_spec: form.model_spec } } : {}),
      ...(selectedRecommendation.value ? inheritKnowledgeScope(selectedRecommendation.value) : {}),
      source_query_id: form.source_query_id || undefined,
      source_query_version: form.source_query_id ? form.source_query_version : undefined
    }, { projectId: form.project_id, idempotencyKey: `create:${requestId}` })
    if (form.start) await equipmentApi.startResearchRun(created.run_id, {
      idempotencyKey: `start:${requestId}:${created.run_id}`
    })
    form.topic = ''; form.supplemental_information = ''; clearSelectedRecommendation(); configOpen.value = false
    await load()
    message.success(form.start ? '研究任务已创建并启动' : '研究草稿已创建')
    await router.push(`/equipment/runs/${encodeURIComponent(created.run_id)}`)
  } catch (error) {
    if (created?.run_id) {
      message.warning(`任务已创建，但启动或列表刷新未完成：${error.message || '请检查任务状态'}`)
      await router.push(`/equipment/runs/${encodeURIComponent(created.run_id)}`)
    } else message.error(error.message || '创建任务失败')
  } finally { creating.value = false }
}
const confirmAction = (title, content, danger = false) => new Promise((resolve) => Modal.confirm({ title, content, okText: '确认', cancelText: '取消', okButtonProps: danger ? { danger: true } : {}, onOk: () => resolve(true), onCancel: () => resolve(false) }))
const actOnRun = async (action, run) => {
  const actions = { pause: [equipmentApi.pauseRun, '已请求暂停'], resume: [equipmentApi.resumeRun, '已恢复执行'], cancel: [equipmentApi.cancelRun, '已停止任务'], delete: [equipmentApi.deleteRun, '已删除任务'] }
  if (action === 'delete' && !await confirmAction('永久删除研究任务', `确定删除“${run.topic}”吗？任务数据和产物可能无法恢复。`, true)) return
  if (action === 'cancel' && !await confirmAction('停止研究任务', `确定停止“${run.topic}”吗？当前执行将终止，已保存的进度仍会保留。`, true)) return
  actionRunId.value = run.run_id
  try { await actions[action][0](run.run_id); message.success(actions[action][1]); await load() } catch (error) { message.error(error.message || '任务操作失败') } finally { actionRunId.value = '' }
}
const deleteSelectedRuns = async () => {
  const targets = selectedDeletableRuns.value
  if (!targets.length) return
  if (!await confirmAction('永久删除所选任务', `确定删除所选的 ${targets.length} 个非运行中任务吗？任务数据和产物可能无法恢复。`, true)) return
  actionRunId.value = '__bulk_delete__'
  try {
    const results = await Promise.allSettled(targets.map((item) => equipmentApi.deleteRun(item.run_id)))
    const failed = results.filter((item) => item.status === 'rejected').length
    selectedRunIds.value = []
    await load()
    if (failed) message.warning(`${targets.length - failed} 个任务删除成功，${failed} 个失败`)
    else message.success(`已删除 ${targets.length} 个任务`)
  } finally {
    actionRunId.value = ''
  }
}
const openArtifact = (run, target) => {
  if (target === 'deep-thinking') return router.push(`/equipment/deep-thinking?run=${encodeURIComponent(run.run_id)}`)
  if (target === 'capabilities') return router.push(`/equipment/capabilities?run=${encodeURIComponent(run.run_id)}`)
  if (target === 'reports') return router.push(`/equipment/reports?run=${encodeURIComponent(run.run_id)}`)
  return router.push(`/equipment/runs/${encodeURIComponent(run.run_id)}?tab=${target}`)
}
watch([recommendationPaused, () => recommendations.value.length], syncRecommendationTimer)
onMounted(() => { void load(); void loadRecommendations(); void loadRuntime(); startRuntimePolling() })
onActivated(() => { if (runs.value.length) load(); void loadRuntime({ silent: true }); startRuntimePolling() })
onDeactivated(stopRuntimePolling)
onBeforeUnmount(() => { if (recommendationTimer) window.clearInterval(recommendationTimer); stopRuntimePolling() })
</script>

<template>
  <div class="equipment-runs-page">
    <section class="research-query-home"><div class="research-query-hero">
      <span>DEEP RESEARCH QUERY</span><h1 class="research-theme-title">创新为帆 探索未至之境</h1>
      <div class="research-query-composer" :class="{ 'config-open': configOpen }">
        <textarea id="research-query-input" v-model="form.topic" aria-label="Deep Research Query" maxlength="4000" placeholder="输入需要进行 Deep Research 的 Query，例如：研究低空无人装备在强对抗环境中的体系能力缺口" @input="clearSelectedRecommendation" @keydown.meta.enter="createRun" @keydown.ctrl.enter="createRun" />
        <div class="research-query-input-state"><span>{{ form.topic.trim() ? `已输入 ${form.topic.trim().length} 字` : '等待输入研究问题' }}</span><span><kbd>⌘/Ctrl</kbd> + <kbd>Enter</kbd> 快速启动</span><button v-if="form.topic" type="button" aria-label="清空 Query" @click="clearQuery"><X :size="12" />清空</button></div>
        <footer><div class="research-query-footer-left"><button type="button" @click="openSupplement"><Plus :size="14" />补充背景与约束</button><details class="research-mode-picker"><summary><Layers3 :size="15" /><span><small>研究模式</small><b>{{ selectedResearchMode.short_name || selectedResearchMode.name }}</b></span><ChevronDown :size="14" /></summary><div class="research-mode-menu"><header><span><b>选择研究模式</b><small>模式将直接控制后端 Agent 编排与并发策略</small></span><em>{{ RESEARCH_MODE_PROFILES.length }} 种</em></header><div><button v-for="item in RESEARCH_MODE_PROFILES" :key="item.id" type="button" :class="{ selected: item.id === selectedResearchMode.id }" @click="selectResearchMode($event, item.id)"><span class="mode-icon"><Layers3 :size="16" /></span><span><b>{{ item.short_name || item.name }}<em>{{ item.badge }}</em></b><small>{{ item.description }}</small><code>{{ item.id }}</code></span><CheckCircle2 v-if="item.id === selectedResearchMode.id" :size="17" /></button></div><div class="research-mode-menu-note"><ShieldCheck :size="13" />所选模式随研究任务保存，可在草稿阶段修改并由 Worker 原样执行。</div></div></details><div class="research-model-picker" :class="{ 'missing-default': !hasDefaultModel && !form.model_spec }" :title="hasDefaultModel || form.model_spec ? '为本次研究任务选择模型' : '尚未配置系统默认模型，请为本次任务选择模型'"><CircleAlert v-if="!hasDefaultModel && !form.model_spec" :size="15" aria-hidden="true" /><BrainCircuit v-else :size="15" aria-hidden="true" /><ModelSelectorComponent upward :model_spec="form.model_spec" size="nano" display-name="mini" :placeholder="hasDefaultModel ? '系统默认模型' : '选择研究模型'" clearable @select-model="(spec) => (form.model_spec = spec || '')" /></div></div><div class="research-query-footer-right"><button type="button" @click="router.push('/equipment/queries')"><Sparkles :size="15" />AI 生成 Query</button><button type="button" class="research-config-trigger" :class="{ active: configOpen }" @click="configOpen = !configOpen"><Wrench :size="14" />{{ configOpen ? '收起运行配置' : '研究运行配置' }}<ChevronDown :size="13" /></button><button type="button" class="primary research-start-trigger" :disabled="!form.topic.trim() || creating" @click="createRun"><Play :size="14" />{{ creating ? '启动中…' : '启动研究' }}</button></div></footer>
        <div v-if="configOpen" class="research-query-inline-config-shell"><textarea id="research-query-supplement" v-model="form.supplemental_information" class="research-query-supplement" maxlength="8000" placeholder="可选：补充作战场景、时间范围、约束、前提假设或希望覆盖的技术/装备类型。" /><div class="vue-run-config-grid"><label><span>所属项目</span><select v-model="form.project_id"><option v-for="item in projects" :key="item.id" :value="item.id">{{ projectDisplayName(item, userStore.isAdmin) }}</option></select></label><label><span>研究路线</span><select v-model="form.research_route"><option value="auto">自动选择</option><option value="new_winning_mechanism">新制胜机理</option><option value="traditional_gap">传统能力缺口</option><option value="war_case_learning">局部战争案例</option></select></label><a-checkbox v-model:checked="form.start">创建后立即排队</a-checkbox></div></div>
      </div>
      <div class="research-query-suggestions"><div class="research-query-suggestion-heading"><span><small>问题库灵感推荐</small><em><i />全库 {{ recommendations.length }} 条 · 自动轮播 · 点击即可带入研究</em></span><button type="button" class="suggestion-refresh" :disabled="recommendationLoading" @click="loadRecommendations"><RefreshCw :class="{ spin: recommendationLoading }" :size="12" />{{ recommendationLoading ? '读取中' : '重新排序' }}</button></div><div v-if="recommendationLoading && !recommendations.length" class="recommendation-skeleton" aria-hidden="true"><div v-for="index in 3" :key="index" /></div><div v-else-if="recommendations.length" class="recommendation-carousel"><button type="button" class="recommendation-playback" :aria-label="recommendationPaused ? '继续自动轮播' : '暂停自动轮播'" @click="recommendationPaused = !recommendationPaused">{{ recommendationPaused ? '继续轮播' : '暂停轮播' }}</button><button type="button" class="recommendation-arrow previous" aria-label="上一条推荐 Query" @click="moveRecommendation(-1)"><ChevronLeft :size="20" /></button><div class="recommendation-stage"><button v-for="(item, index) in recommendations" v-show="recommendationPosition(index)" :key="item.query_id || item.query" type="button" :title="item.query" :data-carousel-offset="recommendationPosition(index)" class="recommendation-card" :class="[recommendationPosition(index), { selected: selectedRecommendationId === item.query_id }]" @click="chooseRecommendation(item, index)"><span>{{ item.source_type === 'agent' ? 'AGENT DISCOVERY' : item.source_type === 'import' ? 'CURATED INSIGHT' : 'RESEARCH IDEA' }}<CheckCircle2 v-if="selectedRecommendationId === item.query_id" :size="14" /></span><b>{{ item.query }}</b><p>{{ item.supplemental_information || item.generation_rationale || '点击将此 Query 带入研究任务。' }}</p></button></div><button type="button" class="recommendation-arrow next" aria-label="下一条推荐 Query" @click="moveRecommendation(1)"><ChevronRight :size="20" /></button></div><div v-else class="recommendation-empty"><span>{{ recommendationError || '问题库中暂无可推荐 Query' }}</span><button type="button" @click="router.push('/equipment/queries')">打开问题库</button></div></div>
    </div></section>

    <section class="page-title"><div><span>RESEARCH WORKSPACE</span><h1>研究任务与运行记录</h1><p>Query 审核后可直接带入研究任务；运行过程、证据、能力画像和报告持续留痕。</p></div><a-button :loading="loading" title="刷新任务" @click="load"><ReloadOutlined /></a-button></section>
    <section class="research-runtime-panel" aria-label="研究任务并行执行状态">
      <header>
        <div class="runtime-heading">
          <span class="runtime-icon"><Activity :size="17" /></span>
          <span><b>{{ runtime.parallel_enabled ? '多任务并行执行已启用' : '单任务执行模式' }}</b><small>每个槽位运行一个独立研究任务，扩容即时生效，缩容不会中断运行中的任务。</small></span>
        </div>
        <div class="runtime-actions">
          <em>{{ runtime.active_count }}/{{ runtime.configured_capacity }} 运行中</em>
          <button v-if="runtime.can_manage" type="button" @click="capacityEditing = !capacityEditing"><Wrench :size="13" />设置槽位</button>
          <button type="button" :disabled="runtimeLoading" title="刷新槽位状态" @click="loadRuntime()"><RefreshCw :class="{ spin: runtimeLoading }" :size="13" /></button>
        </div>
      </header>
      <div v-if="capacityEditing && runtime.can_manage" class="runtime-capacity-editor">
        <span><b>并行研究任务槽位</b><small>可设置 1–{{ runtime.capacity_limit }}；建议按模型额度、CPU 和内存逐步扩展。</small></span>
        <div>
          <button type="button" aria-label="减少研究槽位" :disabled="capacitySaving || capacityDraft <= 1" @click="capacityDraft -= 1"><Minus :size="14" /></button>
          <strong>{{ capacityDraft }}</strong>
          <button type="button" aria-label="增加研究槽位" :disabled="capacitySaving || capacityDraft >= runtime.capacity_limit" @click="capacityDraft += 1"><Plus :size="14" /></button>
          <button type="button" class="primary" :disabled="capacitySaving || capacityDraft === runtime.configured_capacity" @click="applyResearchCapacity">{{ capacitySaving ? '应用中…' : '应用' }}</button>
        </div>
      </div>
      <p v-if="runtimeError" class="runtime-error"><CircleAlert :size="14" />{{ runtimeError }}</p>
      <div class="runtime-slot-grid">
        <article v-for="(task, index) in runtimeSlots" :key="task?.task_id || `slot-${index}`" :class="task ? 'busy' : 'idle'">
          <span>槽位 #{{ index + 1 }}</span>
          <b>{{ task ? (runById.get(task.run_id)?.topic || task.run_id || '研究任务执行中') : '等待研究任务' }}</b>
          <small>{{ task ? '正在并行执行' : '可立即领取任务' }}</small>
        </article>
      </div>
      <footer><span><i :class="runtime.pending_count ? 'queued' : ''" />{{ runtimeTransitionText }}</span><small>容量由 PostgreSQL 原子锁控制，多个 Worker 实例也不会超卖槽位。</small></footer>
    </section>
    <section class="workspace-pulse" aria-label="研究工作台概览"><div class="pulse-heading"><div><span>WORKSPACE PULSE</span><b>今天的研究进展</b></div><small>{{ counts.active ? `${counts.active} 个任务正在推进` : '当前没有运行中的任务' }}</small></div><div class="pulse-metrics"><article class="pulse-metric active"><span>进行中</span><strong>{{ counts.active }}</strong><small>实时跟踪</small></article><article class="pulse-metric success"><span>已完成</span><strong>{{ counts.completed }}</strong><small>可直接阅读报告</small></article><article class="pulse-metric warn"><span>需要处理</span><strong>{{ counts.failed }}</strong><small>{{ counts.failed ? '可从断点继续' : '暂无异常任务' }}</small></article></div><div class="pulse-next"><div><span class="pulse-next-icon"><ThunderboltOutlined /></span><span><b>{{ latestCompleted ? '继续使用最近成果' : '从一个研究问题开始' }}</b><small>{{ latestCompleted?.topic || '输入 Query，系统会自动规划信源、Agent 和报告结构。' }}</small></span></div><button @click="latestCompleted ? router.push(`/equipment/runs/${latestCompleted.run_id}`) : router.push('/equipment/queries')">{{ latestCompleted ? '查看成果' : '打开问题库' }}</button></div></section>
    <section class="research-run-center">
      <div class="research-run-toolbar"><div class="run-status-tabs"><button :class="{ active: status === 'all' }" @click="status = 'all'"><InboxOutlined />全部 <em>{{ counts.current }}</em></button><button :class="{ active: status === 'active' }" @click="status = 'active'"><ClockCircleOutlined />进行中 <em>{{ counts.active }}</em></button><button :class="{ active: status === 'completed' }" @click="status = 'completed'"><CheckCircleOutlined />已完成 <em>{{ counts.completed }}</em></button></div><button class="run-refresh-button" :disabled="loading" @click="load"><ReloadOutlined />刷新</button></div>
      <div class="run-live-note"><ThunderboltOutlined /><b>实时</b><span>多智能体编排器每次运行都会沉淀报告、证据与可追溯的执行轨迹。</span></div>
      <div class="run-search-row"><div class="searchbox"><SearchOutlined /><input v-model="search" placeholder="搜索研究主题或运行 ID（按 / 聚焦）"><button v-if="search" class="searchbox-clear" type="button" title="清空搜索" aria-label="清空搜索" @click="search = ''"><X :size="13" /></button></div><label class="filter-select"><ListFilter :size="15" /><select v-model="status"><option value="all">全部当前任务</option><option value="active">全部进行中</option><option v-for="(label, value) in statusLabels" :key="value" :value="value">{{ label }}</option></select></label><button v-if="selectedDeletableRuns.length" type="button" class="danger" :disabled="actionRunId === '__bulk_delete__'" @click="deleteSelectedRuns"><Trash2 :size="15" />{{ actionRunId === '__bulk_delete__' ? '删除中' : `永久删除 (${selectedDeletableRuns.length})` }}</button><button v-if="selectedRunIds.length" type="button" :disabled="actionRunId === '__bulk_delete__'" @click="selectedRunIds = []"><X :size="14" />清除选择</button><span>{{ visibleRuns.length }} 项结果</span></div>
      <div v-if="loading && !runs.length" class="research-run-grid skeleton-grid"><article v-for="index in 6" :key="index" class="research-run-card skeleton-card" /></div><a-empty v-else-if="!visibleRuns.length" :description="search || status !== 'all' ? '当前已加载任务中没有符合条件的结果' : '暂无研究任务。在页面顶部输入 Query 即可启动第一次研究。'" />
      <div v-else class="research-run-scroll"><div class="research-run-grid"><article v-for="run in visibleRuns" :key="run.run_id" class="research-run-card" :class="run.status" :data-run-id="run.run_id">
        <div class="run-card-heading"><label class="run-card-select" title="选择任务"><input type="checkbox" :aria-label="`选择 ${run.topic}`" :checked="selectedRunIds.includes(run.run_id)" @change="toggleSelectedRun(run.run_id)"></label><button class="run-card-title" @click="router.push(`/equipment/runs/${run.run_id}`)"><b>{{ run.topic }}</b><small>{{ run.supplemental_information || run.run_id }}</small></button><span class="status" :class="run.status">{{ statusLabels[run.status] || run.status }}</span></div>
        <div class="run-card-counts" aria-label="研究产物数量"><span><b>{{ artifactCount(run, 'sources') }}</b> 信源</span><span><b>{{ artifactCount(run, 'evidence') }}</b> 证据</span><span><b>{{ artifactCount(run, 'capabilities') }}</b> 能力图像</span><span><b>{{ artifactCount(run, 'winning_steps') }}</b> S1–S6</span><span><b>{{ artifactCount(run, 'reports') }}</b> 报告</span><span :class="{ 'has-deep-sessions': deepSessionCount(run) }"><b>{{ deepSessionCount(run) }}</b> 深研</span></div>
        <button v-if="run.status === 'completed'" type="button" class="run-card-capability-preview" @click="openArtifact(run, 'capabilities')"><span class="run-card-capability-icon"><ExperimentOutlined /></span><span class="run-card-capability-copy"><b>能力图像 <em>{{ artifactCount(run, 'capabilities') }}</em></b><small>点击查看完整能力画像与论证</small></span><ChevronRight :size="14" /></button>
        <div class="run-card-artifacts" aria-label="研究产物快捷入口"><button type="button" class="run-card-deep-link" @click="openArtifact(run, 'deep-thinking')"><MessageSquare :size="13" />{{ deepSessionCount(run) ? '继续深研' : '发起深研' }}<span>{{ deepSessionCount(run) }}</span></button><button type="button" @click="openArtifact(run, 'interactions')"><Layers3 :size="13" />交互过程</button><button type="button" @click="openArtifact(run, 'evidence')"><Search :size="13" />证据中心<span>{{ artifactCount(run, 'evidence') }}</span></button><button type="button" @click="openArtifact(run, 'winning')"><BrainCircuit :size="13" />S1–S6 Agent<span>{{ artifactCount(run, 'winning_steps') }}</span></button><button v-if="run.status !== 'completed' && artifactCount(run, 'capabilities')" type="button" @click="openArtifact(run, 'capabilities')"><ExperimentOutlined />能力图像<span>{{ artifactCount(run, 'capabilities') }}</span></button><button v-if="artifactCount(run, 'reports')" type="button" @click="openArtifact(run, 'reports')"><FileCheck2 :size="13" />研究报告<span>{{ artifactCount(run, 'reports') }}</span></button></div>
        <div class="run-card-meta"><span>{{ formatUpdatedAt(run.updated_at) }}</span><span>{{ routeLabel(run.research_route) }}</span></div>
        <div v-if="run.status === 'failed'" class="run-card-recovery"><div><CircleAlert :size="15" /><span><b>任务执行中断</b><small>已保留检查点，可从上次进度继续</small></span></div><button type="button" class="primary" :disabled="actionRunId === run.run_id" @click="actOnRun('resume', run)"><RefreshCw :class="{ spin: actionRunId === run.run_id }" :size="14" />{{ actionRunId === run.run_id ? '恢复中' : '从断点继续' }}</button></div>
        <div class="run-card-footer"><span class="run-mode-label" :class="run.execution?.mode === 'fake' ? 'fake' : 'real'"><i />{{ run.execution?.mode === 'fake' ? '离线模拟' : '真实运行' }}</span><span>{{ run.payload?.model_spec || run.execution?.model || '系统默认模型' }}</span><div><button v-if="activeStatuses.has(run.status)" type="button" class="icon-button row-stop" :disabled="actionRunId === run.run_id" title="停止研究任务并终止所有 Agent 进程" @click="actOnRun('cancel', run)"><X :size="15" /></button><button type="button" class="icon-button" title="打开研究详情" @click="router.push(`/equipment/runs/${run.run_id}`)"><EyeOutlined /></button><button type="button" class="icon-button row-delete" :disabled="actionRunId === run.run_id" title="永久删除任务及后端数据" @click="actOnRun('delete', run)"><DeleteOutlined /></button></div></div>
      </article></div></div>
    </section>
  </div>
</template>

<style scoped>
.equipment-runs-page{color:#20283a;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","HarmonyOS Sans SC","Noto Sans SC","Microsoft YaHei",Inter,system-ui,Arial,sans-serif;font-size:16px}.page-title{display:flex;align-items:end;justify-content:space-between;gap:16px;margin:0 0 18px}.page-title h1,.page-title p{margin:0}.page-title p{margin-top:4px;color:#778297;font-size:11px}.research-model-picker{display:inline-flex;align-items:center;min-width:0;max-width:190px;height:36px;padding:0 2px 0 8px;border:1px solid #e1e5f2;border-radius:10px;background:#f8f9fd;color:#5b59ad}.research-model-picker:focus-within,.research-model-picker:hover{border-color:#aeb6e9;background:#f2f3ff;box-shadow:0 0 0 3px rgba(92,101,205,.08)}.research-model-picker.missing-default{border-color:#efc7cb;background:#fff8f8;color:#b64d59}.research-model-picker :deep(.model-select){max-width:158px;color:#485276}.research-model-picker :deep(.config-dropdown-trigger){max-width:150px;font-size:10px;font-weight:700}.research-query-inline-config-shell{padding:12px;border-top:1px solid #edf0f7;background:#fbfcff}.research-query-supplement{height:72px!important;padding:10px!important;border:1px solid #dfe3ed!important;border-radius:9px!important;resize:vertical!important}.vue-run-config-grid{display:grid;grid-template-columns:1fr 1fr;align-items:end;gap:10px;margin-top:10px}.vue-run-config-grid label{display:grid;gap:5px;color:#68758b;font-size:10px;font-weight:700}.vue-run-config-grid select{height:36px;border:1px solid #dce2ec;border-radius:8px;background:#fff}.run-card-title{width:100%}.run-card-heading .status{width:auto;flex:0 0 auto;padding:4px 8px;border-radius:12px;background:#eef1f5;color:#68758b;font-size:10px;font-weight:750}.run-card-heading .status.completed{background:#e9f8f0;color:#258259}.run-card-heading .status.failed{background:#fff0f1;color:#b64d59}.run-card-heading .status.queued,.run-card-heading .status.researching,.run-card-heading .status.planning{background:#efedff;color:#5653c8}
.research-runtime-panel{margin:0 0 18px;overflow:hidden;border:1px solid #dfe5f1;border-radius:13px;background:#fff;box-shadow:0 8px 28px rgba(38,54,95,.05)}.research-runtime-panel>header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 16px;border-bottom:1px solid #e8edf5;background:linear-gradient(135deg,#fbfcff,#f4f6ff)}.runtime-heading,.runtime-heading>span,.runtime-actions,.runtime-capacity-editor,.runtime-capacity-editor>span,.runtime-capacity-editor>div,.research-runtime-panel>footer,.research-runtime-panel>footer>span{display:flex;align-items:center}.runtime-heading{gap:10px;min-width:0}.runtime-heading>span:not(.runtime-icon),.runtime-capacity-editor>span{align-items:flex-start;flex-direction:column;gap:3px}.runtime-heading b,.runtime-capacity-editor b{color:#34405a;font-size:12px}.runtime-heading small,.runtime-capacity-editor small,.research-runtime-panel>footer small{color:#77849a;font-size:10px}.runtime-icon{justify-content:center;width:32px;height:32px;border-radius:9px;background:#ececff;color:#5552c9}.runtime-actions{gap:7px}.runtime-actions em{padding:5px 9px;border-radius:999px;background:#eaf8f0;color:#267d58;font-size:10px;font-style:normal;font-weight:750}.runtime-actions button,.runtime-capacity-editor button{height:30px;padding:0 9px;border:1px solid #d9e1ee;border-radius:7px;background:#fff;color:#58667f;font-size:10px;cursor:pointer}.runtime-actions button{display:inline-flex;align-items:center;gap:5px}.runtime-capacity-editor{justify-content:space-between;gap:18px;padding:12px 16px;border-bottom:1px solid #e9edf4;background:#fbfcff}.runtime-capacity-editor>div{gap:6px}.runtime-capacity-editor strong{min-width:32px;color:#3e3ba9;font-size:18px;text-align:center}.runtime-capacity-editor button.primary{border-color:#5552cf;background:#5552cf;color:#fff}.runtime-capacity-editor button:disabled,.runtime-actions button:disabled{cursor:not-allowed;opacity:.5}.runtime-error{display:flex;align-items:center;gap:6px;margin:0;padding:9px 16px;background:#fff3f3;color:#b54c58;font-size:10px}.runtime-slot-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:12px 16px}.runtime-slot-grid article{display:grid;gap:4px;min-width:0;padding:10px 11px;border:1px solid #e0e6f0;border-radius:9px;background:#fafbfe}.runtime-slot-grid article.busy{border-color:#aaa9e9;background:#f3f3ff}.runtime-slot-grid span{color:#747f93;font-size:9px;font-weight:750}.runtime-slot-grid b{overflow:hidden;color:#3f4d67;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.runtime-slot-grid article.busy b{color:#4e4bbd}.runtime-slot-grid small{color:#8994a6;font-size:9px}.research-runtime-panel>footer{justify-content:space-between;gap:14px;padding:9px 16px;border-top:1px solid #edf0f5;background:#fafbfc}.research-runtime-panel>footer>span{gap:7px;color:#5f6d83;font-size:10px}.research-runtime-panel>footer i{width:7px;height:7px;border-radius:50%;background:#39a675;box-shadow:0 0 0 3px rgba(57,166,117,.12)}.research-runtime-panel>footer i.queued{background:#d59535;box-shadow:0 0 0 3px rgba(213,149,53,.12)}
@media(max-width:900px){.runtime-slot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.research-model-picker{flex:1;max-width:none}.research-model-picker :deep(.model-select),.research-model-picker :deep(.config-dropdown-trigger){max-width:none}.vue-run-config-grid{grid-template-columns:1fr}.page-title{align-items:flex-start}.run-card-title{width:auto;min-width:0}.run-card-heading .status{width:auto}.run-search-row{align-items:stretch;flex-direction:column}.run-search-row .searchbox,.run-search-row .filter-select,.run-search-row .filter-select select{width:100%}.research-runtime-panel>header,.runtime-capacity-editor,.research-runtime-panel>footer{align-items:flex-start;flex-direction:column}.runtime-actions{width:100%;flex-wrap:wrap}.runtime-actions em{margin-right:auto}.runtime-slot-grid{grid-template-columns:1fr}.runtime-capacity-editor>div{width:100%;justify-content:flex-end}}
</style>
