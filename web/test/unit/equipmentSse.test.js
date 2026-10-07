import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AuthenticatedEventSource } from '../../src/utils/authenticatedEventSource.js'

test('研究 SSE 携带认证头、解析跨数据块事件，并保留恢复游标', async (t) => {
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => 'test-token' } })
  t.after(() => {
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage)
    else delete globalThis.localStorage
  })
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    const encoder = new TextEncoder()
    return new Response(new ReadableStream({ start(controller) {
      for (const chunk of ['id: 42\r\nevent: progres', 's\r\ndata: 第一行\r\n', 'data: 第二行\r\n\r\n']) controller.enqueue(encoder.encode(chunk))
      controller.close()
    } }), { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const events = new AuthenticatedEventSource('/api/v1/runs/owned/events')
  t.after(() => events.close())
  const event = await new Promise(resolve => events.addEventListener('progress', resolve, { once: true }))
  assert.equal(event.data, '第一行\n第二行')
  assert.equal(event.lastEventId, '42')
  assert.equal(calls[0].options.headers.Authorization, 'Bearer test-token')
  assert.equal(calls[0].url.includes('test-token'), false)
  events.close()
})

test('研究 SSE 权限被撤销时停止重连', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 403 }))
  const events = new AuthenticatedEventSource('/api/v1/runs/denied/events')
  await new Promise(resolve => { events.onerror = resolve })
  assert.equal(events.readyState, AuthenticatedEventSource.CLOSED)
  assert.equal(events.retry, undefined)
})
