<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { storeToRefs } from 'pinia'
import {
  Bot,
  BrainCircuit,
  ChevronDown,
  Database,
  FileCheck2,
  FileText,
  GitBranch,
  Layers,
  MessageSquarePlus,
  Minimize2,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Quote,
  RefreshCw,
  Sparkles,
  Target,
  WandSparkles,
  Wrench
} from '@lucide/vue'
import { equipmentApi } from '@/apis/equipment_api'
import { agentApi } from '@/apis/agent_api'
import { useProjectsStore } from '@/stores/projects'
import { useUserStore } from '@/stores/user'
import { projectDisplayName } from '@/utils/projectSelection'
import AgentChatComponent from '@/components/AgentChatComponent.vue'
import EquipmentLegacyDeepSession from '@/components/equipment/EquipmentLegacyDeepSession.vue'
import EquipmentDeepCandidateVersions from '@/components/equipment/EquipmentDeepCandidateVersions.vue'
import EquipmentDeepSessionHistory from '@/components/equipment/EquipmentDeepSessionHistory.vue'
import EquipmentDeepSkillPicker from '@/components/equipment/EquipmentDeepSkillPicker.vue'
import EquipmentDeepStageProjection from '@/components/equipment/EquipmentDeepStageProjection.vue'
import EquipmentModelField from '@/components/equipment/EquipmentModelField.vue'
import { useEquipmentModelPrefill } from '@/composables/useEquipmentModelPrefill'
import {
  CAPABILITY_PORTRAIT_AGENT_SLUG,
  TECHNOLOGY_CABIN_ACTIONS,
  WEAPON_SCHEME_AGENT_SLUG,
  capabilitySeedFocus,
  isTechnologyCabinSection,
  newWeaponDivergencePrompt,
  parsePortraitSections,
  portraitSectionHint,
  portraitSectionPrompt,
  s6CapabilityCardPrompt,
  technologyCabinPrompt
} from '@/utils/equipmentDeepPortraitSections.js'
import { readDeepLaunchCard } from '@/utils/equipmentDeepLaunch.js'
import { deepSessionStatus, normalizeDeepSessions } from '@/utils/equipmentDeepSessions.js'
import { EQUIPMENT_DEEP_SLASH_COMMANDS } from '@/utils/equipmentDeepCommands.js'
import { normalizeEquipmentDeepSkillIds } from '@/utils/equipmentDeepSkills.js'

const route = useRoute()
const router = useRouter()
const projectsStore = useProjectsStore()
const userStore = useUserStore()
const { projects } = storeToRefs(projectsStore)
const loading = ref(false)
const sessionsLoading = ref(true)
const sessionsError = ref('')
const sessionActionId = ref('')
const loadError = ref('')
const sessionSwitchError = ref('')
const sessionSwitching = ref(false)
const pendingSessionId = ref('')
const creating = ref(false)
const branchCreating = ref(false)
const contextOpen = ref(false)
const researchControlOpen = ref(false)
const DEEP_FOCUS_MODE_KEY = 'equipment-deep-conversation-focus-v1'
const readConversationFocusMode = () => {
  if (typeof window === 'undefined') return true
  try {
    return window.localStorage.getItem(DEEP_FOCUS_MODE_KEY) !== 'false'
  } catch {
    return true
  }
}
const conversationFocusMode = ref(readConversationFocusMode())
const createArtifact = ref(false)
const sidebarOpen = ref(true)
const sessions = ref([])
const session = ref(null)
const runs = ref([])
const agents = ref([])
const capabilityVersionRows = ref([])
const sessionCandidateVersionCards = ref([])
const contextOptions = ref({ capability_cards: [], reference_weapons: [] })
const contextOptionsLoading = ref(false)
const contextOptionsError = ref('')
const contextRequestSequence = ref(0)
const sessionRequestSequence = ref(0)
const nativeChat = ref(null)
const sessionHistory = ref(null)
const candidateVersions = ref(null)
const legacySending = ref(false)
const legacyError = ref('')
let legacyPollSequence = 0
const DEEP_SKILL_CACHE_KEY = 'equipment-deep-active-skills-v1'
const readActiveSkillCache = () => {
  if (typeof window === 'undefined') return {}
  try {
    const value = JSON.parse(window.sessionStorage.getItem(DEEP_SKILL_CACHE_KEY) || '{}')
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  } catch {
    return {}
  }
}
const activeSkillIdsBySession = ref(readActiveSkillCache())
const form = ref({
  project_id: '',
  run_id: undefined,
  research_object_type: 'selected',
  capability_card_key: undefined,
  capability_scope: 'all',
  reference_weapon_id: undefined,
  title: '',
  topic: '',
  focus: '',
  model_spec: '',
  agent_slug: 'deep-research',
  knowledge_enabled: true,
  subagents_enabled: true,
  research_mode: 'new_weapon_diverge',
  research_section: ''
})
const { hasDefaultModel } = useEquipmentModelPrefill(form)

const sessionId = computed(() => String(route.params.sessionId || ''))
const selectedHistorySessionId = computed(
  () => pendingSessionId.value || String(session.value?.session_id || '') || sessionId.value
)
// 能力画像卡上的「定向深研 / 追问」带着 cap/run 跳转过来，会话要自动配置好。
const cardKey = computed(() => String(route.query.cap || ''))
const referenceKey = computed(() => String(route.query.reference || ''))
const cardRunId = computed(() => String(route.query.run || ''))
const requestedSection = computed(() => String(route.query.section || '').trim())
const RESEARCH_MODE_IDS = new Set(['section_deepen', 'new_weapon_diverge'])
const resolveResearchMode = (value) => (RESEARCH_MODE_IDS.has(value) ? value : 'section_deepen')
const researchMode = ref('section_deepen')
const activeResearchSection = ref(requestedSection.value)
const provisioning = ref(false)
const prefilledSectionKey = ref('')
const boundSections = computed(() => session.value?.payload?.capability_sections || [])
const boundEquipment = computed(() => String(session.value?.payload?.capability_name || ''))
const boundReferences = computed(() => session.value?.payload?.reference_weapons || [])
const nativeThreadId = computed(() => String(session.value?.payload?.thread_id || ''))
const usesNativeAgent = computed(
  () => session.value?.payload?.runtime === 'agent' && Boolean(nativeThreadId.value)
)
const activeSkillIds = computed({
  get() {
    const id = sessionId.value
    if (id && Object.prototype.hasOwnProperty.call(activeSkillIdsBySession.value, id)) {
      return normalizeEquipmentDeepSkillIds(activeSkillIdsBySession.value[id])
    }
    return normalizeEquipmentDeepSkillIds(session.value?.payload?.active_skill_ids || [])
  },
  set(value) {
    const id = sessionId.value
    if (!id) return
    activeSkillIdsBySession.value = {
      ...activeSkillIdsBySession.value,
      [id]: normalizeEquipmentDeepSkillIds(value)
    }
    if (typeof window !== 'undefined') {
      try {
        window.sessionStorage.setItem(
          DEEP_SKILL_CACHE_KEY,
          JSON.stringify(activeSkillIdsBySession.value)
        )
      } catch {
        // 无痕/受限存储环境仍保留当前页面内的会话选择。
      }
    }
  }
})
const deepRunMeta = computed(() => ({
  equipment_deep_focus: String(session.value?.payload?.focus || ''),
  equipment_deep_mode: researchMode.value,
  equipment_deep_section: activeResearchSection.value,
  equipment_create_artifact: Boolean(createArtifact.value),
  equipment_active_skill_ids: activeSkillIds.value
}))
const isSectionDeepen = computed(() => researchMode.value === 'section_deepen')
const technologyCabinMode = computed(
  () =>
    isSectionDeepen.value &&
    isTechnologyCabinSection(activeResearchSection.value || requestedSection.value)
)
const researchModeLabel = computed(() =>
  technologyCabinMode.value ? '技术攻关舱' : isSectionDeepen.value ? '深化当前装备' : '发散新质武器'
)
const deepActionOptions = computed(() =>
  technologyCabinMode.value
    ? TECHNOLOGY_CABIN_ACTIONS
    : isSectionDeepen.value
      ? [
          { id: 'bottlenecks', label: '拆解技术卡点' },
          { id: 'solutions', label: '设计攻关方案' },
          { id: 'process', label: '推演作战流程' },
          { id: 'mechanism', label: '深挖制胜逻辑' },
          { id: 'revision', label: '形成本栏修订' }
        ]
      : [
          { id: 'orthogonal', label: '生成正交候选' },
          { id: 'compare', label: '比较候选取舍' },
          { id: 'challenge', label: '检验最低成本反制' }
        ]
)
const sessionCapabilities = computed(() => [
  {
    icon: Database,
    label: session.value?.payload?.knowledge_enabled === false ? '知识库关闭' : '知识库检索'
  },
  {
    icon: Network,
    label: session.value?.payload?.subagents_enabled === false ? 'Subagent 关闭' : 'Subagent 协同'
  },
  { icon: Bot, label: session.value?.payload?.agent_name || '装备研究助手' }
])
const agentOptions = computed(() =>
  agents.value.map((item) => ({ value: item.slug, label: item.name || item.slug }))
)
const weaponSchemeAgentAvailable = computed(() =>
  agents.value.some((item) => item.slug === WEAPON_SCHEME_AGENT_SLUG)
)
const capabilityPortraitAgentAvailable = computed(() =>
  agents.value.some((item) => item.slug === CAPABILITY_PORTRAIT_AGENT_SLUG)
)
const recommendedAgentSlug = (
  section = form.value.research_section,
  mode = form.value.research_mode
) => {
  if (isTechnologyCabinSection(section) && weaponSchemeAgentAvailable.value)
    return WEAPON_SCHEME_AGENT_SLUG
  if (mode === 'new_weapon_diverge' && capabilityPortraitAgentAvailable.value)
    return CAPABILITY_PORTRAIT_AGENT_SLUG
  return 'deep-research'
}
const applyRecommendedAgent = (
  section = form.value.research_section,
  mode = form.value.research_mode
) => {
  form.value.agent_slug = recommendedAgentSlug(section, mode)
}
const researchAgentSlug = (
  section = form.value.research_section,
  mode = form.value.research_mode
) => form.value.agent_slug || recommendedAgentSlug(section, mode)
const researchContext = computed(() => session.value?.research_context || {})
const branchItems = computed(() => session.value?.branches || [])
const filteredRuns = computed(() =>
  runs.value.filter((item) => !form.value.project_id || item.project_id === form.value.project_id)
)
const capabilityCards = computed(() => contextOptions.value.capability_cards || [])
const referenceWeapons = computed(() => contextOptions.value.reference_weapons || [])
const selectedRun = computed(() =>
  runs.value.find((item) => String(item.run_id || '') === String(form.value.run_id || ''))
)
const selectedRunReadOnly = computed(() => Boolean(selectedRun.value?.readonly))
const isReadOnlyRun = (run) => Boolean(run?.readonly)
const activeRun = computed(() => {
  const runId = String(session.value?.run_id || form.value.run_id || cardRunId.value || '')
  return runs.value.find((item) => String(item.run_id || '') === runId)
})
const relatedSessionCount = computed(() => {
  const runId = String(activeRun.value?.run_id || '')
  return runId ? sessions.value.filter((item) => String(item.run_id || '') === runId).length : 0
})
const historyCurrentRunId = computed(() =>
  String(cardRunId.value || form.value.run_id || activeRun.value?.run_id || '')
)
const viewingArchivedSession = computed(() => deepSessionStatus(session.value) === 'archived')
const selectedCapability = computed(() => {
  if (form.value.research_object_type !== 'selected') return undefined
  return capabilityCards.value.find((item) => item.card_key === form.value.capability_card_key)
})
const selectedCapabilitySections = computed(() => {
  if (!selectedCapability.value) return []
  const sections = parsePortraitSections(
    selectedCapability.value.deep_capability_portrait || selectedCapability.value.capability_image
  )
  if (form.value.capability_scope === 'all') return sections
  return sections.filter((item) => item.label === form.value.capability_scope)
})
const capabilitySectionOptions = computed(() => {
  if (!selectedCapability.value) return [{ value: 'all', label: '全部五栏' }]
  const sections = parsePortraitSections(
    selectedCapability.value.deep_capability_portrait || selectedCapability.value.capability_image
  )
  return [
    { value: 'all', label: `全部五栏（${sections.length} 栏）` },
    ...sections.map((item) => ({ value: item.label, label: item.label }))
  ]
})
const selectedReference = computed(() => {
  if (form.value.research_object_type !== 'reference') return undefined
  return referenceWeapons.value.find(
    (item) => item.hypothesis_id === form.value.reference_weapon_id
  )
})
const selectedScopeLabel = computed(() =>
  form.value.capability_scope === 'all' ? '全部五栏' : form.value.capability_scope
)
const contextBindingSummary = computed(() => {
  const parts = []
  if (selectedCapability.value) {
    parts.push(`${capabilityEquipmentName(selectedCapability.value)} · ${selectedScopeLabel.value}`)
  }
  if (selectedReference.value) parts.push(`参考武器 · ${selectedReference.value.title}`)
  return parts.join(' / ')
})
const suggestedTopic = ref('')
const suggestedFocus = ref('')

const syncNativeThread = async () => {
  if (!nativeThreadId.value) return
  await nextTick()
  const selected = await nativeChat.value?.selectThreadFromRoute(nativeThreadId.value)
  if (selected === false) {
    throw new Error('平台原生会话不存在或无权访问')
  }
}

const loadList = async () => {
  sessionsLoading.value = true
  sessionsError.value = ''
  try {
    const [loadedProjects, agentResponse, sessionResponse, runResponse] = await Promise.all([
      projectsStore.loadProjects().catch(() => []),
      agentApi.getAgents().catch(() => ({ agents: [] })),
      equipmentApi.listDeepSessions().catch((error) => {
        sessionsError.value = error.message || '无法读取专家会话。'
        return []
      }),
      equipmentApi.listRuns().catch(() => [])
    ])
    agents.value = agentResponse?.agents || []
    applyRecommendedAgent(requestedSection.value || form.value.research_section)
    sessions.value = normalizeDeepSessions(sessionResponse)
    runs.value = runResponse || []
    const ownProjects = loadedProjects.filter(
      (project) => String(project.uid || '') === String(userStore.uid || '')
    )
    const defaultProject = ownProjects[0] || (await projectsStore.ensureEquipmentProject())
    const requestedRun = runs.value.find((item) => String(item.run_id || '') === cardRunId.value)
    if (!sessionId.value && requestedRun) {
      if (requestedRun.project_id) form.value.project_id = requestedRun.project_id
      form.value.run_id = requestedRun.run_id
    }
    if (!form.value.project_id && defaultProject?.id) form.value.project_id = defaultProject.id
    if (!agentOptions.value.some((item) => item.value === form.value.agent_slug)) {
      form.value.agent_slug =
        agentOptions.value.find((item) => item.value === 'deep-research')?.value ||
        agentOptions.value[0]?.value ||
        'deep-research'
    }
  } finally {
    sessionsLoading.value = false
  }
}

