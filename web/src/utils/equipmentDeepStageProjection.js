export const EQUIPMENT_DEEP_STAGES = Object.freeze([
  ['context', '研究边界'],
  ['s3_divergence', '开放探索'],
  ['council_critique', '交叉复核'],
  ['s4_mapping', '方向深化'],
  ['s6_authoring', '形成画像']
])

export const EQUIPMENT_SECTION_DEEPEN_STAGES = Object.freeze([
  ['section_baseline', '栏目基线'],
  ['section_technical', '技术攻关'],
  ['section_process', '流程推演'],
  ['section_mechanism', '机理深化'],
  ['section_revision', '修订建议']
])

const text = (value) => String(value ?? '').trim()
const objectValue = (value) =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {}
const arrayValue = (value) => (Array.isArray(value) ? value : [])

const parseJson = (value) => {
  if (typeof value !== 'string') return value
  const source = value.trim()
  if (!source || (!source.startsWith('{') && !source.startsWith('['))) return value
  try {
    return JSON.parse(source)
  } catch {
    return value
  }
}

const normalizedStatus = (value) => text(value).toLowerCase().replaceAll('-', '_')
const terminalSuccess = (value) => ['completed', 'success', 'succeeded', 'verified'].includes(normalizedStatus(value))
const terminalFailure = (value) =>
  ['failed', 'blocked', 'cancelled', 'canceled', 'rejected'].includes(normalizedStatus(value))

const messageText = (message) => {
  const content = message?.content
  if (typeof content === 'string') return content.trim()
  if (!Array.isArray(content)) return ''
  return content
    .map((part) => (typeof part === 'string' ? part : part?.text || part?.content || ''))
    .filter(Boolean)
    .join('\n')
    .trim()
}

export const flattenDeepConversationMessages = (conversations) =>
  arrayValue(conversations).flatMap((conversation) => arrayValue(conversation?.messages))

const toolName = (call) => text(call?.name || call?.function?.name)

const toolArguments = (call) => {
  const value = parseJson(call?.args ?? call?.function?.arguments)
  return value && typeof value === 'object' ? value : {}
}

const toolResult = (call) => {
  const raw = call?.tool_call_result?.content ?? call?.result ?? call?.output
  return parseJson(raw)
}

export const collectDeepToolCalls = (conversations) =>
  flattenDeepConversationMessages(conversations).flatMap((message) =>
    arrayValue(message?.tool_calls).map((call) => ({
      ...call,
      name: toolName(call),
      arguments: toolArguments(call),
      result: toolResult(call),
      message
    }))
  )

const CANDIDATE_COLLECTION_KEYS = new Set([
  'candidates',
  'candidate_reviews',
  'directions',
  'innovation_directions',
  'proposals',
  'proposal_briefs',
  'research_frontier',
  'selected_candidates'
])
const DECISION_COLLECTION_KEYS = new Set(['decisions', 'candidate_reviews', 'adjudications'])
const REJECTED_COLLECTION_KEYS = new Set([
  'rejected',
  'rejected_directions',
  'discarded_candidates'
])
const ASSUMPTION_COLLECTION_KEYS = new Set(['assumption_ledger', 'assumptions'])
const QUESTION_COLLECTION_KEYS = new Set(['open_questions', 'research_gaps', 'unresolved_questions'])

const walkCollections = (sources, keys) => {
  const rows = []
  const seen = new WeakSet()
  const visit = (value, depth = 0) => {
    const parsed = parseJson(value)
    if (!parsed || typeof parsed !== 'object' || depth > 6) return
    if (seen.has(parsed)) return
    seen.add(parsed)
    if (Array.isArray(parsed)) {
      parsed.slice(0, 80).forEach((item) => visit(item, depth + 1))
      return
    }
    Object.entries(parsed)
      .slice(0, 100)
      .forEach(([key, item]) => {
        if (keys.has(key) && Array.isArray(item)) rows.push(...item.slice(0, 30))
        visit(item, depth + 1)
      })
  }
  arrayValue(sources).forEach((source) => visit(source))
  return rows
}

const candidateName = (value) => {
  if (typeof value === 'string') return text(value)
  const item = objectValue(value)
  return text(
    item.candidate_name ||
      item.innovation_variant_name ||
      item.name ||
      item.direction ||
      item.title ||
      item.equipment_name
  )
}

const reasonableLabel = (value) => {
  const label = text(value).replace(/\s+/g, ' ')
  return label.length >= 2 && label.length <= 96 ? label : ''
}

