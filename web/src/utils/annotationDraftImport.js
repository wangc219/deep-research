const AI_DRAFT_CONTRACT_VERSION = 'defense-kg-ai-draft-v1'

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)

const normalizePage = (value) => (value === null || value === undefined ? null : Number(value))

const assertAiDraft = (draft, lineNumber) => {
  const prefix = `第 ${lineNumber} 行`
  if (!isObject(draft)) throw new Error(`${prefix}不是 JSON 对象`)
  if (draft.contract_version !== AI_DRAFT_CONTRACT_VERSION) {
    throw new Error(`${prefix}不是受支持的 AI 候选契约`)
  }
  if (!String(draft.document_id || '').trim()) throw new Error(`${prefix}缺少 document_id`)
  if (!Array.isArray(draft.blocks) || !draft.blocks.length) throw new Error(`${prefix}缺少权威 Block`)
  if (!Array.isArray(draft.entities) || !Array.isArray(draft.relations)) {
    throw new Error(`${prefix}的 entities 或 relations 不是数组`)
  }
  const provenance = draft.draft_provenance
  if (
    !isObject(provenance) ||
    provenance.annotation_kind !== 'ai_prelabel' ||
    provenance.formal_gold_eligible !== false ||
    provenance.human_confirmed !== false
  ) {
    throw new Error(`${prefix}缺少不可冒充真人提交的 AI 谱系标记`)
  }
}

export const parseAiDraftJsonl = (text) => {
  const drafts = new Map()
  const lines = String(text || '').split(/\r?\n/)
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim()
    if (!line) continue
    let draft
    try {
      draft = JSON.parse(line)
    } catch {
      throw new Error(`第 ${index + 1} 行不是合法 JSON`)
    }
    assertAiDraft(draft, index + 1)
    if (drafts.has(draft.document_id)) {
      throw new Error(`document_id ${draft.document_id} 在导入文件中重复`)
    }
    drafts.set(draft.document_id, draft)
  }
  if (!drafts.size) throw new Error('导入文件中没有 AI 候选文档')
  return drafts
}

const authoritativeBlocksMatch = (draftBlocks, assignmentBlocks) => {
  if (draftBlocks.length !== assignmentBlocks.length) return false
  return draftBlocks.every((draftBlock, index) => {
    const assignmentBlock = assignmentBlocks[index]
    return (
      draftBlock.block_id === assignmentBlock.block_id &&
      draftBlock.text === assignmentBlock.text &&
      normalizePage(draftBlock.page) === normalizePage(assignmentBlock.page)
    )
  })
}

export const prepareAiDraftForAssignment = (draft, assignment, currentUserUid) => {
  if (!draft) throw new Error('当前任务没有可用的 AI 候选')
  if (!assignment) throw new Error('尚未选择标注任务')
  if (assignment.role !== 'annotator') throw new Error('AI 候选只能加载到独立标注员编辑器')
  const intendedReviewer = String(draft.draft_provenance?.intended_human_reviewer || '').trim()
  if (!intendedReviewer || intendedReviewer !== String(currentUserUid || '').trim()) {
    throw new Error('AI 候选不属于当前登录账号，已阻止跨标注员加载')
  }
  const metadataFields = ['document_id', 'split', 'language', 'source_type', 'domain']
  for (const field of metadataFields) {
    if (String(draft[field] ?? '') !== String(assignment[field] ?? '')) {
      throw new Error(`AI 候选的 ${field} 与当前任务不一致`)
    }
  }
  if (!authoritativeBlocksMatch(draft.blocks, assignment.blocks || [])) {
    throw new Error('AI 候选 Block 与当前任务的 PostgreSQL 权威 Block 不完全一致')
  }
  return {
    entities: draft.entities.map((entity) => ({ ...entity })),
    relations: draft.relations.map((relation) => ({
      ...relation,
      evidence_block_ids: [...(relation.evidence_block_ids || [])],
      evidence_spans: (relation.evidence_spans || []).map((span) => ({ ...span })),
      applicable_conditions: [...(relation.applicable_conditions || [])]
    }))
  }
}

export const mergeAiDraftMaps = (target, incoming) => {
  const merged = new Map(target)
  for (const [documentId, draft] of incoming) {
    if (merged.has(documentId)) throw new Error(`document_id ${documentId} 在多个导入文件中重复`)
    merged.set(documentId, draft)
  }
  return merged
}
