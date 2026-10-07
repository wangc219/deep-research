<script setup>
import { computed, nextTick, onActivated, onDeactivated, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { Modal, message } from 'ant-design-vue'
import {
  Archive,
  ArrowLeft,
  BookOpenCheck,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Database,
  ExternalLink,
  Eye,
  FilePlus2,
  Lightbulb,
  Link2,
  LoaderCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Sparkles,
  Trash2,
  WandSparkles,
  X
} from '@lucide/vue'

import { equipmentApi } from '@/apis/equipment_api'
import { createIdempotencyKey } from '@/apis/base'
import { databaseApi } from '@/apis/knowledge_api'
import EquipmentQueryKnowledgeScope from '@/components/equipment/EquipmentQueryKnowledgeScope.vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { useEquipmentModelPrefill } from '@/composables/useEquipmentModelPrefill'
import { useProjectsStore } from '@/stores/projects'
import { useUserStore } from '@/stores/user'
import { projectDisplayName } from '@/utils/projectSelection'
import {
  GENERATION_STAGE_LABELS,
  QUERY_SOURCE_LABELS,
  QUERY_STATUS_LABELS,
  buildDivergenceExamplePatch,
  buildResearchRunPayload,
  createKnowledgeScope,
  indexQueriesById,
  knowledgeScopeSummary,
  normalizeAccessibleKnowledgeBases,
  normalizePagedResult,
  parseReferenceUrls,
  queryLineageModelSpec,
  selectLeastUsedDiscoveryAngle,
  validateReferenceUrls
} from '@/utils/equipmentQueries'

const DIVERGENCE_EXAMPLES = [
  {
    label: '天基赋能地面导弹',
    topic: '天基平台与地面导弹平台协同赋能运用',
    angle: '以天基与地面导弹平台相互赋能为主线，牵引双方装备和体系发展。',
    demand: '分析当前与未来协同态势、主要协同方式、作战效能提升，以及地面作战中可由天基能力解决的单装与体系痛点。',
    technology: '分析天基资源能力与规划、天地通信技术途径和水平、天基能力向地面装备映射，以及融合后对导弹能力建设方向的影响。'
  },
  {
    label: '海上无人导弹融合',
    topic: '海上无人平台与导弹融合的新型作战模式',
    angle: '探索面向远海任务的无人平台与导弹或导弹投送融合模式，牵引无人装备与作战体系发展。',
    demand: '分析主要海上作战场景、对手装备与威胁形式、侦控抗打等应对模式，以及远海作战难点痛点。',
    technology: '分析海上无人装备与远海应用技术的发展现状和趋势，识别能够解决关键难点的装备技术组合。'
  },
  {
    label: '社会化资源引战',
    topic: '社会化资源引入作战与国防工业体系发展',
    angle: '从现代战争形态变化出发，研究社会化力量和资源进入作战体系的新模式。',
    demand: '总结现代战争对国防工业体系的冲击、社会化资源参战案例与价值，研判未来模式及其可解决的能力痛点。',
    technology: '分析装备、信息科学、人工智能及其他工业技术如何赋能作战，并拓展认知与心理等非动能维度。'
  }
]

const AUTONOMOUS_DISCOVERY_ANGLES = [
  '东海、台海与第一岛链海空态势',
  '南海岛礁、海上通道与远海保障态势',
  '西太平洋第二岛链与远程机动投送态势',
  '中印边境、高原山地与极端环境任务态势',
  '朝鲜半岛、东北亚防空反导与预警态势',
  '中亚与西部边境反无人及非传统安全态势',
  '周边低空无人集群与要地防护态势',
  '邻国远程火力、导弹防御与体系对抗态势',
  '海上封锁、岛链通道与分布式火力态势',
  '太空、网络与电磁支撑周边联合任务态势'
]

const router = useRouter()
const projectsStore = useProjectsStore()
const userStore = useUserStore()
const { projects } = storeToRefs(projectsStore)
const runProjectId = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const queries = ref([])
const generations = ref([])
const generationQueryRows = ref([])
const knowledgeBases = ref([])
const loading = ref(true)
const generationLoading = ref(true)
const knowledgeLoading = ref(true)
const knowledgeError = ref('')
const error = ref('')
const selectedId = ref('')
const selectedIds = ref([])
const search = ref('')
const status = ref('all')
const sourceType = ref('all')
const taskFilter = ref('all')
const taskSearch = ref('')
const collapsedGenerationIds = ref(new Set())
const busyGenerationIds = ref(new Set())
const referenceOpen = ref(false)
const manualOpen = ref(false)
const detailOpen = ref(false)
const mutating = ref(false)
const generating = ref(false)
const pollEnabled = ref(true)
let loadToken = 0
let pollTimer = null
let searchTimer = null

const generationForm = reactive({
  mode: 'guided',
  topic: '',
  expected_angle: '',
  demand_dimension: '',
  technology_dimension: '',
  supplemental_information: '',
  count: 8,
  model_spec: '',
  knowledge_enabled: true,
  knowledge_ids: [],
  reference_text: 'https://www.81.cn/'
})
const manualForm = reactive({
  query: '',
  supplemental_information: '',
  generation_rationale: '',
  knowledge_enabled: true,
  knowledge_ids: []
})
const { hasDefaultModel } = useEquipmentModelPrefill(generationForm)

const selected = computed(() => (
  queries.value.find((item) => item.query_id === selectedId.value)
  || generationQueryRows.value.find((item) => item.query_id === selectedId.value)
  || null
))
const selectedRows = computed(() => queries.value.filter((item) => selectedIds.value.includes(item.query_id)))
const allCurrentSelected = computed(() => queries.value.length > 0 && queries.value.every((item) => selectedIds.value.includes(item.query_id)))
const activeGenerations = computed(() => generations.value.filter((item) => ['queued', 'running'].includes(item.status)))
const generationCounts = computed(() => ({
  all: generations.value.length,
  running: activeGenerations.value.length,
  completed: generations.value.filter((item) => item.status === 'completed').length
}))
const visibleGenerations = computed(() => {
  const keyword = taskSearch.value.trim().toLowerCase()
  return generations.value.filter((item) => {
    const matchesFilter = taskFilter.value === 'all'
      || (taskFilter.value === 'running' && ['queued', 'running'].includes(item.status))
      || item.status === taskFilter.value
    const haystack = `${item.topic || ''} ${item.generation_id || ''} ${item.stage || ''}`.toLowerCase()
    return matchesFilter && (!keyword || haystack.includes(keyword))
  })
})
const queryById = computed(() => indexQueriesById(generationQueryRows.value, queries.value))
const metrics = computed(() => ({
  draft: queries.value.filter((item) => item.status === 'draft').length,
  published: queries.value.filter((item) => item.status === 'published').length,
  agent: queries.value.filter((item) => item.source_type === 'agent').length
}))
const formatDateTime = (value) => {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  }).format(date)
}

const displaySourceTitle = (title) => String(title || '').replace(/^本地语义生成\s*[:：]?\s*/, '态势研判：')

const applyDivergenceExample = (example) => {
  Object.assign(generationForm, buildDivergenceExamplePatch(example))
}

const selectAutonomousDiscoveryAngle = () => (
  selectLeastUsedDiscoveryAngle(AUTONOMOUS_DISCOVERY_ANGLES, generations.value)
  || AUTONOMOUS_DISCOVERY_ANGLES[0]
)

const setGenerationMode = (mode) => {
  generationForm.mode = mode
}

const openManualForm = () => {
  manualForm.knowledge_enabled = generationForm.knowledge_enabled
  manualForm.knowledge_ids = [...generationForm.knowledge_ids]
  manualOpen.value = true
}

const onQueryCardKeydown = (event, item) => {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  openDetail(item)
}

const setError = (reason, fallback) => {
  error.value = reason?.message || fallback
}

const confirmAction = (title, content, okText = '确认') => new Promise((resolve) => {
  Modal.confirm({
    title,
    content,
    okText,
    cancelText: '取消',
    okButtonProps: okText.includes('删除') ? { danger: true } : {},
    onOk: () => resolve(true),
    onCancel: () => resolve(false)
  })
})

