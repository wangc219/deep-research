import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  buildEvidenceSegments,
  graphReviewCandidateTitle,
  graphReviewConfidence
} from '../../src/utils/graphReview.js'

const workbenchSource = await readFile(
  new URL('../../src/components/knowledge/GraphReviewWorkbench.vue', import.meta.url),
  'utf8'
)
const conflictPanelSource = await readFile(
  new URL('../../src/components/knowledge/GraphConflictPanel.vue', import.meta.url),
  'utf8'
)
const graphApiSource = await readFile(
  new URL('../../src/apis/graph_api.js', import.meta.url),
  'utf8'
)

test('审核证据按 exclusive-end Span 回切并忽略重叠与非法区间', () => {
  const text = '相控阵雷达提升探测能力'
  const segments = buildEvidenceSegments(text, [
    { start: 0, end: 5 },
    { start: 2, end: 6 },
    { start: 7, end: 11 },
    { start: -1, end: 2 },
    { start: 0, end: 999 }
  ])

  assert.deepEqual(segments, [
    { text: '相控阵雷达', highlight: true },
    { text: '提升', highlight: false },
    { text: '探测能力', highlight: true }
  ])
})

test('审核候选标题与置信度保持实体和关系语义', () => {
  assert.equal(
    graphReviewCandidateTitle({
      target_type: 'entity_mention',
      mention_text: '相控阵雷达',
      standard_name: '相控阵雷达',
      entity_type: 'KeyTechnology'
    }),
    '相控阵雷达 · KeyTechnology'
  )
  assert.equal(
    graphReviewCandidateTitle({
      target_type: 'relation_mention',
      source_name: '相控阵雷达',
      relation_type: 'ENABLES_CAPABILITY',
      target_name: '探测能力'
    }),
    '相控阵雷达 → ENABLES_CAPABILITY → 探测能力'
  )
  assert.equal(graphReviewConfidence(0.923), '92%')
})

test('审核工作台展示歧义实体对齐候选且明确不自动合并', () => {
  assert.match(workbenchSource, /实体对齐候选/)
  assert.match(workbenchSource, /歧义候选不会自动合并/)
  assert.match(workbenchSource, /selectedItem\.alignment\.candidates/)
})

test('关系审核显式展示适用条件、推理依据和不确定性', () => {
  assert.match(workbenchSource, /关系适用条件与推理边界/)
  assert.match(workbenchSource, /selectedItem\.applicable_conditions/)
  assert.match(workbenchSource, /selectedItem\.reasoning_basis/)
  assert.match(workbenchSource, /selectedItem\.uncertainty/)
})

test('审核工作台集成独立冲突队列并要求填写裁决结论', () => {
  assert.match(workbenchSource, /GraphConflictPanel/)
  assert.match(workbenchSource, /冲突治理/)
  assert.match(conflictPanelSource, /知识冲突治理/)
  assert.match(conflictPanelSource, /请先填写裁决结论/)
  assert.match(conflictPanelSource, /resolveConflict/)
  assert.match(conflictPanelSource, /immediate: true/)
})

test('图谱 API 客户端封装冲突治理和阶段运行查询', () => {
  assert.match(graphApiSource, /getConflicts/)
  assert.match(graphApiSource, /registerConflict/)
  assert.match(graphApiSource, /resolveConflict/)
  assert.match(graphApiSource, /getBuildRuns/)
  assert.match(graphApiSource, /getBuildRun/)
})
