import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DRAFT_THREAD_ID,
  createThreadDraftStore,
  createThreadDraftSession,
  shouldDiscardPersistedThreadDraft
} from '../../src/utils/thread_draft.js'

// 构造可注入的内存存储，模拟 localStorage 行为
const createMemoryStorage = () => {
  const storage = new Map()
  return {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
    _raw: storage
  }
}

test('切换线程时保存旧线程草稿并还原新线程草稿', () => {
  const store = createThreadDraftStore(createMemoryStorage())
  const session = createThreadDraftSession(store)

  // 在线程 A 输入后切换到线程 B：B 不显示 A 的草稿
  session.switchThread('thread-a', '')
  session.saveInput('A 的未发送文本')
  const restoredInB = session.switchThread('thread-b', 'A 的未发送文本')
  assert.equal(restoredInB, '')

  // 切回 A：A 的未发送文本完整恢复
  const restoredInA = session.switchThread('thread-a', '')
  assert.equal(restoredInA, 'A 的未发送文本')
})

test('新建对话草稿独立，不继承已有对话文本', () => {
  const store = createThreadDraftStore(createMemoryStorage())
  const session = createThreadDraftSession(store)

  session.switchThread('thread-a', '')
  session.saveInput('A 的未发送文本')

  // 新建对话（无线程 ID）使用独立草稿
  const draftRestored = session.switchThread('', 'A 的未发送文本')
  assert.equal(draftRestored, '')
  assert.equal(store.read(DRAFT_THREAD_ID), '')
})

test('草稿发送创建线程后清理新建对话草稿，仅清空当前对话', () => {
  const store = createThreadDraftStore(createMemoryStorage())
  const session = createThreadDraftSession(store)

  // 新建对话中输入待发送文本
  session.saveInput('待发送文本')
  // 发送后输入清空，草稿随输入清除
  session.saveInput('')
  assert.equal(store.read(DRAFT_THREAD_ID), '')

  // 场景二：切换发生在输入清空之前（发送流程内部先创建线程）
  const session2 = createThreadDraftSession(store)
  session2.saveInput('又一次待发送文本')
  session2.switchThread('thread-new', '又一次待发送文本')
  session2.clearDraftThread()
  session2.saveInput('')
  assert.equal(store.read(DRAFT_THREAD_ID), '')
  assert.equal(store.read('thread-new'), '')
})

test('发送清空输入时仅清空当前线程草稿，其他线程不受影响', () => {
  const store = createThreadDraftStore(createMemoryStorage())
  const session = createThreadDraftSession(store)

  session.switchThread('thread-a', '')
  session.saveInput('A 的草稿')
  session.switchThread('thread-b', 'A 的草稿')
  session.saveInput('B 的草稿')

  // 在线程 B 发送：仅 B 的草稿被清空
  session.saveInput('')
  assert.equal(store.read('thread-b'), '')
  assert.equal(store.read('thread-a'), 'A 的草稿')
})

test('异常切换回退后草稿不互相污染', () => {
  const store = createThreadDraftStore(createMemoryStorage())
  const session = createThreadDraftSession(store)

  session.switchThread('thread-a', '')
  session.saveInput('A 的草稿')

  // 切换到 B 后立即回退到 A（模拟 selectChat 失败恢复）
  session.switchThread('thread-b', 'A 的草稿')
  const restored = session.switchThread('thread-a', '')
  assert.equal(restored, 'A 的草稿')
  assert.equal(store.read('thread-b'), '')
})

test('删除当前线程后输入草稿被丢弃，不残留孤儿缓存', () => {
  const storage = createMemoryStorage()
  const store = createThreadDraftStore(storage)
  const session = createThreadDraftSession(store)

  session.switchThread('thread-a', '')
  session.saveInput('A 的草稿')
  assert.equal(store.read('thread-a'), 'A 的草稿')

  // 线程删除后切走：调用方传入空文本，旧线程草稿应被清除
  session.switchThread('', '')
  assert.equal(store.read('thread-a'), '')
})

