import test from 'node:test';
import assert from 'node:assert/strict';

import {
  filterDeepSlashCommands,
  inferProcessRosterMode,
  isTerminalJob,
  matchDeepSlashCommand,
  mergeDeepJobState,
  parseQuotedDeepMessage,
  formatQuotedDeepMessage,
  extractDeepFollowUps,
  directionFollowUp,
  deepForkIdempotencyKey,
  isThreadNearBottom,
  shouldShowJumpToLatest,
  pickDeepSessionForTarget,
  extractDeliberationCandidates,
  mergeDeliberationProposals,
  uniqueNamedValues,
  isShortCandidateName,
  shortDeepFocusAngle,
  anchorWelcomeSuggestion,
  branchActiveSkillIds,
  branchWorkingMemory,
  projectDeepAgentActivity,
  projectDeepActivityRoster,
  projectDeepContextUsage,
  projectDeepMemory,
  projectLiveConversationFeedback,
  sanitizePublicResearchGap,
  parseDeepTargetIdentity,
  resolveDeepHistoryFilterAfterMutation,
  resolveDeepBranchId,
  resolveDeepBranchNavigation,
  resolveDeepRequestRole,
  resolveDeepTurnFocus,
  resolveBranchSkillSelection,
} from './deep-thinking-state.js';

test('retrieval status diagnostics stay out of public follow-up gaps', () => {
  assert.equal(sanitizePublicResearchGap('来源边界：检索不可用'), '');
  assert.equal(
    sanitizePublicResearchGap('补充任务失能判据与落装接口'),
    '补充任务失能判据与落装接口',
  );
});

test('older poll response cannot replace newer SSE terminal state', () => {
  const completed = {
    job_id: 'job-1',
    state_version: 8,
    stage: 'publish',
    status: 'completed',
    progress: 1,
  };
  const stalePoll = {
    job_id: 'job-1',
    state_version: 7,
    stage: 's3_divergence',
    status: 'running',
    progress: 0.35,
  };

  assert.deepEqual(mergeDeepJobState(completed, stalePoll), completed);
});

test('same-version non-terminal update cannot resurrect a terminal job', () => {
  const cancelled = {
    job_id: 'job-2',
    state_version: 4,
    stage: 'publish',
    status: 'cancelled',
    progress: 1,
  };
  const delayed = {
    job_id: 'job-2',
    state_version: 4,
    stage: 's4_mapping',
    status: 'running',
    progress: 0.7,
  };

  assert.deepEqual(mergeDeepJobState(cancelled, delayed), cancelled);
});

test('stage and progress only move forward within one attempt', () => {
  const current = {
    job_id: 'job-3',
    state_version: 5,
    stage: 's6_authoring',
    status: 'running',
    progress: 0.82,
  };
  const delayed = {
    job_id: 'job-3',
    state_version: 5,
    stage: 's3_divergence',
    status: 'queued',
    progress: 0.25,
  };
  const merged = mergeDeepJobState(current, delayed);

  assert.equal(merged.stage, 's6_authoring');
  assert.equal(merged.status, 'running');
  assert.equal(merged.progress, 0.82);
});

test('higher-version explicit retry resets terminal stage and progress', () => {
  const failed = {
    job_id: 'job-4',
    state_version: 11,
    stage: 'publish',
    status: 'failed',
    progress: 1,
    error: 'old failure',
  };
  const retry = {
    job_id: 'job-4',
    state_version: 12,
    stage: 'queued',
    status: 'queued',
    progress: 0,
    error: '',
  };
  const merged = mergeDeepJobState(failed, retry);

  assert.equal(merged.stage, 'queued');
  assert.equal(merged.status, 'queued');
  assert.equal(merged.progress, 0);
  assert.equal(merged.error, '');
  assert.equal(isTerminalJob(merged), false);
});

test('a different queued job replaces the previous completed turn', () => {
  const completed = {
    job_id: 'job-old',
    state_version: 9,
    stage: 'publish',
    status: 'completed',
    progress: 1,
  };
  const next = {
    job_id: 'job-next',
    state_version: 1,
    stage: 'queued',
    status: 'queued',
    progress: 0,
  };

  assert.deepEqual(mergeDeepJobState(completed, next), next);
});

