<script setup>
import '@/assets/css/equipment-workbench-live.css'
import '@/assets/css/equipment-workbench-theme.css'
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Modal, message } from 'ant-design-vue'
import {
  Activity,
  Archive,
  ArrowLeft,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Clock3,
  Database,
  FileCheck2,
  FlaskConical,
  Layers3,
  MessageSquare,
  PauseCircle,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Wifi,
  WifiOff,
  XCircle
} from '@lucide/vue'
import { equipmentApi } from '@/apis/equipment_api'
import {
  BUSINESS_AGENTS,
  LOOP_ARCHITECTURE,
  S_AGENT_ARCHITECTURE,
  arrayValue,
  buildEvidenceProjection,
  buildInteractionProjection,
  buildWinningProjection,
  candidateSummary,
  candidateTitle,
  displayValue,
  mergeInteractionProjection,
  resolveWinningSwarm
} from './run_detail_projection'

const route = useRoute()
const router = useRouter()

const run = ref(null)
const platformEvents = ref([])
const legacyInteractions = ref(null)
const legacyEvidence = ref(null)
const legacyWinning = ref(null)
const loading = ref(true)
const refreshing = ref(false)
const action = ref('')
const loadError = ref('')
const projectionNote = ref('')
const connected = ref(true)
const agentFilter = ref('all')
const eventSearch = ref('')
const evidenceSearch = ref('')
const showAuditRecords = ref(false)
const pollEnabled = ref(true)
let timer = null
let loadToken = 0

const runId = computed(() => String(route.params.runId || '').trim())
const activeTab = computed(() => {
  const value = String(route.query.tab || 'overview')
  return ['overview', 'interactions', 'evidence', 'winning'].includes(value) ? value : 'overview'
})
const terminal = computed(() => ['completed', 'failed', 'cancelled', 'archived'].includes(run.value?.status))
const canStart = computed(() => run.value?.status === 'draft' && !run.value?.readonly)
const canPause = computed(() =>
  ['queued', 'planning', 'researching', 'recalling', 'synthesizing', 'reviewing', 'reporting'].includes(
    run.value?.status
  )
)
const canResume = computed(() =>
  ['paused', 'failed', 'pause_requested'].includes(run.value?.status) && !run.value?.readonly
)
const canCancel = computed(() => canPause.value || run.value?.status === 'paused')

const progress = computed(() => {
  if (run.value?.status === 'completed') return 100
  const stages = ['draft', 'queued', 'planning', 'researching', 'recalling', 'synthesizing', 'reviewing', 'reporting']
  const index = stages.indexOf(run.value?.status)
  return index < 0 ? 0 : Math.round((index / (stages.length - 1)) * 92)
})

const fallbackInteractions = computed(() => buildInteractionProjection(platformEvents.value, run.value || {}))
const interactions = computed(() =>
  mergeInteractionProjection(legacyInteractions.value, fallbackInteractions.value)
)
const events = computed(() => arrayValue(interactions.value?.events))
const workflow = computed(() => interactions.value?.workflow || {})
const evidenceRows = computed(() =>
  buildEvidenceProjection(legacyEvidence.value, events.value)
)
const winning = computed(() =>
  buildWinningProjection(legacyWinning.value, events.value, run.value || {}, interactions.value)
)
const swarm = computed(() => resolveWinningSwarm(winning.value, interactions.value))

const eventTypeSet = computed(() => new Set(events.value.map((event) => event.event_type)))
const hasEvent = (...types) => types.some((type) => eventTypeSet.value.has(type))

const statusLabel = (value) =>
  ({
    draft: '草稿',
    queued: '等待执行',
    planning: '规划中',
    researching: '研究中',
    recalling: '定向回溯',
    synthesizing: '综合研判',
    reviewing: '审计中',
    reporting: '报告生成',
    pause_requested: '暂停请求中',
    paused: '已暂停',
    cancel_requested: '取消请求中',
    completed: '已完成',
    failed: '运行失败',
    cancelled: '已取消',
    archived: '已归档',
    pending: '待执行',
    running: '执行中',
    skipped: '已跳过',
    merged: '已合并',
    pruned: '已剪枝',
    recruiting: '招募中'
  })[value] || value || '读取中'

const routeLabel = (value) =>
  ({ auto: '自动路线', traditional_gap: '传统差距路线', new_winning_mechanism: '新制胜机理路线' })[
    value
  ] || value || '自动路线'

const eventLabel = (value) => {
  const labels = {
    run_created: '研究任务已创建',
    run_queued: '研究任务已排队',
    run_started: '研究任务启动',
    status_changed: '运行状态变化',
    discovery_meta_loop_evaluated: 'L4 元循环完成',
    baseline_pipeline_started: '前置专业研究启动',
    baseline_wave_started: '专业 Agent 波次启动',
    baseline_agent_completed: '专业 Agent 完成',
    baseline_agents_summarized: '前置研究已汇总',
    discovery_convergence_completed: '跨分支收敛完成',
    winning_input_prepared: 'S1–S6 输入包已形成',
    winning_resources_projected: '共享受控资源已投影',
    winning_mission_graph_planned: '动态任务图已规划',
    winning_agent_instance_recruited: '动态 Agent 已招募',
    winning_agent_session_started: '动态 Agent 会话启动',
    winning_agent_session_completed: '动态 Agent 会话完成',
    winning_contribution_merged: 'Agent 贡献已合并',
    winning_reasoning_step_completed: 'S Agent 推理节点完成',
    winning_stage_completed: '循环门控完成',
    recall_requested: '发起定向回溯',
    recall_task_completed: '定向回溯完成',
    capability_image_created: '能力画像已形成',
    audit_completed: '业务审计完成',
    report_completed: '研究报告已生成',
    run_result_saved: '运行结果已保存',
    run_failed: '研究任务失败'
  }
  return labels[value] || String(value || '运行事件').replaceAll('_', ' · ')
}

const formatTime = (value) => {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(date)
}

const eventTone = (event) => {
  if (/failed|error|blocked|cancelled|rejected/.test(event.event_type)) return 'failed'
  if (/completed|saved|merged|created/.test(event.event_type)) return 'completed'
  if (/started|running|progress|queued|waiting|recruited/.test(event.event_type)) return 'running'
  return 'neutral'
}

const dynamicMembers = computed(() =>
  arrayValue(swarm.value?.members).length
    ? arrayValue(swarm.value.members)
    : arrayValue(workflow.value?.dynamic_agents)
)

const dynamicStatusCount = (statuses) =>
  dynamicMembers.value.filter((member) => statuses.includes(member.status)).length

const waveMembers = (wave) => dynamicMembers.value.filter((member) => Number(member.wave || 1) === wave)

const waveLabel = (wave) => ({ 1: '问题发散', 2: '开放创作', 3: '组合决策' })[wave]

const swarmRolePools = computed(() => {
  const rows = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'].map((node) => ({
    node,
    label: S_AGENT_ARCHITECTURE[Number(node.slice(1)) - 1]?.name.replace(' Agent', '') || node,
    count: dynamicMembers.value.filter(
      (member) => (member.mission_node || member.merge_target) === node
    ).length
  }))
  const specialistCount = dynamicMembers.value.filter(
    (member) => !/^S[1-6]$/.test(member.mission_node || member.merge_target || '')
  ).length
  return [...rows, { node: 'SP', label: '专项补强', count: specialistCount }]
})

const candidateRows = computed(() => arrayValue(swarm.value?.candidate_lineage))
const portfolioRows = computed(() => {
  const direct = arrayValue(swarm.value?.final_equipment_portfolio)
  if (direct.length) return direct
  return candidateRows.value.filter(
    (candidate) =>
      candidate.s6_eligible === true ||
      candidate.selection_status === 'selected' ||
      candidate.portfolio_status === 'selected'
  )
})

const businessAgents = computed(() => {
  const dynamicIds = new Set(
    dynamicMembers.value.map((member) =>
      String(member.agent_instance_id || member.instance_id || member.agent_id || '')
    )
  )
  return arrayValue(interactions.value?.agents).filter(
    (agent) =>
      !dynamicIds.has(String(agent.agent_id || '')) &&
      !['orchestrator', 'winning_mechanism', 'winning_swarm_controller', 'auditor', 'reporter'].includes(
        agent.agent_id
      )
  )
})

const filterAgents = computed(() => {
  const standard = arrayValue(interactions.value?.agents)
  const dynamic = dynamicMembers.value.map((member, index) => ({
    agent_id:
      member.agent_instance_id || member.instance_id || member.agent_id || `dynamic-agent-${index}`,
    display_name: member.display_name || '动态专用 Agent'
  }))
  const map = new Map([...standard, ...dynamic].map((agent) => [agent.agent_id, agent]))
  return [...map.values()].filter((agent) => agent.agent_id)
})

const eventAgentName = (event) => {
  const id = event.actor || event.details?.target_agent_id || ''
  return (
    filterAgents.value.find((agent) => agent.agent_id === id)?.display_name ||
    BUSINESS_AGENTS[id]?.display_name ||
    id ||
    '系统'
  )
}

