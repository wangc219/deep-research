const text = value => String(value ?? '').trim();

export const DEEP_STAGES = [
  ['context', '研究边界'],
  ['s3_divergence', '开放探索'],
  ['council_critique', '交叉复核'],
  ['s4_mapping', '方向深化'],
  ['s6_authoring', '形成画像'],
];

const DEEP_STAGE_ALIASES = {
  queued: 'context',
  context_snapshot: 'context',
  divergence: 's3_divergence',
  s3: 's3_divergence',
  mapping: 's4_mapping',
  critique: 'council_critique',
  council_critique: 'council_critique',
  s5_adjudication: 'council_critique',
  s4: 's4_mapping',
  s4_mapping: 's4_mapping',
  retrieval: 's3_divergence',
  authoring: 's6_authoring',
  s6: 's6_authoring',
  inspect_memory: 'context',
  memory: 'context',
  help: 'context',
  command: 'context',
  conduct: 'context',
  deepen: 's4_mapping',
  validation: 's4_mapping',
  publish: 's4_mapping',
};

const TERMINAL_STATUSES = new Set([
  'partial',
  'failed',
  'blocked',
  'cancelled',
  'rejected',
]);

export const normalizeDeepStage = stage => {
  const value = text(stage).toLowerCase();
  return DEEP_STAGE_ALIASES[value] || value;
};

export const isTerminalJob = job => {
  const status = text(typeof job === 'string' ? job : job?.status).toLowerCase();
  if (TERMINAL_STATUSES.has(status)) return true;
  return status === 'completed' && (
    !job
    || !text(job?.stage)
    || text(job?.stage).toLowerCase() === 'publish'
  );
};

export const furthestDeepStage = (...stages) => {
  const order = [...DEEP_STAGES.map(([key]) => key), 'publish'];
  return stages
    .map(stage => (
      text(stage).toLowerCase() === 'publish'
        ? 'publish'
        : normalizeDeepStage(stage)
    ))
    .filter(stage => order.includes(stage))
    .reduce((furthest, stage) => (
      order.indexOf(stage) > order.indexOf(furthest) ? stage : furthest
    ), '');
};

const jobId = job => text(job?.job_id || job?.id);
const stateVersion = job => {
  const value = Number(job?.state_version);
  return Number.isFinite(value) && value >= 0 ? value : 0;
};
const progressValue = job => {
  const value = Number(job?.progress);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
};
const normalizedStatus = job => {
  const status = text(job?.status).toLowerCase();
  const stage = text(job?.stage).toLowerCase();
  return status === 'completed' && stage && stage !== 'publish'
    ? 'running'
    : status;
};

/** Merge SSE, polling and command receipts without regressing visible state. */
export const mergeDeepJobState = (current, incoming) => {
  if (!incoming || typeof incoming !== 'object') return current || null;
  if (!current || typeof current !== 'object' || jobId(current) !== jobId(incoming)) {
    return {
      ...incoming,
      status: normalizedStatus(incoming) || incoming.status,
      progress: progressValue(incoming),
    };
  }

  const currentVersion = stateVersion(current);
  const incomingVersion = stateVersion(incoming);
  if (incomingVersion < currentVersion) return current;

  const incomingState = {
    ...incoming,
    status: normalizedStatus(incoming) || current.status,
  };
  const retryReset = (
    incomingVersion > currentVersion
    && isTerminalJob(current)
    && text(incoming.stage).toLowerCase() === 'queued'
    && ['queued', 'running'].includes(text(incomingState.status).toLowerCase())
  );
  if (retryReset) {
    return {
      ...current,
      ...incomingState,
      stage: text(incoming.stage) || 'queued',
      progress: progressValue(incoming),
      state_version: incomingVersion,
      error: text(incoming.error),
    };
  }

  if (isTerminalJob(current) && !isTerminalJob(incomingState)) {
    return {
      ...current,
      state_version: Math.max(currentVersion, incomingVersion),
    };
  }

  const currentStatus = normalizedStatus(current);
  const incomingStatus = normalizedStatus(incomingState);
  const nonTerminalRank = {queued: 0, running: 1, completed: 1};
  const status = isTerminalJob(incomingState)
    ? incomingStatus
    : (nonTerminalRank[incomingStatus] ?? 0) >= (nonTerminalRank[currentStatus] ?? 0)
      ? incomingStatus
      : currentStatus;
  return {
    ...current,
    ...incomingState,
    stage: furthestDeepStage(current.stage, incoming.stage)
      || text(incoming.stage)
      || current.stage,
    status,
    progress: Math.max(progressValue(current), progressValue(incoming)),
    state_version: Math.max(currentVersion, incomingVersion),
    error: text(incoming.error) || current.error || '',
  };
};

const AGENT_EVENT_TYPES = new Set([
  'deep_agent_started',
  'deep_agent_progress',
  'deep_agent_handoff',
  'deep_agent_completed',
  'deep_agent_failed',
]);

const AGENT_LABELS = {
  deep_dialogue_orchestrator: '任务编排 Agent',
  deep_dialogue_council: '开放探索 Agent',
  deep_dialogue_doctrine_breaker: '新质颠覆架构 Agent',
  deep_dialogue_terminal_effect_architect: '直接毁伤机理 Agent',
  deep_dialogue_adversary_red_team: '反适应制衡 Agent',
  deep_dialogue_adversarial_judge: '观点复核 Agent',
  deep_thinking_dialogue: '候选方向综合总编',
  deep_dialogue_memory: '决策记忆',
  deep_dialogue_runtime: '命令路由',
};

const eventDelta = event => (
  event?.delta && typeof event.delta === 'object' ? event.delta : {}
);
const eventValue = (event, key) => eventDelta(event)[key] ?? event?.[key];
const eventText = event => text(eventValue(event, 'text') || eventValue(event, 'summary_text'));
const boundedStrings = value => (
  Array.isArray(value)
    ? value.map(text).filter(Boolean).slice(0, 8)
    : []
);

