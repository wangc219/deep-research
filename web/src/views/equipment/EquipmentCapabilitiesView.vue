<script setup>
import { computed, nextTick, onActivated, onMounted, ref, watch } from 'vue'
import '@/assets/css/equipment-workbench-live.css'
import '@/assets/css/equipment-workbench-theme.css'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { storeToRefs } from 'pinia'
import {
  Activity,
  Archive,
  BrainCircuit,
  ChevronDown,
  CircleAlert,
  Download,
  FileCheck2,
  FlaskConical,
  GitCompare,
  History,
  Layers3,
  ListFilter,
  MessageSquare,
  Printer,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Undo2,
  X
} from '@lucide/vue'
import CapabilityPortraitCard from '@/components/equipment/CapabilityPortraitCard.vue'
import EquipmentTechnologySolutionCard from '@/components/equipment/EquipmentTechnologySolutionCard.vue'
import { equipmentApi } from '@/apis/equipment_api'
import { useEquipmentStore } from '@/stores/equipment'
import {
  capabilityCardKey,
  capabilityDimensions,
  capabilityLineageKey,
  capabilityPortraitModules,
  capabilityTitle,
  capabilityVersionMeta,
  isCapabilityDeepResearch,
  normalizeCapabilities
} from '@/utils/equipmentCapabilities'
import { publishDeepLaunchCard } from '@/utils/equipmentDeepLaunch.js'
import {
  isTechnologySolutionSession,
  latestTechnologySession
} from '@/utils/equipmentTechnologySolutions.js'
import {
  S5_SCORE_DIMENSIONS,
  S5_SCORE_SCHEMA,
  capabilityS5Scorecard,
  emptyS5ScoreInput
} from '@/utils/equipmentCapabilityScoring.js'
import { routeLabel, runStatusLabel } from './reportPresentation.js'

const route = useRoute()
const router = useRouter()
const equipmentStore = useEquipmentStore()
const { resources, loading: resourceLoading } = storeToRefs(equipmentStore)

const runs = computed(() => resources.value.runs)
const versions = computed(() => normalizeCapabilities(resources.value.capabilities))
const favorites = computed(() => resources.value.favorites)
const loading = computed(() => Boolean(resourceLoading.value.capabilities || resourceLoading.value.runs))
const selectedRunId = ref(String(route.query.run || ''))
const taskPickerOpen = ref(true)
const search = ref('')
const status = ref('all')
const versionManagerOpen = ref(false)
const versionLedger = ref([])
const versionLoading = ref(false)
const versionBusy = ref('')
const sidecarError = ref('')
const referenceWeapons = ref([])
const feedbackItems = ref([])
const feedbackOpen = ref(false)
const feedbackTarget = ref(null)
const feedbackComment = ref('')
const feedbackVerdict = ref('needs_revision')
const feedbackSaving = ref(false)
const feedbackRollbackBusy = ref('')
const favoriteBusy = ref(new Set())
const technologySessions = ref([])
const technologySessionsLoading = ref(false)
const feedbackScores = ref(emptyS5ScoreInput())
const feedbackRubricSuggestions = ref(emptyS5ScoreInput())
const scoreDimensions = S5_SCORE_DIMENSIONS
const printHeaders = ['装备', '来源 / 版本状态', '能力分类', '概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果', '制胜逻辑']
const printWidths = [12, 12, 10, 13, 14, 13, 14, 12]

const selectedRun = computed(() => runs.value.find((item) => item.run_id === selectedRunId.value) || null)
const selectedRunReadOnly = computed(() => Boolean(selectedRun.value?.readonly))
const visibleRuns = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return runs.value.filter((item) => (
    item.status !== 'archived' &&
    (status.value === 'all' || item.status === status.value || status.value === 'active' && !['completed', 'failed', 'cancelled', 'archived', 'draft'].includes(item.status)) &&
    (!keyword || `${item.topic} ${item.supplemental_information || ''} ${item.run_id}`.toLowerCase().includes(keyword))
  ))
})
const selectedCapabilities = computed(() => versions.value.filter((item) => !selectedRunId.value || item.run_id === selectedRunId.value))
const formalCapabilities = computed(() => selectedCapabilities.value.filter((item) => !isCapabilityDeepResearch(item)))
const deepCapabilities = computed(() => selectedCapabilities.value.filter(isCapabilityDeepResearch))
const visibleReferenceWeapons = computed(() => {
  const identities = new Set(formalCapabilities.value.flatMap((item) => [item.hypothesis_id, item.card_binding_id, capabilityTitle(item)].map((value) => String(value || '').trim().toLowerCase()).filter(Boolean)))
  return referenceWeapons.value.filter((item) => {
    const title = referenceTitle(item)
    return title && ![item.hypothesis_id, item.card_binding_id, title].map((value) => String(value || '').trim().toLowerCase()).some((value) => value && identities.has(value))
  })
})
const deepCards = computed(() => deepCapabilities.value.map((item) => ({ item, formalItem: findFormalBaseline(item) })))
const feedbackWeighted = computed(() => {
  const values = scoreDimensions.map(({ key, weight }) => {
    const raw = feedbackScores.value[key]
    return [String(raw ?? '').trim() === '' ? Number.NaN : Number(raw), weight]
  })
  if (values.some(([value]) => !Number.isFinite(value) || value < 0 || value > 100)) return null
  return Math.round(values.reduce((sum, [value, weight]) => sum + value * weight / 100, 0))
})
const feedbackModelScorecard = computed(() => capabilityS5Scorecard(feedbackTarget.value || {}))
const feedbackModelScores = computed(() => feedbackModelScorecard.value.scores)
const feedbackModelWeighted = computed(() => {
  const score = feedbackModelScorecard.value.weightedScore
  return score === null ? null : Math.round(score * 100)
})
const rubricFeedbackCount = (feedback) => Object.values(feedback?.rubric_feedback || {})
  .filter((value) => String(value || '').trim()).length