const loadContextOptions = async (runId) => {
  const sequence = ++contextRequestSequence.value
  contextOptions.value = { capability_cards: [], reference_weapons: [] }
  contextOptionsError.value = ''
  if (!runId) return
  contextOptionsLoading.value = true
  try {
    const response = await equipmentApi.getDeepContextOptions(runId)
    if (sequence !== contextRequestSequence.value) return
    contextOptions.value = {
      capability_cards: response?.selected_weapons || response?.capability_cards || [],
      reference_weapons: response?.reference_weapons || []
    }
    if (
      !contextOptions.value.capability_cards.length &&
      contextOptions.value.reference_weapons.length
    ) {
      form.value.research_object_type = 'reference'
    } else if (
      !contextOptions.value.reference_weapons.length &&
      contextOptions.value.capability_cards.length
    ) {
      form.value.research_object_type = 'selected'
    }
  } catch (error) {
    if (sequence !== contextRequestSequence.value) return
    contextOptionsError.value = error.message || '研究对象加载失败'
  } finally {
    if (sequence === contextRequestSequence.value) contextOptionsLoading.value = false
  }
}

const updateResearchSuggestions = () => {
  const capabilityName = selectedCapability.value
    ? capabilityEquipmentName(selectedCapability.value)
    : ''
  const referenceName = String(selectedReference.value?.title || '').trim()
  const runTopic = String(selectedRun.value?.topic || '').trim()
  const seedName = capabilityName || referenceName
  const scopedSection = selectedCapabilitySections.value[0]
  const deepenCurrent = form.value.research_mode === 'section_deepen' && capabilityName
  form.value.research_section = deepenCurrent && scopedSection ? scopedSection.label : ''
  const nextTopic = deepenCurrent
    ? scopedSection
      ? `深化「${capabilityName}」的「${scopedSection.label}」栏并形成可核验修订`
      : `深化「${capabilityName}」现有能力画像，破解技术卡点并闭合作战流程与制胜逻辑`
    : runTopic
      ? `面向「${runTopic}」发散未来制胜新质武器装备${seedName ? `（以「${seedName}」为启发）` : ''}`
      : seedName
        ? `以「${seedName}」为启发，发散未来制胜新质武器装备`
        : ''
  const contextLead = runTopic
    ? `以关联 Query「${runTopic}」及其未来战争态势为核心问题空间`
    : '以未来战争态势下的制胜与制衡需求为核心问题空间'
  const seedContext = capabilityName
    ? `当前能力画像「${capabilityName}」及${selectedScopeLabel.value}仅作为启发与待突破基线，不是候选边界`
    : referenceName
      ? `参考武器「${referenceName}」仅作为启发与对照基线，不是候选边界`
      : '现有装备与技术路线仅作为启发和对照基线，不是候选边界'
  const nextFocus = deepenCurrent
    ? scopedSection
      ? portraitSectionPrompt(scopedSection.label, capabilityName, scopedSection.text)
      : capabilitySeedFocus(capabilityName, selectedCapabilitySections.value)
    : [
        `${contextLead}，开放发散能够形成制胜优势、制衡对手的新质创新颠覆武器装备`,
        seedContext,
        '从任务链反转、作用机理、装备构型、交战窗口、成本交换和对手反适应等多维探索正交方向',
        '不预设单一装备形态、技术路线或固定结论，先扩大解空间，再按作战价值、颠覆性与可行性收敛'
      ].join('；')

  if (!form.value.topic.trim() || form.value.topic === suggestedTopic.value)
    form.value.topic = nextTopic
  if (!form.value.focus.trim() || form.value.focus === suggestedFocus.value)
    form.value.focus = nextFocus
  suggestedTopic.value = nextTopic
  suggestedFocus.value = nextFocus
}

const loadSession = async () => {
  const sequence = ++sessionRequestSequence.value
  const requestedSessionId = sessionId.value
  const previousSession = session.value
  const previousResearchMode = researchMode.value
  const previousResearchSection = activeResearchSection.value
  if (!requestedSessionId) {
    session.value = null
    pendingSessionId.value = ''
    sessionSwitching.value = false
    sessionSwitchError.value = ''
    return
  }
  const retainsCurrentSession = Boolean(
    previousSession && String(previousSession.session_id || '') !== requestedSessionId
  )
  pendingSessionId.value = requestedSessionId
  sessionSwitching.value = true
  sessionSwitchError.value = ''
  try {
    const response = await equipmentApi.getDeepSession(requestedSessionId)
    if (sequence !== sessionRequestSequence.value || requestedSessionId !== sessionId.value) return
    session.value = response
    const payload = response?.payload || {}
    // 旧会话可能没有 research_mode。此时保持装备身份的栏目深化更保守，
    // 只有服务端明确保存 new_weapon_diverge 时才进入开放发散模式。
    researchMode.value = requestedSection.value
      ? 'section_deepen'
      : resolveResearchMode(payload.research_mode)
    activeResearchSection.value =
      requestedSection.value || String(payload.research_section || '').trim()
    contextOpen.value = false
    await syncNativeThread()
    if (sequence !== sessionRequestSequence.value || requestedSessionId !== sessionId.value) return
    // 原生会话切换会恢复该线程自己的草稿，因此栏目深挖问题必须在切换完成后
    // 最后写入一次，避免先预填、后被线程草稿覆盖为空。
    if (requestedSection.value) {
      prefilledSectionKey.value = ''
      await prefillRequestedSection()
    }
  } catch (error) {
    if (sequence !== sessionRequestSequence.value || requestedSessionId !== sessionId.value) return
    if (!retainsCurrentSession) throw error

    // 历史会话打开失败时保留用户正在阅读的内容，避免退回新建表单或空白页。
    session.value = previousSession
    researchMode.value = previousResearchMode
    activeResearchSection.value = previousResearchSection
    sessionSwitchError.value = error.message || '历史对话打开失败，请重试。'
    await nextTick()
    await syncNativeThread().catch(() => undefined)
    message.error(sessionSwitchError.value)
  } finally {
    if (sequence === sessionRequestSequence.value && requestedSessionId === sessionId.value) {
      pendingSessionId.value = ''
      sessionSwitching.value = false
    }
  }
}

const LEGACY_TERMINAL_STATUSES = new Set([
  'completed',
  'failed',
  'blocked',
  'cancelled',
  'canceled',
  'rejected',
  'partial'
])

const waitForLegacyRefresh = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds))

const refreshLegacySession = async (expectedSessionId) => {
  const response = await equipmentApi.getDeepSession(expectedSessionId)
  if (expectedSessionId !== sessionId.value || usesNativeAgent.value) return null
  session.value = response
  sessions.value = sessions.value.map((item) =>
    item.session_id === response?.session_id ? { ...item, ...response } : item
  )
  return response
}

const submitLegacyMessage = async (content) => {
  const expectedSessionId = sessionId.value
  if (!expectedSessionId || usesNativeAgent.value || legacySending.value) return
  const pollSequence = ++legacyPollSequence
  legacySending.value = true
  legacyError.value = ''
  try {
    const submitted = await equipmentApi.sendDeepMessage(expectedSessionId, {
      content,
      model_spec: session.value?.payload?.model_spec || undefined,
      focus: String(session.value?.payload?.focus || ''),
      create_artifact: false,
      active_skill_ids: session.value?.payload?.active_skill_ids || []
    })
    const jobId = String(submitted?.job?.job_id || submitted?.job?.id || '')
    let current = await refreshLegacySession(expectedSessionId)

    // 旧运行时没有 SSE。按低频、有限次数刷新当前 Job，既让导入会话可继续追问，
    // 也避免空闲页面持续轮询或重新拉取整套研究数据。
    for (let attempt = 0; attempt < 48; attempt += 1) {
      if (
        pollSequence !== legacyPollSequence ||
        expectedSessionId !== sessionId.value ||
        usesNativeAgent.value
      ) {
        return
      }
      const jobs = Array.isArray(current?.jobs) ? current.jobs : []
      const currentJob = jobId
        ? jobs.find((item) => String(item?.job_id || item?.id || '') === jobId)
        : jobs[0]
      const status = String(currentJob?.status || '').toLowerCase()
      if (status && LEGACY_TERMINAL_STATUSES.has(status)) break
      await waitForLegacyRefresh(attempt < 6 ? 1500 : 3000)
      current = await refreshLegacySession(expectedSessionId)
    }
    await loadList()
  } catch (error) {
    if (pollSequence === legacyPollSequence) {
      legacyError.value = error.message || '旧版深研追问提交失败'
      message.error(legacyError.value)
    }
  } finally {
    if (pollSequence === legacyPollSequence) legacySending.value = false
  }
}

const load = async () => {
  loading.value = true
  loadError.value = ''
  try {
    await Promise.all([loadList(), loadSession()])
  } catch (error) {
    loadError.value = error.message || '深研对话加载失败'
    message.error(loadError.value)
  } finally {
    loading.value = false
  }
}

const createSession = async () => {
  if (selectedRunReadOnly.value) {
    message.warning('历史研究任务为只读数据')
    return
  }
  if (!form.value.project_id || !(form.value.topic || form.value.title).trim()) {
    message.warning('请填写项目与研讨主题')
    return
  }
  creating.value = true
  try {
    const created = await equipmentApi.createDeepSession({
      project_id: form.value.project_id,
      title: form.value.title,
      topic: form.value.topic,
      focus: form.value.focus,
      run_id: form.value.run_id || undefined,
      model_spec: form.value.model_spec || undefined,
      agent_slug: researchAgentSlug(),
      knowledge_enabled: form.value.knowledge_enabled,
      subagents_enabled: form.value.subagents_enabled,
      research_mode: form.value.research_mode,
      research_section: form.value.research_section,
      capability_card_key: selectedCapability.value?.card_key || '',
      capability_name: selectedCapability.value
        ? capabilityEquipmentName(selectedCapability.value)
        : '',
      capability_sections: selectedCapabilitySections.value,
      reference_weapons: selectedReference.value ? [selectedReference.value] : []
    })
    form.value.topic = ''
    form.value.title = ''
    form.value.focus = ''
    await loadList()
    await router.push(`/equipment/deep-thinking/${created.session_id}`)
  } catch (error) {
    message.error(error.message || '创建会话失败')
  } finally {
    creating.value = false
  }
}

const capabilityEquipmentName = (card) =>
  String(
    card?.equipment_name ||
      card?.primary_equipment_identity ||
      card?.name ||
      card?.title ||
      card?.capability_name ||
      ''
  ).trim() || '未命名装备'

const matchesCardKey = (card, key) =>
  [card?.version_id, card?.card_binding_id, card?.card_key, card?.capability_id, card?.id].some(
    (value) => String(value || '') === key
  )

const matchesReferenceKey = (item, key) =>
  [item?.hypothesis_id, item?.card_binding_id, item?.title, item?.primary_equipment_identity].some(
    (value) => String(value || '') === key
  )

/**
 * 从能力画像卡直接进入时，不再让用户手填表单：定位卡片、解析五栏、
 * 以五栏为种子建会话，然后换到该会话路由。
 */
const provisionFromCard = async () => {
  if (sessionId.value || !cardKey.value || provisioning.value) return
  provisioning.value = true
  try {
    const existing = sessions.value.find((item) => {
      if (String(item?.payload?.capability_card_key || '') !== cardKey.value) return false
      if (!requestedSection.value) return true
      return String(item?.payload?.research_section || '').trim() === requestedSection.value
    })
    if (existing) {
      await router.replace({
        path: `/equipment/deep-thinking/${existing.session_id}`,
        query: requestedSection.value ? { section: requestedSection.value } : {}
      })
      return
    }
    // 工作台点卡时已把卡片内容交接过来；它与平台能力表不是同一个库，
    // 所以先用交接内容，取不到再回查平台能力表。
    const handoff = readDeepLaunchCard(cardKey.value)
    let name = String(handoff?.name || '').trim()
    let sections = Array.isArray(handoff?.sections) ? handoff.sections : []
    let runId = String(handoff?.run_id || '')
    if (!sections.length) {
      const cards = (await equipmentApi.listCapabilities()) || []
      const card = cards.find((item) => matchesCardKey(item, cardKey.value))
      if (!card) {
        message.warning('未找到该能力画像卡，请手动配置深研会话')
        return
      }
      name = capabilityEquipmentName(card)
      sections = parsePortraitSections(card.deep_capability_portrait || card.capability_image)
      runId = String(card.run_id || '')
    }
    if (!name) name = '未命名装备'
    const sectionLabel = requestedSection.value || String(handoff?.section_label || '').trim()
    const section = sections.find((item) => String(item?.label || '').trim() === sectionLabel)
    form.value.research_mode = 'section_deepen'
    form.value.research_section = section?.label || ''
    const sectionFocus = section
      ? portraitSectionPrompt(section.label, name, section.text)
      : capabilitySeedFocus(name, sections)
    const feedbackComment = String(handoff?.source_feedback_comment || '').trim()
    const resolvedFocus = feedbackComment
      ? [
          sectionFocus,
          `专家反馈驱动：${feedbackComment}`,
          '优先深挖装备与技术实现中的研发卡点、关键技术痛点及解决路径，并联动作战流程与制胜逻辑；证据缺口、工程瓶颈、失效边界、验证动作和修订建议按问题需要展开，不机械凑项。'
        ]
          .filter(Boolean)
          .join('；')
      : sectionFocus
    const technologyCabin = isTechnologyCabinSection(section?.label)
    if (technologyCabin && weaponSchemeAgentAvailable.value) {
      form.value.agent_slug = WEAPON_SCHEME_AGENT_SLUG
    }
    const sessionTitle = technologyCabin
      ? `技术攻关舱 · ${name}`
      : section
        ? `深挖${section.label} · ${name}`
        : `定向深研 · ${name}`
    const sessionTopic = technologyCabin
      ? `面向「${name}」形成武器装备研究方案，贯通能力目标、总体设计、技术体系、关键技术、突破难点、解决路径与具体实现`
      : section
        ? `深挖「${name}」能力画像的「${section.label}」栏并形成可核验修订`
        : `以能力画像卡「${name}」为启发，面向关联 Query 发散未来制胜新质武器装备`
    const targetRunId = cardRunId.value || runId || ''
    form.value.run_id = targetRunId || form.value.run_id
    form.value.topic = sessionTopic
    form.value.focus = resolvedFocus
    form.value.title = sessionTitle
    const targetRun = runs.value.find(
      (item) => String(item.run_id || '') === String(targetRunId || '')
    )
    if (isReadOnlyRun(targetRun)) {
      message.warning('当前研究任务为只读数据')
      return
    }
    if (!form.value.project_id) {
      message.warning('请先选择所属项目后再创建深研会话')
      return
    }
    const payload = {
      project_id: form.value.project_id,
      title: sessionTitle,
      topic: `${sessionTopic}。`,
      focus: resolvedFocus,
      run_id: targetRunId || undefined,
      model_spec: form.value.model_spec || undefined,
      agent_slug: researchAgentSlug(section?.label),
      knowledge_enabled: form.value.knowledge_enabled,
      subagents_enabled: form.value.subagents_enabled,
      research_mode: 'section_deepen',
      research_section: section?.label || '',
      source_feedback_id: String(handoff?.source_feedback_id || ''),
      capability_card_key: cardKey.value,
      capability_name: name,
      capability_sections: sections
    }
    const created = await equipmentApi.createDeepSession(payload)
    if (!created?.session_id) throw new Error('深研会话已创建，但未返回会话编号')
    await loadList()
    await router.replace({
      path: `/equipment/deep-thinking/${created.session_id}`,
      query: section ? { section: section.label } : {}
    })
  } catch (error) {
    form.value.run_id = cardRunId.value || form.value.run_id
    form.value.title = form.value.title || `定向深研 · ${cardKey.value}`
    message.error(error.message || '定向深研自动配置失败，请手动创建会话')
  } finally {
    provisioning.value = false
  }
}

