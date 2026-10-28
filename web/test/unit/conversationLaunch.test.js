import assert from 'node:assert/strict'
import test from 'node:test'
import {
  readConversationDraft,
  saveConversationDraft,
  shouldSubmitConversation
} from '../../src/utils/conversationLaunch.js'
import {
  latestHumanMessage,
  truncateReplacedMessageBranch
} from '../../src/utils/conversationMessages.js'

test('Enter submits, while IME confirmation, modifiers and held keys keep editing', () => {
  assert.equal(shouldSubmitConversation({ key: 'Enter' }), true)
  for (const event of [
    { key: 'Enter', isComposing: true },
    { key: 'Enter', keyCode: 229 },
    { key: 'Enter', shiftKey: true },
    { key: 'Enter', ctrlKey: true },
    { key: 'Enter', metaKey: true },
    { key: 'Enter', altKey: true },
    { key: 'Enter', repeat: true },
    { key: 'a' }
  ])
    assert.equal(shouldSubmitConversation(event), false)
})

test('drafts round-trip independently by user and context, and clear after sending', () => {
  const values = new Map()
  const storage = {
    getItem: (key) => values.get(key),
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key)
  }
  saveConversationDraft(storage, 'alice:run1', {
    topic: '研究问题\n第二行',
    focus: '补充偏好',
    model_spec: 'do-not-store'
  })
  assert.deepEqual(readConversationDraft(storage, 'alice:run1'), {
    topic: '研究问题\n第二行',
    focus: '补充偏好'
  })
  assert.deepEqual(readConversationDraft(storage, 'bob:run1'), { topic: '', focus: '' })
  assert.deepEqual(readConversationDraft(storage, 'alice:run2'), { topic: '', focus: '' })
  assert.equal(values.get('alice:run1').includes('model_spec'), false)
  saveConversationDraft(storage, 'alice:run1', { topic: '', focus: '' })
  assert.equal(values.has('alice:run1'), false)
})

test('malformed or unavailable browser storage does not break composing', () => {
  for (const storage of [
    null,
    {
      getItem() {
        throw new Error('blocked')
      }
    },
    { getItem: () => 'null' },
    { getItem: () => '{' },
    { getItem: () => '{"topic":[],"focus":42}' }
  ]) {
    assert.deepEqual(readConversationDraft(storage, 'draft'), { topic: '', focus: '' })
    assert.doesNotThrow(() =>
      saveConversationDraft(storage, 'draft', { topic: 'question', focus: '' })
    )
  }
})

test('only the most recent human message can be selected for editing', () => {
  const first = { id: 'human1', type: 'human', content: '原问题' }
  const last = { id: 'human2', type: 'human', content: '最近的问题' }
  const conversations = [
    { messages: [first, { type: 'ai', content: '回答' }] },
    { messages: [last, { type: 'ai' }] },
    { messages: [{ type: 'tool' }] }
  ]
  assert.equal(latestHumanMessage(conversations), last)
  assert.equal(latestHumanMessage([{ messages: [first, last] }]), last)
  assert.equal(latestHumanMessage([]), null)
  assert.equal(latestHumanMessage([{ messages: [{ type: 'ai' }] }]), null)
})

test('accepted edit removes the replaced question and its old reply from local history', () => {
  const messages = [
    { id: 1, type: 'human', content: 'earlier' },
    { id: 2, type: 'ai', content: 'earlier answer' },
    { id: 3, type: 'human', content: 'old question' },
    { id: 4, type: 'ai', content: 'old answer' }
  ]
  assert.deepEqual(truncateReplacedMessageBranch(messages, 3), messages.slice(0, 2))
  assert.equal(truncateReplacedMessageBranch(messages, 99), messages)
})