/** Project replayable public events into a compact Agent activity model. */
export const projectDeepAgentActivity = (events = []) => {
  const rows = Array.isArray(events) ? events : [];
  const ordered = rows
    .map((event, index) => ({event, index}))
    .sort((left, right) => {
      const leftSequence = Number(left.event?.sequence);
      const rightSequence = Number(right.event?.sequence);
      if (!Number.isFinite(leftSequence) || !Number.isFinite(rightSequence)) {
        return left.index - right.index;
      }
      return (leftSequence - rightSequence) || (left.index - right.index);
    });
  const agents = new Map();
  const handoffs = [];
  const interventions = [];
  const handoffKeys = new Set();

  const upsertAgent = (agentId, event, patch = {}) => {
    const id = text(agentId);
    if (!id) return;
    const current = agents.get(id) || {
      agent_id: id,
      label: AGENT_LABELS[id] || text(eventValue(event, 'role')) || id,
      role: text(eventValue(event, 'role')),
      axis: text(eventValue(event, 'axis')),
      status: 'waiting',
      summary: '',
      deliverable_refs: [],
      first_sequence: Number(event?.sequence) || 0,
      last_sequence: 0,
    };
    const incomingDeliverables = boundedStrings(eventValue(event, 'deliverable_refs'));
    const proposalNames = boundedStrings(eventValue(event, 'proposal_names'));
    const deliverables = [...current.deliverable_refs];
    [...incomingDeliverables, ...proposalNames].forEach(item => {
      if (!deliverables.includes(item) && deliverables.length < 8) deliverables.push(item);
    });
    agents.set(id, {
      ...current,
      label: text(patch.label) || text(eventValue(event, 'role')) || current.label,
      role: text(eventValue(event, 'role')) || current.role,
      axis: text(eventValue(event, 'axis')) || current.axis,
      summary: eventText(event) || current.summary,
      deliverable_refs: deliverables,
      last_sequence: Math.max(current.last_sequence, Number(event?.sequence) || 0),
      ...patch,
    });
  };

  ordered.forEach(({event, index}) => {
    if (!event || typeof event !== 'object') return;
    const type = text(event.event_type);
    const agentId = text(eventValue(event, 'agent_id'));
    const status = text(event.status).toLowerCase();
    const kind = text(eventValue(event, 'kind')).toLowerCase();
    if (AGENT_EVENT_TYPES.has(type) && agentId) {
      const projectedStatus = type === 'deep_agent_failed'
        ? 'failed'
        : type === 'deep_agent_completed'
          ? 'done'
          : 'running';
      upsertAgent(agentId, event, {status: projectedStatus});
    } else if (agentId && (eventValue(event, 'role') || eventValue(event, 'axis'))) {
      upsertAgent(agentId, event, {
        status: status === 'failed' || status === 'blocked'
          ? 'failed'
          : status === 'completed' || kind === 'answer'
            ? 'done'
            : 'running',
      });
    }

    if (type === 'deep_agent_handoff') {
      const fromAgentId = text(eventValue(event, 'from_agent_id'));
      const toAgentId = text(eventValue(event, 'to_agent_id'));
      if (!fromAgentId || !toAgentId) return;
      const key = text(event.event_id)
        || `${Number(event.sequence) || index}:${fromAgentId}:${toAgentId}:${text(eventValue(event, 'handoff_kind'))}`;
      if (handoffKeys.has(key)) return;
      handoffKeys.add(key);
      const deliverableRefs = boundedStrings(eventValue(event, 'deliverable_refs'));
      handoffs.push({
        key,
        from_agent_id: fromAgentId,
        from_label: AGENT_LABELS[fromAgentId] || fromAgentId,
        to_agent_id: toAgentId,
        to_label: AGENT_LABELS[toAgentId] || toAgentId,
        handoff_kind: text(eventValue(event, 'handoff_kind')),
        summary: eventText(event),
        deliverable_refs: deliverableRefs,
        sequence: Number(event.sequence) || 0,
      });
      if (agents.has(fromAgentId)) {
        agents.set(fromAgentId, {...agents.get(fromAgentId), status: 'done'});
      } else {
        upsertAgent(fromAgentId, event, {
          label: AGENT_LABELS[fromAgentId] || fromAgentId,
          status: 'done',
        });
      }
      upsertAgent(toAgentId, event, {status: 'running'});
    }

    if (type === 'deep_steer_applied') {
      interventions.push({
        key: text(event.event_id) || text(event.steer_id) || `steer-${index}`,
        agent_id: agentId,
        agent_label: text(eventValue(event, 'role')) || AGENT_LABELS[agentId] || '当前 Agent',
        stage: text(event.stage),
        summary: eventText(event) || '你的补充已纳入当前研究。',
        sequence: Number(event.sequence) || 0,
      });
    }
  });

  const projectedAgents = [...agents.values()].sort((left, right) => (
    (left.first_sequence - right.first_sequence)
    || left.label.localeCompare(right.label, 'zh-CN')
  ));
  return {
    agents: projectedAgents,
    handoffs,
    interventions,
    active_count: projectedAgents.filter(agent => agent.status === 'running').length,
    completed_count: projectedAgents.filter(agent => agent.status === 'done').length,
    failed_count: projectedAgents.filter(agent => agent.status === 'failed').length,
  };
};

/** Render only agents that actually appeared in the event stream. */
export const projectDeepActivityRoster = (events = [], {sending = false} = {}) => {
  const activity = projectDeepAgentActivity(events);
  if (activity.agents.length) {
    return activity.agents.map((agent, index) => ({
      ...agent,
      key: agent.agent_id,
      badge: String(index + 1).padStart(2, '0'),
      hint: agent.axis || (agent.status === 'done' ? '已提交可见结果' : '正在深化当前问题'),
    }));
  }
  if (!sending) return [];
  return [{
    agent_id: 'deep_dynamic_runtime',
    key: 'deep_dynamic_runtime',
    badge: '01',
    label: '研究编排',
    role: '研究编排',
    axis: '',
    status: 'running',
    summary: '',
    deliverable_refs: [],
    hint: '正在选择本轮最有价值的探索角度',
  }];
};

const DEFAULT_CONTEXT_BUDGET = 12000;
const LIVING_TURN_LIMIT = 2;

