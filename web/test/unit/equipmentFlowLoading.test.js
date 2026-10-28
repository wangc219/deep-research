import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const readView = (name) => readFileSync(new URL(`../../src/views/equipment/${name}.vue`, import.meta.url), 'utf8')
const ref = (value) => ({ value })
const deferred = () => {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

/** 执行页面实际加载函数，控制网络与流式完成时机。 */
function loadFunction(source, name, nextName, context) {
  const body = source.slice(source.indexOf(`const ${name} = `), source.indexOf(`\nconst ${nextName} = `))
  return vm.runInNewContext(`${body}\n${name}`, context)
}

test('新建深研的首轮仍在流式回复时，线程就绪即解除切换遮罩', async () => {
  const sending = deferred()
  const started = deferred()
  const context = {
    sessionRequestSequence: ref(0), sessionId: ref('new-session'), session: ref(null),
    researchMode: ref('section_deepen'), activeResearchSection: ref(''),
    pendingSessionId: ref(''), sessionSwitching: ref(false), sessionSwitchError: ref(''),
    contextOpen: ref(false), requestedSection: ref(''), prefilledSectionKey: ref(''),
    pendingInitialQuestion: ref({ sessionId: 'new-session', text: '民用终端维护' }),
    usesNativeAgent: ref(true),
    equipmentApi: { getDeepSession: async () => ({ session_id: 'new-session', payload: {} }) },
    syncNativeThread: async () => {}, resolveResearchMode: () => 'section_deepen',
    nativeChat: ref({ submitPrompt: (text) => { started.resolve(text); return sending.promise } })
  }
  const load = loadFunction(readView('EquipmentDeepThinkingView'), 'loadSession', 'LEGACY_TERMINAL_STATUSES', context)
  const loading = load()
  assert.equal(await started.promise, '民用终端维护')
  assert.equal(context.session.value.session_id, 'new-session')
  assert.equal(context.sessionSwitching.value, false)
  assert.equal(context.pendingSessionId.value, '')
  assert.equal(context.pendingInitialQuestion.value, null)
  sending.resolve()
  await loading
})

test('旧线程的慢响应不能解除新线程正在加载的状态或发送旧问题', async () => {
  const response = deferred()
  const context = {
    sessionRequestSequence: ref(0), sessionId: ref('old'), session: ref(null),
    researchMode: ref('section_deepen'), activeResearchSection: ref(''),
    pendingSessionId: ref(''), sessionSwitching: ref(false), sessionSwitchError: ref(''),
    equipmentApi: { getDeepSession: () => response.promise }
  }
  const load = loadFunction(readView('EquipmentDeepThinkingView'), 'loadSession', 'LEGACY_TERMINAL_STATUSES', context)
  const loading = load()
  context.sessionId.value = 'new'
  context.sessionRequestSequence.value += 1
  context.pendingSessionId.value = 'new'
  response.resolve({ session_id: 'old' })
  await loading
  assert.equal(context.session.value, null)
  assert.equal(context.sessionSwitching.value, true)
  assert.equal(context.pendingSessionId.value, 'new')
})

test('Query 切换筛选清除不匹配的旧详情；普通刷新保留主动打开的生成结果', async () => {
  const context = {
    loadToken: 0, loading: ref(false), search: ref('新查询'), status: ref('draft'),
    sourceType: ref('all'), page: ref(1), pageSize: ref(20), total: ref(0), queries: ref([]),
    selectedId: ref('old'), selectedIds: ref(['old']), detailOpen: ref(true),
    generationQueryRows: ref([{ query_id: 'old' }]), error: ref(''),
    equipmentApi: { listQueries: async () => ({ items: [{ query_id: 'new' }], total: 1 }) },
    normalizePagedResult: (payload) => payload
  }
  const load = loadFunction(readView('EquipmentQueriesView'), 'loadQueries', 'loadGenerations', context)
  await load()
  assert.equal(context.selectedId.value, 'old')
  assert.equal(context.detailOpen.value, true)
  await load({ preserveSelection: false })
  assert.equal(context.selectedId.value, 'new')
  assert.equal(context.selectedIds.value.length, 0)
  assert.equal(context.detailOpen.value, false)
  context.equipmentApi.listQueries = async () => ({ items: [], total: 0 })
  await load({ preserveSelection: false })
  assert.equal(context.selectedId.value, '')
})
