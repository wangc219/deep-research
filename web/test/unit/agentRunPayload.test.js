import assert from 'node:assert/strict'
import path from 'node:path'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { createServer } from 'vite'

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
let server
let buildAgentRunPayload

before(async () => {
  const storage = new Map()
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key)
  }
  server = await createServer({ root: webRoot, server: { middlewareMode: true } })
  ;({ buildAgentRunPayload } = await server.ssrLoadModule('/src/apis/agent_api.js'))
})

after(async () => {
  await server?.close()
  delete globalThis.localStorage
})

test('edited question sends its persisted message id to the run API', () => {
  assert.equal(
    buildAgentRunPayload({
      query: 'edited',
      agent_slug: 'main',
      thread_id: 'thread-1',
      replace_message_id: 42
    }).replace_message_id,
    42
  )
  assert.equal(
    buildAgentRunPayload({ query: 'new', agent_slug: 'main', thread_id: 'thread-1' })
      .replace_message_id,
    null
  )
})
