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
  const numbering = '(?:\\d+|[一二三四])'
  const marker = `(?:[-•·*]|${numbering}[、.)）]|[（(]${numbering}[）)])`
  const pattern = new RegExp(`(?:^|(?<=[\\s。；;]))(?:#{1,6}\\s+)?(?:${marker}\\s*)?(${aliases.join('|')})\\s*[：:]`, 'g')
  const matches = [...text.matchAll(pattern)]
  const values = new Map()
  matches.forEach((match, index) => {
    const label = OVERVIEW_FIELDS.find(([, labels]) => labels.includes(match[1]))[0]
    const body = text.slice(match.index + match[0].length, matches[index + 1]?.index ?? text.length).trim()
    if (body) {
      const previous = values.get(label)
      values.set(label, previous ? `${previous}${/[。；;！？]$/.test(previous) ? '' : '；'}${body}` : body)
    }
  })
  const lead = text.slice(0, matches[0]?.index ?? text.length).trim()
  return {
    fields: matches.length ? OVERVIEW_FIELDS.map(([label]) => ({ label, text: values.get(label) || '' })) : [],
    paragraphs: lead.split(/\n+|(?<=[。！？])\s*/u).map((line) => line.replace(new RegExp(`^\\s*${marker}\\s*`), '').trim()).filter(Boolean)
  }
}
