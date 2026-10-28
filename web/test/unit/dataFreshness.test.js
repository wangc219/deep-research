import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createRefreshController,
  notifyDataChanged,
  subscribeDataChanges
} from '../../src/utils/dataFreshness.js'

test('本地及跨标签页通知可取消订阅，不广播用户数据', () => {
  const previousWindow = globalThis.window
  const previousStorage = globalThis.localStorage
  globalThis.window = new EventTarget()
  const writes = []
  globalThis.localStorage = { setItem: (...args) => writes.push(args) }
  try {
    let calls = 0
    const stop = subscribeDataChanges(() => {
      calls += 1
    })
    notifyDataChanged('knowledge')
    assert.equal(calls, 1)
    assert.equal(writes[0][0], 'app:data-version')
    assert.match(writes[0][1], /^\d+:0\.\d+$/)
    const event = new Event('storage')
    event.key = 'app:data-version'
    window.dispatchEvent(event)
    assert.equal(calls, 2)
    stop()
    notifyDataChanged('workspace')
    window.dispatchEvent(event)
    assert.equal(calls, 2)
  } finally {
    globalThis.window = previousWindow
    globalThis.localStorage = previousStorage
  }
})

test('更新通知合并，慢请求期间只追加一次刷新，停止后不再刷新', async () => {
  let scheduled
  let calls = 0
  let release
  const controller = createRefreshController(
    () => {
      calls += 1
      return new Promise((resolve) => {
        release = resolve
      })
    },
    {
      schedule: (fn) => {
        scheduled = fn
        return 1
      },
      cancel: () => {
        scheduled = null
      }
    }
  )
  controller.request()
  controller.request()
  const first = scheduled()
  scheduled = null
  assert.equal(calls, 1)
  controller.request()
  controller.request()
  assert.equal(scheduled, null)
  release()
  await first
  assert.equal(typeof scheduled, 'function')
  const second = scheduled()
  controller.stop()
  release()
  await second
  controller.request()
  assert.equal(calls, 2)
})

test('隐藏页面跳过刷新；失败后可以继续处理通知', async () => {
  let scheduled
  let enabled = false
  let errors = 0
  let calls = 0
  const controller = createRefreshController(
    async () => {
      calls += 1
      throw new Error('temporary')
    },
    {
      enabled: () => enabled,
      schedule: (fn) => {
        scheduled = fn
        return 1
      },
      onError: () => {
        errors += 1
      }
    }
  )
  controller.request()
  assert.equal(scheduled, undefined)
  enabled = true
  controller.request()
  await scheduled()
  controller.request()
  await scheduled()
  assert.equal(calls, 2)
  assert.equal(errors, 2)
  controller.stop()
})
