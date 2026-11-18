import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentSource = await readFile(
  new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
  'utf8'
)
const apiSource = await readFile(new URL('../../src/apis/graph_api.js', import.meta.url), 'utf8')
const knowledgeApiSource = await readFile(
  new URL('../../src/apis/knowledge_api.js', import.meta.url),
  'utf8'
)

test('Pilot 验收卡展示权威规模、质量与失败项，不在前端重算结论', () => {
  assert.match(componentSource, /本地 Pilot 验收/)
  assert.match(componentSource, /source_documents/)
  assert.match(componentSource, /accepted_entities/)
  assert.match(componentSource, /accepted_relations/)
  assert.match(componentSource, /requirements\?\.source_documents/)
  assert.doesNotMatch(componentSource, /source_documents \?\? 0\}\/2000/)
  assert.match(componentSource, /entity_f1/)
  assert.match(componentSource, /relation_f1/)
  assert.match(componentSource, /结论由后端权威报告判定/)
  assert.match(componentSource, /acceptanceStatus\?\.passed/)
})

test('图谱 API 暴露验收状态与评测报告登记契约', () => {
  assert.match(apiSource, /getAcceptanceStatus/)
  assert.match(apiSource, /acceptance\/status/)
  assert.match(apiSource, /recordEvaluation/)
  assert.match(apiSource, /acceptance\/evaluations/)
})

test('投影重建只使用 PostgreSQL 权威重建端点，不从界面调用删除权威数据的 reset', () => {
  assert.match(knowledgeApiSource, /rebuildProjections/)
  assert.match(knowledgeApiSource, /rebuild-projections/)
  assert.match(componentSource, /从 PostgreSQL 重建图投影/)
  assert.match(componentSource, /不删除 PostgreSQL 中的实体、关系、证据、审核决定和历史版本/)
  assert.doesNotMatch(componentSource, /graphBuildApi\.reset/)
})
