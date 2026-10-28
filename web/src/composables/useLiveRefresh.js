import { onActivated, onDeactivated, onMounted, onUnmounted } from 'vue'
import { sharedPolling } from '@/utils/sharedPolling'
import { createRefreshController, subscribeDataChanges } from '@/utils/dataFreshness'

/** 只刷新可见的活动页面，切回页面或用户写入后合并刷新。 */
export function useLiveRefresh(refresh, { interval = 15000, enabled = () => true } = {}) {
  let active = false
  let controller
  let unsubscribe
  let stopPolling
  const request = () => controller?.request()
  const visible = () => active && enabled() && document.visibilityState !== 'hidden'
  const start = () => {
    if (active) return
    const returning = Boolean(controller)
    active = true
    controller = createRefreshController(refresh, { enabled: visible })
    unsubscribe = subscribeDataChanges(request)
    stopPolling = sharedPolling.subscribe(request, interval)
    window.addEventListener('focus', request)
    document.addEventListener('visibilitychange', request)
    if (returning) request()
  }
  const stop = () => {
    active = false
    controller?.stop()
    unsubscribe?.()
    stopPolling?.()
    window.removeEventListener('focus', request)
    document.removeEventListener('visibilitychange', request)
  }
  onMounted(start)
  onActivated(start)
  onDeactivated(stop)
  onUnmounted(stop)
  return { request }
}
