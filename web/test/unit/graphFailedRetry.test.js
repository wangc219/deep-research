import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

test('图谱失败恢复组件明确只重跑失败项', () => {
  const card = readFileSync(
    new URL('../../src/components/knowledge/GraphFailedRetryCard.vue', import.meta.url),
    'utf8'
  )
  const section = readFileSync(
    new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
    'utf8'
  )
  const api = readFileSync(new URL('../../src/apis/knowledge_api.js', import.meta.url), 'utf8')

  assert.match(card, /仅重跑 \{\{ count \}\} 个失败 Chunk，不影响已构建数据/)
  assert.match(card, /\$emit\('retry'\)/)
  assert.match(section, /@retry="confirmRetryFailedGraphChunks"/)
  assert.match(section, /graphBuildApi\.retryFailed\(kbId\.value\)/)
  assert.match(api, /graphBuildUrl\(kbId, 'retry-failed'\)/)
})
