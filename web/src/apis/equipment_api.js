import {
  apiGet,
  apiPost,
  apiDelete,
  apiRequest,
  buildQuery,
  idempotencyHeaders
} from './base'

const encodeId = (value) => encodeURIComponent(String(value || '').trim())

export const equipmentApi = {
  getPortal: () => apiGet('/api/equipment/portal'),
  getResearchRuntime: () => apiGet('/api/equipment/runtime'),
  updateResearchCapacity: (capacity) =>
    apiRequest('/api/equipment/runtime/capacity', {
      method: 'PUT',
      body: JSON.stringify({ capacity })
    }),
  listRuns: (params = {}) => {
    const query = buildQuery(params)
    return apiGet(query ? `/api/equipment/runs?${query}` : '/api/equipment/runs')
  },
  createRun: (payload) => apiPost('/api/equipment/runs', payload),
  getRun: (runId) => apiGet(`/api/equipment/runs/${encodeId(runId)}`),
  updateRun: (runId, payload) =>
    apiRequest(`/api/equipment/runs/${encodeId(runId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  startRun: (runId) => apiPost(`/api/equipment/runs/${encodeId(runId)}/start`, {}),
  pauseRun: (runId) => apiPost(`/api/equipment/runs/${encodeId(runId)}/pause`, {}),
  resumeRun: (runId) => apiPost(`/api/equipment/runs/${encodeId(runId)}/resume`, {}),
  cancelRun: (runId) => apiPost(`/api/equipment/runs/${encodeId(runId)}/cancel`, {}),
  archiveRun: (runId) => apiPost(`/api/equipment/runs/${encodeId(runId)}/archive`, {}),
  deleteRun: (runId) => apiDelete(`/api/equipment/runs/${encodeId(runId)}`),
  listEvents: (runId, afterSeq = 0) =>
    apiGet(`/api/equipment/runs/${encodeId(runId)}/events?${buildQuery({ after_seq: afterSeq })}`),
  getRunInteractions: (runId, compact = true) =>
    apiGet(`/api/equipment/runs/${encodeId(runId)}/interactions?${buildQuery({ compact })}`),
  listRunEvidence: (runId) =>
    apiGet(`/api/equipment/runs/${encodeId(runId)}/evidence`),
  getRunWinningMechanism: (runId) =>
    apiGet(`/api/equipment/runs/${encodeId(runId)}/winning-mechanism`),
  // Query 与研究任务共享 /api/equipment、PostgreSQL 所有权和 Durable Task。
  listQueries: (params = {}) => {
    const query = buildQuery(params)
    return apiGet(query ? `/api/equipment/queries?${query}` : '/api/equipment/queries')
  },
  getQuery: (queryId, params = {}) => {
    const query = buildQuery(params)
    const path = `/api/equipment/queries/${encodeId(queryId)}`
    return apiGet(query ? `${path}?${query}` : path)
  },
  createQuery: (payload) => apiPost('/api/equipment/queries', payload),
  updateQuery: (queryId, payload) =>
    apiRequest(`/api/equipment/queries/${encodeId(queryId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload)
    }),
  publishQuery: (queryId, expectedVersion = undefined) =>
    apiPost(`/api/equipment/queries/${encodeId(queryId)}/publish`, {
      ...(expectedVersion ? { expected_version: expectedVersion } : {})
    }),
  archiveQuery: (queryId, expectedVersion = undefined) =>
    apiPost(`/api/equipment/queries/${encodeId(queryId)}/archive`, {
      ...(expectedVersion ? { expected_version: expectedVersion } : {})
    }),
  deleteQuery: (queryId) => apiDelete(`/api/equipment/queries/${encodeId(queryId)}`),
  bulkSetQueryStatus: (payload) => apiPost('/api/equipment/queries/bulk-status', payload),
  getQueryModelOptions: () => apiGet('/api/equipment/query-model-options'),
  generateQueries: (payload, options = {}) =>
    apiPost('/api/equipment/query-generations', payload, {
      headers: idempotencyHeaders(options.idempotencyKey, 'query-generation')
    }),
  listQueryGenerations: (params = {}) => {
    const query = buildQuery(params)
    return apiGet(query ? `/api/equipment/query-generations?${query}` : '/api/equipment/query-generations')
  },
  getQueryGeneration: (generationId) =>
    apiGet(`/api/equipment/query-generations/${encodeId(generationId)}`),
  cancelQueryGeneration: (generationId) =>
    apiPost(`/api/equipment/query-generations/${encodeId(generationId)}/cancel`, {}),
  retryQueryGeneration: (generationId) =>
    apiPost(`/api/equipment/query-generations/${encodeId(generationId)}/retry`, {}),
  deleteQueryGeneration: (generationId) =>
    apiDelete(`/api/equipment/query-generations/${encodeId(generationId)}`),
  createResearchRun: (payload, options = {}) => {
    const execution = payload?.execution && typeof payload.execution === 'object' ? payload.execution : {}
    const sourceQueryId = String(payload?.source_query_id || '').trim()
    const sourceQueryVersion = Number(payload?.source_query_version) || 1
    return apiPost('/api/equipment/runs', {
      project_id: options.projectId,
      topic: payload?.topic,
      supplemental_information: payload?.supplemental_information || '',
      research_route: payload?.research_route || 'auto',
      model_spec: execution.model_spec || payload?.model_spec || undefined,
      knowledge_enabled: (payload?.knowledge_enabled ?? execution.knowledge_enabled) !== false,
      knowledge_ids: payload?.knowledge_ids !== undefined ? payload.knowledge_ids : (execution.knowledge_ids ?? null),
      interaction_mode: payload?.interaction_mode || 'expert',
      discovery_branch: payload?.discovery_branch || 'auto',
      execution_profile_id: payload?.execution_profile_id || '',
      report_template_mode: payload?.report_template_mode || 'three_layer_nine_item',
      selected_agent_ids: Array.isArray(payload?.selected_agent_ids) ? payload.selected_agent_ids : [],
      max_rounds: Number(payload?.max_rounds) || 2,
      payload: {
        analyst_confirmed: Boolean(payload?.analyst_confirmed),
        query_library: sourceQueryId ? { query_id: sourceQueryId, version: sourceQueryVersion } : undefined,
        legacy_source_query_id: sourceQueryId || undefined,
        legacy_source_query_version: sourceQueryId ? sourceQueryVersion : undefined
      }
    }, {
      headers: idempotencyHeaders(options.idempotencyKey, 'research-run')
    })
  },
  startResearchRun: (runId, options = {}) =>
    apiPost(`/api/equipment/runs/${encodeId(runId)}/start`, {}, {
      headers: idempotencyHeaders(options.idempotencyKey, 'research-start')
    }),
  getResearchReport: (runId) => apiGet(`/api/equipment/runs/${encodeId(runId)}/report`),
  listCapabilities: () => apiGet('/api/equipment/capabilities'),
  listCapabilityVersions: (runId) =>
    apiGet(`/api/equipment/runs/${encodeId(runId)}/capability-versions`),
  verifyCapabilityVersion: (runId, versionId, status = 'verified') =>
    apiPost(`/api/equipment/runs/${encodeId(runId)}/capability-versions/${encodeId(versionId)}/verify`, { status }),
  deleteCapabilityVersion: (runId, versionId) =>
    apiDelete(`/api/equipment/runs/${encodeId(runId)}/capability-versions/${encodeId(versionId)}`),
  restoreCapabilityVersion: (runId, versionId) =>
    apiPost(`/api/equipment/runs/${encodeId(runId)}/capability-versions/${encodeId(versionId)}/restore`, {}),
  purgeCapabilityVersion: (runId, versionId) =>
    apiDelete(`/api/equipment/runs/${encodeId(runId)}/capability-versions/${encodeId(versionId)}/permanent`),
  listExpertFeedback: (runId) =>
    apiGet(`/api/equipment/runs/${encodeId(runId)}/expert-feedback`),
  createExpertFeedback: (runId, payload) =>
    apiPost(`/api/equipment/runs/${encodeId(runId)}/expert-feedback`, payload),
  rollbackExpertFeedback: (runId, feedbackId, reason = '') =>
    apiPost(`/api/equipment/runs/${encodeId(runId)}/expert-feedback/${encodeId(feedbackId)}/rollback`, { reason }),
  listFavorites: async () => {
    const payload = await apiGet('/api/equipment/favorites?limit=200')
    return [payload?.items, payload?.favorites].find(Array.isArray) || []
  },
  createFavoriteCard: (payload) => apiPost('/api/equipment/favorites', payload),
  listFavoriteCards: (params = {}) => {
    const query = buildQuery(params)
    return apiGet(query ? `/api/equipment/favorites?${query}` : '/api/equipment/favorites')
  },
  getFavoriteCard: (favoriteId) =>
    apiGet(`/api/equipment/favorites/${encodeId(favoriteId)}`),
  updateFavoriteCard: (favoriteId, payload) =>
    apiRequest(`/api/equipment/favorites/${encodeId(favoriteId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload)
    }),
  deleteFavoriteCard: (favoriteId) =>
    apiDelete(`/api/equipment/favorites/${encodeId(favoriteId)}`),
  listDeepSessions: () => apiGet('/api/equipment/deep-thinking'),
  getDeepContextOptions: (runId) =>
    apiGet(`/api/equipment/deep-thinking/context-options?${buildQuery({ run_id: runId })}`),
  createDeepSession: (payload) => apiPost('/api/equipment/deep-thinking', payload),
  getDeepSession: (sessionId) => apiGet(`/api/equipment/deep-thinking/${encodeId(sessionId)}`),
  updateDeepSession: (sessionId, payload) =>
    apiRequest(`/api/equipment/deep-thinking/${encodeId(sessionId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload)
    }),
  deleteDeepSession: (sessionId) =>
    apiDelete(`/api/equipment/deep-thinking/${encodeId(sessionId)}`),
  sendDeepMessage: (sessionId, payload) =>
    apiPost(`/api/equipment/deep-thinking/${encodeId(sessionId)}/messages`, payload),
  forkDeepSession: (sessionId, payload) =>
    apiPost(`/api/equipment/deep-thinking/${encodeId(sessionId)}/branches`, payload),
  listReports: () => apiGet('/api/equipment/reports')
}
