import { apiPost, apiDelete, apiGet } from './base'

export const wechatMpApi = {
  openSession: () => apiPost('/api/wechat-mp/session', {}),
  document: () => apiGet('/api/wechat-mp/app/index.html', {}, true, 'text'),
  closeSession: () => apiDelete('/api/wechat-mp/session')
}