/**
 * 参考武器卡与正式能力卡使用不同绑定字段。路由带 reference 时先从
 * 当前 Run 的服务器上下文解析对象，再复用或创建绑定该参考武器的会话。
 */
const provisionFromReference = async () => {
  if (sessionId.value || cardKey.value || !referenceKey.value || provisioning.value) return
  provisioning.value = true
  try {
    const existing = sessions.value.find((item) => {
      const boundRunId = String(item?.run_id || item?.payload?.run_id || '')
      if (cardRunId.value && boundRunId && boundRunId !== cardRunId.value) return false
      const references = Array.isArray(item?.payload?.reference_weapons)
        ? item.payload.reference_weapons
        : []
      return references.some((reference) => matchesReferenceKey(reference, referenceKey.value))
    })
    if (existing) {
      await router.replace(`/equipment/deep-thinking/${existing.session_id}`)
      return
    }

    const runId = cardRunId.value || String(form.value.run_id || '')
    if (!runId) {
      message.warning('未找到参考武器所属研究任务，请手动配置深研会话')
      return
    }
    const requestedRun = runs.value.find((item) => String(item.run_id || '') === runId)
    if (requestedRun?.project_id) form.value.project_id = requestedRun.project_id
    form.value.run_id = runId
    if (isReadOnlyRun(requestedRun)) {
      message.warning('当前研究任务为只读数据')
      return
    }
    await loadContextOptions(runId)
    const reference = referenceWeapons.value.find((item) =>
      matchesReferenceKey(item, referenceKey.value)
    )
    if (!reference) {
      message.warning('未找到该参考武器，请手动配置深研会话')
      return
    }
    form.value.research_object_type = 'reference'
    form.value.research_mode = 'new_weapon_diverge'
    form.value.research_section = ''
    applyRecommendedAgent('', 'new_weapon_diverge')
    form.value.reference_weapon_id = reference.hypothesis_id
    updateResearchSuggestions()

    const name = String(
      reference.title || reference.primary_equipment_identity || '参考武器'
    ).trim()
    if (!form.value.project_id) {
      form.value.title = `定向深研 · ${name}`
      message.warning('请先选择所属项目后再创建深研会话')
      return
    }
    const created = await equipmentApi.createDeepSession({
      project_id: form.value.project_id,
      title: `定向深研 · ${name}`,
      topic: form.value.topic || `以参考武器「${name}」为启发，发散未来制胜新质武器装备。`,
      focus: form.value.focus,
      run_id: runId,
      model_spec: form.value.model_spec || undefined,
      agent_slug: researchAgentSlug('', 'new_weapon_diverge'),
      knowledge_enabled: form.value.knowledge_enabled,
      subagents_enabled: form.value.subagents_enabled,
      research_mode: 'new_weapon_diverge',
      research_section: '',
      reference_weapons: [reference]
    })
    if (!created?.session_id) throw new Error('深研会话已创建，但未返回会话编号')
    await loadList()
    await router.replace(`/equipment/deep-thinking/${created.session_id}`)
  } catch (error) {
    form.value.run_id = cardRunId.value || form.value.run_id
    form.value.research_object_type = 'reference'
    form.value.reference_weapon_id = referenceKey.value
    message.error(error.message || '参考武器深研自动配置失败，请手动创建会话')
  } finally {
    provisioning.value = false
  }
}

const provisionFromRoute = async () => {
  if (cardKey.value) await provisionFromCard()
  else if (referenceKey.value) await provisionFromReference()
}

const sectionHint = portraitSectionHint

const prefillRequestedSection = async () => {
  if (!sessionId.value || !usesNativeAgent.value || !requestedSection.value) return
  const section = boundSections.value.find(
    (item) => String(item?.label || '').trim() === requestedSection.value
  )
  if (!section) return
  const key = `${sessionId.value}:${section.label}`
  if (prefilledSectionKey.value === key) return
  await nextTick()
  const prompt = portraitSectionPrompt(section.label, boundEquipment.value, section.text)
  if (!prompt || !nativeChat.value?.submitPrompt) return
  researchMode.value = 'section_deepen'
  activeResearchSection.value = section.label
  await nativeChat.value.submitPrompt(prompt, { send: false, onlyIfEmpty: true })
  prefilledSectionKey.value = key
}

const diveIntoSection = async (item) => {
  researchMode.value = 'section_deepen'
  activeResearchSection.value = String(item?.label || '').trim()
  const prompt = portraitSectionPrompt(item.label, boundEquipment.value, item.text)
  if (prompt) await nativeChat.value?.submitPrompt(prompt, { send: false })
}

const prefillDeepAction = async (actionId) => {
  const target = boundEquipment.value || '当前装备'
  const section = activeResearchSection.value || '当前画像栏目'
  const sectionBody = boundSections.value.find(
    (item) => String(item?.label || '').trim() === section
  )?.text
  const sectionPrompts = {
    bottlenecks: `围绕研发「${target}」深挖「${section}」：拆解关键技术卡点、工程痛点、指标耦合和系统集成难题，逐项说明根因、影响链路与必须突破的程度，不要只罗列技术名词。`,
    solutions: `针对「${target}」的「${section}」技术卡点，设计至少三条同装备攻关路线：写清原理、关键分系统、指标改善、技术成熟度、依赖条件、工程代价、关键试验和路线取舍，不生成其他装备。`,
    process: `围绕「${target}」推演关键作战流程：闭合平台与人员角色、信息流和火力流、发现—决策—进入—作用—评估时序、协同接口与关键窗口，并反推「${section}」需要满足的技术要求。`,
    mechanism: `围绕「${target}」的制胜逻辑深度发散：从作用链、信息优势、时空窗口、成本交换、体系增益和对手反适应等角度提出多条机理解释，再把每条机理闭合到必要技术和作战动作；保持装备身份不变。`,
    revision: `综合当前对话，为「${target}」的「${section}」形成可直接评审的本栏修订建议，重点写清技术卡点、解决路径、作战流程衔接和制胜机理；证据、边界与验证动作仅在影响方案成立或路线选择时补充。`
  }
  const divergencePrompts = {
    orthogonal: newWeaponDivergencePrompt(target, section),
    compare:
      '比较当前新质武器候选：按任务链变化、直接作用机理、体系角色、军事价值、技术可行性与对手最低成本反制形成可见取舍，不要把相似构型重复计为不同方向。',
    challenge:
      '对当前优先候选做红队检验：寻找对手最低成本反制、关键假设失效、交战窗口坍缩和成本交换逆转条件，并给出保留、重构或淘汰建议。'
  }
  const prompt = technologyCabinMode.value
    ? technologyCabinPrompt(target, sectionBody, actionId)
    : (isSectionDeepen.value ? sectionPrompts : divergencePrompts)[actionId]
  if (prompt) await nativeChat.value?.submitPrompt(prompt, { send: false })
}

const authorNextCard = async () => {
  createArtifact.value = true
  await nextTick()
  await nativeChat.value?.submitPrompt(
    s6CapabilityCardPrompt(
      boundEquipment.value || '当前装备',
      '综合本次深研结论重写一版能力画像，保持装备身份和任务定位不变，重点吸收技术卡点与攻关路线、作战流程推演和制胜机理深化结论；确有关键不确定性时再标注待核验'
    ),
    { send: false }
  )
  researchControlOpen.value = false
}

const focusCandidateDirection = async (item) => {
  const name = String(item?.name || '').trim()
  if (!name) return
  await nativeChat.value?.submitPrompt(
    `聚焦候选方向「${name}」继续深化：说明它改变了哪项关键假设，闭合打击对象、直接作用机理、任务失能判据、对手反制与下一步可证伪验证。`,
    { send: false }
  )
}

const authorCandidateCard = async (item) => {
  const name = String(item?.name || '').trim()
  if (!name) return
  createArtifact.value = true
  await nextTick()
  await nativeChat.value?.submitPrompt(
    s6CapabilityCardPrompt(
      name,
      `确认将已收敛候选方向「${name}」成卡，保持装备身份和作用机理一致，写清直接军事价值、对抗边界及证据缺口`
    )
  )
}

const messageText = (item) => {
  const content = item?.content
  if (typeof content === 'string') return content.trim()
  if (!Array.isArray(content)) return ''
  return content
    .map((part) => (typeof part === 'string' ? part : part?.text || part?.content || ''))
    .filter(Boolean)
    .join('\n')
    .trim()
}

const quoteMessage = async (item) => {
  const excerpt = messageText(item).slice(0, 4000)
  if (!excerpt) {
    message.warning('该回答没有可引用的文本')
    return
  }
  const quote = excerpt
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')
  await nativeChat.value?.submitPrompt(
    `${quote}\n\n请针对上述引用继续深化：闭合打击对象、直接毁伤机理与任务失能判据。`,
    { send: false }
  )
}

const selectSession = (item) => {
  const id = String(item?.session_id || item || '')
  if (!id) return
  if (id === sessionId.value && !sessionSwitching.value) return
  pendingSessionId.value = id
  sessionSwitching.value = true
  sessionSwitchError.value = ''
  const preservedRunId = String(route.query.run || '')
  return router.push({
    path: `/equipment/deep-thinking/${encodeURIComponent(id)}`,
    query: preservedRunId ? { run: preservedRunId } : {}
  })
}
const startNew = () => {
  const runId = String(activeRun.value?.run_id || session.value?.run_id || cardRunId.value || '')
  return router.push({
    path: '/equipment/deep-thinking',
    query: runId ? { run: runId } : {}
  })
}
const openRunWorkspace = (target = 'runs') => {
  const runId = String(activeRun.value?.run_id || session.value?.run_id || cardRunId.value || '')
  if (!runId) return router.push('/equipment/runs')
  if (target === 'capabilities')
    return router.push(`/equipment/capabilities?run=${encodeURIComponent(runId)}`)
  if (target === 'reports')
    return router.push(`/equipment/reports?run=${encodeURIComponent(runId)}`)
  return router.push(`/equipment/runs/${encodeURIComponent(runId)}`)
}
const toggleSidebar = () => {
  sidebarOpen.value = !sidebarOpen.value
}
const setConversationFocus = (enabled) => {
  conversationFocusMode.value = Boolean(enabled)
  researchControlOpen.value = false
  if (conversationFocusMode.value) contextOpen.value = false
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(DEEP_FOCUS_MODE_KEY, String(conversationFocusMode.value))
    } catch {
      // 受限存储环境仍保留当前页面内的专注模式状态。
    }
  }
}
const toggleConversationFocus = () => setConversationFocus(!conversationFocusMode.value)
const openResearchOverview = () => setConversationFocus(false)
const setResearchMode = (mode) => {
  if (!RESEARCH_MODE_IDS.has(mode)) return
  researchMode.value = mode
  createArtifact.value = false
}
const selectResearchSection = async (item) => {
  await diveIntoSection(item)
  researchControlOpen.value = false
}
const selectDeepAction = async (actionId) => {
  await prefillDeepAction(actionId)
  researchControlOpen.value = false
}
const startMention = (group) => nativeChat.value?.startMention(group)
const forkFrom = async (item) => {
  if (!sessionId.value || branchCreating.value) return
  branchCreating.value = true
  try {
    const created = await equipmentApi.forkDeepSession(sessionId.value, {
      from_message_id: String(item?.id || item?.message_id || ''),
      title: `${session.value?.title || '深研'} · 探索分支`
    })
    await loadList()
    await router.push(`/equipment/deep-thinking/${created.session.session_id}`)
  } catch (error) {
    message.error(error.message || '创建研究分支失败')
  } finally {
    branchCreating.value = false
  }
}

const handleRunSubmitted = () => {
  createArtifact.value = false
}

const handleRunCompleted = async () => {
  createArtifact.value = false
  const expectedSessionId = sessionId.value
  try {
    const latest = await equipmentApi.getDeepSession(expectedSessionId)
    if (expectedSessionId === sessionId.value) session.value = latest
    await Promise.all([loadList(), candidateVersions.value?.refresh?.()])
  } catch (error) {
    message.warning(error.message || '深研成果状态刷新失败，可稍后手动重载')
  }
}

const handleCapabilityVersionsLoaded = (payload) => {
  capabilityVersionRows.value = Array.isArray(payload?.versions) ? payload.versions : []
  sessionCandidateVersionCards.value = Array.isArray(payload?.candidates) ? payload.candidates : []
  if (payload?.action && typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('equipment-capabilities-changed', {
        detail: { runId: payload.runId, sessionId: payload.sessionId, action: payload.action }
      })
    )
  }
}

const replaceSession = (updated) => {
  if (!updated?.session_id) return
  sessions.value = sessions.value.map((item) =>
    item.session_id === updated.session_id ? { ...item, ...updated } : item
  )
  if (session.value?.session_id === updated.session_id) {
    session.value = { ...session.value, ...updated }
  }
}

const manageSession = async (item, changes) => {
  if (!item?.session_id || sessionActionId.value) return false
  sessionActionId.value = item.session_id
  sessionsError.value = ''
  try {
    const response = await equipmentApi.updateDeepSession(item.session_id, changes)
    const updated = response?.session || response
    replaceSession(updated)
    if (changes.archived === false) sessionHistory.value?.showCurrent()
    if (changes.archived === true && sessionId.value === item.session_id) {
      const runId = String(item.run_id || route.query.run || '')
      await router.push({ path: '/equipment/deep-thinking', query: runId ? { run: runId } : {} })
    }
    await loadList()
    return true
  } catch (error) {
    sessionsError.value = error.message || '会话管理失败。'
    message.error(sessionsError.value)
    return false
  } finally {
    sessionActionId.value = ''
  }
}

