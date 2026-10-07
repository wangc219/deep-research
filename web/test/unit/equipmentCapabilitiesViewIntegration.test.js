import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const view = readFileSync(
  new URL('../../src/views/equipment/EquipmentCapabilitiesView.vue', import.meta.url),
  'utf8'
)
const liveStyles = readFileSync(
  new URL('../../src/assets/css/equipment-workbench-live.css', import.meta.url),
  'utf8'
)

test('能力画像页的基础按钮规则保持低特异性，允许画像卡组件样式生效', () => {
  assert.ok(/:where\(\.capability-page\)\s+button\s*\{/.test(view), '基础按钮规则应使用 :where(.capability-page)')
  assert.ok(!/\.capability-page\s+button\s*\{/.test(view), '高特异性的 .capability-page button 规则会覆盖卡片按钮')
})

test('能力画像页使用与原工作台一致的画布留白和浅色背景', () => {
  const pageRule = view.match(/\.capability-page\s*\{([^}]*)\}/)?.[1] || ''
  assert.ok(/padding\s*:\s*28px\s+32px\s+40px\s*;/.test(pageRule), '桌面画布应保留 28px 32px 40px 留白')
  assert.ok(/background\s*:\s*radial-gradient\(/.test(pageRule), '画布应保留浅色径向背景')
})

test('能力画像页显示最新三条反馈，并将任务状态和研究路线本地化', () => {
  const presentationImport = view.match(/import\s*\{([^}]*)\}\s*from\s*['"]\.\/reportPresentation\.js['"]/)?.[1] || ''
  assert.ok(/feedbackItems\.slice\(-3\)\.reverse\(\)/.test(view), '反馈历史应显示最新三条')
  assert.ok(/\brunStatusLabel\b/.test(presentationImport), '应导入状态中文标签')
  assert.ok(/\brouteLabel\b/.test(presentationImport), '应导入路线中文标签')
  assert.ok(/runStatusLabel\(item\.status\)/.test(view), '任务列表应显示中文状态')
  assert.ok(/routeLabel\(item\.research_route\)/.test(view), '任务列表应显示中文路线')
  assert.ok(/runStatusLabel\(selectedRun\.status\)/.test(view), '当前任务应显示中文状态')
  assert.ok(/routeLabel\(selectedRun\.research_route\)/.test(view), '当前任务应显示中文路线')
})

test('专家反馈表单覆盖原生控件边框，避免数字评分框出现黑色 inset 边', () => {
  const controlRule = liveStyles.match(
    /\.expert-feedback-form input,\s*\.expert-feedback-form select,\s*\.expert-feedback-form textarea\s*\{([^}]*)\}/
  )?.[1] || ''
  assert.match(controlRule, /border\s*:\s*1px\s+solid\s+#d7dfed\s*;/)
  assert.match(controlRule, /background\s*:\s*#fff\s*;/)
  assert.match(controlRule, /font\s*:\s*inherit\s*;/)
})

test('专家反馈显示真实 S5 分数、评分原则并允许提交细则修改建议', () => {
  assert.match(view, /capabilityS5Scorecard\(feedbackTarget\.value/)
  assert.match(view, /v-for="dimension in scoreDimensions"/)
  assert.match(view, /dimension\.principle/)
  assert.match(view, /feedbackRubricSuggestions\[dimension\.key\]/)
  assert.match(view, /rubric_feedback:\s*rubricFeedback/)
  assert.doesNotMatch(view, /mission_effectiveness|technical_feasibility|innovation_value|cost_effectiveness/)
})

test('正式原卡接收同谱系深研版本并保留独立深研卡片区', () => {
  assert.match(view, /:deep-versions="deepVersionsFor\(item\)"/)
  assert.match(view, /id="deep-research-cards"/)
  assert.match(view, /不覆盖正式原卡/)
})

test('能力画像仅按真实权限限制写入，历史来源本身不再强制只读', () => {
  assert.match(view, /const selectedRunReadOnly = computed/)
  assert.match(view, /Boolean\(selectedRun\.value\?\.readonly\)/)
  assert.doesNotMatch(view, /selectedRun\.value\?\.readonly \|\| selectedRun\.value\?\.historical_snapshot/)
  assert.match(view, /历史数据\{\{ selectedRunReadOnly \? '（只读）' : '（可编辑）' \}\}/)
  assert.match(view, /if \(selectedRunReadOnly\.value\) \{[\s\S]*?历史研究任务为只读数据[\s\S]*?return[\s\S]*?\}[\s\S]*?const versionId/)
  assert.match(view, /:read-only="selectedRunReadOnly"/)
  assert.match(view, /:disabled="selectedRunReadOnly \|\| versionBusy/)
})