const normalizeCandidate = (value) => {
  const item = typeof value === 'string' ? { name: value } : objectValue(value)
  const name = reasonableLabel(candidateName(item))
  if (!name) return null
  return {
    name,
    summary: text(
      item.summary || item.why_promising || item.rationale || item.reason || item.overview
    ).slice(0, 420),
    angle: text(item.winning_angle || item.axis || item.changed_assumption).slice(0, 160),
    equipmentForm: text(item.innovation_equipment_form || item.equipment_form).slice(0, 160),
    verdict: normalizedStatus(item.verdict || item.status),
    nextProbe: text(item.next_probe || item.next_step).slice(0, 240)
  }
}

const uniqueByName = (rows) => {
  const values = new Map()
  rows.forEach((row) => {
    if (!row?.name) return
    const key = row.name.toLowerCase()
    values.set(key, { ...(values.get(key) || {}), ...row })
  })
  return [...values.values()]
}

const normalizeDecision = (value, fallbackVerdict = '') => {
  const item = typeof value === 'string' ? { candidate: value } : objectValue(value)
  const name = reasonableLabel(
    item.candidate || item.candidate_name || item.name || item.direction || item.title
  )
  if (!name) return null
  return {
    name,
    verdict: normalizedStatus(item.verdict || item.status || fallbackVerdict),
    reason: text(item.reason || item.rationale || item.summary).slice(0, 420)
  }
}

const stringRows = (rows, fields) =>
  rows
    .map((value) => {
      if (typeof value === 'string') return text(value)
      const item = objectValue(value)
      return fields.map((field) => text(item[field])).find(Boolean) || ''
    })
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)

export const capabilityVersionsForDeepSession = (versions, sessionId) => {
  const expected = text(sessionId)
  if (!expected) return []
  return arrayValue(versions).filter((version) => {
    const snapshot = objectValue(version?.snapshot)
    return text(version?.session_id || snapshot.session_id) === expected
  })
}

const normalizeHandoff = (run) => {
  const status = normalizedStatus(run?.status)
  return {
    id: text(run?.run_id || run?.id || run?.child_thread_id || run?.subagent_slug),
    name: text(run?.name || run?.display_name || run?.subagent_name || run?.subagent_slug || '协同 Agent'),
    task: text(run?.description || run?.task || run?.prompt).slice(0, 320),
    summary: text(run?.result_summary || run?.summary || run?.error || run?.error_message).slice(0, 420),
    status,
    statusLabel: terminalFailure(status)
      ? '未完成'
      : terminalSuccess(status)
        ? '已交接'
        : status === 'running'
          ? '进行中'
          : '等待中'
  }
}

const stage = (key, status, detail, definitions = EQUIPMENT_DEEP_STAGES) => ({
  key,
  label: definitions.find(([stageKey]) => stageKey === key)?.[1] || key,
  status,
  detail
})

