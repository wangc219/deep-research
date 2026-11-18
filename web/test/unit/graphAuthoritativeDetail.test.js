import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  graphAuthorityReference,
  useAuthoritativeGraphDetail
} from '../../src/composables/useAuthoritativeGraphDetail.js'

const sectionSource = await readFile(
  new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
  'utf8'
)
const detailSource = await readFile(
  new URL('../../src/components/knowledge/AuthoritativeGraphDetail.vue', import.meta.url),
  'utf8'
)

const deferred = () => {
  let resolve
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

test('从节点和边投影属性提取稳定权威标识', () => {
  assert.deepEqual(
    graphAuthorityReference(
      { data: { original: { properties: { entity_id: 'entity-1' } } } },
      'node'
    ),
    { type: 'node', id: 'entity-1' }
  )
  assert.deepEqual(
    graphAuthorityReference({ data: { original: { triple_id: 'triple-1' } } }, 'edge'),
    { type: 'edge', id: 'triple-1' }
  )
  assert.equal(graphAuthorityReference({ data: { original: { labels: ['Chunk'] } } }, 'node'), null)
})

test('迟到的权威详情响应不会覆盖当前选中项', async () => {
  const first = deferred()
  const second = deferred()
  const api = {
    getEntityDetail: async (_kbId, entityId) =>
      entityId === 'entity-1' ? first.promise : second.promise,
    getRelationDetail: async () => ({ data: null })
  }
  const authority = useAuthoritativeGraphDetail(api)

  const firstLoad = authority.load({
    kbId: 'kb',
    type: 'node',
    item: { data: { original: { properties: { entity_id: 'entity-1' } } } }
  })
  const secondLoad = authority.load({
    kbId: 'kb',
    type: 'node',
    item: { data: { original: { properties: { entity_id: 'entity-2' } } } }
  })

  second.resolve({ data: { entity: { entity_id: 'entity-2' } } })
  await secondLoad
  first.resolve({ data: { entity: { entity_id: 'entity-1' } } })
  await firstLoad

  assert.equal(authority.detail.value.entity.entity_id, 'entity-2')
  assert.equal(authority.loading.value, false)
})

test('无权威 ID 的 Chunk 不发起请求，404 显式降级', async () => {
  let calls = 0
  const authority = useAuthoritativeGraphDetail({
    getEntityDetail: async () => {
      calls += 1
      const error = new Error('not found')
      error.status = 404
      throw error
    },
    getRelationDetail: async () => null
  })

  await authority.load({ kbId: 'kb', type: 'node', item: { data: { original: {} } } })
  assert.equal(calls, 0)
  assert.equal(authority.reference.value, null)

  await authority.load({
    kbId: 'kb',
    type: 'node',
    item: { data: { original: { properties: { entity_id: 'missing' } } } }
  })
  assert.equal(calls, 1)
  assert.match(authority.error.value, /没有可展示的已接受权威证据/)
})

test('权威详情按真实证据总数逐页扩大读取且不超过已加载范围', async () => {
  const limits = []
  const authority = useAuthoritativeGraphDetail({
    getEntityDetail: async (_kbId, _entityId, limit) => {
      limits.push(limit)
      return {
        data: {
          entity: { entity_id: 'entity-1' },
          evidence_count: 45,
          evidence: Array.from({ length: Math.min(limit, 45) }, (_, index) => ({
            mention_id: `mention-${index}`
          }))
        }
      }
    },
    getRelationDetail: async () => ({ data: null })
  })

  await authority.load({
    kbId: 'kb',
    type: 'node',
    item: { data: { original: { properties: { entity_id: 'entity-1' } } } }
  })
  assert.equal(authority.canLoadMore.value, true)
  await authority.loadMore()
  await authority.loadMore()

  assert.deepEqual(limits, [20, 40, 45])
  assert.equal(authority.detail.value.evidence.length, 45)
  assert.equal(authority.canLoadMore.value, false)
})

test('加载更多失败保留已经展示的权威证据', async () => {
  let calls = 0
  const authority = useAuthoritativeGraphDetail({
    getEntityDetail: async () => {
      calls += 1
      if (calls > 1) throw new Error('增量证据读取失败')
      return {
        data: {
          entity: { entity_id: 'entity-1' },
          evidence_count: 21,
          evidence: Array.from({ length: 20 }, (_, index) => ({ mention_id: `m-${index}` }))
        }
      }
    },
    getRelationDetail: async () => ({ data: null })
  })

  await authority.load({
    kbId: 'kb',
    type: 'node',
    item: { data: { original: { properties: { entity_id: 'entity-1' } } } }
  })
  await authority.loadMore()

  assert.equal(authority.detail.value.evidence.length, 20)
  assert.equal(authority.error.value, '')
  assert.match(authority.loadMoreError.value, /增量证据读取失败/)
})

test('图谱详情完整接入权威读取和可回切证据展示', () => {
  assert.match(sectionSource, /handleNodeDetailClick/)
  assert.match(sectionSource, /handleEdgeDetailClick/)
  assert.match(sectionSource, /useAuthoritativeGraphDetail/)
  assert.match(detailSource, /PostgreSQL 权威实体/)
  assert.match(detailSource, /PostgreSQL 权威关系/)
  assert.match(detailSource, /evidenceSegments/)
  assert.match(detailSource, /适用条件/)
  assert.match(detailSource, /生命周期/)
  assert.match(detailSource, /关系版本/)
  assert.match(detailSource, /superseded_by_triple_id/)
  assert.match(detailSource, /不确定性/)
  assert.match(detailSource, /pipeline_revision/)
  assert.match(detailSource, /加载更多证据/)
})
