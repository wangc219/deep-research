const objectValue = (value) =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {}

export const arrayValue = (value) => (Array.isArray(value) ? value : [])

const textValue = (value) => String(value ?? '').trim()

const unique = (values) => [...new Set(values.filter(Boolean))]

export const S_AGENT_ARCHITECTURE = [
  {
    step: 1,
    agent_id: 'winning_s1_opponent',
    name: '对手分析 Agent',
    task: '深度挖掘对手体系薄弱环节、关键依赖与替代假设。',
    skills: ['defense_decomposition', 'ooda_vulnerability_analysis'],
    harness: 'winning_step_v1',
    semantics: ['可与 S2 并行', '可跳步', '可回溯']
  },
  {
    step: 2,
    agent_id: 'winning_s2_operations',
    name: '作战运用审查 Agent',
    task: '审视我方现有战法、任务链、协同关系与失败模式。',
    skills: ['winning_path_analysis', 'doctrine_operational_review'],
    harness: 'winning_step_v1',
    semantics: ['可与 S1 并行', '可跳步', '可回溯']
  },
  {
    step: 3,
    agent_id: 'winning_s3_breakthrough',
    name: '突破口思考 Agent',
    task: '生成潜在突破方向，以反事实与效果链验证机会线索。',
    skills: ['effect_chain_analysis', 'counterfactual_triz_innovation'],
    harness: 'winning_step_v1',
    semantics: ['多输入汇聚', '可并行推演', '可回溯']
  },
  {
    step: 4,
    agent_id: 'winning_s4_capability',
    name: '装备能力映射 Agent',
    task: '把战法与任务效果映射为装备能力、功能、性能和体系接口。',
    skills: ['capability_mapping', 'dotmlpf_capability_mapping'],
    harness: 'winning_step_v1',
    semantics: ['可与 S5 迭代', '可并行展开', '可回溯']
  },
  {
    step: 5,
    agent_id: 'winning_s5_gap',
    name: '创新颠覆候选组合评审 Agent',
    task: '在同一制胜维度内择优，再跨维度覆盖互异关系；最多保留 7 个。',
    skills: ['gap_quantification', 'equipment_system_gap_assessment'],
    harness: 'winning_step_v1',
    semantics: ['同维度择优', '跨维度覆盖', '名称冻结']
  },
  {
    step: 6,
    agent_id: 'winning_s6_image',
    name: '能力图像综合 Agent',
    task: '融合差距与前序认识，排序形成装备能力需求图像。',
    skills: ['capability_image_generation', 'capability_portfolio_synthesis'],
    harness: 'winning_step_v1',
    semantics: ['收敛输出', '保留冲突', '可回溯']
  }
]

export const LOOP_ARCHITECTURE = [
  {
    key: 'inner',
    level: 'L1',
    name: '步骤门控',
    event: 'winning_inner_loop_evaluated',
    description: '优先执行确定性检查；仅在证据、必填结构或作用机理存在实质缺口时局部修复。'
  },
  {
    key: 'middle',
    level: 'L2',
    name: '因果复核',
    event: 'winning_middle_loop_evaluated',
    description: '仅在跨步骤断链或高风险矛盾时触发复核，并只重跑受影响的 S Agent。'
  },
  {
    key: 'outer',
    level: 'L3',
    name: '残差回溯',
    event: 'winning_outer_loop_evaluated',
    description: '只对会改变能力结论的证据残差定向补强，不因一般覆盖标签不足重跑全链。'
  },
  {
    key: 'meta',
    level: 'L4',
    name: '元循环',
    event: 'discovery_meta_loop_evaluated',
    description: '调整 A–H 蓝图、S Agent 强度与动态专用 Agent，保持有界重规划。'
  }
]