test('agent activity projection rebuilds completion-order handoffs from replay', () => {
  const projected = projectDeepAgentActivity([
    {
      sequence: 3,
      event_type: 'deep_agent_handoff',
      delta: {
        from_agent_id: 'deep_dialogue_council',
        to_agent_id: 'deep_dialogue_adversarial_judge',
        handoff_kind: 'proposal_review',
        deliverable_refs: ['候选甲', '候选乙'],
        text: '三路提案进入裁决。',
      },
    },
    {
      sequence: 1,
      event_type: 'deep_agent_started',
      status: 'running',
      delta: {
        agent_id: 'deep_dialogue_doctrine_breaker',
        role: '新质颠覆架构 Agent',
        text: '开始发散。',
      },
    },
    {
      sequence: 2,
      event_type: 'deep_agent_completed',
      status: 'completed',
      delta: {
        agent_id: 'deep_dialogue_doctrine_breaker',
        role: '新质颠覆架构 Agent',
        proposal_names: ['候选甲'],
        text: '已提交候选甲。',
      },
    },
  ]);

  assert.equal(projected.agents.find(item => item.agent_id === 'deep_dialogue_doctrine_breaker').status, 'done');
  assert.equal(projected.agents.find(item => item.agent_id === 'deep_dialogue_adversarial_judge').status, 'running');
  assert.deepEqual(projected.handoffs[0].deliverable_refs, ['候选甲', '候选乙']);
});

test('agent activity projection keeps a recovered agent completed after failure', () => {
  const projected = projectDeepAgentActivity([
    {
      sequence: 4,
      event_type: 'deep_agent_failed',
      status: 'partial',
      delta: {agent_id: 'deep_dialogue_adversarial_judge', role: '对抗裁决 Agent', text: '切换降级裁决。'},
    },
    {
      sequence: 5,
      event_type: 'deep_agent_completed',
      status: 'completed',
      delta: {agent_id: 'deep_dialogue_adversarial_judge', role: '对抗裁决 Agent', text: '降级裁决已完成。'},
    },
  ]);

  assert.equal(projected.failed_count, 0);
  assert.equal(projected.completed_count, 1);
  assert.equal(projected.agents[0].summary, '降级裁决已完成。');
});

test('agent activity projection attributes an applied steer to its receiver', () => {
  const projected = projectDeepAgentActivity([
    {
      sequence: 8,
      event_id: 'event-steer',
      event_type: 'deep_steer_applied',
      stage: 'council_critique',
      delta: {
        agent_id: 'deep_dialogue_adversarial_judge',
        role: '对抗裁决 Agent',
        text: '你的补充已由对抗裁决 Agent 纳入当前研究。',
      },
    },
  ]);

  assert.equal(projected.interventions.length, 1);
  assert.equal(projected.interventions[0].agent_id, 'deep_dialogue_adversarial_judge');
  assert.match(projected.interventions[0].summary, /纳入当前研究/);
});

test('activity roster contains only agents observed in the current turn', () => {
  const roster = projectDeepActivityRoster([
    {
      sequence: 1,
      event_type: 'deep_agent_started',
      status: 'running',
      delta: {
        agent_id: 'mission_specific_explorer',
        role: '任务特定探索 Agent',
        axis: '时敏链路反转',
        text: '正在扩展新角度。',
      },
    },
  ], {sending: true});

  assert.equal(roster.length, 1);
  assert.equal(roster[0].agent_id, 'mission_specific_explorer');
  assert.equal(roster[0].label, '任务特定探索 Agent');
  assert.equal(roster[0].badge, '01');
  assert.deepEqual(projectDeepActivityRoster([], {sending: false}), []);
  assert.equal(projectDeepActivityRoster([], {sending: true})[0].label, '研究编排');
});

