import assert from 'node:assert/strict'
import test from 'node:test'

import {
  filterProjects,
  formatRelativeTime,
  projectDisplayName
} from '../../src/utils/projectSelection.js'

test('Project 搜索按名称过滤且无匹配时返回空列表', () => {
  const projects = [{ name: 'Desktop' }, { name: '论文写作' }, { name: 'Agent Skills' }]

  assert.deepEqual(filterProjects(projects, '  agent  '), [{ name: 'Agent Skills' }])
  assert.deepEqual(filterProjects(projects, '不存在'), [])
  assert.equal(filterProjects(projects, ''), projects)
})

test('管理员项目标签包含所有者且搜索支持 owner uid', () => {
  const project = { id: 'project-1', name: '跨用户研究', uid: 'owner-1' }

  assert.equal(projectDisplayName(project, false), '跨用户研究')
  assert.equal(projectDisplayName(project, true), '跨用户研究 · owner-1')
  assert.deepEqual(filterProjects([project], 'owner-1'), [project])
})

test('历史项目时间按分钟到年份显示相对时间', () => {
  const now = Date.parse('2026-08-22T12:00:00Z')

  assert.equal(formatRelativeTime('2026-08-22T11:59:30Z', now), '刚刚')
  assert.equal(formatRelativeTime('2026-08-22T11:55:00Z', now), '5分钟前')
  assert.equal(formatRelativeTime('2026-08-22T09:00:00Z', now), '3小时前')
  assert.equal(formatRelativeTime('2026-08-19T12:00:00Z', now), '3天前')
  assert.equal(formatRelativeTime('2026-06-22T12:00:00Z', now), '2个月前')
  assert.equal(formatRelativeTime('2024-08-22T12:00:00Z', now), '2年前')
  assert.equal(formatRelativeTime('invalid', now), '')
})
