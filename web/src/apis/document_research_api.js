const PREFIX = '/document-research-api'
export const DOCUMENT_TOKEN_KEY = 'document-research.token.v1'
export const documentTaskKey = (user) => `document-research.task.v1.${encodeURIComponent(user)}`

export class DocumentResearchError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'DocumentResearchError'
    this.status = status
  }
}

// 本入口只携带专用 token；不导入平台 client，不附带浏览器 cookie。
export function createDocumentResearchApi(getToken, fetcher = globalThis.fetch) {
  async function request(path, { method = 'GET', body, signal, publicRequest = false, timeout = 60000, blob = false } = {}) {
    const token = getToken()?.trim()
    if (!publicRequest && !token) throw new DocumentResearchError('请输入文档研发服务的专用访问令牌。', 401)
    const headers = { Accept: 'application/json' }
    if (!publicRequest) headers.Authorization = `Bearer ${token}`
    const isForm = body instanceof FormData
    if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
    let response
    const timeoutSignal = AbortSignal.timeout(timeout)
    try {
      response = await fetcher(`${PREFIX}${path}`, {
        method, headers, credentials: 'omit', redirect: 'error',
        body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
        signal: signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal
      })
    } catch (error) {
      if (signal?.aborted) throw error
      if (timeoutSignal.aborted) throw new DocumentResearchError('等待服务响应超时。远端请求可能仍在执行，请稍后再试。')
      throw new DocumentResearchError('无法连接文档研发服务，请确认本机 4198 端口已启动，再重试。')
    }
    if (response.ok && blob) return response.blob()
    let data
    try { data = await response.json() } catch {
      throw new DocumentResearchError('服务返回了非 JSON 响应，请检查专用服务及代理配置。', response.status)
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : '请求未成功，请检查输入或服务日志。'
      throw new DocumentResearchError(detail, response.status)
    }
    return data
  }
  const id = encodeURIComponent
  return {
    health: () => request('/health', { publicRequest: true }),
    session: () => request('/session'),
    modelSettings: () => request('/settings/model'),
    saveModelSettings: (body) => request('/settings/model', { method: 'PUT', body }),
    artifacts: (taskId) => request(`/tasks/${id(taskId)}/artifacts`),
    artifact: (taskId, name) => request(`/tasks/${id(taskId)}/artifacts/${id(name)}`),
    saveArtifact: (taskId, name, body) => request(`/tasks/${id(taskId)}/artifacts/${id(name)}`, { method: 'PUT', body }),
    downloadArtifact: (taskId, name) => request(`/tasks/${id(taskId)}/artifacts/${id(name)}/download`, { blob: true }),
    downloadBundle: (taskId) => request(`/tasks/${id(taskId)}/delivery.zip`, { blob: true }),
    libraries: () => request('/libraries'),
    createLibrary: (name) => request('/libraries', { method: 'POST', body: { name } }),
    deleteLibrary: (libraryId) => request(`/libraries/${id(libraryId)}`, { method: 'DELETE' }),
    documents: (libraryId) => request(`/libraries/${id(libraryId)}/documents`),
    upload: (libraryId, file) => {
      const body = new FormData()
      body.append('file', file)
      return request(`/libraries/${id(libraryId)}/documents`, { method: 'POST', body })
    },
    document: (documentId) => request(`/documents/${id(documentId)}`),
    deleteDocument: (documentId) => request(`/documents/${id(documentId)}`, { method: 'DELETE' }),
    retrieve: (body, signal) => request('/retrieve', { method: 'POST', body, signal, timeout: 150000 }),
    createTask: (body) => request('/tasks', { method: 'POST', body }),
    task: (taskId, signal) => request(`/tasks/${id(taskId)}`, { signal }),
    updateTask: (taskId, body) => request(`/tasks/${id(taskId)}`, { method: 'PATCH', body }),
    runTask: (taskId) => request(`/tasks/${id(taskId)}/run`, { method: 'POST', body: {} }),
    cancelTask: (taskId) => request(`/tasks/${id(taskId)}/cancel`, { method: 'POST', body: {} })
  }
}

export function safeSourceUrl(value) {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch { return null }
}

// 切页、切账号、换任务时 stop() 会阻止在途旧响应写入新页面。
export function createDocumentTaskMonitor({ readTask, onTask, onError, delay = 1500, schedule = setTimeout, unschedule = clearTimeout }) {
  let generation = 0
  let timer
  let controller
  function stop() {
    generation += 1
    unschedule(timer)
    controller?.abort()
  }
  function start(taskId) {
    stop()
    const current = generation
    async function poll() {
      controller = new AbortController()
      try {
        const task = await readTask(taskId, controller.signal)
        if (current !== generation) return
        onTask(task)
        if (task.status === 'running') timer = schedule(poll, delay)
      } catch (error) {
        if (current !== generation) return
        onError(error)
        if (![401, 403, 404].includes(error.status)) timer = schedule(poll, delay * 2)
      }
    }
    void poll()
  }
  return { start, stop }
}

// 启动请求只发一次。响应丢失时读取已知任务的状态，不能自动重发可能产生费用的请求。
export async function runDocumentTaskOnce({ taskId, runTask, isCurrent, onTask, onPending, onError, onUnknown, monitor }) {
  if (!isCurrent()) return
  onPending(true)
  try {
    const task = await runTask(taskId)
    if (!isCurrent()) return
    onPending(false)
    onTask(task)
    if (task.status === 'running') monitor.start(taskId)
  } catch (error) {
    if (!isCurrent()) return
    if ([401, 403, 404].includes(error.status)) {
      onPending(false)
      monitor.stop()
      onError(error)
    } else {
      onUnknown(error)
      monitor.start(taskId)
    }
  }
}

// 预览不生成任务；停止等待或修改资料范围后，任何旧响应都不能重新出现。
export function createDocumentRetrievalPreview({ retrieve, onResult, onError, onLoading }) {
  let generation = 0
  let controller
  function stop() {
    generation += 1
    controller?.abort()
    onLoading(false)
  }
  async function start(payload) {
    stop()
    const current = generation
    controller = new AbortController()
    onLoading(true)
    try {
      const result = await retrieve(payload, controller.signal)
      if (current === generation) onResult(result)
    } catch (error) {
      if (current === generation) onError(error)
    } finally {
      if (current === generation) onLoading(false)
    }
  }
  return { start, stop }
}