export const projectEquipmentDeepStage = ({
  session = null,
  agentState = null,
  conversations = [],
  todos = [],
  subagentRuns = [],
  versions = [],
  activeSkillIds = null,
  processing = false,
  createArtifact = false,
  researchMode = 'new_weapon_diverge',
  researchSection = ''
} = {}) => {
  const messages = flattenDeepConversationMessages(conversations)
  const tools = collectDeepToolCalls(conversations)
  const messageTextValue = messages.map(messageText).filter(Boolean).join('\n')
  const userText = messages
    .filter((item) => ['human', 'user'].includes(text(item?.type || item?.role).toLowerCase()))
    .map(messageText)
    .join('\n')
  const structuredSources = [
    session?.payload,
    session?.research_context,
    agentState,
    ...messages.map((item) => item?.extra_metadata || item?.metadata),
    ...tools.map((item) => item.arguments),
    ...tools.map((item) => item.result)
  ]
  const candidates = uniqueByName(
    walkCollections(structuredSources, CANDIDATE_COLLECTION_KEYS)
      .map(normalizeCandidate)
      .filter(Boolean)
  ).slice(0, 12)
  const decisions = uniqueByName(
    walkCollections(structuredSources, DECISION_COLLECTION_KEYS)
      .map((item) => normalizeDecision(item))
      .filter((item) => item && !['reject', 'rejected'].includes(item.verdict))
  ).slice(0, 8)
  const rejected = uniqueByName(
    [
      ...walkCollections(structuredSources, REJECTED_COLLECTION_KEYS).map((item) =>
        normalizeDecision(item, 'rejected')
      ),
      ...walkCollections(structuredSources, DECISION_COLLECTION_KEYS)
        .map((item) => normalizeDecision(item))
        .filter((item) => ['reject', 'rejected'].includes(item?.verdict))
    ].filter(Boolean)
  ).slice(0, 8)
  const assumptions = stringRows(
    walkCollections(structuredSources, ASSUMPTION_COLLECTION_KEYS),
    ['assumption', 'text', 'summary']
  ).slice(0, 8)
  const openQuestions = stringRows(
    walkCollections(structuredSources, QUESTION_COLLECTION_KEYS),
    ['question', 'gap', 'text', 'summary']
  ).slice(0, 8)
  const handoffs = arrayValue(subagentRuns).map(normalizeHandoff).filter((item) => item.id).slice(-8)
  const sessionVersions = capabilityVersionsForDeepSession(versions, session?.session_id)
  const activeTodos = arrayValue(todos)
  const failed = terminalFailure(session?.status || session?.payload?.status)
  const hasContextTool = tools.some((item) => item.name === 'equipment_deep_context')
  const saveTools = tools.filter((item) => item.name === 'save_equipment_capability_draft')
  const saveFailed = saveTools.some(
    (item) => item?.tool_call_result?.is_error || terminalFailure(item?.status)
  )
  const challengeSignal =
    /\/challenge\b|交叉复核|反证|失效边界|事实核验/.test(`${userText}\n${messageTextValue}`) ||
    handoffs.some((item) => /核验|审查|挑战|反证|fact|verify|critic/i.test(`${item.name} ${item.task}`))
  const mappingSignal =
    /\/synthesize\b|方向深化|能力映射|制胜逻辑|任务失能|作用机理/.test(
      `${userText}\n${messageTextValue}`
    ) || decisions.length > 0
  const authoringSignal =
    createArtifact ||
    /\/card\b|形成.{0,4}(?:能力卡|能力画像)|五栏能力/.test(userText) ||
    saveTools.length > 0
  const divergenceSignal =
    /\/diverge\b|开放发散|候选方向|正交假设|创新方向/.test(
      `${userText}\n${messageTextValue}`
    ) || candidates.length > 0 || handoffs.length > 0
  const handoffFailed = handoffs.some((item) => terminalFailure(item.status))
  const challengeCompleted =
    decisions.length > 0 ||
    rejected.length > 0 ||
    handoffs.some(
      (item) => terminalSuccess(item.status) && /核验|审查|挑战|反证|fact|verify|critic/i.test(`${item.name} ${item.task}`)
    )

  const isSectionDeepen = researchMode === 'section_deepen'
  const solutionSignal =
    /技术实现|技术方案|构型|材料|算法|接口|工艺|部署|关键指标|工程瓶颈|作战流程/.test(
      messageTextValue
    ) || candidates.length > 0
  const processSignal =
    /作战流程|任务链|信息流|火力流|作战时序|发现|决策|进入|作用|毁伤评估|协同接口|关键窗口/.test(
      messageTextValue
    )
  const mechanismSignal =
    /制胜逻辑|制胜机理|作用链|信息优势|时空窗口|成本交换|体系增益|反适应|优势形成/.test(
      messageTextValue
    ) || decisions.length > 0
  const revisionSignal =
    /本栏修订|修订建议|保留.{0,8}补充|纠错|待核验|形成新版/.test(messageTextValue) ||
    saveTools.length > 0

  if (isSectionDeepen) {
    let runningSectionKey = ''
    if (processing) {
      runningSectionKey = revisionSignal || authoringSignal
        ? 'section_revision'
        : mechanismSignal
          ? 'section_mechanism'
          : processSignal
            ? 'section_process'
            : solutionSignal
              ? 'section_technical'
              : 'section_baseline'
    }
    const observedStatus = (key, signal) =>
      runningSectionKey === key ? 'running' : signal ? 'observed' : 'idle'
    const targetLabel = text(researchSection) || '当前画像栏目'
    const sectionStages = [
      stage(
        'section_baseline',
        failed ? 'failed' : runningSectionKey === 'section_baseline' ? 'running' : session ? 'completed' : 'idle',
        session ? `已锁定「${targetLabel}」与当前装备身份` : '等待栏目与装备上下文',
        EQUIPMENT_SECTION_DEEPEN_STAGES
      ),
      stage(
        'section_technical',
        observedStatus('section_technical', solutionSignal),
        solutionSignal
          ? '已有技术卡点或攻关方案分析；可继续深化路线取舍'
          : '等待拆解技术卡点、工程痛点与解决路径',
        EQUIPMENT_SECTION_DEEPEN_STAGES
      ),
      stage(
        'section_process',
        observedStatus('section_process', processSignal),
        processSignal
          ? '已有作战流程推演；可继续闭合角色、时序与协同接口'
          : '等待推演任务链、作战时序与协同动作',
        EQUIPMENT_SECTION_DEEPEN_STAGES
      ),
      stage(
        'section_mechanism',
        observedStatus('section_mechanism', mechanismSignal),
        mechanismSignal
          ? '已有制胜机理分析；可继续闭合技术—动作—优势链路'
          : '等待深化作用链、体系增益与制胜逻辑',
        EQUIPMENT_SECTION_DEEPEN_STAGES
      ),
      stage(
        'section_revision',
        saveFailed
          ? 'failed'
          : runningSectionKey === 'section_revision'
            ? 'running'
            : sessionVersions.length
              ? 'completed'
              : revisionSignal
                ? 'observed'
                : 'idle',
        sessionVersions.length
          ? `已形成 ${sessionVersions.length} 个同装备待核验版本`
          : revisionSignal
            ? '已有修订内容；尚未保存为新版本'
            : '等待形成保留、补充、纠错与待核验清单',
        EQUIPMENT_SECTION_DEEPEN_STAGES
      )
    ]
    const memory = objectValue(session?.payload?.decision_memory || agentState?.decision_memory)
    const projectedActiveSkillIds = Array.isArray(activeSkillIds)
      ? activeSkillIds
      : arrayValue(session?.payload?.active_skill_ids)
    return {
      mode: 'section_deepen',
      title: '栏目深化',
      stages: sectionStages,
      candidates,
      decisions,
      rejected,
      handoffs,
      memory: {
        objective: text(memory.current_objective || memory.objective || session?.payload?.focus || session?.topic),
        assumptions,
        openQuestions,
        activeSkillIds: projectedActiveSkillIds.map(text).filter(Boolean)
      },
      hasDetails: Boolean(
        candidates.length ||
          decisions.length ||
          rejected.length ||
          handoffs.length ||
          assumptions.length ||
          openQuestions.length
      )
    }
  }

  let runningKey = ''
  if (processing) {
    runningKey = authoringSignal
      ? 's6_authoring'
      : mappingSignal
        ? 's4_mapping'
        : challengeSignal
          ? 'council_critique'
          : divergenceSignal || activeTodos.length || handoffs.length
            ? 's3_divergence'
            : 'context'
  }

  const stageRows = [
    stage(
      'context',
      failed ? 'failed' : runningKey === 'context' ? 'running' : session ? 'completed' : 'idle',
      hasContextTool ? '已读取关联 Query、能力版本与研究产物' : session ? '已锁定会话与研究对象' : '等待研究上下文'
    ),
    stage(
      's3_divergence',
      runningKey === 's3_divergence'
        ? 'running'
        : candidates.length
          ? 'completed'
          : divergenceSignal && !processing
            ? 'observed'
          : handoffFailed && !challengeSignal
            ? 'partial'
            : 'idle',
      candidates.length
        ? `已识别 ${candidates.length} 个可见候选方向`
        : divergenceSignal
          ? '已有探索分析；待整理为结构化候选'
          : '等待开放探索'
    ),
    stage(
      'council_critique',
      runningKey === 'council_critique'
        ? 'running'
        : challengeCompleted
          ? 'completed'
          : challengeSignal && !processing
            ? 'observed'
          : handoffFailed && challengeSignal
            ? 'partial'
            : 'idle',
      challengeCompleted
        ? `已记录 ${decisions.length + rejected.length} 项可见裁决`
        : challengeSignal
          ? '已有复核分析；待整理为可见裁决'
          : '等待交叉复核'
    ),
    stage(
      's4_mapping',
      runningKey === 's4_mapping'
        ? 'running'
        : decisions.length && mappingSignal && !processing
          ? 'completed'
          : mappingSignal && !processing
            ? 'observed'
          : 'idle',
      decisions.length
        ? `已收敛 ${decisions.length} 项方向判断`
        : mappingSignal
          ? '已有方向深化；待整理为结构化判断'
          : '等待方向深化'
    ),
    stage(
      's6_authoring',
      saveFailed
        ? 'failed'
        : runningKey === 's6_authoring'
          ? 'running'
          : sessionVersions.length
            ? 'completed'
            : authoringSignal && !processing
              ? 'observed'
            : 'idle',
      sessionVersions.length
        ? `本会话已形成 ${sessionVersions.length} 个能力画像版本`
        : authoringSignal
          ? '正在整理五栏能力画像'
          : '仅在明确成卡后写入新版本'
    )
  ]

  const memory = objectValue(session?.payload?.decision_memory || agentState?.decision_memory)
  const projectedActiveSkillIds = Array.isArray(activeSkillIds)
    ? activeSkillIds
    : arrayValue(session?.payload?.active_skill_ids)
  return {
    mode: 'new_weapon_diverge',
    title: '创新议事',
    stages: stageRows,
    candidates,
    decisions,
    rejected,
    handoffs,
    memory: {
      objective: text(memory.current_objective || memory.objective || session?.payload?.focus || session?.topic),
      assumptions,
      openQuestions,
      activeSkillIds: projectedActiveSkillIds.map(text).filter(Boolean)
    },
    hasDetails: Boolean(
      candidates.length ||
        decisions.length ||
        rejected.length ||
        handoffs.length ||
        assumptions.length ||
        openQuestions.length
    )
  }
}
