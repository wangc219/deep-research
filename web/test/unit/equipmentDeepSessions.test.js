import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildDeepSessionGroups,
  deepSessionStatusLabel,
  normalizeDeepSessions,
  splitDeepQueryDisplay
} from '../../src/utils/equipmentDeepSessions.js'

test('深研历史按 Query 分组且当前 Query 置顶', () => {
  const sessions = [
    { session_id: 'old', run_id: 'run-old', status: 'active', updated_at: '2026-09-25T09:00:00Z' },
    { session_id: 'current-1', run_id: 'run-current', status: 'active', updated_at: '2026-09-24T09:00:00Z' },
    { session_id: 'current-2', run_id: 'run-current', status: 'completed', updated_at: '2026-09-25T10:00:00Z' }
  ]
  const groups = buildDeepSessionGroups({
    sessions,
    runs: [
      { run_id: 'run-current', topic: '当前任务', supplemental_information: '背景约束' },
      { run_id: 'run-old', topic: '历史任务' }
    ],
    currentRunId: 'run-current'
  })

  assert.equal(groups.length, 2)
  assert.equal(groups[0].group_key, 'run:run-current')
  assert.equal(groups[0].is_current, true)
  assert.equal(groups[0].query, '当前任务\n背景约束')
  assert.deepEqual(groups[0].sessions.map((item) => item.session_id), ['current-2', 'current-1'])
})

test('当前与归档会话严格分栏', () => {
  const sessions = [
    { session_id: 'active', run_id: 'run-1', payload: { status: 'active' } },
    { session_id: 'archived', run_id: 'run-1', status: 'archived' }
  ]
  assert.deepEqual(
    buildDeepSessionGroups({ sessions }).flatMap((group) => group.sessions.map((item) => item.session_id)),
    ['active']
  )
  assert.deepEqual(
    buildDeepSessionGroups({ sessions, archived: true }).flatMap((group) => group.sessions.map((item) => item.session_id)),
    ['archived']
  )
})

test('旧数据保留自带 Query 快照且响应外形兼容', () => {
  const legacy = {
    items: [
      {
        session_id: 'legacy',
        project_id: 'project-1',
        payload: {
          query_snapshot: { topic: '旧 Query', supplemental_information: '旧背景' },
          status: 'active'
        }
      }
    ]
  }
  assert.equal(normalizeDeepSessions(legacy).length, 1)
  const groups = buildDeepSessionGroups({ sessions: legacy })
  assert.equal(groups[0].query, '旧 Query\n旧背景')
  assert.equal(splitDeepQueryDisplay(groups[0].query).background, '旧背景')
  assert.equal(deepSessionStatusLabel('archived'), '已归档')
})
