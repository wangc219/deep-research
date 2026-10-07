import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(
  new URL('../../src/views/KnowledgePortalView.vue', import.meta.url),
  'utf8'
)

test('知识门户允许直接删除研究草稿并刷新聚合数据', () => {
  assert.match(source, /v-if="run\.status === 'draft'"/)
  assert.match(source, /class="kp-delete-run"/)
  assert.match(source, /@click="deleteDraftRun\(run\)"/)
  assert.match(source, /await equipmentApi\.deleteRun\(run\.run_id\)/)
  assert.match(source, /await load\(\)/)
  assert.match(source, /永久删除研究草稿/)
  assert.match(source, /okButtonProps: \{ danger: true \}/)
})

test('草稿删除按钮与详情链接分离且具有可访问名称', () => {
  assert.match(source, /class="kp-run-row"/)
  assert.match(source, /:aria-label="`删除研究草稿 \$\{run\.topic\}`"/)
  const runLink = source.match(
    /<router-link class="kp-row" :to="`\/equipment\/runs\/\$\{run\.run_id\}`">[\s\S]*?<\/router-link>/
  )?.[0] || ''
  assert.ok(runLink)
  assert.doesNotMatch(runLink, /<button/)
})