const renameSession = ({ item, title }) => manageSession(item, { title })
const archiveSession = (item) => manageSession(item, { archived: true })
const restoreSession = (item) => manageSession(item, { archived: false })

const deleteSession = async (item) => {
  if (!item?.session_id || sessionActionId.value) return
  sessionActionId.value = item.session_id
  sessionsError.value = ''
  try {
    await equipmentApi.deleteDeepSession(item.session_id)
    sessions.value = sessions.value.filter((row) => row.session_id !== item.session_id)
    if (sessionId.value === item.session_id) {
      const runId = String(item.run_id || route.query.run || '')
      await router.push({ path: '/equipment/deep-thinking', query: runId ? { run: runId } : {} })
    }
  } catch (error) {
    sessionsError.value = error.message || '删除对话失败。'
    message.error(sessionsError.value)
  } finally {
    sessionActionId.value = ''
  }
}

watch(sessionId, async () => {
  legacyPollSequence += 1
  legacySending.value = false
  legacyError.value = ''
  capabilityVersionRows.value = []
  sessionCandidateVersionCards.value = []
  loading.value = true
  loadError.value = ''
  try {
    await loadSession()
  } catch (error) {
    loadError.value = error.message || '深研会话加载失败'
    message.error(loadError.value)
  } finally {
    loading.value = false
  }
})
watch([cardKey, referenceKey], () => void provisionFromRoute())
watch(
  [() => session.value?.session_id, requestedSection, usesNativeAgent],
  () => void prefillRequestedSection(),
  { flush: 'post' }
)
watch(cardRunId, (runId) => {
  if (sessionId.value || !runId) return
  const requestedRun = runs.value.find((item) => String(item.run_id || '') === runId)
  if (!requestedRun) return
  if (requestedRun.project_id) form.value.project_id = requestedRun.project_id
  form.value.run_id = requestedRun.run_id
  updateResearchSuggestions()
})
watch(
  () => form.value.project_id,
  () => {
    if (
      form.value.run_id &&
      !filteredRuns.value.some((item) => item.run_id === form.value.run_id)
    ) {
      form.value.run_id = undefined
    }
  }
)
watch(
  () => form.value.run_id,
  (runId) => {
    form.value.capability_card_key = undefined
    form.value.capability_scope = 'all'
    form.value.reference_weapon_id = undefined
    void loadContextOptions(runId)
    updateResearchSuggestions()
  }
)
watch(
  () => form.value.research_object_type,
  (type) => {
    if (type === 'reference') {
      form.value.capability_card_key = undefined
      form.value.capability_scope = 'all'
      form.value.research_mode = 'new_weapon_diverge'
    } else {
      form.value.reference_weapon_id = undefined
      form.value.research_mode = 'section_deepen'
    }
    updateResearchSuggestions()
  }
)
watch(selectedCapability, (capability, previous) => {
  if (capability && !previous) form.value.research_mode = 'section_deepen'
  updateResearchSuggestions()
})
watch([() => form.value.capability_scope, selectedReference], () => updateResearchSuggestions())
watch(
  () => form.value.research_mode,
  (mode) => {
    applyRecommendedAgent(form.value.research_section, mode)
    updateResearchSuggestions()
  }
)
watch(
  () => form.value.research_section,
  (section) => {
    applyRecommendedAgent(section, form.value.research_mode)
  }
)

onMounted(async () => {
  await load()
  await provisionFromRoute()
})

onBeforeUnmount(() => {
  legacyPollSequence += 1
})
</script>

