import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const readComponent = (name) =>
  readFileSync(
    new URL(`../../src/components/model-management/${name}.vue`, import.meta.url),
    'utf8'
  )

test('AMiner 与 Open WebSearch 设置卡片默认折叠且保留可访问标题', () => {
  for (const name of ['AMinerSettingsCard', 'WebSearchSettingsCard']) {
    const source = readComponent(name)
    const card = source.slice(source.indexOf('<details'), source.indexOf('</details>') + 10)

    assert.match(card, /<details class="(?:aminer|web-search)-card"/)
    assert.doesNotMatch(card, /<details[^>]*\sopen(?:\s|=|>)/)
    assert.match(card, /<summary class="card-summary">/)
    assert.match(card, /class="card-heading" role="heading" aria-level="2"/)
    assert.match(card, /class="card-chevron"/)
  }
})
