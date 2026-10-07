import { apiGet } from './base'

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
      include_combinations = true
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
      include_combinations: include_combinations.toString()
    })
    return await apiGet(`/api/graph/paths?${queryParams.toString()}`, {}, true)
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
  }
}

export const unifiedApi = graphApi
