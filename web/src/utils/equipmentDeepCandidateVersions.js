import {
  capabilityComparisonFields,
  capabilityLineageKey,
  capabilityPortraitModules,
  capabilityTitle,
  normalizeCapability
} from './equipmentCapabilities.js'

const objectValue = (value) =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {}

const textValue = (...values) => {
  for (const value of values) {
    const normalized = String(value ?? '').trim()
    if (normalized) return normalized
  }
  return ''
}

const VERSION_STATUS_ALIASES = {
  accepted: 'verified',
  approved: 'verified',
  baseline: 'formal',
  pending: 'pending_verification',
  rollback: 'rolled_back',
  rolledback: 'rolled_back',
  unverified: 'pending_verification'
}

export const CANDIDATE_PORTRAIT_LABELS = [
  '概述',
  '装备与技术实现',
  '关键作战流程',
  '形成能力与作战效果',
  '制胜逻辑机理'
]

export const candidateVersionId = (item = {}) => {
  const snapshot = objectValue(item.snapshot)
  return textValue(item.version_id, item.id, snapshot.version_id, snapshot.id)
}

/**
 * PostgreSQL 原生深研版本把 session_id 放在 snapshot；旧工作台导入版本可能
 * 使用 source_session_id/deep_session_id，或把字段留在 metadata/structured_fields。
 */
export const candidateVersionSessionId = (item = {}) => {
  const snapshot = objectValue(item.snapshot)
  const payload = objectValue(item.payload)
  const metadata = objectValue(item.metadata)
  const snapshotMetadata = objectValue(snapshot.metadata)
  const structured = objectValue(snapshot.structured_fields || item.structured_fields)
  return textValue(
    item.session_id,
    item.source_session_id,
    item.deep_session_id,
    snapshot.session_id,
    snapshot.source_session_id,
    snapshot.deep_session_id,
    payload.session_id,
    payload.source_session_id,
    metadata.session_id,
    snapshotMetadata.session_id,
    structured.session_id,
    structured.source_session_id
  )
}

export const candidateVersionStatus = (item = {}) => {
  const snapshot = objectValue(item.snapshot)
  const raw = textValue(
    item.status,
    item.verification_status,
    item.version_status,
    snapshot.status,
    snapshot.verification_status
  ).toLowerCase()
  if (raw) return VERSION_STATUS_ALIASES[raw] || raw

  const id = candidateVersionId(item)
  const source = textValue(item.source, snapshot.source).toLowerCase()
  if (id.startsWith('baseline-') || ['formal_s6', 'baseline'].includes(source)) return 'formal'
  return 'pending_verification'
}

export const candidateVersionStatusLabel = (status) => {
  const normalized = candidateVersionStatus({ status })
  return {
    blocked: '已阻塞',
    cancelled: '已取消',
    deleted: '已隐藏',
    failed: '失败',
    formal: '正式基线',
    partial: '部分结果',
    pending_verification: '待核验',
    rejected: '已驳回',
    rolled_back: '已回滚',
    verified: '已核验'
  }[normalized] || normalized
}

export const normalizeCandidateVersion = (item = {}) => {
  const snapshot = objectValue(item.snapshot)
  const structured = objectValue(snapshot.structured_fields || item.structured_fields)
  const modules = objectValue(
    item.capability_portrait_modules ||
      snapshot.capability_portrait_modules ||
      structured.capability_portrait_modules
  )
  const draft = objectValue(
    item.capability_card_draft ||
      snapshot.capability_card_draft ||
      structured.capability_card_draft
  )
  const source = {
    ...structured,
    ...snapshot,
    ...item,
    capability_portrait_modules: modules,
    capability_card_draft: draft
  }
  const normalized = normalizeCapability(source)
  const evidenceRefs = [
    item.evidence_refs,
    item.evidence_ids,
    snapshot.evidence_refs,
    snapshot.evidence_ids,
    structured.evidence_refs
  ].find(Array.isArray) || []

  return {
    ...normalized,
    version_id: candidateVersionId(item),
    version_no:
      item.version_no ??
      item.version ??
      snapshot.version_no ??
      snapshot.version ??
      null,
    status: candidateVersionStatus(item),
    session_id: candidateVersionSessionId(item),
    created_at: textValue(item.created_at, snapshot.created_at),
    source: textValue(item.source, snapshot.source, 'equipment_deep_research_conversation'),
    evidence_refs: evidenceRefs.map((value) => String(value ?? '').trim()).filter(Boolean),
    snapshot
  }
}

