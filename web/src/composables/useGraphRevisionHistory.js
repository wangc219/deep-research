import { computed, ref } from 'vue'

const REVISION_PAGE_SIZE = 20
const CHANGE_PAGE_SIZE = 50
const HISTORY_ERROR_FALLBACK = '图谱版本历史加载失败'

/**
 * 管理 PostgreSQL 权威 graph revision 与不可变变更事件的分页读取。
 */
export function useGraphRevisionHistory(api) {
  const revisions = ref([])
  const revisionCount = ref(0)
  const revisionOffset = ref(0)
  const revisionLoading = ref(false)
  const revisionError = ref('')
  const selectedRevision = ref(null)

  const changes = ref([])
  const changeCount = ref(0)
  const changeOffset = ref(0)
  const changeLoading = ref(false)
  const changeError = ref('')
  const targetType = ref('')
  const targetId = ref('')

  let activeKbId = ''
  let revisionSequence = 0
  let changeSequence = 0

  const revisionPage = computed(() => Math.floor(revisionOffset.value / REVISION_PAGE_SIZE) + 1)
  const changePage = computed(() => Math.floor(changeOffset.value / CHANGE_PAGE_SIZE) + 1)

  const reset = () => {
    revisionSequence += 1
    changeSequence += 1
    activeKbId = ''
    revisions.value = []
    revisionCount.value = 0
    revisionOffset.value = 0
    revisionLoading.value = false
    revisionError.value = ''
    selectedRevision.value = null
    changes.value = []
    changeCount.value = 0
    changeOffset.value = 0
    changeLoading.value = false
    changeError.value = ''
    targetType.value = ''
    targetId.value = ''
  }

  const loadChanges = async ({ offset = changeOffset.value } = {}) => {
    const revisionId = selectedRevision.value?.revision_id
    const kbId = activeKbId
    const sequence = ++changeSequence
    changeOffset.value = Math.max(0, offset)
    changes.value = []
    changeError.value = ''

    if (!kbId || !revisionId) {
      changeCount.value = 0
      changeLoading.value = false
      return null
    }

    changeLoading.value = true
    try {
      const response = await api.getChangeEvents(kbId, {
        graph_revision: revisionId,
        target_type: targetType.value,
        target_id: targetId.value.trim(),
        limit: CHANGE_PAGE_SIZE,
        offset: changeOffset.value
      })
      if (sequence !== changeSequence || kbId !== activeKbId) return null

      const payload = response?.data || {}
      changes.value = Array.isArray(payload.items) ? payload.items : []
      changeCount.value = Number(payload.count || 0)
      return payload
    } catch (error) {
      if (sequence !== changeSequence || kbId !== activeKbId) return null
      changeError.value = historyError(error)
      changeCount.value = 0
      return null
    } finally {
      if (sequence === changeSequence && kbId === activeKbId) changeLoading.value = false
    }
  }

  const selectRevision = async (revision) => {
    selectedRevision.value = revision || null
    changeOffset.value = 0
    return await loadChanges({ offset: 0 })
  }

  const loadRevisions = async ({ kbId = activeKbId, offset = revisionOffset.value } = {}) => {
    const normalizedKbId = String(kbId || '')
    const sequence = ++revisionSequence
    changeSequence += 1
    activeKbId = normalizedKbId
    revisionOffset.value = Math.max(0, offset)
    revisions.value = []
    revisionError.value = ''
    selectedRevision.value = null
    changes.value = []
    changeCount.value = 0
    changeLoading.value = false
    changeError.value = ''

    if (!normalizedKbId) {
      revisionCount.value = 0
      revisionLoading.value = false
      return null
    }

    revisionLoading.value = true
    try {
      const response = await api.getRevisions(normalizedKbId, {
        limit: REVISION_PAGE_SIZE,
        offset: revisionOffset.value
      })
      if (sequence !== revisionSequence || normalizedKbId !== activeKbId) return null

      const payload = response?.data || {}
      revisions.value = Array.isArray(payload.items) ? payload.items : []
      revisionCount.value = Number(payload.count || 0)
      if (revisions.value.length) await selectRevision(revisions.value[0])
      return payload
    } catch (error) {
      if (sequence !== revisionSequence || normalizedKbId !== activeKbId) return null
      revisionError.value = historyError(error)
      revisionCount.value = 0
      return null
    } finally {
      if (sequence === revisionSequence && normalizedKbId === activeKbId) {
        revisionLoading.value = false
      }
    }
  }

  const setRevisionPage = async (page) => {
    return await loadRevisions({ offset: (Math.max(1, page) - 1) * REVISION_PAGE_SIZE })
  }

  const setChangePage = async (page) => {
    return await loadChanges({ offset: (Math.max(1, page) - 1) * CHANGE_PAGE_SIZE })
  }

  const applyFilters = async () => {
    return await loadChanges({ offset: 0 })
  }

  return {
    revisions,
    revisionCount,
    revisionLoading,
    revisionError,
    revisionPage,
    selectedRevision,
    changes,
    changeCount,
    changeLoading,
    changeError,
    changePage,
    targetType,
    targetId,
    revisionPageSize: REVISION_PAGE_SIZE,
    changePageSize: CHANGE_PAGE_SIZE,
    loadRevisions,
    selectRevision,
    setRevisionPage,
    setChangePage,
    applyFilters,
    reset
  }
}

function historyError(error) {
  return (
    error?.response?.data?.detail ||
    error?.response?.data?.message ||
    error?.message ||
    HISTORY_ERROR_FALLBACK
  )
}
