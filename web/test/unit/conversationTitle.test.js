import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeConversationTitle } from '../../src/utils/conversationTitle.js'

test('对话标题保留最终标题，清除完整和重复的推理块', () => {
  assert.equal(normalizeConversationTitle('<think>内部推理</think>关联研究材料'), '关联研究材料')
  assert.equal(normalizeConversationTitle('<think>第一段</think><think>第二段</think>关联研究材料'), '关联研究材料')
})

test('供应商仅残留推理结束标记时不把前面的推理存成标题', () => {
  assert.equal(normalizeConversationTitle('功能连通性验收</think>关联成功验证'), '关联成功验证')
})

test('未闭合的推理不作为标题，保留调用方的原始标题回退', () => {
  assert.equal(normalizeConversationTitle('<think>尚未完成的内部推理'), '')
})

test('普通标题保持原意和完整长度，仅合并多余空白', () => {
  assert.equal(normalizeConversationTitle('  应急照明\n维护检查  '), '应急照明 维护检查')
  assert.equal(normalizeConversationTitle('研究'.repeat(30)), '研究'.repeat(30))
})

test('非文本模型响应不写入可见标题', () => {
  assert.equal(normalizeConversationTitle(null), '')
  assert.equal(normalizeConversationTitle({ content: '标题' }), '')
})
