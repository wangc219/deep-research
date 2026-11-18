import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sectionSource = await readFile(
  new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
  'utf8'
)
const apiSource = await readFile(new URL('../../src/apis/graph_api.js', import.meta.url), 'utf8')

test('图谱配置从治理接口选择不可变本体版本而非锁死默认版本', () => {
  assert.match(sectionSource, /ontologyVersionOptions/)
  assert.match(sectionSource, /selectedOntologyVersion/)
  assert.match(sectionSource, /构建任务会固定保存所选版本的完整本体快照/)
  assert.doesNotMatch(sectionSource, /v-model:value="graphConfigForm\.ontology_version" disabled/)
})

test('图谱 API 覆盖本体版本列表、详情和注册', () => {
  assert.match(apiSource, /getOntologyVersions/)
  assert.match(apiSource, /getOntologyVersion/)
  assert.match(apiSource, /registerOntologyVersion/)
  assert.match(apiSource, /\/api\/graph\/ontology\/versions/)
})
