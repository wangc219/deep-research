import { ref } from 'vue'
import { defineStore } from 'pinia'
import { equipmentApi } from '@/apis/equipment_api'

const RESOURCE_LOADERS = {
  runs: (params) => equipmentApi.listRuns(params),
  queries: (params) => equipmentApi.listQueries(params),
  queryGenerations: (params) => equipmentApi.listQueryGenerations(params),
  capabilities: () => equipmentApi.listCapabilities(),
  favorites: () => equipmentApi.listFavorites(),
  reports: () => equipmentApi.listReports(),
  deepSessions: () => equipmentApi.listDeepSessions()
}

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'archived'])

const emptyResources = () => ({
  runs: [],
  queries: [],
  queryGenerations: [],
  capabilities: [],
  favorites: [],
  reports: [],
  deepSessions: []
})

/**
 * 装备研究域的统一读取缓存。
 *
 * 同一资源的并发读取合并为一个请求；reset 会递增会话版本，使退出
 * 登录前的迟到响应无法写入下一账号。写操作仍由页面显式调用 API，
 * 成功后按资源刷新，避免用乐观状态覆盖后端终态。
 */
export const useEquipmentStore = defineStore('equipment', () => {
  const resources = ref(emptyResources())
  const loading = ref({})
  const loaded = ref({})
  const errors = ref({})
  let sessionVersion = 0
  const pending = new Map()
  const latestRequests = new Map()

  const loadResource = async (name, params = {}) => {
    const loader = RESOURCE_LOADERS[name]
    if (!loader) throw new Error(`未知装备资源: ${name}`)
    const requestKey = `${name}:${JSON.stringify(Object.entries(params).sort(([left], [right]) => left.localeCompare(right)))}`
    // force 表示主动刷新，也应合并相同参数的在途请求。
    if (pending.has(requestKey)) return pending.get(requestKey)

    const requestSession = sessionVersion
    const requestId = Symbol(name)
    latestRequests.set(name, requestId)
    loading.value = { ...loading.value, [name]: true }
    errors.value = { ...errors.value, [name]: '' }
    const request = Promise.resolve()
      .then(() => loader(params))
      .then((items) => {
        if (requestSession !== sessionVersion || latestRequests.get(name) !== requestId) return resources.value[name]
        const rows = Array.isArray(items) ? items : (items?.items || [])
        const previous = new Map(resources.value[name].map((item) => [item.run_id, item.status]))
        if (name === 'runs' && rows.some((item) => (
          previous.has(item.run_id) && previous.get(item.run_id) !== item.status && TERMINAL_STATUSES.has(item.status)
        ))) {
          void Promise.allSettled(['capabilities', 'reports', 'favorites', 'deepSessions'].map((resource) => loadResource(resource)))
        }
        resources.value = { ...resources.value, [name]: rows }
        loaded.value = { ...loaded.value, [name]: true }
        return rows
      })
      .catch((error) => {
        if (requestSession === sessionVersion && latestRequests.get(name) === requestId) {
          errors.value = { ...errors.value, [name]: error?.message || '加载失败' }
        }
        throw error
      })
      .finally(() => {
        if (pending.get(requestKey) === request) pending.delete(requestKey)
        if (requestSession === sessionVersion && latestRequests.get(name) === requestId) {
          loading.value = { ...loading.value, [name]: false }
        }
      })

    pending.set(requestKey, request)
    return request
  }

  const refreshWorkspace = async () => {
    const names = ['runs', 'capabilities', 'favorites', 'reports', 'deepSessions']
    return Promise.all(names.map((name) => loadResource(name, {}, { force: true })))
  }

  const reset = () => {
    sessionVersion += 1
    pending.clear()
    latestRequests.clear()
    resources.value = emptyResources()
    loading.value = {}
    loaded.value = {}
    errors.value = {}
  }

  return {
    resources,
    loading,
    loaded,
    errors,
    loadResource,
    refreshWorkspace,
    reset
  }
})
