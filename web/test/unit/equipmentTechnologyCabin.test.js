import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  CAPABILITY_PORTRAIT_AGENT_SLUG,
  TECHNOLOGY_CABIN_ACTIONS,
  TECHNOLOGY_SOLUTION_CHAPTERS,
  WEAPON_SCHEME_AGENT_SLUG,
  isTechnologyCabinSection,
  portraitSectionPrompt,
  s6CapabilityCardPrompt,
  technologyCabinPrompt
} from '../../src/utils/equipmentDeepPortraitSections.js'
import {
  latestTechnologySession,
  technologySolutionFromSession
} from '../../src/utils/equipmentTechnologySolutions.js'

const readSource = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

const portraitCard = readSource('../../src/components/equipment/CapabilityPortraitCard.vue')
const deepView = readSource('../../src/views/equipment/EquipmentDeepThinkingView.vue')
const capabilitiesView = readSource('../../src/views/equipment/EquipmentCapabilitiesView.vue')
const solutionCard = readSource(
  '../../src/components/equipment/EquipmentTechnologySolutionCard.vue'
)

test('装备与技术实现使用技术攻关舱入口，其他栏目继续使用深挖本栏', () => {
  assert.equal(isTechnologyCabinSection('装备与技术实现'), true)
  assert.equal(isTechnologyCabinSection('关键作战流程'), false)
  assert.match(portraitCard, /isTechnologyCabinSection\(entry\.label\)/)
  assert.match(portraitCard, /'技术攻关舱' : '深挖本栏'/)
  assert.match(portraitCard, /<Wrench v-if="isTechnologyCabinSection\(entry\.label\)"/)
})

test('技术攻关舱提示词覆盖七级研究方案链、验证与成熟度风险', () => {
  const prompt = portraitSectionPrompt('装备与技术实现', '测试装备', '现有技术描述')
  assert.ok(prompt.length < 900, '初始预填应足够明确且避免冗长')
  assert.match(prompt, /保持装备身份/)
  assert.match(prompt, /原卡中的相关技术仅作为研究线索/)
  assert.match(prompt, /纠偏只作为方案设计输入/)
  const workflow = TECHNOLOGY_CABIN_ACTIONS.map((item) =>
    technologyCabinPrompt('测试装备', '', item.id)
  ).join('\n')
  for (const keyword of [
    '能力',
    '总体',
    '技术体系',
    '关键',
    '难突破',
    '解决路径',
    '材料',
    '接口',
    '试验'
  ]) {
    assert.match(workflow, new RegExp(keyword))
  }
  assert.equal(TECHNOLOGY_CABIN_ACTIONS.length, 7)
  assert.deepEqual(
    TECHNOLOGY_SOLUTION_CHAPTERS.map((item) => item.title),
    ['能力目标', '装备总体设计', '技术体系', '关键技术识别', '突破难点', '解决路径', '具体实现']
  )
  const solution = technologyCabinPrompt('测试装备', '', 'implementation_plan')
  assert.match(solution, /一线研发人员/)
  assert.match(solution, /能力—设计—技术—关键项—难点—路径—实现/)
  for (const chapter of TECHNOLOGY_SOLUTION_CHAPTERS) {
    assert.match(solution, new RegExp(chapter.title))
  }
  for (const keyword of [
    '输入输出接口',
    '预算',
    'WBS',
    '试验矩阵',
    '决策门',
    '30/60/90天',
    '工程假设/TBD'
  ]) {
    assert.match(solution, new RegExp(keyword))
  }
  assert.match(solution, /不得重复写成长篇纠错报告/)
  assert.match(solution, /不得覆盖原文件/)
})

test('深研页呈现七级技术攻关链并默认调用武器装备研究方案智能体', () => {
  assert.equal(WEAPON_SCHEME_AGENT_SLUG, 'weapon-equipment-scheme')
  assert.match(deepView, /const technologyCabinMode = computed/)
  assert.match(deepView, /`技术攻关舱 · \$\{name\}`/)
  assert.match(
    deepView,
    /payload\?\.research_section \|\| ''\)\.trim\(\) === requestedSection\.value/
  )
  assert.match(deepView, /class="technology-cabin-panel"/)
  assert.match(deepView, /v-for="\(item, index\) in TECHNOLOGY_CABIN_ACTIONS"/)
  assert.match(deepView, /装备身份锁定/)
  assert.match(deepView, /WEAPON_SCHEME_AGENT_SLUG/)
  assert.match(deepView, /weaponSchemeAgentAvailable/)
  assert.match(deepView, /session\.payload\?\.agent_name \|\| '武器装备研究方案'/)
  assert.match(deepView, /technologyCabinPrompt\(target, sectionBody, actionId\)/)
  assert.match(
    deepView,
    /const prefillDeepAction = async[\s\S]*?submitPrompt\(prompt, \{ send: false \}\)/
  )
  assert.match(
    deepView,
    /prefillRequestedSection[\s\S]*?submitPrompt\(prompt, \{ send: false, onlyIfEmpty: true \}\)/
  )
  assert.match(deepView, /draft-scope="equipment-deep"/)
})

test('形成新版能力卡在生成阶段执行正式 S6 五栏逐栏自检', () => {
  assert.equal(CAPABILITY_PORTRAIT_AGENT_SLUG, 'equipment-capability-portrait')
  const prompt = s6CapabilityCardPrompt('测试装备')
  for (const label of [
    '概述',
    '装备与技术实现',
    '关键作战流程',
    '形成能力与作战效果',
    '制胜逻辑机理'
  ]) {
    assert.match(prompt, new RegExp(label))
  }
  assert.match(prompt, /先分别起草五栏，再逐栏检查/)
  assert.match(prompt, /360–400 个有效中文字/)
  assert.match(prompt, /不加“修订”等后缀/)
  assert.match(prompt, /save_equipment_capability_draft/)
  assert.match(prompt, /capability_portrait_modules/)
  assert.match(prompt, /capability_card_draft/)
  assert.match(deepView, /s6CapabilityCardPrompt/)
  assert.match(deepView, /capabilityPortraitAgentAvailable/)
  assert.match(deepView, /CAPABILITY_PORTRAIT_AGENT_SLUG/)
  assert.match(
    deepView,
    /mode === 'new_weapon_diverge'[\s\S]*?CAPABILITY_PORTRAIT_AGENT_SLUG/
  )
  assert.match(deepView, /能力画像智能体择优生成五栏卡/)
})

test('最终技术方案从定稿动作后的回答提取，并挂在对应原卡上方', () => {
  const session = {
    session_id: 'tech-1',
    updated_at: '2026-09-28T10:00:00Z',
    payload: { research_section: '装备与技术实现', capability_card_key: 'card-1' },
    messages: [
      { role: 'assistant', content: '阶段讨论，不应作为最终方案' },
      { role: 'user', content: technologyCabinPrompt('测试装备', '', 'solution_blueprint') },
      { role: 'assistant', content: '研发目标与指标\n形成具体技术实现方案' }
    ]
  }
  assert.equal(latestTechnologySession([session], { card_key: 'card-1' }), session)
  assert.equal(
    technologySolutionFromSession(session)?.content,
    '研发目标与指标\n形成具体技术实现方案'
  )
  assert.match(capabilitiesView, /<EquipmentTechnologySolutionCard[\s\S]*?<CapabilityPortraitCard/)
  assert.match(capabilitiesView, /loadTechnologySessions\(\)/)
  assert.match(solutionCard, /原能力画像配套研发成果/)
  assert.match(solutionCard, /核心技术[\s\S]*卡点根因[\s\S]*工程实现[\s\S]*试验验证/)
})
