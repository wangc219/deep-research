import { apiGet, apiPost } from './base'

const base = '/api/knowledge/collection-artifacts'
export const collectionArtifactApi = {
  list: (source) => apiGet(`${base}/${source}`),
  sync: (source) => apiPost(`${base}/${source}/sync`, {}),
  archive: (source, ids) => apiPost(`${base}/${source}/archive`, { ids }, {}, true, 'blob').then(response => response.blob())
}
