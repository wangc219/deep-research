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

  const loadResource = async (name, params = {}, { force = false } = {}) => {
    const loader = RESOURCE_LOADERS[name]
    if (!loader) throw new Error(`未知装备资源: ${name}`)
    if (!force && pending.has(name)) return pending.get(name)

    const requestSession = sessionVersion
    loading.value = { ...loading.value, [name]: true }
    errors.value = { ...errors.value, [name]: '' }
    const request = Promise.resolve()
      .then(() => loader(params))
      .then((items) => {
        if (requestSession !== sessionVersion) return resources.value[name]
        const rows = Array.isArray(items) ? items : []
        resources.value = { ...resources.value, [name]: rows }
        loaded.value = { ...loaded.value, [name]: true }
        return rows
      })
      .catch((error) => {
        if (requestSession === sessionVersion) {
          errors.value = { ...errors.value, [name]: error?.message || '加载失败' }
        }
        throw error
      })
      .finally(() => {
        if (pending.get(name) === request) pending.delete(name)
        if (requestSession === sessionVersion) {
          loading.value = { ...loading.value, [name]: false }
        }
      })

    pending.set(name, request)
    return request
  }

  const refreshWorkspace = async () => {
    const names = ['runs', 'capabilities', 'favorites', 'reports', 'deepSessions']
    return Promise.all(names.map((name) => loadResource(name, {}, { force: true })))
  }

  const reset = () => {
    sessionVersion += 1
    pending.clear()
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