const loadQueries = async ({ preserveSelection = true } = {}) => {
  const token = ++loadToken
  loading.value = true
  try {
    const payload = await equipmentApi.listQueries({
      search: search.value.trim() || undefined,
      status: status.value === 'all' ? undefined : status.value,
      source_type: sourceType.value === 'all' ? undefined : sourceType.value,
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value
    })
    if (token !== loadToken) return
    const result = normalizePagedResult(payload, pageSize.value)
    queries.value = result.items
    total.value = result.total
    if (!preserveSelection) selectedIds.value = []
    if (
      !queries.value.some((item) => item.query_id === selectedId.value)
      && !generationQueryRows.value.some((item) => item.query_id === selectedId.value)
    ) {
      selectedId.value = queries.value[0]?.query_id || ''
    }
    error.value = ''
  } catch (reason) {
    if (token === loadToken) setError(reason, 'Query 库读取失败')
  } finally {
    if (token === loadToken) loading.value = false
  }
}

const loadGenerations = async () => {
  generationLoading.value = true
  const [generationResult, queryResult] = await Promise.allSettled([
    equipmentApi.listQueryGenerations({ limit: 20 }),
    equipmentApi.listQueries({ limit: 200, offset: 0 })
  ])
  if (generationResult.status === 'fulfilled') {
    generations.value = normalizePagedResult(generationResult.value, 20).items
  } else {
    setError(generationResult.reason, 'Query 生成任务读取失败')
  }
  if (queryResult.status === 'fulfilled') {
    generationQueryRows.value = normalizePagedResult(queryResult.value, 200).items
  } else {
    message.warning('生成结果索引同步失败，任务历史仍可正常查看')
  }
  generationLoading.value = false
}

const loadKnowledgeBases = async () => {
  knowledgeLoading.value = true
  knowledgeError.value = ''
  try {
    knowledgeBases.value = normalizeAccessibleKnowledgeBases(await databaseApi.getAccessibleDatabases())
  } catch (reason) {
    knowledgeError.value = reason?.message || '知识库列表读取失败'
    message.warning(`${knowledgeError.value}，将保留默认范围`)
  } finally {
    knowledgeLoading.value = false
  }
}

const refresh = async () => {
  await Promise.all([loadQueries(), loadGenerations()])
}