<template>
  <div class="deep-research-shell">
    <div class="deep-mobile-topbar">
      <span><BrainCircuit :size="16" /> 深研对话</span>
      <button
        type="button"
        class="icon-button"
        aria-label="新建深研对话"
        title="新建深研对话"
        @click="startNew"
      >
        <MessageSquarePlus :size="18" />
      </button>
    </div>
    <aside class="deep-sidebar" :class="{ collapsed: !sidebarOpen }" aria-label="深研会话">
      <div class="deep-sidebar-head">
        <div v-if="sidebarOpen" class="deep-sidebar-title">
          <BrainCircuit :size="18" />
          <span>深研对话</span>
        </div>
        <button
          class="icon-button"
          type="button"
          :aria-label="sidebarOpen ? '收起会话栏' : '展开会话栏'"
          @click="toggleSidebar"
        >
          <PanelLeftClose v-if="sidebarOpen" :size="17" />
          <PanelLeftOpen v-else :size="17" />
        </button>
      </div>

      <button class="new-session-button" type="button" @click="startNew">
        <span class="new-session-icon"><MessageSquarePlus :size="15" /></span>
        <span>新建深研</span>
      </button>
      <div class="deep-sidebar-history">
        <EquipmentDeepSessionHistory
          ref="sessionHistory"
          :sessions="sessions"
          :runs="runs"
          :current-run-id="historyCurrentRunId"
          :selected-session-id="selectedHistorySessionId"
          :pending-session-id="pendingSessionId"
          :loading="sessionsLoading"
          :error="sessionsError"
          :busy-session-id="sessionActionId"
          @select="selectSession"
          @rename="renameSession"
          @archive="archiveSession"
          @restore="restoreSession"
          @delete="deleteSession"
        />
      </div>
    </aside>

    <main
      class="deep-main"
      :aria-busy="sessionSwitching || (loading && Boolean(sessionId) && !session)"
    >
      <div v-if="sessionSwitchError && session" class="deep-switch-error" role="alert">
        <span>{{ sessionSwitchError }} 当前对话已保留。</span>
        <button type="button" @click="loadSession">重新打开</button>
      </div>
      <template v-if="loadError">
        <div class="create-workspace deep-load-error" role="alert">
          <h1>深研会话暂时无法加载</h1>
          <p>{{ loadError }}</p>
          <a-button type="primary" :loading="loading" @click="load">重新加载</a-button>
        </div>
      </template>
      <template v-else-if="session">
        <nav
          v-if="
            !conversationFocusMode && (session.payload?.parent_session_id || branchItems.length)
          "
          class="branch-bar"
          aria-label="研究分支"
        >
          <span><GitBranch :size="14" />研究分支</span>
          <button
            v-if="session.payload?.parent_session_id"
            type="button"
            @click="selectSession(session.payload.parent_session_id)"
          >
            主线
          </button>
          <button
            v-for="branch in branchItems"
            :key="branch.branch_id"
            type="button"
            @click="selectSession(branch.child_session_id)"
          >
            {{ branch.title }}
          </button>
          <small v-if="usesNativeAgent">每条分支使用独立的平台原生会话，上下文按分叉点继承</small>
          <small v-else>旧版分支关系与分叉点已按原数据恢复</small>
        </nav>

        <section v-if="!conversationFocusMode" class="research-summary" aria-label="研究设置">
          <div class="research-summary-primary">
            <span class="research-summary-kicker"><Target :size="15" /> 研究上下文</span>
            <strong :title="researchContext.run?.topic || session.topic || session.title">
              {{ researchContext.run?.topic || session.topic || session.title || '自由深研会话' }}
            </strong>
            <span v-if="boundSections.length" class="seed-count"
              >已注入 {{ boundSections.length }} 栏能力画像</span
            >
            <span v-if="activeResearchSection" class="seed-count current-section-count"
              >当前深挖：{{ activeResearchSection }}</span
            >
            <span class="research-mode-badge" :class="{ divergent: !isSectionDeepen }">
              {{ researchModeLabel }}
            </span>
            <span v-if="boundReferences.length" class="seed-count"
              >已注入 {{ boundReferences.length }} 项参考武器</span
            >
          </div>
          <div class="research-summary-actions">
            <button
              v-if="activeRun"
              class="context-button task-link-button"
              type="button"
              @click="openRunWorkspace('runs')"
            >
              <FileText :size="13" /> 返回研究任务
            </button>
            <span v-for="item in sessionCapabilities" :key="item.label" class="capability-pill">
              <component :is="item.icon" :size="13" /> {{ item.label }}
            </span>
            <button
              class="context-button"
              type="button"
              :aria-expanded="contextOpen"
              aria-controls="research-context-details"
              @click="contextOpen = !contextOpen"
            >
              {{ contextOpen ? '收起详情' : '查看详情' }}
            </button>
            <button
              class="context-button focus-mode-button"
              type="button"
              :aria-pressed="conversationFocusMode"
              @click="toggleConversationFocus"
            >
              <Minimize2 :size="13" />
              返回专注对话
            </button>
          </div>
        </section>

        <section
          v-if="contextOpen && !conversationFocusMode"
          id="research-context-details"
          class="research-context-panel"
          aria-label="研究上下文详情"
        >
          <div class="context-panel-heading">
            <span><Target :size="16" /><b>本次研究起点</b></span>
            <button
              type="button"
              class="icon-button"
              aria-label="关闭研究上下文"
              @click="contextOpen = false"
            >
              <PanelLeftClose :size="16" />
            </button>
          </div>
          <p class="context-topic">{{ researchContext.run?.topic || '未关联正式研究任务' }}</p>
          <div class="context-metrics">
            <span
              ><b>{{ researchContext.capability_versions?.length || 0 }}</b
              >能力版本</span
            >
            <span
              ><b>{{ researchContext.artifacts?.length || 0 }}</b
              >研究产物</span
            >
            <span
              ><b>{{ researchContext.branch_context ? 1 : 0 }}</b
              >继承分支</span
            >
            <span v-if="activeRun"
              ><b>{{ relatedSessionCount }}</b
              >关联深研</span
            >
          </div>
          <nav v-if="activeRun" class="context-module-links" aria-label="关联研究模块">
            <button type="button" @click="openRunWorkspace('runs')">任务详情</button>
            <button type="button" @click="openRunWorkspace('capabilities')">能力画像</button>
            <button type="button" @click="openRunWorkspace('reports')">研究报告</button>
          </nav>
          <div v-if="boundSections.length" class="context-sections">
            <b>能力画像五栏 · {{ boundEquipment || '当前装备' }}</b>
            <details v-for="item in boundSections" :key="item.label">
              <summary>{{ item.label }}</summary>
              <p>{{ item.text }}</p>
            </details>
          </div>
          <div v-if="boundReferences.length" class="context-references">
            <b>参考武器</b>
            <article v-for="item in boundReferences" :key="item.hypothesis_id">
              <strong>{{ item.title || item.primary_equipment_identity }}</strong>
              <p>{{ item.overview || '已作为本次深研的参考武器对象。' }}</p>
            </article>
          </div>
        </section>

        <div
          v-if="viewingArchivedSession && usesNativeAgent"
          class="deep-archived-banner"
          role="status"
        >
          该会话已归档，当前为只读状态；可在左侧“归档”中恢复后继续追问。
        </div>
        <section
          v-if="technologyCabinMode && usesNativeAgent"
          class="technology-cabin-panel"
          aria-label="技术攻关舱"
        >
          <div class="technology-cabin-heading">
            <span class="technology-cabin-icon"><Wrench :size="17" /></span>
            <div>
              <small>装备与技术实现专属模块</small>
              <strong>技术攻关舱</strong>
            </div>
          </div>
          <div class="technology-cabin-object">
            <span>当前攻关对象</span>
            <b>{{ boundEquipment || '当前装备' }}</b>
            <em><Target :size="11" /> 装备身份锁定</em>
            <em><Bot :size="11" /> {{ session.payload?.agent_name || '武器装备研究方案' }}</em>
          </div>
          <nav class="technology-cabin-actions" aria-label="技术攻关工作流">
            <button
              v-for="(item, index) in TECHNOLOGY_CABIN_ACTIONS"
              :key="item.id"
              type="button"
              :class="{ primary: item.primary }"
              :disabled="viewingArchivedSession"
              :title="item.hint"
              @click="prefillDeepAction(item.id)"
            >
              <span>{{ index + 1 }}</span>
              <div>
                <b>{{ item.label }}</b>
                <small>{{ item.hint }}</small>
              </div>
            </button>
          </nav>
          <p>七级链由方案智能体逐级推进；点击步骤只会生成可编辑的研究问题，请确认后再发送。</p>
        </section>
        <AgentChatComponent
          v-if="usesNativeAgent"
          ref="nativeChat"
          class="native-deep-chat"
          :agent-id="session.payload?.agent_slug || 'deep-research'"
          :initial-project-id="session.project_id"
          draft-scope="equipment-deep"
          :is-new-conversation="false"
          :single-mode="true"
          :send-disabled="viewingArchivedSession"
          :show-activity-summary="true"
          :slash-commands="EQUIPMENT_DEEP_SLASH_COMMANDS"
          :run-meta="deepRunMeta"
          @run-submitted="handleRunSubmitted"
          @run-completed="handleRunCompleted"
        >
          <template
            #domain-projection="{ agentState, conversations, todos, subagentRuns, isProcessing }"
          >
            <div v-show="!conversationFocusMode" class="deep-domain-projection">
              <EquipmentDeepStageProjection
                :session="session"
                :agent-state="agentState"
                :conversations="conversations"
                :todos="todos"
                :subagent-runs="subagentRuns"
                :versions="capabilityVersionRows"
                :active-skill-ids="activeSkillIds"
                :processing="isProcessing"
                :create-artifact="createArtifact"
                :research-mode="researchMode"
                :research-section="activeResearchSection"
                @focus-direction="focusCandidateDirection"
                @author-card="authorCandidateCard"
              />
              <EquipmentDeepCandidateVersions
                v-show="sessionCandidateVersionCards.length"
                ref="candidateVersions"
                class="deep-inline-candidate-versions"
                :run-id="String(session.run_id || '')"
                :session-id="sessionId"
                :read-only="viewingArchivedSession"
                :show-empty="false"
                @loaded="handleCapabilityVersionsLoaded"
                @changed="handleCapabilityVersionsLoaded"
              />
            </div>
          </template>
          <template #empty-state>
            <section class="deep-empty-state" aria-label="深研对话使用指引">
              <span class="deep-empty-icon"><BrainCircuit :size="22" /></span>
              <h2>从问题出发，完整追踪研究过程</h2>
              <p>
                在下方输入问题；可引用资料或技能。运行后，步骤、子任务、工具调用和 Token
                用量会随任务更新。
              </p>
              <div class="deep-mention-shortcuts" aria-label="快速引用">
                <button
                  v-if="session.payload?.knowledge_enabled !== false"
                  type="button"
                  @click.stop="startMention('knowledgeBases')"
                >
                  <Database :size="16" /> @ 知识库
                </button>
                <button type="button" @click.stop="startMention('files')">
                  <FileText :size="16" /> @ 文件
                </button>
                <button type="button" @click.stop="startMention('skills')">
                  <WandSparkles :size="16" /> @ Skill
                </button>
              </div>
              <div class="deep-empty-guidance">
                <span>① 引用资料</span><span>② 查看执行步骤</span><span>③ 预览并下载成果</span>
              </div>
            </section>
          </template>
          <template v-if="!viewingArchivedSession" #input-actions-left>
            <a-popover
              v-model:open="researchControlOpen"
              trigger="click"
              placement="topLeft"
              overlay-class-name="deep-research-control-popover"
            >
              <template #content>
                <section class="research-control-popover" aria-label="研究方式与下一步">
                  <header class="research-control-head">
                    <div>
                      <b>研究方式</b>
                      <small>先选择研究目标，再选择下一步；所有动作都会先填入输入框。</small>
                    </div>
                    <button
                      type="button"
                      class="research-control-close"
                      aria-label="关闭研究方式"
                      @click="researchControlOpen = false"
                    >
                      <PanelLeftClose :size="15" />
                    </button>
                  </header>

                  <div class="research-control-object">
                    <span>当前对象</span>
                    <strong>{{ boundEquipment || '当前研究对象' }}</strong>
                  </div>

                  <div class="research-control-step">
                    <span>1</span>
                    <div><b>要研究什么？</b><small>切换方式不会立即发送消息</small></div>
                  </div>
                  <div class="research-mode-cards" role="group" aria-label="选择研究方式">
                    <button
                      type="button"
                      :class="{ active: isSectionDeepen }"
                      @click="setResearchMode('section_deepen')"
                    >
                      <span><Layers :size="15" /></span>
                      <div>
                        <b>深化当前装备</b>
                        <small>保持装备身份，补强技术、流程与制胜逻辑</small>
                      </div>
                    </button>
                    <button
                      type="button"
                      :class="{ active: !isSectionDeepen }"
                      @click="setResearchMode('new_weapon_diverge')"
                    >
                      <span><Sparkles :size="15" /></span>
                      <div>
                        <b>发散新质武器</b>
                        <small>允许突破原装备形态，由能力画像智能体择优成卡</small>
                      </div>
                    </button>
                  </div>

                  <template v-if="boundSections.length && isSectionDeepen">
                    <div class="research-control-step compact-step">
                      <span>2</span>
                      <div><b>选择深化栏目</b><small>点击后生成一条可编辑的深挖问题</small></div>
                    </div>
                    <nav class="research-section-options" aria-label="选择深化栏目">
                      <button
                        v-for="item in boundSections"
                        :key="item.label"
                        type="button"
                        :class="{ active: activeResearchSection === item.label }"
                        :title="sectionHint(item.label)"
                        @click="selectResearchSection(item)"
                      >
                        {{ item.label }}
                      </button>
                    </nav>
                  </template>

                  <div class="research-control-step compact-step">
                    <span>{{ isSectionDeepen && boundSections.length ? 3 : 2 }}</span>
                    <div><b>快捷开始</b><small>选择后先检查输入框内容，再决定是否发送</small></div>
                  </div>
                  <div class="research-action-options" aria-label="快捷开始">
                    <button
                      v-for="item in deepActionOptions"
                      :key="item.id"
                      type="button"
                      @click="selectDeepAction(item.id)"
                    >
                      {{ item.label }}
                    </button>
                  </div>

                  <footer class="research-control-footer">
                    <button
                      v-if="isSectionDeepen && boundSections.length"
                      type="button"
                      class="research-card-action"
                      @click="authorNextCard"
                    >
                      <Sparkles :size="13" />形成新版能力卡
                    </button>
                    <button
                      type="button"
                      class="research-overview-action"
                      @click="
                        conversationFocusMode ? openResearchOverview() : setConversationFocus(true)
                      "
                    >
                      <Layers v-if="conversationFocusMode" :size="13" />
                      <Minimize2 v-else :size="13" />
                      {{ conversationFocusMode ? '查看研究全景' : '返回专注对话' }}
                    </button>
                  </footer>
                </section>
              </template>
              <button
                class="focus-research-trigger"
                type="button"
                :aria-expanded="researchControlOpen"
                title="设置研究方式和下一步；不会自动发送"
              >
                <Target :size="14" />
                <span>研究方式</span>
                <em>{{ researchModeLabel }}</em>
                <ChevronDown :size="13" />
              </button>
            </a-popover>
            <EquipmentDeepSkillPicker
              v-model="activeSkillIds"
              :session-id="sessionId"
              placement="top"
            />
            <label class="artifact-toggle" :class="{ active: createArtifact }">
              <FileCheck2 :size="14" />
              <span>形成能力画像草案</span>
              <a-switch v-model:checked="createArtifact" size="small" />
            </label>
          </template>
          <template #message-actions="{ message: nativeMessage }">
            <button
              v-if="
                !viewingArchivedSession &&
                (nativeMessage.type === 'ai' || nativeMessage.role === 'assistant')
              "
              class="quote-message-button"
              type="button"
              @click="quoteMessage(nativeMessage)"
            >
              <Quote :size="13" /> 引用追问
            </button>
            <button
              v-if="
                !viewingArchivedSession &&
                (nativeMessage.type === 'ai' || nativeMessage.role === 'assistant')
              "
              class="fork-message-button"
              type="button"
              :disabled="branchCreating"
              @click="forkFrom(nativeMessage)"
            >
              <GitBranch :size="13" /> 从此处探索分支
            </button>
          </template>
        </AgentChatComponent>
        <EquipmentLegacyDeepSession
          v-else
          class="legacy-deep-chat"
          :session="session"
          :loading="loading"
          :error="legacyError"
          :sending="legacySending"
          @submit="submitLegacyMessage"
        />
      </template>

      <template v-else-if="sessionId && loading">
        <div class="create-workspace deep-session-initial-loading" role="status">
          <RefreshCw :size="22" class="spin" />
          <h1>正在打开历史对话</h1>
          <p>左侧会话目录会保持原位，对话准备完成后将在此处显示。</p>
        </div>
      </template>

      <template v-else-if="provisioning || (cardKey && loading)">
        <div class="create-workspace provision-wait">
          <div class="create-intro">
            <div class="empty-orb"><Sparkles :size="24" /></div>
            <div>
              <div class="deep-kicker"><Sparkles :size="13" /> 定向深研</div>
              <h1>正在按所选能力画像卡配置会话</h1>
              <p>已绑定卡片并注入五栏上下文，完成后直接进入深研对话。</p>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="create-workspace">
          <div class="create-intro">
            <div class="empty-orb create-orb"><Sparkles :size="22" /></div>
            <div class="create-intro-copy">
              <div class="deep-kicker"><Sparkles :size="13" /> 新建定向研究</div>
              <h1>深化装备画像，也可发散新质方向</h1>
              <p>绑定现有装备时默认深挖栏目；需要突破原装备身份时，再显式切换到新质发散。</p>
            </div>
            <div class="create-intro-tags" aria-label="研究方式">
              <span>栏目深化</span><span>证据核验</span><span>可选新质发散</span>
            </div>
          </div>
          <section v-if="activeRun" class="linked-run-banner" aria-label="已关联研究任务">
            <span><Target :size="16" /></span>
            <div>
              <small>已从研究任务进入 · 将自动继承 Query 与研究材料</small>
              <b>{{ activeRun.topic }}</b>
            </div>
            <em>{{ relatedSessionCount }} 个既有深研</em>
            <button type="button" @click="openRunWorkspace('runs')">查看任务</button>
          </section>
          <a-form class="create-form" layout="vertical">
            <section class="launch-section">
              <header class="launch-section-head">
                <span class="launch-step">01</span>
                <div>
                  <b>研究上下文</b><small>关联 Query 和已有研究材料，为模型提供问题空间</small>
                </div>
                <Layers :size="17" />
              </header>
              <div class="launch-section-body">
                <div class="form-grid">
                  <a-form-item label="所属项目" required>
                    <a-select
                      v-model:value="form.project_id"
                      :options="
                        projects.map((item) => ({
                          value: item.id,
                          label: projectDisplayName(item, userStore.isAdmin)
                        }))
                      "
                    />
                  </a-form-item>
                  <a-form-item label="关联研究任务">
                    <a-select
                      v-model:value="form.run_id"
                      allow-clear
                      show-search
                      option-filter-prop="label"
                      placeholder="可选：带入 Query 与研究上下文"
                      :options="
                        filteredRuns.map((item) => ({ value: item.run_id, label: item.topic }))
                      "
                    />
                  </a-form-item>
                </div>
                <section
                  v-if="form.run_id"
                  class="research-binding-builder"
                  aria-label="研究对象级联配置"
                >
                  <div class="binding-builder-head">
                    <span><Layers :size="16" /></span>
                    <div>
                      <b>研究对象</b>
                      <small
                        >先选择对象类型，再选择具体武器；入选武器与参考武器分别独立配置。</small
                      >
                    </div>
                    <span v-if="contextOptionsLoading" class="binding-status">加载中</span>
                  </div>
                  <div v-if="contextOptionsError" class="binding-error" role="alert">
                    <span>{{ contextOptionsError }}</span>
                    <button type="button" @click="loadContextOptions(form.run_id)">重新加载</button>
                  </div>
                  <div v-else class="binding-object-picker">
                    <div class="binding-type-field">
                      <span class="binding-step-copy"
                        ><b>研究对象类型</b><small>本次深研选择其中一种对象</small></span
                      >
                      <a-radio-group v-model:value="form.research_object_type" button-style="solid">
                        <a-radio-button
                          value="selected"
                          :disabled="contextOptionsLoading || !capabilityCards.length"
                        >
                          入选武器<span class="binding-option-count">{{
                            capabilityCards.length
                          }}</span>
                        </a-radio-button>
                        <a-radio-button
                          value="reference"
                          :disabled="contextOptionsLoading || !referenceWeapons.length"
                        >
                          参考武器<span class="binding-option-count">{{
                            referenceWeapons.length
                          }}</span>
                        </a-radio-button>
                      </a-radio-group>
                    </div>
                    <section
                      v-if="form.research_object_type === 'selected'"
                      class="binding-object-panel selected-object-panel"
                    >
                      <header>
                        <span
                          ><b>选择入选武器</b
                          ><small>以已形成正式能力画像的武器装备为研究主体</small></span
                        >
                      </header>
                      <label class="binding-step">
                        <span class="binding-step-copy"
                          ><b>能力画像卡</b><small>选择本次深挖的武器装备主体</small></span
                        >
                        <a-select
                          v-model:value="form.capability_card_key"
                          allow-clear
                          show-search
                          option-filter-prop="label"
                          :loading="contextOptionsLoading"
                          :disabled="contextOptionsLoading || !capabilityCards.length"
                          :placeholder="
                            capabilityCards.length ? '选择入选武器' : '该任务暂无入选武器'
                          "
                          :options="
                            capabilityCards.map((item) => ({
                              value: item.card_key,
                              label: capabilityEquipmentName(item)
                            }))
                          "
                        />
                      </label>
                      <label class="binding-step" :class="{ muted: !selectedCapability }">
                        <span class="binding-step-copy"
                          ><b>画像范围</b><small>继续级联到全部五栏或某一栏</small></span
                        >
                        <a-select
                          v-model:value="form.capability_scope"
                          :disabled="!selectedCapability"
                          :options="capabilitySectionOptions"
                        />
                      </label>
                    </section>
                    <section v-else class="binding-object-panel reference-object-panel">
                      <header>
                        <span
                          ><b>选择参考武器</b
                          ><small>以任务中的候选参考武器为独立研究主体</small></span
                        >
                      </header>
                      <label class="binding-step">
                        <span class="binding-step-copy"
                          ><b>参考武器</b><small>直接选择本次需要深研的参考对象</small></span
                        >
                        <a-select
                          v-model:value="form.reference_weapon_id"
                          allow-clear
                          show-search
                          option-filter-prop="label"
                          :loading="contextOptionsLoading"
                          :disabled="contextOptionsLoading || !referenceWeapons.length"
                          :placeholder="
                            referenceWeapons.length ? '选择参考武器' : '该任务暂无可用参考武器'
                          "
                          :options="
                            referenceWeapons.map((item) => ({
                              value: item.hypothesis_id,
                              label: item.title || item.primary_equipment_identity
                            }))
                          "
                        />
                      </label>
                    </section>
                  </div>
                  <div v-if="contextBindingSummary" class="binding-summary">
                    <Target :size="14" />
                    <span
                      ><small>将注入会话</small><b>{{ contextBindingSummary }}</b></span
                    >
                  </div>
                  <p v-if="selectedReference?.overview" class="reference-preview">
                    {{ selectedReference.overview }}
                  </p>
                </section>
              </div>
            </section>
            <section class="launch-section launch-question-section">
              <header class="launch-section-head">
                <span class="launch-step">02</span>
                <div><b>研究目标</b><small>明确是深化当前装备，还是突破身份发散新装备</small></div>
                <Target :size="17" />
              </header>
              <div class="launch-section-body">
                <div class="launch-mode-picker" role="group" aria-label="新会话研究模式">
                  <button
                    type="button"
                    :class="{ active: form.research_mode === 'section_deepen' }"
                    :disabled="!selectedCapability"
                    @click="form.research_mode = 'section_deepen'"
                  >
                    <b>深化当前装备</b>
                    <small>锁定装备身份，深挖技术攻关、流程与制胜机理</small>
                  </button>
                  <button
                    type="button"
                    :class="{ active: form.research_mode === 'new_weapon_diverge' }"
                    @click="form.research_mode = 'new_weapon_diverge'"
                  >
                    <b>发散新质武器</b>
                    <small>形成正交候选，并由能力画像智能体择优生成五栏卡</small>
                  </button>
                </div>
                <a-form-item label="研讨主题" required>
                  <a-textarea
                    v-model:value="form.topic"
                    :rows="3"
                    :placeholder="
                      form.research_mode === 'section_deepen'
                        ? '例如：深化现有装备的技术实现，破解研发卡点并闭合作战流程与制胜逻辑'
                        : '例如：面向未来低空饱和威胁，发散重构防御成本的新质装备'
                    "
                  />
                </a-form-item>
                <a-form-item
                  :label="
                    form.research_mode === 'section_deepen'
                      ? '研究焦点（锁定装备）'
                      : '研究焦点（开放发散）'
                  "
                  :extra="
                    form.research_mode === 'section_deepen'
                      ? '保持装备身份和任务定位不变，可深化技术实现、作战流程与制胜机理。'
                      : '能力卡和参考武器只作为启发基线，允许形成新装备候选。'
                  "
                >
                  <a-textarea
                    v-model:value="form.focus"
                    :rows="4"
                    :maxlength="1600"
                    show-count
                    :placeholder="
                      form.research_mode === 'section_deepen'
                        ? '围绕关键技术卡点、工程痛点、攻关路线、作战流程和制胜逻辑深化。'
                        : '围绕 Query 场景发散制胜、制衡对手的新质武器，不预设形态与技术路线。'
                    "
                  />
                </a-form-item>
                <div
                  v-if="form.research_mode === 'new_weapon_diverge'"
                  class="divergence-axis-list"
                  aria-label="默认发散维度"
                >
                  <span>任务链反转</span><span>作用机理</span><span>装备构型</span>
                  <span>交战窗口</span><span>成本交换</span><span>对手反适应</span>
                </div>
              </div>
            </section>
            <section class="launch-section">
              <header class="launch-section-head">
                <span class="launch-step">03</span>
                <div><b>研究编排</b><small>选择主模型，并配置检索与并行协作能力</small></div>
                <Bot :size="17" />
              </header>
              <div class="launch-section-body">
                <div class="form-grid runtime-grid">
                  <EquipmentModelField
                    v-model:model-spec="form.model_spec"
                    label="研究模型"
                    :has-default-model="hasDefaultModel"
                  />
                  <a-form-item label="研究智能体">
                    <a-select
                      v-model:value="form.agent_slug"
                      :options="agentOptions"
                      placeholder="选择智能体"
                    />
                  </a-form-item>
                </div>
                <div class="capability-switches">
                  <label :class="{ enabled: form.knowledge_enabled }">
                    <span
                      ><Database :size="17" /><b>知识库检索</b
                      ><small>检索可访问资料并保留来源</small></span
                    >
                    <a-switch v-model:checked="form.knowledge_enabled" />
                  </label>
                  <label :class="{ enabled: form.subagents_enabled }">
                    <span
                      ><Network :size="17" /><b>Subagent 协同</b
                      ><small>并行拆解、交叉核验与汇总</small></span
                    >
                    <a-switch v-model:checked="form.subagents_enabled" />
                  </label>
                </div>
              </div>
            </section>
            <footer class="launch-footer">
              <div>
                <Sparkles :size="16" />
                <span
                  ><b>{{
                    form.research_mode === 'section_deepen'
                      ? '准备深化当前装备'
                      : '准备启动新质发散'
                  }}</b
                  ><small>{{
                    form.research_mode === 'section_deepen'
                      ? '锁定装备身份，推进技术攻关、流程推演、机理深化并修订'
                      : '先发散正交方向，再按价值与可行性收敛'
                  }}</small></span
                >
              </div>
              <a-button
                type="primary"
                size="large"
                :loading="creating"
                :disabled="selectedRunReadOnly"
                :title="selectedRunReadOnly ? '历史研究任务为只读数据' : ''"
                @click="createSession"
              >
                创建深研会话
              </a-button>
            </footer>
          </a-form>
        </div>
      </template>

      <Transition name="deep-session-switch">
        <div
          v-if="sessionSwitching && session"
          class="deep-session-switch-layer"
          role="status"
          aria-live="polite"
        >
          <span><RefreshCw :size="14" class="spin" />正在打开历史对话…</span>
        </div>
      </Transition>
    </main>
  </div>
