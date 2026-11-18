import { computed, ref } from 'vue'

const DETAIL_ERROR_FALLBACK = '权威详情加载失败'
const INITIAL_EVIDENCE_LIMIT = 20
const EVIDENCE_PAGE_SIZE = 20
const MAX_EVIDENCE_LIMIT = 500

/**
 * 从 Neo4j 投影项中提取 PostgreSQL 权威知识标识。
 */
export function graphAuthorityReference(item, type) {
  const original = item?.data?.original || {}
  const properties = original.properties || {}
  const id =
    type === 'node'
      ? properties.entity_id || original.entity_id
      : type === 'edge'
        ? properties.triple_id || original.triple_id
        : ''

  if (!id) return null
  return { type, id: String(id) }
}

/**
 * 管理图投影选中项的权威详情读取，并屏蔽迟到响应。
 */
export function useAuthoritativeGraphDetail(api) {
  const detail = ref(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref('')
  const loadMoreError = ref('')
  const reference = ref(null)
  const evidenceLimit = ref(INITIAL_EVIDENCE_LIMIT)
  let activeKbId = ''
  let requestSequence = 0

  const canLoadMore = computed(() => {
    const loaded = detail.value?.evidence?.length || 0
    const total = Number(detail.value?.evidence_count || loaded)
    return loaded < total && loaded < MAX_EVIDENCE_LIMIT
  })

  const clear = () => {
    requestSequence += 1
    detail.value = null
    loading.value = false
    loadingMore.value = false
    error.value = ''
    loadMoreError.value = ''
    reference.value = null
    evidenceLimit.value = INITIAL_EVIDENCE_LIMIT
    activeKbId = ''
  }

  const load = async ({ kbId, type, item }) => {
    const nextReference = graphAuthorityReference(item, type)
    const sequence = ++requestSequence
    detail.value = null
    error.value = ''
    loadMoreError.value = ''
    reference.value = nextReference
    evidenceLimit.value = INITIAL_EVIDENCE_LIMIT
    activeKbId = nextReference ? String(kbId || '') : ''

    if (!kbId || !nextReference) {
      loading.value = false
      return null
    }

    loading.value = true
    try {
      const response =
        nextReference.type === 'node'
          ? await api.getEntityDetail(kbId, nextReference.id, evidenceLimit.value)
          : await api.getRelationDetail(kbId, nextReference.id, evidenceLimit.value)

      if (sequence !== requestSequence) return null
      detail.value = response?.data || null
      return detail.value
    } catch (requestError) {
      if (sequence !== requestSequence) return null
      error.value = authorityDetailError(requestError)
      return null
    } finally {
      if (sequence === requestSequence) loading.value = false
    }
  }

  const loadMore = async () => {
    if (
      !activeKbId ||
      !reference.value ||
      !detail.value ||
      !canLoadMore.value ||
      loadingMore.value
    ) {
      return null
    }

    const sequence = ++requestSequence
    const kbId = activeKbId
    const activeReference = { ...reference.value }
    const total = Number(detail.value.evidence_count || 0)
    const nextLimit = Math.min(
      evidenceLimit.value + EVIDENCE_PAGE_SIZE,
      total || MAX_EVIDENCE_LIMIT,
      MAX_EVIDENCE_LIMIT
    )
    loadingMore.value = true
    loadMoreError.value = ''

    try {
      const response =
        activeReference.type === 'node'
          ? await api.getEntityDetail(kbId, activeReference.id, nextLimit)
          : await api.getRelationDetail(kbId, activeReference.id, nextLimit)
      if (
        sequence !== requestSequence ||
        kbId !== activeKbId ||
        activeReference.id !== reference.value?.id
      ) {
        return null
      }

      detail.value = response?.data || null
      evidenceLimit.value = nextLimit
      return detail.value
    } catch (requestError) {
      if (sequence !== requestSequence || kbId !== activeKbId) return null
      loadMoreError.value = authorityDetailError(requestError)
      return null
    } finally {
      if (sequence === requestSequence && kbId === activeKbId) loadingMore.value = false
    }
  }

  return {
    detail,
    loading,
    loadingMore,
    error,
    loadMoreError,
    reference,
    canLoadMore,
    load,
    loadMore,
    clear
  }
}

function authorityDetailError(error) {
  if (error?.status === 404 || error?.response?.status === 404) {
    return '当前投影项没有可展示的已接受权威证据'
  }
  return error?.response?.data?.detail || error?.message || DETAIL_ERROR_FALLBACK
}
