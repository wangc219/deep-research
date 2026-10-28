import assert from 'node:assert/strict'
import test from 'node:test'
import { feedbackLearningLabel, feedbackMatchesCapability, feedbackScore, feedbackScoreDelta, sortFeedbackHistory } from '../../src/utils/equipmentFeedback.js'

test('最新反馈始终在前，摘要包含最近三条而不是最旧三条', () => {
  const rows = [1, 5, 2, 4, 3].map((number) => ({ feedback_id: `f${number}`, created_at: `2026-10-26T00:00:0${number}Z` }))
  assert.deepEqual(sortFeedbackHistory(rows).slice(0, 3).map((row) => row.feedback_id), ['f5', 'f4', 'f3'])
  assert.equal(rows[0].feedback_id, 'f1')
})

test('同名画像和跨版本记录不会错误关联，兼容旧记录标识', () => {
  const card = { name: '画像', capability_id: 'cap-a', version_id: 'v2', hypothesis_id: 'h-a' }
  assert.equal(feedbackMatchesCapability({ capability_version_id: 'v1', capability_id: 'cap-a' }, card), false)
  assert.equal(feedbackMatchesCapability({ capability_id: 'cap-b', capability_name: '画像' }, card), false)
  assert.equal(feedbackMatchesCapability({ capability_name: '画像' }, card), true)
  assert.equal(feedbackMatchesCapability({ capability_version_id: 'v2' }, card), true)
  assert.equal(feedbackMatchesCapability({ capability_version_id: 'v2' }, { id: 'v2', capability_id: 'cap-a' }), true)
})

test('提炼候选与验证生效分开，回滚记录优先显示', () => {
  assert.equal(feedbackLearningLabel({ learning_status: 'processed', effect_status: 'pending_validation' }), '已提炼，待验证')
  assert.equal(feedbackLearningLabel({ effect_status: 'effective' }), '已验证有效')
  assert.equal(feedbackLearningLabel({ status: 'rolled_back', effect_status: 'effective' }), '已回滚')
  assert.equal(feedbackLearningLabel({}), '已记录，待提炼')
})

test('缺失评分不能显示成零分，零分与正负校准差异保留', () => {
  for (const value of [null, undefined, '', 'bad']) assert.equal(feedbackScore(value), null)
  assert.equal(feedbackScore(0), 0)
  assert.equal(feedbackScoreDelta({ expert_dimension_scores: { innovation: 0.8 }, model_dimension_scores: { innovation: 0.6 } }, 'innovation'), 20)
  assert.equal(feedbackScoreDelta({ expert_dimension_scores: { innovation: 0 } }, 'innovation'), null)
})