export const branchWorkingMemory = (memory, branchId = 'main') => {
  if (!memory || typeof memory !== 'object') return {};
  const branches = memory.branches;
  const wanted = text(branchId) || 'main';
  if (branches && typeof branches === 'object' && !Array.isArray(branches)) {
    const selected = branches[wanted] || {};
    return selected && typeof selected === 'object' ? selected : {};
  }
  const storedBranch = text(memory.branch_id) || 'main';
  return storedBranch === wanted ? memory : {};
};

const normalizedActiveSkillIds = value => (
  Array.isArray(value)
    ? [...new Set(value.map(text).filter(Boolean))].slice(0, 6)
    : []
);

/** Resolve persisted Skill selection without borrowing from another branch. */
export const branchActiveSkillIds = (session, branchId = 'main', defaultSkillIds = []) => {
  const wanted = text(branchId) || 'main';
  if (!session || typeof session !== 'object') return normalizedActiveSkillIds(defaultSkillIds);
  const rootMemory = session.working_memory && typeof session.working_memory === 'object'
    ? session.working_memory
    : {};
  const memory = branchWorkingMemory(rootMemory, wanted);
  if (Object.prototype.hasOwnProperty.call(memory, 'active_skill_ids')) {
    return normalizedActiveSkillIds(memory.active_skill_ids);
  }

  // The public session alias represents only the server's active branch. It is
  // a valid compatibility fallback for that exact branch, never for a sibling.
  const hasBranchMap = rootMemory.branches
    && typeof rootMemory.branches === 'object'
    && !Array.isArray(rootMemory.branches);
  const storedBranch = hasBranchMap
    ? (text(rootMemory.active_branch_id) || 'main')
    : (text(rootMemory.branch_id) || 'main');
  if (storedBranch === wanted && Array.isArray(session.active_skill_ids)) {
    return normalizedActiveSkillIds(session.active_skill_ids);
  }
  return normalizedActiveSkillIds(defaultSkillIds);
};

/** Guard a turn payload against a selection still scoped to another branch/session. */
export const resolveBranchSkillSelection = ({
  session,
  branchId = 'main',
  selectedSkillIds = [],
  selectedSessionId = '',
  selectedBranchId = '',
  defaultSkillIds = [],
} = {}) => {
  const wanted = text(branchId) || 'main';
  const sessionId = text(session?.session_id);
  if (
    text(selectedSessionId) === sessionId
    && text(selectedBranchId) === wanted
  ) {
    return normalizedActiveSkillIds(selectedSkillIds);
  }
  return branchActiveSkillIds(session, wanted, defaultSkillIds);
};

const countUserTurns = (messages = []) => (
  (Array.isArray(messages) ? messages : []).filter(item => (
    text(item?.role).toLowerCase() === 'user' && text(item?.content)
  )).length
);

const boundedMemoryStrings = (value, limit = 8) => (
  Array.isArray(value)
    ? value.map(item => text(item)).filter(Boolean).slice(0, limit)
    : []
);

const INTERNAL_RETRIEVAL_HINTS = [
  '来源边界', '来源受限', '来源不可用', '来源或工程闭环提示',
  '来源通道失败', '国内外来源不可达', '国内来源不可达', '国际来源不可达',
  '无法访问来源', '无法访问某网站', '没有可引用来源', '证据不足',
  '检索不通', '检索通道异常', '检索无结果', '检索不可用',
  '联网检索不可用', '搜索失败', '检索失败', '本轮检索',
  '未发现可靠可迁移的新技术', '未形成可靠可迁移的新技术结论',
  '未获得可核验的公开来源', '未检索到可靠的新技术',
  '未检索到可靠可迁移的新技术', '未找到可靠可迁移的新技术',
];

export const sanitizePublicResearchText = value => {
  const raw = text(value);
  if (!raw) return '';
  const chunks = raw.split(/(?<=[。！？；;.!?])\s*/);
  const kept = chunks.filter(chunk => (
    chunk.trim()
    && !INTERNAL_RETRIEVAL_HINTS.some(hint => chunk.includes(hint))
  ));
  return kept.join('').trim();
};

export const sanitizePublicResearchGap = value => {
  return sanitizePublicResearchText(value);
};

const memoryDecision = value => {
  if (!value || typeof value !== 'object') return null;
  const candidate = text(value.candidate || value.name || value.title);
  const reason = text(value.reason || value.decisive_issue || value.required_revision);
  const verdict = text(value.verdict || value.status).toLowerCase();
  if (!candidate && !reason) return null;
  return {candidate, verdict, reason};
};

const memoryFrontier = value => {
  if (!value || typeof value !== 'object') return null;
  const direction = text(value.direction || value.name || value.candidate_name);
  const status = text(value.status).toLowerCase();
  const whyPromising = text(value.why_promising || value.winning_angle || value.rationale);
  const assumption = text(value.assumption || value.changed_assumption);
  const nextProbe = text(value.next_probe || value.suggested_question);
  if (!direction && !whyPromising && !nextProbe) return null;
  return {direction, status, why_promising: whyPromising, assumption, next_probe: nextProbe};
};

const memoryAssumption = value => {
  if (!value || typeof value !== 'object') return null;
  const assumption = text(value.assumption || value.changed_assumption);
  const direction = text(value.direction || value.candidate_name || value.name);
  const status = text(value.status).toLowerCase();
  const rationale = text(value.rationale || value.why_promising);
  if (!assumption) return null;
  return {assumption, direction, status, rationale};
};

const memoryResearchGap = value => {
  if (typeof value === 'string') return sanitizePublicResearchGap(value);
  if (!value || typeof value !== 'object') return '';
  const candidate = text(value.candidate_name || value.direction || value.name);
  const question = text(value.suggested_question || value.next_probe || value.question || value.reason);
  const dimensions = boundedMemoryStrings(value.missing_dimensions || value.missing_fields, 8);
  const detail = question || (dimensions.length > 0 ? `待补：${dimensions.join('、')}` : '');
  return sanitizePublicResearchGap([candidate, detail].filter(Boolean).join('：'));
};

const memoryStrategy = value => {
  if (!value || typeof value !== 'object') return null;
  const mode = text(value.mode || value.strategy);
  const rationale = sanitizePublicResearchText(value.rationale);
  const actions = boundedMemoryStrings(value.actions || value.tools, 6);
  const lenses = boundedMemoryStrings(value.lenses, 8);
  if (!mode && !rationale && actions.length === 0 && lenses.length === 0) return null;
  return {mode, rationale, actions, lenses};
};

