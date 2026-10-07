const objectValue = (value) => value && typeof value === 'object' && !Array.isArray(value) ? value : {}

const textValue = (...values) => {
  for (const value of values) {
    if (Array.isArray(value)) {
      const text = value.map((item) => String(item || '').trim()).filter(Boolean).join('\n')
      if (text) return text
    } else if (value !== null && value !== undefined && String(value).trim()) {
      return String(value).trim()
    }
  }
  return ''
}

/**
 * 把历代 capability_versions.snapshot 统一成 Vue 五栏画像契约。
 * 原始字段全部保留，确保收藏、定向深研和后续新字段不丢失。
 */
export const normalizeCapability = (source = {}) => {
  const row = objectValue(source)
  const snapshot = objectValue(row.snapshot)
  const merged = { ...snapshot, ...row }
  const draft = objectValue(merged.capability_card_draft)
  const modules = objectValue(merged.capability_portrait_modules)
  const normalizedDirection = textValue(
    merged.equipment_direction,
    merged.equipmentDirection,
    merged.equipment_direction_name,
    merged.innovation_variant_name,
    merged.equipment_form,
    merged.equipment_forms,
    merged.innovation_equipment_form
  )
  const genericName = textValue(merged.name, merged.title, draft.title)
  const explicitName = textValue(
    merged.equipment_name,
    merged.equipmentName,
    merged.weapon_name,
    merged.primary_equipment_name,
    merged.primary_equipment_identity
  )

  return {
    ...merged,
    // Do not promote a generic “XX型/方向/构型” title to an explicit
    // equipment identity. Old snapshots often keep the concrete weapon name
    // only in the portrait prose, and capabilityTitle() can recover it there.
    equipment_name: explicitName || (
      genericName && !/(?:型|方向|类别|路线|构型)$/.test(genericName)
        ? genericName
        : ''
    ),
    equipment_direction: normalizedDirection,
    problem_statement: textValue(
      merged.problem_statement,
      merged.capability_gap,
      draft.problem_statement,
      modules.problem,
      modules.capability_gap
    ),
    operational_process: textValue(
      merged.operational_process,
      draft.operational_process,
      merged.operational_mechanism,
      modules.operational_process
    ),
    scientific_principle: textValue(
      merged.scientific_principle,
      merged.technical_principle,
      draft.technology_implementation,
      merged.implementation_concept,
      modules.technology
    ),
    capability_outcome: textValue(
      merged.capability_outcome,
      draft.capability_effects,
      merged.direct_military_effects,
      merged.capability_image,
      modules.outcome
    ),
    winning_mechanism: textValue(
      merged.winning_mechanism,
      merged.source_winning_logic,
      draft.winning_logic,
      merged.winning_logic,
      modules.winning_logic
    )
  }
}

export const normalizeCapabilities = (items) => (
  Array.isArray(items) ? items.map((item) => normalizeCapability(item)) : []
)

const PORTRAIT_LABELS = [
  '概述',
  '装备与技术实现',
  '关键作战流程',
  '形成能力与作战效果',
  '制胜逻辑机理与对抗边界',
  '制胜逻辑机理',
  '制胜逻辑',
  '发展与验证路径',
  '决策与考核口径'
]
const S6_PORTRAIT_LABEL_ORDER = [
  '概述',
  '装备与技术实现',
  '关键作战流程',
  '形成能力与作战效果',
  '制胜逻辑机理'
]

