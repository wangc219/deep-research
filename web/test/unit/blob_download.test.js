import assert from 'node:assert/strict'
import test from 'node:test'
import { downloadBlob } from '../../src/utils/download.js'

test('浏览器接管下载前保留 Blob URL，稍后清理 URL 与 DOM', (t) => {
  const previousWindow = globalThis.window
  const previousDocument = globalThis.document
  t.after(() => {
    globalThis.window = previousWindow
    globalThis.document = previousDocument
  })
  const events = []
  let cleanup
  const link = {
    click() {
      events.push(['click', this.href, this.download])
    },
    remove() {
      events.push(['remove'])
    }
  }
  globalThis.document = {
    createElement: () => link,
    body: { appendChild: () => events.push(['append']) }
  }
  globalThis.window = {
    URL: {
      createObjectURL: () => 'blob:artifact',
      revokeObjectURL: (url) => events.push(['revoke', url])
    },
    setTimeout: (fn, delay) => {
      cleanup = fn
      assert.equal(delay, 60_000)
    }
  }
  downloadBlob(new Blob(['report']), '报告.html')
  assert.deepEqual(events, [['append'], ['click', 'blob:artifact', '报告.html'], ['remove']])
  cleanup()
  assert.deepEqual(events.at(-1), ['revoke', 'blob:artifact'])
})
