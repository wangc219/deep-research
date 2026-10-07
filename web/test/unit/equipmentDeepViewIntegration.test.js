import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const readSource = (relativePath) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

const deepView = readSource('../../src/views/equipment/EquipmentDeepThinkingView.vue')
const nativeChat = readSource('../../src/components/AgentChatComponent.vue')

test('深研主页面按 agent runtime 与 thread_id 分流原生和旧版会话', () => {
  assert.match(
    deepView,
    /const usesNativeAgent = computed\([\s\S]*?payload\?\.runtime === 'agent'[\s\S]*?Boolean\(nativeThreadId\.value\)[\s\S]*?\)/
  )
  assert.match(
    deepView,
    /<AgentChatComponent\s+v-if="usesNativeAgent"[\s\S]*?<\/AgentChatComponent>\s*<EquipmentLegacyDeepSession\s+v-else/
  )
  assert.match(deepView, /<EquipmentLegacyDeepSession[\s\S]*?@submit="submitLegacyMessage"/)
})

test('新用户首次进入深研时创建并选中武器装备深研默认项目', () => {
  assert.match(deepView, /projectsStore\.ensureEquipmentProject\(\)/)
  assert.match(
    deepView,
    /const ownProjects = loadedProjects\.filter\([\s\S]*?const defaultProject = ownProjects\[0\] \|\|[\s\S]*?ensureEquipmentProject\(\)/
  )
  assert.match(
    deepView,
    /if \(!form\.value\.project_id && defaultProject\?\.id\) form\.value\.project_id = defaultProject\.id/
  )
})

test('深研新建仅按真实权限限制，历史来源本身可继续修改', () => {
  assert.match(deepView, /const selectedRunReadOnly = computed/)
  assert.match(deepView, /Boolean\(selectedRun\.value\?\.readonly\)/)
  assert.match(deepView, /const isReadOnlyRun = \(run\)/)
  assert.match(deepView, /const createSession = async \(\) => \{[\s\S]*?selectedRunReadOnly\.value[\s\S]*?历史研究任务为只读数据/)
  assert.match(deepView, /if \(isReadOnlyRun\(targetRun\)\)/)
  assert.match(deepView, /if \(isReadOnlyRun\(requestedRun\)\)/)
  assert.match(deepView, /:disabled="selectedRunReadOnly"[\s\S]*?创建深研会话/)
})

test('会话 Skill 选择通过 deepRunMeta 传入平台原生运行', () => {
  assert.match(deepView, /<EquipmentDeepSkillPicker\s+v-model="activeSkillIds"/)
  assert.match(
    deepView,
    /const deepRunMeta = computed\(\(\) => \(\{[\s\S]*?equipment_active_skill_ids: activeSkillIds\.value[\s\S]*?\}\)\)/
  )
  assert.match(deepView, /<AgentChatComponent[\s\S]*?:run-meta="deepRunMeta"/)
})

test('深研双模式贯穿运行元数据且栏目深化为保守默认', () => {
  assert.match(deepView, /const researchMode = ref\('section_deepen'\)/)
  assert.match(
    deepView,
    /const resolveResearchMode = \(value\) =>[\s\S]*?RESEARCH_MODE_IDS\.has\(value\) \? value : 'section_deepen'/
  )
  assert.match(
    deepView,
    /researchMode\.value = requestedSection\.value[\s\S]*?\? 'section_deepen'[\s\S]*?: resolveResearchMode\(payload\.research_mode\)/
  )
  assert.match(
    deepView,
    /equipment_deep_mode: researchMode\.value,[\s\S]*?equipment_deep_section: activeResearchSection\.value/
  )
  assert.match(deepView, /setResearchMode\('section_deepen'\)/)
  assert.match(deepView, /setResearchMode\('new_weapon_diverge'\)/)
  assert.match(deepView, /所有动作都会先填入输入框/)
  assert.match(
    deepView,
    /const diveIntoSection = async[\s\S]*?submitPrompt\(prompt, \{ send: false \}\)/
  )
  assert.match(
    deepView,
    /const prefillDeepAction = async[\s\S]*?submitPrompt\(prompt, \{ send: false \}\)/
  )
})

test('原生 Agent 运行完成后刷新当前会话和候选能力版本', () => {
  assert.match(deepView, /@run-completed="handleRunCompleted"/)
  assert.match(
    deepView,
    /const handleRunCompleted = async \(\) => \{[\s\S]*?equipmentApi\.getDeepSession\(expectedSessionId\)[\s\S]*?candidateVersions\.value\?\.refresh\?\.\(\)[\s\S]*?\n\}/
  )
  assert.match(nativeChat, /defineEmits\(\[[^\]]*'run-completed'[^\]]*\]\)/)
  assert.match(nativeChat, /emit\('run-completed', \{ threadId, runId, touchedThreadIds \}\)/)
})

test('原生聊天领域投影接入阶段状态和会话候选能力卡', () => {
  const projectionStart = deepView.indexOf('<template\n            #domain-projection=')
  const projectionEnd = deepView.indexOf('<template #empty-state>', projectionStart)

  assert.ok(projectionStart >= 0, '应提供 AgentChatComponent 的 domain-projection 插槽')
  assert.ok(projectionEnd > projectionStart, '领域投影应位于原生聊天组件内部')

  const projection = deepView.slice(projectionStart, projectionEnd)
  assert.match(projection, /<EquipmentDeepStageProjection/)
  assert.match(projection, /:versions="capabilityVersionRows"/)
  assert.match(projection, /:active-skill-ids="activeSkillIds"/)
  assert.match(projection, /:research-mode="researchMode"/)
  assert.match(projection, /:research-section="activeResearchSection"/)
  assert.match(projection, /<EquipmentDeepCandidateVersions/)
  assert.match(projection, /ref="candidateVersions"/)
  assert.match(projection, /:session-id="sessionId"/)
  assert.match(projection, /@loaded="handleCapabilityVersionsLoaded"/)
  assert.match(projection, /@changed="handleCapabilityVersionsLoaded"/)
  assert.match(nativeChat, /<slot\s+name="domain-projection"/)
})

test('能力画像单栏入口锁定装备身份并把深挖问题预填到统一对话输入框', () => {
  assert.match(deepView, /const requestedSection = computed/)
  assert.match(
    deepView,
    /const sectionFocus = section[\s\S]*?portraitSectionPrompt\(section\.label, name, section\.text\)/
  )
  assert.match(
    deepView,
    /const prefillRequestedSection = async \(\) => \{[\s\S]*?submitPrompt\(prompt, \{ send: false \}\)/
  )
  assert.match(
    deepView,
    /await syncNativeThread\(\)[\s\S]*?prefilledSectionKey\.value = ''[\s\S]*?await prefillRequestedSection\(\)/
  )
  assert.match(deepView, /class="seed-count current-section-count"/)
  assert.match(deepView, /\.seed-count:not\(\.current-section-count\)/)
  assert.match(deepView, /当前深挖：\{\{ activeResearchSection \}\}/)
})
