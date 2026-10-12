function searchable(value) {
  return typeof value === 'string' ? value.normalize('NFKC').toLowerCase().replace(/\s+/gu, ' ').trim() : ''
}

export function graphSourceOptions(graph, sources = []) {
  const titles = new Map(sources.map((source) => [source.id, source.title]))
  const ids = [...new Set(graph.map((edge) => edge.source_id).filter((id) => typeof id === 'string' && id))]
  return ids.map((id) => ({ id, title: titles.get(id) || '来源标题未提供' }))
}

export function normalizeGraphFilters(graph, filters = {}) {
  return {
    query: typeof filters.query === 'string' ? filters.query : '',
    kind: ['fact', 'inference'].includes(filters.kind) ? filters.kind : 'all',
    sourceId: typeof filters.sourceId === 'string' && graph.some((edge) => edge.source_id === filters.sourceId) ? filters.sourceId : ''
  }
}

export function filterEvidenceGraph(graph, filters = {}) {
  const current = normalizeGraphFilters(graph, filters)
  const terms = searchable(current.query).split(' ').filter(Boolean)
  return graph.filter((edge) => {
    if (current.kind !== 'all' && edge.kind !== current.kind) return false
    if (current.sourceId && edge.source_id !== current.sourceId) return false
    const text = [edge.subject, edge.relation, edge.object].map(searchable).join(' ')
    return terms.every((term) => text.includes(term))
  })
}
