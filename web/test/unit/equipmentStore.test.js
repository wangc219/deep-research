import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

globalThis.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {}
}

test('装备资源并发读取合并为单次请求', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  setActivePinia(createPinia())
  try {
    const { equipmentApi } = await server.ssrLoadModule('/src/apis/equipment_api.js')
    let calls = 0
    let resolveRuns
    equipmentApi.listRuns = () => {
      calls += 1
      return new Promise((resolve) => { resolveRuns = resolve })
    }
    const { useEquipmentStore } = await server.ssrLoadModule('/src/stores/equipment.js')
    const store = useEquipmentStore()
    const first = store.loadResource('runs')
    const second = store.loadResource('runs')
    await Promise.resolve()

    assert.equal(calls, 1)
    resolveRuns([{ run_id: 'run-1' }])
    assert.deepEqual(await first, [{ run_id: 'run-1' }])
    assert.deepEqual(await second, [{ run_id: 'run-1' }])
    assert.deepEqual(store.resources.runs, [{ run_id: 'run-1' }])
    assert.equal(store.loaded.runs, true)
    assert.equal(store.loading.runs, false)
  } finally {
    await server.close()
  }
})

test('退出登录使装备缓存失效且迟到响应不能跨账号写回', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  setActivePinia(createPinia())
  try {
    const { equipmentApi } = await server.ssrLoadModule('/src/apis/equipment_api.js')
    let resolveCapabilities
    equipmentApi.listCapabilities = () => new Promise((resolve) => { resolveCapabilities = resolve })
    const { useEquipmentStore } = await server.ssrLoadModule('/src/stores/equipment.js')
    const { useUserStore } = await server.ssrLoadModule('/src/stores/user.js')
    const store = useEquipmentStore()
    const pending = store.loadResource('capabilities')
    await Promise.resolve()

    useUserStore().logout()
    resolveCapabilities([{ id: 'account-a-card' }])
    await pending

    assert.deepEqual(store.resources.capabilities, [])
    assert.equal(store.loaded.capabilities, undefined)
    assert.equal(store.loading.capabilities, undefined)
  } finally {
    await server.close()
  }
})
