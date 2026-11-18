import assert from 'node:assert/strict'
import test from 'node:test'

import {
  mergeAiDraftMaps,
  parseAiDraftJsonl,
  prepareAiDraftForAssignment
} from '../../src/utils/annotationDraftImport.js'

const makeDraft = (overrides = {}) => ({
  contract_version: 'defense-kg-ai-draft-v1',
  document_id: 'doc-1',
  split: 'train',
  language: 'zh',
  source_type: 'paper',
  domain: 'air-defense',
  draft_provenance: {
    annotation_kind: 'ai_prelabel',
    formal_gold_eligible: false,
    human_confirmed: false,
    intended_human_reviewer: 'pilotbiaozhuyuana'
  },
  blocks: [{ block_id: 'block-1', text: '相控阵雷达提升探测能力', page: 3 }],
  entities: [
    {
      entity_id: 'entity-1',
      block_id: 'block-1',
      type: 'KeyTechnology',
      text: '相控阵雷达',
      start: 0,
      end: 5,
      canonical_entity_id: null
    }
  ],
  relations: [
    {
      relation_id: 'relation-1',
      type: 'ENABLES_CAPABILITY',
      source_entity_id: 'entity-1',
      target_entity_id: 'entity-1',
      evidence_block_ids: ['block-1'],
      evidence_spans: [{ block_id: 'block-1', start: 0, end: 11, text: '相控阵雷达提升探测能力' }],
      applicable_conditions: ['测试条件'],
      claim_level: 'Fact'
    }
  ],
  ...overrides
})

const makeAssignment = (overrides = {}) => ({
  role: 'annotator',
  document_id: 'doc-1',
  split: 'train',
  language: 'zh',
  source_type: 'paper',
  domain: 'air-defense',
  blocks: [{ block_id: 'block-1', text: '相控阵雷达提升探测能力', page: 3 }],
  ...overrides
})

test('解析符合安全谱系约束的 AI JSONL 候选', () => {
  const parsed = parseAiDraftJsonl(`${JSON.stringify(makeDraft())}\n`)
  assert.equal(parsed.size, 1)
  assert.equal(parsed.get('doc-1').draft_provenance.annotation_kind, 'ai_prelabel')
})

test('拒绝可冒充 Gold 或真人确认结果的 AI 候选', () => {
  const draft = makeDraft({
    draft_provenance: {
      ...makeDraft().draft_provenance,
      formal_gold_eligible: true
    }
  })
  assert.throws(() => parseAiDraftJsonl(JSON.stringify(draft)), /不可冒充真人提交/)
})

test('拒绝单文件和多文件中的重复 document_id', () => {
  const line = JSON.stringify(makeDraft())
  assert.throws(() => parseAiDraftJsonl(`${line}\n${line}`), /导入文件中重复/)

  const first = parseAiDraftJsonl(line)
  const second = parseAiDraftJsonl(line)
  assert.throws(() => mergeAiDraftMaps(first, second), /多个导入文件中重复/)
})

test('拒绝将 A 侧候选加载给其他账号或仲裁专家', () => {
  assert.throws(
    () => prepareAiDraftForAssignment(makeDraft(), makeAssignment(), 'pilotbiaozhuyuanb'),
    /不属于当前登录账号/
  )
  assert.throws(
    () =>
      prepareAiDraftForAssignment(
        makeDraft(),
        makeAssignment({ role: 'arbitrator' }),
        'pilotbiaozhuyuana'
      ),
    /只能加载到独立标注员编辑器/
  )
})

test('拒绝与 PostgreSQL 权威 Block 文本、顺序或页码不一致的候选', () => {
  const mismatch = makeAssignment({
    blocks: [{ block_id: 'block-1', text: '已被修改的文本', page: 3 }]
  })
  assert.throws(
    () => prepareAiDraftForAssignment(makeDraft(), mismatch, 'pilotbiaozhuyuana'),
    /权威 Block 不完全一致/
  )
})

test('匹配本人任务时只返回可编辑实体与关系候选', () => {
  const result = prepareAiDraftForAssignment(
    makeDraft(),
    makeAssignment(),
    'pilotbiaozhuyuana'
  )
  assert.equal(result.entities[0].text, '相控阵雷达')
  assert.equal(result.relations[0].claim_level, 'Fact')
  assert.deepEqual(result.relations[0].applicable_conditions, ['测试条件'])
  assert.equal('draft_provenance' in result, false)
})
