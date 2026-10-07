const text = (value) => String(value ?? '').trim()

const hasOwn = (value, key) =>
  Boolean(value && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, key))

const parseJson = (value) => {
  if (typeof value !== 'string') return value
  const source = value.trim()
  if (!source || (!source.startsWith('{') && !source.startsWith('['))) return value
  try {
    return JSON.parse(source)
  } catch {
    return value
  }
}

const objectValue = (value) => {
  const parsed = parseJson(value)
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
}

const arrayValue = (value) => {
  const parsed = parseJson(value)
  if (Array.isArray(parsed)) return parsed
  if (parsed === undefined || parsed === null || parsed === '') return []
  return [parsed]
}

const populatedText = (...values) => {
  for (const value of values) {
    const normalized = text(value)
    if (normalized) return normalized
  }
  return ''
}

const numberValue = (...values) => {
  for (const value of values) {
    if (value === '' || value === null || value === undefined) continue
    const normalized = Number(value)
    if (Number.isFinite(normalized)) return normalized
  }
  return null
}

const flattenedPayload = (row) => {
  const payload = objectValue(row?.payload)
  return {
    ...objectValue(payload.legacy_payload),
    ...objectValue(payload.payload_json),
    ...payload
  }
}

const uniqueValues = (values) => {
  const seen = new Set()
  const rows = []
  for (const value of values) {
    let key
    try {
      key = typeof value === 'string' ? `string:${value}` : `json:${JSON.stringify(value)}`
    } catch {
      key = `string:${String(value)}`
    }
    if (seen.has(key)) continue
    seen.add(key)
    rows.push(value)
  }
  return rows
}

const collectedArrays = (row, payload, names) =>
  uniqueValues(
    names.flatMap((name) => [row?.[name], payload?.[name]]).flatMap((value) => arrayValue(value))
  )

const collectedObjects = (values) => Object.assign({}, ...values.map(objectValue))

const messageMetadata = (row, payload) => {
  const candidates = [payload.metadata_json, payload.metadata, row?.metadata_json, row?.metadata]
  const hasExplicitMetadata = ['metadata', 'metadata_json'].some(
    (key) => hasOwn(row, key) || hasOwn(payload, key)
  )
  const metadata = collectedObjects(candidates)
  // The first PostgreSQL importer stored the legacy metadata object directly
  // in EquipmentDeepMessage.payload. Preserve that shape when no wrapper is
  // present, while newer imports keep their explicit metadata field intact.
  if (!hasExplicitMetadata) return payload
  if (Object.keys(metadata).length) return metadata

  // A malformed early metadata_json value must remain inspectable instead of
  // disappearing merely because it cannot be decoded into an object.
  for (const candidate of [...candidates].reverse()) {
    if (candidate === undefined || candidate === null || candidate === '') continue
    return parseJson(candidate)
  }
  return {}
}

const checkpointValue = (...values) => {
  const merged = collectedObjects(values)
  if (Object.keys(merged).length) return merged
  for (const candidate of values) {
    if (candidate === undefined || candidate === null || candidate === '') continue
    return parseJson(candidate)
  }
  return {}
}

const timestamp = (value) => {
  const parsed = Date.parse(value || '')
  return Number.isFinite(parsed) ? parsed : 0
}

const chronological = (left, right) => {
  if (left.sequence !== null && right.sequence !== null && left.sequence !== right.sequence) {
    return left.sequence - right.sequence
  }
  const timeDelta = timestamp(left.createdAt) - timestamp(right.createdAt)
  if (timeDelta) return timeDelta
  return left.sourceIndex - right.sourceIndex
}

const newestFirst = (left, right) => {
  const timeDelta =
    timestamp(right.updatedAt || right.createdAt) - timestamp(left.updatedAt || left.createdAt)
  return timeDelta || right.sourceIndex - left.sourceIndex
}

export const legacyDeepStatusLabel = (status) =>
  ({
    active: '可继续',
    queued: '待处理',
    pending: '待处理',
    running: '进行中',
    researching: '研究中',
    completed: '已完成',
    partial: '部分完成',
    failed: '失败',
    blocked: '已阻塞',
    cancelled: '已取消',
    canceled: '已取消',
    rejected: '已驳回',
    archived: '已归档'
  })[text(status).toLowerCase()] ||
  text(status) ||
  '未知状态'

export const legacyDeepStatusTone = (status) => {
  const value = text(status).toLowerCase()
  if (['completed', 'verified', 'accepted'].includes(value)) return 'success'
  if (['running', 'researching', 'active'].includes(value)) return 'active'
  if (['queued', 'pending', 'partial'].includes(value)) return 'pending'
  if (['failed', 'blocked', 'rejected'].includes(value)) return 'danger'
  if (['cancelled', 'canceled', 'archived'].includes(value)) return 'muted'
  return 'neutral'
}

export const legacyDeepRoleLabel = (role) =>
  ({
    user: '你',
    human: '你',
    assistant: '研究助手',
    ai: '研究助手',
    system: '系统',
    tool: '工具'
  })[text(role).toLowerCase()] ||
  text(role) ||
  '消息'

