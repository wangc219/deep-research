import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../../src/views/equipment/EquipmentRunsView.vue', import.meta.url), 'utf8')
const createSource = source.slice(source.indexOf('const createRun = '), source.indexOf('\nconst confirmAction = '))
const configuredForm = () => ({
  topic: ' 民用应急照明可靠性研究 ', supplemental_information: ' 限公开资料 ',
  research_route: 'traditional_gap', execution_profile_id: 'legacy_v1',
  interaction_mode: 'autonomous', discovery_branch: 'B', report_template_mode: 'project_argument_v1',
  selected_agent_ids: ['weapon_equipment'], max_rounds: 5, model_spec: 'managed:test',
  source_query_id: 'q-source', source_query_version: 3, start: true
})
function runContext(form) {
  const calls = { created: [], started: [], paths: [] }
  const context = {
    form, creating: { value: false }, configOpen: { value: true },
    selectedRecommendation: { value: { knowledge_enabled: true, knowledge_ids: ['kb-1'] } },
    inheritKnowledgeScope: (value) => value,
    createIdempotencyKey: () => 'test-request',
    equipmentApi: {
      createResearchRun: async (payload) => { calls.created.push(payload); return { run_id: 'draft-1' } },
      startResearchRun: async (id) => { calls.started.push(id) }
    },
    clearSelectedRecommendation: () => {}, load: async () => {},
    message: { success: () => {}, warning: () => {}, error: () => {} },
    router: { push: async (path) => { calls.paths.push(path) } }
  }
  return { createRun: vm.runInNewContext(`${createSource}\ncreateRun`, context), calls }
}

test('研究表单把模板、编排、轮次、Agent、模型与来源一同提交给平台 API', async () => {
  const { createRun, calls } = runContext(configuredForm())
  await createRun()
  const payload = calls.created[0]
  assert.equal(payload.topic, '民用应急照明可靠性研究')
  assert.equal(payload.supplemental_information, '限公开资料')
  for (const key of ['research_route', 'execution_profile_id', 'interaction_mode', 'discovery_branch', 'report_template_mode', 'max_rounds', 'selected_agent_ids']) {
    assert.deepEqual(payload[key], configuredForm()[key], key)
  }
  assert.equal(payload.analyst_confirmed, true)
  assert.equal(payload.execution.model_spec, 'managed:test')
  assert.equal(payload.source_query_id, 'q-source')
  assert.equal(payload.source_query_version, 3)
  assert.deepEqual(payload.knowledge_ids, ['kb-1'])
  assert.deepEqual(calls.started, ['draft-1'])
})

test('保存草稿保留所有运行配置，即使立即排队已勾选也不启动研究', async () => {
  const { createRun, calls } = runContext(configuredForm())
  await createRun({ startImmediately: false })
  assert.equal(calls.created[0].max_rounds, 5)
  assert.equal(calls.created[0].report_template_mode, 'project_argument_v1')
  assert.equal(calls.created[0].analyst_confirmed, false)
  assert.deepEqual(calls.started, [])
  assert.deepEqual(calls.paths, ['/equipment/runs/draft-1'])
})