export const BUSINESS_AGENTS = {
  orchestrator: { display_name: '主控 Agent', harness_profile: 'orchestrator_v1' },
  operational_employment: { display_name: '作战运用 Agent', harness_profile: 'operational_synthesis_v1' },
  combat_scenario: { display_name: '作战场景 Agent', harness_profile: 'scenario_research_v1' },
  international_situation: { display_name: '国际态势 Agent', harness_profile: 'strategic_context_v1' },
  opponent_monitoring: { display_name: '对手监测 Agent', harness_profile: 'opponent_monitoring_v1' },
  system_confrontation: { display_name: '体系对抗 Agent', harness_profile: 'system_confrontation_v1' },
  weapon_equipment: { display_name: '武器装备 Agent', harness_profile: 'equipment_research_v1' },
  case_research: { display_name: '战例研究 Agent', harness_profile: 'case_research_v1' },
  technology_radar: { display_name: '技术雷达 Agent', harness_profile: 'technology_radar_v1' },
  cross_domain_fusion: { display_name: '跨域融合 Agent', harness_profile: 'cross_domain_fusion_v1' },
  nontraditional_security: { display_name: '非传统安全 Agent', harness_profile: 'nontraditional_security_v1' },
  winning_mechanism: { display_name: '制胜机理 Agent', harness_profile: 'winning_core_v1' },
  winning_swarm_controller: { display_name: '动态蜂群主控 Agent', harness_profile: 'winning_swarm_dynamic_v2' },
  auditor: { display_name: '业务审计 Agent', harness_profile: 'audit_v1' },
  reporter: { display_name: '研究报告 Agent', harness_profile: 'reporter_v1' }
}

const eventCandidate = (row) => {
  let candidate = objectValue(row?.payload)
  if (!Object.keys(candidate).length) candidate = objectValue(row)
  for (let depth = 0; depth < 4; depth += 1) {
    const nestedEvent = objectValue(candidate.event)
    if (Object.keys(nestedEvent).length) {
      candidate = nestedEvent
      continue
    }
    const nestedPayload = objectValue(candidate.payload)
    const wrapper =
      candidate.type === 'TraceEvent' ||
      (!candidate.event_type && (nestedPayload.event_type || nestedPayload.actor || nestedPayload.summary))
    if (wrapper && Object.keys(nestedPayload).length) {
      candidate = nestedPayload
      continue
    }
    break
  }
  return candidate
}

export const normalizeRunEvent = (row, index = 0) => {
  const candidate = eventCandidate(row)
  const candidatePayload = objectValue(candidate.payload)
  const explicitDetails = objectValue(candidate.details)
  const details = Object.keys(explicitDetails).length ? explicitDetails : candidatePayload
  const eventType = textValue(candidate.event_type || row?.event_type || details.event_type || 'trace_event')
  const sequence = Number(row?.sequence ?? candidate.sequence ?? index + 1) || index + 1
  const actor = textValue(
    candidate.actor || details.actor || details.agent_id || details.agent_instance_id || row?.payload?.actor
  )
  const summary = textValue(
    candidate.summary ||
      details.summary ||
      details.message ||
      details.detail ||
      details.status ||
      eventType
  )
  return {
    event_id: textValue(candidate.event_id || row?.event_id || `${row?.run_id || 'run'}-${sequence}`),
    event_type: eventType,
    actor,
    sequence,
    created_at: candidate.created_at || row?.created_at || '',
    summary,
    details,
    input_refs: arrayValue(candidate.input_refs),
    output_refs: arrayValue(candidate.output_refs),
    raw: row
  }
}

export const normalizeRunEvents = (rows) => {
  const mapped = arrayValue(rows).map(normalizeRunEvent)
  const deduped = new Map()
  mapped.forEach((event) => {
    const key = event.event_id || `${event.sequence}:${event.event_type}:${event.actor}`
    deduped.set(key, event)
  })
  return [...deduped.values()].sort((left, right) => left.sequence - right.sequence)
}

const statusForDynamicEvent = (type, current = 'planned') => {
  if (/failed/.test(type)) return 'failed'
  if (/cancelled/.test(type)) return 'cancelled'
  if (/pruned|rejected/.test(type)) return 'pruned'
  if (/contribution_merged|hypothesis_merged/.test(type)) return 'merged'
  if (/session_completed|specialist_completed|agent_instance_completed/.test(type)) return 'completed'
  if (/session_started|instance_ready|waiting|spawned/.test(type)) return 'running'
  if (/recruited|recruitment_planned/.test(type)) return 'recruiting'
  return current
}

const dynamicMemberId = (value) =>
  textValue(value.agent_instance_id || value.instance_id || value.task_id || value.agent_id || value.id)