const visibleEvents = computed(() => {
  const query = eventSearch.value.trim().toLocaleLowerCase()
  return events.value
    .filter((event) => {
      const matchesAgent =
        agentFilter.value === 'all' ||
        event.actor === agentFilter.value ||
        event.details?.target_agent_id === agentFilter.value
      if (!matchesAgent) return false
      if (!query) return true
      return `${event.event_type} ${event.summary} ${eventAgentName(event)}`
        .toLocaleLowerCase()
        .includes(query)
    })
    .slice(-80)
})

const filteredEvidence = computed(() => {
  const query = evidenceSearch.value.trim().toLocaleLowerCase()
  if (!query) return evidenceRows.value
  return evidenceRows.value.filter((row) =>
    [row.evidence_id, row.claim, row.excerpt, row.source_title, row.source_url, row.created_by]
      .join(' ')
      .toLocaleLowerCase()
      .includes(query)
  )
})

const evidenceQuality = (row) => {
  const source = String(row.quality_assessment || row.source_tier || '').toUpperCase()
  if (/\bA\b|HIGH|权威/.test(source)) return { label: row.source_tier || '高质量', tone: 'high' }
  if (/\bB\b|MEDIUM|中/.test(source)) return { label: row.source_tier || '已评估', tone: 'medium' }
  return { label: row.source_tier || '待核验', tone: 'pending' }
}

const stepPlan = computed(() => arrayValue(workflow.value?.step_plan))
const reasoningNodes = computed(() => arrayValue(winning.value?.reasoning_nodes))
const sAgentCards = computed(() =>
  S_AGENT_ARCHITECTURE.map((meta) => {
    const plan = stepPlan.value.find((item) => Number(item.step) === meta.step) || {}
    const node = [...reasoningNodes.value]
      .reverse()
      .find((item) => Number(item.step) === meta.step)
    const members = dynamicMembers.value.filter(
      (member) => Number(String(member.mission_node || member.merge_target || '').replace('S', '')) === meta.step
    )
    const memberStatuses = members.map((member) => member.status)
    const status =
      plan.status ||
      (node
        ? 'completed'
        : memberStatuses.some((value) => ['running', 'recruiting', 'queued'].includes(value))
          ? 'running'
          : memberStatuses.length && memberStatuses.every((value) => ['completed', 'merged'].includes(value))
            ? 'completed'
            : memberStatuses.some((value) => value === 'failed')
              ? 'failed'
              : 'pending')
    return {
      ...meta,
      ...plan,
      node,
      members,
      status,
      execution_mode: members.length ? 'dynamic' : plan.execution_mode || plan.mode || 'standard',
      result_summary: plan.result_summary || node?.summary || '',
      backtrack_count:
        Number(plan.backtrack_count) ||
        arrayValue(winning.value?.recalls).filter(
          (item) =>
            Number(item.target_step || String(item.return_node || '').replace('S', '')) === meta.step
        ).length
    }
  })
)

const completedSAgents = computed(() =>
  sAgentCards.value.filter((card) => ['completed', 'skipped'].includes(card.status)).length
)

const loopCards = computed(() =>
  LOOP_ARCHITECTURE.map((meta) => {
    const projected = workflow.value?.loops?.[meta.key] || {}
    const stage = [...arrayValue(winning.value?.stages)]
      .reverse()
      .find((item) => String(item.layer || '').toUpperCase() === meta.level)
    return {
      ...meta,
      count: Number(projected.count || 0) + (stage ? 1 : 0),
      latest: projected.latest || stage?.summary || '',
      passed: stage?.gate_passed
    }
  })
)

const phaseStatus = (done, running) => (done ? 'completed' : running ? 'running' : 'pending')
const workflowPhases = computed(() => {
  const legacy = arrayValue(workflow.value?.phases)
  const status = run.value?.status
  const fallback = [
    {
      id: 'blueprint',
      label: 'A–H 蓝图',
      status: phaseStatus(
        hasEvent('discovery_meta_loop_evaluated'),
        hasEvent('run_started') || ['planning', 'researching'].includes(status)
      ),
      detail: workflow.value?.discovery?.primary_branch
        ? `主分支 ${workflow.value.discovery.primary_branch}`
        : '需求解析与路径选择'
    },
    {
      id: 'baseline',
      label: '前置专业研究',
      status: phaseStatus(
        hasEvent('baseline_agents_summarized', 'discovery_convergence_completed'),
        hasEvent('baseline_pipeline_started', 'baseline_wave_started', 'baseline_discovery_started')
      ),
      detail: `${businessAgents.value.length} 个业务 Agent 参与`
    },
    {
      id: 'convergence',
      label: '收敛融合',
      status: phaseStatus(
        hasEvent('discovery_convergence_completed', 'winning_input_prepared'),
        hasEvent('discovery_convergence_started', 'packet_admission_evaluated')
      ),
      detail: '跨背景、场景与分支聚合'
    },
    {
      id: 's_agents',
      label: 'S1–S6 Agent',
      status: phaseStatus(
        completedSAgents.value === 6 || hasEvent('capability_image_created'),
        completedSAgents.value > 0 || dynamicMembers.value.some((member) => member.status === 'running')
      ),
      detail: `${completedSAgents.value} / 6 个专用 Agent 已完成`
    },
    {
      id: 'audit',
      label: '业务审计',
      status: phaseStatus(
        hasEvent('audit_completed', 'report_completed', 'run_result_saved'),
        events.value.some((event) => event.actor === 'auditor')
      ),
      detail: hasEvent('audit_completed') ? '业务审计完成' : '独立审计与质量复核'
    },
    {
      id: 'report',
      label: '报告交付',
      status: phaseStatus(
        status === 'completed' || hasEvent('report_completed', 'run_result_saved'),
        status === 'reporting' || hasEvent('report_model_call_started')
      ),
      detail: status === 'completed' ? '研究报告已生成' : '等待审计通过'
    }
  ]
  return fallback.map((item) => {
    const projected = legacy.find((phase) => phase.id === item.id)
    return projected ? { ...item, ...projected } : item
  })
})

const artifactCounts = computed(() => ({
  events: Number(interactions.value?.counts?.events || events.value.length),
  evidence: Math.max(
    evidenceRows.value.length,
    Number(run.value?.artifact_counts?.evidence || run.value?.result?.evidence_count || 0)
  ),
  capabilities: Number(
    run.value?.artifact_counts?.capabilities ||
      run.value?.result?.capability_count ||
      portfolioRows.value.length ||
      0
  ),
  reports: Number(
    run.value?.artifact_counts?.reports || (run.value?.result?.report_available ? 1 : 0)
  )
}))

const latestEvents = computed(() => [...events.value].slice(-6).reverse())
const winningInput = computed(() => arrayValue(winning.value?.inputs).at(-1) || null)
const winningResources = computed(() => arrayValue(winning.value?.resources).at(-1) || {})
const winningStages = computed(() => arrayValue(winning.value?.stages))
const winningRecalls = computed(() => arrayValue(winning.value?.recalls))

const resourceBlocks = computed(() => [
  { title: '理论工具库', rows: arrayValue(winningResources.value?.theory_tools), field: 'name' },
  { title: '战例库', rows: arrayValue(winningResources.value?.case_resources), field: 'evidence_id' },
  { title: '前沿情报库', rows: arrayValue(winningResources.value?.frontier_resources), field: 'evidence_id' },
  { title: '问题链', rows: arrayValue(winningResources.value?.question_chain), field: 'question' }
])

const fetchAllEvents = async (id) => {
  const rows = []
  let cursor = 0
  for (let page = 0; page < 50; page += 1) {
    const payload = await equipmentApi.listEvents(id, cursor)
    const chunk = Array.isArray(payload) ? payload : arrayValue(payload?.items)
    if (!chunk.length) break
    rows.push(...chunk)
    const next = Math.max(...chunk.map((item) => Number(item.sequence || 0)))
    if (!Number.isFinite(next) || next <= cursor || chunk.length < 200) break
    cursor = next
  }
  const uniqueRows = new Map()
  rows.forEach((item, index) => {
    const key = item.id || `${item.sequence || index}:${item.event_type || ''}`
    uniqueRows.set(key, item)
  })
  return [...uniqueRows.values()]
}

const fetchLegacyArtifacts = async (id, token) => {
  const settled = await Promise.allSettled([
    equipmentApi.getRunInteractions(id, true),
    equipmentApi.listRunEvidence(id),
    equipmentApi.getRunWinningMechanism(id)
  ])
  if (token !== loadToken) return
  legacyInteractions.value = settled[0].status === 'fulfilled' ? settled[0].value : null
  legacyEvidence.value = settled[1].status === 'fulfilled' ? settled[1].value : null
  legacyWinning.value = settled[2].status === 'fulfilled' ? settled[2].value : null
  const unavailable = settled.filter((item) => item.status === 'rejected').length
  projectionNote.value = unavailable
    ? '部分研究产物暂不可读，当前视图已从平台权威运行事件恢复。'
    : ''
}