/** Public, branch-scoped decision memory. It never projects provider reasoning. */
export const projectDeepMemory = (session, branchId = 'main') => {
  const memory = branchWorkingMemory(session?.working_memory, branchId);
  const directions = Array.isArray(memory.candidate_directions)
    ? memory.candidate_directions
      .filter(item => item && typeof item === 'object' && text(item.name))
      .slice(0, 4)
      .map(item => ({
        name: text(item.name),
        winning_angle: text(item.winning_angle),
        equipment_form: text(item.equipment_form || item.innovation_equipment_form),
        stable: Boolean(item.stable),
      }))
    : [];
  const decisions = Array.isArray(memory.decisions)
    ? memory.decisions.map(memoryDecision).filter(Boolean).slice(0, 8)
    : [];
  const rejected = Array.isArray(memory.rejected_directions)
    ? memory.rejected_directions.map(memoryDecision).filter(Boolean).slice(0, 8)
    : [];
  const frontier = Array.isArray(memory.research_frontier)
    ? memory.research_frontier.map(memoryFrontier).filter(Boolean).slice(0, 8)
    : [];
  const assumptions = Array.isArray(memory.assumption_ledger)
    ? memory.assumption_ledger.map(memoryAssumption).filter(Boolean).slice(0, 12)
    : [];
  const exploredLenses = boundedMemoryStrings(memory.explored_lenses, 18);
  const researchGaps = Array.isArray(memory.research_gaps)
    ? memory.research_gaps.map(memoryResearchGap).filter(Boolean).slice(0, 10)
    : [];
  const lastStrategy = memoryStrategy(memory.last_research_strategy);
  const result = {
    schema_version: 'deep-memory-view-v1',
    branch_id: text(memory.branch_id) || text(branchId) || 'main',
    current_objective: text(memory.current_objective),
    summaries: (Array.isArray(memory.latest_summary) ? memory.latest_summary : [])
      .map(sanitizePublicResearchText).filter(Boolean).slice(0, 6),
    constraints: boundedMemoryStrings(memory.user_constraints, 12),
    decisions,
    rejected,
    directions,
    open_questions: (Array.isArray(memory.open_questions) ? memory.open_questions : [])
      .map(sanitizePublicResearchGap).filter(Boolean).slice(0, 8),
    research_iteration: Math.max(0, Number(memory.research_iteration) || 0),
    research_frontier: frontier,
    assumption_ledger: assumptions,
    explored_lenses: exploredLenses,
    research_gaps: researchGaps,
    last_research_strategy: lastStrategy,
    selection_rationale: sanitizePublicResearchText(memory.selection_rationale),
    finalization_status: text(memory.finalization_status),
  };
  result.has_memory = Boolean(
    result.current_objective
    || result.summaries.length
    || result.constraints.length
    || result.decisions.length
    || result.rejected.length
    || result.directions.length
    || result.open_questions.length
    || result.research_frontier.length
    || result.assumption_ledger.length
    || result.explored_lenses.length
    || result.research_gaps.length
    || result.last_research_strategy
  );
  return result;
};

/** Project nanobot-style context occupancy for the composer usage chip. */
export const projectDeepContextUsage = (session, branchId = 'main') => {
  const stored = session?.context_usage;
  const wantedBranch = text(branchId) || 'main';
  const storedBranch = text(stored?.branch_id);
  const storedMatchesBranch = storedBranch ? storedBranch === wantedBranch : wantedBranch === 'main';
  if (stored && typeof stored === 'object' && storedMatchesBranch && Number.isFinite(Number(stored.share))) {
    return {
      schema_version: 'deep-context-usage-v1',
      branch_id: storedBranch || wantedBranch,
      living_turns: Math.max(0, Number(stored.living_turns) || 0),
      archived_turns: Math.max(0, Number(stored.archived_turns) || 0),
      visible_messages: Math.max(0, Number(stored.visible_messages) || 0),
      estimated_chars: Math.max(0, Number(stored.estimated_chars) || 0),
      budget_chars: Math.max(1, Number(stored.budget_chars) || DEFAULT_CONTEXT_BUDGET),
      share: Math.max(0, Math.min(1, Number(stored.share) || 0)),
      compacted: Boolean(stored.compacted),
      current_objective: text(stored.current_objective),
      constraint_count: Math.max(0, Number(stored.constraint_count) || 0),
      decision_count: Math.max(0, Number(stored.decision_count) || 0),
      open_question_count: Math.max(0, Number(stored.open_question_count) || 0),
      frontier_count: Math.max(0, Number(stored.frontier_count) || 0),
      assumption_count: Math.max(0, Number(stored.assumption_count) || 0),
      explored_lens_count: Math.max(0, Number(stored.explored_lens_count) || 0),
      research_gap_count: Math.max(0, Number(stored.research_gap_count) || 0),
    };
  }
  const memory = branchWorkingMemory(session?.working_memory, branchId);
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const userTurns = countUserTurns(messages);
  const livingTurns = Math.min(LIVING_TURN_LIMIT, userTurns);
  const archivedTurns = Math.max(0, userTurns - livingTurns);
  const constraints = Array.isArray(memory.user_constraints) ? memory.user_constraints : [];
  const decisions = Array.isArray(memory.decisions) ? memory.decisions : [];
  const openQuestions = Array.isArray(memory.open_questions) ? memory.open_questions : [];
  const frontier = Array.isArray(memory.research_frontier) ? memory.research_frontier : [];
  const assumptions = Array.isArray(memory.assumption_ledger) ? memory.assumption_ledger : [];
  const lenses = Array.isArray(memory.explored_lenses) ? memory.explored_lenses : [];
  const researchGaps = Array.isArray(memory.research_gaps) ? memory.research_gaps : [];
  const estimated = JSON.stringify({
    living: livingTurns,
    memory: {
      current_objective: memory.current_objective || '',
      latest_summary: memory.latest_summary || [],
      constraints,
      decisions,
      frontier,
      assumptions,
      lenses,
      research_gaps: researchGaps,
    },
  }).length;
  const share = Math.min(1, estimated / DEFAULT_CONTEXT_BUDGET);
  return {
    schema_version: 'deep-context-usage-v1',
    branch_id: wantedBranch,
    living_turns: livingTurns,
    archived_turns: archivedTurns,
    visible_messages: messages.length,
    estimated_chars: estimated,
    budget_chars: DEFAULT_CONTEXT_BUDGET,
    share,
    compacted: Boolean(memory.latest_summary || memory.current_objective) && archivedTurns > 0,
    current_objective: text(memory.current_objective),
    constraint_count: constraints.length,
    decision_count: decisions.length,
    open_question_count: openQuestions.length,
    frontier_count: frontier.length,
    assumption_count: assumptions.length,
    explored_lens_count: lenses.length,
    research_gap_count: researchGaps.length,
  };
};