test('context usage prefers the server snapshot and falls back to living-window math', () => {
  const fromServer = projectDeepContextUsage({
    context_usage: {
      share: 0.12,
      living_turns: 2,
      archived_turns: 3,
      compacted: true,
      current_objective: '闭合毁伤判据',
      constraint_count: 2,
      decision_count: 1,
      open_question_count: 3,
      visible_messages: 10,
      estimated_chars: 1440,
      budget_chars: 12000,
    },
  });
  assert.equal(fromServer.share, 0.12);
  assert.equal(fromServer.archived_turns, 3);
  assert.equal(fromServer.compacted, true);

  const fallback = projectDeepContextUsage({
    messages: [
      {role: 'user', content: '旧问题'},
      {role: 'assistant', content: '旧结论'},
      {role: 'user', content: '中问题'},
      {role: 'assistant', content: '中结论'},
      {role: 'user', content: '新问题'},
      {role: 'assistant', content: '新结论'},
    ],
    working_memory: {
      current_objective: '夺取先机',
      latest_summary: ['保留颠覆方向'],
      user_constraints: ['不要换壳'],
      decisions: [{candidate: '潜伏节点'}],
    },
  });
  assert.equal(fallback.living_turns, 2);
  assert.equal(fallback.archived_turns, 1);
  assert.equal(fallback.compacted, true);
  assert.equal(fallback.constraint_count, 1);
});

test('decision memory is projected per branch without raw provider state', () => {
  const session = {
    working_memory: {
      active_branch_id: 'main',
      branches: {
        main: {branch_id: 'main', current_objective: '主线目标'},
        'branch-2': {
          branch_id: 'branch-2',
          current_objective: '验证低成本失能路径',
          latest_summary: ['保留两条正交方向'],
          user_constraints: ['不得退化成平台换壳'],
          candidate_directions: [{name: '潜伏节点', winning_angle: '时序反转', stable: true}],
          decisions: [{candidate: '潜伏节点', verdict: 'keep', reason: '可闭合失能判据'}],
          rejected_directions: [{candidate: '增程方案', verdict: 'reject', reason: '仅参数升级'}],
          open_questions: ['反制后如何保持先机？'],
          research_iteration: 3,
          research_frontier: [{
            direction: '潜伏先机节点',
            status: 'exploring',
            why_promising: '可改写攻击时序',
            next_probe: '清场反制后是否仍有收益？',
          }],
          assumption_ledger: [{
            assumption: '发射后必须立即攻击',
            direction: '潜伏先机节点',
            status: 'open',
          }],
          explored_lenses: ['任务链反转', '最低成本反制'],
          research_gaps: [{
            candidate_name: '潜伏先机节点',
            missing_dimensions: ['mission_kill_criterion'],
            suggested_question: '如何观察任务失能？',
          }],
          last_research_strategy: {
            mode: 'challenge',
            actions: ['challenge', 'synthesize'],
            rationale: '先找反例，再保留仍成立的方向',
          },
          provider_state: {hidden: 'must not leak'},
        },
      },
    },
  };
  const projected = projectDeepMemory(session, 'branch-2');
  assert.equal(projected.branch_id, 'branch-2');
  assert.equal(projected.current_objective, '验证低成本失能路径');
  assert.equal(projected.directions[0].stable, true);
  assert.equal(projected.decisions[0].verdict, 'keep');
  assert.equal(projected.research_iteration, 3);
  assert.equal(projected.research_frontier[0].direction, '潜伏先机节点');
  assert.equal(projected.assumption_ledger[0].assumption, '发射后必须立即攻击');
  assert.deepEqual(projected.explored_lenses, ['任务链反转', '最低成本反制']);
  assert.equal(projected.research_gaps[0], '潜伏先机节点：如何观察任务失能？');
  assert.deepEqual(projected.last_research_strategy.actions, ['challenge', 'synthesize']);
  assert.doesNotMatch(projected.research_gaps[0], /\[object Object\]/);
  assert.equal('provider_state' in projected, false);
});

test('branch memory never falls back to the active branch when the target is missing', () => {
  const workingMemory = {
    active_branch_id: 'main',
    branches: {
      main: {
        branch_id: 'main',
        current_objective: '主线目标',
        active_skill_ids: ['skill-main'],
      },
    },
  };

  assert.deepEqual(branchWorkingMemory(workingMemory, 'missing-branch'), {});
  const projected = projectDeepMemory({working_memory: workingMemory}, 'missing-branch');
  assert.equal(projected.branch_id, 'missing-branch');
  assert.equal(projected.current_objective, '');
  assert.equal(projected.has_memory, false);
  assert.deepEqual(
    branchWorkingMemory({branch_id: 'main', current_objective: '旧主线'}, 'branch-2'),
    {},
  );
});