const refresh = async ({ silent = false, includeArtifacts = true } = {}) => {
  if (!runId.value) return
  const token = ++loadToken
  if (!silent) {
    if (run.value) refreshing.value = true
    else loading.value = true
    loadError.value = ''
  }
  try {
    const artifactPromise = includeArtifacts ? fetchLegacyArtifacts(runId.value, token) : null
    const [nextRun, nextEvents] = await Promise.all([
      equipmentApi.getRun(runId.value),
      fetchAllEvents(runId.value)
    ])
    if (token !== loadToken) return
    run.value = nextRun
    platformEvents.value = nextEvents
    connected.value = true
    if (artifactPromise) await artifactPromise
  } catch (error) {
    if (token !== loadToken) return
    connected.value = false
    if (!silent) {
      loadError.value = error?.message || '任务详情加载失败'
      message.error(loadError.value)
    }
  } finally {
    if (token === loadToken) {
      loading.value = false
      refreshing.value = false
    }
  }
}

const startPolling = () => {
  if (timer) return
  pollEnabled.value = true
  timer = window.setInterval(async () => {
    if (!pollEnabled.value || document.visibilityState === 'hidden' || terminal.value) return
    const previousStatus = run.value?.status
    await refresh({ silent: true, includeArtifacts: false })
    if (terminal.value || previousStatus !== run.value?.status) {
      await fetchLegacyArtifacts(runId.value, loadToken)
    }
  }, 3500)
}

const stopPolling = () => {
  pollEnabled.value = false
  if (timer) window.clearInterval(timer)
  timer = null
}

const confirm = (title) =>
  new Promise((resolve) => {
    Modal.confirm({
      title,
      okText: '确认',
      cancelText: '取消',
      onOk: () => resolve(true),
      onCancel: () => resolve(false)
    })
  })

const act = async (name, handler, successText, confirmText = '') => {
  if (confirmText && !(await confirm(confirmText))) return
  action.value = name
  try {
    await handler(runId.value)
    message.success(successText)
    await refresh()
  } catch (error) {
    message.error(error?.message || '操作失败')
  } finally {
    action.value = ''
  }
}

const selectTab = (tab) =>
  router.replace({ query: { ...route.query, tab: tab === 'overview' ? undefined : tab } })

const openArtifact = (path) => router.push({ path, query: { run: runId.value } })

const rawEventText = (event) =>
  JSON.stringify(event.raw?.payload || event.details || {}, null, 2)

onMounted(async () => {
  await refresh()
  startPolling()
})
onActivated(startPolling)
onDeactivated(stopPolling)
onUnmounted(() => {
  stopPolling()
  loadToken += 1
})
watch(runId, async (next, previous) => {
  if (!next || next === previous) return
  run.value = null
  platformEvents.value = []
  legacyInteractions.value = null
  legacyEvidence.value = null
  legacyWinning.value = null
  await refresh()
  startPolling()
})
</script>