const printRows = computed(() => selectedCapabilities.value.map((item) => {
  const modules = new Map(capabilityPortraitModules(item).map((entry) => [entry.label, entry.text]))
  const meta = capabilityVersionMeta(item)
  const dimensions = capabilityDimensions(item).values.join('、') || '—'
  return [
    capabilityTitle(item),
    `${meta.source || 'formal_s6'} · v${meta.version || 1} · ${meta.statusLabel}`,
    dimensions,
    modules.get('概述') || '—',
    modules.get('装备与技术实现') || '—',
    modules.get('关键作战流程') || '—',
    modules.get('形成能力与作战效果') || '—',
    modules.get('制胜逻辑机理') || modules.get('制胜逻辑') || '—'
  ]
}))
const printPageClass = computed(() => printRows.value.length > 4 || printRows.value.flat().join('').length > 7000 ? 'page-a3' : 'page-a4')

function findFormalBaseline(item) {
  const parentKeys = [
    item?.parent_capability_id,
    item?.parent_card_key,
    item?.source_capability_id
  ].map((value) => String(value || '').trim()).filter(Boolean)
  for (const parentKey of parentKeys) {
    const match = formalCapabilities.value.find((candidate) => [
      candidate?.capability_id,
      candidate?.card_binding_id,
      candidate?.card_key,
      candidate?.id,
      candidate?.version_id
    ].some((value) => String(value || '').trim() === parentKey))
    if (match) return match
  }
  const parentName = String(item?.parent_capability_name || '').trim()
  if (parentName) {
    const match = formalCapabilities.value.find((candidate) => capabilityTitle(candidate) === parentName)
    if (match) return match
  }
  const keys = ['hypothesis_id', 'card_binding_id', 'capability_id']
  for (const key of keys) {
    const value = String(item?.[key] || '').trim()
    if (!value) continue
    const match = formalCapabilities.value.find((candidate) => String(candidate?.[key] || '').trim() === value)
    if (match) return match
  }
  const lineage = capabilityLineageKey(item)
  return formalCapabilities.value.find((candidate) => capabilityLineageKey(candidate) === lineage)
    || formalCapabilities.value.find((candidate) => capabilityTitle(candidate) === capabilityTitle(item))
    || null
}

const deepVersionsFor = (formalItem) => deepCards.value
  .filter((entry) => entry.formalItem && capabilityCardKey(entry.formalItem) === capabilityCardKey(formalItem))
  .map((entry) => entry.item)

const technologySessionFor = (item) => latestTechnologySession(technologySessions.value, item)
const technologySectionFor = (item) =>
  capabilityPortraitModules(item).find((entry) => entry.label === '装备与技术实现') || null

const favoriteAliases = (item = {}) => {
  const snapshot = item.snapshot && typeof item.snapshot === 'object' ? item.snapshot : {}
  return [
    item.card_key,
    item.card_binding_id,
    item.capability_id,
    item.id,
    item.display_name,
    snapshot.card_key,
    snapshot.card_binding_id,
    snapshot.capability_id,
    snapshot.id,
    snapshot.name,
    snapshot.equipment_name
  ].map((value) => String(value || '').trim().toLowerCase()).filter(Boolean)
}
const favoriteFor = (item) => {
  if (isCapabilityDeepResearch(item)) return null
  const aliases = new Set(favoriteAliases(item))
  const runId = String(item.run_id || selectedRunId.value)
  return favorites.value.find((favorite) => String(favorite.run_id || '') === runId && favoriteAliases(favorite).some((value) => aliases.has(value))) || null
}
const feedbackFor = (item) => feedbackItems.value.filter((feedback) => (
  feedback.capability_id && feedback.capability_id === item.capability_id ||
  feedback.capability_name && feedback.capability_name === capabilityTitle(item)
))
const isFavoriteBusy = (item) => favoriteBusy.value.has(capabilityCardKey(item))

const referenceTitle = (item = {}) => String(item.title || item.primary_equipment_identity || item.name || (Array.isArray(item.equipment_forms) ? item.equipment_forms[0] : item.equipment_form) || '').trim()
const referenceForm = (item = {}) => Array.isArray(item.equipment_forms) ? item.equipment_forms.filter(Boolean).join(' / ') : String(item.equipment_form || '').trim()
const referenceOverview = (item = {}) => String(item.overview || item.reference_overview || item.concise_winning_summary || '').trim()

const exportCapabilities = async () => {
  if (!selectedCapabilities.value.length) return message.warning('当前任务没有可导出的能力画像')
  try {
    const { Document, HeadingLevel, Packer, Paragraph, Table, TableCell, TableRow, TextRun, WidthType } = await import('docx')
    const cell = (text, bold = false) => new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: String(text), bold })] })] })
    const table = new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [
        new TableRow({ tableHeader: true, children: printHeaders.map((value) => cell(value, true)) }),
        ...printRows.value.map((row) => new TableRow({ children: row.map((value) => cell(value)) }))
      ]
    })
    const doc = new Document({ sections: [{ children: [new Paragraph({ text: '能力画像', heading: HeadingLevel.TITLE }), table] }] })
    const blob = await Packer.toBlob(doc)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `能力画像_${new Date().toISOString().slice(0, 10)}.docx`
    link.click()
    URL.revokeObjectURL(url)
    message.success('能力画像 DOCX 已导出')
  } catch (error) {
    message.error(error.message || 'DOCX 导出失败')
  }
}