export const queuedSteerStatuses = new Set(['queued', 'accepted', 'pending', 'claimed']);

export const THREAD_NEAR_BOTTOM_PX = 72;
export const MAX_QUOTED_CONTEXT_CHARS = 4000;
export const QUOTE_MARKER = '> [引用]';

export const isThreadNearBottom = (node, threshold = THREAD_NEAR_BOTTOM_PX) => {
  if (!node) return true;
  return node.scrollHeight - node.scrollTop - node.clientHeight <= threshold;
};

export const shouldShowJumpToLatest = (node, threshold = THREAD_NEAR_BOTTOM_PX) => {
  if (!node) return false;
  if (node.scrollHeight <= node.clientHeight + 48) return false;
  return !isThreadNearBottom(node, threshold);
};

export const deepSessionIdentityIds = item => [
  item?.card_binding_id,
  item?.hypothesis_id,
  item?.capability_id,
].map(text).filter(Boolean);

/**
 * Rebuild the minimum target object from a URL identity.  The launcher keeps
 * the URL deliberately compact, so a hard refresh may only have the option
 * key (for example `capability-followup:card_binding_id:card-1`) and no
 * serialized card payload.  Keeping this parser here makes that navigation
 * state deterministic and lets the panel submit against the same identity
 * while the richer card context is unavailable.
 */
export const parseDeepTargetIdentity = value => {
  const raw = text(value);
  if (!raw) return null;
  const knownKinds = new Set(['capability-followup', 'reference-research', 'deep-thinking']);
  const firstSeparator = raw.indexOf(':');
  let kind = 'capability-followup';
  let identity = raw;
  if (firstSeparator > 0 && knownKinds.has(raw.slice(0, firstSeparator))) {
    kind = raw.slice(0, firstSeparator);
    identity = raw.slice(firstSeparator + 1);
  }
  const aliases = {
    cap: 'capability_id',
    capability: 'capability_id',
    card: 'card_binding_id',
    hypothesis: 'hypothesis_id',
    candidate: 'candidate_id',
  };
  const match = identity.match(/^([a-z][a-z0-9_]*):(.*)$/i);
  if (!match || !text(match[2])) return null;
  const field = aliases[match[1].toLowerCase()] || match[1];
  const supportedFields = new Set([
    'hypothesis_id',
    'card_binding_id',
    'capability_id',
    'candidate_id',
    'card_id',
    'name',
  ]);
  if (!supportedFields.has(field)) return null;
  const identifier = text(match[2]);
  const valueObject = {[field]: identifier};
  if (field === 'name') valueObject.name = identifier;
  return {kind, value: valueObject, identity: `${field}:${identifier}`};
};

/** Restore mutations leave the active-history filter visible to the user. */
export const resolveDeepHistoryFilterAfterMutation = (currentArchived, changes = {}) => (
  changes?.archived === false ? false : Boolean(currentArchived)
);

export const deepSessionMatchesTarget = (item, context) => {
  const wantedIds = deepSessionIdentityIds(context);
  const itemIds = deepSessionIdentityIds(item);
  if (wantedIds.length && itemIds.length) return itemIds.some(id => wantedIds.includes(id));
  const wantedName = text(
    context?.capability_name
    || context?.title
    || context?.name
    || context?.candidate?.name
    || context?.candidate?.title
    || context?.reference_weapon?.name
    || context?.focused_equipment?.name,
  );
  const itemName = text(item?.capability_name || item?.name || item?.title);
  if (wantedName && itemName) return wantedName === itemName;
  return false;
};

export const pickDeepSessionForTarget = (sessions, context, options = {}) => {
  const allRows = Array.isArray(sessions) ? sessions : [];
  const preferredId = text(options.preferredSessionId);
  if (preferredId) {
    // A URL is an explicit navigation request. Honour it even when the target
    // session is archived; archived rows remain excluded from implicit
    // "latest/current target" selection below.
    const preferred = allRows.find(item => text(item?.session_id) === preferredId);
    if (preferred) return preferred;
  }
  const rows = allRows.filter(item => text(item?.status).toLowerCase() !== 'archived');
  const currentId = text(options.currentSessionId);
  if (currentId) {
    const current = rows.find(item => text(item?.session_id) === currentId);
    if (current && deepSessionMatchesTarget(current, context)) return current;
  }
  const matching = rows.filter(item => deepSessionMatchesTarget(item, context));
  if (!matching.length) return null;
  const runId = text(options.runId);
  if (runId) {
    const sameRun = matching.find(item => text(item?.parent_run_id || item?.run_id) === runId);
    if (sameRun) return sameRun;
  }
  return matching[0];
};

/** Keep a requested branch while a lightweight history row is being hydrated. */
export const resolveDeepBranchId = ({session, currentBranchId = 'main', requestedBranchId = 'main', runningBranchId = ''} = {}) => {
  const current = text(currentBranchId) || 'main';
  const requested = text(requestedBranchId) || 'main';
  const running = text(runningBranchId);
  if (!session?.session_id || !Object.prototype.hasOwnProperty.call(session, 'branches')) {
    return running || current || requested;
  }
  const branches = Array.isArray(session.branches) ? session.branches : [];
  const available = new Set(['main', ...branches.map(item => text(item?.branch_id)).filter(Boolean)]);
  if (running && available.has(running)) return running;
  if (available.has(requested)) return requested;
  if (available.has(current)) return current;
  return 'main';
};