<template>
  <div class="run-detail-page">
    <div class="run-detail-backbar">
      <button class="back-button" type="button" @click="router.push('/equipment/runs')">
        <ArrowLeft :size="15" />
        返回研究任务
      </button>
      <span>{{ runId }}</span>
      <button
        class="icon-button"
        type="button"
        :disabled="refreshing"
        aria-label="刷新任务"
        @click="refresh()"
      >
        <RefreshCw :size="15" :class="{ spinning: refreshing }" />
      </button>
    </div>

    <div v-if="loading && !run" class="run-detail-skeleton" aria-label="正在加载研究任务">
      <i v-for="index in 8" :key="index" />
    </div>

    <section v-else-if="loadError && !run" class="run-load-error">
      <CircleAlert :size="28" />
      <div>
        <b>研究任务暂时无法载入</b>
        <p>{{ loadError }}</p>
      </div>
      <button type="button" @click="refresh()"><RefreshCw :size="14" />重新连接</button>
    </section>

    <template v-else>
      <section class="run-detail-hero">
        <div class="run-detail-heading">
          <div>
            <span>DEEP RESEARCH RUN</span>
            <h1>{{ run?.topic || '研究任务' }}</h1>
            <p>{{ run?.supplemental_information || '运行过程、证据、能力画像与研究报告持续留痕。' }}</p>
          </div>
          <span class="run-detail-status" :class="run?.status">{{ statusLabel(run?.status) }}</span>
        </div>

        <div class="run-progress" :aria-label="`任务进度 ${progress}%`">
          <div><i :style="{ width: `${progress}%` }" /></div>
          <span>{{ progress }}%</span>
        </div>

        <div class="run-detail-meta">
          <span>{{ routeLabel(run?.research_route) }}</span>
          <span>{{ run?.execution?.model_spec || run?.payload?.model_spec || '系统默认模型' }}</span>
          <span>{{ run?.interaction_mode === 'expert' ? '专家交互' : run?.interaction_mode || '标准交互' }}</span>
          <span v-if="run?.historical_snapshot">历史数据 · {{ run?.readonly ? '只读' : '可编辑' }}</span>
          <span v-if="run?.derived_from_legacy_run_id">旧版数据已迁移</span>
          <button type="button" @click="router.push('/models')">模型设置</button>
        </div>

        <div v-if="run?.error" class="run-error-banner">
          <CircleAlert :size="16" />
          <span>{{ run.error }}</span>
        </div>

        <div class="run-detail-actions">
          <button
            v-if="canStart"
            class="primary"
            type="button"
            :disabled="action === 'start'"
            @click="act('start', equipmentApi.startRun, '任务已进入队列')"
          >
            <Play :size="14" />启动研究
          </button>
          <button
            v-if="canPause"
            type="button"
            :disabled="action === 'pause'"
            @click="act('pause', equipmentApi.pauseRun, '已请求暂停')"
          >
            <PauseCircle :size="14" />暂停
          </button>
          <button
            v-if="canResume"
            type="button"
            :disabled="action === 'resume'"
            @click="act('resume', equipmentApi.resumeRun, '任务已从断点恢复')"
          >
            <RefreshCw :size="14" />从断点继续
          </button>
          <button
            v-if="canCancel"
            class="danger"
            type="button"
            :disabled="action === 'cancel'"
            @click="act('cancel', equipmentApi.cancelRun, '任务已取消', '确定取消当前研究任务吗？')"
          >
            <XCircle :size="14" />取消任务
          </button>
          <button
            v-if="terminal && run?.status !== 'archived'"
            type="button"
            :disabled="action === 'archive'"
            @click="act('archive', equipmentApi.archiveRun, '任务已归档')"
          >
            <Archive :size="14" />归档
          </button>
        </div>
      </section>

      <section class="run-artifact-strip" aria-label="研究产物导航">
        <button type="button" :class="{ active: activeTab === 'interactions' }" @click="selectTab('interactions')">
          <MessageSquare :size="19" />
          <span><b>交互过程</b><small>{{ artifactCounts.events }} 条事件</small></span>
          <ChevronRight :size="14" />
        </button>
        <button type="button" :class="{ active: activeTab === 'evidence' }" @click="selectTab('evidence')">
          <Database :size="19" />
          <span><b>证据中心</b><small>{{ artifactCounts.evidence }} 条证据</small></span>
          <ChevronRight :size="14" />
        </button>
        <button type="button" @click="openArtifact('/equipment/capabilities')">
          <FlaskConical :size="19" />
          <span><b>能力画像</b><small>{{ artifactCounts.capabilities }} 个候选</small></span>
          <ChevronRight :size="14" />
        </button>
        <button type="button" @click="openArtifact('/equipment/reports')">
          <FileCheck2 :size="19" />
          <span><b>研究报告</b><small>{{ artifactCounts.reports }} 份报告</small></span>
          <ChevronRight :size="14" />
        </button>
        <button type="button" @click="openArtifact('/equipment/deep-thinking')">
          <Search :size="19" />
          <span><b>深研对话</b><small>继续探索</small></span>
          <ChevronRight :size="14" />
        </button>
      </section>

      <section class="run-event-workspace">
        <header class="workspace-toolbar">
          <div class="run-detail-tabs" role="tablist" aria-label="研究任务视图">
            <button :class="{ active: activeTab === 'overview' }" type="button" @click="selectTab('overview')">运行概览</button>
            <button :class="{ active: activeTab === 'interactions' }" type="button" @click="selectTab('interactions')">交互过程</button>
            <button :class="{ active: activeTab === 'evidence' }" type="button" @click="selectTab('evidence')">证据中心</button>
            <button :class="{ active: activeTab === 'winning' }" type="button" @click="selectTab('winning')">S1–S6 Agent</button>
          </div>
          <div class="live-state" :class="{ connected: connected && !terminal, offline: !connected }">
            <Wifi v-if="connected && !terminal" :size="13" />
            <WifiOff v-else-if="!connected" :size="13" />
            <Clock3 v-else :size="13" />
            {{ !connected ? '连接恢复中' : terminal ? '关键流程审计回放' : '实时接收关键流程' }}
          </div>
        </header>

        <div v-if="projectionNote" class="projection-note">
          <Database :size="14" />
          <span>{{ projectionNote }}</span>
        </div>

        <section v-if="run?.status === 'failed' || workflow?.status === 'failed'" class="workflow-failure">
          <CircleAlert :size="18" />
          <div>
            <b>{{ workflow?.failure?.phase ? `${workflow.failure.phase} 已停止` : '任务已停止' }}</b>
            <span>{{ workflow?.failure?.detail || run?.error || '已保留检查点与可恢复的执行上下文。' }}</span>
          </div>
        </section>

        <template v-if="activeTab === 'overview'">
          <section class="metric-strip interaction-metrics">
            <article class="metric"><div><span>全部事件</span><b>{{ artifactCounts.events }}</b></div><Activity :size="20" /></article>
            <article class="metric"><div><span>关键事件</span><b>{{ events.length }}</b></div><Layers3 :size="20" /></article>
            <article class="metric"><div><span>业务 Agent</span><b>{{ businessAgents.length }}</b></div><Bot :size="20" /></article>
            <article class="metric"><div><span>保存点</span><b>{{ interactions?.counts?.savepoints || 0 }}</b></div><ClipboardCheck :size="20" /></article>
          </section>

          <section class="workflow-overview">
            <header>
              <div><Layers3 :size="18" /><span><b>架构执行总览</b><small>A–H 发现蓝图、六个专用 Agent 与四层循环</small></span></div>
              <div class="workflow-badges">
                <span v-if="workflow?.execution?.provider">Agent</span>
                <span v-if="workflow?.discovery?.primary_branch">主分支 {{ workflow.discovery.primary_branch }}</span>
                <em :class="{ live: !terminal && connected }">{{ terminal ? '审计回放' : '运行中' }}</em>
              </div>
            </header>
            <div class="workflow-phases workflow-phases-six">
              <article v-for="(phase, index) in workflowPhases" :key="phase.id" :class="phase.status">
                <i><CheckCircle2 v-if="phase.status === 'completed'" :size="15" /><template v-else>{{ index + 1 }}</template></i>
                <div><b>{{ phase.label }}</b><small>{{ phase.detail }}</small></div>
              </article>
            </div>

            <div class="s-agent-overview">
              <div class="s-agent-overview-title">
                <div><Bot :size="17" /><span><b>S1–S6 专用 Agent</b><small>动态蜂群根据依赖与质量残差实时调度，支持并行与定向回溯。</small></span></div>
                <em>{{ completedSAgents }} / 6 已完成</em>
              </div>
              <div class="s-agent-grid">
                <article
                  v-for="card in sAgentCards"
                  :key="card.step"
                  class="s-agent-card"
                  :class="[`mode-${card.execution_mode}`, `status-${card.status}`]"
                >
                  <header>
                    <i>S{{ card.step }}</i>
                    <div><b>{{ card.name }}</b><small>独立受控会话</small></div>
                    <span class="s-agent-status" :class="card.status">{{ statusLabel(card.status) }}</span>
                  </header>
                  <p>{{ card.task }}</p>
                  <div v-if="card.result_summary" class="s-agent-result-preview">
                    <small>当前结果</small><span>{{ card.result_summary }}</span>
                  </div>
                  <div class="s-agent-runtime">
                    <span class="step-mode" :class="card.execution_mode">{{ card.execution_mode === 'dynamic' ? '动态' : '标准' }}</span>
                    <span>回溯 {{ card.backtrack_count || 0 }}</span>
                    <span v-if="card.members.length">实例 {{ card.members.length }}</span>
                  </div>
                  <div v-if="card.members.length" class="s-agent-dynamic">
                    <span v-for="member in card.members.slice(0, 3)" :key="member.agent_instance_id || member.instance_id">
                      <Bot :size="12" /><b>{{ member.display_name || '动态 Agent' }}</b><small>{{ statusLabel(member.status) }}</small>
                    </span>
                  </div>
                  <details class="s-agent-tech">
                    <summary>技能与运行配置</summary>
                    <div><code>{{ card.skills?.join(' · ') || '按任务动态装配' }}</code><code>{{ card.harness }}</code></div>
                  </details>
                  <div class="s-agent-semantics"><span v-for="item in card.semantics" :key="item">{{ item }}</span></div>
                </article>
              </div>
            </div>

            <div class="loop-overview">
              <article v-for="loop in loopCards" :key="loop.level" :class="{ used: loop.count > 0 }">
                <header><i>{{ loop.level }}</i><div><b>{{ loop.name }}</b><span>{{ loop.count }} 次</span></div></header>
                <p>{{ loop.description }}</p>
                <small v-if="loop.latest" class="loop-latest">{{ loop.latest }}</small>
              </article>
            </div>
          </section>

          <section class="overview-latest">
            <div class="section-heading"><div><b>最近运行动态</b><span>按 PostgreSQL 权威事件顺序展示。</span></div><button type="button" @click="selectTab('interactions')">查看全部</button></div>
            <div v-if="latestEvents.length" class="latest-event-grid">
              <article v-for="event in latestEvents" :key="event.event_id">
                <i :class="eventTone(event)" /><div><b>{{ eventLabel(event.event_type) }}</b><p>{{ event.summary }}</p><small>{{ eventAgentName(event) }} · {{ formatTime(event.created_at) }}</small></div>
              </article>
            </div>
            <div v-else class="compact-empty"><Clock3 :size="22" /><span>任务事件将在运行后持续写入。</span></div>
          </section>
        </template>

        <template v-else-if="activeTab === 'interactions'">
          <section class="metric-strip interaction-metrics">
            <article class="metric"><div><span>全部事件</span><b>{{ artifactCounts.events }}</b></div><Activity :size="20" /></article>
            <article class="metric"><div><span>关键事件</span><b>{{ events.length }}</b></div><Layers3 :size="20" /></article>
            <article class="metric"><div><span>动态实例</span><b>{{ dynamicMembers.length }}</b></div><BrainCircuit :size="20" /></article>
            <article class="metric"><div><span>保存点</span><b>{{ interactions?.counts?.savepoints || 0 }}</b></div><ClipboardCheck :size="20" /></article>
          </section>

          <section class="workflow-overview compact-workflow">
            <header>
              <div><Layers3 :size="18" /><span><b>架构执行总览</b><small>从研究蓝图到报告交付的关键阶段</small></span></div>
              <em>{{ completedSAgents }} / 6 S Agent 已完成</em>
            </header>
            <div class="workflow-phases workflow-phases-six">
              <article v-for="(phase, index) in workflowPhases" :key="phase.id" :class="phase.status">
                <i><CheckCircle2 v-if="phase.status === 'completed'" :size="15" /><template v-else>{{ index + 1 }}</template></i>
                <div><b>{{ phase.label }}</b><small>{{ phase.detail }}</small></div>
              </article>
            </div>
          </section>

          <section v-if="swarm?.enabled || dynamicMembers.length" class="dynamic-swarm-panel">
            <header>
              <div><BrainCircuit :size="18" /><span><b>动态制胜 Agent 集群</b><small>按任务图隔离执行；通过门控的贡献才会进入共享候选账本。</small></span></div>
              <em :class="{ live: !terminal }">{{ terminal ? '运行回放' : '实时调度' }}</em>
            </header>

            <div class="dynamic-swarm-counts">
              <span><small>动态实例</small><b>{{ dynamicMembers.length }}</b></span>
              <span><small>运行中</small><b>{{ dynamicStatusCount(['running', 'recruiting']) }}</b></span>
              <span><small>已完成</small><b>{{ dynamicStatusCount(['completed', 'merged']) }}</b></span>
              <span><small>已合并</small><b>{{ dynamicStatusCount(['merged']) }}</b></span>
              <span><small>剪枝 / 失败</small><b>{{ dynamicStatusCount(['pruned', 'failed', 'cancelled']) }}</b></span>
            </div>

            <div class="swarm-role-pools">
              <div v-for="pool in swarmRolePools" :key="pool.node" :class="{ specialists: pool.node === 'SP' }">
                <b>{{ pool.node }} <i>{{ pool.count }}</i></b><span>{{ pool.label }}</span>
              </div>
            </div>

            <div class="dynamic-swarm-waves">
              <article v-for="wave in [1, 2, 3]" :key="wave" class="dynamic-swarm-wave" :class="`wave-${wave}`">
                <header><i>W{{ wave }}</i><span><b>{{ waveLabel(wave) }}</b><small>{{ waveMembers(wave).length }} 个专用 Agent</small></span></header>
                <div>
                  <article
                    v-for="member in waveMembers(wave)"
                    :key="member.agent_instance_id || member.instance_id"
                    class="dynamic-swarm-member"
                    :class="`status-${member.status || 'planned'}`"
                  >
                    <header>
                      <i>{{ member.mission_node || member.merge_target || 'SP' }}</i>
                      <div><b>{{ member.display_name || '动态专用 Agent' }}</b><small>{{ member.archetype || '受控专业角色' }}</small></div>
                      <span class="swarm-member-status" :class="member.status">{{ statusLabel(member.status || 'pending') }}</span>
                    </header>
                    <details class="dynamic-swarm-purpose">
                      <summary><span>{{ member.role_purpose || member.purpose || '按当前任务残差执行局部补强。' }}</span><em>展开</em></summary>
                      <p>{{ member.role_purpose || member.purpose || '按当前任务残差执行局部补强。' }}</p>
                    </details>
                    <div class="dynamic-swarm-routing">
                      <span>合并到 <b>{{ member.merge_target || member.mission_node || '共享账本' }}</b></span>
                      <span v-if="member.model">模型 <code>{{ member.model }}</code></span>
                    </div>
                    <div v-if="member.trigger_residuals?.length" class="dynamic-swarm-residuals"><span v-for="item in member.trigger_residuals.slice(0, 4)" :key="item">{{ item }}</span></div>
                  </article>
                  <div v-if="!waveMembers(wave).length" class="dynamic-swarm-empty"><Clock3 :size="14" />该波次尚未招募 Agent</div>
                </div>
              </article>
            </div>

            <section v-if="candidateRows.length" class="swarm-candidate-board">
              <header><div><b>候选装备与假设谱系</b><small>展示有明确装备身份或入选状态的候选。</small></div><em>{{ candidateRows.length }} 项</em></header>
              <div>
                <article
                  v-for="candidate in candidateRows.slice(0, 12)"
                  :key="candidate.hypothesis_id || candidateTitle(candidate)"
                  :class="{ 'candidate-selected': candidate.selection_status === 'selected' || candidate.s6_eligible === true }"
                >
                  <header><b>{{ candidateTitle(candidate) }}</b><span>{{ candidate.mission_node || candidate.source_node || '候选' }}</span></header>
                  <div v-if="candidate.score || candidate.innovation_priority" class="candidate-score"><i :style="{ width: `${Math.round(Number(candidate.score || candidate.innovation_priority) * 100)}%` }" /><em>{{ Math.round(Number(candidate.score || candidate.innovation_priority) * 100) }}%</em></div>
                  <p>{{ candidateSummary(candidate) }}</p>
                  <footer><span v-if="candidate.disruption_tier">{{ candidate.disruption_tier }}</span><span>{{ candidate.selection_status || candidate.status || '待评审' }}</span></footer>
                </article>
              </div>
            </section>

            <section v-if="portfolioRows.length" class="swarm-equipment-portfolio">
              <header><div><b>最终装备组合</b><small>经 S5 组合评审并进入 S6 能力画像成稿。</small></div><em>{{ portfolioRows.length }} 项</em></header>
              <div>
                <article v-for="(item, index) in portfolioRows" :key="item.hypothesis_id || candidateTitle(item)" :class="{ 'innovation-priority': Number(item.innovation_priority || item.score) >= 0.7 }">
                  <i>{{ index + 1 }}</i><div><b>{{ candidateTitle(item) }}</b><p>{{ candidateSummary(item) }}</p><footer><span v-if="item.disruption_tier">{{ item.disruption_tier }}</span><span v-if="item.innovation_priority" class="innovation-score">创新 {{ Math.round(item.innovation_priority * 100) }}%</span></footer></div>
                </article>
              </div>
            </section>
          </section>

          <section class="agent-map compact-agent-map">
            <div class="section-heading"><div><b>本次参与的业务 Agent</b><span>由主控 Agent 结合 A–H 分支路径与当前输入动态选择。</span></div></div>
            <div v-if="businessAgents.length" class="agent-chip-grid">
              <article v-for="agent in businessAgents" :key="agent.agent_id" class="agent-chip"><Bot :size="16" /><div><b>{{ agent.display_name || agent.agent_id }}</b><small>{{ agent.harness_profile || '受控运行' }}</small><span>{{ agent.skill_ids?.slice(0, 2).join(' · ') || '专业分析' }}</span></div></article>
            </div>
            <small v-else class="agent-overflow">主控 Agent 正在判断本次需要的业务 Agent。</small>
          </section>

          <section class="event-filter compact-filter">
            <span>关键事件</span>
            <select v-model="agentFilter" aria-label="按 Agent 筛选">
              <option value="all">全部 Agent</option>
              <option v-for="agent in filterAgents" :key="agent.agent_id" :value="agent.agent_id">{{ agent.display_name || agent.agent_id }}</option>
            </select>
            <label><Search :size="13" /><input v-model="eventSearch" type="search" placeholder="搜索事件" /></label>
            <em>显示 {{ visibleEvents.length }} / {{ artifactCounts.events }}</em>
          </section>

          <section v-if="visibleEvents.length" class="event-timeline compact-timeline">
            <article v-for="event in visibleEvents" :key="event.event_id" class="event-card" :class="eventTone(event)">
              <span class="event-node"><CheckCircle2 v-if="eventTone(event) === 'completed'" :size="14" /><CircleAlert v-else-if="eventTone(event) === 'failed'" :size="14" /><Activity v-else :size="14" /></span>
              <div class="event-content">
                <header><div><span>{{ eventAgentName(event) }}</span><b>{{ eventLabel(event.event_type) }}</b></div><time>#{{ event.sequence }} · {{ formatTime(event.created_at) }}</time></header>
                <details class="event-summary-details"><summary><span>{{ event.summary }}</span><em>展开内容</em></summary><p>{{ event.summary }}</p></details>
                <details v-if="showAuditRecords" class="event-key-details"><summary>查看原始审计记录</summary><pre>{{ rawEventText(event) }}</pre></details>
              </div>
            </article>
          </section>
          <div v-else class="workspace-empty"><Clock3 :size="28" /><b>当前筛选下暂无运行事件</b><p>调整 Agent 或搜索条件后重试。</p></div>
          <button class="audit-toggle" type="button" @click="showAuditRecords = !showAuditRecords"><ShieldCheck :size="14" />{{ showAuditRecords ? '隐藏原始审计记录' : '允许展开原始审计记录' }}</button>
        </template>

        <template v-else-if="activeTab === 'evidence'">
          <section class="evidence-hero">
            <div><Database :size="22" /><span><b>证据中心</b><small>所有结论均回溯到证据编号、来源与质量评估。</small></span></div>
            <em>{{ evidenceRows.length }} 条证据</em>
          </section>
          <label class="evidence-search"><Search :size="15" /><input v-model="evidenceSearch" type="search" placeholder="搜索证据编号、主张、来源或 Agent" /><span>{{ filteredEvidence.length }} 项</span></label>
          <section v-if="filteredEvidence.length" class="evidence-grid">
            <article v-for="row in filteredEvidence" :key="row.evidence_id" class="evidence-card">
              <header><span>{{ row.evidence_id }}</span><em :class="evidenceQuality(row).tone">{{ evidenceQuality(row).label }}</em></header>
              <h3>{{ row.claim || '该证据通过运行事件被引用，完整主张未随旧快照保存。' }}</h3>
              <blockquote v-if="row.excerpt">{{ row.excerpt }}</blockquote>
              <dl>
                <dt>来源</dt><dd>{{ row.source_title || row.source_location || '来源信息待核验' }}</dd>
                <dt>贡献者</dt><dd>{{ BUSINESS_AGENTS[row.created_by]?.display_name || row.created_by || '研究 Agent' }}</dd>
                <dt>记录时间</dt><dd>{{ formatTime(row.created_at) }}</dd>
              </dl>
              <footer>
                <a v-if="row.source_url" :href="row.source_url" target="_blank" rel="noreferrer">查看原始来源 <ChevronRight :size="12" /></a>
                <span v-else><ShieldCheck :size="12" />运行留痕</span>
              </footer>
            </article>
          </section>
          <div v-else class="workspace-empty"><Database :size="30" /><b>{{ evidenceRows.length ? '没有匹配的证据' : '尚未形成可展示证据' }}</b><p>{{ evidenceRows.length ? '尝试缩短搜索词。' : '研究运行后，证据卡会在这里持续汇聚。' }}</p></div>
        </template>

        <template v-else>
          <div v-if="!winningInput" class="workspace-empty"><BrainCircuit :size="30" /><b>本次运行尚未形成 S1–S6 Agent 输入包</b><p>进入制胜机理阶段后将自动展示。</p></div>
          <div v-else class="winning-view s-agent-results-view">
            <section class="winning-input">
              <div><span>S1–S6 AGENT 输入包</span><h2>{{ winningInput.problem_frame?.objective || run?.topic }}</h2><p>{{ winningInput.problem_frame?.route_frame || run?.supplemental_information }}</p></div>
              <dl><dt>研究路线</dt><dd>{{ routeLabel(winningInput.research_route || run?.research_route) }}</dd><dt>输入 Packet</dt><dd>{{ winningInput.packet_ids?.length || 0 }}</dd><dt>证据索引</dt><dd>{{ winningInput.evidence_index?.length || artifactCounts.evidence }}</dd><dt>当前轮次</dt><dd>{{ winningInput.round_budget?.current_round || 1 }} / {{ winningInput.round_budget?.maximum_rounds || run?.max_rounds || 2 }}</dd></dl>
            </section>

            <section v-if="dynamicMembers.length || portfolioRows.length" class="winning-swarm-panel">
              <div class="section-heading"><div><b>制胜机理弹性 Agent 群</b><span>三波开放探索；S1–S6 按依赖动态调度，只有通过门控的贡献进入共享账本。</span></div><em>{{ portfolioRows.length }} 条最终候选</em></div>
              <div class="swarm-metrics"><div><small>动态实例</small><b>{{ dynamicStatusCount(['completed', 'merged']) }} / {{ dynamicMembers.length }}</b></div><div><small>专用波次</small><b>{{ [1, 2, 3].filter((wave) => waveMembers(wave).length).length }} / 3</b></div><div><small>S Agent</small><b>{{ completedSAgents }} / 6</b></div><div><small>最终合并</small><b>{{ portfolioRows.length ? '门控通过' : '运行中' }}</b></div></div>
              <div class="swarm-wave-grid"><article v-for="wave in [1, 2, 3]" :key="wave"><i>W{{ wave }}</i><div><b>{{ waveLabel(wave) }}</b><small>{{ waveMembers(wave).length }} 个专用 Agent</small></div></article></div>
              <div v-if="portfolioRows.length" class="swarm-finalists"><article v-for="(item, index) in portfolioRows" :key="item.hypothesis_id || candidateTitle(item)"><header><i>{{ index + 1 }}</i><div><b>{{ candidateTitle(item) }}</b><small>{{ item.equipment_form || item.primary_equipment_identity || '装备形态待验证' }}</small></div><em v-if="item.score || item.innovation_priority">{{ Math.round(Number(item.score || item.innovation_priority) * 100) }}%</em></header><p>{{ candidateSummary(item) }}</p><div><span>证据 {{ item.evidence_ids?.length || 0 }}</span><span>残差 {{ item.residuals?.length || 0 }}</span><span>{{ item.status || item.selection_status || 'finalist' }}</span></div></article></div>
            </section>

            <section class="winning-resource-section">
              <div class="section-heading"><div><b>共享受控资源</b><span>各 Agent 读取投影后的理论、案例、前沿证据与问题链，不共享其他 Agent 原始会话。</span></div></div>
              <div class="winning-resources">
                <article v-for="block in resourceBlocks" :key="block.title"><b>{{ block.title }}</b><span>{{ block.rows.length }} 项</span><ul><li v-for="(row, index) in block.rows.slice(0, 5)" :key="index">{{ row[block.field] || displayValue(row) }}</li></ul></article>
              </div>
            </section>

            <section class="s-agent-result-section">
              <div class="section-heading"><div><b>六个专用 Agent 结果</b><span>按 Agent 展示“认识—证据—置信度—下一步建议”。</span></div><small>{{ reasoningNodes.length }} 个结果节点</small></div>
              <div class="s-agent-result-grid">
                <article v-for="card in sAgentCards" :key="card.step" class="s-agent-result-card" :class="card.node ? 'completed' : card.status">
                  <header><i>S{{ card.step }}</i><div><b>{{ card.name }}</b><small>{{ card.task }}</small></div><span>{{ card.node ? `已形成 · 回溯 ${card.backtrack_count || 0}` : statusLabel(card.status) }}</span></header>
                  <template v-if="card.node">
                    <h3>{{ card.node.title || `S${card.step} 研究认识` }}</h3>
                    <div class="s-agent-result-quad"><section class="recognition"><small>认识</small><p>{{ card.node.summary || '—' }}</p></section><section><small>证据</small><p>{{ card.node.evidence_ids?.slice(0, 4).join(' · ') || '暂无可展示证据编号' }}</p></section><section><small>置信度</small><b>{{ Math.round(Number(card.node.confidence || 0) * 100) }}%</b></section><section class="next"><small>下一步建议</small><p>{{ card.node.next_action?.reason || card.node.next_step_suggestion || '以循环门控和开放问题为准。' }}</p></section></div>
                    <details><summary>输入、假设与追溯</summary><div><span><b>输入引用</b>{{ card.node.input_refs?.join(' · ') || '—' }}</span><span><b>关键假设</b>{{ card.node.assumptions?.join('；') || '—' }}</span></div></details>
                  </template>
                  <p v-else class="s-agent-result-empty">{{ card.status === 'skipped' ? '当前分支按业务路径跳过该 Agent，不生成虚假结果。' : '该 Agent 尚未形成结果节点。' }}</p>
                  <footer><span>{{ card.skills.slice(0, 2).join(' · ') }}</span><code>{{ card.harness }}</code></footer>
                </article>
              </div>
            </section>

            <section v-if="winningStages.length" class="s-agent-loop-results">
              <div class="section-heading"><div><b>循环门控结果</b><span>L1 内循环、L2 中循环与 L3 外循环检查六个 Agent 结果的证据、连续性和覆盖。</span></div></div>
              <div><article v-for="stage in winningStages" :key="stage.stage_id" :class="stage.gate_passed === false ? 'limited' : 'passed'"><header><i>{{ stage.layer || 'L1' }}</i><div><b>{{ stage.title || '循环门控' }}</b><small>置信度 {{ Math.round(Number(stage.confidence || 0) * 100) }}% · 证据 {{ stage.evidence_ids?.length || 0 }}</small></div><em>{{ stage.gate_passed === false ? '门控受限' : '门控通过' }}</em></header><p v-if="stage.gate_reasons?.length">{{ stage.gate_reasons.join('；') }}</p><p v-else-if="stage.summary">{{ stage.summary }}</p><details v-if="stage.outputs && Object.keys(stage.outputs).length"><summary>查看本层输出</summary><div><span v-for="(value, key) in stage.outputs" :key="key"><b>{{ key }}</b>{{ displayValue(value) }}</span></div></details></article></div>
            </section>

            <section v-if="winningRecalls.length" class="winning-recalls s-agent-recalls">
              <div class="section-heading"><div><b>定向回溯与再调</b><span>按 S Agent、能力标签或返回节点补充，不无差别重跑整个流程。</span></div></div>
              <article v-for="item in winningRecalls" :key="item.recall_id"><b>{{ item.source_layer || '门控' }} → {{ item.return_node || `S${item.target_step || '?'}` }}</b><span>{{ item.target_agent_id || item.target_capability_tag || '目标 Agent' }}</span><p>{{ item.reason }}</p><small>{{ statusLabel(item.status || 'completed') }}</small></article>
            </section>
          </div>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
