import assert from 'node:assert/strict'
import test from 'node:test'
import { createPollingScheduler } from '../../src/utils/sharedPolling.js'

test('共享一个定时器，隐藏时暂停，慢请求完成后再调度，取消订阅后停止', async () => {
  let callback
  let timers = 0
  let visible = true
  let clock = 0
  let calls = 0
  let finish
  const scheduler = createPollingScheduler({
    schedule: (fn) => { callback = fn; timers += 1; return timers },
    cancel: () => { callback = null },
    visible: () => visible,
    now: () => clock
  })
  const stop = scheduler.subscribe(() => {
    calls += 1
    return new Promise((resolve) => { finish = resolve })
  }, 1000)
  const stopOther = scheduler.subscribe(() => { calls += 1 }, 1000)
  assert.equal(timers, 1)
  clock = 1000
  visible = false
  await callback()
  assert.equal(calls, 0)
  visible = true
  const tick = callback()
  assert.equal(calls, 2)
  assert.equal(timers, 2)
  finish()
  await tick
  assert.equal(timers, 3)
  stop()
  stopOther()
  assert.equal(callback, null)
})
