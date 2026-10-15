const OVERVIEW_FIELDS = [
  ['当前背景', ['当前背景', '背景']],
  ['解决思路', ['解决思路', '解决方案']],
  ['达到效果', ['达到效果', '预期效果']],
  ['核心创新', ['核心创新', '创新点']]
]

/** 按原文标签拆分概述，未标注的历史文字只分句，不推断或补写内容。 */
export function portraitOverview(value = '') {
  const text = String(value || '').replace(/\*\*/g, '').trim()
  if (!text) return { fields: [], paragraphs: [] }

  const aliases = OVERVIEW_FIELDS.flatMap(([, labels]) => labels)
  const pattern = new RegExp(`(?:^|[\\s。；;])(?:[-•·]|\\d+[、.)）])?\\s*(${aliases.join('|')})\\s*[：:]`, 'g')
  const matches = [...text.matchAll(pattern)]
  const values = new Map()
  matches.forEach((match, index) => {
    const label = OVERVIEW_FIELDS.find(([, labels]) => labels.includes(match[1]))[0]
    const body = text.slice(match.index + match[0].length, matches[index + 1]?.index ?? text.length).trim()
    if (body) values.set(label, [values.get(label), body].filter(Boolean).join('；'))
  })
  const lead = text.slice(0, matches[0]?.index ?? text.length).trim()
  return {
    fields: matches.length ? OVERVIEW_FIELDS.map(([label]) => ({ label, text: values.get(label) || '' })) : [],
    paragraphs: lead.split(/\n+|(?<=[。！？])\s*/u).map((line) => line.replace(/^\s*(?:[-•·]|\d+[、.)）])\s*/, '').trim()).filter(Boolean)
  }
}
