function dateKey(value, timeZone) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const parts = new Intl.DateTimeFormat('en', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function briefTimestamp(brief) {
  return brief?.published_at || brief?.created_at
}

export function findLatestBriefForToday(
  briefs,
  { now = new Date(), timeZone = 'Asia/Shanghai', unreadOnly = false } = {}
) {
  const today = dateKey(now, timeZone)
  if (!today) return null

  return (Array.isArray(briefs) ? briefs : [])
    .filter((brief) => !unreadOnly || brief?.unread)
    .filter((brief) => dateKey(briefTimestamp(brief), timeZone) === today)
    .sort((left, right) => new Date(briefTimestamp(right)) - new Date(briefTimestamp(left)))[0] || null
}

export function briefPushSessionKey(userId, briefId) {
  return `innovation-brief-push:${String(userId || 'anonymous')}:${String(briefId || '')}`
}

export function formatBriefTime(value, timeZone = 'Asia/Shanghai') {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const parts = new Intl.DateTimeFormat('en', {
    timeZone,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${Number(values.month)}月${Number(values.day)}日 ${values.hour}:${values.minute}`
}