const pollGenerations = async () => {
  if (!pollEnabled.value || document.visibilityState === 'hidden') return
  const active = activeGenerations.value
  if (!active.length) return
  try {
    const updates = await Promise.all(active.map((item) => equipmentApi.getQueryGeneration(item.generation_id)))
    const previous = new Map(generations.value.map((item) => [item.generation_id, item.status]))
    const updateMap = new Map(updates.map((item) => [item.generation_id, item]))
    generations.value = generations.value.map((item) => updateMap.get(item.generation_id) || item)
    if (updates.some((item) => item.status === 'completed' && previous.get(item.generation_id) !== 'completed')) {
      page.value = 1
      status.value = 'draft'
      sourceType.value = 'agent'
      await loadQueries({ preserveSelection: false })
    }
  } catch (reason) {
    setError(reason, '生成状态同步失败，稍后会继续重试')
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollEnabled.value = true
  pollTimer = setInterval(pollGenerations, 1800)
}
const stopPolling = () => {
  pollEnabled.value = false
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

const buildGenerationContext = (autonomousAngle = '') => {
  if (generationForm.mode === 'autonomous') {
    return [
      '自动态势发散模式。',
      autonomousAngle && `本次轮换视角：${autonomousAngle}。`,
      generationForm.supplemental_information.trim()
        ? `用户补充偏好：${generationForm.supplemental_information.trim()}`
        : '优先检索该视角下最新、权威的公开态势信号。',
      '因果链：外部态势→任务压力→作战缺口→武器装备能力与发展需求。',
      '发散框架：同时覆盖需求牵引、技术驱动、体系实战、颠覆逻辑与规模建设。'
    ].filter(Boolean).join('\n')
  }
  return [
    generationForm.expected_angle.trim() && `预期角度：${generationForm.expected_angle.trim()}`,
    generationForm.demand_dimension.trim() && `需求牵引维度：${generationForm.demand_dimension.trim()}`,
    generationForm.technology_dimension.trim() && `技术驱动维度：${generationForm.technology_dimension.trim()}`,
    generationForm.supplemental_information.trim() && `其他发散偏好：${generationForm.supplemental_information.trim()}`
  ].filter(Boolean).join('\n')
}

const submitGeneration = async () => {
  if (!runProjectId.value) {
    message.warning('请先选择 Query 所属项目')
    return
  }
  if (generationForm.mode === 'guided' && !generationForm.topic.trim()) {
    message.warning('请先输入希望发散的装备需求母题')
    return
  }
  const referenceUrls = parseReferenceUrls(generationForm.reference_text)
  const referenceError = validateReferenceUrls(referenceUrls)
  if (referenceError) {
    message.warning(referenceError)
    return
  }
  generating.value = true
  error.value = ''
  const idempotencyKey = createIdempotencyKey('query-generation')
  try {
    const autonomousAngle = generationForm.mode === 'autonomous' ? selectAutonomousDiscoveryAngle() : ''
    const created = await equipmentApi.generateQueries({
      project_id: runProjectId.value,
      topic: generationForm.mode === 'autonomous'
        ? `${autonomousAngle}：武器装备能力与发展需求研判`
        : generationForm.topic.trim(),
      supplemental_information: buildGenerationContext(autonomousAngle),
      reference_urls: referenceUrls,
      count: generationForm.count,
      model_spec: generationForm.model_spec.trim() || undefined,
      ...createKnowledgeScope(generationForm.knowledge_enabled, generationForm.knowledge_ids)
    }, { idempotencyKey })
    generations.value = [created, ...generations.value.filter((item) => item.generation_id !== created.generation_id)].slice(0, 20)
    message.success('Query 生成任务已进入后台执行')
    startPolling()
  } catch (reason) {
    setError(reason, '生成任务提交失败')
  } finally {
    generating.value = false
  }
}

const createManualQuery = async () => {
  if (!runProjectId.value) {
    message.warning('请先选择 Query 所属项目')
    return
  }
  if (!manualForm.query.trim()) {
    message.warning('请填写研究选题')
    return
  }
  mutating.value = true
  try {
    const created = await equipmentApi.createQuery({
      project_id: runProjectId.value,
      query: manualForm.query.trim(),
      supplemental_information: manualForm.supplemental_information.trim(),
      generation_rationale: manualForm.generation_rationale.trim(),
      ...createKnowledgeScope(manualForm.knowledge_enabled, manualForm.knowledge_ids)
    })
    Object.assign(manualForm, {
      query: '', supplemental_information: '', generation_rationale: '',
      knowledge_enabled: generationForm.knowledge_enabled,
      knowledge_ids: [...generationForm.knowledge_ids]
    })
    manualOpen.value = false
    page.value = 1
    status.value = 'all'
    sourceType.value = 'all'
    await loadQueries({ preserveSelection: false })
    selectedId.value = created.query_id
    message.success('Query 草稿已保存')
  } catch (reason) {
    setError(reason, 'Query 保存失败')
  } finally {
    mutating.value = false
  }
}

const publishOne = async (item, quiet = false) => {
  const published = await equipmentApi.publishQuery(item.query_id, item.version)
  if (!quiet) message.success('Query 已发布')
  return published
}

const mutateOne = async (action, item) => {
  mutating.value = true
  error.value = ''
  try {
    if (action === 'publish') await publishOne(item)
    if (action === 'archive') {
      if (!await confirmAction('归档 Query', '归档后不会出现在研究任务选择器中，历史版本仍会保留。', '归档')) return
      await equipmentApi.archiveQuery(item.query_id, item.version)
      message.success('Query 已归档')
    }
    if (action === 'delete') {
      if (!await confirmAction('永久删除 Query', `确定删除“${item.query}”吗？已创建的研究任务不会被删除。`, '永久删除')) return
      await equipmentApi.deleteQuery(item.query_id)
      selectedIds.value = selectedIds.value.filter((id) => id !== item.query_id)
      message.success('Query 已删除')
    }
    await Promise.all([loadQueries(), loadGenerations()])
  } catch (reason) {
    setError(reason, `${action === 'delete' ? '删除' : action === 'archive' ? '归档' : '发布'}失败`)
  } finally {
    mutating.value = false
  }
}

const bulkStatus = async (nextStatus) => {
  const targets = selectedRows.value.filter((item) => nextStatus !== 'published' || item.status === 'draft')
  if (!targets.length) return
  const label = nextStatus === 'published' ? '发布' : '归档'
  if (!await confirmAction(`批量${label} Query`, `将处理当前页选中的 ${targets.length} 条 Query。`, `确认${label}`)) return
  mutating.value = true
  try {
    await equipmentApi.bulkSetQueryStatus({
      query_ids: targets.map((item) => item.query_id),
      status: nextStatus,
      versions: Object.fromEntries(targets.map((item) => [item.query_id, item.version]))
    })
    selectedIds.value = []
    await loadQueries({ preserveSelection: false })
    message.success(`已批量${label} ${targets.length} 条 Query`)
  } catch (reason) {
    setError(reason, `批量${label}失败`)
  } finally {
    mutating.value = false
  }
}

const bulkDelete = async () => {
  const targets = [...selectedRows.value]
  if (!targets.length || !await confirmAction('批量永久删除 Query', `确定删除当前页选中的 ${targets.length} 条 Query 吗？`, '永久删除')) return
  mutating.value = true
  try {
    const results = await Promise.allSettled(targets.map((item) => equipmentApi.deleteQuery(item.query_id)))
    const failed = results.filter((item) => item.status === 'rejected').length
    selectedIds.value = []
    await Promise.all([loadQueries({ preserveSelection: false }), loadGenerations()])
    if (failed) message.warning(`${targets.length - failed} 条删除成功，${failed} 条失败`)
    else message.success(`已删除 ${targets.length} 条 Query`)
  } catch (reason) {
    setError(reason, '批量删除后的状态同步失败')
  } finally {
    mutating.value = false
  }
}

const createAndStartRun = async (query, batchId) => {
  if (!runProjectId.value) throw new Error('请先选择研究任务所属项目')
  const current = query.status === 'draft' ? await publishOne(query, true) : query
  const modelSpec = queryLineageModelSpec(current, generations.value, generationForm.model_spec)
  const requestId = batchId || createIdempotencyKey('query-research')
  const created = await equipmentApi.createResearchRun(
    buildResearchRunPayload(current, modelSpec),
    { idempotencyKey: `create:${requestId}:${current.query_id}`, projectId: runProjectId.value }
  )
  await equipmentApi.startResearchRun(created.run_id, {
    idempotencyKey: `start:${requestId}:${created.run_id}`
  })
  return created
}

const directResearch = async (item) => {
  if (!runProjectId.value) {
    message.warning('请先选择研究任务所属项目')
    return
  }
  if (!await confirmAction('启动研究任务', `系统将${item.status === 'draft' ? '先发布该 Query，并' : ''}创建、启动研究任务。`, '创建并启动')) return
  mutating.value = true
  error.value = ''
  try {
    const created = await createAndStartRun(item)
    message.success('研究任务已创建并启动')
    await router.push(`/equipment/runs/${encodeURIComponent(created.run_id)}`)
  } catch (reason) {
    setError(reason, '研究任务创建或启动失败')
  } finally {
    mutating.value = false
  }
}

const scheduleResearch = async (item) => {
  if (item.status !== 'published') {
    message.warning('请先审核发布该 Query，再设置定时研究')
    return
  }
  const projectId = item.project_id || runProjectId.value
  if (!projectId) {
    message.warning('请先选择研究任务所属项目')
    return
  }
  await router.push({
    path: '/agent-manage',
    query: {
      tab: 'schedules',
      target_type: 'equipment_research',
      project_id: projectId,
      source_query_id: item.query_id,
      source_query_version: item.version,
      topic: item.query,
      supplemental_information: item.supplemental_information || ''
    }
  })
}

const batchResearch = async () => {
  const targets = selectedRows.value.filter((item) => item.status !== 'archived')
  if (targets.length && !runProjectId.value) {
    message.warning('请先选择研究任务所属项目')
    return
  }
  if (!targets.length || !await confirmAction('批量启动研究', `将为当前页选中的 ${targets.length} 条 Query 分别创建并启动研究任务。`, '批量启动')) return
  mutating.value = true
  try {
    const batchId = createIdempotencyKey('query-batch')
    const results = await Promise.allSettled(targets.map((item) => createAndStartRun(item, batchId)))
    const failed = results.filter((item) => item.status === 'rejected').length
    selectedIds.value = []
    await loadQueries({ preserveSelection: false })
    if (failed) message.warning(`${targets.length - failed} 条已启动，${failed} 条失败；可逐条重试失败项`)
    else {
      message.success(`${targets.length} 条研究任务已创建并启动`)
      await router.push('/equipment/runs')
    }
  } catch (reason) {
    setError(reason, '批量启动研究失败')
  } finally {
    mutating.value = false
  }
}

const actOnGeneration = async (action, item) => {
  if (busyGenerationIds.value.has(item.generation_id)) return
  const labels = { cancel: '终止', delete: '删除', retry: '重试' }
  if ((action === 'cancel' || action === 'delete') && !await confirmAction(
    `${labels[action]} Query 生成任务`,
    action === 'cancel' ? 'Worker 会在安全检查点停止，未入库内容不会保存。' : '只删除任务记录和专属运行文件，已入库 Query 会保留。',
    labels[action]
  )) return
  const nextBusy = new Set(busyGenerationIds.value)
  nextBusy.add(item.generation_id)
  busyGenerationIds.value = nextBusy
  try {
    let updated = null
    if (action === 'cancel') updated = await equipmentApi.cancelQueryGeneration(item.generation_id)
    if (action === 'retry') updated = await equipmentApi.retryQueryGeneration(item.generation_id)
    if (action === 'delete') await equipmentApi.deleteQueryGeneration(item.generation_id)
    if (updated) generations.value = generations.value.map((row) => row.generation_id === updated.generation_id ? updated : row)
    else generations.value = generations.value.filter((row) => row.generation_id !== item.generation_id)
    message.success(`生成任务已${labels[action]}`)
  } catch (reason) {
    setError(reason, `生成任务${labels[action]}失败`)
  } finally {
    const remaining = new Set(busyGenerationIds.value)
    remaining.delete(item.generation_id)
    busyGenerationIds.value = remaining
  }
}

const toggleCurrentPage = (checked) => {
  const ids = new Set(selectedIds.value)
  queries.value.forEach((item) => checked ? ids.add(item.query_id) : ids.delete(item.query_id))
  selectedIds.value = [...ids]
}

const toggleQuerySelection = (queryId, checked) => {
  const ids = new Set(selectedIds.value)
  if (checked) ids.add(queryId)
  else ids.delete(queryId)
  selectedIds.value = [...ids]
}

const openDetail = async (item) => {
  selectedId.value = item.query_id
  if (window.matchMedia('(max-width: 760px)').matches) {
    detailOpen.value = true
    await nextTick()
    document.querySelector('.query-detail-panel')?.scrollIntoView({ block: 'start' })
  }
}

const toggleGeneration = (generationId) => {
  const next = new Set(collapsedGenerationIds.value)
  if (next.has(generationId)) next.delete(generationId)
  else next.add(generationId)
  collapsedGenerationIds.value = next
}

const selectGeneratedQuery = async (queryId) => {
  let item = queryById.value.get(queryId)
  if (!item) {
    try {
      item = await equipmentApi.getQuery(queryId, { include_revisions: false })
      generationQueryRows.value = [
        item,
        ...generationQueryRows.value.filter((row) => row.query_id !== item.query_id)
      ]
    } catch (reason) {
      setError(reason, '该生成结果读取失败')
      return
    }
  }
  await openDetail(item)
  if (!window.matchMedia('(max-width: 760px)').matches) {
    document.querySelector('.query-library-shell')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

const loadFirstQueryPage = () => {
  if (page.value !== 1) {
    page.value = 1
    return
  }
  loadQueries({ preserveSelection: false })
}

watch([status, sourceType, pageSize], () => {
  loadFirstQueryPage()
})
watch(page, () => loadQueries({ preserveSelection: false }))
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    loadFirstQueryPage()
  }, 320)
})