test('空草稿写入时清除缓存，避免无效条目累积', () => {
  const storage = createMemoryStorage()
  const store = createThreadDraftStore(storage)

  store.write('thread-a', '文本')
  assert.equal(storage._raw.size, 1)
  store.write('thread-a', '')
  assert.equal(storage._raw.size, 0)
})

test('不同模块即使使用同一线程或新建态，也保持草稿完全隔离', () => {
  const storage = createMemoryStorage()
  const generalStore = createThreadDraftStore(storage, 'agent-chat')
  const equipmentStore = createThreadDraftStore(storage, 'equipment-deep')

  generalStore.write(DRAFT_THREAD_ID, '智能对话草稿')
  equipmentStore.write(DRAFT_THREAD_ID, '技术攻关预填')
  generalStore.write('thread-shared', '智能对话线程草稿')
  equipmentStore.write('thread-shared', '装备深研线程草稿')

  assert.equal(generalStore.read(DRAFT_THREAD_ID), '智能对话草稿')
  assert.equal(equipmentStore.read(DRAFT_THREAD_ID), '技术攻关预填')
  assert.equal(generalStore.read('thread-shared'), '智能对话线程草稿')
  assert.equal(equipmentStore.read('thread-shared'), '装备深研线程草稿')
  assert.equal(storage._raw.size, 4)
})

test('localStorage 不可用时草稿功能静默降级不抛错', () => {
  const brokenStorage = {
    getItem: () => {
      throw new Error('unavailable')
    },
    setItem: () => {
      throw new Error('unavailable')
    },
    removeItem: () => {
      throw new Error('unavailable')
    }
  }
  const store = createThreadDraftStore(brokenStorage)
  const session = createThreadDraftSession(store)

  assert.equal(store.read('thread-a'), '')
  assert.doesNotThrow(() => store.write('thread-a', '文本'))
  assert.doesNotThrow(() => store.remove('thread-a'))
  assert.doesNotThrow(() => {
    session.switchThread('thread-a', '文本')
    session.saveInput('文本')
    session.clearDraftThread()
    session.clearCurrentThread()
  })
})

test('恢复草稿与已持久化用户消息一致时判定为已发送残留', () => {
  assert.equal(
    shouldDiscardPersistedThreadDraft('远程精打武器的末段识别如何优化？', [
      { type: 'human', content: '远程精打武器的末段识别如何优化？' }
    ]),
    true
  )
})

test('恢复草稿与用户消息仅有空白和换行差异时仍判定为已发送残留', () => {
  assert.equal(
    shouldDiscardPersistedThreadDraft('杀伤链重构\n  与任务接续', [
      { role: 'user', content: '  杀伤链重构 与任务接续  ' }
    ]),
    true
  )
})

test('支持 OpenAI 和 LangChain 风格的用户消息内容块', () => {
  assert.equal(
    shouldDiscardPersistedThreadDraft('末段自主识别 分级决策', [
      {
        role: 'human',
        content: [{ text: '末段自主识别' }, { content: '分级决策' }]
      }
    ]),
    true
  )
})

test('未发送草稿与历史用户消息不同时继续保留', () => {
  assert.equal(
    shouldDiscardPersistedThreadDraft('这是新的追问草稿', [
      { type: 'human', content: '这是已经发送的问题' }
    ]),
    false
  )
})

test('助手消息即使与草稿相同也不能触发清理', () => {
  assert.equal(
    shouldDiscardPersistedThreadDraft('需要继续验证的设想', [
      { type: 'ai', role: 'assistant', content: '需要继续验证的设想' }
    ]),
    false
  )
})

test('清理当前线程不会影响其他线程草稿', () => {
  const store = createThreadDraftStore(createMemoryStorage())
  const session = createThreadDraftSession(store)

  session.switchThread('thread-a', '')
  session.saveInput('A 已发送残留')
  store.write('thread-b', 'B 未发送草稿')
  session.clearCurrentThread()

  assert.equal(store.read('thread-a'), '')
  assert.equal(store.read('thread-b'), 'B 未发送草稿')
})
