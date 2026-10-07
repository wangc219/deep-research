import { apiGet, apiPost, apiDelete, apiRequest } from './base'

export const enterpriseApi = {
  organization: () => apiGet('/api/enterprise/organization'),
  monitoring: () => apiGet('/api/enterprise/monitoring'),
  permissions: () => apiGet('/api/enterprise/permissions/me'),
  createTenant: (body) => apiPost('/api/enterprise/tenants', body),
  updateTenant: (id, body) =>
    apiRequest(`/api/enterprise/tenants/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteTenant: (id) => apiDelete(`/api/enterprise/tenants/${id}`),
  createDepartment: (body) => apiPost('/api/departments', body),
  setDepartment: (id, body) =>
    apiRequest(`/api/enterprise/departments/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteDepartment: (id) => apiDelete(`/api/departments/${id}`),
  saveRule: (body) =>
    apiRequest('/api/enterprise/permissions', { method: 'PUT', body: JSON.stringify(body) }),
  deleteRule: (id) => apiDelete(`/api/enterprise/permissions/${id}`)
}
