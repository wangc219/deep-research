/** 多个页面共享计时器；隐藏时暂停，每个订阅独立等待自己的刷新完成。 */
export function createPollingScheduler({
  schedule = setTimeout,
  cancel = clearTimeout,
  now = Date.now,
  visible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden'
} = {}) {
  const subscriptions = new Map()
  let timer = null
  let timerAt = null

  const arm = () => {
    const idle = [...subscriptions.values()].filter((entry) => !entry.running)
    if (!idle.length) return
    const delay = visible()
      ? Math.max(50, Math.min(...idle.map((entry) => entry.nextAt - now())))
      : 1000
    const nextAt = now() + delay
    if (timer !== null && timerAt <= nextAt) return
    if (timer !== null) cancel(timer)
    timerAt = nextAt
    timer = schedule(tick, delay)
  }
  const tick = async () => {
    timer = null
    timerAt = null
    const requests = []
    if (visible()) {
      const due = [...subscriptions.entries()].filter(([, entry]) => !entry.running && entry.nextAt <= now())
      for (const [key, entry] of due) {
        if (!subscriptions.has(key)) continue
        entry.running = true
        requests.push((async () => {
          try {
            await entry.callback()
          } finally {
            entry.running = false
            entry.nextAt = now() + entry.interval
            // 慢查询只暂停自己的订阅，不阻塞其他页面的状态刷新。
            if (subscriptions.has(key)) arm()
          }
        })())
      }
    }
    arm()
    await Promise.allSettled(requests)
  }
  const subscribe = (callback, interval) => {
    const key = Symbol('polling')
    subscriptions.set(key, { callback, interval, nextAt: now() + interval, running: false })
    arm()
    return () => {
      subscriptions.delete(key)
      if (!subscriptions.size && timer !== null) {
        cancel(timer)
        timer = null
        timerAt = null
      }
    }
  }
  return { subscribe }
}

export const sharedPolling = createPollingScheduler()
