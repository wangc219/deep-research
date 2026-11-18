import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { createServer } from 'vite'

test('新对话优先武器装备助手，不可用时才回退持久化智能体', async () => {
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => null, setItem() {}, removeItem() {} }
  })
  const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
  const server = await createServer({
    root: webRoot,
    server: { middlewareMode: true },
    appType: 'custom'
  })
  try {
    const { getPreferredAgentId } = await server.ssrLoadModule('/src/stores/agent.js')
    assert.equal(
      getPreferredAgentId(
        [
          { id: 'deep-research', name: '深度研究' },
          { id: 'default-chatbot', name: '武器装备助手', is_builtin: true },
          { id: 'research-explorer', name: '调研探索员', is_subagent: true }
        ],
        'deep-research'
      ),
      'default-chatbot'
    )
    assert.equal(
      getPreferredAgentId(
        [
          { id: 'deep-research', name: '深度研究' },
          { id: 'research-explorer', name: '调研探索员', is_subagent: true }
        ],
        'deep-research'
      ),
      'deep-research'
    )
  } finally {
    await server.close()
    if (previousStorage) Object.defineProperty(globalThis, 'localStorage', previousStorage)
    else delete globalThis.localStorage
  }
})