/** Coordinate branch correction with URL publication during session hydration. */
export const resolveDeepBranchNavigation = ({
  session,
  currentBranchId = 'main',
  requestedBranchId = 'main',
  runningBranchId = '',
  preferredSessionId = '',
} = {}) => {
  const sessionId = text(session?.session_id);
  const current = text(currentBranchId) || 'main';
  const requested = text(requestedBranchId) || 'main';
  const preferred = text(preferredSessionId);
  const restoringPreferredSession = Boolean(
    sessionId && preferred === sessionId,
  );
  const awaitingPreferredSession = Boolean(sessionId && preferred && preferred !== sessionId);
  const hasBranchCatalog = Boolean(
    session && Object.prototype.hasOwnProperty.call(session, 'branches'),
  );
  let branchId = resolveDeepBranchId({
    session,
    currentBranchId: current,
    requestedBranchId: requested,
    runningBranchId,
  });
  // History rows do not include branches. Preserve an explicit URL branch
  // until the detail response can validate it instead of publishing `main`.
  if (restoringPreferredSession && !hasBranchCatalog && requested !== 'main') {
    branchId = requested;
  }
  if (awaitingPreferredSession) branchId = current;
  return {
    branchId,
    shouldPublish: Boolean(sessionId) && !awaitingPreferredSession && !(
      restoringPreferredSession && current !== branchId
    ),
  };
};

/** Existing sessions own their focus; a launcher focus must never cross sessions. */
export const resolveDeepTurnFocus = (session, launcherFocus = '') => {
  if (!text(session?.session_id)) return text(launcherFocus);
  const refs = session?.context_refs && typeof session.context_refs === 'object'
    ? session.context_refs
    : {};
  return text(refs.focus || session?.focus);
};

const DEEP_REQUEST_ROLES = new Set(['analyst', 'developer', 'reviewer', 'auditor', 'admin']);

/** Prefer server/projected identity and use a route-specific role only in legacy mode. */
export const resolveDeepRequestRole = (context, legacyFallback = 'analyst') => {
  const source = context && typeof context === 'object' ? context : {};
  const scope = source.scope && typeof source.scope === 'object' ? source.scope : {};
  const auth = source.auth && typeof source.auth === 'object' ? source.auth : {};
  const identity = source.identity && typeof source.identity === 'object' ? source.identity : {};
  const candidates = [
    auth.role,
    identity.role,
    source.authenticated_role,
    source.request_role,
    source.role,
    scope.role,
    ...(Array.isArray(auth.roles) ? auth.roles : []),
    ...(Array.isArray(identity.roles) ? identity.roles : []),
  ];
  const available = new Set(candidates.map(value => text(value).toLowerCase()).filter(role => DEEP_REQUEST_ROLES.has(role)));
  const resolved = ['admin', 'auditor', 'reviewer', 'developer', 'analyst'].find(role => available.has(role));
  const fallback = text(legacyFallback).toLowerCase();
  return resolved || (DEEP_REQUEST_ROLES.has(fallback) ? fallback : 'analyst');
};

/** A lost fork response retries the same operation; the next branch gets a new key. */
export const deepForkIdempotencyKey = (sessionId, messageId, branches = []) => {
  const branchIds = (Array.isArray(branches) ? branches : [])
    .map(item => text(item?.branch_id))
    .filter(branchId => branchId && branchId !== 'main');
  return `fork:${text(sessionId)}:${text(messageId)}:${branchIds.length + 1}`;
};

