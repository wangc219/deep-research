export const latestHumanMessage = (conversations = []) => {
  for (let index = conversations.length - 1; index >= 0; index--) {
    const message = (conversations[index].messages || []).findLast((item) => item.type === 'human')
    if (message) return message
  }
  return null
}

export const truncateReplacedMessageBranch = (messages = [], messageId) => {
  const targetId = Number(messageId)
  if (!Number.isFinite(targetId)) return messages
  const replacedIndex = messages.findIndex((item) => Number(item?.id) === targetId)
  return replacedIndex >= 0 ? messages.slice(0, replacedIndex) : messages
}
