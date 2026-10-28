// Enter sends; Shift+Enter and IME confirmation remain editing actions.
export const shouldSubmitConversation = (event) =>
  event.key === 'Enter' &&
  !event.shiftKey &&
  !event.ctrlKey &&
  !event.metaKey &&
  !event.altKey &&
  !event.isComposing &&
  event.keyCode !== 229 &&
  !event.repeat

export const readConversationDraft = (storage, key) => {
  try {
    const value = JSON.parse(storage.getItem(key) || '{}')
    return {
      topic: typeof value?.topic === 'string' ? value.topic : '',
      focus: typeof value?.focus === 'string' ? value.focus : ''
    }
  } catch {
    return { topic: '', focus: '' }
  }
}

export const saveConversationDraft = (storage, key, draft) => {
  try {
    if (!draft.topic && !draft.focus) storage.removeItem(key)
    else storage.setItem(key, JSON.stringify({ topic: draft.topic, focus: draft.focus }))
  } catch {
    // Restricted browser storage must never block composing or sending.
  }
}
