export const MAX_EQUIPMENT_DEEP_SKILLS = 12

const text = (value) => String(value ?? '').trim()

const stringList = (value) => {
  if (!Array.isArray(value)) return []
  return [...new Set(value.map(text).filter(Boolean))]
}

const sourceRows = (value) => {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.data)) return value.data
  if (Array.isArray(value?.data?.data)) return value.data.data
  return []
}

export const equipmentDeepSkillLimit = (value = MAX_EQUIPMENT_DEEP_SKILLS) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return MAX_EQUIPMENT_DEEP_SKILLS
  return Math.min(MAX_EQUIPMENT_DEEP_SKILLS, Math.max(1, Math.floor(parsed)))
}

export const equipmentDeepSkillId = (skill) => {
  if (typeof skill === 'string') return text(skill)
  if (!skill || typeof skill !== 'object') return ''
  return text(skill.slug || skill.skill_id || skill.id)
}

const uniqueEquipmentDeepSkillIds = (value) => {
  if (!Array.isArray(value)) return []
  return [...new Set(value.map(equipmentDeepSkillId).filter(Boolean))]
}

export function normalizeAccessibleDeepSkills(payload) {
  const normalized = []
  const seen = new Set()

  for (const item of sourceRows(payload)) {
    const skill = typeof item === 'string' ? { slug: item } : item
    const skillId = equipmentDeepSkillId(skill)
    if (!skillId || seen.has(skillId) || skill?.enabled === false) continue
    seen.add(skillId)
    normalized.push({
      ...skill,
      skill_id: skillId,
      slug: skillId,
      name: text(skill?.name) || skillId,
      description: text(skill?.description),
      source_scope: text(skill?.source_scope || skill?.source) || 'shared',
      triggers: stringList(skill?.triggers),
      tool_dependencies: stringList(skill?.tool_dependencies),
      mcp_dependencies: stringList(skill?.mcp_dependencies),
      skill_dependencies: stringList(skill?.skill_dependencies)
    })
  }

  return normalized
}

export function normalizeEquipmentDeepSkillIds(value, maxSelected = MAX_EQUIPMENT_DEEP_SKILLS) {
  const limit = equipmentDeepSkillLimit(maxSelected)
  return uniqueEquipmentDeepSkillIds(value).slice(0, limit)
}

export function reconcileEquipmentDeepSkillIds(
  selected,
  skills,
  maxSelected = MAX_EQUIPMENT_DEEP_SKILLS
) {
  const allowed = new Set(normalizeAccessibleDeepSkills(skills).map((skill) => skill.skill_id))
  return uniqueEquipmentDeepSkillIds(selected)
    .filter((skillId) => allowed.has(skillId))
    .slice(0, equipmentDeepSkillLimit(maxSelected))
}

export function toggleEquipmentDeepSkillId({
  selected,
  skillId,
  enabled,
  skills,
  maxSelected = MAX_EQUIPMENT_DEEP_SKILLS
}) {
  const id = equipmentDeepSkillId(skillId)
  const limit = equipmentDeepSkillLimit(maxSelected)
  const current = reconcileEquipmentDeepSkillIds(selected, skills, limit)
  if (!id) return { selected: current, limited: false, unavailable: true }

  if (!enabled) {
    return {
      selected: current.filter((item) => item !== id),
      limited: false,
      unavailable: false
    }
  }

  const allowed = new Set(normalizeAccessibleDeepSkills(skills).map((skill) => skill.skill_id))
  if (!allowed.has(id)) return { selected: current, limited: false, unavailable: true }
  if (current.includes(id)) return { selected: current, limited: false, unavailable: false }
  if (current.length >= limit) return { selected: current, limited: true, unavailable: false }

  return { selected: [...current, id], limited: false, unavailable: false }
}

export function filterAccessibleDeepSkills(skills, query) {
  const normalized = normalizeAccessibleDeepSkills(skills)
  const needle = text(query).toLocaleLowerCase('zh-CN')
  if (!needle) return normalized

  return normalized.filter((skill) =>
    [
      skill.skill_id,
      skill.name,
      skill.description,
      skill.source_scope,
      ...skill.triggers,
      ...skill.tool_dependencies,
      ...skill.mcp_dependencies,
      ...skill.skill_dependencies
    ]
      .filter(Boolean)
      .join(' ')
      .toLocaleLowerCase('zh-CN')
      .includes(needle)
  )
}

export const equipmentDeepSkillSourceLabel = (sourceScope) =>
  ({
    personal: '个人 Skill',
    builtin: '内置 Skill',
    shared: '共享 Skill'
  })[text(sourceScope).toLowerCase()] || '可访问 Skill'

export const sameEquipmentDeepSkillIds = (left, right) => {
  const a = normalizeEquipmentDeepSkillIds(left)
  const b = normalizeEquipmentDeepSkillIds(right)
  return a.length === b.length && a.every((item, index) => item === b[index])
}
