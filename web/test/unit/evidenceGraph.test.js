import assert from 'node:assert/strict'
import test from 'node:test'
import { filterEvidenceGraph, graphSourceOptions, normalizeGraphFilters } from '../../src/views/document-research/evidenceGraph.js'

const graph = [
  { subject: 'Docling', relation: '支持提取', object: '复杂表格', kind: 'fact', source_id: 'S1', quote: 'Docling 支持提取复杂表格。' },
  { subject: 'Docling', relation: '可能提升', object: '跨页表格识别', kind: 'inference', source_id: 'S2', quote: '该推断尚需验证。' },
  { subject: 'PaddleOCR', relation: '支持', object: '中文识别', kind: 'fact', source_id: 'S2', quote: 'PaddleOCR 支持中文识别。' },
  { subject: 'Layout Model', relation: 'uses', object: 'Table Structure', kind: 'fact', source_id: 'S3', quote: 'exact source quote' }
]

test('graph search supports Chinese and combined terms across endpoints and relation without changing quotes', () => {
  const snapshot = structuredClone(graph)
  assert.deepEqual(filterEvidenceGraph(graph, { query: 'Docling 表格' }), graph.slice(0, 2))
  assert.deepEqual(filterEvidenceGraph(graph, { query: '跨页 可能提升' }), [graph[1]])
  assert.deepEqual(filterEvidenceGraph(graph, { query: '中文' }), [graph[2]])
  assert.deepEqual(filterEvidenceGraph(graph, { query: 'docling 中文' }), [])
  assert.deepEqual(graph, snapshot)
})

test('graph search accepts mixed case, full-width letters and extra whitespace but does not search incidental quote text', () => {
  assert.deepEqual(filterEvidenceGraph(graph, { query: '  ＤＯＣＬＩＮＧ\t支持提取\n' }), [graph[0]])
  assert.deepEqual(filterEvidenceGraph(graph, { query: 'layout\tSTRUCTURE' }), [graph[3]])
  assert.deepEqual(filterEvidenceGraph(graph, { query: 'exact source quote' }), [])
  assert.equal(filterEvidenceGraph(graph, { query: '  ' }).length, 4)
})

test('graph source, type and text filters intersect without dropping relation evidence', () => {
  assert.deepEqual(filterEvidenceGraph(graph, { sourceId: 'S2', kind: 'fact' }), [graph[2]])
  assert.deepEqual(filterEvidenceGraph(graph, { sourceId: 'S2', kind: 'inference', query: '表格' }), [graph[1]])
  assert.deepEqual(filterEvidenceGraph(graph, { sourceId: 'S2', kind: 'fact', query: 'Docling' }), [])
})

test('stale sources and invalid filter values cannot hide a replacement graph', () => {
  const next = [graph[3]]
  const stale = { query: '', sourceId: 'S1', kind: 'unsupported' }
  assert.deepEqual(normalizeGraphFilters(next, stale), { query: '', sourceId: '', kind: 'all' })
  assert.deepEqual(filterEvidenceGraph(next, stale), next)
  assert.deepEqual(normalizeGraphFilters([], { query: null, sourceId: 'S1' }), { query: '', sourceId: '', kind: 'all' })
  assert.deepEqual(filterEvidenceGraph([], stale), [])
})

test('source options include only graph references, deduplicate chunks and retain missing historical titles', () => {
  assert.deepEqual(graphSourceOptions(graph, [{ id: 'S1', title: '官方文档' }, { id: 'S2', title: '实验建议' }, { id: 'S4', title: '未引用资料' }]), [
    { id: 'S1', title: '官方文档' }, { id: 'S2', title: '实验建议' }, { id: 'S3', title: '来源标题未提供' }
  ])
  assert.deepEqual(graphSourceOptions([{ subject: 'legacy', kind: 'fact' }]), [])
})
