const objectValue = (value) =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {}

const textValue = (...values) => {
  for (const value of values) {
    if (Array.isArray(value)) {
      const text = value
        .map((item) => String(item || '').trim())
        .filter(Boolean)
        .join('\n')
      if (text) return text
    } else if (value !== null && value !== undefined && String(value).trim()) {
      return String(value).trim()
    }
  }
  return ''
}

const CAPABILITY_PORTRAIT_LABELS = [
  '概述',
  '装备与技术实现',
  '关键作战流程',
  '形成能力与作战效果',
  '制胜逻辑机理与对抗边界',
  '制胜逻辑机理',
  '制胜逻辑'
]

const REPORT_SOURCE_HEADING_RE = /核心公开来源索引|正式证据引用说明|证据引用说明|参考文献|来源索引/

export const runStatusLabel = (value) =>
  ({
    queued: '已排队',
    draft: '草稿',
    planning: '规划中',
    researching: '研究中',
    recalling: '再调中',
    synthesizing: 'S1–S6 综合中',
    reviewing: '审计中',
    reporting: '报告生成中',
    pause_requested: '请求暂停',
    paused: '已暂停',
    cancel_requested: '正在停止',
    cancelled: '已取消',
    completed: '已完成',
    failed: '失败',
    archived: '已归档'
  })[value] || value || '未知'

export const routeLabel = (value) =>
  ({
    new_winning_mechanism: '新制胜机理',
    traditional_gap: '传统能力缺口',
    war_case_learning: '局部战争案例',
    auto: '自动'
  })[value] || value || '自动'

/**
 * PostgreSQL 事件与迁移前的 workbench 事件包装层级不同。
 * 只在展示边界展平它们，不修改服务端事实。
 */
export const normalizeResearchEvent = (event = {}) => {
  const row = objectValue(event)
  const payload = objectValue(row.payload)
  const embedded = objectValue(payload.event)
  const embeddedPayload = objectValue(embedded.payload)
  const details = {
    ...objectValue(payload.details),
    ...embeddedPayload,
    ...objectValue(embedded.details),
    ...objectValue(row.details)
  }
  return {
    ...row,
    event_type: textValue(embedded.event_type, row.event_type, details.event_type),
    actor: textValue(embedded.actor, row.actor, payload.actor, details.actor, details.agent_id),
    summary: textValue(embedded.summary, row.summary, payload.summary, details.summary),
    details
  }
}

export const reporterLifecycle = (events = [], runStatus = '') => {
  const normalized = (Array.isArray(events) ? events : []).map(normalizeResearchEvent)
  let status = 'pending'
  let started = false
  let failedEvent = null
  let progressEvent = null

  for (const event of normalized) {
    const delegated =
      event.event_type === 'agent_task_delegated' &&
      textValue(event.details.target_agent_id, event.details.agent_id) === 'reporter'
    const reporterActivity =
      event.actor === 'reporter' ||
      String(event.event_type || '').startsWith('report_model_') ||
      event.event_type === 'report_completed'
    if (delegated || reporterActivity) {
      started = true
      if (status !== 'completed') status = 'running'
    }
    if (
      ['report_model_queue_started', 'report_model_call_started', 'report_model_call_progress'].includes(
        event.event_type
      )
    ) {
      progressEvent = event
    }
    if (event.event_type === 'report_model_failed') {
      started = true
      status = 'failed'
      failedEvent = event
    } else if (event.event_type === 'report_completed') {
      started = true
      status = 'completed'
      failedEvent = null
    } else if (
      delegated ||
      ['report_model_queue_started', 'report_model_call_started', 'report_model_call_progress'].includes(
        event.event_type
      )
    ) {
      // A checkpoint resume appends new Reporter activity after the old
      // failure event.  The later activity is authoritative for the current
      // phase, while the old event remains available in the audit trail.
      status = 'running'
      failedEvent = null
    }
  }

  if (runStatus === 'completed') status = 'completed'
  // A run-level failure can be persisted before a deferred Reporter process
  // finishes writing its artifact.  Only an explicit Reporter failure (or a
  // run that never reached Reporter) is terminal for the report surface.
  const terminalFailure =
    status === 'failed' ||
    ['cancelled', 'archived'].includes(runStatus) ||
    (runStatus === 'failed' && !started)

  const progress = progressEvent?.details || {}
  const progressText = textValue(
    progress.current_step,
    progress.step,
    progressEvent?.summary,
    started ? '独立报告 Agent 正在撰写' : '等待 Reporter 阶段'
  )
  const elapsed = Number(progress.elapsed_seconds)

  return {
    status,
    started,
    terminalFailure,
    failureDetail: textValue(
      failedEvent?.details?.detail,
      failedEvent?.details?.error,
      failedEvent?.summary
    ),
    progressText:
      Number.isFinite(elapsed) && elapsed > 0
        ? `${progressText} · 已耗时 ${Math.round(elapsed)} 秒`
        : progressText
  }
}

