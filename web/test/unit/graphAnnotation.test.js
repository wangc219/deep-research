import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const workbenchSource = await readFile(
  new URL('../../src/components/knowledge/GraphAnnotationWorkbench.vue', import.meta.url),
  'utf8'
)
const sectionSource = await readFile(
  new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
  'utf8'
)
const apiSource = await readFile(new URL('../../src/apis/graph_api.js', import.meta.url), 'utf8')
const draftImportSource = await readFile(
  new URL('../../src/utils/annotationDraftImport.js', import.meta.url),
  'utf8'
)

test('双标工作台展示权威 Block、严格 Span、标准实体和关系条件编辑', () => {
  assert.match(workbenchSource, /PostgreSQL 权威 Block/)
  assert.match(workbenchSource, /Span 使用 \[start, end\)/)
  assert.match(workbenchSource, /canonical_entity_id/)
  assert.match(workbenchSource, /applicable_conditions/)
  assert.match(workbenchSource, /claim_level/)
  assert.match(workbenchSource, /evidence_spans/)
})

test('双份初稿提交前隔离，齐备后显示差异并由第三人提交仲裁终稿', () => {
  assert.match(workbenchSource, /另一名标注员提交前看不到你的初稿/)
  assert.match(workbenchSource, /独立标注差异/)
  assert.match(workbenchSource, /assignment\.both_submitted/)
  assert.match(workbenchSource, /提交专家仲裁终稿/)
  assert.match(workbenchSource, /adjudicateAnnotation/)
})

test('图谱主界面移除双标入口，同时保留历史活动 API 兼容能力', () => {
  assert.doesNotMatch(sectionSource, /GraphAnnotationWorkbench/)
  assert.doesNotMatch(sectionSource, /双标与专家仲裁/)
  assert.match(apiSource, /createAnnotationCampaign/)
  assert.match(apiSource, /getMyAnnotationAssignments/)
  assert.match(apiSource, /submitAnnotation/)
  assert.match(apiSource, /adjudicateAnnotation/)
  assert.match(apiSource, /exportAnnotationCampaign/)
})

test('人工审核入口仍只对可写用户显示', () => {
  assert.match(
    sectionSource,
    /v-if="isMilvus && !readonly"\s+class="action-btn"\s+title="人工审核"/
  )
})

test('双标工作台使用有界高度并让任务栏与编辑区独立滚动', () => {
  assert.match(workbenchSource, /height: min\(72vh, 760px\)/)
  assert.match(workbenchSource, /\.assignment-list \{[\s\S]*?min-height: 0;[\s\S]*?overflow-y: auto;/)
  assert.match(workbenchSource, /\.annotation-main \{[\s\S]*?min-height: 0;[\s\S]*?overflow-y: auto;/)
  assert.match(workbenchSource, /grid-template-rows: minmax\(120px, 180px\) minmax\(0, 1fr\)/)
})

test('AI 候选导入只加载到本人编辑器，不在导入处理函数中提交 revision', () => {
  assert.match(workbenchSource, /导入本人 AI 候选/)
  assert.match(workbenchSource, /AI 候选草稿已加载/)
  assert.match(workbenchSource, /prepareAiDraftForAssignment/)
  assert.match(draftImportSource, /annotation_kind !== 'ai_prelabel'/)
  assert.match(draftImportSource, /formal_gold_eligible !== false/)
  assert.match(draftImportSource, /human_confirmed !== false/)

  const importHandler = workbenchSource.slice(
    workbenchSource.indexOf('const importAiDraftFiles'),
    workbenchSource.indexOf('const hydrateDraft')
  )
  assert.doesNotMatch(importHandler, /submitAnnotation|adjudicateAnnotation/)
})

test('统一提交以一次最终确认覆盖持久草稿，不设置逐篇已核对门槛', () => {
  assert.match(workbenchSource, /统一提交 \{\{ bulkEligibleCount \}\} 篇 revision/)
  assert.match(workbenchSource, /不要求逐篇点击“已核对”/)
  assert.match(workbenchSource, /Modal\.confirm/)
  assert.match(workbenchSource, /bulkSubmitAnnotations/)
  assert.match(apiSource, /confirm_submission: true/)
  assert.doesNotMatch(workbenchSource, /标记本篇已核对/)
})