onMounted(async () => {
  await Promise.allSettled([loadQueries(), loadGenerations(), loadKnowledgeBases(), projectsStore.loadProjects()])
  if (!runProjectId.value) runProjectId.value = projects.value[0]?.id || ''
  Object.assign(manualForm, {
    knowledge_enabled: generationForm.knowledge_enabled,
    knowledge_ids: [...generationForm.knowledge_ids]
  })
  startPolling()
})
onActivated(startPolling)
onDeactivated(stopPolling)
onUnmounted(() => {
  stopPolling()
  clearTimeout(searchTimer)
  loadToken += 1
})
</script>

<template>
  <div class="query-page query-library-page embedded">
    <div class="query-library-backbar">
      <button type="button" @click="router.push('/equipment/runs')">
        <ArrowLeft :size="15" />返回研究任务
      </button>
      <span>可围绕母题深度发散，也可让 Agent 自主发现方向；审核后带入 Deep Research。</span>
      <label class="query-project-picker">
        <span>研究项目</span>
        <select v-model="runProjectId" aria-label="研究任务所属项目">
          <option disabled value="">请选择项目</option>
          <option v-for="project in projects" :key="project.id" :value="project.id">
            {{ projectDisplayName(project, userStore.isAdmin) }}
          </option>
        </select>
      </label>
    </div>

    <section class="query-generator-hero">
      <span class="query-hero-orb"><WandSparkles :size="22" /></span>
      <span class="query-hero-eyebrow">DEMAND DISCOVERY AGENT</span>
      <h1>多维发散思考，发现装备需求 Query</h1>
      <p>可输入选题角度、场景描述或文档材料，也可由 Agent 结合公开态势自主发现方向；从需求牵引、技术驱动、体系实战和颠覆逻辑等维度形成简洁研究选题。</p>
      <div class="query-generation-mode-tabs" aria-label="Query 生成模式">
        <button type="button" :class="{ active: generationForm.mode === 'guided' }" @click="setGenerationMode('guided')">
          <Lightbulb :size="15" />
          <span><b>围绕母题发散</b><small>输入一个方向，向多维度深挖</small></span>
        </button>
        <button type="button" :class="{ active: generationForm.mode === 'autonomous' }" @click="setGenerationMode('autonomous')">
          <Sparkles :size="15" />
          <span><b>自动态势发散</b><small>无需母题，Agent 自主发现研究方向</small></span>
        </button>
      </div>

      <div class="query-generator-card">
        <template v-if="generationForm.mode === 'guided'">
          <label for="query-generation-topic">需求母题 / 发散材料</label>
          <textarea
            id="query-generation-topic"
            v-model="generationForm.topic"
            maxlength="500"
            placeholder="例如：输入‘复杂电磁环境下精确打击装备能力需求’，Agent 将围绕场景、任务、技术、体系和颠覆方向发散生成多条短 Query。"
          />
        </template>
        <div v-else class="query-autonomous-context">
          <Sparkles :size="23" />
          <span>
            <b>快速研判中国周边态势并发现装备发展方向</b>
            <p>聚焦邻国、周边海域、岛链与边境任务环境，检索最新公开信号，再按“外部态势 → 任务压力 → 作战缺口 → 装备需求”快速转译为研究 Query。</p>
            <em>无人、低空反制、颠覆性远打和精打武器是高关注方向，但不设封闭目录或固定配额；由模型根据本次态势因果链自主发现更多高价值武器装备需求。</em>
          </span>
        </div>

        <div v-if="generationForm.mode === 'guided'" class="query-divergence-framework">
          <div class="query-framework-heading">
            <span><Sparkles :size="15" /><b>多维发散框架</b><small>先明确研究意图，再由 Agent 深度发散，避免只做同义改写</small></span>
            <div>
              <button
                v-for="example in DIVERGENCE_EXAMPLES"
                :key="example.label"
                type="button"
                @click="applyDivergenceExample(example)"
              >
                {{ example.label }}
              </button>
            </div>
          </div>
          <label>
            <span><b>预期角度</b><small>希望牵引什么发展</small></span>
            <textarea v-model="generationForm.expected_angle" placeholder="例如：以天基与地面导弹平台相互赋能为主线，牵引双方装备与体系发展。" />
          </label>
          <label>
            <span><b>需求牵引维度</b><small>场景、威胁、手段与痛点</small></span>
            <textarea v-model="generationForm.demand_dimension" placeholder="当前与未来任务场景是什么？对手能力和威胁形式是什么？现有手段有哪些？单装与体系还存在哪些缺口？" />
          </label>
          <label>
            <span><b>技术驱动维度</b><small>现状、规划与能力映射</small></span>
            <textarea v-model="generationForm.technology_dimension" placeholder="相关资源和技术能力达到什么水平？成熟度与路线图如何？哪些技术可映射为装备能力并改变发展方向？" />
          </label>
          <label>
            <span><b>其他发散偏好</b><small>体系、颠覆与规模建设</small></span>
            <textarea id="query-generation-context" v-model="generationForm.supplemental_information" maxlength="8000" placeholder="可限定作战环境、时间范围，并指定体系韧性、颠覆逻辑、工业化或需要排除的角度。" />
          </label>
        </div>
        <textarea
          v-else
          id="query-generation-context"
          v-model="generationForm.supplemental_information"
          class="query-generation-context autonomous"
          maxlength="8000"
          placeholder="自主发现偏好（可选）：希望重点关注的装备领域、区域态势、技术方向或时间范围。"
        />

        <div class="query-agent-config">
          <div class="query-count-control">
            <span><b>生成数量</b><small>按本次需要灵活选择</small></span>
            <div>
              <button
                v-for="count in [4, 6, 8, 12]"
                :key="count"
                type="button"
                :class="{ active: generationForm.count === count }"
                @click="generationForm.count = count"
              >
                {{ count }}
              </button>
            </div>
          </div>
        </div>

        <EquipmentQueryKnowledgeScope
          v-model:enabled="generationForm.knowledge_enabled"
          v-model:selected-ids="generationForm.knowledge_ids"
          :databases="knowledgeBases"
          :loading="knowledgeLoading"
          :error="knowledgeError"
        />

        <div class="query-generator-footer">
          <button
            type="button"
            class="query-context-toggle"
            :class="{ active: referenceOpen || parseReferenceUrls(generationForm.reference_text).length }"
            @click="referenceOpen = !referenceOpen"
          >
            <Link2 :size="14" />参考 URL<span v-if="parseReferenceUrls(generationForm.reference_text).length"> · {{ parseReferenceUrls(generationForm.reference_text).length }}</span>
          </button>
          <div
            class="query-model-picker"
            :class="{ 'missing-default': !hasDefaultModel && !generationForm.model_spec }"
            :title="hasDefaultModel || generationForm.model_spec ? '为本次 Query 生成选择模型' : '尚未配置系统默认模型，请为本次 Query 生成选择模型'"
          >
            <CircleAlert v-if="!hasDefaultModel && !generationForm.model_spec" :size="15" aria-hidden="true" />
            <WandSparkles v-else :size="15" aria-hidden="true" />
            <ModelSelectorComponent
              upward
              :model_spec="generationForm.model_spec"
              size="nano"
              display-name="mini"
              :placeholder="hasDefaultModel ? '系统默认模型' : '选择生成模型'"
              clearable
              @select-model="(spec) => { generationForm.model_spec = spec || '' }"
            />
          </div>
          <span>输出 {{ generationForm.count }} 条 18–25 字短 Query · 详细维度、理由与来源独立保存</span>
          <button
            type="button"
            class="query-generate-button"
            :disabled="generating || (generationForm.mode === 'guided' && !generationForm.topic.trim())"
            @click="submitGeneration"
          >
            <LoaderCircle v-if="generating" class="spin" :size="16" />
            <Send v-else :size="16" />
            {{ generationForm.mode === 'autonomous' ? '自动发散生成 Query' : '发散生成 Query' }}
          </button>
        </div>
      </div>

      <section v-if="referenceOpen" class="query-reference-url-panel">
        <header>
          <div><Link2 :size="17" /><span><b>优先参考 URL</b><small>Agent 将先阅读这些公开网页，再结合联网检索补充军事信息线索</small></span></div>
          <em>{{ parseReferenceUrls(generationForm.reference_text).length }}/12</em>
        </header>
        <textarea v-model="generationForm.reference_text" spellcheck="false" placeholder="每行输入一个公开 HTTPS 地址，例如：&#10;https://www.example.gov.cn/equipment-planning&#10;https://www.example.org/research-report" />
        <footer>
          <span>系统会自动去重，并移除 token、api_key 等敏感查询参数；URL 仅作为 Query 生成线索。</span>
          <button v-if="generationForm.reference_text" type="button" @click="generationForm.reference_text = ''"><X :size="13" />清空</button>
        </footer>
      </section>

      <div class="query-decomposition-guide">
        <article><span>1</span><div><b>{{ generationForm.mode === 'guided' ? '输入母题' : '研判公开态势' }}</b><small>{{ generationForm.mode === 'guided' ? '可以是一句话，也可以是文档中的长段落' : '从安全环境、任务与技术信号中自主发现方向' }}</small></div></article>
        <article><span>2</span><div><b>多维深度发散</b><small>从需求、技术、体系和颠覆角度寻找研究机会</small></div></article>
        <article><span>3</span><div><b>形成短选题</b><small>标题保持简洁，详细研究维度单独保存</small></div></article>
      </div>

      <section class="query-generation-task-slots" aria-live="polite">
        <header>
          <div><Sparkles :size="16" /><span><b>Query 发散执行槽位</b><small>独立于研究任务并行槽位，仅显示正在执行的 Query 任务</small></span></div>
          <em>{{ activeGenerations.length }} 个进行中</em>
        </header>
        <div v-if="activeGenerations.length" class="query-generation-task-grid">
          <article v-for="item in activeGenerations" :key="item.generation_id" class="query-generation-task" :class="item.status">
            <div class="query-generation-task-icon"><LoaderCircle class="spin" :size="15" /></div>
            <div class="query-generation-task-body">
              <div class="query-generation-task-title"><b>正在生成 Query</b><span>{{ item.requested_count || item.count || 0 }} 条</span></div>
              <p :title="item.topic">{{ item.topic }}</p>
              <small>{{ GENERATION_STAGE_LABELS[item.stage] || item.stage || '等待状态' }} · 后台持续执行中 · 创建于 {{ formatDateTime(item.created_at) }}</small>
            </div>
          </article>
        </div>
        <div v-else class="query-generation-task-empty">
          <LoaderCircle v-if="generationLoading" class="spin" :size="15" />
          <Clock3 v-else :size="15" />
          {{ generationLoading ? '正在读取 Query 执行槽位…' : '当前没有正在执行的 Query 任务。' }}
        </div>
      </section>

      <section class="query-generation-task-list">
        <header class="query-task-list-tabs">
          <div>
            <button type="button" :class="{ active: taskFilter === 'all' }" @click="taskFilter = 'all'"><Archive :size="15" />全部 <em>{{ generationCounts.all }}</em></button>
            <button type="button" :class="{ active: taskFilter === 'running' }" @click="taskFilter = 'running'"><Clock3 :size="15" />进行中 <em>{{ generationCounts.running }}</em></button>
            <button type="button" :class="{ active: taskFilter === 'completed' }" @click="taskFilter = 'completed'"><CheckCircle2 :size="15" />已完成 <em>{{ generationCounts.completed }}</em></button>
          </div>
          <button type="button" class="query-task-list-refresh" :disabled="generationLoading" @click="loadGenerations"><RefreshCw :class="{ spin: generationLoading }" :size="15" />刷新</button>
        </header>
        <div class="query-task-list-note"><Sparkles :size="15" /><b>实时</b><span>Query 发散任务持续沉淀生成状态、产出数量与可追溯的执行时间；删除任务会同步清理专属运行文件。</span></div>
        <div class="query-task-list-toolbar">
          <label><Search :size="16" /><input v-model="taskSearch" placeholder="搜索发散主题或任务 ID"></label>
          <span>{{ visibleGenerations.length }} 项结果</span>
        </div>
        <div v-if="generationLoading && !generations.length" class="query-generation-task-empty"><LoaderCircle class="spin" :size="15" />正在读取 Query 发散任务…</div>
        <div v-else-if="visibleGenerations.length" class="query-generation-task-list-grid">
          <article
            v-for="item in visibleGenerations"
            :key="item.generation_id"
            class="query-generation-task-list-row"
            :class="[item.status, { expanded: !collapsedGenerationIds.has(item.generation_id) }]"
            role="button"
            tabindex="0"
            :aria-expanded="!collapsedGenerationIds.has(item.generation_id)"
            @click="toggleGeneration(item.generation_id)"
            @keydown.enter.prevent="toggleGeneration(item.generation_id)"
            @keydown.space.prevent="toggleGeneration(item.generation_id)"
          >
            <header>
              <span class="query-generation-task-list-check"><ChevronDown :size="12" /></span>
              <b>{{ item.topic }}</b>
              <em>
                <LoaderCircle v-if="['queued', 'running'].includes(item.status)" class="spin" :size="12" />
                <CheckCircle2 v-else-if="item.status === 'completed'" :size="12" />
                <X v-else-if="item.status === 'cancelled'" :size="12" />
                <CircleAlert v-else :size="12" />
                {{ ['queued', 'running'].includes(item.status) ? '进行中' : item.status === 'completed' ? '已完成' : item.status === 'cancelled' ? '已终止' : '失败' }}
              </em>
            </header>
            <p>{{ item.supplemental_information || '由 Agent 结合公开态势与输入偏好，多维发散形成装备需求 Query。' }}</p>
            <div class="query-generation-task-list-metrics">
              <span><strong>{{ item.requested_count || item.count || 0 }}</strong> 目标</span>
              <span><strong>{{ item.result_query_ids?.length || 0 }}</strong> 草稿</span>
              <span><strong>{{ item.source_references?.length || 0 }}</strong> 来源</span>
            </div>
            <div class="query-generation-task-list-meta">
              <span>{{ GENERATION_STAGE_LABELS[item.stage] || item.stage || '等待状态' }}</span>
              <time :datetime="item.created_at">创建于 {{ formatDateTime(item.created_at) }}</time>
            </div>
            <footer @click.stop>
              <span><i />真实运行</span>
              <div class="query-generation-task-actions">
                <button
                  v-if="['queued', 'running'].includes(item.status)"
                  type="button"
                  class="query-generation-task-stop"
                  title="终止当前生成任务"
                  :disabled="busyGenerationIds.has(item.generation_id)"
                  @click="actOnGeneration('cancel', item)"
                >
                  <LoaderCircle v-if="busyGenerationIds.has(item.generation_id)" class="spin" :size="13" />
                  <X v-else :size="13" />
                </button>
                <button
                  v-else-if="['failed', 'cancelled'].includes(item.status)"
                  type="button"
                  title="重试生成任务"
                  :disabled="busyGenerationIds.has(item.generation_id)"
                  @click="actOnGeneration('retry', item)"
                >
                  <LoaderCircle v-if="busyGenerationIds.has(item.generation_id)" class="spin" :size="13" />
                  <RotateCcw v-else :size="13" />
                </button>
                <button
                  v-if="!['queued', 'running'].includes(item.status)"
                  type="button"
                  title="删除任务记录"
                  :disabled="busyGenerationIds.has(item.generation_id)"
                  @click="actOnGeneration('delete', item)"
                >
                  <LoaderCircle v-if="busyGenerationIds.has(item.generation_id)" class="spin" :size="13" />
                  <Trash2 v-else :size="13" />
                </button>
              </div>
            </footer>
            <section v-if="!collapsedGenerationIds.has(item.generation_id)" class="query-generation-task-results" @click.stop>
              <header><span><Sparkles :size="14" /><b>本次生成的 Query</b></span><em>{{ item.result_query_ids?.length || 0 }} 条</em></header>
              <ol v-if="item.result_query_ids?.some((id) => queryById.has(id))">
                <li v-for="queryId in item.result_query_ids.filter((id) => queryById.has(id))" :key="queryId">
                  <button type="button" class="query-result-title" @click="selectGeneratedQuery(queryId)">
                    <span>{{ queryById.get(queryId).query }}</span>
                    <small>{{ QUERY_STATUS_LABELS[queryById.get(queryId).status] || queryById.get(queryId).status }}</small>
                  </button>
                  <div class="query-result-actions">
                    <button type="button" title="查看详情" aria-label="查看详情" @click="selectGeneratedQuery(queryId)"><Eye :size="12" /></button>
                    <button v-if="queryById.get(queryId).status === 'draft'" type="button" title="审核发布" aria-label="审核发布" :disabled="mutating" @click="mutateOne('publish', queryById.get(queryId))"><BookOpenCheck :size="12" /></button>
                    <button v-if="queryById.get(queryId).status !== 'archived'" type="button" title="新建研究任务" aria-label="新建研究任务" :disabled="mutating" @click="directResearch(queryById.get(queryId))"><Play :size="12" /></button>
                    <button type="button" title="删除 Query" aria-label="删除 Query" :disabled="mutating" @click="mutateOne('delete', queryById.get(queryId))"><Trash2 :size="12" /></button>
                  </div>
                </li>
              </ol>
              <div v-else class="query-generation-task-results-state">
                <Clock3 :size="15" />{{ ['queued', 'running'].includes(item.status) ? 'Query 正在生成，完成后可在这里查看。' : item.result_query_ids?.length ? '生成结果正在同步到 Query 库。' : '这个任务没有保存 Query 结果。' }}
              </div>
            </section>
          </article>
        </div>
        <div v-else class="query-generation-task-empty"><Search :size="15" />没有匹配的 Query 发散任务。</div>
      </section>
    </section>

    <div v-if="error" class="query-error" role="alert">
      <CircleAlert :size="16" />{{ error }}
      <button type="button" aria-label="关闭错误提示" @click="error = ''"><X :size="14" /></button>
    </div>

    <section class="query-library-content">
      <div class="query-library-heading">
        <div><span>QUERY LIBRARY</span><h2>装备需求短 Query 库</h2><p>卡片只展示短选题；研究维度、形成理由和来源依据在详情中保留。</p></div>
        <div>
          <button type="button" @click="openManualForm"><FilePlus2 :size="15" />人工录入</button>
          <button type="button" :disabled="loading || generationLoading" @click="refresh"><RefreshCw :class="{ spin: loading || generationLoading }" :size="15" />刷新</button>
        </div>
      </div>

      <form v-if="manualOpen" class="manual-query-form" @submit.prevent="createManualQuery">
        <header>
          <div><FilePlus2 :size="17" /><span><b>人工录入短 Query</b><small>详细研究范围请放在补充信息中</small></span></div>
          <button type="button" aria-label="关闭人工录入" @click="manualOpen = false"><X :size="15" /></button>
        </header>
        <label>
          研究选题
          <textarea v-model="manualForm.query" maxlength="4000" required placeholder="例如：卫星拒止条件下多源自主导航精打武器研究" />
        </label>
        <div>
          <label>详细研究维度与补充信息<textarea v-model="manualForm.supplemental_information" maxlength="8000" /></label>
          <label>生成 / 选题理由<textarea v-model="manualForm.generation_rationale" maxlength="2000" /></label>
        </div>
        <EquipmentQueryKnowledgeScope
          v-model:enabled="manualForm.knowledge_enabled"
          v-model:selected-ids="manualForm.knowledge_ids"
          :databases="knowledgeBases"
          :loading="knowledgeLoading"
          :error="knowledgeError"
        />
        <footer>
          <button type="button" @click="manualOpen = false">取消</button>
          <button type="submit" class="primary" :disabled="mutating || !manualForm.query.trim()">
            <LoaderCircle v-if="mutating" class="spin" :size="14" />{{ mutating ? '保存中' : '保存草稿' }}
          </button>
        </footer>
      </form>

      <div class="query-metrics">
        <article><Database :size="18" /><span><small>筛选结果</small><b>{{ total }}</b></span></article>
        <article><Clock3 :size="18" /><span><small>本页待审核</small><b>{{ metrics.draft }}</b></span></article>
        <article><BookOpenCheck :size="18" /><span><small>本页已发布</small><b>{{ metrics.published }}</b></span></article>
        <article><Sparkles :size="18" /><span><small>本页 Agent 生成</small><b>{{ metrics.agent }}</b></span></article>
      </div>

      <div class="query-library-shell">
        <div class="query-list-column">
          <div class="query-library-toolbar">
            <label><Search :size="15" /><input v-model="search" placeholder="搜索 Query、理由或研究角度"></label>
            <select v-model="status"><option value="all">全部状态</option><option value="draft">待审核</option><option value="published">已发布</option><option value="archived">已归档</option></select>
            <select v-model="sourceType"><option value="all">全部来源</option><option value="agent">Agent 生成</option><option value="manual">人工录入</option><option value="import">资料导入</option></select>
            <span>{{ queries.length }} 条</span>
          </div>
          <div class="query-bulk-toolbar">
            <label><input type="checkbox" :checked="allCurrentSelected" @change="toggleCurrentPage($event.target.checked)"><span>选择当前页</span></label>
            <template v-if="selectedRows.length">
              <span class="query-bulk-count">已选 {{ selectedRows.length }} 条</span>
              <button type="button" :disabled="mutating || !selectedRows.some((item) => item.status === 'draft')" @click="bulkStatus('published')"><BookOpenCheck :size="14" />批量审核发布</button>
              <button type="button" :disabled="mutating" @click="bulkStatus('archived')"><Archive :size="14" />批量归档</button>
              <button type="button" class="primary" :disabled="mutating || !runProjectId || !selectedRows.some((item) => item.status !== 'archived')" @click="batchResearch"><Play :size="14" />批量启动研究</button>
              <button type="button" class="danger" :disabled="mutating" @click="bulkDelete"><Trash2 :size="14" />批量删除</button>
              <button type="button" @click="selectedIds = []"><X :size="14" />清除</button>
            </template>
          </div>
          <div v-if="loading" class="query-empty"><LoaderCircle class="spin" :size="18" />正在读取 Query 库</div>
          <div v-else-if="queries.length" class="query-card-grid">
            <article
              v-for="item in queries"
              :key="item.query_id"
              class="query-library-card"
              :class="{ selected: selectedId === item.query_id }"
              role="button"
              tabindex="0"
              @click="openDetail(item)"
              @keydown="onQueryCardKeydown($event, item)"
            >
              <header>
                <label class="query-card-select" @click.stop>
                  <input type="checkbox" :checked="selectedIds.includes(item.query_id)" :aria-label="`选择 ${item.query}`" @change="toggleQuerySelection(item.query_id, $event.target.checked)">
                  <span class="query-status" :class="item.status">{{ QUERY_STATUS_LABELS[item.status] || item.status }}</span>
                </label>
                <em>{{ QUERY_SOURCE_LABELS[item.source_type] || item.source_type }}</em>
              </header>
              <p>{{ item.query }}</p>
              <footer>
                <span><Lightbulb :size="12" />{{ item.generation_rationale ? '含生成理由' : '理由待补充' }}</span>
                <span class="query-card-time" :title="item.created_at"><Clock3 :size="11" />{{ item.source_type === 'agent' ? '生成于 ' : '录入于 ' }}{{ formatDateTime(item.created_at) }}</span>
                <span>{{ item.source_references?.length || 0 }} 个来源</span>
              </footer>
            </article>
          </div>
          <div v-else class="query-empty"><Search :size="18" />没有匹配的 Query</div>
          <a-pagination
            v-if="total > 0"
            class="query-pagination"
            v-model:current="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-size-options="['10', '20', '50']"
            show-size-changer
            show-less-items
          />
        </div>

        <aside class="query-detail-panel" :class="{ empty: !selected, 'mobile-detail-active': detailOpen }">
          <button type="button" class="query-detail-return" @click="detailOpen = false"><ArrowLeft :size="15" />返回 Query 列表</button>
          <template v-if="!selected"><Lightbulb :size="24" /><p>选择一条短 Query，查看它对应的详细研究维度、生成理由和来源依据。</p></template>
          <template v-else>
            <header><div><span class="query-status" :class="selected.status">{{ QUERY_STATUS_LABELS[selected.status] || selected.status }}</span><em>{{ QUERY_SOURCE_LABELS[selected.source_type] || selected.source_type }} · v{{ selected.version }} · {{ selected.source_type === 'agent' ? '生成于' : '录入于' }} {{ formatDateTime(selected.created_at) }}</em></div><small>{{ selected.query_id }}</small></header>
            <h3>{{ selected.query }}</h3>
            <div class="query-detail-knowledge" :class="{ disabled: selected.knowledge_enabled === false }"><Database :size="14" /><span><b>{{ knowledgeScopeSummary(selected) }}</b><small>这是运行级可用范围；仅在 Agent 判断有必要时调用，不会预取正文或注入蜂群上下文。</small></span></div>
            <section class="query-detail-block"><b>研究角度与补充信息</b><p>{{ selected.supplemental_information || '暂无补充信息，可在启动研究前继续编辑。' }}</p></section>
            <section class="query-detail-block"><b>生成理由</b><p>{{ selected.generation_rationale || '该条为人工或资料导入 Query，尚未补充生成理由。' }}</p></section>
            <section class="query-source-list">
              <b>来源依据</b>
              <article v-for="(source, index) in selected.source_references || []" :key="`${source.url || source.title}-${index}`">
                <span>
                  <a v-if="source.url" :href="source.url" target="_blank" rel="noreferrer">{{ displaySourceTitle(source.title) || source.url }}<ExternalLink :size="12" /></a>
                  <span v-else class="query-source-title">{{ displaySourceTitle(source.title) || '未命名来源' }}</span>
                  <small>{{ source.relevance_note || '用于形成 Query 的背景线索' }}</small>
                </span>
              </article>
              <p v-if="!selected.source_references?.length">暂无直接来源，后续研究仍需独立采集与核验正式证据。</p>
              <em>{{ selected.source_disclaimer || 'Query 生成参考线索，不等同于后续研究结论的正式证据。' }}</em>
            </section>
            <div class="query-detail-actions">
              <button v-if="selected.status !== 'archived'" type="button" :disabled="mutating" @click="mutateOne('archive', selected)"><Archive :size="15" />归档</button>
              <button type="button" class="danger" :disabled="mutating" @click="mutateOne('delete', selected)"><Trash2 :size="15" />删除</button>
              <button v-if="selected.status === 'draft'" type="button" :disabled="mutating" @click="mutateOne('publish', selected)"><BookOpenCheck :size="15" />审核发布</button>
              <button v-if="selected.status === 'published'" type="button" :disabled="mutating || !runProjectId" @click="scheduleResearch(selected)">
                <CalendarClock :size="15" />设置定时研究
              </button>
              <button v-if="selected.status !== 'archived'" type="button" class="primary" :disabled="mutating || !runProjectId" @click="directResearch(selected)">
                <LoaderCircle v-if="mutating" class="spin" :size="15" /><Play v-else :size="15" />{{ selected.status === 'draft' ? '发布并启动研究' : '用此 Query 启动研究' }}
              </button>
            </div>
          </template>
        </aside>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Legacy Vue placeholder rules are intentionally disabled. The React-authored
   component CSS below is the visual contract during the component-by-component migration.