const completeCapabilityText = (value) => {
  let text = String(value || '')
  const placeholder =
    /(^|[；;\uff0c,\n])\s*(?:string|array|object|null|number|boolean)\s*(?=($|[；;\uff0c,。\n]))/gi
  let previous = ''
  while (previous !== text) {
    previous = text
    text = text.replace(placeholder, '$1')
  }
  return text
    .replace(/；；+/g, '；')
    .replace(/;;+/g, ';')
    .replace(/[；;]。/g, '。')
    .trim()
}

const sanitizeCapabilityPortraitSection = (value) =>
  String(value || '')
    .replace(
      /\b(?:key_technologies|system_architecture|implementation_path|key_bottlenecks|keyword_context|intelligence_requirement|latency_requirement|coordination_requirement|enabling_technologies|module_content|operational_steps|capability_portrait_modules)\b/g,
      ' '
    )
    .replace(/['"]?[a-z][a-z0-9]*(?:_[a-z0-9]+)+['"]?\s*:/g, ' ')
    .replace(/[{}[\]'="]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

export const capabilityPortraitModules = (item = {}) => {
  const row = objectValue(item)
  const modules = objectValue(row.capability_portrait_modules)
  const fallback = [
    ['概述', textValue(modules.overview, row.problem_statement, row.capability_gap)],
    [
      '装备与技术实现',
      textValue(
        modules.technology_implementation,
        modules.equipment_and_technology,
        modules.technology,
        row.scientific_principle,
        row.technical_principle
      )
    ],
    [
      '关键作战流程',
      textValue(modules.operational_process, row.operational_process, row.operational_mechanism)
    ],
    [
      '形成能力与作战效果',
      textValue(modules.capability_effects, modules.outcome, row.capability_outcome, row.mission_effect)
    ],
    [
      '制胜逻辑机理',
      textValue(modules.winning_logic, row.winning_mechanism, row.source_winning_logic)
    ]
  ]
    .map(([label, text]) => ({ label, text: sanitizeCapabilityPortraitSection(text) }))
    .filter((entry) => entry.text)

  const raw = sanitizeCapabilityPortraitSection(
    completeCapabilityText(textValue(row.deep_capability_portrait, row.capability_image))
  )
  if (!raw) return fallback
  const pattern = new RegExp(`(${CAPABILITY_PORTRAIT_LABELS.join('|')})\\s*[：:]`, 'g')
  const matches = [...raw.matchAll(pattern)]
  if (!matches.length) {
    return fallback.length >= 5
      ? fallback
      : [{ label: '概述', text: raw }, ...fallback.filter((entry) => entry.label !== '概述')]
  }

  const parsed = []
  const lead = raw
    .slice(0, matches[0].index)
    .replace(/^[\s·•*-]+/, '')
    .trim()
  if (lead) parsed.push({ label: '概述', text: lead })
  matches.forEach((match, index) => {
    const text = raw
      .slice(match.index + match[0].length, matches[index + 1]?.index ?? raw.length)
      .trim()
    if (!text) return
    const label =
      match[1] === '制胜逻辑机理与对抗边界' || match[1] === '制胜逻辑'
        ? '制胜逻辑机理'
        : match[1]
    const existing = parsed.find((entry) => entry.label === label)
    if (existing) existing.text = `${existing.text}\n${text}`
    else parsed.push({ label, text })
  })
  return parsed.length ? parsed : fallback
}

export const capabilityTitle = (item = {}) =>
  textValue(
    item.equipment_name,
    item.name,
    item.primary_equipment_identity,
    item.title,
    item.capability_name,
    item.capability_id,
    item.id,
    '未命名装备'
  )

export const capabilityVersionMeta = (item = {}) => {
  const deepSource =
    item.is_deep_research ||
    /deep|reference_weapon|supplement|深研/i.test(
      `${item.source || ''} ${item.version_source || ''}`
    )
  const status = String(
    item.verification_status ||
      item.version_status ||
      item.status ||
      (item.confidence_limited || deepSource ? 'pending_verification' : 'formal')
  ).toLowerCase()
  const version = item.version_no ?? item.version ?? item.research_version ?? ''
  const statusLabel = ['formal', 'verified', 'approved', 'accepted'].includes(status)
    ? '已核验'
    : status === 'rejected'
      ? '已驳回'
      : ['rolled_back', 'rollback'].includes(status)
        ? '已回滚'
        : '待核验'
  return {
    status,
    statusLabel,
    version: String(version || '').replace(/^v/i, ''),
    source: textValue(
      item.source,
      item.version_source,
      item.is_deep_research ? 'reference_weapon_deep_research' : 'formal_s6'
    )
  }
}

const WEAPON_DIMENSION_LABELS = {
  damage: '毁伤维度',
  strike: '打击维度',
  penetration: '突防维度',
  interception: '拦截维度',
  suppression: '压制维度',
  denial: '拒止维度',
  reconnaissance: '侦察感知维度',
  early_warning: '预警维度',
  electronic_countermeasure: '电子对抗维度',
  deterrence: '威慑维度',
  survivability: '生存抗毁维度',
  battlefield_control: '战场控制维度'
}

const dimensionLabel = (value) => {
  const text = String(value || '').trim()
  return WEAPON_DIMENSION_LABELS[text] || text
}

export const capabilityDimensions = (item = {}) => {
  const classification = item.capability_classification
  if (!classification) return { values: [], basis: '' }
  if (typeof classification !== 'object') {
    return {
      values: String(classification)
        .split(/[、,，;；]/)
        .map(dimensionLabel)
        .filter(Boolean)
        .slice(0, 3),
      basis: ''
    }
  }
  const primary = classification.primary_dimension || classification.primary || ''
  const secondary = classification.secondary_dimensions || classification.secondary || []
  const secondaryValues = Array.isArray(secondary)
    ? secondary
    : String(secondary).split(/[、,，;；]/)
  const values = [primary, ...secondaryValues]
    .map(dimensionLabel)
    .filter((value, index, rows) => value && rows.indexOf(value) === index)
    .slice(0, 3)
  return { values, basis: textValue(classification.classification_basis) }
}

export const capabilityConfidence = (item = {}) => {
  const value = Number(item.confidence ?? item.score ?? item.snapshot?.confidence)
  if (!Number.isFinite(value)) return '—'
  return `${(value <= 1 ? value * 100 : value).toFixed(1)}%`
}

const agentFacingText = (value, preserveLayout = false) => {
  const sanitized = String(value ?? '')
    .replace(/(?:概念性工作名|Query因果)\s*[：:]\s*[^；。\n]*[；。]?/g, '')
    .replace(/甲方可读能力画像报告/g, '能力画像研究报告')
    .replace(/甲方能力画像报告/g, '能力画像研究报告')
    .replace(/甲方报告/g, '研究报告')
    .replace(/甲方/g, '项目')
    .replace(/codex\s*子\s*agent/gi, '专用 Agent')
    .replace(/codex[\s_-]*cli/gi, 'Agent')
    .replace(/codex\s*专用\s*agent/gi, '专用 Agent')
    .replace(/自定义\s*agent/gi, 'Agent')
    .replace(/codex/gi, 'Agent')
  return (preserveLayout ? sanitized : sanitized.replace(/\s{2,}/g, ' ')).trim()
}

const markdownTableCells = (line) => {
  const text = String(line || '')
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
  const cells = []
  let cell = ''
  let escaped = false
  for (const character of text) {
    if (character === '|' && !escaped) {
      cells.push(cell.trim())
      cell = ''
      continue
    }
    cell += character
    escaped = character === '\\' && !escaped
    if (character !== '\\') escaped = false
  }
  cells.push(cell.trim())
  return cells
}

const isMarkdownTableDivider = (line) => {
  const cells = markdownTableCells(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

const summarizeBaselineGapTable = (value) => {
  const lines = String(value || '').split('\n')
  const result = []
  let inTargetSection = false
  let converted = false
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*$/)
    if (heading) {
      const title = heading[2].replace(/[*_`]/g, '').trim()
      inTargetSection = /^现役(?:任务链)?基线与五档差距(?:如下)?$/.test(title)
      result.push(inTargetSection ? `${heading[1]} 现役基线与五档差距综述` : line)
      continue
    }
    if (inTargetSection && !converted && line.includes('|') && isMarkdownTableDivider(lines[index + 1])) {
      const headers = markdownTableCells(line)
      const rows = []
      index += 2
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        rows.push(markdownTableCells(lines[index]))
        index += 1
      }
      const overview = rows
        .map((row, rowIndex) => {
          const title = (row[0] || `第 ${rowIndex + 1} 档`).replace(/\*\*|__/g, '').trim()
          const details = headers
            .slice(1)
            .map((header, cellIndex) => {
              const cell = row[cellIndex + 1]?.replace(/\*\*|__/g, '').trim()
              const label = (header || `字段 ${cellIndex + 2}`).replace(/\*\*|__/g, '').trim()
              return cell ? `${label}为${cell}` : ''
            })
            .filter(Boolean)
          return `${title}方面，${details.join('；')}。`
        })
        .join('')
      result.push('', overview)
      converted = true
      index -= 1
      continue
    }
    result.push(line)
  }
  return result.join('\n')
}

export const normalizeReportMarkdownTables = (value) => {
  const lines = String(value || '').split('\n')
  const result = []
  let inTable = false
  let sawDivider = false
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const trimmed = line.trim()
    if (!trimmed.startsWith('|')) {
      inTable = false
      sawDivider = false
      result.push(line)
      continue
    }
    if (isMarkdownTableDivider(trimmed)) {
      if (inTable && sawDivider) continue
      inTable = true
      sawDivider = true
      result.push(trimmed)
      continue
    }
    const closed = trimmed.endsWith('|') ? trimmed : `${trimmed} |`
    if (!inTable) {
      inTable = true
      sawDivider = false
      result.push(closed)
      const next = (lines[index + 1] || '').trim()
      if (next.startsWith('|') && !isMarkdownTableDivider(next)) {
        const width = Math.max(1, markdownTableCells(closed).length)
        result.push(`| ${Array.from({ length: width }, () => '---').join(' | ')} |`)
        sawDivider = true
      }
      continue
    }
    result.push(closed)
  }
  return result.join('\n')
}

const decodeHtmlEntities = (value) =>
  String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&amp;/gi, '&')

const reportHtmlCellText = (value) =>
  decodeHtmlEntities(
    String(value || '')
      .replace(/<br\s*\/?\s*>/gi, '；')
      .replace(/<\/p>\s*<p\b[^>]*>/gi, '；')
      .replace(/<[^>]+>/g, '')
  )
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\|/g, '\\|')

export const normalizeReportHtmlTables = (value) =>
  String(value || '').replace(/<table\b[^>]*>[\s\S]*?<\/table>/gi, (table) => {
    const rows = [...table.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)]
      .map((match) =>
        [...match[1].matchAll(/<(th|td)\b[^>]*>([\s\S]*?)<\/\1>/gi)].map((cell) => ({
          header: cell[1].toLowerCase() === 'th',
          text: reportHtmlCellText(cell[2])
        }))
      )
      .filter((row) => row.length)
    if (!rows.length) return table
    const width = Math.max(...rows.map((row) => row.length))
    const normalizedRows = rows.map((row) =>
      Array.from({ length: width }, (_, index) => row[index]?.text || '')
    )
    const firstRowIsHeader = rows[0].some((cell) => cell.header)
    const header = firstRowIsHeader
      ? normalizedRows[0]
      : Array.from({ length: width }, (_, index) => `字段 ${index + 1}`)
    const body = firstRowIsHeader ? normalizedRows.slice(1) : normalizedRows
    return `\n\n| ${header.join(' | ')} |\n| ${header.map(() => '---').join(' | ')} |${
      body.length ? `\n${body.map((row) => `| ${row.join(' | ')} |`).join('\n')}` : ''
    }\n\n`
  })

const normalizeBareUrls = (value) => {
  const source = String(value || '')
  return source.replace(
    /https?:\/\/[^\s<>\u3000-\u303f\uff00-\uffef()[\]{}"']+/g,
    (matched, offset) => {
      const prefix = source.slice(Math.max(0, offset - 2), offset)
      if (prefix.endsWith('](') || source[offset - 1] === '<') return matched
      const trailing = matched.match(/[.,;:!?]+$/)?.[0] || ''
      const url = trailing ? matched.slice(0, -trailing.length) : matched
      return `<${url}>${trailing}`
    }
  )
}

const splitLongParagraph = (block, softLimit = 360, hardLimit = 480) => {
  const compact = String(block || '').replace(/\s+/g, ' ').trim()
  if (!compact || compact.length <= hardLimit) return [String(block || '').trim()].filter(Boolean)
  if (/^#{1,6}\s|^\||^>\s|^```|^[-*+]\s|^\d+[.)、]\s/.test(compact)) {
    return [String(block || '').trim()].filter(Boolean)
  }
  const sentences = compact.match(/[^。！？!?；;]+[。！？!?；;]?/g) || [compact]
  const paragraphs = []
  let current = ''
  for (const sentence of sentences) {
    const piece = sentence.trim()
    if (!piece) continue
    if (current && current.length + piece.length > softLimit) {
      paragraphs.push(current.trim())
      current = piece
    } else current = `${current}${piece}`
  }
  if (current.trim()) paragraphs.push(current.trim())
  return paragraphs.length ? paragraphs : [compact]
}

const splitPnSegments = (block) => {
  const text = String(block || '').trim()
  if (!text || /^#{1,6}\s|^\||^```/.test(text)) return [text].filter(Boolean)
  const labelRe = /\*\*\s*([^*]+?)\s*[（(](P[1-9])[）)]\s*[。.]?\s*\*\*/g
  let matches = [...text.matchAll(labelRe)]
  if (!matches.length) {
    const plainRe = /(?:^|(?<=[。！？\n]))\s*([^\n。！？]{1,80}?)\s*[（(](P[1-9])[）)]\s*[。.]?\s*/g
    matches = [...text.matchAll(plainRe)]
  }
  if (!matches.length) return [text]
  const segments = []
  if (matches[0].index > 0) {
    const preamble = text.slice(0, matches[0].index).trim()
    if (preamble) segments.push(preamble)
  }
  matches.forEach((match, index) => {
    const end = matches[index + 1]?.index ?? text.length
    const name = String(match[1] || '').trim()
    const code = match[2]
    const body = text.slice(match.index + match[0].length, end).trim()
    if (name && code) segments.push(body ? `#### ${code} ${name}\n\n${body}` : `#### ${code} ${name}`)
    else if (body) segments.push(body)
  })
  return segments.length ? segments : [text]
}

export const segmentReportParagraphs = (value) => {
  const lines = String(value || '').split('\n')
  const prepared = []
  let inFence = false
  for (const line of lines) {
    if (/^\s*```/.test(line)) inFence = !inFence
    const stripped = line.trim()
    if (
      !inFence &&
      stripped &&
      prepared.length &&
      /^#{1,6}\s/.test((prepared.at(-1) || '').trim()) &&
      !stripped.startsWith('#') &&
      prepared.at(-1).trim()
    ) {
      prepared.push('')
    }
    if (
      !inFence &&
      /^(?:[-*+]|\d+[.)、])\s/.test(stripped) &&
      prepared.length &&
      prepared.at(-1).trim()
    ) {
      prepared.push('')
    }
    if (
      !inFence &&
      /(?:^|\*\*)\s*[^*\n]{0,80}?（P[1-9]）/.test(stripped) &&
      prepared.length &&
      prepared.at(-1).trim() &&
      !/^#{1,6}\s/.test(stripped)
    ) {
      prepared.push('')
    }
    prepared.push(line)
  }

  const normalized = prepared.join('\n').replace(/\n{3,}/g, '\n\n')
  const blocks = []
  let fence = false
  let buffer = []
  const flush = () => {
    const block = buffer.join('\n').trim()
    buffer = []
    if (!block) return
    if (
      fence ||
      block.startsWith('|') ||
      /^#{1,6}\s/m.test(block) ||
      /^(?:[-*+]|\d+[.)、])\s/m.test(block) ||
      block.startsWith('>')
    ) {
      blocks.push(block)
      return
    }
    for (const segment of splitPnSegments(block)) {
      if (/^####\s+P[1-9]\b/.test(segment)) blocks.push(segment)
      else blocks.push(...splitLongParagraph(segment))
    }
  }
  for (const line of normalized.split('\n')) {
    if (/^\s*```/.test(line)) {
      if (!fence) flush()
      fence = !fence
      buffer.push(line)
      if (!fence) flush()
      continue
    }
    if (fence) {
      buffer.push(line)
      continue
    }
    if (!line.trim()) flush()
    else buffer.push(line)
  }
  flush()
  return blocks.join('\n\n')
}

const normalizeAbbreviations = (value) => {
  const replacements = [
    [/DARPA\s+CODE/g, '美国国防高级研究计划局“受限环境协同作战”项目'],
    [/CJADC2/g, '联合全域指挥控制'],
    [/GNSS/g, '全球导航卫星系统'],
    [/GPS/g, '全球定位系统'],
    [/\bQuery\b/g, '查询问题'],
    [/ISR\s*\/\s*C2/g, '侦察监视情报与指挥控制'],
    [/\bISR\b/g, '侦察监视情报'],
    [/\bC2\b/g, '指挥控制'],
    [/\bDOD\b|\bDoD\b/g, '美国国防部']
  ]
  let inFence = false
  let inSourceIndex = false
  return String(value || '')
    .split('\n')
    .map((line) => {
      if (/^\s*```/.test(line)) {
        inFence = !inFence
        return line
      }
      if (REPORT_SOURCE_HEADING_RE.test(line)) inSourceIndex = true
      if (inFence || inSourceIndex) return line
      return replacements.reduce((current, [pattern, replacement]) => current.replace(pattern, replacement), line)
    })
    .join('\n')
}

const reportHasEquipmentTable = (markdown) =>
  /(^|\n)\s*\|\s*(?:武器装备|装备系统方向|装备方向|具体装备方向)\s*\|/m.test(String(markdown || ''))

const reportTableCellText = (value, limit = 280) => {
  const text = String(value || '')
    .replace(/\s+/g, ' ')
    .replace(/\|/g, '／')
    .trim()
  if (!text) return '—'
  if (text.length <= limit) return text
  const clipped = text.slice(0, limit)
  const boundary = Math.max(clipped.lastIndexOf('。'), clipped.lastIndexOf('；'), clipped.lastIndexOf('，'))
  return `${boundary > 80 ? clipped.slice(0, boundary + 1) : clipped}…`
}

const capabilityTableCells = (row = {}) => {
  const points = new Map(capabilityPortraitModules(row).map((item) => [item.label, item.text]))
  const modules = objectValue(row.capability_portrait_modules)
  const direction = textValue(row.equipment_direction, row.equipment_form, row.equipment_category)
  const name = [capabilityTitle(row), direction && `装备方向：${direction}`]
    .filter(Boolean)
    .join(' · ')
  const technologies = Array.isArray(row.enabling_technologies)
    ? row.enabling_technologies.filter(Boolean).join('、')
    : ''
  return [
    name,
    textValue(
      points.get('装备与技术实现'),
      modules.equipment_and_technology,
      modules.key_technologies,
      technologies,
      row.scientific_principle,
      row.equipment_form
    ),
    textValue(
      points.get('形成能力与作战效果'),
      modules.capability_effects,
      row.mission_effect,
      row.capability_outcome,
      row.military_utility,
      row.capability_gap
    ),
    textValue(
      points.get('关键作战流程'),
      modules.operational_process,
      row.operational_process,
      row.operational_mechanism,
      row.strike_countermeasure_value,
      row.source_winning_logic
    )
  ].map((cell) => reportTableCellText(cell))
}

const buildEquipmentTable = (capabilityRows = []) => {
  const rows = (Array.isArray(capabilityRows) ? capabilityRows : [])
    .map(capabilityTableCells)
    .filter((cells) => cells[0] && cells[0] !== '—')
  if (!rows.length) return ''
  return [
    '| 武器装备 | 核心技术 | 形成能力 | 作战概念与主要效果 |',
    '| --- | --- | --- | --- |',
    ...rows.map((cells) => `| ${cells.join(' | ')} |`)
  ].join('\n')
}

const resolvedTemplateMode = (run, markdown = '') => {
  const configured = String(run?.report_template_mode || run?.payload?.report_template_mode || '').trim()
  if (['project_argument_v1', 'three_layer_nine_item'].includes(configured)) return configured
  const source = String(markdown || '')
  const project = /^##\s*[一二三四五][、.．]?\s*(需求分析|项目画像|总体方案|关键技术|研制基础)\s*$/m.test(source)
  const threeLayer = /^##\s*第[一二三]层/m.test(source) || /^###\s*[①-⑨]/m.test(source)
  if (project && !threeLayer) return 'project_argument_v1'
  if (threeLayer && !project) return 'three_layer_nine_item'
  return ''
}

const ensureEquipmentTable = (markdown, capabilityRows = [], templateMode = '') => {
  const source = String(markdown || '')
  if (!source.trim() || reportHasEquipmentTable(source)) return source
  const table = buildEquipmentTable(capabilityRows)
  if (!table) return source
  const block = `\n\n${table}\n`
  const mode = templateMode || resolvedTemplateMode(null, source)
  const projectMode = mode === 'project_argument_v1'
  const threeLayerMode = mode === 'three_layer_nine_item'
  if ((projectMode || !threeLayerMode) && /^###\s*（一）装备图像概述\s*$/m.test(source)) {
    return source.replace(/(^###\s*（一）装备图像概述\s*$)/m, `$1${block}`)
  }
  if ((threeLayerMode || !projectMode) && /^###\s*⑦\s*装备能力图像\s*$/m.test(source)) {
    return source.replace(/(^###\s*⑦\s*装备能力图像\s*$)/m, `$1${block}`)
  }
  if (projectMode && /^##\s*二[、.．]?\s*项目画像\s*$/m.test(source)) {
    return source.replace(
      /(^##\s*二[、.．]?\s*项目画像\s*$)/m,
      `$1\n\n### （一）装备图像概述${block}`
    )
  }
  if (threeLayerMode && /^##\s*第三层[^\n]*$/m.test(source)) {
    return source.replace(/(^##\s*第三层[^\n]*$)/m, `$1\n\n### ⑦ 装备能力图像${block}`)
  }
  if (projectMode) return `${source.trimEnd()}\n\n### （一）装备图像概述${block}`
  if (threeLayerMode) return `${source.trimEnd()}\n\n### ⑦ 装备能力图像${block}`
  return source
}

export const buildDeepResearchSupplement = (rows = []) => {
  const deepRows = (Array.isArray(rows) ? rows : []).filter((row) => {
    const meta = capabilityVersionMeta(row)
    if (meta.formalBaseline || (meta.status === 'formal' && !row.is_deep_research)) return false
    return Boolean(
      row.is_deep_research ||
        ['pending', 'pending_verification', 'unverified'].includes(meta.status) ||
        row.confidence_limited === true ||
        /deep|reference_weapon|supplement|深研/i.test(`${meta.source} ${row.source || ''}`)
    )
  })
  if (!deepRows.length) return ''
  const lines = [
    '## 深研补充（待核验）',
    '',
    '以下内容来自深度追问或参考武器定向深研，原始报告正文保持不变；正式采纳前需完成审核。',
    ''
  ]
  deepRows.forEach((row) => {
    const meta = capabilityVersionMeta(row)
    const evidence = row.evidence_ids || row.evidence_refs || []
    const body = textValue(
      row.deep_capability_portrait,
      row.capability_image,
      row.reference_overview,
      row.overview
    )
    lines.push(
      `### ${capabilityTitle(row)}${meta.version ? ` · v${meta.version}` : ''}`,
      '',
      `- 状态：${meta.statusLabel}`,
      `- 来源：${meta.source || 'deep-thinking'}`,
      `- 证据引用：${Array.isArray(evidence) ? evidence.length : 0} 条`,
      '',
      body || '深研任务已启动，详细能力画像将在校验通过后补充。',
      ''
    )
  })
  return lines.join('\n')
}

export const normalizeReportDocument = (text, run = null, capabilityRows = []) => {
  const raw = typeof text === 'string' ? text : JSON.stringify(text ?? '', null, 2)
  const supplement = raw.includes('深研补充（待核验）')
    ? ''
    : buildDeepResearchSupplement(capabilityRows)
  const enriched = ensureEquipmentTable(
    supplement ? `${raw}\n\n${supplement}` : raw,
    capabilityRows,
    resolvedTemplateMode(run, raw)
  )
  const content = segmentReportParagraphs(
    normalizeBareUrls(
      normalizeReportMarkdownTables(
        normalizeReportHtmlTables(agentFacingText(normalizeAbbreviations(enriched), true))
      )
    )
      .replace(/\\\*\\\*([^\n]+?)\\\*\\\*/g, '**$1**')
      // Only trim spaces inside a bold marker. Using `\s` here also matches
      // paragraph breaks, so the closing `**` of one paragraph can be paired
      // with the opening `**` of the next and collapse valid Markdown blocks.
      .replace(/\*\*([^*\n]+?)[ \t]+\*\*/g, '**$1**')
      .replace(/(\*\*[^*\n]+?\*\*)(?=[\u3400-\u9fffA-Za-z0-9])/g, '$1 ')
  )
  const expanded = content.replace(/五档差距判断如下[。:：]\s*([^\n]+)/g, (full, body) => {
    const tiers = String(body)
      .split(/\s*(?=第[一二三四五]档(?:是|为)?)/)
      .filter(Boolean)
    if (tiers.length !== 5) return full
    return `五档差距判断如下：\n\n${tiers
      .map((tier, index) => {
        const match = tier.match(/^第([一二三四五])档(?:是|为)?\s*(.*)$/)
        return match
          ? `${index + 1}. **第${match[1]}档**：${match[2].trim()}`
          : `${index + 1}. ${tier.trim()}`
      })
      .join('\n\n')}`
  })
  return summarizeBaselineGapTable(expanded)
}

export const compactReportInlineLinks = (value) => {
  let inlineLinks = 0
  let inSourceIndex = false
  let inFence = false
  return String(value || '')
    .split('\n')
    .map((line) => {
      if (/^\s*```/.test(line)) {
        inFence = !inFence
        return line
      }
      if (REPORT_SOURCE_HEADING_RE.test(line)) inSourceIndex = true
      if (inFence || inSourceIndex) return line
      return line
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (full, label) => {
          inlineLinks += 1
          return inlineLinks <= 2 ? full : label
        })
        .replace(/<https?:\/\/[^>\s]+>/g, (full) => {
          inlineLinks += 1
          return inlineLinks <= 2 ? full : '（来源链接见文末索引）'
        })
    })
    .join('\n')
}

export const reportFilename = (run = {}) => {
  const topic = String(run.topic || 'research-report')
    .replace(/[\\/:*?"<>|\s]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `${topic || 'research-report'}-${run.run_id || 'report'}.md`
}
