import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  buildDivergenceExamplePatch,
  buildResearchRunPayload,
  createKnowledgeScope,
  indexQueriesById,
  inheritKnowledgeScope,
  normalizePagedResult,
  parseReferenceUrls,
  queryLineageModelSpec,
  queryMatchesFilters,
  selectLeastUsedDiscoveryAngle,
  toggleKnowledgeSelection,
  validateReferenceUrls
} from '../../src/utils/equipmentQueries.js'

test('normalizes paged query payloads without losing server totals', () => {
  assert.deepEqual(normalizePagedResult({ items: [{ query_id: 'q1' }], total: 31, limit: 10, offset: 20 }), {
    items: [{ query_id: 'q1' }], total: 31, limit: 10, offset: 20
  })
  assert.equal(normalizePagedResult([{ query_id: 'legacy' }]).total, 1)
})

test('indexes generation results across pages and lets the current page refresh stale rows', () => {
  const historyRow = { query_id: 'q-history', query: '历史结果', version: 1 }
  const staleRow = { query_id: 'q-current', query: '旧标题', version: 1 }
  const currentRow = { query_id: 'q-current', query: '新标题', version: 2 }
  const index = indexQueriesById([historyRow, staleRow], [currentRow])
  assert.equal(index.get('q-history'), historyRow)
  assert.equal(index.get('q-current'), currentRow)
})

test('example templates fill the mother topic and all three divergence dimensions', () => {
  assert.deepEqual(buildDivergenceExamplePatch({
    topic: ' 母题 ',
    angle: ' 角度 ',
    demand: ' 需求 ',
    technology: ' 技术 '
  }), {
    topic: '母题',
    expected_angle: '角度',
    demand_dimension: '需求',
    technology_dimension: '技术'
  })
})

test('autonomous discovery rotates toward the least-used and least-recent angle', () => {
  const angles = ['东海', '南海', '边境']
  assert.equal(selectLeastUsedDiscoveryAngle(angles, [{ topic: '东海态势' }]), '南海')
  assert.equal(selectLeastUsedDiscoveryAngle(angles, [
    { topic: '南海态势' },
    { topic: '东海态势' },
    { topic: '边境态势' }
  ]), '边境')
})

test('knowledge scope keeps all, none, and explicit selection distinct', () => {
  assert.deepEqual(createKnowledgeScope(true, []), { knowledge_enabled: true, knowledge_ids: null })
  assert.deepEqual(createKnowledgeScope(false, ['kb-1']), { knowledge_enabled: false, knowledge_ids: [] })
  assert.deepEqual(inheritKnowledgeScope({ knowledge_enabled: true, knowledge_ids: [' kb-1 ', 'kb-1'] }), {
    knowledge_enabled: true,
    knowledge_ids: ['kb-1']
  })
})

test('knowledge selection toggles cleanly and enforces the 64-library limit', () => {
  assert.deepEqual(toggleKnowledgeSelection([' kb-1 ', 'kb-1'], 'kb-2'), ['kb-1', 'kb-2'])
  assert.deepEqual(toggleKnowledgeSelection(['kb-1', 'kb-2'], 'kb-1'), ['kb-2'])
  const fullSelection = Array.from({ length: 64 }, (_, index) => `kb-${index}`)
  assert.deepEqual(toggleKnowledgeSelection(fullSelection, 'kb-overflow'), fullSelection)
})

test('reference URLs are deduplicated and reject unsafe schemes or credentials', () => {
  assert.deepEqual(parseReferenceUrls('https://a.example/x\nhttps://a.example/x https://b.example/y'), [
    'https://a.example/x',
    'https://b.example/y'
  ])
  assert.equal(validateReferenceUrls(['https://a.example/x']), '')
  assert.match(validateReferenceUrls(['http://a.example/x']), /格式不正确/)
  assert.match(validateReferenceUrls(['https://user:secret@a.example/x']), /格式不正确/)
})

