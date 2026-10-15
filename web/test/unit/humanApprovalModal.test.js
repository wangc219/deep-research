import assert from 'node:assert/strict'
import test from 'node:test'

import { createRenderer, h, nextTick } from 'vue'
import { createServer } from 'vite'
import { compileScript, parse } from 'vue/compiler-sfc'
import { readFileSync } from 'node:fs'

const makeNode = (type) => {
  const node = { type, children: [], props: {}, style: {}, parent: null, text: '' }
  node.focus = () => {
    node.focused = true
  }
  return node
}

const renderer = createRenderer({
  createElement: makeNode,
  createText(text) {
    return { ...makeNode('text'), text }
  },
  createComment(text) {
    return { ...makeNode('comment'), text }
  },
  insert(child, parent, anchor = null) {
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove(child) {
    const index = child.parent?.children.indexOf(child) ?? -1
    if (index >= 0) child.parent.children.splice(index, 1)
  },
  setText(node, text) {
    node.text = text
  },
  setElementText(node, text) {
    node.text = text
    node.children = []
  },
  parentNode: (node) => node.parent,
  nextSibling: (node) => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  patchProp(node, key, _oldValue, value) {
    node.props[key] = value
  }
})

const find = (node, predicate) => {
  if (predicate(node)) return node
  for (const child of node.children || []) {
    const match = find(child, predicate)
    if (match) return match
  }
  return undefined
}

const textContent = (node) =>
  [node.text, ...(node.children || []).map((child) => textContent(child))].join('')

test('输入框上方提问卡片提交纯文本，并在跳过时省略当前题答案', async (t) => {
  globalThis.window = {
    getComputedStyle: () => ({
      lineHeight: '20',
      paddingTop: '0',
      paddingBottom: '0',
      borderTopWidth: '0',
      borderBottomWidth: '0'
    })
  }

  const server = await createServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom',
    plugins: [
      {
        name: 'human-approval-modal-test',
        resolveId(id) {
          if (id === 'virtual:human-approval-modal-test') return `\0${id}`
        },
        load(id) {
          if (id !== '\0virtual:human-approval-modal-test') return
          const source = readFileSync(
            new URL('../../src/components/HumanApprovalModal.vue', import.meta.url),
            'utf8'
          )
          const { descriptor } = parse(source)
          return compileScript(descriptor, {
            id: 'human-approval-modal-test',
            inlineTemplate: true
          }).content
        }
      }
    ]
  })

  let app
  try {
    const { default: HumanApprovalModal } = await server.ssrLoadModule(
      'virtual:human-approval-modal-test'
    )
    const submissions = []
    const questions = [
      { question_id: 'destination', question: '你想去哪个城市？' },
      {
        question_id: 'season',
        question: '你最喜欢哪个季节？',
        options: ['春天', '夏天']
      }
    ]
    const host = makeNode('root')
    app = renderer.createApp(() =>
      h(HumanApprovalModal, {
        visible: true,
        questions,
        onSubmit: (answer) => submissions.push(answer)
      })
    )
    app.mount(host)
    await nextTick()
    assert.equal(find(host, (node) => node.props.role === 'region').props['aria-modal'], undefined)
    assert.equal(find(host, (node) => node.props.class === 'question-dialog-backdrop'), undefined)

    const answer = find(host, (node) => node.props.placeholder === '请输入你的回答…')
    assert.ok(answer)
    answer.props.onInput({ target: { value: '  杭州  ' } })
    await nextTick()

    const next = find(host, (node) => node.type === 'button' && node.props.class === 'btn btn-approve')
    assert.equal(textContent(next), '下一步')
    assert.equal(next.props.disabled, false)
    assert.equal(next.parent?.parent?.props.class, 'question-response-bar free-text-answer')
    next.props.onClick()
    await nextTick()

    assert.ok(find(host, (node) => node.props.placeholder === '或自行填写回答'))
    const spring = find(
      host,
      (node) => node.type === 'input' && node.props.value === '春天'
    )
    spring.props.onChange()
    await nextTick()
    const submit = find(host, (node) => node.type === 'button' && node.props.class === 'btn btn-approve')
    assert.equal(textContent(submit), '提交')
    assert.equal(submit.parent?.parent?.props.class, 'question-response-bar other-input')
    submit.props.onClick()
    assert.deepEqual(submissions, [{ destination: '杭州', season: '春天' }])

    app.unmount()
    submissions.length = 0
    const skippedHost = makeNode('root')
    app = renderer.createApp(() =>
      h(HumanApprovalModal, {
        visible: true,
        questions,
        onSubmit: (answerValue) => submissions.push(answerValue)
      })
    )
    app.mount(skippedHost)
    await nextTick()
    const skip = find(
      skippedHost,
      (node) => node.type === 'button' && node.props.class === 'btn btn-skip'
    )
    skip.props.onClick()
    await nextTick()
    const skippedSpring = find(
      skippedHost,
      (node) => node.type === 'input' && node.props.value === '春天'
    )
    skippedSpring.props.onChange()
    await nextTick()
    const skippedSubmit = find(
      skippedHost,
      (node) => node.type === 'button' && node.props.class === 'btn btn-approve'
    )
    skippedSubmit.props.onClick()

    assert.deepEqual(submissions, [{ season: '春天' }])

    app.unmount()
    submissions.length = 0
    const customHost = makeNode('root')
    app = renderer.createApp(() =>
      h(HumanApprovalModal, {
        visible: true,
        questions,
        onSubmit: (answerValue) => submissions.push(answerValue)
      })
    )
    app.mount(customHost)
    await nextTick()
    find(customHost, (node) => node.type === 'button' && node.props.class === 'btn btn-skip').props.onClick()
    await nextTick()
    const customAnswer = find(
      customHost,
      (node) => node.props.placeholder === '或自行填写回答'
    )
    customAnswer.props.onInput({ target: { value: '  秋天  ' } })
    await nextTick()
    find(
      customHost,
      (node) => node.type === 'button' && node.props.class === 'btn btn-approve'
    ).props.onClick()

    assert.deepEqual(submissions, [
      { season: { type: 'other', text: '秋天', selected: [] } }
    ])

    app.unmount()
    submissions.length = 0
    const multipleHost = makeNode('root')
    app = renderer.createApp(() =>
      h(HumanApprovalModal, {
        visible: true,
        questions: [
          {
            question_id: 'cities',
            question: '你想去哪些城市？',
            options: ['杭州', '上海'],
            multi_select: true
          }
        ],
        onSubmit: (answerValue) => submissions.push(answerValue)
      })
    )
    app.mount(multipleHost)
    await nextTick()
    await nextTick()

    const questionTitle = find(multipleHost, (node) => node.props.id === 'question-dialog-title')
    assert.equal(questionTitle.focused, true)

    const multipleCustomAnswer = find(
      multipleHost,
      (node) => node.props.placeholder === '或自行填写回答'
    )
    multipleCustomAnswer.props.onInput({ target: { value: '苏州' } })
    await nextTick()
    find(multipleHost, (node) => node.type === 'input' && node.props.value === '杭州').props.onChange()
    await nextTick()

    const multipleSubmit = find(
      multipleHost,
      (node) => node.type === 'button' && node.props.class === 'btn btn-approve'
    )
    assert.equal(multipleSubmit.props.disabled, false)
    multipleSubmit.props.onClick()
    assert.deepEqual(submissions, [{ cities: ['杭州'] }])


    app.unmount()
    t.mock.timers.enable({ apis: ['Date', 'setInterval'], now: 1_000_000 })
    const savedStates = new Map()
    window.sessionStorage = {
      getItem: (key) => savedStates.get(key) || null,
      setItem: (key, value) => savedStates.set(key, value)
    }
    const recommendedQuestions = [
      { question_id: 'equipment', question: '聚焦哪类装备？', options: [
        { label: '水下装备（推荐）', value: 'underwater', description: '适合深水长期观测，重点研究续航与感知能力。' },
        { label: '水面装备', value: 'surface' }
      ] },
      { question_id: 'focus', question: '侧重哪些维度？', multi_select: true, options: [
        { label: '能力画像 (Recommended)', value: 'capability' },
        { label: '技术路径', value: 'technology' }
      ] }
    ]
    const mountQuestions = (props = {}) => {
      submissions.length = 0
      const root = makeNode('root')
      app = renderer.createApp(() => h(HumanApprovalModal, {
        visible: true, autoRecommend: true, questions: recommendedQuestions,
        onSubmit: (value) => submissions.push(value), ...props
      }))
      app.mount(root)
      return root
    }
    const timedHost = mountQuestions({ requestKey: 'thread:run-auto' })
    await nextTick()
    assert.ok(textContent(timedHost).includes('2:00 后未作答'))
    const description = find(timedHost, (node) => node.props.class === 'option-description')
    assert.equal(textContent(description), '适合深水长期观测，重点研究续航与感知能力。')
    assert.ok(description.parent.children.find((node) => String(node.props.class || '').includes('option-label')))
    assert.equal(textContent(find(timedHost, (node) => node.props.id === 'question-dialog-title')), '聚焦哪类装备？')
    t.mock.timers.tick(119_750)
    await nextTick()
    assert.deepEqual(submissions, [])
    t.mock.timers.tick(250)
    await nextTick()
    assert.deepEqual(submissions, [{ equipment: 'underwater', focus: ['capability'] }])
    t.mock.timers.tick(120_000)
    assert.equal(submissions.length, 1)

    app.unmount()
    const restoredHost = mountQuestions({ requestKey: 'thread:run-auto' })
    await nextTick()
    t.mock.timers.tick(120_000)
    assert.deepEqual(submissions, [])
    assert.ok(textContent(restoredHost).includes('自动选择已停止'))

    app.unmount()
    const manualHost = mountQuestions({ requestKey: 'thread:run-manual' })
    await nextTick()
    find(manualHost, (node) => node.type === 'input' && node.props.value === 'surface').props.onChange()
    await nextTick()
    t.mock.timers.tick(120_000)
    assert.deepEqual(submissions, [])
    assert.ok(textContent(manualHost).includes('自动选择已停止'))

    app.unmount()
    const customTimedHost = mountQuestions({ requestKey: 'thread:run-custom' })
    await nextTick()
    find(customTimedHost, (node) => node.props.placeholder === '或自行填写回答')
      .props.onInput({ target: { value: '跨域协同' } })
    await nextTick()
    t.mock.timers.tick(120_000)
    assert.deepEqual(submissions, [])

    app.unmount()
    mountQuestions({ requestKey: 'thread:run-refresh' })
    await nextTick()
    t.mock.timers.tick(60_000)
    app.unmount()
    const refreshedHost = mountQuestions({ requestKey: 'thread:run-refresh' })
    await nextTick()
    assert.ok(textContent(refreshedHost).includes('1:00 后未作答'))
    t.mock.timers.tick(60_000)
    await nextTick()
    assert.equal(submissions.length, 1)

    app.unmount()
    mountQuestions({ requestKey: 'thread:run-no-default', questions })
    await nextTick()
    t.mock.timers.tick(120_000)
    assert.deepEqual(submissions, [])

    app.unmount()
    mountQuestions({ requestKey: 'thread:run-approval', kind: 'tool_approval',
      actionRequests: [{ name: 'execute', args: { command: 'example' } }] })
    await nextTick()
    t.mock.timers.tick(120_000)
    assert.deepEqual(submissions, [])
  } finally {
    app?.unmount()
    await server.close()
    delete globalThis.window
  }
})
