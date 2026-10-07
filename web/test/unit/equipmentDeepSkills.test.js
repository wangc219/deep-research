import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from 'vue/compiler-sfc'
import {
  MAX_EQUIPMENT_DEEP_SKILLS,
  equipmentDeepSkillLimit,
  equipmentDeepSkillSourceLabel,
  filterAccessibleDeepSkills,
  normalizeAccessibleDeepSkills,
  normalizeEquipmentDeepSkillIds,
  reconcileEquipmentDeepSkillIds,
  toggleEquipmentDeepSkillId
} from '../../src/utils/equipmentDeepSkills.js'

const accessibleSkills = [
  {
    slug: 'evidence-review',
    name: '证据核验',
    description: '核对关键论断与来源',
    source_scope: 'builtin',
    triggers: ['证据', '核验'],
    tool_dependencies: ['browser']
  },
  {
    skill_id: 'concept-divergence',
    name: '概念发散',
    description: '生成正交装备方向',
    source_scope: 'personal'
  },
  { slug: 'disabled-skill', name: '不可用', enabled: false },
  { slug: 'evidence-review', name: '重复项' }
]

test('可访问 Skill 响应统一为深研目录并过滤禁用项和重复项', () => {
  const normalized = normalizeAccessibleDeepSkills({ success: true, data: accessibleSkills })

  assert.deepEqual(
    normalized.map((item) => item.skill_id),
    ['evidence-review', 'concept-divergence']
  )
  assert.equal(normalized[0].slug, 'evidence-review')
  assert.equal(normalized[0].source_scope, 'builtin')
  assert.deepEqual(normalized[0].triggers, ['证据', '核验'])
  assert.equal(equipmentDeepSkillSourceLabel('personal'), '个人 Skill')
})

test('本轮 Skill 去重、限制为最多 12 项并只保留可访问项', () => {
  const ids = Array.from({ length: 15 }, (_, index) => `skill-${index}`)
  assert.equal(MAX_EQUIPMENT_DEEP_SKILLS, 12)
  assert.equal(equipmentDeepSkillLimit(99), 12)
  assert.equal(equipmentDeepSkillLimit(0), 1)
  assert.deepEqual(normalizeEquipmentDeepSkillIds([...ids, ids[0]]), ids.slice(0, 12))

  const catalog = ids.map((slug) => ({ slug }))
  assert.deepEqual(
    reconcileEquipmentDeepSkillIds(['missing', ...ids], catalog),
    ids.slice(0, 12)
  )
})

test('多选切换报告达到上限和不可访问状态，取消选择可恢复容量', () => {
  const catalog = Array.from({ length: 13 }, (_, index) => ({ slug: `skill-${index}` }))
  const full = catalog.slice(0, 12).map((item) => item.slug)

  assert.deepEqual(
    toggleEquipmentDeepSkillId({
      selected: full,
      skillId: 'skill-12',
      enabled: true,
      skills: catalog
    }),
    { selected: full, limited: true, unavailable: false }
  )
  assert.deepEqual(
    toggleEquipmentDeepSkillId({
      selected: full,
      skillId: 'skill-0',
      enabled: false,
      skills: catalog
    }),
    { selected: full.slice(1), limited: false, unavailable: false }
  )
  assert.deepEqual(
    toggleEquipmentDeepSkillId({
      selected: [],
      skillId: 'private-skill',
      enabled: true,
      skills: catalog
    }),
    { selected: [], limited: false, unavailable: true }
  )
})

test('搜索覆盖 ID、名称、描述、触发词和依赖', () => {
  assert.deepEqual(
    filterAccessibleDeepSkills(accessibleSkills, '概念').map((item) => item.skill_id),
    ['concept-divergence']
  )
  assert.deepEqual(
    filterAccessibleDeepSkills(accessibleSkills, 'browser').map((item) => item.skill_id),
    ['evidence-review']
  )
  assert.deepEqual(
    filterAccessibleDeepSkills(accessibleSkills, '核验').map((item) => item.skill_id),
    ['evidence-review']
  )
})

test('Skill 选择器暴露 session 级 v-model 契约并可通过 SFC 编译', () => {
  const source = readFileSync(
    new URL('../../src/components/equipment/EquipmentDeepSkillPicker.vue', import.meta.url),
    'utf8'
  )
  const { descriptor, errors } = parse(source, { filename: 'EquipmentDeepSkillPicker.vue' })

  assert.deepEqual(errors, [])
  assert.doesNotThrow(() =>
    compileScript(descriptor, {
      id: 'equipment-deep-skill-picker-test',
      inlineTemplate: true
    })
  )
  assert.match(source, /emit\('update:modelValue', \[\.\.\.next\]\)/)
  assert.match(source, /sessionId: props\.sessionId/)
  assert.match(source, /skillApi\.listAccessibleSkills\(\)/)
  assert.match(source, /每轮最多选择 \$\{limit\.value\} 个 Skill/)
  assert.match(source, /class="deep-skill-chips"/)
  assert.match(source, /aria-label="搜索 Skill"/)
  assert.match(source, /var\(--color-bg-container\)/)
})
