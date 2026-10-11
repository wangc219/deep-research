import test from 'node:test'
import assert from 'node:assert/strict'
import { createDocumentResearchApi } from '../src/apis/document_research_api.js'

test('交付下载使用专用鉴权并保持二进制响应与认证错误语义', async () => {
  const calls = []
  let denied = false
  const api = createDocumentResearchApi(() => 'dedicated-token', async (url, options) => {
    calls.push({ url, options })
    return denied ? new Response(JSON.stringify({ detail: '权限已撤销' }), { status: 403 }) : new Response(new Uint8Array([80, 75, 3, 4]), { headers: { 'Content-Type': 'application/zip' } })
  })
  assert.deepEqual([...new Uint8Array(await (await api.downloadBundle('task/id')).arrayBuffer())], [80, 75, 3, 4])
  assert.equal(calls[0].url, '/document-research-api/tasks/task%2Fid/delivery.zip')
  assert.equal(calls[0].options.headers.Authorization, 'Bearer dedicated-token')
  assert.equal(calls[0].options.credentials, 'omit')
  assert.equal(calls[0].options.redirect, 'error')
  denied = true
  await assert.rejects(api.downloadArtifact('task', 'report.md'), { status: 403, message: '权限已撤销' })
})

test('Markdown 保存显式携带旧文件版本，设置请求不写浏览器存储', async () => {
  const calls = []
  const api = createDocumentResearchApi(() => 'dedicated-token', async (url, options) => {
    calls.push({ url, options })
    return new Response('{}')
  })
  await api.saveArtifact('task', 'report.md', { content: '# revision', expected_sha256: 'old-version' })
  assert.deepEqual(JSON.parse(calls[0].options.body), { content: '# revision', expected_sha256: 'old-version' })
  await api.saveModelSettings({ base_url: 'https://example.com/v1', model: 'example', api_key: 'synthetic-secret' })
  assert.equal(calls[1].options.method, 'PUT')
  assert.equal(calls[1].url, '/document-research-api/settings/model')
  assert.equal(calls[1].options.credentials, 'omit')
})
