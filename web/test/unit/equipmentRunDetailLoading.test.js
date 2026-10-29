import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, KeepAlive, nextTick, ref, ssrContextKey } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createServer } from 'vite'

let server, View, api, polling
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  server = await createServer({ server: { middlewareMode: true, hmr: false } })
  ;({ default: View } = await server.ssrLoadModule('/src/views/equipment/EquipmentRunDetailView.vue'))
  ;({ equipmentApi: api } = await server.ssrLoadModule('/src/apis/equipment_api.js'))
  ;({ sharedPolling: polling } = await server.ssrLoadModule('/src/utils/sharedPolling.js'))
  globalThis.document = { visibilityState: 'visible' }
})
after(async () => {
  await server?.close()
  delete globalThis.localStorage
  delete globalThis.document
})
const settle = async () => { await nextTick(); await new Promise((resolve) => setImmediate(resolve)) }
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const projection = (id = 'run-1') => ({
  run_id: id,
  events: [{ event_id: `${id}-done`, sequence: 2480, event_type: 'report_completed', summary: '报告已完成' }],
  counts: { events: 2480 },
  workflow: { step_plan: [], loops: {} }
})
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
async function mount(t, implementations = {}, tab = 'interactions') {
  const calls = []
  for (const name of ['getRun', 'getRunInteractions', 'listEvents', 'listRunEvidence', 'getRunWinningMechanism']) {
    t.mock.method(api, name, (...args) => {
      calls.push({ name, args })
      if (implementations[name]) return implementations[name](...args)
      if (name === 'getRun') return Promise.resolve({ run_id: args[0], status: 'completed', topic: args[0] })
      if (name === 'getRunInteractions') return Promise.resolve(projection(args[0]))
      return Promise.resolve([])
    })
  }
  let callback
  t.mock.method(polling, 'subscribe', (fn) => { callback = fn; return () => {} })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/runs/:runId', component: {} }] })
  await router.push(`/runs/run-1?tab=${tab}`)
  await router.isReady()
  let instance
  const active = ref(true)
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(() => h(KeepAlive, null, { default: () => active.value ? h(Component) : null }))
  app.provide(ssrContextKey, { modules: new Set() })
  app.use(router)
  app.mount({})
  t.after(() => app.unmount())
  return { calls, router, active, state: () => instance.setupState, poll: () => callback() }
}

test('2480 条历史事件使用摘要直达，双生命周期和慢请求轮询合并为一组读取', async (t) => {
  const interaction = deferred()
  const page = await mount(t, { getRunInteractions: () => interaction.promise })
  await settle()
  assert.equal(page.state().run.run_id, 'run-1')
  assert.equal(page.state().loading, false)
  assert.equal(page.state().interactionsLoading, true)
  const tick = page.poll()
  await settle()
  assert.deepEqual(page.calls.map(x => x.name), ['getRun', 'getRunInteractions'])
  interaction.resolve(projection())
  await tick
  await settle()
  assert.equal(page.state().artifactCounts.events, 2480)
  assert.equal(page.state().interactionsLoading, false)
  await page.poll()
  assert.equal(page.calls.length, 2, '已完成任务不再轮询')
})

test('证据和 S1–S6 独立按需加载，切换标签不等待其他慢产物', async (t) => {
  const winning = deferred()
  const page = await mount(t, { getRunWinningMechanism: () => winning.promise })
  await settle()
  assert.equal(page.calls.length, 2)
  await page.router.push('/runs/run-1?tab=winning')
  await settle()
  assert.equal(page.state().activeArtifactLoading, true)
  await page.router.push('/runs/run-1?tab=evidence')
  await settle()
  assert.equal(page.state().activeArtifactLoading, false)
  assert.deepEqual(page.state().legacyEvidence, [])
  assert.equal(page.calls.filter(x => x.name === 'listRunEvidence').length, 1)
  await page.router.push('/runs/run-1?tab=interactions')
  await settle()
  assert.equal(page.state().activeArtifactLoading, false)
  winning.resolve({ reasoning_nodes: [] })
  await settle()
})

test('完整事件单次读取且重复点击合并，不再执行公网逐页回放', async (t) => {
  const rows = Array.from({ length: 2480 }, (_, i) => ({ event_id: `event-${i}`, sequence: i + 1, event_type: 'tool_result' }))
  const page = await mount(t, { getRunInteractions: (id, compact) => Promise.resolve(compact ? projection(id) : { ...projection(id), events: rows }) })
  await settle()
  await Promise.all([page.state().loadCompleteEvents(), page.state().loadCompleteEvents()])
  assert.deepEqual(page.calls.filter(x => x.name === 'getRunInteractions').map(x => x.args[1]), [true, false])
  assert.equal(page.calls.filter(x => x.name === 'listEvents').length, 0)
  assert.equal(page.state().legacyInteractions.events.length, 2480)
  assert.equal(page.state().completeEventsLoaded, true)
})

test('切换任务和停用页面取消读取，迟到产物不覆盖新任务', async (t) => {
  const old = deferred()
  const page = await mount(t, { getRunInteractions: id => id === 'run-1' ? old.promise : Promise.resolve(projection(id)) })
  await settle()
  const oldSignal = page.calls.find(x => x.name === 'getRunInteractions').args[2].signal
  await page.router.push('/runs/run-2?tab=interactions')
  await settle()
  assert.equal(oldSignal.aborted, true)
  old.resolve(projection('run-1'))
  await settle()
  assert.equal(page.state().legacyInteractions.run_id, 'run-2')
  assert.equal(page.state().run.run_id, 'run-2')
  const currentSignal = page.calls.filter(x => x.name === 'getRunInteractions').at(-1).args[2].signal
  page.active.value = false
  await settle()
  assert.equal(currentSignal.aborted, true)
})

test('产物失败保留错误与重试入口，摘要恢复路径仍可读取权威事件', async (t) => {
  let attempts = 0
  const page = await mount(t, {
    getRunInteractions: () => Promise.reject(new Error('摘要暂不可读')),
    listRunEvidence: () => ++attempts === 1 ? Promise.reject(new Error('暂时失败')) : Promise.resolve([{ evidence_id: 'ev-1' }])
  })
  await settle()
  assert.equal(page.state().completeEventsLoaded, true)
  await page.router.push('/runs/run-1?tab=evidence')
  await settle()
  assert.match(page.state().activeArtifactError, /重试/)
  await page.state().loadActiveArtifact({ force: true })
  assert.equal(page.state().activeArtifactError, '')
  assert.equal(page.state().legacyEvidence[0].evidence_id, 'ev-1')
})