export const candidatePortraitSlots = (item = {}) => {
  const byLabel = new Map(
    capabilityPortraitModules(item).map((entry) => [String(entry.label || '').trim(), entry.text])
  )
  return CANDIDATE_PORTRAIT_LABELS.map((label) => ({
    label,
    text: String(byLabel.get(label) || '').trim(),
    complete: Boolean(String(byLabel.get(label) || '').trim())
  }))
}

const versionTimestamp = (item = {}) => {
  const timestamp = Date.parse(String(item.created_at || ''))
  return Number.isFinite(timestamp) ? timestamp : 0
}

export const sessionCandidateVersions = (items, sessionId) => {
  const normalizedSessionId = String(sessionId || '').trim()
  if (!normalizedSessionId || !Array.isArray(items)) return []
  return items
    .map(normalizeCandidateVersion)
    .filter(
      (item) => item.session_id === normalizedSessionId && candidateVersionStatus(item) !== 'formal'
    )
    .sort(
      (left, right) =>
        versionTimestamp(right) - versionTimestamp(left) ||
        Number(right.version_no || 0) - Number(left.version_no || 0)
    )
}

const formalVersions = (items) =>
  (Array.isArray(items) ? items : [])
    .map(normalizeCandidateVersion)
    .filter((item) => candidateVersionStatus(item) === 'formal')

export const findCandidateFormalBaseline = (candidate = {}, items = []) => {
  const baselines = formalVersions(items)
  if (!baselines.length) return null

  const explicitBaseId = textValue(candidate.base_version_id, candidate.snapshot?.base_version_id)
  if (explicitBaseId) {
    const exactBase = baselines.find((item) => candidateVersionId(item) === explicitBaseId)
    if (exactBase) return exactBase
  }

  for (const field of ['hypothesis_id', 'card_binding_id', 'capability_id']) {
    const value = textValue(candidate[field], candidate.snapshot?.[field]).toLowerCase()
    if (!value) continue
    const match = baselines.find(
      (item) => textValue(item[field], item.snapshot?.[field]).toLowerCase() === value
    )
    if (match) return match
  }

  const lineage = capabilityLineageKey(candidate)
  const lineageMatch = baselines.find((item) => capabilityLineageKey(item) === lineage)
  if (lineageMatch) return lineageMatch

  const title = capabilityTitle(candidate).toLowerCase()
  return baselines.find((item) => capabilityTitle(item).toLowerCase() === title) || null
}

const comparableText = (value) =>
  String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()

export const candidateBaselineDiff = (candidate = {}, baseline = null) => {
  if (!baseline) return []
  return capabilityComparisonFields(baseline, candidate)
    .map(([label, before, after]) => ({
      label,
      before: comparableText(before) || '—',
      after: comparableText(after) || '—'
    }))
    .filter((entry) => entry.before !== entry.after)
}

export const buildSessionCandidateVersionCards = (items, sessionId) =>
  sessionCandidateVersions(items, sessionId).map((version) => {
    const baseline = findCandidateFormalBaseline(version, items)
    const modules = candidatePortraitSlots(version)
    return {
      id: candidateVersionId(version),
      version,
      baseline,
      modules,
      completedModules: modules.filter((item) => item.complete).length,
      diff: candidateBaselineDiff(version, baseline)
    }
  })