const loadCapabilitySidecars = async () => {
  if (!selectedRunId.value) {
    versionLedger.value = []
    feedbackItems.value = []
    referenceWeapons.value = []
    technologySessions.value = []
    sidecarError.value = ''
    return
  }
  const [versionsResult, feedbackResult, contextResult, technologyResult] = await Promise.allSettled([
    equipmentApi.listCapabilityVersions(selectedRunId.value),
    equipmentApi.listExpertFeedback(selectedRunId.value),
    equipmentApi.getDeepContextOptions(selectedRunId.value),
    loadTechnologySessions()
  ])
  const errors = []
  if (versionsResult.status === 'fulfilled') versionLedger.value = versionsResult.value?.versions || []
  else errors.push(versionsResult.reason?.message || '版本链读取失败')
  if (feedbackResult.status === 'fulfilled') feedbackItems.value = Array.isArray(feedbackResult.value) ? feedbackResult.value : feedbackResult.value?.items || []
  else errors.push(feedbackResult.reason?.message || '专家反馈读取失败')
  if (contextResult.status === 'fulfilled') referenceWeapons.value = contextResult.value?.reference_weapons || []
  else errors.push(contextResult.reason?.message || '参考武器读取失败')
  if (technologyResult.status === 'rejected') errors.push(technologyResult.reason?.message || '技术方案读取失败')
  sidecarError.value = [...new Set(errors)].join('；')
}

const loadTechnologySessions = async () => {
  technologySessionsLoading.value = true
  try {
    const response = await equipmentApi.listDeepSessions()
    const rows = (Array.isArray(response) ? response : response?.items || []).filter(
      (item) =>
        String(item?.run_id || '') === selectedRunId.value && isTechnologySolutionSession(item)
    )
    const details = await Promise.allSettled(
      rows.map((item) => equipmentApi.getDeepSession(item.session_id))
    )
    technologySessions.value = details
      .filter((item) => item.status === 'fulfilled')
      .map((item) => item.value)
  } finally {
    technologySessionsLoading.value = false
  }
}

const toggleVersionManager = async () => {
  versionManagerOpen.value = !versionManagerOpen.value
  if (!versionManagerOpen.value || !selectedRunId.value) return
  versionLoading.value = true
  try {
    versionLedger.value = (await equipmentApi.listCapabilityVersions(selectedRunId.value))?.versions || []
  } catch (error) {
    sidecarError.value = error.message || '版本链加载失败'
  } finally {
    versionLoading.value = false
  }
}

const confirmVersionMutation = (item, action) => {
  const name = capabilityTitle(item.snapshot || item)
  if (action === 'delete') return window.confirm(`确定删除深研版本“${name} · v${item.version_no || '?'}”吗？\n\n正式 S6 基线不受影响，删除后可在版本管理中恢复。`)
  if (action === 'purge') return window.confirm(`确定永久删除深研版本“${name} · v${item.version_no || '?'}”吗？\n\n此操作不可恢复。`)
  return true
}

const mutateVersion = async (item, action) => {
  if (selectedRunReadOnly.value) {
    message.warning('历史研究任务为只读数据')
    return
  }
  const versionId = item.version_id || item.id
  if (!versionId || versionBusy.value || !confirmVersionMutation(item, action)) return
  versionBusy.value = versionId
  try {
    if (action === 'delete') await equipmentApi.deleteCapabilityVersion(selectedRunId.value, versionId)
    if (action === 'restore') await equipmentApi.restoreCapabilityVersion(selectedRunId.value, versionId)
    if (action === 'purge') await equipmentApi.purgeCapabilityVersion(selectedRunId.value, versionId)
    await Promise.all([loadCapabilitySidecars(), equipmentStore.loadResource('capabilities', {}, { force: true })])
    message.success(action === 'restore' ? '深研版本已恢复' : action === 'purge' ? '深研版本已永久删除' : '深研版本已删除，可在版本管理中恢复')
  } catch (error) {
    sidecarError.value = error.message || '版本操作失败'
  } finally {
    versionBusy.value = ''
  }
}

const openFeedback = (item = null) => {
  if (selectedRunReadOnly.value) {
    message.warning('历史研究任务为只读数据')
    return
  }
  feedbackTarget.value = item
  feedbackComment.value = ''
  feedbackVerdict.value = 'needs_revision'
  feedbackScores.value = emptyS5ScoreInput()
  feedbackRubricSuggestions.value = emptyS5ScoreInput()
  feedbackOpen.value = true
}

const submitFeedback = async (launchDeep = false) => {
  if (selectedRunReadOnly.value) return message.warning('历史研究任务为只读数据')
  if (!feedbackComment.value.trim()) return message.warning('请填写反馈意见')
  if (feedbackTarget.value && feedbackWeighted.value === null) return message.warning('请完整填写五个维度的 0–100 分')
  feedbackSaving.value = true
  try {
    const item = feedbackTarget.value
    const scores = item ? Object.fromEntries(scoreDimensions.map(({ key }) => [key, Number(feedbackScores.value[key]) / 100])) : {}
    const rubricFeedback = item ? Object.fromEntries(
      scoreDimensions
        .map(({ key }) => [key, String(feedbackRubricSuggestions.value[key] || '').trim()])
        .filter(([, value]) => value)
    ) : {}
    const saved = await equipmentApi.createExpertFeedback(selectedRunId.value, {
      capability_id: item?.capability_id || '',
      hypothesis_id: item?.hypothesis_id || '',
      capability_name: item ? capabilityTitle(item) : '本任务整体能力画像',
      comment: feedbackComment.value.trim(),
      verdict: item ? feedbackVerdict.value : 'needs_revision',
      rating: item ? Math.max(1, Math.min(5, Math.round(feedbackWeighted.value / 20))) : null,
      dimensions: item ? scoreDimensions.map(({ key }) => key) : [],
      target_agent_ids: item ? ['S5'] : [],
      stage_scope: item ? ['S5'] : [],
      model_dimension_scores: item && feedbackModelScorecard.value.complete
        ? feedbackModelScorecard.value.scores
        : {},
      expert_dimension_scores: scores,
      expert_weighted_score: item ? feedbackWeighted.value / 100 : null,
      rubric_feedback: rubricFeedback,
      rubric_version: S5_SCORE_SCHEMA,
      reviewer_role: 'expert'
    })
    feedbackOpen.value = false
    await loadCapabilitySidecars()
    if (launchDeep && item) {
      message.success('专家反馈已保存，正在进入定向深研')
      openDeep(item, null, saved?.feedback)
    } else {
      message.success('专家反馈已保存')
    }
  } catch (error) {
    message.error(error.message || '反馈保存失败')
  } finally {
    feedbackSaving.value = false
  }
}

