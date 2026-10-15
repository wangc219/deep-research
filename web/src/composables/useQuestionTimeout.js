import { computed, onUnmounted, ref, watch } from 'vue'
import { buildRecommendedAnswers } from '@/utils/questionUtils'

const TIMEOUT_MS = 120_000

/** 给未作答的澄清问题计时；按运行标识保留刷新和切换前的截止时间。 */
export function useQuestionTimeout({ visible, enabled, requestKey, questions, submit }) {
  const secondsRemaining = ref(null)
  const manual = ref(false)
  let interval
  let deadline
  let storageKey

  const stop = () => {
    clearInterval(interval)
    interval = undefined
    secondsRemaining.value = null
  }

  const readState = () => {
    try {
      return JSON.parse(window.sessionStorage.getItem(storageKey))
    } catch {
      return null
    }
  }

  const saveState = (state) => {
    if (!storageKey) return
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(state))
    } catch {
      // 浏览器禁止存储时，当前页面仍正常计时。
    }
  }

  const markInteracted = () => {
    manual.value = true
    saveState({ manual: true })
    stop()
  }

  const tick = () => {
    if (!visible.value || !enabled.value || manual.value) return stop()
    secondsRemaining.value = Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
    if (secondsRemaining.value > 0) return
    const answers = buildRecommendedAnswers(questions.value)
    markInteracted()
    if (answers) submit(answers)
  }

  watch(
    () => [visible.value, enabled.value, requestKey.value, JSON.stringify(questions.value)],
    () => {
      stop()
      storageKey = requestKey.value ? `question-timeout:${requestKey.value}` : null
      const saved = storageKey ? readState() : null
      manual.value = Boolean(saved?.manual)
      if (!visible.value || !enabled.value || manual.value || !buildRecommendedAnswers(questions.value)) return
      deadline = Number.isFinite(saved?.deadline) ? saved.deadline : Date.now() + TIMEOUT_MS
      saveState({ deadline })
      // 等本轮 props 和表单重置完成，避免恢复已到期问题时使用旧表单。
      interval = setInterval(tick, 250)
      secondsRemaining.value = Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
    },
    { immediate: true }
  )

  onUnmounted(stop)
  const countdown = computed(() => {
    const seconds = secondsRemaining.value
    if (seconds === null) return ''
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
  })

  return { countdown, manual, markInteracted }
}
