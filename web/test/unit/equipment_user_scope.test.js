import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

test('登录身份同步到研究工作台存储作用域并在退出时清除', async () => {
  const previousStorage = globalThis.localStorage
  const previousScope = globalThis.__EQUIPMENT_USER_ID__
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => '', setItem: () => {}, removeItem: () => {} }
  })
  const server = await createServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom'
  })
  setActivePinia(createPinia())
  try {
    const { useUserStore } = await server.ssrLoadModule('/src/stores/user.js')
    const { useAgentStore } = await server.ssrLoadModule('/src/stores/agent.js')
    const { useProjectsStore } = await server.ssrLoadModule('/src/stores/projects.js')
    const { useEquipmentStore } = await server.ssrLoadModule('/src/stores/equipment.js')
    const { authApi } = await server.ssrLoadModule('/src/apis/auth_api.js')
    authApi.login = async () => ({
      access_token: 'token', user_id: 1, username: 'a', uid: 'user-a', role: 'user'
    })
    const store = useUserStore()
    const agentStore = useAgentStore()
    agentStore.agents = [{ id: 'previous-user-agent' }]
    agentStore.isInitialized = true
    await store.login({ username: 'a', password: 'secret' })
    assert.equal(globalThis.__EQUIPMENT_USER_ID__, 'user-a')
    assert.deepEqual(agentStore.agents, [])
    assert.equal(agentStore.isInitialized, false)
    const projectsStore = useProjectsStore()
    const equipmentStore = useEquipmentStore()
    projectsStore.projects = [{ id: 'owner-project' }]
    projectsStore.hasLoaded = true
    equipmentStore.resources = { ...equipmentStore.resources, runs: [{ run_id: 'owner-run' }] }
    equipmentStore.loaded = { runs: true }
    agentStore.agents = [{ id: 'user-role-agent' }]
    agentStore.isInitialized = true
    authApi.getCurrentUser = async () => ({
      id: 1, username: 'a', uid: 'user-a', role: 'admin'
    })
    await store.getCurrentUser()
    assert.equal(store.isAdmin, true)
    assert.equal(store.userRole, 'admin')
    assert.deepEqual(agentStore.agents, [])
    assert.equal(agentStore.isInitialized, false)
    assert.deepEqual(projectsStore.projects, [])
    assert.equal(projectsStore.hasLoaded, false)
    assert.deepEqual(equipmentStore.resources.runs, [])
    assert.deepEqual(equipmentStore.loaded, {})
    store.logout()
    assert.equal(globalThis.__EQUIPMENT_USER_ID__, undefined)
  } finally {
    await server.close()
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: previousStorage })
    if (previousScope === undefined) delete globalThis.__EQUIPMENT_USER_ID__
    else globalThis.__EQUIPMENT_USER_ID__ = previousScope
  }
})
