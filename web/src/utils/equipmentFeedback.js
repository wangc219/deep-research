/** 反馈记录按服务端时间展示，回滚和候选记忆不表示已验证生效。 */
export function sortFeedbackHistory(rows = []) {
  return [...rows].sort((left, right) => (
    (Date.parse(right.created_at || '') || 0) - (Date.parse(left.created_at || '') || 0) ||
    String(right.feedback_id || '').localeCompare(String(left.feedback_id || ''))
  ))
}

export function feedbackMatchesCapability(feedback, item) {
  if (!item) return true
  if (feedback.capability_version_id) return feedback.capability_version_id === (item.version_id || item.id)
  if (feedback.capability_id) return feedback.capability_id === item.capability_id
  if (feedback.hypothesis_id) return feedback.hypothesis_id === item.hypothesis_id
  return feedback.capability_name === (item.name || item.equipment_name || '')
}

export function feedbackLearningLabel(feedback) {
  if (feedback.status === 'rolled_back' || feedback.learning_status === 'rolled_back') return '已回滚'
  if (feedback.effect_status === 'effective') return '已验证有效'
  if (feedback.effect_status === 'validated') return '已验证，待效果评估'
  if (feedback.effect_status === 'ineffective') return '效果验证未通过'
  if (feedback.effect_status === 'inconclusive') return '效果待进一步确认'
  if (['superseded', 'withdrawn'].includes(feedback.effect_status)) return '已停用'
  if (feedback.learning_status === 'processed') return '已提炼，待验证'
  return '已记录，待提炼'
}

export function feedbackScoreDelta(feedback, dimension) {
  const model = feedbackScore(feedback.model_dimension_scores?.[dimension])
  const expert = feedbackScore(feedback.expert_dimension_scores?.[dimension])
  return model === null || expert === null ? null : expert - model
}

export function feedbackScore(value) {
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
    ? null : Math.round(Number(value) * 100)
}