test('branch skill selection is isolated and stale selections cannot enter another branch turn', () => {
  const session = {
    session_id: 'session-1',
    active_skill_ids: ['skill-main-alias'],
    working_memory: {
      active_branch_id: 'main',
      branches: {
        main: {branch_id: 'main', active_skill_ids: ['skill-main']},
        explore: {branch_id: 'explore', active_skill_ids: ['skill-explore']},
      },
    },
  };

  assert.deepEqual(branchActiveSkillIds(session, 'main'), ['skill-main']);
  assert.deepEqual(branchActiveSkillIds(session, 'explore'), ['skill-explore']);
  assert.deepEqual(branchActiveSkillIds(session, 'missing-branch'), []);
  assert.deepEqual(branchActiveSkillIds(null, 'main', ['explicit-default']), ['explicit-default']);

  assert.deepEqual(resolveBranchSkillSelection({
    session,
    branchId: 'explore',
    selectedSkillIds: ['unsaved-main-selection'],
    selectedSessionId: 'session-1',
    selectedBranchId: 'main',
  }), ['skill-explore']);
  assert.deepEqual(resolveBranchSkillSelection({
    session,
    branchId: 'missing-branch',
    selectedSkillIds: ['unsaved-main-selection'],
    selectedSessionId: 'session-1',
    selectedBranchId: 'main',
  }), []);
});

test('context usage does not reuse a main-branch snapshot for another branch', () => {
  const projected = projectDeepContextUsage({
    context_usage: {branch_id: 'main', share: 0.9, living_turns: 2},
    messages: [{role: 'user', branch_id: 'branch-2', content: '分支问题'}],
    working_memory: {
      branches: {'branch-2': {branch_id: 'branch-2', current_objective: '分支目标'}},
    },
  }, 'branch-2');
  assert.equal(projected.branch_id, 'branch-2');
  assert.notEqual(projected.share, 0.9);
  assert.equal(projected.current_objective, '分支目标');
});

test('slash commands filter from a leading slash', () => {
  const matches = filterDeepSlashCommands('/c');
  assert.deepEqual(matches.map(item => item.id), ['challenge', 'card']);
  assert.equal(matchDeepSlashCommand('/diverge').id, 'diverge');
  assert.equal(matchDeepSlashCommand('/challenge 只检验清场反制').id, 'challenge');
  assert.equal(matchDeepSlashCommand('/synthesize').id, 'synthesize');
  assert.equal(matchDeepSlashCommand('/memory').id, 'memory');
  assert.equal(matchDeepSlashCommand('/card 保持方向').id, 'card');
  assert.equal(matchDeepSlashCommand('继续追问'), null);
  assert.deepEqual(filterDeepSlashCommands('card'), []);
});

test('live conversation feedback promotes completed agent answers immediately', () => {
  const projected = projectLiveConversationFeedback([
    {
      sequence: 1,
      event_type: 'deep_agent_started',
      status: 'running',
      stage: 's3_divergence',
      delta: {
        kind: 'summary',
        agent_id: 'deep_dialogue_doctrine_breaker',
        role: '新质颠覆架构 Agent',
        axis: '颠覆·机理·链反转',
        text: '正在沿任务链反转发散。',
      },
    },
    {
      sequence: 2,
      event_type: 'deep_agent_completed',
      status: 'completed',
      stage: 's3_divergence',
      delta: {
        kind: 'answer',
        agent_id: 'deep_dialogue_doctrine_breaker',
        role: '新质颠覆架构 Agent',
        axis: '颠覆·机理·链反转',
        round: 'divergence',
        proposal_names: ['潜伏先机节点'],
        proposal_briefs: [{name: '潜伏先机节点', winning_angle: '任务链重构', equipment_form: '潜伏展开节点'}],
        text: '颠覆·机理·链反转：将即时攻击改为潜伏后择机断链。',
      },
    },
    {
      sequence: 3,
      event_type: 'deep_agent_completed',
      status: 'completed',
      stage: 'council_critique',
      delta: {
        kind: 'answer',
        agent_id: 'deep_dialogue_adversarial_judge',
        role: '对抗裁决 Agent',
        round: 'critique',
        verdicts: ['潜伏先机节点→keep'],
        text: '保留能夺先机制衡的颠覆方向。',
      },
    },
  ]);

  assert.equal(projected.segments.length, 2);
  assert.match(projected.markdown, /潜伏先机节点/);
  assert.equal(projected.answer.concept_directions[0].name, '潜伏先机节点');
  assert.equal(projected.answer.adjudication.candidate_reviews[0].verdict, 'keep');
  assert.equal(projected.answer.agent_dialogue[1].round, 'critique');
});

