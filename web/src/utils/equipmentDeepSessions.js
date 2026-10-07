const text = (value) => String(value || '').trim()

export const deepSessionStatus = (session) =>
  text(session?.status || session?.payload?.status || 'active').toLowerCase() || 'active'

export const deepSessionStatusLabel = (status) =>
  ({
    active: '可继续',
    running: '思考中',
    queued: '待处理',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    partial: '部分完成',
    blocked: '已阻塞',
    rejected: '已驳回',
    archived: '已归档'
  })[text(status).toLowerCase()] || text(status) || '可继续'

export const splitDeepQueryDisplay = (value) => {
  const full = text(value)
  if (!full) {
    return {
      topic: '未命名 Query 任务',
      background: '',
      backgroundPreview: '',
      full: '',
      hasBackground: false
    }
  }
  const parts = full
    .split(/\n+/)
    .map((part) => part.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
  const topic = parts[0] || '未命名 Query 任务'
  const background = parts.slice(1).join(' ')
  return {
    topic,
    background,
    backgroundPreview: background.length > 42 ? `${background.slice(0, 42)}…` : background,
    full,
    hasBackground: Boolean(background)
  }
}

const sessionRunId = (session) =>
  text(session?.run_id || session?.parent_run_id || session?.payload?.parent_run_id || session?.payload?.run_id)

const snapshotQuery = (snapshot) => {
  if (Array.isArray(snapshot)) return snapshot.map(text).filter(Boolean).join('\n')
  if (!snapshot || typeof snapshot !== 'object') return text(snapshot)
  return [
    snapshot.query || snapshot.topic || snapshot.query_text,
    snapshot.supplemental_information || snapshot.background || snapshot.context
  ]
    .map(text)
    .filter(Boolean)
    .join('\n')
}

const queryForSession = (session, run) => {
  const runQuery = [run?.topic, run?.supplemental_information].map(text).filter(Boolean).join('\n')
  return (
    runQuery ||
    snapshotQuery(session?.payload?.query_snapshot) ||
    text(session?.payload?.query) ||
    text(session?.topic) ||
    text(session?.title) ||
    '未命名 Query 任务'
  )
}

const timestamp = (value) => {
  const parsed = Date.parse(value || '')
  return Number.isFinite(parsed) ? parsed : 0
}

export const normalizeDeepSessions = (payload) => {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.items)) return payload.items
  if (Array.isArray(payload?.sessions)) return payload.sessions
  return []
}

/**
 * Rebuild the React workbench's Query-grouped history from PostgreSQL sessions
 * and the platform Run projection. Imported legacy rows retain their stored
 * query snapshot when the parent Run no longer exists.
 */
export const buildDeepSessionGroups = ({
  sessions = [],
  runs = [],
  currentRunId = '',
  archived = false
} = {}) => {
  const runMap = new Map(runs.map((run) => [text(run?.run_id || run?.id), run]))
  const groups = new Map()

  normalizeDeepSessions(sessions)
    .filter((item) => (deepSessionStatus(item) === 'archived') === Boolean(archived))
    .forEach((item) => {
      const runId = sessionRunId(item)
      const run = runMap.get(runId)
      const query = queryForSession(item, run)
      const fallbackKey = text(item?.project_id) || 'standalone'
      const groupKey = runId ? `run:${runId}` : `query:${fallbackKey}:${query}`
      const existing = groups.get(groupKey) || {
        group_key: groupKey,
        query,
        run_ids: runId ? [runId] : [],
        is_current: Boolean(runId && runId === text(currentRunId)),
        updated_at: item?.updated_at || item?.created_at || '',
        sessions: []
      }
      existing.sessions.push(item)
      if (timestamp(item?.updated_at || item?.created_at) > timestamp(existing.updated_at)) {
        existing.updated_at = item?.updated_at || item?.created_at || ''
      }
      groups.set(groupKey, existing)
    })

  return [...groups.values()]
    .map((group) => ({
      ...group,
      session_count: group.sessions.length,
      sessions: [...group.sessions].sort(
        (left, right) =>
          timestamp(right?.updated_at || right?.created_at) -
          timestamp(left?.updated_at || left?.created_at)
      )
    }))
    .sort((left, right) => {
      if (left.is_current !== right.is_current) return left.is_current ? -1 : 1
      return timestamp(right.updated_at) - timestamp(left.updated_at)
    })
}

export const formatDeepSessionTime = (value, locale = 'zh-CN') => {
  const parsed = new Date(value || '')
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleString(locale, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}
