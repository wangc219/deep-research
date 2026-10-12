export const AMINER_DEFAULTS = {
  enabled: false,
  user_id: '',
  chat_budget_cents: 20,
  deep_budget_cents: 50,
  chat_search_limit: 2,
  chat_detail_limit: 3,
  chat_reference_limit: 1,
  deep_search_limit: 6,
  deep_detail_limit: 10,
  deep_reference_limit: 2
}

export const createAMinerDraft = (option) => ({
  ...AMINER_DEFAULTS,
  ...(option?.value || {}),
  api_key: '',
  chat_budget_yuan: Number(option?.value?.chat_budget_cents ?? 20) / 100,
  deep_budget_yuan: Number(option?.value?.deep_budget_cents ?? 50) / 100
})

export const buildAMinerConfigPatch = (draft) => {
  const value = Object.fromEntries(Object.keys(AMINER_DEFAULTS).map((key) => [key, draft[key]]))
  value.user_id = String(draft.user_id || '').trim()
  value.chat_budget_cents = Math.round(Number(draft.chat_budget_yuan) * 100)
  value.deep_budget_cents = Math.round(Number(draft.deep_budget_yuan) * 100)
  const apiKey = String(draft.api_key || '').trim()
  if (apiKey) value.api_key = apiKey
  return value
}

export const parseAcademicResult = (content) => {
  try {
    let value = content
    if (Array.isArray(value))
      value = value
        .filter((item) => item?.type === 'text')
        .map((item) => item.text)
        .join('')
    if (typeof value === 'string') value = JSON.parse(value)
    return value && typeof value === 'object' ? value : { results: [] }
  } catch {
    return { status: 'unavailable', results: [], message: '论文检索结果暂时无法读取' }
  }
}

export const academicSourceUrl = (url) => {
  try {
    const source = new URL(url)
    return source.protocol === 'https:' || source.protocol === 'http:' ? source.href : ''
  } catch {
    return ''
  }
}

export const ACADEMIC_LEVEL_LABELS = {
  metadata: '题录',
  partial_abstract: '部分摘要',
  abstract: '完整摘要'
}