test('follow-up deepening is inferred from observed activity', () => {
  const mode = inferProcessRosterMode(
    [{
      stage: 's4_mapping',
      event_type: 'deep_agent_started',
      delta: {
        round: 'deepen',
        role: '内部多维发散',
        axis: '多维度多角度交叉发散',
        agent_id: 'deep_thinking_dialogue',
      },
    }],
    {sending: true, activeStage: 's4_mapping'},
  );
  assert.equal(mode, 'deepen');
});

test('opening divergence events use open exploration mode', () => {
  const mode = inferProcessRosterMode(
    [{
      stage: 's3_divergence',
      event_type: 'deep_agent_started',
      delta: {
        round: 'divergence',
        agent_id: 'deep_dialogue_doctrine_breaker',
        role: '新质颠覆架构 Agent',
      },
    }],
    {sending: true, activeStage: 's3_divergence'},
  );
  assert.equal(mode, 'explore');
});

test('live feedback keeps internal deepen angles visible', () => {
  const projected = projectLiveConversationFeedback([
    {
      sequence: 1,
      event_type: 'deep_agent_completed',
      status: 'completed',
      stage: 's4_mapping',
      delta: {
        kind: 'answer',
        round: 'deepen',
        role: '内部发散 · 直接毁伤·末端效应·目标失能',
        axis: '直接毁伤·末端效应·目标失能',
        agent_id: 'deep_thinking_dialogue',
        proposal_names: ['潜伏先机节点'],
        text: '把失能判据收到关键任务舱段退出当前任务周期。',
      },
    },
  ]);
  assert.equal(projected.segments[0].round, 'deepen');
  assert.match(projected.markdown, /潜伏先机节点/);
});

test('later feedback from the same agent appends without replacing earlier text', () => {
  const projected = projectLiveConversationFeedback([
    {
      sequence: 11,
      event_type: 'deep_agent_completed',
      status: 'completed',
      stage: 's4_mapping',
      delta: {
        kind: 'answer',
        round: 'deepen',
        role: '候选方向综合总编',
        agent_id: 'deep_thinking_dialogue',
        text: '第一条完整反馈\n- 保留这一条中的明细 A\n- 保留明细 B',
      },
    },
    {
      sequence: 12,
      event_type: 'deep_agent_completed',
      status: 'completed',
      stage: 's4_mapping',
      delta: {
        kind: 'answer',
        round: 'deepen',
        role: '候选方向综合总编',
        agent_id: 'deep_thinking_dialogue',
        text: '第二条反馈，应追加显示',
      },
    },
  ]);

  assert.equal(projected.segments.length, 2);
  assert.match(projected.markdown, /第一条完整反馈/);
  assert.match(projected.markdown, /保留明细 B/);
  assert.match(projected.markdown, /第二条反馈，应追加显示/);
  assert.ok(projected.markdown.indexOf('第一条完整反馈') < projected.markdown.indexOf('第二条反馈'));
});

test('replayed duplicate event does not duplicate its visible result', () => {
  const event = {
    event_id: 'deep-event-stable',
    sequence: 15,
    event_type: 'deep_agent_completed',
    stage: 's3_divergence',
    delta: {kind: 'answer', role: '开放探索 Agent', text: '稳定回放结果'},
  };
  const projected = projectLiveConversationFeedback([event, {...event}]);
  assert.equal(projected.segments.length, 1);
});

test('quoted follow-up round-trips without wrapping slash commands', () => {
  const formatted = formatQuotedDeepMessage('继续闭合失能判据', '把打击对象收到关键任务舱段');
  const parsed = parseQuotedDeepMessage(formatted);
  assert.equal(parsed.quotedContext, '把打击对象收到关键任务舱段');
  assert.equal(parsed.content, '继续闭合失能判据');
  assert.equal(formatQuotedDeepMessage('/card', '引用不应进入命令'), '/card');
});