const rollbackFeedback = async (item) => {
  if (selectedRunReadOnly.value) return message.warning('历史研究任务为只读数据')
  if (!window.confirm('确定回滚这条专家反馈吗？\n\n反馈会停止作为后续 Agent 的记忆输入，但审计记录仍保留。')) return
  feedbackRollbackBusy.value = item.feedback_id
  try {
    await equipmentApi.rollbackExpertFeedback(selectedRunId.value, item.feedback_id, '审核者从能力画像页回滚')
    await loadCapabilitySidecars()
    message.success('反馈已回滚')
  } catch (error) {
    message.error(error.message || '反馈回滚失败')
  } finally {
    feedbackRollbackBusy.value = ''
  }
}

const toggleFavorite = async (item, desired) => {
  const key = capabilityCardKey(item)
  if (favoriteBusy.value.has(key)) return
  favoriteBusy.value = new Set([...favoriteBusy.value, key])
  try {
    const existing = favoriteFor(item)
    if (desired) {
      await equipmentApi.createFavoriteCard({
        run_id: item.run_id || selectedRunId.value,
        card_key: item.card_key || item.card_binding_id || item.capability_id || item.version_id || item.id || capabilityTitle(item),
        card_binding_id: item.card_binding_id || '',
        capability_id: item.capability_id || ''
      })
    } else if (existing) {
      await equipmentApi.deleteFavoriteCard(existing.favorite_id || existing.id)
    }
    await equipmentStore.loadResource('favorites', {}, { force: true })
    message.success(desired ? '已加入个人收藏' : '已取消收藏')
  } catch (error) {
    message.error(error.message || (desired ? '收藏失败' : '取消收藏失败'))
  } finally {
    const next = new Set(favoriteBusy.value)
    next.delete(key)
    favoriteBusy.value = next
  }
}

const openDeep = (item, section = null, feedback = null) => {
  const key = item.card_binding_id || item.card_key || item.capability_id || item.id || capabilityTitle(item)
  publishDeepLaunchCard({
    card_key: key,
    run_id: item.run_id || selectedRunId.value,
    capability_id: item.capability_id || '',
    name: capabilityTitle(item),
    sections: capabilityPortraitModules(item),
    section_label: section?.label || '',
    section_text: section?.text || '',
    source_feedback_id: feedback?.feedback_id || '',
    source_feedback_comment: feedback?.comment || '',
    source_feedback_verdict: feedback?.verdict || ''
  })
  router.push({
    path: '/equipment/deep-thinking',
    query: {
      run: item.run_id || selectedRunId.value,
      cap: key,
      ...(feedback?.feedback_id ? { feedback: feedback.feedback_id } : {}),
      ...(section?.label ? { section: section.label } : {})
    }
  })
}

const openTechnologyCabin = (item) => openDeep(item, technologySectionFor(item))

const openReferenceDeep = (item) => router.push({
  path: '/equipment/deep-thinking',
  query: { run: selectedRunId.value, reference: item.hypothesis_id || referenceTitle(item) }
})

const focusCapabilityCard = async (item) => {
  await nextTick()
  const key = capabilityCardKey(item)
  const target = [...document.querySelectorAll('.capability-sheet')].find((node) => node.dataset.cardKey === key)
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  target.classList.remove('capability-highlight')
  void target.offsetWidth
  target.classList.add('capability-highlight')
  window.setTimeout(() => target.classList.remove('capability-highlight'), 2600)
}

const focusRouteCard = async () => {
  const key = String(route.query.cap || '').trim()
  if (!key) return
  const item = selectedCapabilities.value.find((candidate) => [
    capabilityCardKey(candidate),
    candidate.card_binding_id,
    candidate.card_key,
    candidate.capability_id,
    candidate.id
  ].some((value) => String(value || '') === key))
  if (item) await focusCapabilityCard(item)
}

