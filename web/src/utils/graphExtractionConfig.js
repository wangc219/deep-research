export const DEFAULT_GRAPH_EXTRACTION_CONCURRENCY = 8
export const DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS = 180
export const DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS = 8192
export const DEFAULT_GRAPH_THINKING_BUDGET = 2048

export const graphPerformanceOptions = (options = {}) => ({
  max_output_tokens:
    options.model_params?.max_tokens ??
    options.model_params?.max_completion_tokens ??
    options.max_output_tokens ??
    DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS,
  enable_thinking:
    options.model_params?.extra_body?.enable_thinking ?? options.enable_thinking ?? true,
  thinking_budget:
    options.model_params?.extra_body?.thinking_budget ??
    options.thinking_budget ??
    DEFAULT_GRAPH_THINKING_BUDGET
})

export const unmanagedGraphModelParams = (params = {}) => {
  const result = { ...params }
  delete result.max_tokens
  delete result.max_completion_tokens
  if (result.extra_body && typeof result.extra_body === 'object') {
    result.extra_body = { ...result.extra_body }
    delete result.extra_body.enable_thinking
    delete result.extra_body.thinking_budget
    if (!Object.keys(result.extra_body).length) delete result.extra_body
  }
  return result
}

export const GRAPH_EXTRACTION_PRESETS = [
  {
    key: 'stable',
    label: '稳定',
    concurrency_count: 4,
    timeout_seconds: 300,
    enable_thinking: true,
    thinking_budget: 4096,
    max_output_tokens: DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS,
    description: '公网模型或频繁超时时使用'
  },
  {
    key: 'balanced',
    label: '均衡',
    concurrency_count: DEFAULT_GRAPH_EXTRACTION_CONCURRENCY,
    timeout_seconds: DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
    enable_thinking: true,
    thinking_budget: DEFAULT_GRAPH_THINKING_BUDGET,
    max_output_tokens: DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS,
    description: '推荐，兼顾稳定性与速度'
  },
  {
    key: 'fast',
    label: '快速',
    concurrency_count: 16,
    timeout_seconds: DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
    enable_thinking: false,
    thinking_budget: DEFAULT_GRAPH_THINKING_BUDGET,
    max_output_tokens: DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS,
    description: '关闭思考，适合简单文本；复杂关系建议均衡'
  }
]

export const applyGraphExtractionPreset = (target, key) => {
  const preset = GRAPH_EXTRACTION_PRESETS.find((item) => item.key === key)
  if (!preset) return false
  target.concurrency_count = preset.concurrency_count
  target.timeout_seconds = preset.timeout_seconds
  target.enable_thinking = preset.enable_thinking
  target.thinking_budget = preset.thinking_budget
  target.max_output_tokens = preset.max_output_tokens
  return true
}

export const matchGraphExtractionPreset = ({ concurrency_count, timeout_seconds }) => {
  return (
    GRAPH_EXTRACTION_PRESETS.find(
      (item) =>
        item.concurrency_count === Number(concurrency_count) &&
        item.timeout_seconds === Number(timeout_seconds)
    )?.key || 'custom'
  )
}

export const graphExtractionRiskMessage = ({ model_spec, concurrency_count, timeout_seconds }) => {
  const concurrency = Number(concurrency_count)
  const timeout = Number(timeout_seconds)
  const siliconFlow = /^siliconflow(?:-cn)?:/i.test(String(model_spec || ''))
  const messages = []

  if (siliconFlow && concurrency > 16) {
    messages.push(`SiliconFlow 并发 ${concurrency} 过高，运行时将自动限制为 16`)
  } else if (concurrency > 64) {
    messages.push(`并发 ${concurrency} 过高，运行时将自动限制为 64`)
  }
  if (timeout > 0 && timeout < 120) {
    messages.push(`单次超时仅 ${timeout} 秒，复杂 Schema 建议至少 180 秒`)
  }

  return messages.join('；')
}
