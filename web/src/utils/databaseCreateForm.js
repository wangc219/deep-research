import { DEFAULT_CHUNK_PRESET_ID } from './chunkUtils.js'

export const createDefaultShareConfig = () => ({
  version: 2,
  read_scope: { access_level: 'global', department_ids: [], user_uids: [] },
  manage_scope: null
})

export const buildCategoryTreeData = (items = []) =>
  items
    .filter((item) => item?.active !== false)
    .map((item) => ({
      value: item.id,
      key: item.id,
      title: item.name,
      label: item.name,
      children: buildCategoryTreeData(item.children || [])
    }))

export const buildCategoryPathMap = (items = [], parentPath = '') => {
  const result = new Map()
  for (const item of items) {
    if (item?.active === false) continue
    const path = parentPath ? `${parentPath} / ${item.name}` : item.name
    result.set(item.id, path)
    for (const [id, childPath] of buildCategoryPathMap(item.children || [], path)) {
      result.set(id, childPath)
    }
  }
  return result
}

export const createEmptyDatabaseForm = (embeddingModel = '') => ({
  name: '',
  description: '',
  category_id: null,
  embedding_model_spec: embeddingModel,
  kb_type: '',
  chunk_preset_id: DEFAULT_CHUNK_PRESET_ID,
  additional_params: {}
})

export const createParamValues = (fields = []) =>
  Object.fromEntries(
    fields.map((field) => [
      field.key,
      'default' in field ? field.default : field.type === 'boolean' ? false : ''
    ])
  )

export const selectDatabaseType = (form, type, typeInfo) => ({
  ...form,
  kb_type: type,
  additional_params: createParamValues(typeInfo?.create_params?.options)
})

export const validateDatabaseConfig = (form, typeInfo) => {
  if (!String(form?.name || '').trim()) return '请输入知识库名称'
  if (typeInfo?.requires_embedding_model && !form?.embedding_model_spec) {
    return '请选择嵌入模型'
  }

  for (const field of typeInfo?.create_params?.options || []) {
    const value = form?.additional_params?.[field.key]
    if (
      field.required &&
      (value === undefined || value === null || (typeof value === 'string' && !value.trim()))
    ) {
      return `请填写${field.label || field.key}`
    }
    if (field.type === 'number' && typeof value === 'number') {
      if (field.min !== undefined && value < field.min)
        return `${field.label || field.key}不能小于${field.min}`
      if (field.max !== undefined && value > field.max)
        return `${field.label || field.key}不能大于${field.max}`
    }
  }
  return ''
}

export const buildDatabaseRequest = (form, typeInfo, shareConfig, defaultEmbeddingModel) => {
  const additionalParams = {}
  for (const field of typeInfo?.create_params?.options || []) {
    const value = form.additional_params[field.key]
    additionalParams[field.key] = typeof value === 'string' ? value.trim() : value
  }

  const request = {
    database_name: form.name.trim(),
    description: form.description?.trim() || '',
    kb_type: form.kb_type,
    category_id: form.category_id || null,
    additional_params: additionalParams,
    share_config: shareConfig
  }
  if (typeInfo?.requires_embedding_model) {
    request.embedding_model_spec = form.embedding_model_spec || defaultEmbeddingModel
    request.additional_params.chunk_preset_id = form.chunk_preset_id || DEFAULT_CHUNK_PRESET_ID
  }
  return request
}
