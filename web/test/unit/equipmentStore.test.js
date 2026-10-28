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

test('主动刷新合并相同参数请求，不同参数的迟到结果不能覆盖新筛选', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  setActivePinia(createPinia())
  try {
    const { equipmentApi } = await server.ssrLoadModule('/src/apis/equipment_api.js')
    const resolvers = []
    equipmentApi.listRuns = () => new Promise((resolve) => { resolvers.push(resolve) })
    const { useEquipmentStore } = await server.ssrLoadModule('/src/stores/equipment.js')
    const store = useEquipmentStore()
    const first = store.loadResource('runs', { status: 'draft' })
    const duplicate = store.loadResource('runs', { status: 'draft' }, { force: true })
    const second = store.loadResource('runs', { status: 'completed' })
    await Promise.resolve()
    assert.equal(resolvers.length, 2)
    resolvers[1]([{ run_id: 'new', status: 'completed' }])
    await second
    resolvers[0]([{ run_id: 'old', status: 'draft' }])
    await Promise.all([first, duplicate])
    assert.equal(store.resources.runs[0].run_id, 'new')
    assert.equal(store.loading.runs, false)
  } finally {
    await server.close()
  }
})

test('任务转为终态后统一刷新报告、画像、收藏和深研会话', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  setActivePinia(createPinia())
  try {
    const { equipmentApi } = await server.ssrLoadModule('/src/apis/equipment_api.js')
    const calls = []
    for (const name of ['listCapabilities', 'listReports', 'listFavorites', 'listDeepSessions']) {
      equipmentApi[name] = async () => { calls.push(name); return [] }
    }
    equipmentApi.listRuns = async () => [{ run_id: 'r', status: 'completed' }]
    const { useEquipmentStore } = await server.ssrLoadModule('/src/stores/equipment.js')
    const store = useEquipmentStore()
    store.resources.runs = [{ run_id: 'r', status: 'researching' }]
    await store.loadResource('runs')
    assert.deepEqual(calls.sort(), ['listCapabilities', 'listDeepSessions', 'listFavorites', 'listReports'])
  } finally {
    await server.close()
  }
})
