import { apiGet, apiPost } from './base'

export const graphApi = {
  getGraphs: async () => {
    return await apiGet('/api/graph/list', {}, true)
  },

  getSubgraph: async (params) => {
    const {
      kb_id,
      node_label = '*',
      max_depth = 2,
      max_nodes = 100,
      exclude_chunk = false
    } = params

    if (!kb_id) {
      throw new Error('kb_id is required')
    }

    const queryParams = new URLSearchParams({
      kb_id,
      node_label,
      max_depth: max_depth.toString(),
      max_nodes: max_nodes.toString(),
      exclude_chunk: exclude_chunk.toString()
    })

    return await apiGet(`/api/graph/subgraph?${queryParams.toString()}`, {}, true)
  },

  discoverPaths: async (params) => {
    const {
      kb_id,
      query,
      mode = 'auto',
      max_hops = 5,
      max_paths = 10,
      include_combinations = true,
      retrieval_mode = 'mix',
      query_enhancement_enabled = false,
      query_model_spec = '',
      query_enhancement_strict = false,
      path_reranking_enabled = false,
      path_reranking_model_spec = '',
      path_reranking_strict = false,
      narrative_enabled = false,
      narrative_model_spec = '',
      narrative_strict = false
    } = params

    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    if (!query?.trim()) {
      throw new Error('query is required')
    }

    const queryParams = new URLSearchParams({
      kb_id,
      query: query.trim(),
      mode,
      max_hops: max_hops.toString(),
      max_paths: max_paths.toString(),
      include_combinations: include_combinations.toString(),
      retrieval_mode,
      query_enhancement_enabled: query_enhancement_enabled.toString(),
      query_enhancement_strict: query_enhancement_strict.toString(),
      path_reranking_enabled: path_reranking_enabled.toString(),
      path_reranking_strict: path_reranking_strict.toString(),
      narrative_enabled: narrative_enabled.toString(),
      narrative_strict: narrative_strict.toString()
    })
    if (query_enhancement_enabled && query_model_spec) {
      queryParams.set('query_model_spec', query_model_spec)
    }
    if (path_reranking_enabled && path_reranking_model_spec) {
      queryParams.set('path_reranking_model_spec', path_reranking_model_spec)
    }
    if (narrative_enabled && narrative_model_spec) {
      queryParams.set('narrative_model_spec', narrative_model_spec)
    }
    return await apiGet(`/api/graph/paths?${queryParams.toString()}`, {}, true)
  },

  discoverInnovation: async (kb_id, payload) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    if (!payload?.query?.trim()) {
      throw new Error('query is required')
    }
    return await apiPost(`/api/graph/databases/${encodeURIComponent(kb_id)}/innovation/discover`, {
      query: payload.query.trim(),
      discovery_mode: payload.discovery_mode,
      max_hops: payload.max_hops ?? 5,
      max_candidates: payload.max_candidates ?? 10,
      persist: payload.persist ?? true,
      retrieval_mode: payload.retrieval_mode || 'mix',
      evidence_scope: payload.evidence_scope || 'any',
      query_enhancement_enabled: payload.query_enhancement_enabled === true,
      query_model_spec: payload.query_model_spec || null,
      query_enhancement_strict: payload.query_enhancement_strict === true,
      path_reranking_enabled: payload.path_reranking_enabled === true,
      path_reranking_model_spec: payload.path_reranking_model_spec || null,
      path_reranking_strict: payload.path_reranking_strict === true,
      innovation_llm_enabled: payload.innovation_llm_enabled === true,
      innovation_model_spec: payload.innovation_model_spec || null,
      innovation_llm_strict: payload.innovation_llm_strict === true,
      innovation_llm_concurrency: payload.innovation_llm_concurrency ?? 2
    })
  },

  generateEvidenceGroundedSolution: async (kb_id, payload) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    if (!payload?.query?.trim()) {
      throw new Error('query is required')
    }
    return await apiPost(`/api/graph/databases/${encodeURIComponent(kb_id)}/innovation/solution`, {
      query: payload.query.trim(),
      discovery_mode: payload.discovery_mode,
      llm_enabled: payload.llm_enabled === true,
      model_spec: payload.model_spec || null,
      max_hops: payload.max_hops ?? 5,
      max_paths: payload.max_paths ?? 5,
      retrieval_mode: payload.retrieval_mode || 'mix',
      evidence_scope: payload.evidence_scope || 'any',
      query_enhancement_enabled: payload.query_enhancement_enabled === true,
      query_model_spec: payload.query_model_spec || null,
      query_enhancement_strict: payload.query_enhancement_strict === true,
      path_reranking_enabled: payload.path_reranking_enabled === true,
      path_reranking_model_spec: payload.path_reranking_model_spec || null,
      path_reranking_strict: payload.path_reranking_strict === true
    })
  },

  getInnovationCandidates: async (kb_id, { status = 'pending', limit = 50, offset = 0 } = {}) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({
      status,
      limit: String(limit),
      offset: String(offset)
    })
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/innovation/candidates?${queryParams.toString()}`,
      {},
      true
    )
  },

  reviewInnovationCandidate: async (kb_id, hypothesis_id, decision) => {
    if (!kb_id || !hypothesis_id) {
      throw new Error('kb_id and hypothesis_id are required')
    }
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/innovation/candidates/${encodeURIComponent(hypothesis_id)}/review`,
      decision
    )
  },

  getEntityDetail: async (kb_id, entity_id, evidence_limit = 100) => {
    if (!kb_id || !entity_id) {
      throw new Error('kb_id and entity_id are required')
    }
    const queryParams = new URLSearchParams({ evidence_limit: String(evidence_limit) })
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/entities/${encodeURIComponent(entity_id)}?${queryParams.toString()}`,
      {},
      true
    )
  },

  getRelationDetail: async (kb_id, triple_id, evidence_limit = 100) => {
    if (!kb_id || !triple_id) {
      throw new Error('kb_id and triple_id are required')
    }
    const queryParams = new URLSearchParams({ evidence_limit: String(evidence_limit) })
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/relations/${encodeURIComponent(triple_id)}?${queryParams.toString()}`,
      {},
      true
    )
  },

  getDocumentCards: async (kb_id, { governance_status = '', limit = 50, offset = 0 } = {}) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (governance_status) queryParams.set('governance_status', governance_status)
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/document-cards?${queryParams.toString()}`,
      {},
      true
    )
  },

  getDocumentCard: async (kb_id, card_id) => {
    if (!kb_id || !card_id) {
      throw new Error('kb_id and card_id are required')
    }
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/document-cards/${encodeURIComponent(card_id)}`,
      {},
      true
    )
  },

  getRevisions: async (kb_id, { limit = 50, offset = 0 } = {}) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/revisions?${queryParams.toString()}`,
      {},
      true
    )
  },

  getChangeEvents: async (
    kb_id,
    { graph_revision = '', target_type = '', target_id = '', limit = 100, offset = 0 } = {}
  ) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (graph_revision) queryParams.set('graph_revision', graph_revision)
    if (target_type) queryParams.set('target_type', target_type)
    if (target_id) queryParams.set('target_id', target_id)
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/changes?${queryParams.toString()}`,
      {},
      true
    )
  },

  analyzeEntityEvolution: async (kb_id, entity_id, { persist = true } = {}) => {
    if (!kb_id || !entity_id) {
      throw new Error('kb_id and entity_id are required')
    }
    const queryParams = new URLSearchParams({ persist: String(persist) })
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/entities/${encodeURIComponent(entity_id)}/evolution/analyze?${queryParams.toString()}`,
      {}
    )
  },

  getEntityEvolution: async (kb_id, entity_id, limit = 24) => {
    if (!kb_id || !entity_id) {
      throw new Error('kb_id and entity_id are required')
    }
    const queryParams = new URLSearchParams({ limit: String(limit) })
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/entities/${encodeURIComponent(entity_id)}/evolution?${queryParams.toString()}`,
      {},
      true
    )
  },

  getEntityHistory: async (kb_id, entity_id) => {
    if (!kb_id || !entity_id) {
      throw new Error('kb_id and entity_id are required')
    }
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/entities/${encodeURIComponent(entity_id)}/history`,
      {},
      true
    )
  },

  redirectEntity: async (kb_id, entity_id, payload) => {
    if (!kb_id || !entity_id) {
      throw new Error('kb_id and entity_id are required')
    }
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/entities/${encodeURIComponent(entity_id)}/redirect`,
      payload
    )
  },

  updateRelationLifecycle: async (kb_id, triple_id, payload) => {
    if (!kb_id || !triple_id) {
      throw new Error('kb_id and triple_id are required')
    }
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/relations/${encodeURIComponent(triple_id)}/lifecycle`,
      payload
    )
  },

  getStats: async (kb_id) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }

    const queryParams = new URLSearchParams({ kb_id })
    return await apiGet(`/api/graph/stats?${queryParams.toString()}`, {}, true)
  },

  getLabels: async (kb_id) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }

    const queryParams = new URLSearchParams({ kb_id })
    return await apiGet(`/api/graph/labels?${queryParams.toString()}`, {}, true)
  },

  getOntology: async (version = '') => {
    const queryParams = new URLSearchParams()
    if (version) queryParams.set('version', version)
    const query = queryParams.toString()
    return await apiGet(`/api/graph/ontology${query ? `?${query}` : ''}`, {}, true)
  },

  getOntologyVersions: async ({ limit = 100, offset = 0 } = {}) => {
    const queryParams = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    return await apiGet(`/api/graph/ontology/versions?${queryParams.toString()}`, {}, true)
  },

  getOntologyVersion: async (version) => {
    if (!version) {
      throw new Error('version is required')
    }
    return await apiGet(`/api/graph/ontology/versions/${encodeURIComponent(version)}`, {}, true)
  },

  registerOntologyVersion: async (payload) => {
    return await apiPost('/api/graph/ontology/versions', payload)
  },

  getReviewQueue: async ({ kb_id, status = 'pending', limit = 100, offset = 0 }) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({
      kb_id,
      status,
      limit: String(limit),
      offset: String(offset)
    })
    return await apiGet(`/api/graph/review-queue?${queryParams.toString()}`, {}, true)
  },

  submitReviewDecision: async (kb_id, decision) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/review-decisions`,
      decision
    )
  },

  getConflicts: async ({ kb_id, status = 'open', severity = '', limit = 100, offset = 0 }) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({
      status,
      limit: String(limit),
      offset: String(offset)
    })
    if (severity) queryParams.set('severity', severity)
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/conflicts?${queryParams.toString()}`,
      {},
      true
    )
  },

  registerConflict: async (kb_id, conflict) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    return await apiPost(`/api/graph/databases/${encodeURIComponent(kb_id)}/conflicts`, conflict)
  },

  resolveConflict: async (kb_id, conflict_id, resolution) => {
    if (!kb_id || !conflict_id) {
      throw new Error('kb_id and conflict_id are required')
    }
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/conflicts/${encodeURIComponent(conflict_id)}/resolve`,
      resolution
    )
  },

  replayProjections: async (kb_id, limit = 20) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({ kb_id, limit: String(limit) })
    return await apiPost(`/api/graph/projections/replay?${queryParams.toString()}`, {})
  },

  getAcceptanceStatus: async (kb_id) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/acceptance/status`,
      {},
      true
    )
  },

  getBuildRuns: async (kb_id, { limit = 50, offset = 0 } = {}) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    const queryParams = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/build-runs?${queryParams.toString()}`,
      {},
      true
    )
  },

  getBuildRun: async (kb_id, run_id) => {
    if (!kb_id || !run_id) {
      throw new Error('kb_id and run_id are required')
    }
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/build-runs/${encodeURIComponent(run_id)}`,
      {},
      true
    )
  },

  recordEvaluation: async (kb_id, payload) => {
    if (!kb_id) {
      throw new Error('kb_id is required')
    }
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/acceptance/evaluations`,
      payload
    )
  },

  createAnnotationCampaign: async (kb_id, payload) => {
    if (!kb_id) throw new Error('kb_id is required')
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-campaigns`,
      payload
    )
  },

  getAnnotationCampaigns: async (kb_id) => {
    if (!kb_id) throw new Error('kb_id is required')
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-campaigns`,
      {},
      true
    )
  },

  getMyAnnotationAssignments: async (kb_id, campaign_id = '') => {
    if (!kb_id) throw new Error('kb_id is required')
    const query = new URLSearchParams()
    if (campaign_id) query.set('campaign_id', campaign_id)
    const suffix = query.toString()
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-assignments/mine${suffix ? `?${suffix}` : ''}`,
      {},
      true
    )
  },

  getAnnotationAssignment: async (kb_id, assignment_id) => {
    if (!kb_id || !assignment_id) throw new Error('kb_id and assignment_id are required')
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-assignments/${encodeURIComponent(assignment_id)}`,
      {},
      true
    )
  },

  submitAnnotation: async (kb_id, assignment_id, payload) => {
    if (!kb_id || !assignment_id) throw new Error('kb_id and assignment_id are required')
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-assignments/${encodeURIComponent(assignment_id)}/submissions`,
      { payload }
    )
  },

  saveAnnotationDraft: async (
    kb_id,
    assignment_id,
    payload,
    { source_kind = 'manual', provenance = {} } = {}
  ) => {
    if (!kb_id || !assignment_id) throw new Error('kb_id and assignment_id are required')
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-assignments/${encodeURIComponent(assignment_id)}/draft`,
      { payload, source_kind, provenance }
    )
  },

  bulkSubmitAnnotations: async (kb_id, campaign_id, expected_draft_count) => {
    if (!kb_id || !campaign_id) throw new Error('kb_id and campaign_id are required')
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-campaigns/${encodeURIComponent(campaign_id)}/submissions/bulk`,
      { confirm_submission: true, expected_draft_count }
    )
  },

  adjudicateAnnotation: async (kb_id, assignment_id, payload) => {
    if (!kb_id || !assignment_id) throw new Error('kb_id and assignment_id are required')
    return await apiPost(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-assignments/${encodeURIComponent(assignment_id)}/adjudication`,
      { payload }
    )
  },

  exportAnnotationCampaign: async (kb_id, campaign_id) => {
    if (!kb_id || !campaign_id) throw new Error('kb_id and campaign_id are required')
    return await apiGet(
      `/api/graph/databases/${encodeURIComponent(kb_id)}/annotation-campaigns/${encodeURIComponent(campaign_id)}/export`,
      {},
      true
    )
  }
}

export const unifiedApi = graphApi
