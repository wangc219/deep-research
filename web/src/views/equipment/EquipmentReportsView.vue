<script setup>
import {
  computed,
  nextTick,
  onActivated,
  onDeactivated,
  onMounted,
  onUnmounted,
  ref,
  watch
} from 'vue'
import '@/assets/css/equipment-workbench-live.css'
import '@/assets/css/equipment-workbench-theme.css'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { storeToRefs } from 'pinia'
import {
  AlignLeft,
  Archive,
  ChevronDown,
  CircleAlert,
  Copy,
  Download,
  FileCheck2,
  FlaskConical,
  ListFilter,
  MessageSquare,
  Printer,
  RefreshCw,
  Search,
  WifiOff
} from '@lucide/vue'
import { useEquipmentStore } from '@/stores/equipment'
import { equipmentApi } from '@/apis/equipment_api'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { capabilityVersionMeta, normalizeCapabilities } from '@/utils/equipmentCapabilities'
import EquipmentReportCapabilityCards from './EquipmentReportCapabilityCards.vue'
import {
  compactReportInlineLinks,
  normalizeReportDocument,
  reportFilename,
  reporterLifecycle,
  routeLabel,
  runStatusLabel
} from './reportPresentation.js'

const route = useRoute()
const router = useRouter()
const equipmentStore = useEquipmentStore()
const {
  resources,
  loading: resourceLoading,
  loaded: resourceLoaded
} = storeToRefs(equipmentStore)

const selectedRunId = ref(String(route.query.run || ''))
const standaloneRun = ref(null)
const taskQuery = ref('')
const taskStatus = ref('all')
const reportBody = ref('')
const reportReadError = ref('')
const events = ref([])
const artifactsLoading = ref(false)
const eventsLoading = ref(false)
const pageLoading = ref(false)
const pageReady = ref(false)
const resumingReport = ref(false)
const reportResumeError = ref('')
const online = ref(typeof navigator === 'undefined' ? true : navigator.onLine)
const syncWarning = ref('')
const headings = ref([])
const tocOpen = ref(false)
const reportArticleRef = ref(null)
const tocRef = ref(null)
const contentRef = ref(null)

let artifactRequestToken = 0
let pollTimer = null
let pollInFlight = false
let pageActive = true
let reportObserver = null

const activeStatuses = new Set([
  'queued',
  'planning',
  'researching',
  'recalling',
  'synthesizing',
  'reviewing',
  'reporting',
  'pause_requested',
  'cancel_requested'
])

const runs = computed(() => resources.value.runs || [])
const reports = computed(() => resources.value.reports || [])
const capabilities = computed(() => normalizeCapabilities(resources.value.capabilities))
const availableRuns = computed(() => {
  const current = runs.value.filter((item) => item.status !== 'archived')
  if (
    standaloneRun.value &&
    standaloneRun.value.status !== 'archived' &&
    !current.some((item) => item.run_id === standaloneRun.value.run_id)
  ) {
    return [standaloneRun.value, ...current]
  }
  return current
})
const selectedRun = computed(
  () =>
    runs.value.find((item) => String(item.run_id) === selectedRunId.value) ||
    (String(standaloneRun.value?.run_id || '') === selectedRunId.value
      ? standaloneRun.value
      : null)
)
const selectedReportMeta = computed(
  () => reports.value.find((item) => String(item.run_id) === selectedRunId.value) || null
)
const selectedCapabilities = computed(() =>
  capabilities.value.filter((item) => String(item.run_id || '') === selectedRunId.value)
)
const reportCapabilities = computed(() => selectedCapabilities.value.map((item) => (
  capabilityVersionMeta(item).formalBaseline
    ? { ...item, confidence_limited: false, is_deep_research: false }
    : item
)))
const isRunActive = computed(() => activeStatuses.has(selectedRun.value?.status))
const lifecycle = computed(() => reporterLifecycle(events.value, selectedRun.value?.status || ''))
const normalizedReport = computed(() =>
  reportBody.value.trim()
    ? normalizeReportDocument(reportBody.value, selectedRun.value, reportCapabilities.value)
    : ''
)
const displayedReport = computed(() => compactReportInlineLinks(normalizedReport.value))
const visibleRuns = computed(() => {
  const keyword = taskQuery.value.trim().toLowerCase()
  return availableRuns.value.filter((item) => {
    const matchesStatus =
      taskStatus.value === 'all' ||
      (taskStatus.value === 'active' && activeStatuses.has(item.status)) ||
      taskStatus.value === item.status
    const searchable = `${item.topic || ''} ${item.supplemental_information || ''} ${item.run_id || ''}`.toLowerCase()
    return matchesStatus && (!keyword || searchable.includes(keyword))
  })
})
const loadingResources = computed(
  () => Boolean(resourceLoading.value.runs || resourceLoading.value.reports)
)
const showFailure = computed(
  () =>
    !eventsLoading.value &&
    !displayedReport.value &&
    (lifecycle.value.status === 'failed' ||
      (selectedRun.value?.status === 'failed' && lifecycle.value.terminalFailure))
)
const awaitingReport = computed(() => {
  const status = selectedRun.value?.status
  if (!selectedRun.value || displayedReport.value || showFailure.value) return false
  return Boolean(
    isRunActive.value ||
      lifecycle.value.status === 'running' ||
      status === 'completed' ||
      (status === 'failed' && lifecycle.value.started && !lifecycle.value.terminalFailure)
  )
})
const shouldPoll = computed(() => {
  if (!pageActive || !online.value || !selectedRun.value) return false
  if (displayedReport.value) return isRunActive.value
  if (['cancelled', 'archived', 'draft', 'paused'].includes(selectedRun.value.status)) return false
  return !lifecycle.value.terminalFailure || lifecycle.value.status === 'running'
})
const failureDetail = computed(() =>
  String(
    lifecycle.value.failureDetail ||
      selectedRun.value?.error ||
      'Reporter 未能完成独立深度撰写。已完成的能力画像仍然保留。'
  ).slice(0, 600)
)
const earlyCapabilityLabel = computed(() =>
  ['completed', 'failed', 'cancelled', 'archived'].includes(selectedRun.value?.status)
    ? '报告正文暂不可读，先展示已完成的能力画像'
    : '报告仍在后台撰写，先展示已完成的能力画像'
)
const emptyDescription = computed(() => {
  if (!selectedRun.value) return '请选择研究任务'
  if (selectedRun.value.historical_snapshot) return '历史快照未包含原始报告产物'
  if (selectedRun.value.status === 'cancelled') return '该任务已取消，未形成可读报告正文'
  if (selectedRun.value.status === 'draft') return '草稿任务启动并完成后可查看研究报告'
  if (selectedRun.value.status === 'paused') return '任务已暂停，可从任务详情继续执行'
  if (reportReadError.value) return '报告产物读取失败，请刷新后重试'
  return selectedRun.value.status === 'completed'
    ? '报告产物暂不可读，请刷新后重试'
    : '任务完成后可查看本页'
})