const chooseRun = async (item) => {
  selectedRunId.value = item.run_id
  taskPickerOpen.value = false
  await router.replace({ query: { ...route.query, run: item.run_id, cap: undefined } })
  await loadCapabilitySidecars()
  if (window.matchMedia('(max-width: 900px)').matches) {
    await nextTick()
    document.querySelector('.task-review-content.capabilities')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

const load = async () => {
  try {
    await Promise.all(['runs', 'capabilities', 'favorites'].map((name) => equipmentStore.loadResource(name, {}, { force: true })))
    if (!selectedRunId.value) selectedRunId.value = versions.value[0]?.run_id || runs.value[0]?.run_id || ''
    await loadCapabilitySidecars()
    await focusRouteCard()
  } catch (error) {
    message.error(error.message || '能力画像加载失败')
  }
}

watch(() => route.query.run, async (value) => {
  selectedRunId.value = String(value || '')
  await loadCapabilitySidecars()
  await focusRouteCard()
})
watch(() => route.query.cap, focusRouteCard)
onMounted(load)
onActivated(() => { if (versions.value.length) load() })
</script>

<template>
  <div class="capability-page">
    <section class="page-title"><div><span>交互中心</span><h1>能力图像</h1><p>直接选择研究任务，连续查看交互、证据、S Agent、能力画像、深研对话和研究报告。</p></div></section>

    <nav class="workspace-stage-nav" aria-label="当前任务产物导航">
      <div class="workspace-stage-nav-inner">
        <button type="button" @click="router.push('/equipment/runs')"><Archive :size="15" />研究任务</button>
        <section class="workspace-artifact-card" aria-label="当前任务产物导航"><span>当前任务产物</span><div>
          <button type="button" class="active" aria-current="page" :disabled="!selectedRun"><FlaskConical :size="15" />能力图像</button>
          <button type="button" :disabled="!selectedRun" @click="router.push(`/equipment/deep-thinking?run=${encodeURIComponent(selectedRunId)}`)"><MessageSquare :size="15" />深研对话</button>
          <button type="button" :disabled="!selectedRun" @click="router.push(`/equipment/reports?run=${encodeURIComponent(selectedRunId)}`)"><FileCheck2 :size="15" />研究报告</button>
        </div></section>
      </div>
    </nav>

    <div class="task-review-workspace capability-workspace" :class="{ 'has-selected-task': selectedRun }">
      <section class="task-review-rail">
        <button type="button" class="task-picker-toggle" :disabled="!selectedRun && loading" :aria-expanded="!selectedRun || taskPickerOpen" aria-controls="capability-task-picker" @click="taskPickerOpen = !taskPickerOpen">
          <ListFilter :size="17" /><span><b>研究任务</b><small>{{ selectedRun?.topic || '选择任务，查看能力画像' }}</small></span><em>{{ !selectedRun || taskPickerOpen ? '收起任务列表' : '切换任务' }}</em><ChevronDown :size="16" />
        </button>
        <div v-show="!selectedRun || taskPickerOpen" id="capability-task-picker">
          <header><div><ListFilter :size="17" /><span><b>研究任务</b><small>{{ visibleRuns.length }} / {{ runs.filter((item) => item.status !== 'archived').length }}</small></span></div></header>
          <div class="task-review-filters"><div class="searchbox"><Search :size="15" /><input v-model="search" placeholder="搜索任务或运行 ID"></div><select v-model="status"><option value="all">全部状态</option><option value="active">进行中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="draft">草稿</option></select></div>
          <div class="task-review-list">
            <template v-if="visibleRuns.length"><button v-for="item in visibleRuns" :key="item.run_id" type="button" :class="{ selected: selectedRunId === item.run_id }" @click="chooseRun(item)"><span><b>{{ item.topic }}</b><small>{{ item.run_id }}</small></span><div><i class="status" :class="item.status"><i />{{ runStatusLabel(item.status) }}</i><em>{{ routeLabel(item.research_route) }}</em></div></button></template>
            <div v-else-if="loading" class="task-row-skeletons" aria-hidden="true"><div v-for="index in 5" :key="index" class="task-row-skeleton"><span class="skeleton" style="width:74%;height:12px" /><span class="skeleton" style="width:46%;height:9px" /></div></div>
            <div v-else class="empty"><Activity :size="23" />当前已加载任务中没有匹配结果</div>
          </div>
        </div>
      </section>

      <section class="task-review-content capabilities">
        <header v-if="selectedRun" class="task-review-context"><div><span>当前能力画像任务</span><b>{{ selectedRun.topic }}</b><small>{{ selectedRun.run_id }} · {{ routeLabel(selectedRun.research_route) }} · {{ runStatusLabel(selectedRun.status) }}<template v-if="selectedRun.historical_snapshot"> · 历史数据{{ selectedRunReadOnly ? '（只读）' : '（可编辑）' }}</template></small></div><i class="status" :class="selectedRun.status"><i />{{ runStatusLabel(selectedRun.status) }}</i></header>

        <div v-if="loading && !selectedCapabilities.length" class="pane-skeleton" aria-hidden="true"><span v-for="(width, index) in ['28%','100%','95%','86%','22%','97%','90%','78%']" :key="index" class="skeleton" :style="{ width, height: index === 0 || index === 4 ? '15px' : '11px' }" /></div>
        <div v-else-if="selectedCapabilities.length" class="capability-view">
          <div class="capability-toolbar">
            <div><b>能力画像成果</b><small>正式 S6 基线与深研对话结果分区保留；深研卡片可定位原卡并展开差异对比</small></div>
            <div>
              <button v-if="deepCapabilities.length" type="button" class="deep-research-jump-button" @click="document.getElementById('deep-research-cards')?.scrollIntoView({ behavior: 'smooth', block: 'start' })"><Layers3 :size="14" />深研卡片 <span>{{ deepCapabilities.length }}</span></button>
              <button type="button" class="deep-toolbar-button" @click="router.push(`/equipment/deep-thinking?run=${encodeURIComponent(selectedRunId)}`)"><BrainCircuit :size="14" />深度思考 Agent</button>
              <button type="button" :class="{ 'is-active': versionManagerOpen }" @click="toggleVersionManager"><GitCompare :size="14" />深研版本管理</button>
              <button type="button" @click="exportCapabilities"><Download :size="14" />导出 DOCX</button>
              <button type="button" class="primary" @click="window.print()"><Printer :size="14" />打印 / 导出 PDF</button>
            </div>
          </div>

          <section v-if="versionManagerOpen" class="capability-version-manager">
            <header><div><GitCompare :size="16" /><span><b>深研版本管理</b><small>{{ selectedRunReadOnly ? '当前为历史只读任务，仅可查看版本链。' : '正式 S6 基线不可删除；深研版本可先隐藏后恢复，也可对已隐藏版本永久删除。' }}</small></span></div><button type="button" class="icon-button" aria-label="关闭版本管理" @click="versionManagerOpen = false"><X :size="16" /></button></header>
            <p v-if="sidecarError" class="form-error"><CircleAlert :size="14" />{{ sidecarError }}</p>
            <div v-if="versionLoading" class="capability-version-manager-empty"><RefreshCw :size="15" class="spin" />正在读取版本链…</div>
            <div v-else-if="versionLedger.length" class="capability-version-manager-list"><article v-for="item in [...versionLedger].reverse()" :key="item.version_id || item.id" :class="{ 'is-deleted': capabilityVersionMeta(item).status === 'deleted' }"><div><b>{{ capabilityTitle(item.snapshot || item) }}</b><span><em>v{{ item.version_no || item.version || '?' }}</em><small class="version-manager-status" :class="capabilityVersionMeta(item).status">{{ capabilityVersionMeta(item).statusLabel }}</small><small>{{ item.created_at ? new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) : '历史导入版本' }}</small></span></div><span v-if="capabilityVersionMeta(item).status === 'formal'" class="version-manager-protected"><ShieldCheck :size="13" />不可变基线</span><div v-else-if="capabilityVersionMeta(item).status === 'deleted'" class="version-manager-actions"><button type="button" class="version-restore-button" :disabled="selectedRunReadOnly || versionBusy === (item.version_id || item.id)" :title="selectedRunReadOnly ? '历史研究任务为只读数据' : ''" @click="mutateVersion(item, 'restore')"><History :size="13" />恢复</button><button type="button" class="capability-version-purge" :disabled="selectedRunReadOnly || versionBusy === (item.version_id || item.id)" :title="selectedRunReadOnly ? '历史研究任务为只读数据' : ''" @click="mutateVersion(item, 'purge')"><Trash2 :size="13" />永久删除</button></div><button v-else type="button" class="capability-version-delete" :disabled="selectedRunReadOnly || versionBusy === (item.version_id || item.id)" :title="selectedRunReadOnly ? '历史研究任务为只读数据' : ''" @click="mutateVersion(item, 'delete')"><Trash2 :size="13" />{{ versionBusy === (item.version_id || item.id) ? '处理中…' : '删除' }}</button></article></div>
            <div v-else class="capability-version-manager-empty">当前任务尚无深研版本。</div>
          </section>

          <div class="capability-print-table" :class="printPageClass">
            <h1>能力画像</h1><table><colgroup><col v-for="(width, index) in printWidths" :key="index" :style="{ width: `${width}%` }"></colgroup><thead><tr><th v-for="header in printHeaders" :key="header">{{ header }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in printRows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td></tr></tbody></table>
            <section v-if="visibleReferenceWeapons.length" class="capability-reference-print-block" :class="{ 'page-break-before': printPageClass === 'page-a3' }"><h2>参考装备</h2><table><thead><tr><th>参考装备</th><th>概述</th></tr></thead><tbody><tr v-for="item in visibleReferenceWeapons" :key="item.hypothesis_id || referenceTitle(item)"><td>{{ referenceTitle(item) }}</td><td>{{ referenceOverview(item) || '—' }}</td></tr></tbody></table></section>
          </div>

          <section class="expert-feedback-panel">
            <header><div><span class="expert-feedback-icon"><MessageSquare :size="17" /></span><span><b>专家审核反馈</b><small>{{ selectedRunReadOnly ? '历史研究任务为只读数据，反馈记录仅供查看。' : '画像卡反馈统一记录五维评分与意见；任务整体反馈保留为文字意见。' }}</small></span></div><div class="expert-feedback-head-actions"><em>{{ feedbackItems.length ? `已记录 ${feedbackItems.length} 条` : '尚未反馈' }}</em><button type="button" class="primary" :disabled="selectedRunReadOnly" :title="selectedRunReadOnly ? '历史研究任务为只读数据' : ''" @click="openFeedback()"><MessageSquare :size="14" />提交反馈</button></div></header>
            <div class="expert-feedback-learning"><Sparkles :size="15" /><span><b>记忆处理 Agent 已接入</b><small>自动去重、压缩、相关性评分，并限制每个后续 Agent 读取的记忆数量，避免多卡反馈造成上下文噪声。</small></span></div>
            <p v-if="sidecarError" class="form-error"><CircleAlert :size="14" />{{ sidecarError }}</p>
            <div v-if="feedbackItems.length" class="expert-feedback-history"><article v-for="feedback in feedbackItems.slice(-3).reverse()" :key="feedback.feedback_id"><header><span class="feedback-verdict processed">已处理</span><b>{{ feedback.capability_name || '本任务整体' }}</b><span v-if="Number.isFinite(Number(feedback.expert_weighted_score))" class="feedback-score-chip">专家综合 {{ Math.round(Number(feedback.expert_weighted_score) * 100) }}</span><span v-if="rubricFeedbackCount(feedback)" class="feedback-rubric-chip">细则建议 {{ rubricFeedbackCount(feedback) }} 项</span><small>{{ feedback.created_at ? new Date(feedback.created_at).toLocaleString('zh-CN', { hour12: false }) : '' }}</small></header><p>{{ feedback.comment || '未填写反馈意见。' }}</p><div v-if="feedback.learning_signal"><Sparkles :size="13" /><span><b>已提炼高价值记忆 · {{ Array.isArray(feedback.target_agent_ids) ? feedback.target_agent_ids.join('、') : '自动路由' }}</b>{{ feedback.learning_signal }}</span></div><footer class="expert-feedback-item-actions"><small>回滚后保留审计记录，但不再进入后续记忆。</small><button type="button" class="feedback-rollback-button" :disabled="selectedRunReadOnly || feedbackRollbackBusy === feedback.feedback_id" :title="selectedRunReadOnly ? '历史研究任务为只读数据' : ''" @click="rollbackFeedback(feedback)"><RefreshCw v-if="feedbackRollbackBusy === feedback.feedback_id" :size="13" class="spin" /><Undo2 v-else :size="13" />{{ feedbackRollbackBusy === feedback.feedback_id ? '回滚中…' : '回滚反馈' }}</button></footer></article></div>
          </section>

          <div v-if="feedbackOpen" class="expert-feedback-modal-backdrop" @mousedown.self="feedbackOpen = false">
            <form class="expert-feedback-form portfolio-score-feedback-form" role="dialog" aria-modal="true" aria-label="提交专家审核意见" @submit.prevent="submitFeedback(false)" @mousedown.stop>
              <header><div><b>{{ feedbackTarget ? '针对本卡反馈' : '提交专家审核意见' }}</b><small>{{ feedbackTarget ? `${capabilityTitle(feedbackTarget)} · 五维评分与 S5 保持同一口径` : '任务整体反馈将自动处理后路由给相关 S1–S6 Agent。' }}</small></div><button type="button" class="icon-button" aria-label="关闭反馈表单" @click="feedbackOpen = false"><X :size="16" /></button></header>
              <label class="expert-feedback-target"><span>反馈对象</span><select :value="feedbackTarget ? capabilityCardKey(feedbackTarget) : ''" @change="openFeedback(selectedCapabilities.find((item) => capabilityCardKey(item) === $event.target.value) || null)"><option value="">本任务整体能力画像</option><option v-for="item in selectedCapabilities" :key="capabilityCardKey(item)" :value="capabilityCardKey(item)">{{ capabilityTitle(item) }}</option></select></label>
              <template v-if="feedbackTarget">
                <section class="portfolio-score-comparison" aria-label="S5 模型评分、评分原则与专家评分对照">
                  <header><span>评分维度与原则</span><span>当前 S5</span><span>专家评分</span></header>
                  <label v-for="dimension in scoreDimensions" :key="dimension.key" class="portfolio-score-row">
                    <span><b>{{ dimension.label }}</b><small>权重 {{ dimension.weight }}%</small></span>
                    <output>{{ feedbackModelScores[dimension.key] === null ? '—' : Math.round(feedbackModelScores[dimension.key] * 100) }}</output>
                    <span class="portfolio-score-input"><input v-model="feedbackScores[dimension.key]" type="number" min="0" max="100" step="1" inputmode="numeric" :aria-label="`${dimension.label}专家评分`" required><em>分</em></span>
                    <small class="portfolio-score-principle"><b>评分原则</b>{{ dimension.principle }}</small>
                    <input v-model="feedbackRubricSuggestions[dimension.key]" class="portfolio-rubric-feedback" maxlength="1000" :aria-label="`${dimension.label}评分细则修改建议`" placeholder="对本维度评分细则的修改建议（可选）">
                  </label>
                  <footer><span>综合评分</span><output>{{ feedbackModelWeighted ?? '未经过 S5' }}</output><b>{{ feedbackWeighted ?? '待填写' }}</b></footer>
                </section>
                <label><span>审核结论</span><select v-model="feedbackVerdict"><option value="approved">认可画像</option><option value="needs_revision">建议修订</option><option value="rejected">建议淘汰</option></select></label>
              </template>
              <label><span>反馈意见</span><textarea v-model="feedbackComment" maxlength="4000" :placeholder="feedbackTarget ? '说明评分差异、关键依据或需要修订的判断……' : '指出整体画像中最有价值、最不准确或需要补强的地方……'" required /></label>
              <div v-if="feedbackTarget" class="portfolio-calibration-note"><Sparkles :size="14" /><span><b>评分校准样本</b><small>当前 S5 原分、专家分、差值和细则修改建议一并保存；经回放或专家裁决验证后，才用于后续评分口径迭代。</small></span></div>
              <footer><small>{{ feedbackTarget ? '严格按 S5 的创新性/需求性/科学可行性/效能性/发展性及 30/30/20/10/10 权重计算' : '保存后自动提炼、去重并路由到相关 Agent' }}</small><button v-if="feedbackTarget" type="button" :disabled="selectedRunReadOnly || feedbackSaving" @click="submitFeedback(true)"><BrainCircuit :size="14" />保存并定向深研</button><button type="submit" class="primary" :disabled="selectedRunReadOnly || feedbackSaving">{{ feedbackSaving ? '保存中…' : feedbackTarget ? '提交评分反馈' : '提交反馈' }}<Send :size="14" /></button></footer>
            </form>
          </div>

          <section
            v-for="item in formalCapabilities"
            :key="capabilityCardKey(item)"
            class="capability-version-group"
          >
            <EquipmentTechnologySolutionCard
              :equipment-name="capabilityTitle(item)"
              :session="technologySessionFor(item)"
              :loading="technologySessionsLoading"
              @open="openTechnologyCabin(item)"
            />
            <CapabilityPortraitCard
              :item="item"
              :deep-versions="deepVersionsFor(item)"
              :favorite="favoriteFor(item)"
              :favorite-pending="isFavoriteBusy(item)"
              :feedback-count="feedbackFor(item).length"
              :version-busy="versionBusy === (item.version_id || item.id)"
              :read-only="selectedRunReadOnly"
              @feedback="openFeedback"
              @deep="openDeep"
              @favorite="toggleFavorite"
              @jump="focusCapabilityCard"
              @delete-version="(row) => mutateVersion(row, 'delete')"
            />
          </section>

          <section v-if="deepCards.length" id="deep-research-cards" class="capability-deep-research-panel"><header><div><span class="deep-research-panel-icon"><GitCompare :size="17" /></span><span><b>深研卡片</b><small>来自深研对话的独立能力画像，不覆盖正式原卡；选择卡片可定位原卡或查看差异。</small></span></div><em>{{ deepCards.length }} 张</em></header><div class="capability-deep-research-list"><CapabilityPortraitCard v-for="entry in deepCards" :key="capabilityCardKey(entry.item)" :item="entry.item" :formal-item="entry.formalItem" :feedback-count="feedbackFor(entry.item).length" :version-busy="versionBusy === (entry.item.version_id || entry.item.id)" :read-only="selectedRunReadOnly" @feedback="openFeedback" @deep="openDeep" @jump="focusCapabilityCard" @delete-version="(row) => mutateVersion(row, 'delete')" /></div></section>

          <section v-if="visibleReferenceWeapons.length" class="capability-reference-library"><header><div><b>参考武器</b><small>仅展示具备明确装备名称或形态、但未进入本轮 S6 详细画像的候选；深度研究锁定单个装备，在当前 Query 下对话式发散，不重新执行完整 S1–S6</small></div><em>{{ visibleReferenceWeapons.length }} 条</em></header><div class="capability-reference-grid"><article v-for="item in visibleReferenceWeapons" :key="item.hypothesis_id || referenceTitle(item)" class="capability-reference-card"><header><span class="capability-reference-badge">参考</span><span><b>{{ referenceTitle(item) || referenceForm(item) }}</b><small v-if="referenceForm(item) && referenceForm(item) !== referenceTitle(item)">{{ referenceForm(item) }}</small></span></header><p>{{ referenceOverview(item) || '暂无参考概述。' }}</p><footer class="capability-reference-actions"><span class="reference-research-status">创新候选 · 可继续深挖</span><div><button type="button" class="reference-research-button" :disabled="selectedRunReadOnly" :title="selectedRunReadOnly ? '历史研究任务为只读数据' : ''" @click="openReferenceDeep(item)">定向深研 / 追问<BrainCircuit :size="13" /></button></div></footer></article></div></section>
        </div>
        <div v-else class="empty"><Activity :size="23" />{{ selectedRun ? '该任务还没有能力画像版本' : '请选择研究任务' }}</div>
      </section>
    </div>
  </div>
</template>

<style>
.capability-page,
.capability-page * { box-sizing: border-box; }
.capability-page {
  display: grid;
  min-height: 100%;
  min-width: 0;
  gap: 0;
  padding: 28px 32px 40px;
  background:
    radial-gradient(circle at 78% -12%, rgb(105 102 243 / 11%), transparent 32%),
    radial-gradient(circle at 6% 102%, rgb(78 154 128 / 6%), transparent 34%),
    #f5f7fb;
  color: #20283a;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "HarmonyOS Sans SC", "Noto Sans SC", "Microsoft YaHei", Inter, system-ui, Arial, sans-serif;
  line-height: normal;
}
.capability-page :where(h1, h2, h3, h4, h5, h6, b, strong, th) { font-weight: 700; }
:where(.capability-page) .page-title { display: flex; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
:where(.capability-page) .page-title > div > span { color: #78849a; font-size: 10px; letter-spacing: .7px; }
:where(.capability-page) .page-title h1 { margin: 5px 0 7px; font-size: 26px; letter-spacing: 0; }
:where(.capability-page) .page-title p { margin: 0; color: #69758a; font-size: 13px; line-height: 1.55; }
:where(.capability-page) button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; height: 34px; padding: 0 11px; border: 1px solid #d9e1ec; border-radius: 6px; background: #fff; color: #445167; font-family: inherit; font-size: 13px; cursor: pointer; }
:where(.capability-page) button:hover:not(:disabled) { border-color: #aab8d5; }
:where(.capability-page) button.primary { border-color: #4845d6; background: #4845d6; color: #fff; }
:where(.capability-page) button:disabled { cursor: not-allowed; opacity: .55; }
:where(.capability-page) .icon-button { width: 34px; padding: 0; }
:where(.capability-page) .searchbox { display: flex; align-items: center; gap: 7px; width: 100%; height: 34px; padding: 0 9px; border: 1px solid #dce3ed; border-radius: 5px; background: #fff; color: #738097; }
:where(.capability-page) .searchbox input { width: 250px; border: 0; outline: 0; font-family: inherit; }
:where(.capability-page) .status { display: inline-flex; align-items: center; gap: 6px; color: #a26c24; font-size: 12px; font-style: normal; white-space: nowrap; }
:where(.capability-page) .status > i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
:where(.capability-page) .status.completed { color: #34835b; }
:where(.capability-page) .status.failed { color: #bd4d58; }
:where(.capability-page) .status.researching,
:where(.capability-page) .status.planning,
:where(.capability-page) .status.recalling { color: #4946c7; }
:where(.capability-page) .empty { min-height: 150px; display: flex; align-items: center; justify-content: center; gap: 8px; color: #7b869a; font-size: 13px; }
:where(.capability-page) .spin { animation: capability-spin .9s linear infinite; }
.capability-page .workspace-stage-nav {
  position: sticky;
  top: 0;
  z-index: 40;
  align-self: start;
  background: #fff;
  box-shadow: 0 8px 22px rgb(39 53 82 / 10%);
}
.capability-page .capability-sheet,
.capability-page .capability-deep-research-panel,
.capability-page .task-review-content { scroll-margin-top: 68px; }
.task-review-content.capabilities { container-type: inline-size; }
.capability-page .capability-title-row,
.capability-page .capability-card-actions { flex-wrap: wrap; }

@container (max-width: 700px) {
  .capability-sheet > header { align-items: flex-start; flex-direction: column; gap: 12px; padding: 16px; }
  .capability-sheet h2 { font-size: 18px; line-height: 1.4; overflow-wrap: anywhere; word-break: break-word; }
  .capability-score { width: 100%; min-width: 0; flex-direction: row; gap: 8px; justify-content: flex-start; border-left: 0; border-top: 1px solid #dfe5ef; padding-top: 10px; }
  .capability-score b { font-size: 20px; }
  .capability-portrait { margin: 14px 12px; padding: 14px; }
  .capability-portrait-card { padding: 12px; }
  .capability-portrait-card p { font-size: 12px; line-height: 1.75; }
  .capability-deep-research-panel { padding: 12px; }
  .capability-deep-research-panel > header { align-items: flex-start; }
  .capability-deep-research-panel > header em { margin-left: auto; }
  .deep-research-comparison { margin: 0 12px 14px; }
  .deep-research-comparison > header { align-items: flex-start; flex-direction: column; }
  .deep-research-comparison-grid { grid-template-columns: 1fr; }
}

@media (max-width: 900px) {
  .capability-page { padding: 18px 16px 32px; }
  .capability-page .page-title { flex-direction: column; }
}

@media (max-width: 560px) {
  .capability-page { padding: 14px 12px 84px; }
  .capability-page .workspace-stage-nav { margin-top: -4px; }
}

.dark .capability-page {
  background:
    radial-gradient(circle at 78% -12%, rgb(103 99 225 / 12%), transparent 34%),
    #14171d;
  color: #dfe4ed;
}
@keyframes capability-spin { to { transform: rotate(360deg); } }
</style>
