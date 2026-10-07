import {
  TECHNOLOGY_CABIN_SECTION,
  TECHNOLOGY_SOLUTION_TRIGGER
} from './equipmentDeepPortraitSections.js'

const text = (value) => String(value ?? '').trim()

const cardAliases = (item = {}) => {
  const snapshot = item.snapshot && typeof item.snapshot === 'object' ? item.snapshot : {}
  return [
    item.card_key,
    item.card_binding_id,
    item.capability_id,
    item.id,
    item.version_id,
    snapshot.card_key,
    snapshot.card_binding_id,
    snapshot.capability_id,
    snapshot.id
  ]
    .map(text)
    .filter(Boolean)
}

export function isTechnologySolutionSession(session = {}) {
  return text(session?.payload?.research_section) === TECHNOLOGY_CABIN_SECTION
}

export function technologySessionMatchesCard(session = {}, item = {}) {
  if (!isTechnologySolutionSession(session)) return false
  const boundKey = text(session?.payload?.capability_card_key)
  return Boolean(boundKey && cardAliases(item).includes(boundKey))
}

export function technologySolutionFromSession(session = {}) {
  const messages = Array.isArray(session.messages) ? session.messages : []
  let triggerIndex = -1
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (text(message?.role) === 'user' && text(message?.content).includes(TECHNOLOGY_SOLUTION_TRIGGER)) {
      triggerIndex = index
      break
    }
  }
  if (triggerIndex < 0) return null
  for (let index = messages.length - 1; index > triggerIndex; index -= 1) {
    const message = messages[index]
    if (text(message?.role) !== 'assistant' || !text(message?.content)) continue
    return {
      content: text(message.content),
      messageId: text(message.message_id || message.id),
      createdAt: text(message.created_at),
      sessionId: text(session.session_id),
      updatedAt: text(session.updated_at)
    }
  }
  return null
}

export function latestTechnologySession(sessions = [], item = {}) {
  return [...sessions]
    .filter((session) => technologySessionMatchesCard(session, item))
    .sort((left, right) => text(right.updated_at).localeCompare(text(left.updated_at)))[0] || null
}
