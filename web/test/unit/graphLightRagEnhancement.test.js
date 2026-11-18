import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const sectionSource = readFileSync(
  new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
  'utf8'
)

test('轻量化 RAG 是生产界面的唯一图谱抽取主流程', () => {
  assert.match(sectionSource, /extractor_type: 'lightrag_primary'/)
  assert.match(sectionSource, /orchestration_mode: 'lightrag_primary'/)
  assert.match(sectionSource, /value: 'lightrag_primary'/)
  assert.doesNotMatch(sectionSource, /value: 'hybrid_v2'/)
  assert.doesNotMatch(sectionSource, /DEFAULT_IE_ENDPOINT/)
})

test('增强配置保存项目模型、一次补抽和受限结构上下文', () => {
  assert.match(sectionSource, /model_spec: graphConfigForm\.llm_enhancement_model_spec/)
  assert.match(sectionSource, /max_gleanings: 1/)
  assert.match(sectionSource, /context_window_size: graphConfigForm\.context_window_size/)
  assert.match(sectionSource, /context_max_chars: graphConfigForm\.context_max_chars/)
  assert.match(sectionSource, /adaptive_routing: \{ enabled: false \}/)
})

test('轻量化 RAG 全链路提供受控 Agent 并行槽位', () => {
  assert.match(sectionSource, /llm_enhancement_concurrency: 2/)
  assert.match(sectionSource, /label: '均衡 · 4'/)
  assert.match(sectionSource, /label: '高吞吐 · 8'/)
  assert.match(sectionSource, /concurrency_count: graphConfigForm\.llm_enhancement_concurrency/)
})

test('增强配置能够从嵌套选项恢复到表单', () => {
  assert.match(sectionSource, /const llmEnhancement = options\.llm_enhancement \|\| \{\}/)
  assert.match(sectionSource, /llmEnhancement\.model_spec \|\| configStore\.config\?\.default_model/)
  assert.match(sectionSource, /const documentEnhancement = options\.document_enhancement \|\| \{\}/)
  assert.match(sectionSource, /documentLlmEnhancement\.model_spec \|\| configStore\.config\?\.default_model/)
})

test('LightRAG 配置不提交任何独立抽取 sidecar', () => {
  assert.doesNotMatch(sectionSource, /document_enhancement_endpoint/)
  assert.doesNotMatch(sectionSource, /ie_model_version/)
  assert.doesNotMatch(sectionSource, /ie_endpoint/)
  assert.doesNotMatch(sectionSource, /parallel_primary_extraction/)
  assert.doesNotMatch(sectionSource, /secondary: \{ enabled: false \}/)
})

test('知识图谱配置提供三步快速设置并隐藏低频参数', () => {
  assert.match(sectionSource, /graph-config-step/)
  assert.match(sectionSource, /选择统一增强模型/)
  assert.match(sectionSource, /并行槽位/)
  assert.match(sectionSource, /高级设置/)
})

test('图路径、创新发现和方案生成默认使用 LightRAG mix 检索', () => {
  assert.match(sectionSource, /retrieval_mode: 'mix'/)
  assert.match(sectionSource, /<a-select-option value="mix">图谱 \+ 原文 \+ 关键词/)
})
