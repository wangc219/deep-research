import assert from 'node:assert/strict'
import test from 'node:test'
import { createMarkdownRenderer } from '../../src/utils/markdown_preview.js'
import { normalizeCitationSource } from '../../src/utils/sourceCitations.js'

const renderer = createMarkdownRenderer({ themeName: 'github-light' })

test('正文引用使用来源 URL，DOI 缩写转换为来源链接', () => {
  const html = renderer.render(
    '结论<cite source="https://arxiv.org/abs/2205.14135" type="url">1</cite>' +
      '<cite type="url" source="10.48550/arXiv.1706.03762">2</cite>'
  )
  assert.match(html, /href="https:\/\/arxiv.org\/abs\/2205.14135"/)
  assert.match(html, /href="https:\/\/doi.org\/10.48550\/arXiv.1706.03762"/)
  assert.match(html, /target="_blank" rel="noopener noreferrer"/)
})

test('引用标签和 URL 保持转义，危险协议不能生成引用链接', () => {
  for (const source of ['javascript:alert(1)', 'data:text/html,test', 'file:///etc/passwd', '/relative']) {
    assert.equal(normalizeCitationSource(source), '')
    assert.doesNotMatch(renderer.render(`结论<cite source="${source}" type="url">1</cite>`), /source-citation/)
  }
  const html = renderer.render('结论<cite source="https://example.org/?x=1&amp;y=2" type="url">&lt;img&gt;</cite>')
  assert.match(html, /href="https:\/\/example.org\/\?x=1&amp;y=2"/)
  assert.match(html, /&lt;img&gt;<\/a>/)
  assert.doesNotMatch(html, /<img/)
})

test('文件引用与代码示例继续使用原有展示', () => {
  assert.doesNotMatch(renderer.render('附件<cite source="file.pdf" type="file">1</cite>'), /source-citation/)
  assert.doesNotMatch(
    renderer.render('`<cite source="https://example.org" type="url">1</cite>`'),
    /class="source-citation"/
  )
})
