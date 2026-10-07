import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  capabilityVersionsForDeepSession,
  collectDeepToolCalls,
  projectEquipmentDeepStage
} from '../../src/utils/equipmentDeepStageProjection.js'

test('深研阶段投影以会话为研究边界且空状态不伪造候选成果', () => {
  const projection = projectEquipmentDeepStage({
    session: { session_id: 'session-a', topic: '低空防御', payload: { focus: '成本交换' } }
  })

  assert.equal(projection.stages[0].status, 'completed')
  assert.equal(projection.stages[1].status, 'idle')
  assert.equal(projection.candidates.length, 0)
  assert.equal(projection.hasDetails, false)
  assert.equal(projection.memory.objective, '成本交换')
})

test('从公开结构化消息恢复候选、裁决、假设与未决问题', () => {
  const conversations = [
    {
      messages: [
        {
          type: 'ai',
          content: '已完成方向汇总。',
          extra_metadata: {
            research_frontier: [
              {
                direction: '分布式诱饵云',
                why_promising: '迫使对手提高识别成本',
                next_probe: '验证抗风偏能力'
              }
            ],
            adjudication: {
              candidate_reviews: [
                { candidate_name: '分布式诱饵云', verdict: 'accept', reason: '成本交换显著' },
                { candidate_name: '单平台强干扰', verdict: 'reject', reason: '生存性不足' }
              ]
            },
            assumption_ledger: [{ assumption: '对手依赖单模态识别' }],
            open_questions: ['复杂气象下的散布误差']
          }
        }
      ]
    }
  ]
  const projection = projectEquipmentDeepStage({
    session: { session_id: 'session-a', payload: {} },
    conversations
  })

  assert.deepEqual(
    projection.candidates.map((item) => item.name),
    ['分布式诱饵云', '单平台强干扰']
  )
  assert.deepEqual(
    projection.decisions.map((item) => item.name),
    ['分布式诱饵云']
  )
  assert.deepEqual(
    projection.rejected.map((item) => item.name),
    ['单平台强干扰']
  )
  assert.deepEqual(projection.memory.assumptions, ['对手依赖单模态识别'])
  assert.deepEqual(projection.memory.openQuestions, ['复杂气象下的散布误差'])
  assert.equal(
    projection.stages.find((item) => item.key === 'council_critique').status,
    'completed'
  )
})

test('成卡工具运行与会话版本分别映射为进行中和已完成', () => {
  const conversations = [
    {
      messages: [
        {
          type: 'human',
          content: '/card 分布式诱饵云'
        },
        {
          type: 'ai',
          tool_calls: [
            {
              name: 'save_equipment_capability_draft',
              args: '{"name":"分布式诱饵云"}',
              status: 'running'
            }
          ]
        }
      ]
    }
  ]
  const calls = collectDeepToolCalls(conversations)
  assert.equal(calls[0].arguments.name, '分布式诱饵云')

  const running = projectEquipmentDeepStage({
    session: { session_id: 'session-a', payload: {} },
    conversations,
    processing: true,
    createArtifact: true
  })
  assert.equal(running.stages.at(-1).status, 'running')

  const completed = projectEquipmentDeepStage({
    session: { session_id: 'session-a', payload: {} },
    conversations,
    versions: [
      { version_id: 'v-a', snapshot: { session_id: 'session-a' } },
      { version_id: 'v-b', session_id: 'session-b' }
    ]
  })
  assert.equal(completed.stages.at(-1).status, 'completed')
  assert.deepEqual(
    capabilityVersionsForDeepSession(
      completed
        ? [
            { version_id: 'v-a', snapshot: { session_id: 'session-a' } },
            { version_id: 'v-b', session_id: 'session-b' }
          ]
        : [],
      'session-a'
    ).map((item) => item.version_id),
    ['v-a']
  )
})

test('Subagent 公开任务投影交接状态且组件提供候选成卡事件', () => {
  const projection = projectEquipmentDeepStage({
    session: { session_id: 'session-a', payload: {} },
    processing: true,
    subagentRuns: [
      {
        run_id: 'child-1',
        subagent_slug: 'fact-checker',
        description: '核验候选方向的反制边界',
        status: 'running'
      }
    ]
  })
  assert.equal(projection.handoffs[0].statusLabel, '进行中')
  assert.equal(projection.stages.find((item) => item.key === 'council_critique').status, 'running')

  const component = readFileSync(
    new URL('../../src/components/equipment/EquipmentDeepStageProjection.vue', import.meta.url),
    'utf8'
  )
  assert.match(component, /defineEmits\(\['focus-direction', 'author-card'\]\)/)
  assert.match(component, /projection\.title/)
  assert.match(component, /Agent 交接/)
  assert.match(component, /决策记忆/)
})

test('阶段投影优先展示本轮显式选择的 Skill，并允许显式清空', () => {
  const session = {
    session_id: 'session-skills',
    payload: { active_skill_ids: ['session-default'] }
  }

  const selected = projectEquipmentDeepStage({
    session,
    activeSkillIds: ['current-a', 'current-b']
  })
  assert.deepEqual(selected.memory.activeSkillIds, ['current-a', 'current-b'])

  const cleared = projectEquipmentDeepStage({ session, activeSkillIds: [] })
  assert.deepEqual(cleared.memory.activeSkillIds, [])

  const fallback = projectEquipmentDeepStage({ session })
  assert.deepEqual(fallback.memory.activeSkillIds, ['session-default'])
})

test('栏目深化使用业务适配环节且已有分析不误报为异常', () => {
  const projection = projectEquipmentDeepStage({
    session: { session_id: 'session-section', payload: { focus: '技术实现深挖' } },
    researchMode: 'section_deepen',
    researchSection: '装备与技术实现',
    conversations: [
      {
        messages: [
          {
            type: 'ai',
            content:
              '已拆解材料与算法技术卡点和工程瓶颈，提出攻关方案；同时推演作战流程、任务链与协同接口，并从成本交换和体系增益深化制胜逻辑。'
          }
        ]
      }
    ]
  })

  assert.equal(projection.title, '栏目深化')
  assert.deepEqual(
    projection.stages.map((item) => item.label),
    ['栏目基线', '技术攻关', '流程推演', '机理深化', '修订建议']
  )
  assert.equal(projection.stages[0].status, 'completed')
  assert.equal(projection.stages[1].status, 'observed')
  assert.equal(projection.stages[2].status, 'observed')
  assert.equal(projection.stages[3].status, 'observed')
  assert.notEqual(projection.stages[3].status, 'failed')
})

test('阶段组件说明环节可非线性推进并区分已有分析', () => {
  const component = readFileSync(
    new URL('../../src/components/equipment/EquipmentDeepStageProjection.vue', import.meta.url),
    'utf8'
  )
  assert.match(component, /可非线性推进/)
  assert.match(component, /status === 'observed'/)
  assert.match(component, /同装备深化方案/)
  assert.match(component, /const collapsed = ref\(true\)/)
})

test('新质发散正文已有复核或深化时显示待结构化而非空闲异常', () => {
  const projection = projectEquipmentDeepStage({
    session: { session_id: 'session-diverge', payload: {} },
    researchMode: 'new_weapon_diverge',
    conversations: [
      {
        messages: [
          {
            type: 'ai',
            content: '已完成交叉复核并分析失效边界，推荐继续方向深化，闭合作用机理与任务失能判据。'
          }
        ]
      }
    ]
  })

  assert.equal(projection.stages.find((item) => item.key === 'council_critique').status, 'observed')
  assert.equal(projection.stages.find((item) => item.key === 's4_mapping').status, 'observed')
})
