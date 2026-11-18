import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildCategoryPathMap,
  buildCategoryTreeData,
  buildDatabaseRequest,
  createEmptyDatabaseForm,
  selectDatabaseType,
  validateDatabaseConfig
} from '../../src/utils/databaseCreateForm.js'
import { getKbTypeLabel } from '../../src/utils/kb_utils.js'

const difyType = {
  create_params: {
    options: [
      { key: 'url', label: '地址', required: true },
      { key: 'token', label: 'Token', type: 'password', required: true }
    ]
  }
}

test('切换知识库类型保留通用字段并重置类型参数', () => {
  const form = {
    ...createEmptyDatabaseForm('embed/model'),
    name: '产品资料',
    description: '说明',
    category_id: 'category-child'
  }
  const selected = selectDatabaseType(form, 'dify', difyType)
  assert.equal(selected.name, '产品资料')
  assert.equal(selected.description, '说明')
  assert.equal(selected.category_id, 'category-child')
  assert.deepEqual(selected.additional_params, { url: '', token: '' })
})

test('配置校验拒绝空名称和必填动态字段', () => {
  const empty = selectDatabaseType(createEmptyDatabaseForm(), 'dify', difyType)
  assert.equal(validateDatabaseConfig(empty, difyType), '请输入知识库名称')
  empty.name = '资料'
  assert.equal(validateDatabaseConfig(empty, difyType), '请填写地址')
})

test('只为需要嵌入模型的类型构建模型和分块参数', () => {
  const form = {
    ...createEmptyDatabaseForm('embed/model'),
    name: '资料',
    kb_type: 'milvus',
    chunk_preset_id: 'general'
  }
  const request = buildDatabaseRequest(
    form,
    { requires_embedding_model: true, create_params: { options: [] } },
    { version: 2 },
    'fallback/model'
  )
  assert.equal(request.embedding_model_spec, 'embed/model')
  assert.equal(request.additional_params.chunk_preset_id, 'general')
  assert.equal(request.category_id, null)

  const connectorRequest = buildDatabaseRequest(
    { ...form, kb_type: 'dify' },
    difyType,
    { version: 2 },
    'fallback/model'
  )
  assert.equal('embedding_model_spec' in connectorRequest, false)
  assert.equal('chunk_preset_id' in connectorRequest.additional_params, false)
})

test('创建请求携带知识库主分类', () => {
  const request = buildDatabaseRequest(
    {
      ...createEmptyDatabaseForm(),
      name: '反无人资料库',
      kb_type: 'dify',
      category_id: 'counter-uas'
    },
    { create_params: { options: [] } },
    { version: 2 },
    ''
  )

  assert.equal(request.category_id, 'counter-uas')
})

test('分类树保留层级并生成无歧义的完整路径', () => {
  const categories = [
    {
      id: 'root',
      name: '新质作战技术',
      active: true,
      children: [
        { id: 'child', name: '反无人技术', active: true, children: [] },
        { id: 'disabled', name: '已停用', active: false, children: [] }
      ]
    }
  ]

  const tree = buildCategoryTreeData(categories)
  const paths = buildCategoryPathMap(categories)

  assert.equal(tree[0].children.length, 1)
  assert.equal(tree[0].children[0].value, 'child')
  assert.equal(paths.get('child'), '新质作战技术 / 反无人技术')
  assert.equal(paths.has('disabled'), false)
})

test('知识库类型标签映射将 milvus 解析为本平台', () => {
  assert.equal(getKbTypeLabel('milvus'), '本平台')
  assert.equal(getKbTypeLabel('Milvus'), '本平台')
  assert.equal(getKbTypeLabel('dify'), 'Dify')
  assert.equal(getKbTypeLabel('notion'), 'Notion')
  assert.equal(getKbTypeLabel('unknown'), 'unknown')
})
