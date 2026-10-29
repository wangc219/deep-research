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

test('一个慢订阅不阻塞其他订阅，同一订阅不会重叠，取消后不会复活', async () => {
  let clock = 0, timerId = 0, slowCalls = 0, fastCalls = 0, release
  const timers = new Map()
  const scheduler = createPollingScheduler({
    now: () => clock,
    schedule: (fn, delay) => { const id=++timerId; timers.set(id,{fn,at:clock+delay}); return id },
    cancel: id => timers.delete(id)
  })
  const runNext = () => {
    const [id, timer] = [...timers.entries()].sort(([,a],[,b])=>a.at-b.at)[0]
    timers.delete(id)
    clock=timer.at
    return timer.fn()
  }
  const stopSlow = scheduler.subscribe(() => { slowCalls++; return new Promise(resolve=>{release=resolve}) },1000)
  const stopFast = scheduler.subscribe(() => { fastCalls++ },1000)
  const first = runNext()
  await Promise.resolve()
  await runNext()
  assert.equal(slowCalls,1)
  assert.equal(fastCalls,2)
  stopSlow()
  stopFast()
  release()
  await first
  assert.equal(timers.size,0)
})
