import assert from 'node:assert/strict'
import test from 'node:test'
import {
  collectionArtifactState,
  filterCollectionArtifactRows,
  paginateCollectionArtifactRows,
  selectCollectionArtifactPage
} from '../../src/utils/collectionArtifactList.js'

const artifact = (index, overrides = {}) => ({
  id: `artifact-${index}`,
  title: `文字稿 ${index}`,
  account: index % 2 ? '火研所' : '人民日报',
  available: true,
  download_state: 'downloaded',
  ...overrides
})

test('成果筛选保留全局序号并支持视频号、标题和状态组合', () => {
  const items = [
    artifact(1),
    artifact(2, { title: '装备测试', download_state: 'imported' }),
    artifact(3, { available: false })
  ]

  assert.deepEqual(
    filterCollectionArtifactRows(items, { account: '火研所' }).map((row) => row.index),
    [1, 3]
  )
  assert.deepEqual(
    filterCollectionArtifactRows(items, { query: '装备', state: 'imported' }).map(
      (row) => row.item.id
    ),
    ['artifact-2']
  )
  assert.equal(collectionArtifactState(items[2]), 'missing')
})

test('任意后续成果可分页定位，不再固定停留在前一百条', () => {
  const rows = filterCollectionArtifactRows(
    Array.from({ length: 205 }, (_, index) => artifact(index + 1))
  )
  const result = paginateCollectionArtifactRows(rows, 3, 100)

  assert.equal(result.page, 3)
  assert.equal(result.totalPages, 3)
  assert.deepEqual(
    result.rows.map((row) => row.index),
    [201, 202, 203, 204, 205]
  )
})

test('选择当前页遵守每批一百项上限并允许清空后处理下一页', () => {
  const rows = filterCollectionArtifactRows(
    Array.from({ length: 150 }, (_, index) => artifact(index + 1))
  )
  const first = selectCollectionArtifactPage([], rows.slice(0, 100))
  const overflow = selectCollectionArtifactPage(first.ids, rows.slice(100))
  const nextBatch = selectCollectionArtifactPage([], rows.slice(100))

  assert.equal(first.ids.length, 100)
  assert.equal(first.limitReached, false)
  assert.equal(overflow.ids.length, 100)
  assert.equal(overflow.limitReached, true)
  assert.equal(nextBatch.ids.length, 50)
  assert.equal(nextBatch.ids[0], 'artifact-101')
})