const DIMENSION_LABELS = {
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

const normalizeText = (value) => String(value ?? '').replace(/\s+/g, ' ').trim()

const CAPABILITY_NAMED_EQUIPMENT_RE = /[“"「『]([^”"」』\n]{2,80}(?:巡飞弹|导弹|弹药|无人机|无人艇|无人车|无人潜航器|鱼雷|火箭弹|炸弹|武器系统|效应器|平台))[”"」』]/g

export const capabilityDirection = (item = {}) => {
  const value = textValue(
    item.equipment_direction,
    item.equipmentDirection,
    item.equipment_direction_name,
    item.innovation_variant_name
  )
  if (value) return value.endsWith('型') ? `${value}装备` : value
  const name = normalizeText(item.name)
  if (!/(?:型|方向|类别|路线|构型)$/.test(name)) return ''
  return name.endsWith('型') ? `${name}装备` : name
}

export const capabilityDisplayEquipmentForm = (item = {}) => {
  const name = normalizeText(item.name)
  const form = textValue(item.equipment_form, item.equipment_forms, item.equipment_category, item.innovation_equipment_form)
  const kind = (value) => {
    if (/无人机|无人平台|无人艇|无人车|无人潜航/.test(value)) return 'platform'
    if (/拦截弹|巡飞|导弹|弹药|鱼雷|水雷/.test(value)) return 'munition'
    if (/激光武器|高功率微波|定向能/.test(value)) return 'directed-energy'
    return ''
  }
  return kind(name) && kind(form) && kind(name) !== kind(form)
    ? textValue(item.primary_equipment_identity, item.name)
    : form
}

export const capabilityTitle = (item = {}) => {
  const direction = capabilityDirection(item)
  const explicit = textValue(
    item.equipment_name,
    item.equipmentName,
    item.weapon_name,
    item.primary_equipment_name
  )
  if (explicit && explicit !== direction) return explicit

  const name = textValue(item.name, item.title, item.capability_name)
  if (name && name === direction) return name
  if (name && name !== direction && !/(?:型|方向|类别|路线|构型)$/.test(name)) return name

  const modules = objectValue(item.capability_portrait_modules)
  const portrait = [item.deep_capability_portrait, item.capability_image, ...Object.values(modules)]
    .map((value) => String(value || '').trim())
    .filter(Boolean)
    .join(' ')
  CAPABILITY_NAMED_EQUIPMENT_RE.lastIndex = 0
  const match = CAPABILITY_NAMED_EQUIPMENT_RE.exec(portrait)
  return textValue(
    match?.[1],
    name,
    direction,
    item.primary_equipment_identity,
    item.display_name,
    item.capability_id,
    item.id
  ) || '未命名装备'
}

export const capabilityConfidence = (item = {}) => {
  const value = Number(item.confidence ?? item.score ?? item.snapshot?.confidence)
  if (!Number.isFinite(value)) return '—'
  return `${(value <= 1 ? value * 100 : value).toFixed(1)}%`
}

const sanitizePortraitText = (value) => normalizeText(value)
  .replace(/\b(?:key_technologies|system_architecture|implementation_path|key_bottlenecks|keyword_context|intelligence_requirement|latency_requirement|coordination_requirement|enabling_technologies|module_content|operational_steps|capability_portrait_modules)\b/g, ' ')
  .replace(/['"]?[a-z][a-z0-9]*(?:_[a-z0-9]+)+['"]?\s*:/g, ' ')
  .replace(/[{}'=]/g, ' ')
  .replaceAll('[', ' ')
  .replaceAll(']', ' ')
  .replace(/\s+/g, ' ')
  .trim()

const sanitizePortraitModuleText = (value, label = '') => {
  let text = normalizeText(value)
    .replace(/^(?:[-–—·•*]\s*)+/, '')
    .replace(/\s+(?:[-–—·•*]\s*)+$/, '')
    .trim()
  if (label === '概述') {
    // Legacy S6 prose sometimes embeds the classification sentence at the
    // beginning of the overview. The card already renders that information as
    // dimension pills, so keeping it here duplicates React's presentation.
    const withoutFullSentence = text.replace(/^能力分类\s*[：:]\s*.*?。\s*/, '').trim()
    text = withoutFullSentence === text
      ? text.replace(/^能力分类\s*[：:]\s*.*?[；;]\s*/, '').trim()
      : withoutFullSentence
  }
  return text
}

export const capabilityPortraitModules = (item = {}) => {
  const modules = objectValue(item.capability_portrait_modules)
  const draft = objectValue(item.capability_card_draft)
  const fallback = [
    ['概述', modules.overview || item.problem_statement || item.capability_gap || draft.problem_statement],
    ['装备与技术实现', modules.technology_implementation || modules.technology || item.scientific_principle || draft.technology_implementation],
    ['关键作战流程', modules.operational_process || item.operational_process || draft.operational_process],
    ['形成能力与作战效果', modules.capability_effects || modules.outcome || item.capability_outcome || draft.capability_effects],
    ['制胜逻辑机理', modules.winning_logic || item.winning_mechanism || draft.winning_logic]
  ].map(([label, text]) => ({ label, text: sanitizePortraitModuleText(text, label) })).filter((entry) => entry.text)

  const raw = sanitizePortraitText(item.deep_capability_portrait || item.capability_image)
  if (!raw) return fallback
  const pattern = new RegExp(
    `(${PORTRAIT_LABELS.join('|')})(?:\\s*[（(][^\\n）)]{1,24}[）)])?\\s*[：:]`,
    'g'
  )
  const matches = [...raw.matchAll(pattern)]
  if (!matches.length) {
    return fallback.length >= 5
      ? fallback
      : [{ label: '概述', text: raw }, ...fallback.filter((entry) => entry.label !== '概述')]
  }

  const parsed = []
  const lead = sanitizePortraitModuleText(raw.slice(0, matches[0].index), '概述')
  if (lead) parsed.push({ label: '概述', text: lead })
  matches.forEach((match, index) => {
    const label = match[1] === '制胜逻辑机理与对抗边界' ? '制胜逻辑机理' : match[1]
    const text = sanitizePortraitModuleText(
      raw.slice(match.index + match[0].length, matches[index + 1]?.index ?? raw.length),
      label
    )
    if (!text) return
    const existing = parsed.find((entry) => entry.label === label)
    if (existing) existing.text = `${existing.text}\n${text}`
    else parsed.push({ label, text })
  })
  if (!parsed.length) return fallback
  const normalized = parsed.map((entry) => ({
    ...entry,
    label: ['制胜逻辑机理与对抗边界', '制胜逻辑'].includes(entry.label)
      ? '制胜逻辑机理'
      : entry.label
  }))
  const byLabel = new Map()
  normalized.forEach((entry) => {
    if (!byLabel.has(entry.label)) byLabel.set(entry.label, entry.text)
  })
  const ordered = S6_PORTRAIT_LABEL_ORDER
    .filter((label) => byLabel.has(label))
    .map((label) => ({ label, text: byLabel.get(label) }))
  const extras = normalized.filter((entry) => !S6_PORTRAIT_LABEL_ORDER.includes(entry.label))
  return [...ordered, ...extras]
}

export const capabilityPortraitComplete = (item = {}) => {
  const labels = new Set(capabilityPortraitModules(item).map((entry) => entry.label))
  return ['概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果']
    .every((label) => labels.has(label)) && ['制胜逻辑机理', '制胜逻辑'].some((label) => labels.has(label))
}

const dimensionLabel = (value) => {
  const normalized = normalizeText(value)
  if (DIMENSION_LABELS[normalized]) return DIMENSION_LABELS[normalized]
  const inferred = [
    [/毁伤|摧毁|杀伤|破坏/, 'damage'],
    [/突防|穿透|渗透/, 'penetration'],
    [/拦截|阻断目标/, 'interception'],
    [/压制|抑制/, 'suppression'],
    [/拒止|禁入|区域控制/, 'denial'],
    [/侦察|感知|探测|识别/, 'reconnaissance'],
    [/预警|提前发现/, 'early_warning'],
    [/电子对抗|干扰|电磁/, 'electronic_countermeasure'],
    [/威慑/, 'deterrence'],
    [/生存|抗毁|恢复|韧性/, 'survivability'],
    [/战场控制|作战主动权|时空控制/, 'battlefield_control'],
    [/打击|弹药|巡猎|攻击|火力/, 'strike']
  ].find(([pattern]) => pattern.test(normalized))
  return inferred ? DIMENSION_LABELS[inferred[1]] : normalized
}

export const capabilityDimensions = (item = {}) => {
  const classification = item.capability_classification
  if (!classification) return { values: [], basis: '' }
  if (typeof classification !== 'object' || Array.isArray(classification)) {
    const values = String(classification).split(/[、,，;；]/).map(dimensionLabel).filter(Boolean)
    return { values: [...new Set(values)].slice(0, 3), basis: '' }
  }
  const primary = normalizeText(classification.primary_dimension || classification.primary)
  const rawSecondary = classification.secondary_dimensions || classification.secondary || []
  const secondary = Array.isArray(rawSecondary)
    ? rawSecondary
    : String(rawSecondary).split(/[、,，;；]/)
  const primaryLabel = dimensionLabel(primary)
  const seen = new Set(primaryLabel ? [primaryLabel] : [])
  const secondaryLabels = secondary.map((value) => ({ raw: normalizeText(value), label: dimensionLabel(value) })).filter(({ raw, label }) => {
    if (!label || seen.has(label)) return false
    if (/弹|弹药|导弹|巡飞|母弹|平台|战斗体|舱|无人机|无人艇|无人车/.test(raw) && !/维度$/.test(raw)) return false
    seen.add(label)
    return true
  }).map(({ label }) => label)
  const values = [primaryLabel, ...secondaryLabels].filter(Boolean).slice(0, 3)
  return { values, basis: normalizeText(classification.classification_basis) }
}

export const capabilityVersionMeta = (item = {}) => {
  const formalBaseline = String(item.version_id || item.id || '').startsWith('baseline-') && item.is_deep_research !== true
  const source = normalizeText(item.source || item.version_source || (item.is_deep_research ? 'reference_weapon_deep_research' : 'formal_s6'))
  const rawStatus = normalizeText(item.verification_status || item.version_status || item.status || (item.confidence_limited ? 'pending_verification' : formalBaseline ? 'formal' : '')).toLowerCase()
  const status = formalBaseline ? 'formal' : rawStatus || (source === 'formal_s6' ? 'formal' : 'pending_verification')
  const version = String(item.version_no ?? item.version ?? item.research_version ?? (status === 'formal' ? 1 : '')).replace(/^v/i, '')
  const statusLabel = ['verified', 'formal', 'approved', 'accepted'].includes(status)
    ? status === 'formal' ? '正式基线' : '已核验'
    : status === 'deleted' ? '已删除'
      : status === 'rejected' ? '已驳回'
        : ['rolled_back', 'rollback'].includes(status) ? '已回滚' : '待核验'
  return { formalBaseline, source, status, version, statusLabel }
}

export const isCapabilityDeepResearch = (item = {}) => {
  const meta = capabilityVersionMeta(item)
  if (meta.formalBaseline) return false
  return Boolean(
    item.is_deep_research ||
    meta.source !== 'formal_s6' ||
    ['pending', 'pending_verification', 'unverified', 'partial', 'rejected', 'rolled_back'].includes(meta.status)
  )
}

export const capabilityCardKey = (item = {}) => {
  const prefix = isCapabilityDeepResearch(item) ? 'deep:' : ''
  const identity = textValue(item.version_id, item.card_binding_id, item.card_key, item.capability_id, item.hypothesis_id, item.id, capabilityTitle(item))
  return `${prefix}${identity}`
}

export const capabilityLineageKey = (item = {}) => {
  for (const field of ['hypothesis_id', 'card_binding_id', 'capability_id']) {
    const value = normalizeText(item[field]).toLowerCase()
    if (value) return `${field}:${value}`
  }
  return `legacy:${normalizeText(capabilityTitle(item)).toLowerCase()}`
}

export const capabilityComparisonFields = (formalItem = {}, currentItem = {}) => {
  const formalModules = new Map(capabilityPortraitModules(formalItem).map((entry) => [entry.label, entry.text]))
  const currentModules = new Map(capabilityPortraitModules(currentItem).map((entry) => [entry.label, entry.text]))
  const formalDimensions = capabilityDimensions(formalItem).values.join('、') || '—'
  const currentDimensions = capabilityDimensions(currentItem).values.join('、') || '—'
  return [
    ['装备名称', capabilityTitle(formalItem), capabilityTitle(currentItem)],
    ['装备方向', capabilityDirection(formalItem) || capabilityDisplayEquipmentForm(formalItem) || '—', capabilityDirection(currentItem) || capabilityDisplayEquipmentForm(currentItem) || '—'],
    ['能力分类', formalDimensions, currentDimensions],
    ...['概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果'].map((label) => [
      label,
      formalModules.get(label) || '—',
      currentModules.get(label) || '—'
    ]),
    [
      '制胜逻辑机理',
      formalModules.get('制胜逻辑机理') || formalModules.get('制胜逻辑') || '—',
      currentModules.get('制胜逻辑机理') || currentModules.get('制胜逻辑') || '—'
    ]
  ]
}
