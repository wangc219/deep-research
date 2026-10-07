import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDepartmentDirectory,
  buildDepartmentPathMap
} from '../../src/utils/departmentDirectory.js'

const departments = [
  { id: 3, name: '下级部门', parent_id: 2, user_count: 2 },
  { id: 1, name: '总部', parent_id: null, user_count: 4 },
  { id: 2, name: '研发部', parent_id: 1, user_count: 3 }
]

test('部门目录按 parent_id 组装为层级树', () => {
  const tree = buildDepartmentDirectory(departments)

  assert.equal(tree.length, 1)
  assert.equal(tree[0].title, '总部')
  assert.equal(tree[0].children[0].title, '研发部')
  assert.equal(tree[0].children[0].children[0].title, '下级部门')
  assert.equal(tree[0].children[0].children[0].userCount, 2)
})

test('部门路径使用完整层级名称', () => {
  const paths = buildDepartmentPathMap(departments)

  assert.equal(paths.get(3), '总部 / 研发部 / 下级部门')
})