const projectDynamicMembers = (events) => {
  const members = new Map()
  const graphEvents = events.filter((event) => event.event_type === 'winning_mission_graph_planned')
  graphEvents.forEach((event) => {
    const graph = objectValue(event.details.graph || event.details.mission_graph)
    arrayValue(graph.agent_instances || graph.tasks || event.details.agent_instances).forEach((row) => {
      const source = objectValue(row)
      const id = dynamicMemberId(source)
      if (id) members.set(id, { ...source, agent_instance_id: id })
    })
  })
  events
    .filter((event) => /^(winning_agent_|specialist_|winning_contribution_)/.test(event.event_type))
    .forEach((event) => {
      const details = event.details
      const id = dynamicMemberId(details) || event.actor
      if (!id || !/^winning-agent-|specialist|dynamic/i.test(id)) return
      const previous = members.get(id) || { agent_instance_id: id }
      members.set(id, {
        ...previous,
        ...details,
        agent_instance_id: id,
        display_name: details.display_name || previous.display_name || '动态专用 Agent',
        mission_node: details.mission_node || details.merge_target || previous.mission_node || previous.merge_target,
        merge_target: details.merge_target || details.mission_node || previous.merge_target || previous.mission_node,
        status: statusForDynamicEvent(event.event_type, details.status || previous.status)
      })
    })
  return [...members.values()]
}

const candidateFromDetails = (details) => {
  const nested = [details.candidate, details.hypothesis, details.portfolio_item]
    .map(objectValue)
    .find((row) => Object.keys(row).length)
  const source = nested || details
  const hasIdentity =
    source.hypothesis_id ||
    source.card_binding_id ||
    source.title ||
    source.name ||
    source.equipment_form ||
    source.primary_equipment_identity
  return hasIdentity ? source : null
}

const projectCandidates = (events) => {
  const candidates = new Map()
  events
    .filter((event) => /hypothesis|candidate|portfolio|s6_card/.test(event.event_type))
    .forEach((event) => {
      const rows = [
        candidateFromDetails(event.details),
        ...arrayValue(event.details.candidates),
        ...arrayValue(event.details.hypotheses),
        ...arrayValue(event.details.final_equipment_portfolio),
        ...arrayValue(event.details.portfolio)
      ].filter(Boolean)
      rows.forEach((row, index) => {
        const source = objectValue(row)
        const key = textValue(
          source.hypothesis_id ||
            source.card_binding_id ||
            source.capability_id ||
            source.title ||
            source.name ||
            `${event.event_id}-${index}`
        )
        const previous = candidates.get(key) || {}
        candidates.set(key, {
          ...previous,
          ...source,
          hypothesis_id: source.hypothesis_id || previous.hypothesis_id || key,
          status: source.status || previous.status || (/rejected/.test(event.event_type) ? 'rejected' : undefined),
          selection_status:
            source.selection_status ||
            previous.selection_status ||
            (/selected|portfolio.*completed|s6_card.*completed/.test(event.event_type) ? 'selected' : undefined)
        })
      })
    })
  return [...candidates.values()]
}

const projectStepPlan = (events, dynamicMembers) =>
  S_AGENT_ARCHITECTURE.map((meta) => {
    const nodeEvents = events.filter((event) => {
      const step = Number(event.details.step || String(event.details.mission_node || event.details.merge_target).replace('S', ''))
      return step === meta.step
    })
    const members = dynamicMembers.filter(
      (member) => Number(String(member.mission_node || member.merge_target).replace('S', '')) === meta.step
    )
    const completed = nodeEvents.some((event) =>
      /completed|merged|reasoning_step_completed/.test(event.event_type)
    )
    const failed = nodeEvents.some((event) => /failed/.test(event.event_type))
    const running = nodeEvents.some((event) => /started|running|ready|waiting/.test(event.event_type))
    const skipped = nodeEvents.some((event) => /skipped/.test(event.event_type))
    const latest = nodeEvents.at(-1)
    return {
      ...meta,
      status: failed ? 'failed' : completed ? 'completed' : skipped ? 'skipped' : running ? 'running' : 'pending',
      execution_mode: members.length ? 'dynamic' : 'standard',
      dynamic_agents: members,
      result_summary: latest?.summary || '',
      current_step: latest?.details?.current_step || '',
      backtrack_count: nodeEvents.filter((event) => /recall|backtrack/.test(event.event_type)).length
    }
  })

