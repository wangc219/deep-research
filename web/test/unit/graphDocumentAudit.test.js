import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sectionSource = await readFile(
  new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
  'utf8'
)
const workbenchSource = await readFile(
  new URL('../../src/components/knowledge/DocumentKnowledgeCardWorkbench.vue', import.meta.url),
  'utf8'
)
const apiSource = await readFile(new URL('../../src/apis/graph_api.js', import.meta.url), 'utf8')

test('图谱配置默认启用保守文档分流并可显式关闭过滤', () => {
  assert.match(sectionSource, /document_audit_enabled: true/)
  assert.match(sectionSource, /filter_non_research: true/)
  assert.match(sectionSource, /document_audit:/)
  assert.match(sectionSource, /只排除强证据命中的非研究或正文不足材料/)
})

test('文档知识审计工作台展示推断边界、研究链和可回切 Span 原文', () => {
  assert.match(sectionSource, /DocumentKnowledgeCardWorkbench/)
  assert.match(workbenchSource, /待审核关系和推断不会被展示成已确认事实/)
  assert.match(workbenchSource, /研究主线 \/ 辅线/)
  assert.match(workbenchSource, /evidence_refs/)
  assert.match(workbenchSource, /evidence\.text/)
  assert.match(workbenchSource, /evidence\.rebuildable/)
  assert.match(workbenchSource, /evidence\.supports/)
  assert.match(workbenchSource, /support\.evidence_use_label/)
  assert.match(workbenchSource, /support\.review_status/)
  assert.match(workbenchSource, /support\.extraction_method/)
  assert.match(workbenchSource, /military_value_level/)
  assert.match(workbenchSource, /military_value_review_required/)
  assert.match(workbenchSource, /military_value_reason/)
  assert.match(workbenchSource, /需专家复核/)
  assert.match(workbenchSource, /focused_reextraction_recommended/)
  assert.match(workbenchSource, /轻量化 RAG 技术价值/)
  assert.match(workbenchSource, /高价值重点复抽/)
  assert.match(workbenchSource, /value_routing\.dimensions/)
  assert.match(workbenchSource, /只调整复抽预算，不作为事实、人工 Gold 或正式验收结论/)
  assert.match(workbenchSource, /仅看高价值重点复抽/)
  assert.match(workbenchSource, /知识形成与审核流程/)
  assert.match(workbenchSource, /价值分流/)
  assert.match(workbenchSource, /模型抽取/)
  assert.match(workbenchSource, /人工复核/)
  assert.match(workbenchSource, /evidenceVisibleLimit/)
  assert.match(workbenchSource, /再显示/)
  assert.match(workbenchSource, /\[\{\{\s+evidence\.start\s+\}\},\s+\{\{\s+evidence\.end\s+\}\}\)/)
  assert.match(workbenchSource, /Inference/)
  assert.match(workbenchSource, /key_metrics/)
  assert.match(workbenchSource, /transfer_potential/)
  assert.match(workbenchSource, /graph_rag_hints/)
  assert.match(workbenchSource, /narrative_report/)
  assert.match(workbenchSource, /创新边仅为待审核候选，不进入默认事实查询/)
})

test('主图为空但存在候选知识时引导用户进入审计和审核，而不是误报没有结果', () => {
  assert.match(sectionSource, /hasReviewableKnowledge/)
  assert.match(sectionSource, /候选知识等待审核/)
  assert.match(sectionSource, /默认主图只展示已接受知识/)
  assert.match(sectionSource, /查看知识审计/)
  assert.match(sectionSource, /审核候选知识/)
})

test('轻量化 RAG 创新工作台突出多跳检索和双向创新发现且保留证据边界', () => {
  assert.match(sectionSource, /轻量化 RAG 多跳检索与创新预测/)
  assert.match(sectionSource, /LIGHTWEIGHT GRAPH DISCOVERY/)
  assert.match(sectionSource, /自上而下 · 需求牵引/)
  assert.match(sectionSource, /自下而上 · 技术涌现/)
  assert.match(sectionSource, /检索并生成结论/)
  assert.match(sectionSource, /证据约束创新预测/)
  assert.match(sectionSource, /模型增强与证据约束/)
  assert.match(sectionSource, /只解释当前图谱与原文证据/)
  assert.match(sectionSource, /不自动写入知识事实/)
})

test('图谱 API 提供知识卡列表和详情端点', () => {
  assert.match(apiSource, /getDocumentCards/)
  assert.match(apiSource, /getDocumentCard/)
  assert.match(apiSource, /document-cards/)
})
