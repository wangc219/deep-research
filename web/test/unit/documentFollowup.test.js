import assert from 'node:assert/strict'
import test from 'node:test'
import { createFollowupDraft } from '../../src/views/document-research/followupDraft.js'

test('follow-up retains only user questions and constraints, resetting all outbound choices', () => {
  const task = {
    id: 'parent', status: 'completed', problem: '跨页表头如何识别？', context_questions: ['表格需求'],
    library_ids: ['local-a'], parser_version: 'v1', constraints: 'CPU', expected_result: '结构正确',
    allow_public: true, allow_web_search: true, public_query: 'old search', allow_external_model: true,
    report: { answer: [{ text: 'Never use old model content as evidence' }], sources: [{ text: 'old evidence' }] }
  }
  const draft = createFollowupDraft(task, 'research')
  assert.deepEqual(draft.questions, ['表格需求', '跨页表头如何识别？'])
  assert.deepEqual(draft.library_ids, ['local-a'])
  assert.equal(draft.fields.constraints, 'CPU')
  assert.equal(draft.fields.mode, 'research')
  assert.equal(draft.fields.problem, '')
  for (const flag of ['allow_public', 'allow_web_search', 'allow_external_model']) assert.equal(draft.fields[flag], false)
  assert.equal(draft.fields.public_query, '')
  assert.equal(JSON.stringify(draft).includes('old evidence'), false)
  assert.equal(JSON.stringify(draft).includes('Never use old'), false)
  draft.library_ids.push('new')
  assert.deepEqual(task.library_ids, ['local-a'])
})

test('follow-up display caps recent context consistently by Unicode code points', () => {
  const draft = createFollowupDraft({ id: 'p', status: 'completed', library_ids: [], context_questions: ['discarded', 'two', 'three'], problem: '📃'.repeat(2001) })
  assert.deepEqual(draft.questions.slice(0, 2), ['two', 'three'])
  assert.equal(Array.from(draft.questions[2]).length, 2000)
  assert.equal(draft.truncated, true)
  assert.equal(createFollowupDraft({ id: 'p', status: 'completed', library_ids: [], context_questions: [], problem: 'short', context_truncated: true }).truncated, true)
})

test('unfinished or invalid tasks cannot start a follow-up draft', () => {
  for (const status of ['running', 'failed', 'cancelled', 'needs_input', 'ready']) {
    assert.equal(createFollowupDraft({ id: 'p', status, library_ids: [] }), null)
  }
  assert.equal(createFollowupDraft(null), null)
  assert.equal(createFollowupDraft({ status: 'completed' }), null)
  assert.equal(createFollowupDraft({ id: 'p', status: 'completed' }, 'invalid'), null)
})
