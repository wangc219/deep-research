export const COLLECTION_ARTIFACT_SELECTION_LIMIT = 100
export const COLLECTION_ARTIFACT_PAGE_SIZES = [20, 50, 100]

const normalizedText = (value) => String(value || '').trim().toLocaleLowerCase('zh-CN')

export function collectionArtifactState(item) {
  if (!item?.available) return 'missing'
  if (item.download_state === 'imported') return 'imported'
  if (item.download_state === 'importing') return 'importing'
  if (item.download_state === 'failed') return 'failed'
  return 'downloaded'
}

/** 保留原始排序序号，使筛选前后仍可按同一编号定位成果。 */
export function filterCollectionArtifactRows(items, filters = {}) {
  const query = normalizedText(filters.query)
  const account = String(filters.account || '').trim()
  const state = String(filters.state || 'all')

  return (items || [])
    .map((item, index) => ({ item, index: index + 1 }))
    .filter(({ item }) => {
      if (account && item.account !== account) return false
      if (state !== 'all' && collectionArtifactState(item) !== state) return false
      if (!query) return true
      return normalizedText(`${item.title} ${item.account}`).includes(query)
    })
}

export function paginateCollectionArtifactRows(rows, page, pageSize) {
  const normalizedSize = Math.max(1, Number(pageSize) || COLLECTION_ARTIFACT_PAGE_SIZES[1])
  const totalPages = Math.max(1, Math.ceil(rows.length / normalizedSize))
  const normalizedPage = Math.min(Math.max(1, Number(page) || 1), totalPages)
  const start = (normalizedPage - 1) * normalizedSize
  return {
    page: normalizedPage,
    totalPages,
    rows: rows.slice(start, start + normalizedSize)
  }
}

/** 选择当前页可用成果，达到服务端每批上限时明确返回截断事实。 */
export function selectCollectionArtifactPage(
  selectedIds,
  rows,
  limit = COLLECTION_ARTIFACT_SELECTION_LIMIT
) {
  const ids = [...new Set(selectedIds || [])]
  for (const row of rows || []) {
    const item = row?.item || row
    if (!item?.available || !item.id || ids.includes(item.id)) continue
    if (ids.length >= limit) return { ids, limitReached: true }
    ids.push(item.id)
  }
  return { ids, limitReached: false }
}