</template>

<style scoped>
.deep-research-shell {
  display: flex;
  height: 100vh;
  min-height: 620px;
  background: var(--gray-25);
  color: var(--gray-900);
}
.deep-sidebar {
  width: 320px;
  flex: 0 0 320px;
  border-right: 1px solid var(--gray-150);
  background: #f4f6fb;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
  transition:
    width 0.18s ease,
    flex-basis 0.18s ease;
}
.deep-sidebar.collapsed {
  width: 52px;
  flex-basis: 52px;
}
.deep-sidebar.collapsed .deep-sidebar-head {
  justify-content: center;
  padding: 0;
}
.deep-sidebar.collapsed > .new-session-button,
.deep-sidebar.collapsed > .deep-sidebar-history {
  display: none;
}
.deep-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 8px 0 12px;
  border-bottom: 1px solid var(--gray-100);
}
.deep-sidebar-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  color: var(--gray-800);
  font-size: 13px;
  font-weight: 650;
}
.deep-sidebar-title svg {
  color: var(--gray-600);
  stroke-width: 1.8;
}
.icon-button {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--gray-500);
  cursor: pointer;
}
.icon-button:hover {
  background: var(--gray-50);
  color: var(--gray-900);
}
.new-session-button {
  display: flex;
  align-items: center;
  gap: 9px;
  width: calc(100% - 16px);
  height: 34px;
  margin: 10px 8px 14px;
  padding: 0 9px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-800);
  font-size: 13px;
  font-weight: 550;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease,
    color 0.15s ease;
}
.new-session-button:hover {
  border-color: var(--main-200);
  background: var(--main-50);
  color: var(--main-color);
}
.new-session-button:focus-visible {
  outline: 2px solid var(--main-300);
  outline-offset: 1px;
}
.new-session-icon {
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 6px;
  background: var(--main-50);
  color: var(--main-color);
}
.deep-main {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}
.native-deep-chat {
  min-height: 0;
  flex: 1;
}
.native-deep-kicker {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.deep-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 86px;
  padding: 14px 28px;
  border-bottom: 1px solid var(--gray-100);
  background: color-mix(in srgb, var(--gray-0) 92%, transparent);
}
.deep-heading {
  min-width: 0;
}
.deep-kicker {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 3px;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.deep-heading h1,
.create-intro h1 {
  margin: 0;
  font-size: 19px;
  line-height: 1.35;
}
.deep-heading p,
.create-intro p {
  margin: 3px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}
.capability-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}
.capability-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 9px;
  border: 1px solid var(--gray-150);
  border-radius: 999px;
  background: var(--gray-0);
  color: var(--gray-600);
  font-size: 11px;
}
.context-button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 9px;
  border: 1px solid var(--main-200);
  border-radius: 999px;
  background: var(--main-50);
  color: var(--main-color);
  font-size: 11px;
  cursor: pointer;
}
.branch-bar {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 6px 28px;
  border-bottom: 1px solid var(--gray-100);
  background: var(--gray-0);
  overflow-x: auto;
}
.branch-bar > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--gray-600);
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}
.branch-bar button {
  padding: 5px 9px;
  border: 1px solid var(--gray-150);
  border-radius: 999px;
  background: var(--gray-25);
  color: var(--gray-700);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
}
.branch-bar small {
  margin-left: auto;
  color: var(--gray-400);
  white-space: nowrap;
}
.research-context-panel {
  display: grid;
  gap: 10px;
  margin: 14px max(24px, calc((100% - 900px) / 2)) 0;
  padding: 14px 16px;
  border: 1px solid var(--main-100);
  border-radius: 12px;
  background: color-mix(in srgb, var(--main-50) 60%, var(--gray-0));
}
.research-context-panel > div:first-child {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--main-color);
}
.research-context-panel span {
  display: grid;
}
.research-context-panel small {
  color: var(--gray-500);
  font-size: 11px;
}
.research-context-panel em {
  margin-left: auto;
  padding: 3px 7px;
  border-radius: 999px;
  background: var(--gray-0);
  color: var(--gray-600);
  font-size: 10px;
  font-style: normal;
}
.context-metrics {
  display: flex;
  gap: 8px;
}
.context-metrics span {
  display: flex;
  align-items: baseline;
  gap: 4px;
  padding: 6px 9px;
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-500);
  font-size: 10px;
}
.context-metrics b {
  color: var(--gray-900);
  font-size: 14px;
}
.context-module-links {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.context-module-links button {
  min-height: 28px;
  padding: 4px 10px;
  border: 1px solid var(--main-100);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--main-color);
  font-size: 10px;
  cursor: pointer;
}
.task-link-button {
  white-space: nowrap;
}
.research-context-panel p {
  margin: 0;
  color: var(--gray-500);
  font-size: 10px;
}
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 30px max(24px, calc((100% - 900px) / 2));
}
.conversation-empty {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 12vh 16px 40px;
  text-align: center;
}
.empty-orb {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  margin-bottom: 4px;
  border: 1px solid var(--main-100);
  border-radius: 16px;
  background: linear-gradient(145deg, var(--main-50), var(--gray-0));
  color: var(--main-color);
  box-shadow: 0 12px 30px color-mix(in srgb, var(--main-color) 12%, transparent);
}
.conversation-empty h2 {
  margin: 0;
  font-size: 19px;
}
.conversation-empty p {
  margin: 0;
  color: var(--gray-500);
  font-size: 13px;
}
.prompt-examples {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
}
.prompt-examples button {
  padding: 8px 11px;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--gray-600);
  font-size: 12px;
  cursor: pointer;
}
.prompt-examples button:hover {
  border-color: var(--main-200);
  color: var(--main-color);
}
.message-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: 0 0 26px;
}
.message-row.user {
  flex-direction: row-reverse;
}
.message-avatar {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--main-color);
  font-size: 11px;
  font-weight: 700;
}
.message-row.user .message-avatar {
  background: var(--main-color);
  color: white;
  border-color: var(--main-color);
}
.message-content {
  min-width: 0;
  max-width: calc(100% - 44px);
  flex: 1;
}
.message-row.user .message-content {
  flex: 0 1 auto;
  max-width: 72%;
}
.message-author {
  margin-bottom: 6px;
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 600;
}
.message-row.user .message-author {
  text-align: right;
}
.user-message {
  padding: 10px 13px;
  border-radius: 12px 3px 12px 12px;
  background: var(--main-color);
  color: #fff;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
}
.tool-calls {
  display: grid;
  gap: 7px;
  margin-top: 10px;
}
.fork-message-button,
.quote-message-button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 8px;
  padding: 5px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--gray-400);
  font-size: 10px;
  cursor: pointer;
}
.fork-message-button:hover,
.quote-message-button:hover {
  background: var(--gray-50);
  color: var(--main-color);
}
.thinking-row {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0 0 24px 42px;
  color: var(--gray-500);
  font-size: 12px;
}
.thinking-row span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--main-color);
  animation: pulse 1.2s infinite ease-in-out;
}
.thinking-row span:nth-child(2) {
  animation-delay: 0.15s;
}
.thinking-row span:nth-child(3) {
  animation-delay: 0.3s;
  margin-right: 4px;
}
.job-error {
  margin: 12px 42px;
  padding: 10px 12px;
  border: 1px solid #f1dadd;
  border-radius: 9px;
  background: #fff7f7;
  color: #b4505b;
  font-size: 12px;
}
.composer-wrap {
  padding: 10px max(24px, calc((100% - 900px) / 2)) 18px;
  background: linear-gradient(transparent, var(--gray-25) 28%);
  text-align: center;
}
.composer-options {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 6px;
}
.composer-options label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-500);
  font-size: 10px;
}
.composer-options label.active {
  border-color: var(--main-200);
  color: var(--main-color);
}
.composer {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 10px 10px 14px;
  border: 1px solid var(--gray-200);
  border-radius: 15px;
  background: var(--gray-0);
  box-shadow: 0 10px 30px color-mix(in srgb, var(--gray-900) 7%, transparent);
}
.composer:focus-within {
  border-color: var(--main-300);
  box-shadow:
    0 0 0 3px var(--main-50),
    0 10px 30px color-mix(in srgb, var(--gray-900) 7%, transparent);
}
.composer textarea {
  min-height: 28px;
  max-height: 140px;
  flex: 1;
  resize: none;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--gray-900);
  font: inherit;
  font-size: 14px;
  line-height: 1.7;
}
.send-button {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 10px;
  background: var(--main-color);
  color: white;
  cursor: pointer;
}
.send-button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.composer-wrap > span {
  display: inline-block;
  margin-top: 7px;
  color: var(--gray-400);
  font-size: 10px;
}
.artifact-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 8px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  color: var(--gray-500);
  font-size: 10px;
  white-space: nowrap;
}
.artifact-toggle.active {
  border-color: var(--main-200);
  color: var(--main-color);
  background: var(--main-50);
}
.context-sections {
  display: grid;
  gap: 3px;
  padding-top: 4px;
  border-top: 1px solid var(--main-100);
}
.context-sections > b {
  color: var(--gray-700);
  font-size: 11px;
}
.context-sections summary {
  padding: 3px 0;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.context-sections details p {
  margin: 0 0 6px;
  max-height: 140px;
  overflow-y: auto;
  color: var(--gray-600);
  font-size: 11px;
  line-height: 1.6;
}
.context-references {
  display: grid;
  gap: 7px;
  padding-top: 8px;
  border-top: 1px solid var(--main-100);
}
.context-references > b {
  color: var(--gray-700);
  font-size: 11px;
}
.context-references article {
  display: grid;
  gap: 3px;
  padding: 9px 10px;
  border: 1px solid var(--gray-100);
  border-radius: 9px;
  background: var(--gray-0);
}
.context-references article strong {
  color: var(--gray-800);
  font-size: 11px;
}
.context-references article p {
  max-height: 90px;
  overflow-y: auto;
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.6;
}
.create-workspace {
  width: min(1040px, calc(100% - 48px));
  margin: auto;
  padding: 36px 0 48px;
}
.create-intro {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 22px;
  padding: 0 4px;
}
.create-orb {
  width: 54px;
  height: 54px;
  flex: 0 0 54px;
  margin: 0;
  border-color: color-mix(in srgb, var(--main-color) 18%, transparent);
  border-radius: 17px;
  background:
    radial-gradient(circle at 30% 20%, var(--gray-0), transparent 48%),
    linear-gradient(145deg, var(--main-100), var(--main-50));
}
.create-intro-copy {
  min-width: 0;
  flex: 1;
}
.create-intro-copy h1 {
  font-size: clamp(21px, 2.5vw, 28px);
  letter-spacing: -0.025em;
}
.create-intro-copy p {
  max-width: 660px;
  margin-top: 5px;
  line-height: 1.65;
}
.create-intro-tags {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}
.create-intro-tags span,
.divergence-axis-list span {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  border: 1px solid var(--main-100);
  border-radius: 999px;
  background: color-mix(in srgb, var(--main-50) 68%, var(--gray-0));
  color: var(--main-color);
  font-size: 10px;
  font-weight: 600;
}
.linked-run-banner {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 11px;
  margin: -8px 0 14px;
  padding: 11px 13px;
  border: 1px solid color-mix(in srgb, var(--main-color) 18%, var(--gray-150));
  border-radius: 12px;
  background: color-mix(in srgb, var(--main-50) 62%, var(--gray-0));
}
.linked-run-banner > span {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--main-color);
}
.linked-run-banner > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.linked-run-banner small,
.linked-run-banner em {
  color: var(--gray-500);
  font-size: 10px;
  font-style: normal;
}
.linked-run-banner b {
  overflow: hidden;
  color: var(--gray-800);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.linked-run-banner button {
  min-height: 30px;
  padding: 4px 10px;
  border: 1px solid var(--main-100);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--main-color);
  font-size: 10px;
  cursor: pointer;
}
.create-form {
  display: grid;
  gap: 14px;
  padding: 0;
  background: transparent;
}
.launch-section {
  overflow: hidden;
  border: 1px solid var(--gray-150);
  border-radius: 15px;
  background: var(--gray-0);
  box-shadow: 0 8px 24px color-mix(in srgb, var(--gray-900) 4%, transparent);
}
.launch-question-section {
  border-color: color-mix(in srgb, var(--main-color) 20%, var(--gray-150));
  box-shadow: 0 10px 28px color-mix(in srgb, var(--main-color) 6%, transparent);
}
.launch-section-head {
  display: flex;
  min-height: 58px;
  align-items: center;
  gap: 11px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--gray-100);
  background: linear-gradient(
    135deg,
    var(--gray-25),
    color-mix(in srgb, var(--main-50) 38%, var(--gray-0))
  );
}
.launch-section-head > div {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}
.launch-section-head b {
  color: var(--gray-900);
  font-size: 13px;
  font-weight: 650;
}
.launch-section-head small {
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.45;
}
.launch-section-head > svg {
  flex: 0 0 auto;
  color: var(--main-color);
  opacity: 0.8;
}
.launch-step {
  display: inline-grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  border-radius: 9px;
  background: var(--main-50);
  color: var(--main-color);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.04em;
}
.launch-section-body {
  padding: 18px 18px 4px;
}
.launch-section-body :deep(.ant-form-item-label > label) {
  color: var(--gray-700);
  font-size: 12px;
  font-weight: 600;
}
.launch-section-body :deep(.ant-input),
.launch-section-body :deep(.ant-input-affix-wrapper),
.launch-section-body :deep(.ant-select-selector) {
  border-radius: 9px !important;
}
.launch-section-body :deep(textarea.ant-input) {
  padding: 11px 12px;
  line-height: 1.65;
}
.launch-section-body :deep(.ant-form-item-extra) {
  margin-top: 6px;
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.55;
}
.launch-mode-picker {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
  margin-bottom: 16px;
}
.launch-mode-picker button {
  display: grid;
  gap: 3px;
  padding: 11px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-25);
  color: var(--gray-700);
  cursor: pointer;
  text-align: left;
}
.launch-mode-picker button.active {
  border-color: var(--main-300);
  background: var(--main-50);
  color: var(--main-color);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--main-100) 65%, transparent);
}
.launch-mode-picker button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.launch-mode-picker b {
  font-size: 12px;
}
.launch-mode-picker small {
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.5;
}
.divergence-axis-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: -4px 0 16px;
}
.divergence-axis-list span {
  border-color: var(--gray-150);
  background: var(--gray-25);
  color: var(--gray-600);
  font-weight: 500;
}
.runtime-grid {
  align-items: start;
}
.launch-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 15px 16px;
  border: 1px solid var(--main-100);
  border-radius: 14px;
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--main-50) 72%, var(--gray-0)),
    var(--gray-0)
  );
}
.launch-footer > div,
.launch-footer > div > span {
  display: flex;
  min-width: 0;
}
.launch-footer > div {
  align-items: center;
  gap: 10px;
  color: var(--main-color);
}
.launch-footer > div > span {
  flex-direction: column;
  gap: 2px;
}
.launch-footer b {
  color: var(--gray-800);
  font-size: 12px;
}
.launch-footer small {
  color: var(--gray-500);
  font-size: 10px;
}
.launch-footer :deep(.ant-btn) {
  min-width: 150px;
  height: 40px;
  border: 0;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 650;
  box-shadow: 0 8px 20px color-mix(in srgb, var(--main-color) 22%, transparent);
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.research-binding-builder {
  display: grid;
  gap: 12px;
  margin: 0 0 14px;
  padding: 16px;
  border: 1px solid var(--main-100);
  border-radius: 14px;
  background: color-mix(in srgb, var(--main-50) 42%, var(--gray-0));
}
.binding-builder-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.binding-builder-head > span:first-child {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 9px;
  background: var(--main-100);
  color: var(--main-color);
}
.binding-builder-head > div {
  display: grid;
  flex: 1;
  gap: 2px;
}
.binding-builder-head b {
  color: var(--gray-850, var(--gray-900));
  font-size: 13px;
}
.binding-builder-head small {
  color: var(--gray-500);
  font-size: 11px;
  line-height: 1.5;
}
.binding-status {
  color: var(--main-color);
  font-size: 10px;
}
.binding-object-picker {
  display: grid;
  gap: 10px;
}
.binding-type-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--gray-100);
  border-radius: 12px;
  background: var(--gray-0);
}
.binding-type-field :deep(.ant-radio-group) {
  display: flex;
  flex: 0 0 auto;
}
.binding-type-field :deep(.ant-radio-button-wrapper) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 118px;
  justify-content: center;
}
.binding-option-count {
  display: inline-grid;
  min-width: 18px;
  height: 18px;
  place-items: center;
  padding: 0 5px;
  border-radius: 9px;
  background: color-mix(in srgb, currentColor 10%, transparent);
  font-size: 10px;
  line-height: 18px;
}
.binding-object-panel {
  display: grid;
  align-content: start;
  gap: 8px;
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--gray-100);
  border-radius: 12px;
  background: var(--gray-0);
}
.binding-object-panel.selected-object-panel {
  border-color: color-mix(in srgb, var(--main-color) 18%, var(--gray-100));
}
.binding-object-panel.reference-object-panel {
  background: color-mix(in srgb, var(--gray-25) 78%, var(--gray-0));
}
.binding-object-panel > header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 1px 1px 7px;
  border-bottom: 1px solid var(--gray-100);
}
.binding-object-panel > header > span {
  display: grid;
  gap: 1px;
  min-width: 0;
}
.binding-object-panel > header b {
  color: var(--gray-850, var(--gray-900));
  font-size: 12px;
}
.binding-object-panel > header small {
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.4;
}
.binding-step {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--gray-100);
  border-radius: 10px;
  background: var(--gray-0);
  transition:
    border-color 0.16s ease,
    opacity 0.16s ease;
}
.binding-step:hover {
  border-color: var(--main-150, var(--main-100));
}
.binding-step.muted {
  opacity: 0.64;
}
.binding-step-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.binding-step-copy b {
  color: var(--gray-800);
  font-size: 12px;
}
.binding-step-copy small {
  overflow: hidden;
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.binding-step :deep(.ant-select) {
  width: 100%;
  min-width: 0;
}
.binding-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 11px;
  border-radius: 10px;
  background: var(--main-50);
  color: var(--main-color);
}
.binding-summary > span {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-width: 0;
}
.binding-summary small {
  flex: 0 0 auto;
  color: var(--gray-500);
  font-size: 10px;
}
.binding-summary b {
  overflow: hidden;
  font-size: 11px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.reference-preview {
  display: -webkit-box;
  margin: -3px 2px 0;
  overflow: hidden;
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.binding-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 10px;
  border: 1px solid #f1dadd;
  border-radius: 9px;
  background: #fff7f7;
  color: #b4505b;
  font-size: 11px;
}
.binding-error button {
  border: 0;
  background: transparent;
  color: inherit;
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
}
.capability-switches {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: 2px 0 14px;
}
.capability-switches label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: var(--gray-25);
  transition:
    border-color 0.16s ease,
    background-color 0.16s ease,
    box-shadow 0.16s ease;
}
.capability-switches label.enabled {
  border-color: color-mix(in srgb, var(--main-color) 22%, var(--gray-150));
  background: color-mix(in srgb, var(--main-50) 58%, var(--gray-0));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--main-color) 4%, transparent);
}
.capability-switches label > span {
  display: grid;
  grid-template-columns: 22px 1fr;
  align-items: center;
  min-width: 0;
  text-align: left;
}
.capability-switches svg {
  grid-row: 1 / 3;
  color: var(--main-color);
  opacity: 0.72;
}
.capability-switches label.enabled svg {
  opacity: 1;
}
.capability-switches b {
  color: var(--gray-800);
  font-size: 13px;
}
.capability-switches small {
  color: var(--gray-500);
  font-size: 11px;
}
@keyframes pulse {
  0%,
  80%,
  100% {
    opacity: 0.3;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-2px);
  }
}
@media (max-width: 820px) {
  .deep-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .capability-pills {
    justify-content: flex-start;
  }
  .form-grid,
  .capability-switches {
    grid-template-columns: 1fr;
  }
  .message-list,
  .composer-wrap {
    padding-right: 16px;
    padding-left: 16px;
  }
  .branch-bar {
    padding-right: 16px;
    padding-left: 16px;
  }
  .branch-bar small {
    display: none;
  }
  .research-context-panel {
    margin-right: 16px;
    margin-left: 16px;
  }
  .context-metrics {
    flex-wrap: wrap;
  }
}