.run-detail-page {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding-bottom: 30px;
  color: #20283a;
}

button,
input,
select {
  font: inherit;
}

button {
  cursor: pointer;
}

.run-detail-backbar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  padding: 7px 9px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  background: var(--gray-0);
  box-shadow: 0 5px 18px var(--shadow-0);
}

.run-detail-backbar > span {
  overflow: hidden;
  color: var(--gray-500);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.back-button,
.icon-button,
.run-detail-actions button,
.run-detail-meta button,
.run-load-error button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--gray-200);
  border-radius: 7px;
  background: var(--gray-0);
  color: var(--gray-700);
  font-size: 11px;
  font-weight: 650;
}

.icon-button {
  width: 31px;
  padding: 0;
}

.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.run-detail-hero {
  position: relative;
  display: grid;
  gap: 14px;
  padding: 22px;
  overflow: hidden;
  border: 1px solid #dfe5ef;
  border-radius: 14px;
  background:
    radial-gradient(circle at 92% 0%, rgba(98, 95, 240, 0.11), transparent 27%),
    linear-gradient(145deg, #fff, #f9faff);
  box-shadow: 0 14px 34px rgba(48, 56, 105, 0.06);
}

.run-detail-hero::after {
  position: absolute;
  right: -28px;
  bottom: -60px;
  width: 190px;
  height: 190px;
  border: 1px solid rgba(98, 95, 240, 0.09);
  border-radius: 50%;
  content: '';
}

.run-detail-heading {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.run-detail-heading > div {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.run-detail-heading > div > span,
.winning-input > div > span {
  color: var(--main-700);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.run-detail-heading h1 {
  margin: 0;
  color: #253149;
  font-size: clamp(21px, 2.2vw, 28px);
  line-height: 1.25;
}

.run-detail-heading p {
  max-width: 900px;
  margin: 0;
  color: #748096;
  font-size: 11px;
  line-height: 1.6;
}

.run-detail-status {
  flex: 0 0 auto;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--main-50);
  color: var(--main-700);
  font-size: 10px;
  font-weight: 800;
}

.run-detail-status.completed,
.run-detail-status.archived {
  background: #e9f7ef;
  color: #2f7d56;
}

.run-detail-status.failed,
.run-detail-status.cancelled {
  background: #fbeaec;
  color: #a84d57;
}

.run-detail-status.paused,
.run-detail-status.pause_requested {
  background: #faf2e2;
  color: #8c6932;
}

.run-progress {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.run-progress > div {
  height: 7px;
  flex: 1;
  overflow: hidden;
  border-radius: 999px;
  background: #e9edf4;
}

.run-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--main-700), var(--main-500));
  box-shadow: 0 0 12px rgba(98, 95, 240, 0.3);
  transition: width 0.35s ease;
}

.run-progress span {
  min-width: 32px;
  color: var(--main-700);
  font-size: 10px;
  font-weight: 800;
  text-align: right;
}

.run-detail-meta,
.run-detail-actions {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.run-detail-meta span,
.run-detail-meta button {
  min-height: 0;
  padding: 4px 8px;
  border: 1px solid #dfe4ed;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.78);
  color: #6c788e;
  font-size: 10px;
  font-weight: 500;
}

.run-detail-meta button {
  color: var(--main-700);
}

.run-detail-actions button.primary {
  border-color: var(--main-600);
  background: var(--main-600);
  color: #fff;
}

.run-detail-actions button.danger {
  border-color: #eccbd0;
  color: #a84955;
}

.run-detail-actions button:disabled,
.icon-button:disabled {
  cursor: wait;
  opacity: 0.55;
}

.run-error-banner,
.projection-note {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 11px;
  border: 1px solid #efcdd1;
  border-radius: 7px;
  background: #fff7f7;
  color: #a84d57;
  font-size: 10px;
  line-height: 1.5;
}

.projection-note {
  border-color: #d9d7f5;
  background: var(--main-40);
  color: #5f5db8;
}

.run-artifact-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 9px;
}

.run-artifact-strip button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  min-width: 0;
  padding: 12px;
  border: 1px solid #dfe5ef;
  border-radius: 10px;
  background: #fff;
  color: var(--main-700);
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.run-artifact-strip button:hover,
.run-artifact-strip button.active {
  border-color: var(--main-300);
  box-shadow: 0 8px 20px rgba(68, 66, 194, 0.08);
  transform: translateY(-1px);
}

.run-artifact-strip button.active {
  background: var(--main-30);
}

.run-artifact-strip button > span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.run-artifact-strip b {
  color: #3f4c63;
  font-size: 11px;
}

.run-artifact-strip small {
  overflow: hidden;
  color: #8993a5;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-event-workspace {
  display: grid;
  gap: 15px;
  min-width: 0;
  padding: 18px;
  border: 1px solid #dfe5ef;
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 12px 30px rgba(47, 56, 98, 0.045);
}

.workspace-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #edf0f5;
}