export const normalizeLegacyDeepMessage = (row = {}, sourceIndex = 0) => {
  const payload = flattenedPayload(row)
  const metadata = messageMetadata(row, payload)
  const status = populatedText(row.status, payload.status, 'completed').toLowerCase()
  const role = populatedText(row.role, payload.role, 'assistant').toLowerCase()
  return {
    id: populatedText(row.message_id, row.id, payload.message_id, `legacy-message-${sourceIndex}`),
    sequence: numberValue(row.sequence, payload.sequence),
    sourceIndex,
    role,
    roleLabel: legacyDeepRoleLabel(role),
    content: populatedText(row.content, payload.content),
    status,
    statusLabel: legacyDeepStatusLabel(status),
    statusTone: legacyDeepStatusTone(status),
    createdAt: populatedText(row.created_at, payload.created_at),
    parentMessageId: populatedText(row.parent_message_id, payload.parent_message_id),
    branchId: populatedText(row.branch_id, payload.branch_id, 'main'),
    turnId: populatedText(row.turn_id, payload.turn_id),
    messageKind: populatedText(row.message_kind, payload.message_kind, 'message'),
    artifactRefs: collectedArrays(row, payload, ['artifact_refs', 'artifact_refs_json']),
    versionRefs: collectedArrays(row, payload, ['version_refs', 'version_refs_json']),
    metadata,
    error: populatedText(
      row.error,
      payload.error,
      metadata.error,
      metadata.error_message,
      metadata.detail
    ),
    payload
  }
}

export const normalizeLegacyDeepJob = (row = {}, sourceIndex = 0) => {
  const payload = flattenedPayload(row)
  const checkpoint = checkpointValue(
    payload.checkpoint_json,
    payload.checkpoint,
    row.checkpoint_json,
    row.checkpoint
  )
  const status = populatedText(row.status, payload.status, 'queued').toLowerCase()
  return {
    id: populatedText(row.job_id, row.id, payload.job_id, `legacy-job-${sourceIndex}`),
    sourceIndex,
    status,
    statusLabel: legacyDeepStatusLabel(status),
    statusTone: legacyDeepStatusTone(status),
    stage: populatedText(row.stage, payload.stage),
    kind: populatedText(row.kind, payload.kind),
    branchId: populatedText(row.branch_id, payload.branch_id, 'main'),
    parentJobId: populatedText(row.parent_job_id, payload.parent_job_id),
    childRunId: populatedText(row.child_run_id, payload.child_run_id),
    rootMessageId: populatedText(row.root_message_id, payload.root_message_id),
    modelSpec: populatedText(row.model_spec, payload.model_spec),
    stateVersion: numberValue(row.state_version, payload.state_version),
    createdAt: populatedText(row.created_at, payload.created_at),
    updatedAt: populatedText(
      row.updated_at,
      payload.updated_at,
      row.created_at,
      payload.created_at
    ),
    checkpoint,
    error: populatedText(row.error, payload.error, checkpoint?.error, checkpoint?.error_message),
    payload
  }
}

export const normalizeLegacyDeepBranch = (row = {}, sourceIndex = 0) => {
  const payload = flattenedPayload(row)
  const status = populatedText(row.status, payload.status, 'active').toLowerCase()
  const id = populatedText(row.branch_id, row.id, payload.branch_id, `legacy-branch-${sourceIndex}`)
  return {
    id,
    sourceIndex,
    title: populatedText(row.title, payload.title, id === 'main' ? '主线' : '探索分支'),
    status,
    statusLabel: legacyDeepStatusLabel(status),
    statusTone: legacyDeepStatusTone(status),
    parentBranchId: populatedText(row.parent_branch_id, payload.parent_branch_id),
    forkedFromMessageId: populatedText(
      row.forked_from_message_id,
      row.from_message_id,
      payload.forked_from_message_id,
      payload.from_message_id
    ),
    childSessionId: populatedText(row.child_session_id, payload.child_session_id),
    createdAt: populatedText(row.created_at, payload.created_at),
    updatedAt: populatedText(
      row.updated_at,
      payload.updated_at,
      row.created_at,
      payload.created_at
    ),
    payload
  }
}

export const projectLegacyDeepSession = (session) => {
  if (!session || typeof session !== 'object') {
    return {
      id: '',
      title: '',
      status: '',
      statusLabel: '',
      statusTone: 'neutral',
      archived: false,
      messages: [],
      jobs: [],
      branches: []
    }
  }

  const payload = objectValue(session.payload)
  const status = populatedText(session.status, payload.status, 'active').toLowerCase()
  const messageRows = Array.isArray(session.messages)
    ? session.messages
    : Array.isArray(payload.messages)
      ? payload.messages
      : []
  const jobRows = Array.isArray(session.jobs)
    ? session.jobs
    : Array.isArray(payload.jobs)
      ? payload.jobs
      : []
  const branchRows = Array.isArray(session.branches)
    ? session.branches
    : Array.isArray(payload.branches)
      ? payload.branches
      : []

  return {
    id: populatedText(session.session_id, session.id, payload.session_id),
    title: populatedText(
      session.title,
      payload.title,
      session.topic,
      payload.topic,
      '历史深研对话'
    ),
    topic: populatedText(session.topic, payload.topic),
    status,
    statusLabel: legacyDeepStatusLabel(status),
    statusTone: legacyDeepStatusTone(status),
    archived: status === 'archived',
    createdAt: populatedText(session.created_at, payload.created_at),
    updatedAt: populatedText(session.updated_at, payload.updated_at),
    messages: messageRows.map(normalizeLegacyDeepMessage).sort(chronological),
    jobs: jobRows.map(normalizeLegacyDeepJob).sort(newestFirst),
    branches: branchRows.map(normalizeLegacyDeepBranch).sort(chronological),
    payload
  }
}

export const hasLegacyDeepValue = (value) => {
  if (Array.isArray(value)) return value.length > 0
  if (value && typeof value === 'object') return Object.keys(value).length > 0
  return Boolean(text(value))
}

export const formatLegacyDeepJson = (value) => {
  if (typeof value === 'string') {
    const parsed = parseJson(value)
    if (parsed === value) return value
    value = parsed
  }
  try {
    return JSON.stringify(value, null, 2) ?? String(value ?? '')
  } catch {
    return String(value ?? '')
  }
}

export const formatLegacyDeepReference = (value) => {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value ?? '')
  }
}
