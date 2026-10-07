const MAX_KNOWLEDGE_IDS = 64

const cleanText = (value) => (typeof value === 'string' ? value.trim() : '')

export const QUERY_STATUS_LABELS = {
  draft: '待审核',
  published: '已发布',
  archived: '已归档'
}

export const QUERY_SOURCE_LABELS = {
  agent: 'Agent 生成',
  manual: '人工录入',
  import: '资料导入'
}

export const GENERATION_STAGE_LABELS = {
  queued: '等待生成 Worker',
  web_validation: '联网校验公开线索',
  query_generation: '多维发散生成需求选题',
  persisting: '质量门控与原子入库',
  completed: '生成完成',
  failed: '生成失败',
  cancelled: '已终止'
}

export function normalizePagedResult(payload, fallbackLimit = 20) {
  if (Array.isArray(payload)) {
    return { items: payload, total: payload.length, limit: fallbackLimit, offset: 0 }
  }
  const items = Array.isArray(payload?.items) ? payload.items : []
  const total = Number.isFinite(Number(payload?.total)) ? Number(payload.total) : items.length
  const limit = Number.isFinite(Number(payload?.limit)) ? Number(payload.limit) : fallbackLimit
  const offset = Number.isFinite(Number(payload?.offset)) ? Number(payload.offset) : 0
  return { items, total, limit, offset }
}

export function indexQueriesById(...collections) {
  const index = new Map()
  for (const collection of collections) {
    if (!Array.isArray(collection)) continue
    for (const item of collection) {
      const queryId = cleanText(item?.query_id)
      if (queryId) index.set(queryId, item)
    }
  }
  return index
}

export function buildDivergenceExamplePatch(example = {}) {
  return {
    topic: cleanText(example.topic),
    expected_angle: cleanText(example.angle),
    demand_dimension: cleanText(example.demand),
    technology_dimension: cleanText(example.technology)
  }
}

export function selectLeastUsedDiscoveryAngle(angles = [], generations = []) {
  const candidates = angles.map((angle, order) => {
    const appearances = generations
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => String(item?.topic || '').includes(angle))
    return {
      angle,
      order,
      count: appearances.length,
      lastSeen: appearances.length ? appearances[0].index : -1
    }
  })
  candidates.sort((left, right) => (
    left.count - right.count
    || right.lastSeen - left.lastSeen
    || left.order - right.order
  ))
  return candidates[0]?.angle || ''
}

export function normalizeKnowledgeIds(value) {
  if (!Array.isArray(value)) return []
  const seen = new Set()
  const result = []
  for (const item of value) {
    const id = cleanText(item)
    if (!id || seen.has(id)) continue
    seen.add(id)
    result.push(id)
    if (result.length >= MAX_KNOWLEDGE_IDS) break
  }
  return result
}

export function toggleKnowledgeSelection(selectedIds, knowledgeId) {
  const ids = normalizeKnowledgeIds(selectedIds)
  const id = cleanText(knowledgeId)
  if (!id) return ids
  if (ids.includes(id)) return ids.filter((item) => item !== id)
  if (ids.length >= MAX_KNOWLEDGE_IDS) return ids
  return [...ids, id]
}

export function createKnowledgeScope(enabled = true, selectedIds = []) {
  if (!enabled) return { knowledge_enabled: false, knowledge_ids: [] }
  const ids = normalizeKnowledgeIds(selectedIds)
  return { knowledge_enabled: true, knowledge_ids: ids.length ? ids : null }
}

export function inheritKnowledgeScope(record = {}) {
  if (record.knowledge_enabled === false) return { knowledge_enabled: false, knowledge_ids: [] }
  if (record.knowledge_ids == null) return { knowledge_enabled: true, knowledge_ids: null }
  return { knowledge_enabled: true, knowledge_ids: normalizeKnowledgeIds(record.knowledge_ids) }
}

export function knowledgeScopeSummary(record = {}) {
  if (record.knowledge_enabled === false) return '知识库能力已关闭'
  if (record.knowledge_ids == null) return '全部可见知识库按需可用'
  const count = normalizeKnowledgeIds(record.knowledge_ids).length
  return count ? `${count} 个知识库按需可用` : '未开放知识库'
}

export function normalizeAccessibleKnowledgeBases(payload) {
  const rows = Array.isArray(payload?.databases)
    ? payload.databases
    : Array.isArray(payload?.items)
      ? payload.items
      : []
  const seen = new Set()
  return rows.flatMap((row) => {
    const id = cleanText(row?.kb_id || row?.id)
    if (!id || seen.has(id)) return []
    seen.add(id)
    return [{
      kb_id: id,
      name: cleanText(row?.name) || '未命名知识库',
      description: cleanText(row?.description),
      supports_documents: row?.supports_documents !== false
    }]
  })
}

export function parseReferenceUrls(value) {
  return [...new Set(String(value || '').split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean))]
}

export function validateReferenceUrls(urls) {
  if (urls.length > 12) return '最多可添加 12 个参考 URL'
  for (const value of urls) {
    try {
      const url = new URL(value)
      if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) throw new Error('invalid')
    } catch {
      return `参考地址格式不正确：${value}。请使用不含账号密码的公开 HTTPS URL`
    }
  }
  return ''
}

export function queryLineageModelSpec(query = {}, generations = [], fallback = '') {
  const direct = cleanText(query.model_spec)
  if (direct) return direct
  const generation = generations.find((item) => item.generation_id === query.generation_id)
  return cleanText(generation?.model_config?.model_spec)
    || cleanText(generation?.provider_snapshot?.model_spec)
    || cleanText(fallback)
}

export function buildResearchRunPayload(query, modelSpec = '') {
  return {
    topic: cleanText(query?.query),
    supplemental_information: cleanText(query?.supplemental_information),
    research_route: 'auto',
    interaction_mode: 'expert',
    discovery_branch: 'auto',
    execution_profile_id: 'winning_swarm_dynamic_v2',
    max_rounds: 2,
    selected_agent_ids: [],
    analyst_confirmed: true,
    source_query_id: cleanText(query?.query_id),
    source_query_version: Number(query?.version) || 1,
    ...inheritKnowledgeScope(query),
    ...(cleanText(modelSpec) ? { execution: { model_spec: cleanText(modelSpec) } } : {})
  }
}

export function queryMatchesFilters(item, { search = '', status = 'all', sourceType = 'all' } = {}) {
  const keyword = cleanText(search).toLowerCase()
  return (status === 'all' ? item?.status !== 'archived' : item?.status === status)
    && (sourceType === 'all' || item?.source_type === sourceType)
    && (!keyword || `${item?.query || ''} ${item?.supplemental_information || ''} ${item?.generation_rationale || ''}`.toLowerCase().includes(keyword))
}