.run-detail-tabs {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.run-detail-tabs button {
  height: 32px;
  padding: 0 11px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #68758b;
  font-size: 10px;
  font-weight: 700;
}

.run-detail-tabs button:hover {
  background: #f4f6fa;
}

.run-detail-tabs button.active {
  border-color: var(--main-600);
  background: var(--main-600);
  color: #fff;
  box-shadow: 0 5px 12px rgba(98, 95, 240, 0.18);
}

.live-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  padding: 5px 8px;
  border-radius: 999px;
  background: #eef1f5;
  color: #737f92;
  font-size: 10px;
  font-weight: 650;
}

.live-state.connected {
  background: #e6f5eb;
  color: #2f7d56;
}

.live-state.offline {
  background: #fff1e7;
  color: #9b6222;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  min-height: 88px;
  padding: 17px;
  border: 1px solid #e3e7f1;
  border-radius: 12px;
  background: linear-gradient(145deg, #fff, #fafbff);
  color: #20283a;
}

.metric div {
  display: grid;
  gap: 2px;
}

.metric span {
  color: #7e899b;
  font-size: 10px;
}

.metric b {
  color: #35445f;
  font-size: 18px;
}

.compact-workflow {
  margin-bottom: 0;
}

.workflow-overview > header > em {
  padding: 4px 8px;
  border-radius: 999px;
  background: #eef1f6;
  color: #707c90;
  font-size: 10px;
  font-style: normal;
}

.workflow-phases-six article {
  min-width: 0;
}

.workflow-phases-six article.completed {
  border-color: #cfe4d6;
  background: #eef8f1;
  color: #397656;
}

.workflow-phases-six article.running {
  border-color: #afaeed;
  background: #eef1ff;
  color: #504ebd;
  box-shadow: inset 3px 0 var(--main-600);
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-heading > div {
  display: grid;
  gap: 3px;
}

.section-heading b {
  color: #2f3d55;
  font-size: 13px;
}

.section-heading span {
  color: #7b8799;
  font-size: 10px;
  line-height: 1.45;
}

.section-heading > em,
.section-heading > small {
  color: var(--main-700);
  font-size: 10px;
  font-style: normal;
}

.section-heading button {
  border: 0;
  background: transparent;
  color: var(--main-700);
  font-size: 10px;
}

.overview-latest,
.agent-map {
  padding: 15px;
  border: 1px solid #dfe5ef;
  border-radius: 9px;
  background: #fff;
}

.latest-event-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  margin-top: 11px;
}

.latest-event-grid article {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid #e7eaf0;
  border-radius: 6px;
  background: #fafbfd;
}

.latest-event-grid > article > i {
  width: 7px;
  height: 7px;
  margin-top: 4px;
  border-radius: 50%;
  background: #9ba4b3;
}

.latest-event-grid > article > i.running { background: var(--main-600); }
.latest-event-grid > article > i.completed { background: #3a8868; }
.latest-event-grid > article > i.failed { background: #b25b64; }
.latest-event-grid b { color: #3a475d; font-size: 10px; }
.latest-event-grid p { display: -webkit-box; margin: 3px 0; overflow: hidden; color: #657187; font-size: 10px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.latest-event-grid small { color: #929baa; font-size: 9px; }

.compact-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 80px;
  color: #8993a4;
  font-size: 10px;
}

.event-filter {
  display: grid;
  grid-template-columns: auto minmax(150px, 210px) minmax(180px, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  border: 1px solid #e1e6ef;
  border-radius: 7px;
  background: #fafbfd;
}

.event-filter > span {
  color: #43516a;
  font-size: 11px;
  font-weight: 700;
}

.event-filter select,
.event-filter label,
.evidence-search {
  min-height: 31px;
  border: 1px solid #dce3ed;
  border-radius: 6px;
  background: #fff;
}

.event-filter select {
  padding: 0 8px;
  color: #526078;
  font-size: 10px;
}

.event-filter label,
.evidence-search {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 9px;
  color: #8791a2;
}

.event-filter input,
.evidence-search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: #3e4b61;
  font-size: 10px;
}

.event-filter em {
  color: #7f8a9b;
  font-size: 10px;
  font-style: normal;
}

.event-timeline {
  position: relative;
  display: grid;
  gap: 9px;
  padding-left: 39px;
}

.event-timeline::before {
  position: absolute;
  top: 13px;
  bottom: 13px;
  left: 14px;
  width: 1px;
  background: #dde3ed;
  content: '';
}

.event-card {
  position: relative;
  min-width: 0;
  border: 1px solid #e1e6ef;
  border-radius: 7px;
  background: #fff;
}

.event-node {
  position: absolute;
  top: 13px;
  left: -39px;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 1px solid #dce2ec;
  border-radius: 50%;
  background: #fff;
  color: #778398;
}

.event-card.completed .event-node { border-color: #c8dfd2; background: #eaf6ef; color: #347657; }
.event-card.running .event-node { border-color: #c9c8f3; background: #efefff; color: var(--main-700); }
.event-card.failed .event-node { border-color: #edc9cd; background: #fbeaec; color: #a84d57; }

.event-content {
  padding: 11px 13px;
}

.event-content > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.event-content > header > div {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.event-content > header span {
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--main-50);
  color: var(--main-700);
  font-size: 9px;
}

.event-content > header b { color: #344157; font-size: 11px; }
.event-content time { color: #929baa; font-size: 9px; white-space: nowrap; }
.event-key-details pre { max-height: 300px; margin: 8px 0 0; padding: 9px; overflow: auto; border-radius: 5px; background: #f5f7fa; color: #526078; font-size: 9px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }

.audit-toggle {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  gap: 6px;
  padding: 6px 9px;
  border: 1px solid #dde3ed;
  border-radius: 6px;
  background: #fff;
  color: #667389;
  font-size: 10px;
}

.evidence-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 15px;
  border: 1px solid #dfe5ef;
  border-radius: 9px;
  background: linear-gradient(145deg, #fbfcff, var(--main-30));
}

.evidence-hero > div {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--main-700);
}

.evidence-hero span { display: grid; gap: 3px; }
.evidence-hero b { color: #2f3d55; font-size: 14px; }
.evidence-hero small { color: #788397; font-size: 10px; }
.evidence-hero em { padding: 4px 8px; border-radius: 999px; background: var(--main-50); color: var(--main-700); font-size: 10px; font-style: normal; }
.evidence-search { width: min(520px, 100%); }
.evidence-search > span { color: #8a94a5; font-size: 10px; }

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.evidence-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 13px;
  border: 1px solid #dfe5ee;
  border-top: 3px solid var(--main-600);
  border-radius: 8px;
  background: #fff;
}

.evidence-card > header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.evidence-card > header > span { overflow: hidden; color: var(--main-700); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.evidence-card > header em { flex: 0 0 auto; padding: 3px 6px; border-radius: 999px; font-size: 9px; font-style: normal; }
.evidence-card > header em.high { background: #e5f3eb; color: #347657; }
.evidence-card > header em.medium { background: #edf1ff; color: #5351bd; }
.evidence-card > header em.pending { background: #faf2e2; color: #8c6932; }
.evidence-card h3 { margin: 11px 0 8px; color: #344157; font-size: 11px; line-height: 1.6; }
.evidence-card blockquote { margin: 0 0 9px; padding: 7px 9px; border-left: 2px solid var(--main-300); background: #f7f8fb; color: #68758a; font-size: 10px; line-height: 1.55; }
.evidence-card dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 5px 8px; margin: auto 0 0; padding: 9px 0; border-top: 1px solid #edf0f4; }
.evidence-card dt { color: #929baa; font-size: 9px; }
.evidence-card dd { min-width: 0; margin: 0; overflow: hidden; color: #5d697d; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.evidence-card footer { display: flex; align-items: center; min-height: 20px; }
.evidence-card footer a,
.evidence-card footer span { display: inline-flex; align-items: center; gap: 3px; color: var(--main-700); font-size: 9px; text-decoration: none; }

.workspace-empty,
.run-load-error {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 7px;
  min-height: 220px;
  padding: 24px;
  border: 1px dashed #d8dee8;
  border-radius: 9px;
  background: #fafbfd;
  color: #8a94a5;
  text-align: center;
}

.workspace-empty b,
.run-load-error b { color: #536076; font-size: 12px; }
.workspace-empty p,
.run-load-error p { margin: 0; color: #8a94a5; font-size: 10px; }

.run-detail-skeleton {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.run-detail-skeleton i {
  height: 92px;
  border-radius: 10px;
  background: linear-gradient(90deg, #f0f2f5 25%, #f8f9fb 37%, #f0f2f5 63%);
  background-size: 400% 100%;
  animation: skeleton 1.4s ease infinite;
}

.run-detail-skeleton i:first-child { grid-column: 1 / -1; height: 210px; }

@keyframes skeleton {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}

.winning-view {
  display: grid;
  gap: 14px;
}

.winning-input {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.7fr);
  gap: 18px;
  padding: 18px;
  border: 1px solid #d9dff0;
  border-radius: 9px;
  background: linear-gradient(145deg, #fafbff, var(--main-30));
}

.winning-input h2 { margin: 6px 0; color: #29374f; font-size: 19px; line-height: 1.35; }
.winning-input p { margin: 0; color: #6b788e; font-size: 10px; line-height: 1.6; }
.winning-input dl { display: grid; grid-template-columns: auto 1fr; align-content: center; gap: 7px 10px; margin: 0; padding: 12px; border: 1px solid rgba(98, 95, 240, 0.12); border-radius: 7px; background: rgba(255, 255, 255, 0.72); }
.winning-input dt { color: #8490a2; font-size: 10px; }
.winning-input dd { margin: 0; color: #465675; font-size: 10px; font-weight: 700; text-align: right; }

.winning-swarm-panel {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid #dadff0;
  border-radius: 9px;
  background: linear-gradient(145deg, #fbfcff, #f8f6ff);
}

.swarm-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }
.swarm-metrics > div { display: grid; gap: 4px; padding: 9px 10px; border: 1px solid #e1e6ef; border-radius: 6px; background: rgba(255, 255, 255, 0.82); }
.swarm-metrics small { color: #7f8a9b; font-size: 9px; }
.swarm-metrics b { color: #405170; font-size: 13px; }
.swarm-wave-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; }
.swarm-wave-grid article { display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid #e1e5ef; border-radius: 6px; background: #fff; }
.swarm-wave-grid i { display: grid; place-items: center; width: 28px; height: 25px; border-radius: 5px; background: var(--main-50); color: var(--main-700); font-size: 10px; font-style: normal; font-weight: 800; }
.swarm-wave-grid div { display: grid; gap: 2px; }
.swarm-wave-grid b { color: #3b485e; font-size: 10px; }
.swarm-wave-grid small { color: #8590a1; font-size: 9px; }
.swarm-finalists { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.swarm-finalists article { padding: 10px; border: 1px solid #dce7e2; border-radius: 6px; background: #fbfefc; }
.swarm-finalists article > header { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; gap: 7px; }
.swarm-finalists article > header > i { display: grid; place-items: center; width: 23px; height: 23px; border-radius: 50%; background: #e4f2eb; color: #34775c; font-size: 9px; font-style: normal; font-weight: 800; }
.swarm-finalists article > header div { display: grid; gap: 2px; min-width: 0; }
.swarm-finalists article > header b { overflow: hidden; color: #344c43; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.swarm-finalists article > header small { color: #71857d; font-size: 9px; }
.swarm-finalists article > header em { color: #34775c; font-size: 11px; font-style: normal; font-weight: 800; }
.swarm-finalists article > p { margin: 7px 0; color: #5f716b; font-size: 10px; line-height: 1.5; }
.swarm-finalists article > div { display: flex; flex-wrap: wrap; gap: 4px; }
.swarm-finalists article > div span { padding: 2px 4px; border-radius: 4px; background: #eaf3ef; color: #557267; font-size: 9px; }

.winning-resource-section,
.s-agent-result-section,
.s-agent-loop-results,
.winning-recalls {
  padding: 16px;
  border: 1px solid #dfe6ef;
  border-radius: 8px;
  background: #fff;
}

.winning-resources {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.winning-resources article { min-width: 0; padding: 10px; border: 1px solid #e2e7ef; border-radius: 6px; background: #fafbfd; }
.winning-resources article > b { color: #3b485e; font-size: 10px; }
.winning-resources article > span { float: right; color: var(--main-700); font-size: 9px; }
.winning-resources ul { margin: 8px 0 0; padding-left: 15px; }
.winning-resources li { overflow: hidden; margin: 4px 0; color: #68758a; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }

.s-agent-result-card details > div,
.s-agent-loop-results details > div {
  color: #59667a;
}

.s-agent-result-card details > div > span,
.s-agent-loop-results details > div > span {
  display: grid;
  gap: 3px;
}

.s-agent-result-card details b,
.s-agent-loop-results details b {
  color: #7d8798;
  font-size: 9px;
}

.s-agent-loop-results article > p { margin: 8px 0 0; color: #68758a; font-size: 10px; line-height: 1.5; }
.s-agent-loop-results article > header > em { color: #347657; font-size: 9px; font-style: normal; }
.s-agent-loop-results article.limited > header > em { color: #91642e; }

.winning-recalls { display: grid; gap: 8px; }
.winning-recalls > article { display: grid; grid-template-columns: minmax(120px, 0.8fr) minmax(100px, 0.6fr) minmax(200px, 1.8fr) auto; align-items: center; gap: 8px; padding: 8px 9px; border-radius: 6px; background: #f7f8fb; }
.winning-recalls > article b { color: #45536b; font-size: 10px; }
.winning-recalls > article span { color: var(--main-700); font-size: 9px; }
.winning-recalls > article p { margin: 0; color: #68758a; font-size: 9px; }
.winning-recalls > article small { color: #3c8061; font-size: 9px; }

@media (max-width: 1180px) {
  .run-artifact-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .workflow-phases-six { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .s-agent-grid,
  .s-agent-result-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .swarm-role-pools { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .evidence-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 800px) {
  .run-detail-heading,
  .workspace-toolbar,
  .workflow-overview > header,
  .dynamic-swarm-panel > header,
  .section-heading { align-items: flex-start; flex-direction: column; }
  .run-artifact-strip,
  .metric-strip,
  .dynamic-swarm-counts,
  .loop-overview,
  .swarm-metrics,
  .winning-resources { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .event-filter { grid-template-columns: 1fr 1fr; }
  .event-filter > span { grid-column: 1 / -1; }
  .event-filter > em { text-align: right; }
  .winning-input { grid-template-columns: 1fr; }
  .swarm-candidate-board > div { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .latest-event-grid { grid-template-columns: 1fr; }
}

@media (max-width: 560px) {
  .run-detail-page { gap: 11px; }
  .run-detail-hero,
  .run-event-workspace { padding: 13px; border-radius: 10px; }
  .run-detail-heading h1 { font-size: 19px; }
  .run-detail-status { align-self: flex-start; }
  .run-artifact-strip,
  .metric-strip,
  .workflow-phases-six,
  .s-agent-grid,
  .s-agent-result-grid,
  .dynamic-swarm-counts,
  .swarm-role-pools,
  .swarm-candidate-board > div,
  .swarm-equipment-portfolio > div,
  .loop-overview,
  .evidence-grid,
  .swarm-metrics,
  .swarm-wave-grid,
  .swarm-finalists,
  .winning-resources { grid-template-columns: 1fr; }
  .run-detail-tabs { display: grid; grid-template-columns: repeat(2, 1fr); width: 100%; }
  .run-detail-tabs button { width: 100%; }
  .live-state { align-self: flex-start; }
  .event-filter { grid-template-columns: 1fr; }
  .event-filter > span { grid-column: auto; }
  .event-filter > em { text-align: left; }
  .event-content > header { flex-direction: column; }
  .event-timeline { padding-left: 32px; }
  .event-node { left: -32px; width: 24px; height: 24px; }
  .winning-recalls > article { grid-template-columns: 1fr; }
  .run-detail-skeleton { grid-template-columns: 1fr; }
  .run-detail-skeleton i:first-child { grid-column: auto; }
}
</style>
