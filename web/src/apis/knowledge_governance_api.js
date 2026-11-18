import { apiDelete, apiGet, apiPost, apiRequest, buildQuery } from './base'

const patch = (url, data) =>
  apiRequest(url, { method: 'PATCH', body: JSON.stringify(data) }, true, 'json')

export const knowledgeGovernanceApi = {
  categories: (includeInactive = false) =>
    apiGet(`/api/knowledge/categories?${buildQuery({ include_inactive: includeInactive })}`),
  createCategory: (data) => apiPost('/api/knowledge/categories', data),
  updateCategory: (id, data) => patch(`/api/knowledge/categories/${encodeURIComponent(id)}`, data),
  deleteCategory: (id) => apiDelete(`/api/knowledge/categories/${encodeURIComponent(id)}`),
  sources: (kbId) => apiGet(`/api/knowledge/sources?${buildQuery({ kb_id: kbId })}`),
  createSource: (data) => apiPost('/api/knowledge/sources', data),
  updateSource: (id, data) => patch(`/api/knowledge/sources/${encodeURIComponent(id)}`, data),
  deleteSource: (id) => apiDelete(`/api/knowledge/sources/${encodeURIComponent(id)}`),
  testSource: (id) => apiPost(`/api/knowledge/sources/${encodeURIComponent(id)}/test`, {}),
  runSource: (id) => apiPost(`/api/knowledge/sources/${encodeURIComponent(id)}/run`, {}),
  sourceRuns: (id) => apiGet(`/api/knowledge/sources/${encodeURIComponent(id)}/runs`),
  staging: (params) => apiGet(`/api/knowledge/staging?${buildQuery(params)}`),
  reviewStaging: (data) => apiPost('/api/knowledge/staging/review', data)
}

export const innovationBriefApi = {
  subscriptions: () => apiGet('/api/knowledge/brief-subscriptions'),
  createSubscription: (data) => apiPost('/api/knowledge/brief-subscriptions', data),
  updateSubscription: (id, data) =>
    patch(`/api/knowledge/brief-subscriptions/${encodeURIComponent(id)}`, data),
  deleteSubscription: (id) =>
    apiDelete(`/api/knowledge/brief-subscriptions/${encodeURIComponent(id)}`),
  run: (id, briefType = 'daily') =>
    apiPost(`/api/knowledge/brief-subscriptions/${encodeURIComponent(id)}/run`, {
      brief_type: briefType
    }),
  runs: (subscriptionId = null) =>
    apiGet(`/api/knowledge/brief-subscriptions/runs?${buildQuery({ subscription_id: subscriptionId })}`),
  briefs: (params = {}) => apiGet(`/api/knowledge/briefs?${buildQuery(params)}`),
  brief: (id) => apiGet(`/api/knowledge/briefs/${encodeURIComponent(id)}`),
  markRead: (id, read = true) =>
    apiPost(`/api/knowledge/briefs/${encodeURIComponent(id)}/read`, { read })
}
