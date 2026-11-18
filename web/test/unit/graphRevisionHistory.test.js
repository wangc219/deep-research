import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { useGraphRevisionHistory } from '../../src/composables/useGraphRevisionHistory.js'

const sectionSource = await readFile(
  new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
  'utf8'
)
const workbenchSource = await readFile(
  new URL('../../src/components/knowledge/GraphRevisionHistoryWorkbench.vue', import.meta.url),
  'utf8'
)

const deferred = () => {
  let resolve
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

test('版本列表自动选择首个 revision 并按权威版本读取变更事件', async () => {
  const calls = []
  const history = useGraphRevisionHistory({
    getRevisions: async (kbId, params) => {
      calls.push(['revisions', kbId, params])
      return {
        data: {
          count: 1,
          items: [{ revision_id: 'revision-1', ontology_version: 'defense-kg-1.0' }]
        }
      }
    },
    getChangeEvents: async (kbId, params) => {
      calls.push(['changes', kbId, params])
      return { data: { count: 1, items: [{ event_id: 'event-1' }] } }
    }
  })

  await history.loadRevisions({ kbId: 'kb-1', offset: 0 })

  assert.equal(history.selectedRevision.value.revision_id, 'revision-1')
  assert.equal(history.changes.value[0].event_id, 'event-1')
  assert.equal(calls[1][2].graph_revision, 'revision-1')
  assert.equal(calls[1][2].limit, 50)
})

test('切换知识库后迟到的 revision 响应不会覆盖当前历史', async () => {
  const first = deferred()
  const second = deferred()
  const history = useGraphRevisionHistory({
    getRevisions: async (kbId) => (kbId === 'kb-1' ? first.promise : second.promise),
    getChangeEvents: async () => ({ data: { count: 0, items: [] } })
  })

  const firstLoad = history.loadRevisions({ kbId: 'kb-1' })
  const secondLoad = history.loadRevisions({ kbId: 'kb-2' })
  second.resolve({ data: { count: 1, items: [{ revision_id: 'revision-2' }] } })
  await secondLoad
  first.resolve({ data: { count: 1, items: [{ revision_id: 'revision-1' }] } })
  await firstLoad

  assert.equal(history.selectedRevision.value.revision_id, 'revision-2')
  assert.equal(history.revisionLoading.value, false)
})

test('筛选与分页参数只作用于当前 revision', async () => {
  let changeParams = null
  const history = useGraphRevisionHistory({
    getRevisions: async () => ({
      data: { count: 1, items: [{ revision_id: 'revision-1' }] }
    }),
    getChangeEvents: async (_kbId, params) => {
      changeParams = params
      return { data: { count: 75, items: [] } }
    }
  })

  await history.loadRevisions({ kbId: 'kb-1' })
  history.targetType.value = 'entity'
  history.targetId.value = ' entity-1 '
  await history.applyFilters()
  await history.setChangePage(2)

  assert.deepEqual(changeParams, {
    graph_revision: 'revision-1',
    target_type: 'entity',
    target_id: 'entity-1',
    limit: 50,
    offset: 50
  })
  assert.equal(history.changePage.value, 2)
})

test('图谱页面以独立工作台接入 revision、筛选和 before/after 审计视图', () => {
  assert.match(sectionSource, /GraphRevisionHistoryWorkbench/)
  assert.match(sectionSource, /showRevisionHistory/)
  assert.match(workbenchSource, /useGraphRevisionHistory/)
  assert.match(workbenchSource, /不可变 Change Event/)
  assert.match(workbenchSource, /查看变更前后数据/)
  assert.match(workbenchSource, /targetType/)
})
