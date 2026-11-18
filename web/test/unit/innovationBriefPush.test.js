import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  briefPushSessionKey,
  findLatestBriefForToday,
  formatBriefTime
} from '../../src/utils/innovationBriefPush.js'

test('登录推送只选择上海时区当天最新的未读简报', () => {
  const result = findLatestBriefForToday(
    [
      { id: 'old', unread: true, created_at: '2026-11-03T15:59:59Z' },
      { id: 'read', unread: false, created_at: '2026-11-04T01:00:00Z' },
      { id: 'early', unread: true, created_at: '2026-11-04T00:00:00Z' },
      { id: 'latest', unread: true, created_at: '2026-11-04T08:00:00Z' }
    ],
    { now: new Date('2026-11-04T12:00:00Z'), unreadOnly: true }
  )

  assert.equal(result.id, 'latest')
})

test('页面今日卡片可以展示已读的当日最新简报', () => {
  const result = findLatestBriefForToday(
    [{ id: 'read', unread: false, created_at: '2026-11-04T01:00:00Z' }],
    { now: new Date('2026-11-04T12:00:00Z') }
  )

  assert.equal(result.id, 'read')
})

test('提前生成的简报按正式推送时间归属日期和排序', () => {
  const result = findLatestBriefForToday(
    [
      {
        id: 'prepared-yesterday',
        unread: true,
        created_at: '2026-11-03T15:30:00Z',
        published_at: '2026-11-04T00:00:00Z'
      },
      {
        id: 'created-later-but-published-earlier',
        unread: true,
        created_at: '2026-11-04T01:00:00Z',
        published_at: '2026-11-03T23:00:00Z'
      }
    ],
    { now: new Date('2026-11-04T12:00:00Z') }
  )

  assert.equal(result.id, 'prepared-yesterday')
})

test('跨上海自然日的历史简报不会作为登录推送', () => {
  const result = findLatestBriefForToday(
    [{ id: 'yesterday', unread: true, created_at: '2026-11-03T15:59:59Z' }],
    { now: new Date('2026-11-04T12:00:00Z'), unreadOnly: true }
  )

  assert.equal(result, null)
})

test('推送会话键按用户和简报隔离', () => {
  assert.equal(briefPushSessionKey('user-1', 'brief-1'), 'innovation-brief-push:user-1:brief-1')
  assert.notEqual(briefPushSessionKey('user-1', 'brief-1'), briefPushSessionKey('user-2', 'brief-1'))
})

test('简报时间按上海时区展示', () => {
  assert.equal(formatBriefTime('2026-11-04T00:03:00Z'), '11月4日 08:03')
})

test('布局在已登录会话中持续轮询今日简报', () => {
  const source = readFileSync(new URL('../../src/layouts/AppLayout.vue', import.meta.url), 'utf8')

  assert.match(source, /const BRIEF_PUSH_SYNC_INTERVAL_MS = 30 \* 1000/)
  assert.match(source, /startBriefPushSync\(\)/)
  assert.match(source, /void loadLatestBriefPush\(\)/)
  assert.match(source, /clearInterval\(briefPushSyncTimer\)/)
})

test('来源治理入口受独立构建开关保护', () => {
  const source = readFileSync(new URL('../../src/views/ExtensionsView.vue', import.meta.url), 'utf8')

  assert.match(source, /v-if="knowledgeGovernanceEnabled"/)
  assert.match(source, /VITE_ENABLE_KNOWLEDGE_GOVERNANCE === 'true'/)
})
