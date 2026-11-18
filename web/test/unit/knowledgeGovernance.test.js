import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const governanceSource = await readFile(
  new URL('../../src/views/KnowledgeGovernanceView.vue', import.meta.url),
  'utf8'
)

test('分类树防御异常旧数据且窄屏不会把分类名称挤成逐字竖排', () => {
  assert.match(governanceSource, /const visited = new Set\(\)/)
  assert.match(governanceSource, /if \(visited\.has\(item\.id\)\) continue/)
  assert.match(governanceSource, /class="category-title"/)
  assert.match(governanceSource, /@media\(max-width:600px\)/)
  assert.match(governanceSource, /\.category-title\{flex-basis:100%;width:100%\}/)
  assert.match(governanceSource, /class="category-actions" wrap/)
})