const projectLoops = (events) =>
  Object.fromEntries(
    LOOP_ARCHITECTURE.map((loop) => {
      const rows = events.filter((event) => event.event_type === loop.event)
      return [
        loop.key,
        {
          count: rows.length,
          latest: rows.at(-1)?.summary || '',
          details: rows.at(-1)?.details || {}
        }
      ]
    })
  )

const deriveAgents = (events, dynamicMembers) => {
  const ids = unique(
    events.flatMap((event) => [event.actor, event.details.agent_id, event.details.target_agent_id])
  )
  const agents = ids
    .filter((id) => id && !dynamicMembers.some((member) => dynamicMemberId(member) === id))
    .map((agentId) => ({
      agent_id: agentId,
      display_name: BUSINESS_AGENTS[agentId]?.display_name || agentId,
      harness_profile: BUSINESS_AGENTS[agentId]?.harness_profile || '受控运行',
      skill_ids: []
    }))
  return agents
}

const projectDiscovery = (events, run) => {
  const started = events.find((event) => event.event_type === 'run_started')?.details || {}
  const meta = [...events].reverse().find((event) => event.event_type === 'discovery_meta_loop_evaluated')
    ?.details
  const selection = objectValue(started.agent_selection)
  return {
    primary_branch: meta?.primary_branch || run?.discovery_branch || run?.payload?.discovery_branch || '',
    secondary_branches: arrayValue(meta?.secondary_branches),
    branch_name: meta?.branch_name || '',
    baseline_agent_plan: arrayValue(selection.baseline_agent_plan)
  }
}

export const buildInteractionProjection = (rows, run = {}) => {
  const events = normalizeRunEvents(rows)
  const dynamicMembers = projectDynamicMembers(events)
  const candidates = projectCandidates(events)
  const stepPlan = projectStepPlan(events, dynamicMembers)
  const missionGraphEvent = [...events]
    .reverse()
    .find((event) => event.event_type === 'winning_mission_graph_planned')
  const missionGraph = objectValue(missionGraphEvent?.details?.graph || missionGraphEvent?.details?.mission_graph)
  const portfolioRows = candidates.filter(
    (candidate) =>
      candidate.s6_eligible === true ||
      candidate.selection_status === 'selected' ||
      candidate.portfolio_status === 'selected'
  )
  const agents = deriveAgents(events, dynamicMembers)
  const activeAgentIds = unique([
    ...agents.map((agent) => agent.agent_id),
    ...dynamicMembers.map(dynamicMemberId)
  ])
  const failedEvent = [...events].reverse().find((event) => /run_failed|audit_delivery_blocked/.test(event.event_type))
  const savepoints = events.filter((event) => event.event_type === 'savepoint').length
  return {
    run_id: run?.run_id || '',
    agents,
    events,
    counts: {
      events: events.length,
      visible_events: events.length,
      active_agents: activeAgentIds.length,
      tool_calls: events.filter((event) => event.event_type === 'tool_call').length,
      tool_results: events.filter((event) => event.event_type === 'tool_result').length,
      savepoints
    },
    workflow: {
      status: run?.status || '',
      failure: failedEvent
        ? { phase: failedEvent.details.phase, detail: failedEvent.summary || run?.error }
        : run?.error
          ? { detail: run.error }
          : {},
      active_agent_ids: activeAgentIds,
      discovery: projectDiscovery(events, run),
      execution: {
        profile_id: run?.execution_profile_id || run?.payload?.execution_profile_id || '',
        provider: run?.execution?.provider || run?.payload?.execution?.provider || ''
      },
      step_plan: stepPlan,
      loops: projectLoops(events),
      dynamic_agents: dynamicMembers,
      swarm_cluster: {
        enabled: dynamicMembers.length > 0 || Object.keys(missionGraph).length > 0,
        members: dynamicMembers,
        mission_graph: missionGraph,
        candidate_lineage: candidates,
        final_equipment_portfolio: portfolioRows,
        counts: {
          total: dynamicMembers.length,
          running: dynamicMembers.filter((member) => member.status === 'running').length,
          completed: dynamicMembers.filter((member) => ['completed', 'merged'].includes(member.status)).length,
          merged: dynamicMembers.filter((member) => member.status === 'merged').length,
          pruned: dynamicMembers.filter((member) => ['pruned', 'failed', 'cancelled'].includes(member.status))
            .length
        }
      }
    }
  }
}

