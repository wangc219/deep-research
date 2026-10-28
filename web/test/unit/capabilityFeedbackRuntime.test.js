import assert from 'node:assert/strict'
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { pid } from 'node:process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import { setImmediate } from 'node:timers'
import { compileScript, parse } from 'vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive, ref } from 'vue'

const source = new URL('../../src/views/equipment/EquipmentCapabilitiesView.vue', import.meta.url)
const compiledPath = fileURLToPath(new URL(`../../.capability-feedback-runtime-${pid}.mjs`, import.meta.url))
const defer = () => {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const flush = async () => { await nextTick(); await new Promise(setImmediate) }
const renderer = createRenderer({
  createElement: (type) => ({ type, children: [] }), createText: (text) => ({ text }), createComment: () => ({}),
  insert: (node, parent) => { parent.children.push(node); node.parent = parent }, remove: () => {},
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text },
  parentNode: (node) => node.parent, nextSibling: () => null, patchProp: () => {}
})

test('实际能力画像组件：最新三条、跨任务迟到响应、保存后回读失败与卸载隔离', async () => {
  const runtime = {
    route: reactive({ query: { run: 'run-a' } }),
    store: { resources: ref({ runs: [], capabilities: [], favorites: [] }), loading: ref({}), loadResource: async () => [] },
    api: { listCapabilityVersions: async () => ({ versions: [] }), listExpertFeedback: async () => [],
      getDeepContextOptions: async () => ({}), listDeepSessions: async () => [] },
    subscriptions: [], notices: [], confirmations: []
  }
  globalThis.__capabilityFeedbackRuntime = runtime
  const previousDocument = globalThis.document
  globalThis.document = { getElementById: () => ({ scrollIntoView() {} }) }
  let app
  try {
    const { descriptor } = parse(readFileSync(source, 'utf8'))
    let code = compileScript(descriptor, { id: 'capability-feedback-runtime' }).content
    code = code.replace(/^import ['"][^'"]+\.css['"];?\s*$/gm, '')
      .replace(/import (\w+) from ['"]@\/[^'"]+\.vue['"]/g, 'const $1 = {}')
      .replace(/import \{ useRoute, useRouter \} from ['"]vue-router['"]/, 'const useRoute = () => globalThis.__capabilityFeedbackRuntime.route; const useRouter = () => ({ replace: async () => {}, push: async () => {} })')
      .replace(/import \{ message, Modal \} from ['"]ant-design-vue['"]/, "const message = Object.fromEntries(['success','warning','error'].map(key => [key, value => globalThis.__capabilityFeedbackRuntime.notices.push([key,value])])) ; const Modal = { confirm: options => globalThis.__capabilityFeedbackRuntime.confirmations.push(options) }")
      .replace(/import \{ useEquipmentStore \} from ['"]@\/stores\/equipment['"]/, 'const useEquipmentStore = () => globalThis.__capabilityFeedbackRuntime.store')
      .replace(/import \{ equipmentApi \} from ['"]@\/apis\/equipment_api['"]/, 'const equipmentApi = globalThis.__capabilityFeedbackRuntime.api')
      .replace(/import \{ sharedPolling \} from ['"]@\/utils\/sharedPolling['"]/, 'const sharedPolling = { subscribe(callback) { const entry = { callback, stopped: false }; globalThis.__capabilityFeedbackRuntime.subscriptions.push(entry); return () => { entry.stopped = true } } }')
      .replace(/(['"])@\/([^'"]+)\1/g, (_, quote, path) => quote + new URL('../../src/' + path + (path.endsWith('.js') ? '' : '.js'), import.meta.url).href + quote)
      .replace("'./reportPresentation.js'", JSON.stringify(new URL('../../src/views/equipment/reportPresentation.js', import.meta.url).href))
    writeFileSync(compiledPath, code)
    const View = (await import(`${pathToFileURL(compiledPath).href}?time=${Date.now()}`)).default
    View.render = () => h('main')
    app = renderer.createApp(View)
    app.mount({ children: [] })
    await flush()
    const state = app._instance.setupState
    state.feedbackItems = [1, 5, 2, 4, 3].map((id) => ({ feedback_id: `f${id}`, created_at: `2026-10-26T00:00:0${id}Z` }))
    assert.deepEqual(state.visibleFeedback.map((row) => row.feedback_id), ['f5','f4','f3'])

    const old = defer()
    const recent = defer()
    let calls = 0
    runtime.api.listExpertFeedback = () => (++calls === 1 ? old.promise : recent.promise)
    const oldRequest = state.loadFeedback()
    state.selectedRunId = 'run-b'
    assert.deepEqual(state.feedbackItems, [])
    const newRequest = state.loadFeedback()
    recent.resolve([{ feedback_id: 'new-task' }])
    await newRequest
    old.resolve([{ feedback_id: 'old-task' }])
    await oldRequest
    assert.equal(state.feedbackItems[0].feedback_id, 'new-task')

    const stale = defer()
    calls = 0
    runtime.api.listExpertFeedback = () => ++calls === 1 ? stale.promise : Promise.reject(new Error('回读暂时不可用'))
    const staleRead = state.loadFeedback()
    runtime.api.createExpertFeedback = async () => ({ feedback: { feedback_id: 'committed', comment: '已持久化意见', created_at: '2026-10-26T10:00:00Z' } })
    state.feedbackComment = '合成验收意见'
    await state.submitFeedback(false)
    stale.resolve([])
    await staleRead
    assert.equal(state.feedbackItems[0].feedback_id, 'committed')
    assert.match(state.feedbackError, /回读暂时不可用/)
    assert.equal(runtime.notices.some(([kind, text]) => kind === 'success' && text.includes('已保存')), true)
    assert.equal(runtime.notices.some(([kind]) => kind === 'error'), false)
    let rollbackCalls = 0
    const rolled = { feedback_id: 'committed', status: 'rolled_back' }
    runtime.api.rollbackExpertFeedback = async () => { rollbackCalls++; return { feedback: rolled } }
    runtime.api.listExpertFeedback = async () => [rolled]
    state.rollbackFeedback(state.feedbackItems[0])
    assert.equal(rollbackCalls, 0)
    assert.equal(runtime.confirmations[0].okText, '确认回滚')
    await runtime.confirmations[0].onOk()
    assert.equal(rollbackCalls, 1)
    assert.equal(state.feedbackItems[0].status, 'rolled_back')
    state.rollbackFeedback(state.feedbackItems[0])
    state.selectedRunId = 'run-c'
    await runtime.confirmations[1].onOk()
    assert.equal(rollbackCalls, 1)
    app.unmount()
    app = null
    assert.equal(runtime.subscriptions.every((entry) => entry.stopped), true)
  } finally {
    app?.unmount()
    unlinkSync(compiledPath)
    delete globalThis.__capabilityFeedbackRuntime
    if (previousDocument === undefined) delete globalThis.document
    else globalThis.document = previousDocument
  }
})