.query-page { display: grid; gap: 20px; padding: 4px 0 36px; color: var(--ant-color-text, #172033); }
.query-page__header, .section-heading, .generator-card__title, .generator-card__footer, .generation-row, .query-card header, .query-card footer, .query-detail > header, .detail-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
h1, h2, h3, h4, p { margin: 0; }
.query-page__header h1 { margin: 4px 0 6px; font-size: clamp(26px, 3vw, 38px); }
.query-page__header p, .section-heading p, .generator-card__title p { color: #718096; }
.eyebrow { color: #5b6ee1; font-size: 11px; font-weight: 800; letter-spacing: .14em; }
.generator-card, .generation-section, .library-section { border: 1px solid rgba(93, 109, 146, .18); border-radius: 18px; background: var(--ant-color-bg-container, #fff); box-shadow: 0 14px 44px rgba(42, 55, 90, .06); }
.generator-card { padding: 22px; background: radial-gradient(circle at 0 0, rgba(94, 88, 255, .12), transparent 34%), var(--ant-color-bg-container, #fff); }
.generator-card__title { align-items: flex-start; }
.generator-card__title > div:nth-child(2) { flex: 1; }
.generator-orb { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 14px; color: #fff; background: linear-gradient(135deg, #6157ec, #1689ff); }
.generator-grid, .generator-config { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; margin-top: 18px; }
.generator-grid .span-2 { grid-column: span 2; }
.generator-config { margin-top: 12px; padding-top: 14px; border-top: 1px solid rgba(93, 109, 146, .13); }
.generator-config :deep(.ant-select) { width: 100%; margin-top: 8px; }
.generator-card__footer { padding-top: 12px; color: #718096; font-size: 12px; }
.generation-section, .library-section { padding: 20px; }
.section-heading { margin-bottom: 16px; }
.generation-list { display: grid; gap: 10px; }
.generation-row { justify-content: flex-start; padding: 13px 15px; border: 1px solid rgba(93, 109, 146, .16); border-radius: 13px; background: rgba(246, 248, 253, .72); }
.generation-row.running, .generation-row.queued { border-color: rgba(82, 93, 245, .38); }
.generation-status-icon { color: #5b6ee1; font-size: 18px; }
.generation-row__body { flex: 1; min-width: 0; }
.generation-row__body > div { display: flex; align-items: center; gap: 8px; }
.generation-row__body strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.generation-row__body p, .generation-row__body small { display: block; margin-top: 3px; color: #718096; }
.generation-row__actions { display: flex; flex-wrap: wrap; gap: 6px; }
.metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.metrics-row article { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid rgba(93, 109, 146, .14); border-radius: 12px; background: rgba(247, 249, 253, .7); color: #5b6ee1; }
.metrics-row span { display: grid; color: inherit; }
.metrics-row small { color: #718096; }
.metrics-row b { color: var(--ant-color-text, #172033); font-size: 20px; }
.library-toolbar { display: grid; grid-template-columns: minmax(260px, 1fr) 150px 150px; gap: 10px; }
.bulk-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-height: 48px; padding: 8px 0; }
.library-layout { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(320px, .9fr); gap: 16px; }
.query-list { min-width: 0; }
.query-card { padding: 15px; margin-bottom: 10px; border: 1px solid rgba(93, 109, 146, .16); border-radius: 14px; cursor: pointer; transition: .18s ease; }
.query-card:hover, .query-card.active { border-color: #6372e8; box-shadow: 0 8px 24px rgba(74, 86, 185, .1); transform: translateY(-1px); }
.query-card header { justify-content: flex-start; }
.query-card header > span:last-child { margin-left: auto; color: #718096; font-size: 12px; }
.query-card h3 { margin: 10px 0 6px; font-size: 16px; line-height: 1.55; }
.query-card p { display: -webkit-box; overflow: hidden; color: #718096; font-size: 13px; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.query-card footer { margin-top: 10px; color: #8a96a8; font-size: 11px; }
.query-detail { align-self: start; position: sticky; top: 82px; min-height: 360px; padding: 18px; border: 1px solid rgba(93, 109, 146, .17); border-radius: 15px; background: rgba(248, 250, 254, .82); }
.query-detail > header { align-items: flex-start; color: #718096; font-size: 12px; }
.query-detail > header > div { display: flex; align-items: center; gap: 6px; }
.query-detail h2 { margin: 16px 0; line-height: 1.5; }
.query-detail section { margin-top: 16px; }
.query-detail section h4 { margin-bottom: 6px; color: #526078; }
.query-detail section p { color: #68778e; line-height: 1.75; white-space: pre-wrap; }
.knowledge-summary { display: flex; gap: 10px; padding: 11px; border-radius: 11px; color: #4858c8; background: rgba(91, 110, 225, .09); }
.knowledge-summary div { display: grid; }
.knowledge-summary small { color: #718096; }
.source-list { display: grid; gap: 6px; }
.source-list a { overflow-wrap: anywhere; }
.detail-actions { justify-content: flex-start; flex-wrap: wrap; margin-top: 20px; }
.detail-actions .ant-btn-primary { margin-left: auto; }
.mobile-return { display: none; }

:global(html.dark) .generator-card, :global(html.dark) .generation-section, :global(html.dark) .library-section { background-color: #151a27; border-color: rgba(154, 166, 206, .2); box-shadow: none; }
:global(html.dark) .generation-row, :global(html.dark) .metrics-row article, :global(html.dark) .query-detail { background: rgba(28, 35, 52, .9); }
:global(html.dark) .query-card { background: rgba(20, 26, 39, .55); }

@media (max-width: 960px) {
  .library-layout { grid-template-columns: 1fr; }
  .query-detail { position: static; }
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 680px) {
  .query-page__header, .generator-card__title, .generator-card__footer, .section-heading, .generation-row { align-items: stretch; flex-direction: column; }
  .generator-grid, .generator-config, .library-toolbar { grid-template-columns: 1fr; }
  .generator-grid .span-2 { grid-column: span 1; }
  .metrics-row { grid-template-columns: 1fr 1fr; }
  .generator-card, .generation-section, .library-section { padding: 15px; border-radius: 14px; }
  .generation-row__actions { justify-content: flex-end; }
  .query-detail { display: none; position: fixed; inset: 54px 0 0; z-index: 25; overflow: auto; border-radius: 0; }
  .query-detail.mobile-open { display: block; }
  .mobile-return { display: inline-flex; margin-bottom: 12px; }
  .detail-actions .ant-btn-primary { margin-left: 0; }
}
*/
</style>

<!-- React 权威页面的组件样式已固化到 Vue 目录，避免迁移后的页面继续依赖 React 源码。 -->
<style src="@/assets/css/equipment-query-library.css"></style>

<style>
.query-library-page {
  padding: 4px 0 36px;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
}
.query-library-page :is(b, strong) { font-weight: 700; }
.query-library-page :where(button, input, textarea, select) { font-family: inherit; }
.query-library-page :where(button) {
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 11px;
  border: 1px solid #d9e1ec;
  border-radius: 6px;
  background: #fff;
  color: #445167;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  transition: border-color 150ms ease, background 150ms ease, box-shadow 150ms ease, transform 150ms ease;
}
.query-library-page :where(button:hover:not(:disabled)) { border-color: #aab8d5; box-shadow: 0 5px 14px rgba(54, 67, 111, .07); }
.query-library-page :where(button:focus-visible) { outline: 2px solid #8f8de7; outline-offset: 2px; }
.query-library-page :where(button:disabled) { cursor: not-allowed; opacity: .55; }
.query-library-page button.primary { border-color: #4845d6; background: linear-gradient(135deg, #5e5bdf, #4845ce); color: #fff; }
.query-library-page button.danger { border-color: #e0aeb4; background: #fff7f7; color: #b14d59; }
.query-library-content { display: contents; }
.query-generation-mode-tabs button { border: 1px solid #dce2ee; }
.query-agent-config { grid-template-columns: 1fr; }
.query-model-picker { display: inline-flex; align-items: center; min-width: 0; max-width: 190px; height: 34px; padding: 0 2px 0 8px; border: 1px solid #e1e5f2; border-radius: 9px; background: #f4f5fb; color: #5b59ad; }
.query-model-picker:focus-within, .query-model-picker:hover { border-color: #aeb6e9; background: #efeffc; box-shadow: 0 0 0 3px rgba(92, 101, 205, .08); }
.query-model-picker.missing-default { border-color: #efc7cb; background: #fff8f8; color: #b64d59; }
.query-model-picker .model-select { max-width: 158px; color: #485276; }
.query-model-picker .config-dropdown-trigger { max-width: 150px; font-size: 10px; font-weight: 700; }
.query-generation-task-actions { display: flex; align-items: center; gap: 5px; margin-left: auto; }
.query-source-title { color: #5452c6; font-size: 10px; overflow-wrap: anywhere; }
.query-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 12px;
  border-top: 1px solid #edf0f5;
}
.query-pagination .ant-pagination-total-text,
.query-pagination .ant-pagination-options,
.query-pagination .ant-pagination-item,
.query-pagination .ant-pagination-prev,
.query-pagination .ant-pagination-next { font-size: 11px; }
.query-project-picker { display: flex; align-items: center; gap: 6px; margin-left: auto; color: #748096; font-size: 10px; }
.query-project-picker > span { white-space: nowrap; }
.query-project-picker select { max-width: 220px; height: 32px; padding: 0 8px; border: 1px solid #dce2ec; border-radius: 8px; background: #fff; color: #536078; font-size: 10px; outline: none; }
.query-project-picker select:focus { border-color: #8f8de7; box-shadow: 0 0 0 2px rgba(102, 91, 211, .08); }

html.dark .query-library-page { color: #d8deeb; }
html.dark .query-library-backbar,
html.dark .query-generator-hero,
html.dark .query-generator-card,
html.dark .query-generation-task-slots,
html.dark .query-generation-task-list,
html.dark .query-metrics article,
html.dark .query-list-column,
html.dark .query-library-card,
html.dark .query-detail-panel,
html.dark .query-detail-block,
html.dark .manual-query-form,
html.dark .query-reference-url-panel,
html.dark .query-generation-task,
html.dark .query-generation-task-list-row,
html.dark .query-generation-task-results,
html.dark .query-generation-task-results li,
html.dark .query-knowledge-summary,
html.dark .query-knowledge-picker,
html.dark .query-knowledge-options label { background: #151a27; border-color: rgba(154, 166, 206, .22); color: #d8deeb; box-shadow: none; }
html.dark .query-divergence-framework,
html.dark .query-agent-config,
html.dark .query-generator-footer,
html.dark .query-bulk-toolbar,
html.dark .query-autonomous-context,
html.dark .query-task-list-note { background: #111622; border-color: rgba(154, 166, 206, .18); }
html.dark .query-divergence-framework label,
html.dark .query-decomposition-guide article,
html.dark .query-library-toolbar label,
html.dark .query-library-toolbar select,
html.dark .query-task-list-toolbar label,
html.dark .query-project-picker select,
html.dark .query-model-picker,
html.dark .query-knowledge-actions button { background: #1c2333; border-color: rgba(154, 166, 206, .24); color: #d8deeb; }
html.dark .query-library-page :is(input, textarea, select) { color: #d8deeb; }
html.dark .query-library-page :is(input, textarea)::placeholder { color: #737f94; }
html.dark .query-generator-hero h1,
html.dark .query-library-heading h2,
html.dark .query-library-card p,
html.dark .query-detail-panel h3,
html.dark .query-generation-task-list-row > header > b,
html.dark .query-generation-task-results li span,
html.dark .query-autonomous-context b,
html.dark .query-framework-heading b,
html.dark .query-divergence-framework label b { color: #e3e8f2; }
html.dark .query-library-page button:not(.primary):not(.query-generate-button):not(.active) { background-color: #1c2333; border-color: rgba(154, 166, 206, .24); color: #cbd3e2; }

@media (max-width: 1050px) {
  .query-agent-config { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .query-library-page { padding-bottom: 24px; }
  .query-pagination { justify-content: center; overflow-x: auto; }
  .query-agent-config { grid-template-columns: 1fr; }
  .query-count-control { grid-column: auto; }
  .query-model-picker { flex: 1; max-width: none; }
  .query-model-picker .model-select, .query-model-picker .config-dropdown-trigger { max-width: none; }
  .query-library-backbar { align-items: flex-start; flex-direction: column; }
  .query-project-picker { width: 100%; margin-left: 0; }
  .query-project-picker select { min-width: 0; max-width: none; flex: 1; }
  .query-generation-task-actions { margin-left: auto; }
}
@media (max-width: 535px) {
  .query-pagination .ant-pagination-options { display: none; }
}
@media (max-width: 390px) {
  .query-pagination { padding-inline: 6px; }
}
</style>