test('follow-up extraction prefers structured next questions then answer headings', () => {
  const extracted = extractDeepFollowUps({
    answer: {next_questions: ['如何保持反适应收益？']},
    messages: [{
      role: 'assistant',
      content: '### 后续追问\n- 失能判据如何被战场观察确认？\n- 对手最低成本反制后如何改构型？',
    }],
  });
  assert.equal(extracted[0], '如何保持反适应收益？');
  assert.ok(extracted.some(item => item.includes('失能判据')));
  assert.match(directionFollowUp({name: '潜伏先机节点', winning_angle: '任务链重构'}), /潜伏先机节点/);
});

test('thread near-bottom helper uses a nanobot-style threshold', () => {
  assert.equal(isThreadNearBottom({scrollHeight: 800, scrollTop: 740, clientHeight: 50}), true);
  assert.equal(isThreadNearBottom({scrollHeight: 800, scrollTop: 100, clientHeight: 50}), false);
  assert.equal(shouldShowJumpToLatest({scrollHeight: 382, scrollTop: 0, clientHeight: 382}), false);
  assert.equal(shouldShowJumpToLatest({scrollHeight: 800, scrollTop: 100, clientHeight: 50}), true);
});

test('opening a card does not steal another equipment transcript', () => {
  const sessions = [
    {session_id: 's-bai', title: '百链分散攻击巡飞弹', card_binding_id: 's6-card-bai', run_id: 'run-1', status: 'active'},
    {session_id: 's-dihuan', title: '低换高耗攻击巡飞弹', card_binding_id: 's6-card-dihuan', run_id: 'run-1', status: 'active'},
  ];
  const matched = pickDeepSessionForTarget(sessions, {card_binding_id: 's6-card-dihuan'}, {runId: 'run-1'});
  assert.equal(matched.session_id, 's-dihuan');
  assert.equal(pickDeepSessionForTarget(sessions, {card_binding_id: 's6-card-new'}, {runId: 'run-1'}), null);
  assert.equal(
    pickDeepSessionForTarget(sessions, {card_binding_id: 's6-card-dihuan'}, {
      runId: 'run-1',
      currentSessionId: 's-bai',
    }).session_id,
    's-dihuan',
  );
});

test('an explicit URL session restores an archived transcript', () => {
  const sessions = [
    {session_id: 's-current', card_binding_id: 'card-a', status: 'active'},
    {session_id: 's-archived', card_binding_id: 'card-b', status: 'archived'},
  ];

  assert.equal(
    pickDeepSessionForTarget(sessions, {card_binding_id: 'card-a'}, {preferredSessionId: 's-archived'})?.session_id,
    's-archived',
  );
  assert.equal(
    pickDeepSessionForTarget(sessions, {card_binding_id: 'card-b'}),
    null,
    'archived sessions must not be selected implicitly',
  );
});

test('a target-only URL can rebuild a minimal equipment target after refresh', () => {
  assert.deepEqual(parseDeepTargetIdentity('capability-followup:card_binding_id:card-7'), {
    kind: 'capability-followup',
    value: {card_binding_id: 'card-7'},
    identity: 'card_binding_id:card-7',
  });
  assert.deepEqual(parseDeepTargetIdentity('reference-research:hypothesis_id:h-2'), {
    kind: 'reference-research',
    value: {hypothesis_id: 'h-2'},
    identity: 'hypothesis_id:h-2',
  });
  assert.deepEqual(parseDeepTargetIdentity('cap:9'), {
    kind: 'capability-followup',
    value: {capability_id: '9'},
    identity: 'capability_id:9',
  });
  assert.equal(parseDeepTargetIdentity(''), null);
  assert.equal(parseDeepTargetIdentity('unknown:9'), null);
});

test('restoring an archived session returns the history list to active sessions', () => {
  assert.equal(resolveDeepHistoryFilterAfterMutation(true, {archived: false}), false);
  assert.equal(resolveDeepHistoryFilterAfterMutation(false, {archived: false}), false);
  assert.equal(resolveDeepHistoryFilterAfterMutation(true, {title: 'rename'}), true);
  assert.equal(resolveDeepHistoryFilterAfterMutation(false, {archived: true}), false);
});

