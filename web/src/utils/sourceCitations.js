// 将回答中的 URL 引用投影成安全链接；DOI 是模型常见的来源缩写。
export const normalizeCitationSource = (source) => {
  const value = String(source || '').trim()
  if (/^10\.\d{4,9}\/\S+$/i.test(value)) {
    return `https://doi.org/${encodeURIComponent(value).replaceAll('%2F', '/')}`
  }
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : ''
  } catch {
    return ''
  }
}

const CITATION_RE =
  /^<cite\s+(?:source\s*=\s*(["'])(.*?)\1\s+type\s*=\s*(["'])url\3|type\s*=\s*(["'])url\4\s+source\s*=\s*(["'])(.*?)\5)\s*>([^<]*)<\/cite>/i

export const markdownItSourceCitations = (md) => {
  md.inline.ruler.before('html_inline', 'source_citation', (state, silent) => {
    const match = CITATION_RE.exec(state.src.slice(state.pos))
    if (!match) return false
    const url = normalizeCitationSource(md.utils.unescapeAll(match[2] ?? match[6]))
    if (!url) return false
    if (!silent) {
      const token = state.push('source_citation', 'cite', 0)
      token.meta = { url, label: md.utils.unescapeAll(match[7].trim()) }
    }
    state.pos += match[0].length
    return true
  })
  md.renderer.rules.source_citation = (tokens, index) => {
    const { url, label } = tokens[index].meta
    return `<cite><a class="source-citation" href="${md.utils.escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${md.utils.escapeHtml(label)}</a></cite>`
  }
}
