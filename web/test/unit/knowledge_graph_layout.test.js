import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildKnowledgeGraphGroupLayout,
  getKnowledgeGraphNodeType,
  KNOWLEDGE_GRAPH_LAYOUTS,
  OTHER_NODE_TYPE
} from '../../src/utils/knowledgeGraphLayout.js'

test('知识图谱布局模式提供自由与按标签分组两种选择', () => {
  assert.deepEqual(KNOWLEDGE_GRAPH_LAYOUTS, { FORCE: 'force', GROUPED: 'grouped' })
})

test('实体类型兼容图谱的多种标签字段，无标签归入其他', () => {
  assert.equal(getKnowledgeGraphNodeType({ type: '技术' }), '技术')
  assert.equal(getKnowledgeGraphNodeType({ normalized: { type: '能力' } }), '能力')
  assert.equal(getKnowledgeGraphNodeType({ properties: { label: '应用' } }), '应用')
  assert.equal(getKnowledgeGraphNodeType({ labels: ['概念', 'Entity'] }), '概念')
  assert.equal(getKnowledgeGraphNodeType({ type: '  ' }), OTHER_NODE_TYPE)
})

test('分组布局按数量和名称稳定排序且不修改原始节点', () => {
  const nodes = [
    { id: '3', name: 'C', type: '应用' },
    { id: '2', name: 'B', type: '技术' },
    { id: '1', name: 'A', type: '技术' },
    { id: '4', name: 'D', type: '能力' }
  ]
  const snapshot = structuredClone(nodes)
  const first = buildKnowledgeGraphGroupLayout(nodes, { width: 800, height: 600 })
  const second = buildKnowledgeGraphGroupLayout([...nodes].reverse(), { width: 800, height: 600 })

  assert.deepEqual(first.groups, [
    { type: '技术', count: 2 },
    { type: '能力', count: 1 },
    { type: '应用', count: 1 }
  ])
  assert.deepEqual(first, second)
  assert.deepEqual(nodes, snapshot)
})

test('大规模分组布局为每个节点生成唯一有效网格坐标', () => {
  const types = ['技术', '应用', '能力', '概念', '原理', '证据']
  const nodes = Array.from({ length: 160 }, (_, index) => ({
    id: `node-${index}`,
    name: `实体 ${index}`,
    type: types[index % types.length]
  }))
  const layout = buildKnowledgeGraphGroupLayout(nodes, { width: 1280, height: 720 })
  const coordinates = Object.values(layout.positions)
  const uniqueCoordinates = new Set(coordinates.map(({ row, col }) => `${row}:${col}`))

  assert.equal(coordinates.length, nodes.length)
  assert.equal(uniqueCoordinates.size, nodes.length)
  assert.ok(coordinates.every(({ row, col }) => row >= 0 && col >= 0))
  assert.ok(coordinates.every(({ row, col }) => row < layout.rows && col < layout.cols))
})
