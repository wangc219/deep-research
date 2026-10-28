import assert from 'node:assert/strict'
import test from 'node:test'
import { importWorkspaceSelection } from '../../src/utils/workspaceImport.js'

test('沙盒批量入库保留失败暂存，仅重试剩余项且不影响成功文件', async () => {
  const staged = new Map()
  const uploads = []
  const tasks = []
  let fail = true
  const upload = async (kb, paths) => {
    uploads.push(paths[0])
    if (paths[0] === '/duplicate.docx') throw new Error('已存在相同内容')
    return { items: [{ file_path: `minio://${paths[0]}`, content_hash: 'hash', size: 42 }] }
  }
  const submit = async (kb, items, params) => {
    assert.equal(kb, 'kb')
    assert.equal(params.auto_index, true)
    assert.equal(params.content_hashes[items[0]], 'hash')
    if (fail && items[0].includes('retry')) throw new Error('服务暂不可用')
    return { task_id: items[0] }
  }
  const options = { kbId: 'kb', staged, upload, submit, onSubmitted: task => tasks.push(task) }
  const result = await importWorkspaceSelection({ ...options, paths: ['/ok.docx', '/retry.docx', '/duplicate.docx'] })
  assert.deepEqual(result.succeeded, ['/ok.docx'])
  assert.deepEqual(result.failed.map(item => item.path), ['/retry.docx', '/duplicate.docx'])
  fail = false
  const retry = await importWorkspaceSelection({ ...options, paths: result.failed.map(item => item.path) })
  assert.deepEqual(retry.succeeded, ['/retry.docx'])
  assert.equal(uploads.filter(path => path === '/retry.docx').length, 1)
  assert.equal(tasks.length, 2)
  assert.equal(staged.size, 0)
})