const isMissingReportError = (error) => Number(error?.status || error?.response?.status) === 404

const hydrateMissingRun = async (runId) => {
  if (!runId || runs.value.some((item) => String(item.run_id) === runId)) {
    standaloneRun.value = null
    return
  }
  try {
    standaloneRun.value = await equipmentApi.getRun(runId)
  } catch {
    standaloneRun.value = null
  }
}

const readSelectedArtifacts = async ({ quiet = false, reset = false } = {}) => {
  const runId = selectedRunId.value
  const token = ++artifactRequestToken
  if (reset) {
    reportBody.value = ''
    reportReadError.value = ''
    events.value = []
    headings.value = []
    tocOpen.value = false
    reportResumeError.value = ''
  }
  if (!runId) {
    artifactsLoading.value = false
    eventsLoading.value = false
    return
  }

  if (!quiet || reset) artifactsLoading.value = true
  if (reset || !events.value.length) eventsLoading.value = true
  const [reportResult, eventResult] = await Promise.allSettled([
    equipmentApi.getResearchReport(runId),
    equipmentApi.listEvents(runId, 0)
  ])
  if (token !== artifactRequestToken) return

  let connectionFailure = ''
  if (reportResult.status === 'fulfilled') {
    const value = reportResult.value
    const body = typeof value === 'string' ? value : value?.content || value?.report || ''
    if (String(body || '').trim()) reportBody.value = String(body)
    reportReadError.value = ''
  } else if (!isMissingReportError(reportResult.reason)) {
    reportReadError.value = reportResult.reason?.message || '研究报告读取失败'
    connectionFailure = reportReadError.value
  } else {
    reportReadError.value = ''
  }

  if (eventResult.status === 'fulfilled') {
    events.value = Array.isArray(eventResult.value)
      ? eventResult.value
      : eventResult.value?.items || []
  } else {
    connectionFailure = eventResult.reason?.message || '运行事件同步失败'
  }

  syncWarning.value = online.value ? connectionFailure : '网络已断开，恢复连接后将自动继续同步'
  artifactsLoading.value = false
  eventsLoading.value = false
}

const refreshResources = async ({ quiet = false } = {}) => {
  const results = await Promise.allSettled(
    ['runs', 'reports', 'capabilities'].map((name) =>
      equipmentStore.loadResource(name, {}, { force: true })
    )
  )
  const failures = results.filter((result) => result.status === 'rejected')
  if (failures.length) {
    syncWarning.value = failures[0].reason?.message || '部分工作台数据同步失败'
    if (!quiet && failures.length === results.length) message.error(syncWarning.value)
  }
  return results
}

const ensureSelection = async () => {
  const requestedRunId = String(route.query.run || '')
  if (requestedRunId) {
    selectedRunId.value = requestedRunId
    await hydrateMissingRun(requestedRunId)
    return
  }
  const nextRunId = String(reports.value[0]?.run_id || availableRuns.value[0]?.run_id || '')
  selectedRunId.value = nextRunId
  if (nextRunId) await router.replace({ query: { ...route.query, run: nextRunId } })
}

const load = async ({ quiet = false, resetArtifacts = false } = {}) => {
  if (!quiet) pageLoading.value = true
  try {
    await refreshResources({ quiet })
    await ensureSelection()
    await readSelectedArtifacts({ quiet, reset: resetArtifacts || !pageReady.value })
    pageReady.value = true
  } finally {
    pageLoading.value = false
  }
}