test('branch URL intent survives a summary and is validated by full session detail', () => {
  const requested = resolveDeepBranchId({
    session: {session_id: 's-1', status: 'active'},
    currentBranchId: 'branch-2',
    requestedBranchId: 'branch-2',
  });
  assert.equal(requested, 'branch-2');
  assert.equal(resolveDeepBranchId({
    session: {session_id: 's-1', branches: [{branch_id: 'branch-2'}]},
    currentBranchId: requested,
    requestedBranchId: 'branch-2',
  }), 'branch-2');
  assert.equal(resolveDeepBranchId({
    session: {session_id: 's-1', branches: [{branch_id: 'branch-2'}, {branch_id: 'branch-3'}]},
    currentBranchId: 'branch-2',
    requestedBranchId: 'branch-3',
  }), 'branch-3', 'browser navigation must override the previously active branch');
  assert.equal(resolveDeepBranchId({
    session: {session_id: 's-1', branches: []},
    currentBranchId: 'missing-branch',
    requestedBranchId: 'missing-branch',
  }), 'main');
});

test('branch restore waits for the branch correction before publishing navigation', () => {
  const navigation = {
    currentBranchId: 'main',
    requestedBranchId: 'branch-2',
    preferredSessionId: 's-1',
  };
  const summaryDecision = resolveDeepBranchNavigation({
    ...navigation,
    session: {session_id: 's-1', status: 'active'},
  });
  assert.deepEqual(summaryDecision, {
    branchId: 'branch-2',
    shouldPublish: false,
  });

  const detailDecision = resolveDeepBranchNavigation({
    ...navigation,
    session: {session_id: 's-1', branches: [{branch_id: 'branch-2'}]},
  });
  assert.deepEqual(detailDecision, {
    branchId: 'branch-2',
    shouldPublish: false,
  });

  const correctedDecision = resolveDeepBranchNavigation({
    ...navigation,
    currentBranchId: detailDecision.branchId,
    session: {session_id: 's-1', branches: [{branch_id: 'branch-2'}]},
  });
  assert.deepEqual(correctedDecision, {
    branchId: 'branch-2',
    shouldPublish: true,
  });
});

test('browser navigation back to main waits for active branch state to catch up', () => {
  const detail = {
    session_id: 's-1',
    branches: [{branch_id: 'branch-2'}],
  };
  const pending = resolveDeepBranchNavigation({
    session: detail,
    currentBranchId: 'branch-2',
    requestedBranchId: 'main',
    preferredSessionId: 's-1',
  });
  assert.deepEqual(pending, {branchId: 'main', shouldPublish: false});
  assert.deepEqual(resolveDeepBranchNavigation({
    session: detail,
    currentBranchId: pending.branchId,
    requestedBranchId: 'main',
    preferredSessionId: 's-1',
  }), {branchId: 'main', shouldPublish: true});
});

test('an old session cannot overwrite a browser request for another session', () => {
  assert.deepEqual(resolveDeepBranchNavigation({
    session: {
      session_id: 's-old',
      branches: [{branch_id: 'branch-old'}],
    },
    currentBranchId: 'branch-old',
    requestedBranchId: 'main',
    preferredSessionId: 's-new',
  }), {
    branchId: 'branch-old',
    shouldPublish: false,
  });
});

test('history sessions never inherit launcher focus from another equipment', () => {
  assert.equal(resolveDeepTurnFocus(null, '装备 A 的 launcher focus'), '装备 A 的 launcher focus');
  assert.equal(resolveDeepTurnFocus({session_id: 's-b', context_refs: {}}, '装备 A 的 launcher focus'), '');
  assert.equal(resolveDeepTurnFocus({
    session_id: 's-b',
    context_refs: {focus: '装备 B 的持久化 focus'},
  }, '装备 A 的 launcher focus'), '装备 B 的持久化 focus');
});

