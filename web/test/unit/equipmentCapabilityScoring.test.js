import assert from 'node:assert/strict'
import test from 'node:test'

import {
  S5_SCORE_DIMENSIONS,
  capabilityS5Scorecard,
  emptyS5ScoreInput
} from '../../src/utils/equipmentCapabilityScoring.js'

test('S5 反馈使用领域真实五维口径与 30/30/20/10/10 权重', () => {
  assert.deepEqual(
    S5_SCORE_DIMENSIONS.map(({ key, label, weight }) => [key, label, weight]),
    [
      ['innovation', '创新性', 30],
      ['demand', '需求性', 30],
      ['feasibility', '科学可行性', 20],
      ['effectiveness', '效能性', 10],
      ['development', '发展性', 10]
    ]
  )
  assert.ok(S5_SCORE_DIMENSIONS.every(({ principle }) => principle.length > 30))
})

test('能力卡 S5 分数支持 0-1 与百分制并重新计算综合分', () => {
  const scorecard = capabilityS5Scorecard({
    s5_dimension_scores: {
      innovation: 80.4,
      demand: 0.82,
      feasibility: 0.74,
      effectiveness: 0.77,
      development: 0.76
    }
  })

  assert.equal(scorecard.complete, true)
  assert.equal(Math.round(scorecard.weightedScore * 10000) / 10000, 0.7882)
})

test('缺失评分不会被空字符串错误计算成 0 分', () => {
  assert.equal(capabilityS5Scorecard({}).weightedScore, null)
  assert.deepEqual(Object.values(emptyS5ScoreInput()), ['', '', '', '', ''])
})
