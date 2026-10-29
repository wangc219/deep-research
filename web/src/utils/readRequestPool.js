/** 合并同身份、同参数的在途读取；每个调用方独立取消，响应完成后立即失效。 */
export function createReadRequestPool(fetchRequest) {
  const pending = new Map()
  return (url, options = {}) => {
    const signal = options.signal
    if (signal?.aborted) return Promise.reject(new DOMException('读取已取消', 'AbortError'))
    const { signal: ignoredSignal, ...requestOptions } = options
    void ignoredSignal
    const headers = [...new Headers(options.headers).entries()].sort(([a], [b]) => a.localeCompare(b))
    const key = JSON.stringify([url, { ...requestOptions, headers }])
    let entry = pending.get(key)
    if (!entry) {
      entry = { controller: new AbortController(), observers: new Set() }
      pending.set(key, entry)
      Promise.resolve().then(() => {
        if (entry.controller.signal.aborted) throw new DOMException('读取已取消', 'AbortError')
        return fetchRequest(url, { ...options, signal: entry.controller.signal })
      }).then((response) => {
        if (pending.get(key) === entry) pending.delete(key)
        const observers = [...entry.observers]
        // 每个调用方拥有独立响应体，不能共享已消费的 Response 或可变业务对象。
        const responses = observers.map((_, index) => index === observers.length - 1 ? response : response.clone())
        observers.forEach((observer, index) => observer.resolve(responses[index]))
      }).catch((error) => {
        if (pending.get(key) === entry) pending.delete(key)
        for (const observer of entry.observers) observer.reject(error)
      })
    }
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        entry.observers.delete(observer)
        signal?.removeEventListener('abort', abort)
      }
      const observer = {
        resolve(value) { cleanup(); resolve(value) },
        reject(error) { cleanup(); reject(error) }
      }
      const abort = () => {
        observer.reject(new DOMException('读取已取消', 'AbortError'))
        if (!entry.observers.size) {
          if (pending.get(key) === entry) pending.delete(key)
          entry.controller.abort()
        }
      }
      entry.observers.add(observer)
      signal?.addEventListener('abort', abort, { once: true })
    })
  }
}

export const pooledReadFetch = createReadRequestPool((url, options) => fetch(url, options))
