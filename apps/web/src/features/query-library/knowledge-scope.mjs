const MAX_KNOWLEDGE_IDS = 64;

const cleanText = value => typeof value === 'string' ? value.trim() : '';

export function normalizeKnowledgeIds(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const normalized = [];
  for (const rawId of value) {
    const knowledgeId = cleanText(rawId);
    if (!knowledgeId || seen.has(knowledgeId)) continue;
    seen.add(knowledgeId);
    normalized.push(knowledgeId);
    if (normalized.length >= MAX_KNOWLEDGE_IDS) break;
  }
  return normalized;
}

/**
 * Build scope for a new Query. No explicit selection means all currently
 * visible knowledge bases remain available on demand; it never means eager
 * retrieval or prompt injection.
 */
export function createKnowledgeScope({enabled = true, selectedIds = []} = {}) {
  if (!enabled) return {knowledge_enabled: false, knowledge_ids: []};
  const knowledgeIds = normalizeKnowledgeIds(selectedIds);
  return {
    knowledge_enabled: true,
    knowledge_ids: knowledgeIds.length ? knowledgeIds : null,
  };
}

/** Preserve an already-persisted Query scope when creating a research Run. */
export function inheritKnowledgeScope(record) {
  if (!record || typeof record !== 'object') return {};
  if (record.knowledge_enabled === false) {
    return {knowledge_enabled: false, knowledge_ids: []};
  }
  if (record.knowledge_ids == null) {
    return {knowledge_enabled: true, knowledge_ids: null};
  }
  return {
    knowledge_enabled: true,
    knowledge_ids: normalizeKnowledgeIds(record.knowledge_ids),
  };
}

export function normalizeAccessibleKnowledgeBases(payload) {
  const rows = Array.isArray(payload?.databases)
    ? payload.databases
    : Array.isArray(payload?.items) ? payload.items : [];
  const seen = new Set();
  return rows.flatMap(row => {
    const knowledgeId = cleanText(row?.kb_id);
    if (!knowledgeId || seen.has(knowledgeId)) return [];
    seen.add(knowledgeId);
    return [{
      kb_id: knowledgeId,
      name: cleanText(row?.name) || '未命名知识库',
      description: cleanText(row?.description),
      supports_documents: row?.supports_documents !== false,
    }];
  });
}

export function accessibleKnowledgeUrl(apiBase, baseHref = 'http://localhost/') {
  const url = new URL(cleanText(apiBase) || '/api/v1', baseHref);
  const markerIndex = url.pathname.lastIndexOf('/api/v1');
  url.pathname = markerIndex >= 0
    ? `${url.pathname.slice(0, markerIndex)}/api/knowledge/databases/accessible`
    : '/api/knowledge/databases/accessible';
  url.search = '';
  url.hash = '';
  return url.toString();
}

export function knowledgeScopeSummary(record) {
  if (record?.knowledge_enabled === false) return '知识库能力已关闭';
  if (record?.knowledge_ids == null) return '全部可见知识库按需可用';
  const count = normalizeKnowledgeIds(record.knowledge_ids).length;
  return count ? `${count} 个知识库按需可用` : '未开放知识库';
}

