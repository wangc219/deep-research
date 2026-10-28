import { apiGet, apiPost, apiDelete } from './base'

const base = '/api/knowledge/wxchannels'
export const wxchannelsApi = {
  revokeCollector: (id) => apiDelete(`${base}/collector/devices/${encodeURIComponent(id)}`),
  connect: () => apiPost(`${base}/connect`, {}),
  collectorPackage: (payload) =>
    apiPost(`${base}/collector/package`, payload, {}, true, 'blob').then((response) =>
      response.blob()
    ),
  status: (mode = 'central') => apiGet(`${base}/status?mode=${encodeURIComponent(mode)}`),
  channels: () => apiGet(`${base}/channels`),
  channelVideos: (id, offset = 0, filters = {}) => {
    const params = new URLSearchParams({ offset: String(offset), limit: '20' })
    for (const [key, value] of Object.entries(filters))
      if (value !== null && value !== undefined && value !== '') params.set(key, String(value))
    return apiGet(`${base}/channels/${encodeURIComponent(id)}/videos?${params}`)
  },
  deleteChannel: (id) => apiDelete(`${base}/channels/${encodeURIComponent(id)}`),
  videos: (payload) => apiPost(`${base}/videos`, payload),
  transcribe: (payload) => apiPost(`${base}/transcribe`, payload),
  tasks: () => apiGet(`${base}/tasks`),
  task: (id) => apiGet(`${base}/tasks/${encodeURIComponent(id)}`),
  cancel: (id) => apiPost(`${base}/tasks/${encodeURIComponent(id)}/cancel`),
  deleteHistory: (id) => apiDelete(`${base}/tasks/${encodeURIComponent(id)}`),
  download: (id, index) =>
    apiGet(`${base}/tasks/${encodeURIComponent(id)}/items/${index}/docx`, {}, true, 'blob').then(
      (response) => response.blob()
    ),
  archive: (id) =>
    apiGet(`${base}/tasks/${encodeURIComponent(id)}/archive`, {}, true, 'blob').then((response) =>
      response.blob()
    ),
  import: (kb, payload) => apiPost(`${base}/databases/${encodeURIComponent(kb)}/import`, payload)
}
