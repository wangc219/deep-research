import assert from 'node:assert/strict'
import test from 'node:test'
import { portraitOverview } from '../../src/utils/portraitOverview.js'

test('四项概述按固定顺序展示，保留字段内容', () => {
  const result = portraitOverview('**当前背景**：资料分散。解决思路：统一索引。达到效果：便于查阅。核心创新：跨库引用。')
  assert.deepEqual(result.fields, [
    { label: '当前背景', text: '资料分散。' },
    { label: '解决思路', text: '统一索引。' },
    { label: '达到效果', text: '便于查阅。' },
    { label: '核心创新', text: '跨库引用。' }
  ])
  assert.deepEqual(result.paragraphs, [])
})

test('历史概述只按原文分条，不虚构四项归属，不切开小数', () => {
  assert.deepEqual(portraitOverview('版本为1.5。资料有待核验！后续补充？'), {
    fields: [], paragraphs: ['版本为1.5。', '资料有待核验！', '后续补充？']
  })
})

test('部分字段不补写，保留前导原文和重复标签的补充信息', () => {
  const result = portraitOverview('原始说明。背景：旧内容；背景：补充；创新点：新内容')
  assert.deepEqual(result.paragraphs, ['原始说明。'])
  assert.deepEqual(result.fields, [
    { label: '当前背景', text: '旧内容；补充；' },
    { label: '解决思路', text: '' },
    { label: '达到效果', text: '' },
    { label: '核心创新', text: '新内容' }
  ])
})

test('兼容 Markdown 标题、中文编号和括号编号，保留句末标点', () => {
  const result = portraitOverview('### **当前背景**：资料分散。\n（一）解决思路：统一索引。\n三、达到效果：便于查阅。\n(4) 核心创新：跨库引用。')
  assert.deepEqual(result.fields.map((field) => field.text), ['资料分散。', '统一索引。', '便于查阅。', '跨库引用。'])
  assert.deepEqual(result.paragraphs, [])
})

test('不把正文中的相似用词或小数识别成标签和编号', () => {
  const result = portraitOverview('当前背景：说明解决思路：只是正文，版本1.5。\n核心创新：引用。')
  assert.equal(result.fields[0].text, '说明解决思路：只是正文，版本1.5。')
  assert.equal(result.fields[1].text, '')
  assert.equal(result.fields[3].text, '引用。')
})

test('兼容编号分条和空概述', () => {
  const result = portraitOverview('1、当前背景：背景\n2、解决思路：索引\n3、达到效果：查阅\n4、核心创新：引用')
  assert.deepEqual(result.fields.map((field) => field.text), ['背景', '索引', '查阅', '引用'])
  assert.deepEqual(portraitOverview(), { fields: [], paragraphs: [] })
})
