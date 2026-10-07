const MODULE_DEFINITIONS = [
  ['overview', '概述'],
  ['technology_implementation', '装备与技术实现'],
  ['operational_process', '关键作战流程'],
  ['capability_effects', '形成能力与作战效果'],
  ['winning_logic', '制胜逻辑机理']
]

const asObject = (value) =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {}

export const favoriteRowId = (item = {}) =>
  String(item.favorite_id || item.id || item.card_key || `${item.run_id || ''}-${item.name || ''}`)

export const favoriteDisplayRow = (item = {}) => {
  const snapshot = asObject(item.snapshot || item.snapshot_json || item.card || item.capability)
  return {
    ...snapshot,
    favorite_id: item.favorite_id || item.id || snapshot.favorite_id || '',
    card_key: item.card_key || snapshot.card_key || '',
    run_id: item.run_id || item.source_run_id || snapshot.run_id || '',
    display_name: item.display_name ?? snapshot.display_name ?? '',
    note: item.note ?? snapshot.note ?? '',
    tags: Array.isArray(item.tags) ? item.tags : Array.isArray(snapshot.tags) ? snapshot.tags : [],
    source_topic: item.source_topic || snapshot.source_topic || '',
    source_status: item.source_status || snapshot.source_status || '',
    source_deleted: Boolean(item.source_deleted ?? snapshot.source_deleted),
    created_at: item.created_at || snapshot.created_at || '',
    updated_at: item.updated_at || snapshot.updated_at || ''
  }
}

const parsePortraitText = (value) => {
  const source = String(value || '').trim()
  if (!source) return new Map()
  const labels = MODULE_DEFINITIONS.map(([, label]) => label).concat(['制胜逻辑'])
  const pattern = new RegExp(`(?:^|\\n)\\s*(?:#{1,6}\\s*)?(?:\\d+[.、]\\s*)?(${labels.join('|')})\\s*[：:]?\\s*`, 'g')
  const matches = [...source.matchAll(pattern)]
  if (!matches.length) return new Map([['概述', source]])
  return new Map(matches.map((match, index) => [
    match[1],
    source.slice((match.index || 0) + match[0].length, matches[index + 1]?.index ?? source.length).trim()
  ]))
}

export const favoriteModules = (row = {}) => {
  const modules = asObject(row.capability_portrait_modules)
  const parsed = parsePortraitText(row.deep_capability_portrait || row.capability_image)
  return MODULE_DEFINITIONS.map(([key, label]) => ({
    key,
    label,
    text: String(
      modules[key]
      || parsed.get(label)
      || (key === 'winning_logic' ? parsed.get('制胜逻辑') : '')
      || ''
    ).trim()
  })).filter((item) => item.text)
}

export const favoriteDimensions = (classification) => {
  const source = asObject(classification)
  const primary = String(source.primary_dimension || source.primary || '').trim()
  const secondarySource = source.secondary_dimensions || source.secondary || []
  const secondary = (Array.isArray(secondarySource) ? secondarySource : [secondarySource])
    .map((item) => String(item || '').trim())
    .filter(Boolean)
  return [...new Set([primary, ...secondary].filter(Boolean))]
}

export const favoriteSourceUnavailable = (item = {}) =>
  Boolean(item.source_deleted)
  || /deleted|删除|unavailable|不可读/i.test(String(item.source_status || ''))

