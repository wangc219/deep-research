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

test('技术栏目默认只提供目标和背景，完整方案仅在明确选用时生成', () => {
  const prompt = portraitSectionPrompt('装备与技术实现', '测试装备', '现有技术描述', '原始概述')
  assert.match(prompt, /测试装备/)
  assert.match(prompt, /装备与技术实现/)
  assert.match(prompt, /原始概述/)
  assert.match(prompt, /现有技术描述/)
  assert.match(prompt, /现有描述可核验与修正/)
  assert.doesNotMatch(prompt, /七章|七级|必须|冻结|WBS|30\/60\/90/)
  assert.ok(prompt.length < 400)
  assert.equal(TECHNOLOGY_CABIN_ACTIONS.length, 7)
  assert.equal(TECHNOLOGY_SOLUTION_CHAPTERS.length, 7)
  const solution = technologyCabinPrompt('测试装备', '', 'implementation_plan')
  assert.match(solution, /请形成一份可交付的技术实现方案/)
  assert.match(solution, /武器装备研发技术方案报告/)
  assert.match(solution, /面向研发人员 · 技术路线设计 · 关键问题攻关 · 工程实现/)
  for (const chapter of [
    '项目概述与研发需求',
    '总体技术方案',
    '核心技术体系',
    '关键技术攻关',
    '技术实现方案',
    '技术路线与研发计划',
    '预期成果与应用价值'
  ]) {
    assert.match(solution, new RegExp(chapter))
  }
  assert.match(solution, /必要时重构新质武器装备/)
  assert.match(solution, /而不是资料综述/)
})

test('技术研究角度按需展开，默认使用自主研究智能体', () => {
  assert.equal(WEAPON_SCHEME_AGENT_SLUG, 'weapon-equipment-scheme')
  assert.match(deepView, /const technologyCabinMode = computed/)
  assert.match(deepView, /`技术攻关舱 · \$\{name\}`/)
  assert.match(
    deepView,
    /payload\?\.research_section \|\| ''\)\.trim\(\) === requestedSection\.value/
  )
  assert.match(deepView, /class="technology-cabin-panel"/)
  assert.match(deepView, /class="technology-cabin-sources"/)
  assert.match(deepView, /Open Web/)
  assert.match(deepView, /本地知识库/)
  assert.match(deepView, /AMiner/)
  assert.match(deepView, /v-for="\(item, index\) in TECHNOLOGY_CABIN_ACTIONS"/)
  assert.match(deepView, /聚焦当前装备/)
  assert.match(deepView, /const recommendedAgentSlug = \(\) => 'deep-research'/)
  assert.match(deepView, /technologyCabinMode && usesNativeAgent && !conversationFocusMode/)
  assert.match(deepView, /session\.payload\?\.agent_name \|\| '深度研究'/)
  assert.match(deepView, /technologyCabinPrompt\(target, sectionBody, actionId, overviewBody\)/)
  assert.match(
    deepView,
    /portraitSectionPrompt\(item\.label, boundEquipment\.value, item\.text, overviewBody\)/
  )
  assert.match(
    deepView,
    /const prefillDeepAction = async[\s\S]*?submitPrompt\(prompt, \{ send: false \}\)/
  )
  assert.match(
    deepView,
    /prefillRequestedSection[\s\S]*?submitPrompt\(prompt, \{ send: false, onlyIfEmpty: true \}\)/
  )
  assert.match(deepView, /draft-scope="equipment-deep"/)
  assert.match(deepView, /class="conversation-launch-composer"/)
  assert.match(deepView, /class="conversation-context-bar"/)
  assert.match(deepView, /v-model:open="bindingTreeOpen"/)
  assert.match(deepView, /filteredQueryRunOptions/)
  assert.match(deepView, /class="binding-query-node"/)
  assert.match(deepView, /class="binding-equipment-node"/)
  assert.match(deepView, /class="binding-equipment-panel"/)
  assert.match(deepView, /class="binding-portrait-panel"/)
  assert.match(deepView, /能力画像五栏/)
  assert.match(deepView, /按模板生成技术方案/)
  assert.match(
    deepView,
    /technologyCabinPrompt\(choice\.name, section\.text, 'implementation_plan', overview\)/
  )
  assert.match(deepView, /class="conversation-tool-button"/)
  assert.match(deepView, /更多设置/)
  assert.match(deepView, /v-model:value="form\.agent_slug"/)
  assert.match(deepView, /<ModelSelectorComponent/)
  assert.doesNotMatch(deepView, /launchPrompts/)
  assert.match(deepView, /queryRunOptions/)
  assert.match(deepView, /runs\.value\.map/)
  assert.doesNotMatch(deepView, /v-model:value="form\.project_id"/)
  assert.match(deepView, /equipmentChoices/)
  assert.match(deepView, /selectEquipmentFromTree/)
  assert.match(deepView, /selectQuickCapability/)
  assert.match(deepView, /selectQuickReference/)
  assert.match(deepView, /参考武器/)
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
  assert.match(prompt, /S5只负责入选/)
  assert.match(prompt, /冻结为共享创新锚点/)
  assert.match(prompt, /当前背景、解决思路、达到效果、核心创新/)
  assert.match(prompt, /360–400 个有效中文字/)
  assert.match(prompt, /不加“修订”等后缀/)
  assert.match(prompt, /save_equipment_capability_draft/)
  assert.match(prompt, /capability_portrait_modules/)
  assert.match(prompt, /capability_card_draft/)
  assert.match(deepView, /s6CapabilityCardPrompt/)
  assert.match(deepView, /const recommendedAgentSlug = \(\) => 'deep-research'/)
})

test('最终技术方案从定稿动作后的回答提取，并融合到对应原卡技术栏目', () => {
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
  assert.match(
    capabilitiesView,
    /<CapabilityPortraitCard[\s\S]*?<template #technology-solution>[\s\S]*?<EquipmentTechnologySolutionCard[\s\S]*?<\/CapabilityPortraitCard>/
  )
  assert.match(capabilitiesView, /v-if="technologySessionFor\(item\)"/)
  assert.match(capabilitiesView, /loadTechnologySessions\(\)/)
  assert.match(solutionCard, /原能力画像配套研发成果/)
  assert.match(solutionCard, /核心技术[\s\S]*卡点根因[\s\S]*工程实现[\s\S]*试验验证/)
})