test('research payload preserves Query lineage, knowledge scope, and selected model', () => {
  const payload = buildResearchRunPayload({
    query_id: 'q1',
    version: 3,
    query: '  低空无人体系研究  ',
    supplemental_information: ' 场景 ',
    knowledge_enabled: false,
    knowledge_ids: ['ignored']
  }, 'openai/gpt-test')
  assert.equal(payload.topic, '低空无人体系研究')
  assert.equal(payload.source_query_id, 'q1')
  assert.equal(payload.source_query_version, 3)
  assert.deepEqual(payload.knowledge_ids, [])
  assert.deepEqual(payload.execution, { model_spec: 'openai/gpt-test' })
})

test('研究任务 API 将 Query 的知识范围与来源版本写入后端契约', async () => {
  const source = await readFile(new URL('../../src/apis/equipment_api.js', import.meta.url), 'utf8')
  assert.match(source, /knowledge_enabled: \(payload\?\.knowledge_enabled \?\? execution\.knowledge_enabled\) !== false/)
  assert.match(source, /knowledge_ids: payload\?\.knowledge_ids !== undefined \? payload\.knowledge_ids/)
  assert.match(source, /query_library: sourceQueryId \? \{ query_id: sourceQueryId, version: sourceQueryVersion \}/)
})

test('Query 生成模型常驻主操作栏并使用统一模型字段', async () => {
  const source = await readFile(new URL('../../src/views/equipment/EquipmentQueriesView.vue', import.meta.url), 'utf8')
  const footerStart = source.indexOf('<div class="query-generator-footer">')
  const footerEnd = source.indexOf('</div>', source.indexOf('class="query-generate-button"', footerStart))
  const footerSource = source.slice(footerStart, footerEnd)

  assert.match(footerSource, /class="query-model-picker"/)
  assert.match(footerSource, /<ModelSelectorComponent\s+upward/)
  assert.match(footerSource, /:model_spec="generationForm\.model_spec"/)
  assert.match(footerSource, /size="nano"/)
  assert.match(footerSource, /hasDefaultModel \? '系统默认模型' : '选择生成模型'/)
  assert.match(source, /model_spec: generationForm\.model_spec\.trim\(\) \|\| undefined/)
  assert.doesNotMatch(source, /model_config: \{ model_spec: generationForm\.model_spec/)
})

test('Query 生成数量与后端最多 12 条的契约一致', async () => {
  const source = await readFile(new URL('../../src/views/equipment/EquipmentQueriesView.vue', import.meta.url), 'utf8')
  assert.match(source, /v-for="count in \[4, 6, 8, 12\]"/)
  assert.doesNotMatch(source, /v-for="count in \[[^\]]*(?:16|20)/)
})

test('Query 全生命周期只使用统一装备平台 API', async () => {
  const source = await readFile(new URL('../../src/apis/equipment_api.js', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /\/api\/v1\/query-library/)
  assert.match(source, /\/api\/equipment\/queries/)
  assert.match(source, /\/api\/equipment\/query-generations/)
})

test('Query 创建与生成显式绑定当前平台项目', async () => {
  const source = await readFile(new URL('../../src/views/equipment/EquipmentQueriesView.vue', import.meta.url), 'utf8')
  assert.match(source, /equipmentApi\.generateQueries\(\{\s*project_id: runProjectId\.value,/)
  assert.match(source, /equipmentApi\.createQuery\(\{\s*project_id: runProjectId\.value,/)
})

test('generated Query inherits its generation model and filters are deterministic', () => {
  const query = { query_id: 'q1', generation_id: 'g1', status: 'draft', source_type: 'agent', query: '低空蜂群' }
  assert.equal(queryLineageModelSpec(query, [{ generation_id: 'g1', model_config: { model_spec: 'model-x' } }], 'fallback'), 'model-x')
  assert.equal(queryMatchesFilters(query, { search: '蜂群', status: 'draft', sourceType: 'agent' }), true)
  assert.equal(queryMatchesFilters(query, { search: '海上', status: 'draft', sourceType: 'agent' }), false)
})