const rowsFromPayload = (payload, keys = []) => {
  if (Array.isArray(payload)) return payload
  const source = objectValue(payload)
  for (const key of keys) {
    if (Array.isArray(source[key])) return source[key]
  }
  return []
}

export const buildEvidenceProjection = (payload, events = []) => {
  const direct = rowsFromPayload(payload, ['items', 'evidence', 'rows', 'results'])
  const cards = new Map()
  const add = (value, fallback = {}) => {
    const source = objectValue(value)
    const evidenceId = textValue(
      source.evidence_id || source.id || source.card_id || fallback.evidence_id
    )
    if (!evidenceId) return
    const previous = cards.get(evidenceId) || {}
    // A trace reference is only a fallback; it must not replace an authoritative
    // EvidenceCard claim or provenance already returned by the artifact API.
    cards.set(evidenceId, { ...fallback, ...previous, ...source, evidence_id: evidenceId })
  }
  direct.forEach((row) => add(row))
  events.forEach((event) => {
    const details = objectValue(event.details)
    ;[
      details.evidence_card,
      details.evidence,
      details.card,
      ...arrayValue(details.evidence_cards),
      ...arrayValue(details.evidence_items)
    ].forEach((row) => add(row, { created_at: event.created_at, created_by: event.actor }))
    const refs = unique([
      ...arrayValue(details.evidence_ids),
      ...event.output_refs.filter((value) => /^ev[-_:]/i.test(String(value)))
    ])
    refs.forEach((evidenceId) =>
      add(
        { evidence_id: evidenceId },
        {
          claim: event.summary,
          created_at: event.created_at,
          created_by: event.actor,
          quality_assessment: '运行事件引用'
        }
      )
    )
  })
  return [...cards.values()]
}

const stageFromEvent = (event) => {
  const details = event.details
  const summary = event.summary
  const match = summary.match(/(L[1-4]).*gate\s*=\s*(true|false)/i)
  const layer = textValue(details.layer || details.stage_id || match?.[1] || 'L1').toUpperCase()
  return {
    ...details,
    stage_id: details.stage_id || `${layer}-${event.sequence}`,
    layer,
    title: details.title || `${layer} ${LOOP_ARCHITECTURE.find((item) => item.level === layer)?.name || '循环门控'}`,
    gate_passed:
      typeof details.gate_passed === 'boolean'
        ? details.gate_passed
        : match
          ? match[2].toLowerCase() === 'true'
          : !/failed|limited|false/i.test(summary),
    summary
  }
}

