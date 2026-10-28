/** 清理模型标题中的推理块，避免将内部标记保存为用户可见标题。 */
export function normalizeConversationTitle(value) {
  if (typeof value !== 'string') return ''
  return value
    .replace(/^[\s\S]*<\/think\s*>/i, '')
    .replace(/<think\b[^>]*>[\s\S]*$/i, '')
    .replace(/\s+/g, ' ')
    .trim()
}