export const extractDeliberationCandidates = (value, limit = 6) => {
  const source = text(value);
  if (!source) return [];
  const seen = new Set();
  const names = [];
  const push = raw => {
    const name = text(raw)
      .replace(/^[-*·\d.、]+\s*/, '')
      .replace(/[。；;]+$/g, '')
      .replace(/^[「"']|[」"']$/g, '');
    if (!name || name.length < 2 || name.length > 48 || seen.has(name)) return;
    if (/^(创新舱|对抗裁决|候选|优先保留|保留方向|提案)$/.test(name)) return;
    seen.add(name);
    names.push(name);
  };
  for (const chunk of source.split(/(?=(?:候选|优先保留|保留方向|提案)[:：])/)) {
    const match = chunk.match(/^(?:候选|优先保留|保留方向|提案)[:：]\s*([^\n]+)/);
    if (!match) continue;
    match[1].split(/[、,，;；|/]/).forEach(part => push(part.split(/[。]/)[0]));
  }
  return names.slice(0, Math.max(1, Number(limit) || 6));
};

export const isShortCandidateName = value => {
  const name = text(value);
  if (!name || name.length < 2 || name.length > 48) return false;
  if (/[:：。；;\n]/.test(name)) return false;
  return !/^(创新舱|对抗裁决|候选|优先保留|保留方向|提案)$/.test(name);
};

export const uniqueNamedValues = (names, seen) => {
  const owned = seen instanceof Set ? seen : new Set();
  const unique = [];
  for (const name of Array.isArray(names) ? names : []) {
    const value = text(name);
    if (!value || owned.has(value) || !isShortCandidateName(value)) continue;
    owned.add(value);
    unique.push(value);
  }
  return unique;
};

export const mergeDeliberationProposals = (...groups) => {
  const seen = new Set();
  const names = [];
  for (const group of groups) {
    const rows = Array.isArray(group) ? group : [group];
    for (const item of rows) {
      const value = text(item);
      if (!value) continue;
      names.push(...uniqueNamedValues(
        isShortCandidateName(value) ? [value] : extractDeliberationCandidates(value),
        seen,
      ));
    }
  }
  return names;
};

export const DEEP_FOCUS_ANGLE_LIMIT = 36;

export const shortDeepFocusAngle = (value, {name = '', limit = DEEP_FOCUS_ANGLE_LIMIT} = {}) => {
  const angle = text(value);
  if (!angle) return '';
  const label = text(name);
  if (label && angle === label) return '';
  const max = Math.max(8, Number(limit) || DEEP_FOCUS_ANGLE_LIMIT);
  if (angle.length > max) return '';
  return angle;
};

export const anchorWelcomeSuggestion = (equipment, prompt, limit = 120) => {
  const name = text(equipment);
  let body = text(prompt);
  if (!body) return '';
  if (!name) return body.length > limit ? `${body.slice(0, limit)}…` : body;
  if (body.includes(name)) {
    return body.length > limit ? `${body.slice(0, limit)}…` : body;
  }
  body = body.replace(/^围绕[「"][^」"]+[」"][，,:：]?\s*/, '').replace(/^围绕/, '').trim() || body;
  const anchored = `围绕「${name}」深度发散：${body}`;
  return anchored.length > limit ? `${anchored.slice(0, limit)}…` : anchored;
};

export const parseQuotedDeepMessage = content => {
  const raw = String(content ?? '').replace(/\r\n?/g, '\n').trim();
  if (!raw.startsWith(`${QUOTE_MARKER}\n`)) {
    return {quotedContext: '', content: raw};
  }
  const rest = raw.slice(QUOTE_MARKER.length + 1);
  const separator = rest.indexOf('\n\n');
  const quoteBlock = separator < 0 ? rest : rest.slice(0, separator);
  const body = separator < 0 ? '' : rest.slice(separator + 2);
  const lines = quoteBlock.split('\n');
  if (!lines.length || lines.some(line => line !== '>' && !line.startsWith('> '))) {
    return {quotedContext: '', content: raw};
  }
  const quotedContext = lines
    .map(line => (line === '>' ? '' : line.slice(2)))
    .join('\n')
    .trim();
  return quotedContext
    ? {quotedContext, content: body.trim()}
    : {quotedContext: '', content: raw};
};

export const formatQuotedDeepMessage = (content, quotedContext) => {
  const body = text(content);
  const quote = String(quotedContext ?? '').replace(/\r\n?/g, '\n').trim();
  if (!quote || body.startsWith('/')) return body;
  if (body.startsWith(QUOTE_MARKER)) return body;
  const block = quote.split('\n').map(line => (line ? `> ${line}` : '>')).join('\n');
  return body ? `${QUOTE_MARKER}\n${block}\n\n${body}` : `${QUOTE_MARKER}\n${block}`;
};

export const directionFollowUp = item => {
  const name = text(item?.innovation_variant_name || item?.name || item?.candidate_name);
  if (!name) return '';
  const angle = shortDeepFocusAngle(
    item?.winning_angle || item?.equipment_form || item?.innovation_equipment_form,
    {name},
  );
  const focus = angle ? `，沿「${angle}」` : '';
  return `围绕「${name}」继续深化${focus}：闭合打击对象、直接毁伤机理与任务失能判据，并预演对手最低成本反制后如何保持非对称收益。`;
};

export const extractDeepFollowUps = ({answer, messages = [], limit = 4} = {}) => {
  const seen = new Set();
  const rows = [];
  const push = value => {
    const next = sanitizePublicResearchGap(value);
    if (!next || next.length < 8 || seen.has(next)) return;
    seen.add(next);
    rows.push(next);
  };
  const source = answer && typeof answer === 'object' ? answer : {};
  (Array.isArray(source.next_questions) ? source.next_questions : []).forEach(push);
  (Array.isArray(source.open_questions) ? source.open_questions : []).forEach(push);
  const latest = [...(Array.isArray(messages) ? messages : [])]
    .reverse()
    .find(item => text(item?.role).toLowerCase() === 'assistant' && text(item?.content));
  if (latest) {
    const match = text(latest.content).match(
      /(?:#{1,6}\s*)?(?:后续追问|建议追问|可以继续问|下一步)\s*\n+([\s\S]{8,900}?)(?=\n#{1,6}\s|$)/,
    );
    if (match) {
      match[1]
        .split(/\n+/)
        .map(line => line.replace(/^[-*\d.、]+\s*/, '').trim())
        .forEach(push);
    }
  }
  return rows.slice(0, Math.max(1, Number(limit) || 4));
};

export const DEEP_SLASH_COMMANDS = [
  {id: 'diverge', command: '/diverge', label: '开放发散', detail: '重新探索正交假设，扩大当前问题的解空间'},
  {id: 'challenge', command: '/challenge', label: '对抗检验', detail: '寻找反例、最低成本反制与失效边界'},
  {id: 'synthesize', command: '/synthesize', label: '综合归纳', detail: '比较已有方向，形成可继续研究的前沿'},
  {id: 'card', command: '/card', label: '形成能力卡', detail: '用已收敛方向写五栏，不再扩展新候选'},
  {id: 'memory', command: '/memory', label: '查看决策记忆', detail: '只读当前工作记忆，不重跑议事'},
  {id: 'help', command: '/help', label: '命令说明', detail: '列出定向深研可用命令'},
];

export const matchDeepSlashCommand = draft => {
  const value = text(draft);
  if (!value.startsWith('/')) return null;
  const name = value.slice(1).split(/\s+/, 1)[0].toLowerCase();
  return DEEP_SLASH_COMMANDS.find(item => item.id === name) || null;
};

export const filterDeepSlashCommands = draft => {
  const value = String(draft ?? '');
  if (!value.startsWith('/')) return [];
  const query = value.slice(1).toLowerCase();
  return DEEP_SLASH_COMMANDS.filter(item => (
    item.command.slice(1).startsWith(query)
    || item.id.startsWith(query)
    || item.label.includes(query)
  ));
};

const looksLikeCompleteAnswerDump = value => {
  const body = text(value);
  return body.length > 360 && /###\s*本轮完整结果/.test(body);
};

const proposalBriefs = event => {
  const raw = eventValue(event, 'proposal_briefs');
  if (!Array.isArray(raw)) return [];
  return raw
    .map(item => {
      if (!item || typeof item !== 'object') return null;
      const name = text(item.name);
      if (!name) return null;
      return {
        name,
        equipment_form: text(item.equipment_form),
        winning_angle: text(item.winning_angle),
        disruptive_difference: text(item.disruptive_difference),
      };
    })
    .filter(Boolean)
    .slice(0, 3);
};

const inferRound = event => {
  const round = text(eventValue(event, 'round')).toLowerCase();
  if (round) return round;
  const stage = normalizeDeepStage(event?.stage);
  if (stage === 'council_critique') return 'critique';
  if (stage === 's6_authoring') return 'authoring';
  if (stage === 's4_mapping') return 'synthesis';
  if (stage === 's3_divergence') return 'divergence';
  if (stage === 'context') return 'memory';
  return '';
};

const EXPLORATION_AGENT_IDS = new Set([
  'deep_dialogue_doctrine_breaker',
  'deep_dialogue_terminal_effect_architect',
  'deep_dialogue_adversary_red_team',
  'deep_dialogue_adversarial_judge',
]);

export const inferProcessRosterMode = (events = [], {sending = false, activeStage = ''} = {}) => {
  const rows = Array.isArray(events) ? events : [];
  const hasExploration = rows.some(item => {
    const id = text(eventValue(item, 'agent_id'));
    const round = inferRound(item);
    const stage = normalizeDeepStage(item?.stage);
    return round === 'divergence'
      || round === 'critique'
      || stage === 's3_divergence'
      || stage === 'council_critique'
      || EXPLORATION_AGENT_IDS.has(id);
  });
  if (hasExploration) return 'explore';
  const hasColumns = rows.some(item => (
    inferRound(item) === 'authoring' || normalizeDeepStage(item?.stage) === 's6_authoring'
  ));
  if (hasColumns) return 'card';
  const hasDeepen = rows.some(item => {
    const round = inferRound(item);
    const axis = text(eventValue(item, 'axis'));
    const role = text(eventValue(item, 'role'));
    return round === 'deepen' || /深化/.test(`${axis}${role}`);
  });
  if (hasDeepen) return 'deepen';
  const hasCommand = rows.some(item => {
    const id = text(eventValue(item, 'agent_id'));
    const round = inferRound(item);
    return id === 'deep_dialogue_memory' || id === 'deep_dialogue_runtime' || round === 'memory' || round === 'command';
  });
  const stage = normalizeDeepStage(activeStage);
  if (sending && stage === 's3_divergence') return 'explore';
  if (sending && stage === 's6_authoring') return 'card';
  if (sending && stage === 's4_mapping') return 'deepen';
  if (hasCommand) return 'command';
  if (sending) return 'pending';
  return 'idle';
};

/** Project in-flight agent answers into a nanobot-style live transcript draft. */
export const projectLiveConversationFeedback = (events = []) => {
  const rows = Array.isArray(events) ? events : [];
  const ordered = rows
    .map((event, index) => ({event, index}))
    .sort((left, right) => {
      const leftSequence = Number(left.event?.sequence);
      const rightSequence = Number(right.event?.sequence);
      if (!Number.isFinite(leftSequence) || !Number.isFinite(rightSequence)) {
        return left.index - right.index;
      }
      return (leftSequence - rightSequence) || (left.index - right.index);
    });

  const segments = [];
  const seenSegments = new Set();
  let runningLabel = '';
  let runningExcerpt = '';

  ordered.forEach(({event}) => {
    const type = text(event?.event_type);
    const kind = text(eventValue(event, 'kind')).toLowerCase();
    const status = text(event?.status).toLowerCase();
    const body = eventText(event);
    if (looksLikeCompleteAnswerDump(body)) return;
    const agentId = text(eventValue(event, 'agent_id'));
    const role = text(eventValue(event, 'role')) || AGENT_LABELS[agentId] || '';
    const axis = text(eventValue(event, 'axis'));
    const round = inferRound(event);
    const stage = normalizeDeepStage(event?.stage);
    const names = boundedStrings(eventValue(event, 'proposal_names'));
    const briefs = proposalBriefs(event);
    const isRunning = type === 'deep_agent_started'
      || status === 'running'
      || kind === 'summary';
    if (isRunning && (role || body) && type !== 'deep_agent_completed') {
      runningLabel = role || AGENT_LABELS[agentId] || '创新舱';
      runningExcerpt = body;
    }
    const isAnswer = kind === 'answer' || type === 'deep_agent_completed';
    if (!isAnswer || !body) return;
    // One agent may return several useful answers in the same stage. Keep
    // each event in order; agent/stage identity previously caused a later
    // answer to overwrite an earlier visible result.
    const key = text(event?.event_id)
      || (Number.isFinite(Number(event?.sequence)) && Number(event.sequence) > 0
        ? `sequence:${Number(event.sequence)}`
        : `${agentId || role}:${stage}:${round || kind}:${body}`);
    if (seenSegments.has(key)) return;
    seenSegments.add(key);
    segments.push({
      key,
      agent_id: agentId,
      role: role || '创新舱',
      axis,
      round: round || 'divergence',
      stage,
      text: body,
      names,
      briefs,
      verdicts: boundedStrings(eventValue(event, 'verdicts')),
    });
  });

  const markdown = segments.map(segment => {
    const title = [segment.role, segment.axis].filter(Boolean).join(' · ');
    const excerpt = text(segment.text);
    const names = segment.names.length ? `\n候选：${segment.names.join('、')}` : '';
    return `**${title}**\n${excerpt}${names}`;
  }).join('\n\n');
  const directions = [];
  segments.forEach(segment => {
    (segment.briefs.length ? segment.briefs : segment.names.map(name => ({name}))).forEach(brief => {
      const name = text(brief.name);
      if (!name || directions.some(item => item.name === name)) return;
      directions.push({
        name,
        equipment_form: text(brief.equipment_form),
        winning_angle: text(brief.winning_angle),
        disruptive_difference: text(brief.disruptive_difference),
      });
    });
  });

  return {
    segments,
    markdown,
    running_label: runningLabel,
    running_excerpt: runningExcerpt,
    answer: {
      agent_dialogue: segments.map(segment => ({
        agent_id: segment.agent_id,
        role: segment.role,
        axis: segment.axis,
        round: segment.round,
        summary: segment.text,
        proposal_names: segment.names,
        verdicts: segment.verdicts,
      })),
      concept_directions: directions,
      adjudication: {
        candidate_reviews: segments
          .filter(segment => segment.round === 'critique')
          .flatMap(segment => (
            segment.verdicts.length
              ? segment.verdicts.map(item => {
                const [name, verdict] = String(item).split(/[→>]/);
                return {
                  candidate_name: text(name),
                  verdict: text(verdict).toLowerCase() || 'keep',
                };
              })
              : segment.names.map(name => ({candidate_name: name, verdict: 'keep'}))
          )),
      },
    },
  };
};