export const buildWinningProjection = (payload, events = [], run = {}, interactions = {}) => {
  const source = objectValue(payload)
  const hasWinningEvents = events.some((event) =>
    /^(winning_|discovery_convergence_completed|capability_image_created)/.test(event.event_type)
  )
  const reasoningFallback = events
    .filter((event) => event.event_type === 'winning_reasoning_step_completed')
    .map((event) => ({
      ...event.details,
      reasoning_node_id: event.details.reasoning_node_id || event.event_id,
      summary: event.details.summary || event.summary
    }))
  const stageFallback = events
    .filter((event) =>
      ['winning_stage_completed', 'winning_inner_loop_evaluated', 'winning_middle_loop_evaluated', 'winning_outer_loop_evaluated'].includes(
        event.event_type
      )
    )
    .map(stageFromEvent)
  const recallFallback = events
    .filter((event) => /recall_requested|recall_task_completed/.test(event.event_type))
    .map((event) => ({ ...event.details, recall_id: event.details.recall_id || event.event_id, reason: event.details.reason || event.summary }))
  const inputFallback = {
    problem_frame: {
      objective: run?.topic || '研究目标待载入',
      route_frame: run?.supplemental_information || '围绕研究目标形成可追溯的装备能力需求图像。'
    },
    research_route: run?.research_route || 'auto',
    packet_ids: unique(
      events.flatMap((event) =>
        event.event_type === 'baseline_agent_completed' ? event.output_refs : []
      )
    ),
    evidence_index: buildEvidenceProjection([], events).map((item) => item.evidence_id),
    round_budget: { current_round: 1, maximum_rounds: run?.max_rounds || 2 }
  }
  const legacyInputs = rowsFromPayload(source.inputs, ['items'])
  const legacyResources = rowsFromPayload(source.resources, ['items'])
  const reasoningNodes = rowsFromPayload(source.reasoning_nodes, ['items'])
  const stages = rowsFromPayload(source.stages, ['items'])
  const recalls = rowsFromPayload(source.recalls, ['items'])
  return {
    ...source,
    inputs: legacyInputs.length ? legacyInputs : hasWinningEvents ? [inputFallback] : [],
    resources: legacyResources,
    reasoning_nodes: reasoningNodes.length ? reasoningNodes : reasoningFallback,
    stages: stages.length ? stages : stageFallback,
    recalls: recalls.length ? recalls : recallFallback,
    workflow: Object.keys(objectValue(source.workflow)).length
      ? source.workflow
      : objectValue(interactions.workflow),
    swarm: Object.keys(objectValue(source.swarm)).length
      ? source.swarm
      : objectValue(interactions.workflow?.swarm_cluster)
  }
}

export const resolveWinningSwarm = (winning = {}, interactions = {}) => {
  const interactionSwarm = objectValue(interactions?.workflow?.swarm_cluster)
  const artifactSwarm = objectValue(winning?.swarm)
  if (!Object.keys(artifactSwarm).length) return interactionSwarm
  return {
    ...interactionSwarm,
    ...artifactSwarm,
    members: arrayValue(artifactSwarm.members).length
      ? artifactSwarm.members
      : arrayValue(interactionSwarm.members),
    candidate_lineage: arrayValue(artifactSwarm.candidate_lineage).length
      ? artifactSwarm.candidate_lineage
      : arrayValue(interactionSwarm.candidate_lineage),
    final_equipment_portfolio: arrayValue(artifactSwarm.final_equipment_portfolio).length
      ? artifactSwarm.final_equipment_portfolio
      : arrayValue(interactionSwarm.final_equipment_portfolio)
  }
}

export const mergeInteractionProjection = (legacyPayload, fallback) => {
  const legacy = objectValue(legacyPayload)
  if (!arrayValue(legacy.events).length) return fallback
  const platformEvents = arrayValue(fallback.events)
  const legacyEvents = arrayValue(legacy.events).map(normalizeRunEvent)
  const eventsById = new Map()
  platformEvents.forEach((event) => eventsById.set(event.event_id, event))
  // Legacy trace rows carry richer details for the same event. Keep those when
  // IDs match, while retaining newer PostgreSQL events absent from the trace.
  legacyEvents.forEach((event) => eventsById.set(event.event_id, event))
  const events = [...eventsById.values()].sort((left, right) =>
    left.sequence - right.sequence || String(left.created_at).localeCompare(String(right.created_at))
  )
  return {
    ...fallback,
    ...legacy,
    agents: arrayValue(legacy.agents).length ? legacy.agents : fallback.agents,
    events,
    counts: {
      ...fallback.counts,
      ...objectValue(legacy.counts),
      events: Math.max(events.length, Number(legacy.counts?.events) || 0),
      visible_events: events.length
    },
    workflow: { ...fallback.workflow, ...objectValue(legacy.workflow) }
  }
}

export const candidateTitle = (candidate) =>
  textValue(
    candidate?.name ||
      candidate?.title ||
      candidate?.primary_equipment_identity ||
      candidate?.equipment_form ||
      candidate?.hypothesis_id
  ) || '未命名候选'

export const candidateSummary = (candidate) =>
  textValue(
    candidate?.concise_winning_summary ||
      candidate?.winning_summary ||
      candidate?.winning_mechanism ||
      candidate?.novelty_delta ||
      candidate?.changed_confrontation_variable ||
      candidate?.summary
  ) || '候选制胜机理正在收敛。'

export const displayValue = (value) => {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.map(displayValue).join('；')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}
