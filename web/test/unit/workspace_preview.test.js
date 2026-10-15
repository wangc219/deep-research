import assert from 'node:assert/strict'
import test from 'node:test'
import { editableWorkspacePath } from '../../src/utils/workspace_preview.js'

test('编辑文件使用用户工作区路径，保持当前 Project 与文件身份', () => {
  assert.equal(
    editableWorkspacePath({ path: '/home/gem/user-data/projects/one/outputs/report.md' }),
    '/projects/one/outputs/report.md'
  )
  assert.equal(
    editableWorkspacePath({
      path: '/outputs/report.md',
      workdir: true,
      artifact_url: '/api/chat/thread/one/artifacts/home/gem/user-data/projects/one/outputs/report.md'
    }),
    '/projects/one/outputs/report.md'
  )
  assert.equal(editableWorkspacePath({ path: '/notes.md', workspace: true }), '/notes.md')
})

test('只读 Skill、未知目录与跳转路径不能显示编辑功能', () => {
  for (const file of [
    { path: '/home/gem/skills/documents/SKILL.md' },
    { path: '/home/gem/user-data/report.md', readonly: true },
    { path: '/etc/passwd' },
    { path: '/home/gem/user-data/../outside.md' },
    { path: '/outputs/report.md', workdir: true }
  ]) assert.equal(editableWorkspacePath(file), '')
})