const chooseRun = async (item) => {
  const runId = String(item.run_id || '')
  if (!runId) return
  if (runId === selectedRunId.value) {
    if (window.matchMedia('(max-width: 900px)').matches) {
      contentRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    return
  }
  standaloneRun.value = null
  selectedRunId.value = runId
  await router.replace({ query: { ...route.query, run: runId } })
  await readSelectedArtifacts({ reset: true })
  if (window.matchMedia('(max-width: 900px)').matches) {
    await nextTick()
    contentRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

const navigateArtifact = (path) => {
  router.push({ path, query: selectedRunId.value ? { run: selectedRunId.value } : {} })
}

const copyText = async (text) => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.left = '-999999px'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) throw new Error('复制失败')
}

const copyReport = async () => {
  try {
    await copyText(normalizedReport.value)
    message.success('已复制研究报告 Markdown')
  } catch {
    message.error('复制失败，请手动选择报告正文')
  }
}

const downloadReport = () => {
  const blob = new Blob([normalizedReport.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = reportFilename(selectedRun.value || { run_id: selectedRunId.value })
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
  message.success('报告已开始下载')
}

const enablePrintMode = () => document.body.classList.add('equipment-report-printing')
const disablePrintMode = () => document.body.classList.remove('equipment-report-printing')
const printReport = () => {
  enablePrintMode()
  try {
    window.print()
  } finally {
    window.setTimeout(disablePrintMode, 0)
  }
}

const resumeReport = async () => {
  if (!selectedRun.value || selectedRun.value.status !== 'failed') return
  resumingReport.value = true
  reportResumeError.value = ''
  try {
    const updated = await equipmentApi.resumeRun(selectedRun.value.run_id)
    standaloneRun.value = updated
    reportBody.value = ''
    message.success('已从检查点继续生成')
    await refreshResources({ quiet: true })
    await readSelectedArtifacts({ reset: true, quiet: true })
  } catch (error) {
    reportResumeError.value = error.message || '断点恢复失败，请检查 Worker 与模型配置。'
  } finally {
    resumingReport.value = false
  }
}

const refreshNow = async ({ quiet = false } = {}) => {
  if (!online.value) {
    syncWarning.value = '网络已断开，恢复连接后将自动继续同步'
    return
  }
  await Promise.allSettled([
    refreshResources({ quiet }),
    readSelectedArtifacts({ quiet })
  ])
}

const poll = async () => {
  if (pollInFlight || !shouldPoll.value || document.visibilityState === 'hidden') return
  pollInFlight = true
  try {
    await refreshNow({ quiet: true })
  } finally {
    pollInFlight = false
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = window.setInterval(() => void poll(), 2500)
}

const stopPolling = () => {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = null
}

const enhanceRenderedReport = () => {
  const root = reportArticleRef.value
  if (!root) {
    headings.value = []
    return
  }
  root.querySelectorAll('.report-markdown table').forEach((table) => {
    if (table.parentElement?.classList.contains('report-table-scroll')) return
    const wrapper = document.createElement('div')
    wrapper.className = 'report-table-scroll'
    table.parentNode?.insertBefore(wrapper, table)
    wrapper.appendChild(table)
  })
  root.querySelectorAll('.report-markdown a[href]').forEach((link) => {
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noreferrer')
  })
  const next = [
    ...root.querySelectorAll(
      '.report-markdown h1, .report-markdown h2, .report-markdown h3, .report-markdown h4'
    )
  ]
    .map((node, index) => ({
      index,
      level: Number(node.tagName.slice(1)) || 2,
      label: String(node.textContent || '').trim()
    }))
    .filter((item) => item.label)
  const unchanged =
    headings.value.length === next.length &&
    headings.value.every(
      (item, index) => item.level === next[index].level && item.label === next[index].label
    )
  if (!unchanged) headings.value = next
}

const connectReportObserver = async () => {
  reportObserver?.disconnect()
  reportObserver = null
  await nextTick()
  if (!reportArticleRef.value) return
  enhanceRenderedReport()
  reportObserver = new MutationObserver(enhanceRenderedReport)
  reportObserver.observe(reportArticleRef.value, { childList: true, subtree: true })
}

const jumpToHeading = (index) => {
  const node = reportArticleRef.value?.querySelectorAll(
    '.report-markdown h1, .report-markdown h2, .report-markdown h3, .report-markdown h4'
  )[index]
  tocOpen.value = false
  node?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const handleDocumentPointerDown = (event) => {
  if (tocOpen.value && !tocRef.value?.contains(event.target)) tocOpen.value = false
}

const handleDocumentKeydown = (event) => {
  if (event.key === 'Escape') tocOpen.value = false
}

const handleOnline = () => {
  online.value = true
  syncWarning.value = ''
  if (pageActive) void refreshNow({ quiet: true })
}

const handleOffline = () => {
  online.value = false
  syncWarning.value = '网络已断开，恢复连接后将自动继续同步'
}

const handleVisibility = () => {
  if (document.visibilityState === 'visible' && pageActive) void refreshNow({ quiet: true })
}

watch(
  () => route.query.run,
  async (value) => {
    const nextRunId = String(value || '')
    if (!nextRunId || nextRunId === selectedRunId.value) return
    selectedRunId.value = nextRunId
    await hydrateMissingRun(nextRunId)
    await readSelectedArtifacts({ reset: true })
  }
)

watch(displayedReport, () => void connectReportObserver(), { flush: 'post' })

onMounted(async () => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeydown)
  document.addEventListener('visibilitychange', handleVisibility)
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)
  window.addEventListener('beforeprint', enablePrintMode)
  window.addEventListener('afterprint', disablePrintMode)
  await load({ resetArtifacts: true })
  startPolling()
})

onActivated(() => {
  pageActive = true
  startPolling()
  if (pageReady.value) void refreshNow({ quiet: true })
})

onDeactivated(() => {
  pageActive = false
  tocOpen.value = false
  stopPolling()
  disablePrintMode()
})

onUnmounted(() => {
  pageActive = false
  artifactRequestToken += 1
  stopPolling()
  reportObserver?.disconnect()
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeydown)
  document.removeEventListener('visibilitychange', handleVisibility)
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
  window.removeEventListener('beforeprint', enablePrintMode)
  window.removeEventListener('afterprint', disablePrintMode)
  disablePrintMode()
})
</script>

<template>
  <main class="reports-page">
    <section class="page-title">
      <div>
        <span>交互中心</span>
        <h1>研究报告</h1>
        <p>直接选择研究任务，连续查看交互、证据、S Agent、能力画像、深研对话和研究报告。</p>
      </div>
    </section>

    <nav class="workspace-stage-nav" aria-label="当前任务产物导航">
      <div class="workspace-stage-nav-inner">
        <button type="button" @click="router.push('/equipment/runs')">
          <Archive :size="15" />研究任务
        </button>
        <section class="workspace-artifact-card" aria-label="当前任务产物导航">
          <span>当前任务产物</span>
          <div>
            <button
              type="button"
              :disabled="!selectedRun"
              @click="navigateArtifact('/equipment/capabilities')"
            >
              <FlaskConical :size="15" />能力图像
            </button>
            <button
              type="button"
              :disabled="!selectedRun"
              @click="navigateArtifact('/equipment/deep-thinking')"
            >
              <MessageSquare :size="15" />深研对话
            </button>
            <button type="button" class="active" :disabled="!selectedRun" aria-current="page">
              <FileCheck2 :size="15" />研究报告
            </button>
          </div>
        </section>
      </div>
    </nav>

    <div class="task-review-workspace" :class="{ 'has-selected-task': selectedRun }">
      <section class="task-review-rail">
        <div class="task-review-picker">
          <header>
            <div>
              <ListFilter :size="17" />
              <span>
                <b>研究任务</b>
                <small>{{ visibleRuns.length }} / {{ availableRuns.length }}</small>
              </span>
            </div>
          </header>
          <div class="task-review-filters">
            <div class="searchbox">
              <Search :size="15" />
              <input v-model="taskQuery" aria-label="搜索研究任务" placeholder="搜索任务或运行 ID" />
            </div>
            <select v-model="taskStatus" aria-label="筛选研究任务状态">
              <option value="all">全部状态</option>
              <option value="active">进行中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
              <option value="draft">草稿</option>
              <option value="paused">已暂停</option>
            </select>
          </div>
          <div class="task-review-list">
            <div v-if="pageLoading && !availableRuns.length" class="task-row-skeletons" aria-hidden="true">
              <div v-for="index in 5" :key="index" class="task-row-skeleton">
                <span class="skeleton-line wide" /><span class="skeleton-line" />
              </div>
            </div>
            <template v-else>
              <button
                v-for="item in visibleRuns"
                :key="item.run_id"
                type="button"
                :class="{ selected: selectedRunId === String(item.run_id) }"
                @click="chooseRun(item)"
              >
                <span>
                  <b>{{ item.topic || '未命名研究任务' }}</b>
                  <small>{{ item.run_id }}</small>
                </span>
                <div>
                  <span class="status" :class="item.status">{{ runStatusLabel(item.status) }}</span>
                  <em>{{ routeLabel(item.research_route) }}</em>
                </div>
              </button>
            </template>
            <div
              v-if="!pageLoading && resourceLoaded.runs && !visibleRuns.length"
              class="empty task-list-empty"
            >
              当前已加载任务中没有匹配结果
            </div>
          </div>
        </div>
      </section>

      <section ref="contentRef" class="task-review-content reports">
        <header v-if="selectedRun" class="task-review-context">
          <div>
            <span>当前研究报告</span>
            <b>{{ selectedRun.topic }}</b>
            <small>
              {{ selectedRun.run_id }} · {{ routeLabel(selectedRun.research_route) }} ·
              {{ runStatusLabel(selectedRun.status) }}
            </small>
          </div>
          <span class="status" :class="selectedRun.status">
            {{ runStatusLabel(selectedRun.status) }}
          </span>
        </header>

        <div v-if="!online || syncWarning" class="report-connectivity" :class="{ offline: !online }">
          <WifiOff v-if="!online" :size="15" />
          <CircleAlert v-else :size="15" />
          <span>
            <b>{{ online ? '同步暂时中断' : '当前处于离线状态' }}</b>
            <small>{{ syncWarning || '恢复连接后将自动继续读取报告和运行事件。' }}</small>
          </span>
          <button v-if="online" type="button" @click="refreshNow()">
            <RefreshCw :size="13" />重试
          </button>
        </div>

        <section v-if="displayedReport" class="report-view enhanced">
          <div class="report-view-header">
            <span><FileCheck2 :size="18" /><b>研究报告</b></span>
            <em :title="selectedReportMeta?.artifact_relpath || selectedRun?.artifact_relpath">
              {{ selectedRun?.topic }}
            </em>
            <div class="report-view-actions">
              <div v-if="headings.length > 1" ref="tocRef" class="report-toc">
                <button
                  type="button"
                  title="报告目录"
                  :aria-expanded="tocOpen"
                  @click="tocOpen = !tocOpen"
                >
                  <AlignLeft :size="14" />目录
                  <ChevronDown :size="13" :class="{ flip: tocOpen }" />
                </button>
                <div v-if="tocOpen" class="report-toc-menu">
                  <button
                    v-for="item in headings"
                    :key="`${item.index}-${item.label}`"
                    type="button"
                    :class="`toc-level-${item.level}`"
                    @click="jumpToHeading(item.index)"
                  >
                    {{ item.label }}
                  </button>
                </div>
              </div>
              <button type="button" title="复制报告 Markdown" @click="copyReport">
                <Copy :size="14" />复制 Markdown
              </button>
              <button type="button" title="下载为 Markdown 文件" @click="downloadReport">
                <Download :size="14" />下载 .md
              </button>
              <button type="button" title="打印报告或另存为 PDF" @click="printReport">
                <Printer :size="14" />打印
              </button>
            </div>
          </div>
          <article ref="reportArticleRef" class="report-document">
            <MarkdownPreview :content="displayedReport" class="report-markdown" />
          </article>
        </section>

        <section v-else-if="showFailure" class="report-view enhanced report-failure-view">
          <div class="report-view-header">
            <span><CircleAlert :size="18" /><b>报告生成失败</b></span>
            <span class="status failed">失败</span>
          </div>
          <article class="empty report-failure-state">
            <CircleAlert :size="22" />
            <section>
              <b>未使用确定性降级模板</b>
              <p>{{ failureDetail }}</p>
              <button
                v-if="selectedRun?.status === 'failed' && !selectedRun?.readonly"
                type="button"
                class="primary"
                :disabled="resumingReport"
                @click="resumeReport"
              >
                <RefreshCw :size="14" :class="{ spin: resumingReport }" />
                {{ resumingReport ? '正在恢复' : '从检查点继续生成' }}
              </button>
              <p v-if="reportResumeError" class="form-error">{{ reportResumeError }}</p>
            </section>
          </article>
          <section v-if="selectedCapabilities.length" class="report-failure-capabilities">
            <div class="report-subsection-heading">
              <span><FlaskConical :size="18" /><b>已完成的能力画像</b></span>
              <em>报告正文暂不可读，先展示已完成的能力画像</em>
            </div>
            <EquipmentReportCapabilityCards
              :rows="selectedCapabilities"
              :run-id="selectedRunId"
            />
          </section>
        </section>

        <section
          v-else-if="selectedCapabilities.length"
          class="report-view enhanced report-early-view"
        >
          <div class="report-view-header">
            <span><FileCheck2 :size="18" /><b>研究报告</b></span>
            <em>{{ earlyCapabilityLabel }}</em>
          </div>
          <EquipmentReportCapabilityCards
            :rows="selectedCapabilities"
            :run-id="selectedRunId"
          />
        </section>

        <section
          v-else-if="artifactsLoading || eventsLoading || awaitingReport"
          class="report-view enhanced report-waiting-view"
        >
          <div class="report-view-header">
            <span><FileCheck2 :size="18" /><b>研究报告</b></span>
            <em>{{ lifecycle.progressText }}</em>
          </div>
          <article class="report-waiting-state">
            <span class="report-waiting-icon"><RefreshCw class="spin" :size="20" /></span>
            <div>
              <b>
                {{
                  selectedRun?.status === 'reporting' || lifecycle.started
                    ? '正在生成研究报告'
                    : '研究任务仍在推进'
                }}
              </b>
              <p>{{ lifecycle.progressText }}。正文或能力画像落盘后，本页会自动更新。</p>
            </div>
            <div class="report-skeleton" aria-hidden="true">
              <span /><span /><span /><span /><span />
            </div>
          </article>
        </section>

        <article v-else class="empty report-empty-state">
          <FileCheck2 :size="23" />
          <b>{{ emptyDescription }}</b>
          <button
            v-if="selectedRun && online"
            type="button"
            :disabled="loadingResources"
            @click="refreshNow()"
          >
            <RefreshCw :size="14" :class="{ spin: loadingResources }" />刷新
          </button>
        </article>
      </section>
    </div>
  </main>
</template>

<style scoped>
.reports-page {
  display: grid;
  min-height: 100%;
  gap: 16px;
  box-sizing: border-box;
  padding: 28px 32px 40px;
  background:
    radial-gradient(circle at 78% -12%, rgb(105 102 243 / 11%), transparent 32%),
    #f5f7fb;
  color: #29344d;
}

.page-title { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.page-title > div > span { color: #5653d2; font-size: 10px; font-weight: 800; letter-spacing: .14em; }
.page-title h1, .page-title p { margin: 0; }
.page-title h1 { margin-top: 5px; color: #263149; font-size: 25px; }
.page-title p { margin-top: 5px; color: #778297; font-size: 11px; }
.reports-page > .workspace-stage-nav {
  position: sticky;
  top: 0;
  z-index: 40;
  align-self: start;
  margin-top: -10px;
  background: #fff;
  box-shadow: 0 8px 22px rgb(39 53 82 / 10%);
}
.workspace-stage-nav button, .report-view button, .report-connectivity button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; cursor: pointer; }
.workspace-stage-nav button:disabled, .report-view button:disabled, .report-connectivity button:disabled { cursor: not-allowed; opacity: .55; }
.task-review-rail { top: 72px; }
.task-review-filters .searchbox { display: flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 9px; }
.task-review-filters .searchbox svg { flex: 0 0 auto; color: #8792a5; }
.task-review-filters input { height: 32px; border: 0; outline: 0; background: transparent; color: #3b485f; font: inherit; }
.task-review-list > button { background: #fff; }
.task-list-empty { display: grid; min-height: 130px; place-items: center; padding: 18px; color: #8590a3; font-size: 11px; line-height: 1.6; }
.task-row-skeletons { display: grid; gap: 6px; }
.task-row-skeleton { min-height: 76px; }
.skeleton-line { display: block; width: 55%; height: 8px; border-radius: 99px; background: linear-gradient(90deg,#edf0f5 20%,#f8f9fb 45%,#edf0f5 70%); background-size: 220% 100%; animation: report-skeleton 1.4s linear infinite; }
.skeleton-line.wide { width: 82%; }
.task-review-content.reports { min-width: 0; }
.task-review-context > .status { flex: 0 0 auto; font-size: 10px; }

.report-connectivity { display: flex; align-items: center; gap: 9px; padding: 9px 14px; border-bottom: 1px solid #eadfbd; background: #fffaf0; color: #946d28; }
.report-connectivity.offline { border-color: #edcbd0; background: #fff5f6; color: #a94c58; }
.report-connectivity > span { display: grid; min-width: 0; gap: 2px; }
.report-connectivity b { font-size: 11px; }
.report-connectivity small { overflow: hidden; color: #7d725d; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.report-connectivity button { flex: 0 0 auto; min-height: 28px; margin-left: auto; padding: 0 9px; border: 1px solid #dbc99d; border-radius: 6px; background: #fff; color: #7d622b; font-size: 10px; }

.report-view.enhanced { width: 100%; min-width: 0; overflow: hidden; border: 0; border-radius: 0; background: #fff; box-shadow: none; }
.report-view.enhanced > .report-view-header, .report-subsection-heading { position: sticky; top: 0; z-index: 3; display: flex; min-height: 50px; box-sizing: border-box; align-items: center; justify-content: space-between; gap: 12px; padding: 0 clamp(18px,3vw,34px); border-bottom: 1px solid #e8ebf2; background: rgb(255 255 255 / 94%); backdrop-filter: blur(10px); }
.report-view.enhanced > .report-view-header > span:first-child, .report-subsection-heading > span { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; color: #5269d5; white-space: nowrap; }
.report-view.enhanced > .report-view-header > em, .report-subsection-heading > em { flex: 0 1 auto; min-width: 0; max-width: 38%; margin-right: auto; overflow: hidden; color: #7d889b; font-size: 10px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.report-view-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }
.report-view-actions button, .report-toc > button { height: 30px; padding: 0 9px; border: 1px solid #dce2ed; border-radius: 6px; background: #fff; color: #5c687d; font-size: 11px; white-space: nowrap; }
.report-view-actions button:hover { border-color: #aaa9ea; background: #f7f7ff; color: #4d4ac5; }
.report-toc { position: relative; }
.report-toc > button svg.flip { transform: rotate(180deg); }
.report-toc-menu { position: absolute; z-index: 30; top: calc(100% + 8px); left: 0; display: grid; width: min(430px,calc(100vw - 60px)); max-height: 340px; gap: 2px; overflow: auto; padding: 8px; border: 1px solid #dde2ec; border-radius: 9px; background: #fff; box-shadow: 0 18px 48px rgb(32 44 75 / 16%); }
.report-toc-menu > button { display: block; width: 100%; height: auto; min-height: 30px; padding: 6px 9px; border: 0; background: transparent; color: #536078; line-height: 1.5; text-align: left; white-space: normal; }
.report-toc-menu > button.toc-level-1 { color: #29364e; font-weight: 700; }
.report-toc-menu > button.toc-level-3 { padding-left: 22px; color: #778398; font-size: 11px; }
.report-toc-menu > button.toc-level-4 { padding-left: 34px; color: #8490a2; font-size: 11px; }
.report-document { min-width: 0; }

.report-document :deep(.report-markdown) { width: 100%; max-height: calc(100vh - 260px); box-sizing: border-box; overflow: auto; padding: 30px clamp(22px,4vw,52px) 48px; color: #35435a; font-size: 14px; line-height: 1.85; overflow-wrap: break-word; }
.report-document :deep(.report-markdown > :first-child) { margin-top: 0; }
.report-document :deep(.report-markdown > :last-child) { margin-bottom: 0; }
.report-document :deep(.report-markdown h1), .report-document :deep(.report-markdown h2), .report-document :deep(.report-markdown h3), .report-document :deep(.report-markdown h4) { color: #1f2e47; line-height: 1.4; scroll-margin-top: 20px; }
.report-document :deep(.report-markdown h1) { margin: 0 0 26px; font-size: 25px; letter-spacing: -.3px; }
.report-document :deep(.report-markdown h2) { margin: 34px 0 16px; padding-bottom: 9px; border-bottom: 1px solid #e3e8f1; font-size: 19px; }
.report-document :deep(.report-markdown h3) { margin: 26px 0 12px; font-size: 16px; }
.report-document :deep(.report-markdown h4) { margin: 28px 0 12px; padding: 10px 12px; border: 1px solid #e4e9f3; border-radius: 8px; background: linear-gradient(180deg,#f7f9fd,#f3f6fb); color: #2a3b58; font-size: 15px; font-weight: 750; }
.report-document :deep(.report-markdown p) { margin: 0 0 15px; }
.report-document :deep(.report-markdown strong) { color: #243653; font-weight: 750; }
.report-document :deep(.report-markdown ul), .report-document :deep(.report-markdown ol) { margin: 8px 0 18px; padding-left: 1.65em; }
.report-document :deep(.report-markdown li) { margin: 7px 0; padding-left: 3px; }
.report-document :deep(.report-markdown li::marker) { color: #6361cd; font-weight: 700; }
.report-document :deep(.report-markdown blockquote) { margin: 18px 0; padding: 12px 16px; border-left: 3px solid #6e6cd5; border-radius: 0 6px 6px 0; background: #f5f7fd; color: #526078; }
.report-document :deep(.report-markdown a) { color: #4c49cb; text-decoration: underline; text-decoration-color: #b4c0ed; text-underline-offset: 3px; }
.report-document :deep(.report-markdown .report-table-scroll) { display: block; width: 100%; max-width: 100%; margin: 20px 0 24px; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.report-document :deep(.report-markdown .report-table-scroll > table), .report-document :deep(.report-markdown table) { display: table; width: 100%; min-width: 0; max-width: 100%; margin: 0; border-collapse: collapse; table-layout: fixed; font-size: 13px; line-height: 1.7; }
.report-document :deep(.report-markdown th), .report-document :deep(.report-markdown td) { min-width: 0; padding: 10px 12px; border: 1px solid #dfe5ee; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; white-space: normal; }
.report-document :deep(.report-markdown th) { background: #f3f6fb; color: #30405c; font-weight: 700; }
.report-document :deep(.report-markdown tr:nth-child(even) td) { background: #fafbfd; }

.report-failure-state, .report-empty-state { display: flex; min-height: 300px; box-sizing: border-box; align-items: center; justify-content: center; gap: 12px; padding: 28px; color: #78859a; text-align: center; }
.report-failure-state p { margin: 0; color: #68758b; font-size: 11px; }
.report-failure-state button.primary { min-height: 32px; padding: 0 12px; border: 1px solid #5653d2; border-radius: 6px; background: #5653d2; color: #fff; font-size: 11px; }
.report-failure-state .form-error { color: #ad4652; }
.report-failure-capabilities { border-top: 1px solid #e7ebf2; }
.report-subsection-heading { position: static; }
.report-waiting-state { display: grid; grid-template-columns: auto 1fr; gap: 13px; min-height: 320px; align-content: center; padding: 30px clamp(22px,4vw,52px) 44px; }
.report-waiting-icon { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 12px; background: #eeefff; color: #5a57cd; }
.report-waiting-state > div:nth-child(2) { display: grid; gap: 6px; align-content: center; }
.report-waiting-state b { color: #344158; font-size: 13px; }
.report-waiting-state p { margin: 0; color: #738096; font-size: 11px; line-height: 1.65; }
.report-skeleton { grid-column: 1 / -1; display: grid; gap: 11px; margin-top: 20px; }
.report-skeleton span { height: 10px; border-radius: 99px; background: linear-gradient(90deg,#edf0f6 20%,#fafbfc 45%,#edf0f6 70%); background-size: 220% 100%; animation: report-skeleton 1.4s linear infinite; }
.report-skeleton span:nth-child(2), .report-skeleton span:nth-child(5) { width: 74%; }
.report-empty-state { flex-direction: column; min-height: 440px; }
.report-empty-state button { min-height: 31px; padding: 0 10px; border: 1px solid #d7deeb; border-radius: 6px; background: #fff; color: #5755bf; font-size: 11px; }
.spin { animation: report-spin 1s linear infinite; }
@keyframes report-spin { to { transform: rotate(360deg); } }
@keyframes report-skeleton { to { background-position: -220% 0; } }

@media (max-width: 1180px) {
  .report-view.enhanced > .report-view-header { min-height: 0; flex-wrap: wrap; padding: 12px 18px; row-gap: 9px; }
  .report-view.enhanced > .report-view-header > em { max-width: calc(100% - 130px); margin-right: 0; }
  .report-view-actions { width: 100%; flex-wrap: wrap; }
}

@media (max-width: 900px) {
  .reports-page { padding: 18px 16px 32px; }
  .task-review-workspace { grid-template-columns: 1fr; }
  .task-review-rail { position: static; }
  .task-review-workspace.has-selected-task .task-review-list { max-height: 190px; }
}

@media (max-width: 560px) {
  .reports-page { gap: 14px; padding: 14px 12px 84px; }
  .page-title h1 { font-size: 23px; }
  .page-title p { line-height: 1.55; }
  .workspace-stage-nav { margin-top: -4px; }
  .workspace-artifact-card { flex: 0 0 auto; flex-direction: row; padding: 0; border: 0; }
  .workspace-artifact-card > span { display: none; }
  .workspace-artifact-card > div { flex-wrap: nowrap; }
  .task-review-context { align-items: flex-start; }
  .task-review-context small { overflow-wrap: anywhere; }
  .report-connectivity { align-items: flex-start; }
  .report-connectivity small { white-space: normal; }
  .report-view.enhanced > .report-view-header { padding-right: 12px; padding-left: 12px; }
  .report-view.enhanced > .report-view-header > em { max-width: calc(100% - 124px); }
  .report-view-actions { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); }
  .report-view-actions > .report-toc { grid-column: 1 / -1; }
  .report-view-actions > .report-toc > button { width: 100%; }
  .report-view-actions > button { min-width: 0; padding: 0 6px; }
  .report-document :deep(.report-markdown) { max-height: calc(100vh - 260px); padding: 22px 20px 36px; font-size: 13px; line-height: 1.8; }
  .report-document :deep(.report-markdown h1) { font-size: 20px; }
  .report-document :deep(.report-markdown h2) { margin-top: 28px; font-size: 17px; }
  .report-waiting-state { grid-template-columns: 1fr; padding: 24px 20px 34px; }
  .report-skeleton { grid-column: 1; }
}
</style>

<style>
.dark .reports-page { background: radial-gradient(circle at 78% -12%,rgb(103 99 225 / 12%),transparent 34%),#14171d; color: #dfe4ed; }
.dark .reports-page .page-title h1, .dark .reports-page .task-review-context b, .dark .reports-page .task-review-list button > span b, .dark .reports-page .report-waiting-state b { color: #e5e9f1; }
.dark .reports-page .workspace-stage-nav, .dark .reports-page .workspace-stage-nav-inner, .dark .reports-page .workspace-artifact-card, .dark .reports-page .task-review-rail, .dark .reports-page .task-review-content, .dark .reports-page .task-review-list > button, .dark .reports-page .report-view.enhanced, .dark .reports-page .report-view.enhanced > .report-view-header, .dark .reports-page .report-view-actions button, .dark .reports-page .report-toc-menu, .dark .reports-page .report-empty-state button { border-color: #343a47; background: #1e222a; color: #c4cbd8; }
.dark .reports-page .task-review-rail > div > header, .dark .reports-page .task-review-context, .dark .reports-page .task-review-filters { border-color: #343a47; background: linear-gradient(135deg,#22262f,#1d2129); }
.dark .reports-page .task-review-list > button.selected { border-color: #716ee0; background: #292c42; }
.dark .reports-page .task-review-filters .searchbox, .dark .reports-page .task-review-filters select { border-color: #3a414f; background: #191d24; color: #d1d7e1; }
.dark .reports-page .report-document .report-markdown, .dark .reports-page .report-document .report-markdown h1, .dark .reports-page .report-document .report-markdown h2, .dark .reports-page .report-document .report-markdown h3, .dark .reports-page .report-document .report-markdown h4, .dark .reports-page .report-document .report-markdown strong { color: #dce2ed; }
.dark .reports-page .report-document .report-markdown h2, .dark .reports-page .report-document .report-markdown th, .dark .reports-page .report-document .report-markdown td { border-color: #3a414f; }
.dark .reports-page .report-document .report-markdown h4, .dark .reports-page .report-document .report-markdown th, .dark .reports-page .report-document .report-markdown tr:nth-child(even) td, .dark .reports-page .report-document .report-markdown blockquote { background: #242935; color: #cbd3df; }

@media print {
  @page { margin: 16mm 14mm; }
  body.equipment-report-printing, body.equipment-report-printing #app, body.equipment-report-printing .app-layout, body.equipment-report-printing #app-router-view { width: 100% !important; height: auto !important; min-height: 0 !important; overflow: visible !important; background: #fff !important; }
  body.equipment-report-printing .app-layout > .header, body.equipment-report-printing .mobile-topbar, body.equipment-report-printing .reports-page > .page-title, body.equipment-report-printing .reports-page > .workspace-stage-nav, body.equipment-report-printing .reports-page .task-review-rail, body.equipment-report-printing .reports-page .task-review-context, body.equipment-report-printing .reports-page .report-connectivity, body.equipment-report-printing .reports-page .report-view-header, body.equipment-report-printing .reports-page .report-view-actions { display: none !important; }
  body.equipment-report-printing .reports-page { display: block !important; min-height: 0 !important; padding: 0 !important; background: #fff !important; }
  body.equipment-report-printing .task-review-workspace, body.equipment-report-printing .task-review-content, body.equipment-report-printing .report-view, body.equipment-report-printing .report-document, body.equipment-report-printing .report-markdown { display: block !important; width: 100% !important; max-width: none !important; max-height: none !important; overflow: visible !important; border: 0 !important; box-shadow: none !important; }
  body.equipment-report-printing .report-markdown { padding: 0 !important; color: #182438 !important; font-size: 12pt !important; line-height: 1.75 !important; }
  body.equipment-report-printing .report-markdown > h1:first-child { margin: 0 0 18mm !important; text-align: center; font-size: 24pt !important; line-height: 1.35 !important; }
  body.equipment-report-printing .report-markdown h1, body.equipment-report-printing .report-markdown h2, body.equipment-report-printing .report-markdown h3, body.equipment-report-printing .report-markdown h4 { break-after: avoid; }
  body.equipment-report-printing .report-markdown .report-table-scroll { display: block !important; width: 100% !important; overflow: visible !important; }
  body.equipment-report-printing .report-markdown table { display: table !important; width: 100% !important; min-width: 0 !important; max-width: 100% !important; table-layout: fixed !important; overflow: visible !important; font-size: 10.5pt !important; line-height: 1.45 !important; }
  body.equipment-report-printing .report-markdown thead { display: table-header-group !important; }
  body.equipment-report-printing .report-markdown tr, body.equipment-report-printing .report-markdown pre, body.equipment-report-printing .report-markdown blockquote, body.equipment-report-printing .report-markdown li { break-inside: avoid; }
  body.equipment-report-printing .report-markdown th, body.equipment-report-printing .report-markdown td { min-width: 0 !important; width: auto !important; padding: 6pt 5pt !important; overflow-wrap: anywhere !important; word-break: break-word !important; }
  body.equipment-report-printing .report-markdown a { color: inherit !important; text-decoration: none !important; }
}
</style>
