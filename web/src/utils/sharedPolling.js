/** 多个页面共享一个调度器；隐藏标签页暂停请求，每个订阅等待上次刷新完成。 */
export function createPollingScheduler({
  schedule = setTimeout,
  cancel = clearTimeout,
  now = Date.now,
  visible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden'
} = {}) {
  const subscriptions = new Map()
  let timer = null
  let running = false

  const arm = () => {
    if (timer !== null || running || !subscriptions.size) return
    const delay = Math.max(50, Math.min(...[...subscriptions.values()].map((entry) => entry.nextAt - now())))
    timer = schedule(tick, visible() ? delay : 1000)
  }
  const tick = async () => {
    timer = null
    running = true
    if (visible()) {
      const due = [...subscriptions.values()].filter((entry) => entry.nextAt <= now())
      await Promise.allSettled(due.map(async (entry) => {
        try {
          await entry.callback()
        } finally {
          entry.nextAt = now() + entry.interval
        }
      }))
    }
    running = false
    arm()
  }
  const subscribe = (callback, interval) => {
    const key = Symbol('polling')
    subscriptions.set(key, { callback, interval, nextAt: now() + interval })
    arm()
    return () => {
      subscriptions.delete(key)
      if (!subscriptions.size && timer !== null) {
        cancel(timer)
        timer = null
      }
    }
  }
  return { subscribe }
}

export const sharedPolling = createPollingScheduler()
