import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const modalSource = readFileSync(
  new URL('../../src/components/GlobalSearchModal.vue', import.meta.url),
  'utf8'
)
const workspaceSource = readFileSync(
  new URL('../../src/views/WorkspaceView.vue', import.meta.url),
  'utf8'
)

test('个人空间搜索明确覆盖文件与文件夹并为目录显示目录图标', () => {
  assert.match(modalSource, /搜索文件或文件夹/)
  assert.match(modalSource, /:is-dir="item\.is_dir"/)
  assert.match(modalSource, /未找到相关文件或文件夹/)
})

test('搜索命中目录后直接进入目录而不是尝试文件预览', () => {
  assert.match(
    workspaceSource,
    /const handleFileSearchSelect = async \(entry\) => \{[\s\S]*?if \(entry\.is_dir\) \{[\s\S]*?await selectWorkspacePath\(entry\.path\)/
  )
  assert.match(
    workspaceSource,
    /if \(String\(path\)\.endsWith\('\/'\)\) \{[\s\S]*?await selectWorkspacePath\(String\(path\)\)/
  )
})
