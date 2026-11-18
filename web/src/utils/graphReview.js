const STATUS_LABELS = {
  pending: '待审核',
  accepted: '已接受',
  rejected: '已拒绝',
  disputed: '有争议',
  superseded: '已废弃'
}

const STATUS_COLORS = {
  pending: 'orange',
  accepted: 'green',
  rejected: 'red',
  disputed: 'gold',
  superseded: 'default'
}

export function graphReviewItemKey(item) {
  return `${item.target_type}-${item.target_id}`
}

export function graphReviewCandidateTitle(item) {
  return item.target_type === 'entity_mention'
    ? `${item.mention_text || item.standard_name} · ${item.entity_type}`
    : `${item.source_name} → ${item.relation_type} → ${item.target_name}`
}

export function graphReviewCandidateSubtitle(item) {
  return item.target_type === 'entity_mention'
    ? `标准名：${item.standard_name}`
    : `${item.claim_level || 'Inference'} · ${item.chunk_id}`
}

export function graphReviewConfidence(value) {
  return `${Math.round(Number(value || 0) * 100)}%`
}

export function graphReviewStatusLabel(status) {
  return STATUS_LABELS[status] || status
}

export function graphReviewStatusColor(status) {
  return STATUS_COLORS[status] || 'default'
}

export function buildEvidenceSegments(textValue, spansValue) {
  const text = String(textValue || '')
  if (!text) return []
  const spans = (spansValue || [])
    .filter(
      (span) =>
        Number.isInteger(span?.start) &&
        Number.isInteger(span?.end) &&
        span.start >= 0 &&
        span.end > span.start &&
        span.end <= text.length
    )
    .sort((left, right) => left.start - right.start)
  if (!spans.length) return [{ text, highlight: false }]

  const segments = []
  let cursor = 0
  for (const span of spans) {
    if (span.start < cursor) continue
    if (span.start > cursor)
      segments.push({ text: text.slice(cursor, span.start), highlight: false })
    segments.push({ text: text.slice(span.start, span.end), highlight: true })
    cursor = span.end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), highlight: false })
  return segments
}
