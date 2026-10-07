import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const readSource = (relativePath) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

const reportCards = readSource('../../src/views/equipment/EquipmentReportCapabilityCards.vue')
const portraitCard = readSource('../../src/components/equipment/CapabilityPortraitCard.vue')
const reportsView = readSource('../../src/views/equipment/EquipmentReportsView.vue')
const capabilitiesView = readSource('../../src/views/equipment/EquipmentCapabilitiesView.vue')
const embedStyles = readSource('../../src/assets/css/equipment-embed.css')

test('报告提前态复用统一能力画像卡，而不是维护第二套卡片结构', () => {
  assert.match(reportCards, /import CapabilityPortraitCard from/)
  assert.match(reportCards, /<CapabilityPortraitCard[\s\S]*surface="report"/)
  assert.doesNotMatch(reportCards, /class="capability-sheet"/)
})

test('统一能力画像卡的报告模式保留深研和完整画像入口并隐藏页内写操作', () => {
  assert.match(portraitCard, /default: 'capabilities'/)
  assert.match(portraitCard, /\['capabilities', 'report'\]/)
  assert.match(portraitCard, /v-if="reportSurface"[\s\S]*查看完整画像/)
  assert.match(portraitCard, /v-if="!reportSurface"[\s\S]*针对本卡反馈/)
  assert.match(portraitCard, /!reportSurface && deepResearch && item\.version_id/)
  assert.match(reportCards, /publishDeepLaunchCard\(\{/)
  assert.match(reportCards, /sections: capabilityPortraitModules\(item\)/)
  assert.match(portraitCard, /深挖本栏/)
  assert.match(reportCards, /section_label: section\?\.label/)
})

test('报告页暗色规则使用稳定的全局祖先选择器', () => {
  assert.doesNotMatch(reportsView, /:global\(\.dark\)/)
  assert.match(reportsView, /\.dark \.reports-page \.report-document \.report-markdown/)
})

test('报告页和能力画像页的阶段导航固定在实际滚动容器顶部', () => {
  for (const source of [reportsView, capabilitiesView]) {
    const rule = source.match(/\.workspace-stage-nav\s*\{([^}]*)\}/)?.[1] || ''
    assert.match(rule, /position\s*:\s*sticky\s*;/)
    assert.match(rule, /top\s*:\s*0\s*;/)
    assert.match(rule, /z-index\s*:\s*40\s*;/)
    assert.match(rule, /align-self\s*:\s*start\s*;/)
  }

  const embeddedRule = embedStyles.match(
    /\.equipment-workbench-host \.workspace-stage-nav\s*\{([^}]*)\}/
  )?.[1] || ''
  assert.match(embeddedRule, /top\s*:\s*0\s*;/)
  assert.doesNotMatch(reportsView, /\.workspace-stage-nav\s*\{[^}]*top\s*:\s*56px/)
})

test('报告正文投影不会把正式 S6 基线误当作待核验深研补充', () => {
  assert.match(reportsView, /capabilityVersionMeta\(item\)\.formalBaseline/)
  assert.match(reportsView, /confidence_limited:\s*false/)
  assert.match(reportsView, /normalizeReportDocument\(reportBody\.value, selectedRun\.value, reportCapabilities\.value\)/)
})