/* The native conversation owns the message and composer layout. Keep the equipment
   controls compact so they never displace its live run, approval or artifact UI. */
.deep-research-shell {
  --deep-sidebar-width: clamp(248px, 19vw, 288px);
  position: relative;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.deep-sidebar {
  display: flex;
  width: var(--deep-sidebar-width);
  flex: 0 0 var(--deep-sidebar-width);
  flex-direction: column;
  min-height: 0;
}
.deep-sidebar.collapsed {
  width: 52px;
  flex-basis: 52px;
}
.deep-sidebar-head {
  flex: 0 0 48px;
  background: var(--gray-0);
}
.deep-sidebar-history {
  display: flex;
  flex: 1;
  width: 100%;
  min-height: 0;
  overflow: hidden;
}
.deep-main {
  position: relative;
  min-height: 0;
  overflow: hidden;
}
.deep-session-switch-layer {
  position: absolute;
  z-index: 20;
  inset: 0;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 14px;
  background: color-mix(in srgb, var(--gray-0) 24%, transparent);
  backdrop-filter: blur(1.5px);
  cursor: progress;
}
.deep-session-switch-layer > span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--gray-150);
  border-radius: 999px;
  background: color-mix(in srgb, var(--gray-0) 94%, transparent);
  color: var(--gray-700);
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 8px 24px color-mix(in srgb, var(--gray-900) 12%, transparent);
}
.deep-switch-error {
  position: absolute;
  z-index: 21;
  top: 10px;
  right: 16px;
  left: 16px;
  display: flex;
  min-height: 36px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 10px 7px 12px;
  border: 1px solid #efc6cc;
  border-radius: 9px;
  background: #fff7f8;
  color: #9f4050;
  font-size: 11px;
  box-shadow: 0 8px 24px rgb(109 46 57 / 10%);
}
.deep-switch-error button {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid #e7b6be;
  border-radius: 6px;
  background: #fff;
  color: #9f4050;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
.deep-session-initial-loading {
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: var(--gray-500);
  text-align: center;
}
.deep-session-initial-loading svg {
  color: var(--main-color);
}
.deep-session-initial-loading h1,
.deep-session-initial-loading p {
  margin: 0;
}
.deep-session-initial-loading h1 {
  color: var(--gray-800);
  font-size: 18px;
}
.deep-session-initial-loading p {
  max-width: 440px;
  font-size: 12px;
  line-height: 1.6;
}
.deep-session-switch-enter-active,
.deep-session-switch-leave-active {
  transition: opacity 0.14s ease;
}
.deep-session-switch-enter-from,
.deep-session-switch-leave-to {
  opacity: 0;
}
.spin {
  animation: deep-session-view-spin 0.9s linear infinite;
}
@keyframes deep-session-view-spin {
  to {
    transform: rotate(360deg);
  }
}
.native-deep-chat {
  overflow: hidden;
}
.native-deep-chat :deep(.chat-box),
.native-deep-chat :deep(.bottom .message-input-wrapper) {
  max-width: min(1120px, calc(100% - 32px));
}
.native-deep-chat :deep(.bottom.start-screen) {
  max-width: min(1120px, calc(100% - 32px));
}
.native-deep-chat :deep(.deep-inline-candidate-versions) {
  max-height: min(390px, 42vh);
  flex: 0 0 auto;
  overflow: auto;
  margin: 0;
  padding: 10px 18px 12px;
  border-top: 0;
  border-bottom: 1px solid var(--gray-150);
  background: var(--gray-25);
}
.deep-archived-banner {
  flex: 0 0 auto;
  padding: 8px 18px;
  border-bottom: 1px solid #e2d9b8;
  background: #fff9e8;
  color: #826b31;
  font-size: 11px;
  line-height: 1.5;
  text-align: center;
}
.technology-cabin-panel {
  display: grid;
  grid-template-columns: minmax(150px, auto) minmax(180px, 1fr);
  align-items: center;
  gap: 14px;
  flex: 0 0 auto;
  padding: 10px 20px;
  border-bottom: 1px solid var(--main-100);
  background:
    linear-gradient(100deg, color-mix(in srgb, var(--main-50) 82%, transparent), transparent 58%),
    var(--gray-0);
}
.technology-cabin-heading,
.technology-cabin-object,
.technology-cabin-actions,
.technology-cabin-actions button,
.technology-cabin-object em {
  display: flex;
  align-items: center;
}
.technology-cabin-heading {
  gap: 9px;
}
.technology-cabin-icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 10px;
  background: var(--main-color);
  color: white;
  box-shadow: 0 6px 18px color-mix(in srgb, var(--main-color) 22%, transparent);
}
.technology-cabin-heading > div {
  display: grid;
  gap: 1px;
}
.technology-cabin-heading small,
.technology-cabin-object > span,
.technology-cabin-actions small {
  color: var(--gray-500);
  font-size: 9px;
  line-height: 1.35;
}
.technology-cabin-heading strong {
  color: var(--gray-900);
  font-size: 15px;
}
.technology-cabin-object {
  min-width: 0;
  flex-wrap: wrap;
  gap: 2px 8px;
  padding-left: 14px;
  border-left: 1px solid var(--main-100);
}
.technology-cabin-object > span {
  width: 100%;
}
.technology-cabin-object b {
  min-width: 0;
  overflow: hidden;
  color: var(--gray-850);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.technology-cabin-object em {
  gap: 3px;
  padding: 2px 6px;
  border: 1px solid var(--main-100);
  border-radius: 999px;
  background: var(--main-50);
  color: var(--main-color);
  font-size: 9px;
  font-style: normal;
  white-space: nowrap;
}
.technology-cabin-actions {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: repeat(7, minmax(92px, 1fr));
  min-width: 0;
  gap: 6px;
  overflow-x: auto;
}
.technology-cabin-actions button {
  min-width: 0;
  flex: 1;
  gap: 6px;
  padding: 6px 7px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-750);
  text-align: left;
  cursor: pointer;
}
.technology-cabin-actions button:hover:not(:disabled),
.technology-cabin-actions button:focus-visible:not(:disabled) {
  border-color: var(--main-300);
  background: var(--main-50);
  color: var(--main-color);
}
.technology-cabin-actions button.primary {
  border-color: var(--main-color);
  background: var(--main-color);
  color: #fff;
}
.technology-cabin-actions button.primary > span {
  background: rgb(255 255 255 / 18%);
  color: #fff;
}
.technology-cabin-actions button.primary:hover:not(:disabled),
.technology-cabin-actions button.primary:focus-visible:not(:disabled) {
  border-color: var(--main-700);
  background: var(--main-700);
  color: #fff;
}
.technology-cabin-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.technology-cabin-actions button > span {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  background: var(--gray-75);
  color: var(--main-color);
  font-size: 9px;
  font-weight: 700;
}
.technology-cabin-actions button > div {
  display: grid;
  min-width: 0;
  gap: 1px;
}
.technology-cabin-actions b {
  overflow: hidden;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.technology-cabin-actions small {
  display: none;
}
.technology-cabin-panel > p {
  display: none;
  margin: 0;
  color: var(--gray-500);
  font-size: 9px;
}
:global(html.dark) .deep-switch-error {
  border-color: #70414a;
  background: #352329;
  color: #f2adb8;
}
:global(html.dark) .deep-switch-error button {
  border-color: #70414a;
  background: #251c21;
  color: #f2adb8;
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
  .deep-session-switch-enter-active,
  .deep-session-switch-leave-active {
    transition: none;
  }
}
.deep-mobile-topbar {
  display: none;
}
.branch-bar {
  flex: 0 0 auto;
  min-width: 0;
  padding-inline: 20px;
}
.branch-bar button {
  flex: 0 0 auto;
}
.research-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 54px;
  flex: 0 0 auto;
  padding: 9px 20px;
  border-bottom: 1px solid var(--gray-100);
  background: var(--gray-0);
}
.research-summary-primary,
.research-summary-actions {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 9px;
}
.research-summary-primary {
  flex: 1;
}
.research-summary-kicker {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 5px;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 650;
}
.research-summary-primary strong {
  overflow: hidden;
  color: var(--gray-850, var(--gray-900));
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.seed-count {
  flex: 0 0 auto;
  color: var(--gray-500);
  font-size: 11px;
}
.research-mode-badge {
  flex: 0 0 auto;
  padding: 3px 7px;
  border: 1px solid color-mix(in srgb, var(--color-success-500) 35%, var(--gray-150));
  border-radius: 999px;
  background: var(--color-success-50);
  color: var(--color-success-700);
  font-size: 10px;
  font-weight: 650;
}
.research-mode-badge.divergent {
  border-color: var(--main-200);
  background: var(--main-50);
  color: var(--main-color);
}
.research-summary-actions {
  justify-content: flex-end;
  flex: 0 0 auto;
}
.research-summary .capability-pill {
  height: 24px;
  font-size: 10px;
}
.focus-mode-button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.research-context-panel {
  position: absolute;
  top: 60px;
  right: 20px;
  z-index: 12;
  display: grid;
  width: min(540px, calc(100% - 40px));
  max-height: min(62vh, 520px);
  margin: 0;
  padding: 16px;
  overflow-y: auto;
  box-shadow: 0 18px 48px color-mix(in srgb, var(--gray-900) 15%, transparent);
}
.context-panel-heading,
.context-panel-heading > span {
  display: flex;
  align-items: center;
  gap: 8px;
}
.context-panel-heading {
  justify-content: space-between;
  color: var(--main-color);
}
.research-context-panel .context-topic {
  color: var(--gray-700);
  font-size: 12px;
  line-height: 1.6;
}
.research-context-panel .context-metrics span {
  display: flex;
}
.deep-empty-state {
  display: grid;
  justify-items: center;
  gap: 10px;
  width: min(620px, 100%);
  margin: clamp(32px, 9vh, 110px) auto 28px;
  padding: 20px;
  text-align: center;
}
.deep-empty-icon {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  border-radius: 17px;
  background: var(--main-50);
  color: var(--main-color);
}
.deep-empty-state h2 {
  margin: 4px 0 0;
  color: var(--gray-900);
  font-size: clamp(17px, 2vw, 22px);
}
.deep-empty-state p {
  max-width: 500px;
  margin: 0;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.7;
}
.deep-mention-shortcuts,
.deep-empty-guidance {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}
.deep-mention-shortcuts {
  margin-top: 8px;
}
.deep-mention-shortcuts button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--gray-700);
  font-size: 12px;
  cursor: pointer;
}
.deep-mention-shortcuts button:hover {
  border-color: var(--main-200);
  color: var(--main-color);
}
.deep-empty-guidance {
  margin-top: 10px;
  color: var(--gray-400);
  font-size: 11px;
}
.deep-empty-guidance span + span::before {
  content: '·';
  margin-right: 8px;
}
.focus-research-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: color-mix(in srgb, var(--gray-0) 92%, var(--main-50));
  color: var(--gray-700);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
}
.focus-research-trigger svg {
  color: var(--main-color);
}
.focus-research-trigger em {
  max-width: 106px;
  overflow: hidden;
  color: var(--main-color);
  font-size: 10px;
  font-weight: 650;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.focus-research-trigger > svg:last-child {
  color: var(--gray-400);
  transition: transform 0.16s ease;
}
.focus-research-trigger[aria-expanded='true'] > svg:last-child {
  transform: rotate(180deg);
}
.focus-research-trigger:hover {
  border-color: var(--main-200);
  color: var(--main-color);
}
.research-control-popover {
  display: grid;
  width: min(448px, calc(100vw - 32px));
  overflow: hidden;
  border: 1px solid var(--gray-150);
  border-radius: 14px;
  background: var(--gray-0);
  box-shadow: 0 18px 50px color-mix(in srgb, var(--gray-900) 16%, transparent);
}
:global(.deep-research-control-popover .ant-popover-inner) {
  padding: 0;
  overflow: hidden;
  border-radius: 14px;
  background: transparent;
}
:global(.deep-research-control-popover .ant-popover-inner-content) {
  padding: 0;
}
.research-control-head,
.research-control-object,
.research-control-step,
.research-control-footer {
  display: flex;
  align-items: center;
}
.research-control-head {
  justify-content: space-between;
  gap: 16px;
  padding: 14px 15px 12px;
  border-bottom: 1px solid var(--gray-100);
  background: color-mix(in srgb, var(--gray-0) 88%, var(--main-50));
}
.research-control-head > div {
  display: grid;
  gap: 2px;
}
.research-control-head b {
  color: var(--gray-850, var(--gray-900));
  font-size: 14px;
}
.research-control-head small,
.research-control-step small {
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.45;
}
.research-control-close {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--gray-500);
  cursor: pointer;
}
.research-control-close:hover {
  background: var(--gray-100);
  color: var(--gray-800);
}
.research-control-object {
  gap: 8px;
  margin: 12px 15px 4px;
  padding: 8px 10px;
  border-radius: 9px;
  background: var(--gray-50);
}
.research-control-object span {
  flex: 0 0 auto;
  color: var(--gray-500);
  font-size: 10px;
}
.research-control-object strong {
  min-width: 0;
  overflow: hidden;
  color: var(--gray-750, var(--gray-800));
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.research-control-step {
  gap: 8px;
  padding: 10px 15px 7px;
}
.research-control-step.compact-step {
  padding-top: 12px;
}
.research-control-step > span {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 50%;
  background: var(--main-50);
  color: var(--main-color);
  font-size: 10px;
  font-weight: 700;
}
.research-control-step > div {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 7px;
}
.research-control-step b {
  color: var(--gray-800);
  font-size: 11px;
}
.research-mode-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 0 15px;
}
.research-mode-cards > button {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 62px;
  padding: 8px 9px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
  text-align: left;
  cursor: pointer;
}
.research-mode-cards > button > span {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 8px;
  background: var(--gray-50);
  color: var(--gray-500);
}
.research-mode-cards > button > div {
  display: grid;
  gap: 2px;
}
.research-mode-cards b {
  color: var(--gray-800);
  font-size: 11px;
}
.research-mode-cards small {
  color: var(--gray-500);
  font-size: 9px;
  line-height: 1.45;
}
.research-mode-cards > button:hover,
.research-mode-cards > button.active {
  border-color: var(--main-200);
  background: color-mix(in srgb, var(--gray-0) 88%, var(--main-50));
}
.research-mode-cards > button.active {
  box-shadow: inset 0 0 0 1px var(--main-100);
}
.research-mode-cards > button.active > span,
.research-mode-cards > button.active b {
  color: var(--main-color);
}
.research-mode-cards > button.active > span {
  background: var(--main-50);
}
.research-section-options,
.research-action-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 15px;
}
.research-section-options button,
.research-action-options button {
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-650, var(--gray-700));
  font-size: 10px;
  cursor: pointer;
}
.research-section-options button:hover,
.research-section-options button.active,
.research-action-options button:hover {
  border-color: var(--main-200);
  background: var(--main-50);
  color: var(--main-color);
}
.research-control-footer {
  justify-content: flex-end;
  gap: 7px;
  margin-top: 13px;
  padding: 10px 15px 12px;
  border-top: 1px solid var(--gray-100);
}
.research-control-footer button {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-650, var(--gray-700));
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
}
.research-control-footer .research-card-action {
  border-color: var(--main-200);
  background: var(--main-50);
  color: var(--main-color);
}
.research-control-footer button:hover {
  border-color: var(--main-200);
  color: var(--main-color);
}
.deep-domain-projection {
  display: contents;
}
.create-workspace {
  max-height: 100%;
  overflow-y: auto;
}
.deep-load-error {
  text-align: center;
}
.deep-load-error p {
  color: var(--gray-500);
}

