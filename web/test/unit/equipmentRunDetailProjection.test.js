import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildEvidenceProjection,
  buildInteractionProjection,
  buildWinningProjection,
  mergeInteractionProjection,
  normalizeRunEvents,
  resolveWinningSwarm
} from '../../src/views/equipment/run_detail_projection.js'

const platformRows = [
  {
    run_id: 'run-new',
    sequence: 1,
    event_type: 'run_started',
    payload: {
      actor: 'orchestrator',
      event_id: 'trace-start',
      event_type: 'run_started',
      summary: '研究启动',
      payload: { agent_ids: ['combat_scenario'] }
    }
  },
  {
    run_id: 'run-new',
    sequence: 2,
    event_type: 'winning_mission_graph_planned',
    payload: {
      type: 'TraceEvent',
      payload: {
        actor: 'winning_swarm_controller',
        event_id: 'trace-graph',
        event_type: 'winning_mission_graph_planned',
        summary: '动态图完成',
        payload: {
          graph: {
            agent_instances: [
              {
                instance_id: 'winning-agent-1',
                display_name: '对手体系建模',
                mission_node: 'S1',
                wave: 1,
                status: 'planned'
              }
            ]
          }
        }
      }
    }
  },
  {
    run_id: 'run-new',
    sequence: 3,
    event_type: 'winning_agent_session_completed',
    payload: {
      actor: 'winning-agent-1',
      event_type: 'winning_agent_session_completed',
      summary: '独立会话完成',
      payload: {
        agent_instance_id: 'winning-agent-1',
        display_name: '对手体系建模',
        mission_node: 'S1',
        wave: 1
      }
    }
  },
  {
    run_id: 'run-new',
    sequence: 4,
    event_type: 'winning_reasoning_step_completed',
    payload: {
      actor: 'winning_mechanism',
      event_id: 'reason-1',
      event_type: 'winning_reasoning_step_completed',
      summary: '识别对手体系依赖',
      output_refs: ['ev-a'],
      payload: { step: 1, confidence: 0.72, evidence_ids: ['ev-a'] }
    }
  }
]

test('平台事件的多层 envelope 会被解包为 React 交互结构', () => {
  const events = normalizeRunEvents(platformRows)
  assert.equal(events[1].event_type, 'winning_mission_graph_planned')
  assert.equal(events[1].details.graph.agent_instances[0].instance_id, 'winning-agent-1')

  const projection = buildInteractionProjection(platformRows, {
    run_id: 'run-new',
    status: 'researching',
    topic: '测试研究'
  })
  assert.equal(projection.workflow.swarm_cluster.members.length, 1)
  assert.equal(projection.workflow.swarm_cluster.members[0].status, 'completed')
  assert.equal(projection.workflow.step_plan[0].status, 'completed')
  assert.equal(projection.counts.events, 4)
})

test('旧版 interactions 优先，同时保留平台 fallback 的缺省字段', () => {
  const fallback = buildInteractionProjection(platformRows, { run_id: 'run-new' })
  const merged = mergeInteractionProjection(
    {
      run_id: 'run-old',
      events: [
        {
          event_id: 'legacy-event',
          event_type: 'savepoint',
          actor: 'orchestrator',
          summary: '保存点',
          details: { checkpoint_id: 'cp-1' }
        }
      ],
      counts: { events: 1, savepoints: 1 },
      workflow: { status: 'completed' }
    },
    fallback
  )
  assert.equal(merged.run_id, 'run-old')
  const savedEvent = merged.events.find((event) => event.event_id === 'legacy-event')
  assert.equal(savedEvent.actor, 'orchestrator')
  assert.equal(savedEvent.details.checkpoint_id, 'cp-1')
  assert.equal(merged.counts.savepoints, 1)
  assert.ok(merged.workflow.swarm_cluster)
  assert.equal(merged.events.length, 5)
  assert.equal(merged.counts.visible_events, 5)
})

test('旧交互快照不会遮住新事件，相同事件优先保留旧产物详情', () => {
  const fallback = buildInteractionProjection(platformRows, { run_id: 'run-new' })
  const merged = mergeInteractionProjection({
    events: [{
      event_id: 'trace-start',
      sequence: 1,
      event_type: 'run_started',
      actor: 'orchestrator',
      summary: '旧版完整记录',
      details: { checkpoint_id: 'cp-1' }
    }],
    counts: { events: 1 }
  }, fallback)
  assert.equal(merged.events.length, 4)
  assert.equal(merged.events[0].summary, '旧版完整记录')
  assert.equal(merged.events.at(-1).event_type, 'winning_reasoning_step_completed')
  assert.equal(merged.counts.events, 4)
})

test('权威证据卡不会被较晚的事件引用覆盖', () => {
  const rows = buildEvidenceProjection([{ evidence_id: 'ev-a', claim: '证据卡原文', created_by: 'researcher' }], [
    { event_type: 'winning_reasoning_step_completed', summary: '事件摘要', created_at: 'later', actor: 'agent', details: { evidence_ids: ['ev-a'] }, output_refs: [] }
  ])
  assert.equal(rows[0].claim, '证据卡原文')
  assert.equal(rows[0].created_by, 'researcher')
})

test('研究尚未进入制胜阶段时不展示虚构的 S1–S6 输入包', () => {
  const events = normalizeRunEvents(platformRows.slice(0, 1))
  const winning = buildWinningProjection(null, events, { topic: '测试研究' })
  assert.deepEqual(winning.inputs, [])
})

test('证据和 S1–S6 结果可从平台事件回放，旧导入数据不会变成空页', () => {
  const events = normalizeRunEvents(platformRows)
  const evidence = buildEvidenceProjection([], events)
  assert.equal(evidence[0].evidence_id, 'ev-a')

  const interactions = buildInteractionProjection(platformRows, { run_id: 'run-new' })
  const winning = buildWinningProjection(null, events, {
    run_id: 'run-new',
    topic: '复杂电磁环境装备需求',
    research_route: 'auto',
    max_rounds: 2
  }, interactions)
  assert.equal(winning.inputs[0].problem_frame.objective, '复杂电磁环境装备需求')
  assert.equal(winning.reasoning_nodes[0].step, 1)
  assert.equal(winning.reasoning_nodes[0].summary, '识别对手体系依赖')
})

test('S1–S6 聚合同时保留交互 Agent 状态和产物中的最终候选', () => {
  const resolved = resolveWinningSwarm(
    {
      swarm: {
        final_merge: { passed: true, finalist_count: 3 },
        final_equipment_portfolio: [
          { name: '候选一' },
          { name: '候选二' },
          { name: '候选三' }
        ]
      }
    },
    {
      workflow: {
        swarm_cluster: {
          members: [{ agent_instance_id: 'winning-agent-1', status: 'completed' }],
          candidate_lineage: [{ hypothesis_id: 'hypothesis-1' }],
          final_equipment_portfolio: []
        }
      }
    }
  )

  assert.equal(resolved.members.length, 1)
  assert.equal(resolved.candidate_lineage.length, 1)
  assert.equal(resolved.final_equipment_portfolio.length, 3)
  assert.equal(resolved.final_merge.passed, true)
})
