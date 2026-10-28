/** 仅广播资源类型；用户内容和身份凭据不进入跨标签页通知。 */
const EVENT = 'app:data-changed'
const STORAGE_KEY = 'app:data-version'

export function notifyDataChanged(resource = 'all') {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { resource } }))
  try {
    localStorage.setItem(STORAGE_KEY, `${Date.now()}:${Math.random()}`)
  } catch {
    // 禁止浏览器存储时，同一页面通知和定时刷新仍可工作。
  }
}

export function subscribeDataChanges(callback) {
  if (typeof window === 'undefined') return () => {}
  const onStorage = (event) => {
    if (event.key === STORAGE_KEY) callback()
  }
  window.addEventListener(EVENT, callback)
  window.addEventListener('storage', onStorage)
  return () => {
    window.removeEventListener(EVENT, callback)
    window.removeEventListener('storage', onStorage)
  }
}

/** 合并短时间内的更新通知；慢请求期间最多追加一次刷新。 */
export function createRefreshController(
  refresh,
  {
    schedule = setTimeout,
    cancel = clearTimeout,
    enabled = () => true,
    delay = 500,
    onError = () => {}
  } = {}
) {
  let timer = null
  let running = false
  let pending = false
  let stopped = false
  const request = () => {
    if (stopped || !enabled()) return
    pending = true
    if (running || timer !== null) return
    timer = schedule(run, delay)
  }
  const run = async () => {
    timer = null
    if (stopped || !enabled()) return
    pending = false
    running = true
    try {
      await refresh()
    } catch (error) {
      onError(error)
    } finally {
      running = false
      if (pending) request()
    }
  }
  return {
    request,
    stop() {
      stopped = true
      pending = false
      if (timer !== null) cancel(timer)
      timer = null
    }
  }
}