:global(html.dark) .deep-sidebar {
  border-color: #343a47;
  background: #151a27;
}
:global(html.dark) .deep-sidebar-head,
:global(html.dark) .deep-mobile-topbar,
:global(html.dark) .research-summary,
:global(html.dark) .branch-bar {
  border-color: #343a47;
  background: #1c2333;
}
:global(html.dark) .new-session-button {
  border-color: #3b4559;
  background: #1c2333;
  color: #d8deeb;
}
:global(html.dark) .new-session-button:hover {
  border-color: #716ee0;
  background: #242642;
  color: #b9b7ff;
}
:global(html.dark) .deep-archived-banner {
  border-color: #6c5a2d;
  background: #302813;
  color: #dbc47f;
}
:global(html.dark) .technology-cabin-panel {
  border-color: #343a47;
  background: linear-gradient(100deg, rgb(52 48 92 / 42%), transparent 58%), #1c2333;
}
:global(html.dark) .technology-cabin-actions button {
  border-color: #3b4559;
  background: #202838;
  color: #d8deeb;
}
:global(html.dark) .technology-cabin-actions button > span {
  background: #2b3345;
}

@media (max-width: 960px) {
  .deep-research-shell {
    flex-direction: column;
  }
  .deep-sidebar {
    position: static;
    display: flex;
    width: 100%;
    height: 88px;
    max-height: 88px;
    flex: 0 0 88px;
    border-right: 0;
    border-bottom: 1px solid #e5e9f3;
    box-shadow: none;
  }
  .deep-sidebar.collapsed {
    display: flex;
    width: 100%;
    flex-basis: 88px;
  }
  .technology-cabin-panel {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .technology-cabin-actions {
    grid-column: 1 / -1;
  }
  .deep-sidebar-head,
  .new-session-button {
    display: none;
  }
  .deep-sidebar.collapsed > .deep-sidebar-history,
  .deep-sidebar-history {
    display: flex;
  }
  .deep-mobile-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-height: 42px;
    flex: 0 0 auto;
    padding: 4px 14px;
    border-bottom: 1px solid var(--gray-100);
    background: var(--gray-0);
  }
  .deep-mobile-topbar span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 650;
  }
  .deep-main {
    width: 100%;
    min-height: 0;
    flex: 1 1 0;
  }
  .research-summary {
    padding-inline: 14px;
  }
  .research-summary .capability-pill {
    display: none;
  }
}
@media (max-width: 820px) {
  .research-summary {
    gap: 8px;
  }
  .research-summary-kicker,
  .seed-count:not(.current-section-count) {
    display: none;
  }
  .current-section-count {
    display: inline-flex;
    flex: 0 0 auto;
    min-height: 22px;
    align-items: center;
    padding: 0 7px;
    border: 1px solid var(--main-100);
    border-radius: 999px;
    background: var(--main-50);
    color: var(--main-color);
    font-size: 10px;
    font-weight: 650;
    white-space: nowrap;
  }
  .research-context-panel {
    top: 60px;
    right: 12px;
    width: calc(100% - 24px);
  }
  .create-workspace {
    width: calc(100% - 28px);
    padding: 28px 0;
  }
  .create-intro {
    align-items: flex-start;
    gap: 12px;
  }
  .create-intro-tags {
    display: none;
  }
  .linked-run-banner {
    grid-template-columns: 32px minmax(0, 1fr) auto;
  }
  .linked-run-banner em {
    display: none;
  }
  .create-form {
    padding: 0;
  }
  .launch-section-body {
    padding: 15px 14px 2px;
  }
  .launch-section-head {
    padding-inline: 14px;
  }
  .launch-footer {
    align-items: stretch;
    flex-direction: column;
  }
  .launch-footer :deep(.ant-btn) {
    width: 100%;
  }
  .binding-type-field {
    align-items: stretch;
    flex-direction: column;
  }
  .binding-type-field :deep(.ant-radio-group) {
    width: 100%;
  }
  .binding-type-field :deep(.ant-radio-button-wrapper) {
    flex: 1;
    min-width: 0;
  }
  .binding-step {
    grid-template-columns: 1fr;
  }
  .binding-step-copy small {
    white-space: normal;
  }
  .binding-summary > span {
    display: grid;
    gap: 1px;
  }
}
@media (max-width: 560px) {
  .technology-cabin-panel {
    grid-template-columns: 1fr;
    gap: 8px;
    padding: 10px 12px;
  }
  .technology-cabin-object {
    padding-left: 0;
    border-left: 0;
  }
  .technology-cabin-actions {
    grid-column: auto;
    overflow-x: auto;
    padding-bottom: 2px;
  }
  .technology-cabin-actions button {
    min-width: 116px;
  }
  .technology-cabin-panel > p {
    display: block;
  }
  .launch-mode-picker {
    grid-template-columns: 1fr;
  }
  .research-mode-cards {
    grid-template-columns: 1fr;
  }
  .research-control-step > div {
    display: grid;
    gap: 1px;
  }
  .focus-research-trigger > span {
    display: none;
  }
  .focus-research-trigger em {
    max-width: 92px;
  }
}

@media (max-width: 720px) {
  .deep-sidebar,
  .deep-sidebar.collapsed {
    height: 80px;
    max-height: 80px;
    flex-basis: 80px;
  }
}

@media (min-width: 961px) and (max-height: 460px) {
  .deep-sidebar {
    width: 232px;
    flex-basis: 232px;
  }
}
</style>