test('plugin role and branch idempotency helpers follow API contracts', () => {
  assert.equal(resolveDeepRequestRole({}, 'admin'), 'admin');
  assert.equal(resolveDeepRequestRole({auth: {roles: ['analyst', 'admin']}}, 'analyst'), 'admin');
  assert.equal(resolveDeepRequestRole({auth: {role: 'reviewer'}}, 'admin'), 'reviewer');
  assert.equal(deepForkIdempotencyKey('s-1', 'm-1', []), 'fork:s-1:m-1:1');
  assert.equal(deepForkIdempotencyKey('s-1', 'm-1', [{branch_id: 'branch-1'}]), 'fork:s-1:m-1:2');
});

test('board candidate chips are recovered from prose labels', () => {
  const names = extractDeliberationCandidates('以下候选均保留最终物理毁伤。 · 候选：静默门槛突入弹群、拦截耗竭反转弹群');
  assert.deepEqual(names, ['静默门槛突入弹群', '拦截耗竭反转弹群']);
  const merged = mergeDeliberationProposals(
    ['静默门槛突入弹群'],
    '优先保留：脆弱窗口捕获型多点失能巡飞弹群、静默伴随占位式分散攻击弹群、拦截耗竭反转弹群',
  );
  assert.equal(merged[0], '静默门槛突入弹群');
  assert.ok(merged.includes('脆弱窗口捕获型多点失能巡飞弹群'));
});

test('prose-length proposal names are parsed into short chips', () => {
  const merged = mergeDeliberationProposals([
    '对抗裁决：本轮优先保留能够把时敏打击链前置到目标必经空间的候选。 · 优先保留：“砚锋”伏域断链器、廉耗锁域伏击器、寒汐收束猎杀网',
  ]);
  assert.deepEqual(merged, ['“砚锋”伏域断链器', '廉耗锁域伏击器', '寒汐收束猎杀网']);
  assert.equal(isShortCandidateName(merged[0]), true);
  assert.equal(isShortCandidateName('对抗裁决：本轮优先保留能够把时敏打击链前置到目标必经空间的候选。 · 优先保留：“砚锋”伏域断链器'), false);
});

test('board candidate click is a quoted follow-up, not a composer-only fill', () => {
  const prompt = directionFollowUp({name: '静默门槛突入弹群', winning_angle: '成本交换'});
  const formatted = formatQuotedDeepMessage(prompt, '静默门槛突入弹群');
  const parsed = parseQuotedDeepMessage(formatted);
  assert.equal(parsed.quotedContext, '静默门槛突入弹群');
  assert.match(parsed.content, /静默门槛突入弹群/);
  assert.match(parsed.content, /成本交换/);
});

test('direction follow-up drops paragraph-length angles', () => {
  const prompt = directionFollowUp({
    name: '“砚锋”伏域断链器',
    winning_angle: '把传统快速打击中的“侦察发现、指挥确认、火力响应”压缩为预置伏域内的自动物理断链',
  });
  assert.equal(prompt.includes('沿「'), false);
  assert.match(prompt, /砚锋/);
  assert.equal(shortDeepFocusAngle('成本交换', {name: '静默门槛突入弹群'}), '成本交换');
  assert.equal(shortDeepFocusAngle('成本交换', {name: '成本交换'}), '');
});

test('unique named values skip already owned candidates', () => {
  const seen = new Set(['寒汐收束猎杀网']);
  assert.deepEqual(
    uniqueNamedValues(['“砚锋”伏域断链器', '寒汐收束猎杀网', '“砚锋”伏域断链器'], seen),
    ['“砚锋”伏域断链器'],
  );
  assert.equal(seen.has('“砚锋”伏域断链器'), true);
});

test('anchored welcome does not stack 围绕 around another 围绕 prompt', () => {
  const anchored = anchorWelcomeSuggestion(
    '低换高耗攻击巡飞弹',
    '围绕成本交换与反适应韧性发散：提出低价换高代价、对手难按旧杀伤链计价的直接杀伤装备',
  );
  assert.match(anchored, /^围绕「低换高耗攻击巡飞弹」深度发散：成本交换/);
  assert.equal(anchored.includes('围绕围绕'), false);
  assert.equal(
    anchorWelcomeSuggestion('低换高耗攻击巡飞弹', '围绕「低换高耗攻击巡飞弹」继续闭合失能判据'),
    '围绕「低换高耗攻击巡飞弹」继续闭合失能判据',
  );
});
