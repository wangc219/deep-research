import assert from 'node:assert/strict'
import test from 'node:test'
import { createReadRequestPool } from '../../src/utils/readRequestPool.js'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const flush = async () => { await Promise.resolve(); await Promise.resolve() }

test('同一身份的并发读取仅发一次请求，响应独立消费且不跨刷新缓存', async () => {
  let calls = 0
  const waiting = deferred()
  const request = createReadRequestPool(() => { calls++; return waiting.promise })
  const options = { headers: { Authorization: 'Bearer owner' } }
  const one = request('/api/items', options)
  const two = request('/api/items', options)
  await flush()
  assert.equal(calls, 1)
  waiting.resolve(Response.json({ items: ['a'] }))
  const [a,b] = await Promise.all([one,two])
  assert.deepEqual(await a.json(), { items: ['a'] })
  assert.deepEqual(await b.json(), { items: ['a'] })
  await request('/api/items', options)
  assert.equal(calls, 2)
})

test('账号、参数及请求头不同的读取互不合并', async () => {
  let calls = 0
  const request = createReadRequestPool(() => { calls++; return Promise.resolve(Response.json({})) })
  await Promise.all([
    request('/api/items?limit=10', { headers: { Authorization: 'Bearer first' } }),
    request('/api/items?limit=10', { headers: { Authorization: 'Bearer second' } }),
    request('/api/items?limit=20', { headers: { Authorization: 'Bearer first' } })
  ])
  assert.equal(calls, 3)
})

test('一个页面取消不影响其他等待者，全部取消才中止网络', async () => {
  const waiting = deferred()
  let upstreamSignal
  const request = createReadRequestPool((_url, options) => { upstreamSignal = options.signal; return waiting.promise })
  const a = new AbortController(), b = new AbortController()
  const one = request('/api/items', { signal:a.signal })
  const two = request('/api/items', { signal:b.signal })
  await flush()
  a.abort()
  await assert.rejects(one, { name:'AbortError' })
  assert.equal(upstreamSignal.aborted, false)
  b.abort()
  await assert.rejects(two, { name:'AbortError' })
  assert.equal(upstreamSignal.aborted, true)
  waiting.reject(new DOMException('aborted','AbortError'))
})

test('失败不会污染后续读取，已取消的订阅不会启动网络', async () => {
  let calls = 0
  const request = createReadRequestPool(() => {
    calls++
    return calls === 1 ? Promise.reject(new Error('network')) : Promise.resolve(Response.json({ ok:true }))
  })
  const [a,b] = await Promise.allSettled([request('/api/items'),request('/api/items')])
  assert.equal(a.status,'rejected')
  assert.equal(b.status,'rejected')
  assert.equal(calls,1)
  assert.deepEqual(await (await request('/api/items')).json(),{ ok:true })
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(request('/api/items',{ signal:controller.signal }),{ name:'AbortError' })
  assert.equal(calls,2)
})
