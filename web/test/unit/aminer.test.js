import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  createAMinerDraft,
  buildAMinerConfigPatch,
  parseAcademicResult,
  academicSourceUrl
} from '../../src/utils/aminer.js'

test('AMiner 密钥不进入表单初值，留空保留，元预算转为整数分', () => {
  const draft = createAMinerDraft({ value: { api_key: 'masked', chat_budget_cents: 0 } })
  assert.equal(draft.enabled, false)
  assert.equal(draft.api_key, '')
  assert.equal(draft.chat_budget_yuan, 0)
  const patch = buildAMinerConfigPatch({ ...draft, deep_budget_yuan: 0.29 })
  assert.equal(patch.deep_budget_cents, 29)
  assert.ok(!('api_key' in patch))
  assert.equal(
    buildAMinerConfigPatch({ ...draft, api_key: ' replacement ' }).api_key,
    'replacement'
  )
})

test('论文结果支持结构化或文本块，故障保留提示并拒绝非法链接', () => {
  const result = { status: 'partial', message: '预算已用尽', results: [{ id: 'p' }] }
  assert.deepEqual(parseAcademicResult([{ type: 'text', text: JSON.stringify(result) }]), result)
  assert.equal(parseAcademicResult('not JSON').status, 'unavailable')
  assert.equal(academicSourceUrl('javascript:alert(1)'), '')
  assert.equal(academicSourceUrl('https://doi.org/10.1/p'), 'https://doi.org/10.1/p')
})
