import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('../../src/views/equipment/EquipmentRunsView.vue', import.meta.url), 'utf8')
const apiSource = await readFile(new URL('../../src/apis/equipment_api.js', import.meta.url), 'utf8')

test('研究任务首页恢复 React Query 推荐轮播和控制组件', () => {
  assert.match(source, /class="recommendation-carousel"/)
  assert.match(source, /class="recommendation-card"/)
  assert.match(source, /暂停自动轮播/)
  assert.match(source, /上一条推荐 Query/)
  assert.match(source, /下一条推荐 Query/)
  assert.match(source, /class="suggestion-refresh"/)
})

test('研究模式与 Query 血缘随创建请求提交给后端', () => {
  assert.match(source, /class="research-mode-picker"/)
  assert.match(source, /execution_profile_id: form\.execution_profile_id/)
  assert.match(source, /source_query_id: form\.source_query_id \|\| undefined/)
  assert.match(source, /source_query_version: form\.source_query_id \? form\.source_query_version : undefined/)
  assert.match(source, /equipmentApi\.createResearchRun\(/)
  assert.match(source, /inheritKnowledgeScope\(selectedRecommendation\.value\)/)
  assert.match(source, /equipmentApi\.startResearchRun\(/)
  assert.doesNotMatch(source, /equipmentApi\.createRun\(/)
})

test('研究模型像智能对话一样常驻 Query 操作栏，而不是藏在运行配置中', () => {
  const footerStart = source.indexOf('<footer>')
  const inlineConfigStart = source.indexOf('<div v-if="configOpen"')
  const footerSource = source.slice(footerStart, inlineConfigStart)
  const inlineConfigSource = source.slice(inlineConfigStart, source.indexOf('</div>', inlineConfigStart))

  assert.match(footerSource, /class="research-model-picker"/)
  assert.match(footerSource, /<ModelSelectorComponent upward/)
  assert.match(footerSource, /:model_spec="form\.model_spec"/)
  assert.match(footerSource, /size="nano"/)
  assert.match(footerSource, /hasDefaultModel \? '系统默认模型' : '选择研究模型'/)
  assert.match(footerSource, /'missing-default': !hasDefaultModel && !form\.model_spec/)
  assert.doesNotMatch(inlineConfigSource, /EquipmentModelField|ModelSelectorComponent/)
  assert.match(source, /\.\.\.\(form\.model_spec \? \{ execution: \{ model_spec: form\.model_spec \} \} : \{\}\)/)
})

test('任务已创建但启动失败时仍可进入详情恢复，不会被当成创建失败', () => {
  assert.match(source, /if \(created\?\.run_id\)/)
  assert.match(source, /任务已创建，但启动或列表刷新未完成/)
  assert.match(source, /router\.push\(`\/equipment\/runs\/\$\{encodeURIComponent\(created\.run_id\)\}`\)/)
})

test('页面不再用局部样式覆盖 React 推荐区和移动端 Hero 尺寸', () => {
  const scopedStyle = source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] || ''
  assert.doesNotMatch(scopedStyle, /\.research-query-suggestions\s*\{/)
  assert.doesNotMatch(scopedStyle, /\.research-query-hero\s*\{/)
})

test('研究任务卡恢复 React 的选择、六类产物、失败恢复和停止操作', () => {
  assert.match(source, /class="run-card-select"/)
  assert.match(source, /<b>\{\{ deepSessionCount\(run\) \}\}<\/b> 深研/)
  assert.match(source, /class="run-card-deep-link"/)
  assert.match(source, />交互过程<\/button>/)
  assert.match(source, />S1–S6 Agent/)
  assert.match(source, /class="run-card-recovery"/)
  assert.match(source, /actOnRun\('cancel', run\)/)
  assert.match(source, /selectedDeletableRuns\.length/)
})

test('研究并行槽位可视化并允许管理员在前端热扩容', () => {
  assert.match(source, /class="research-runtime-panel"/)
  assert.match(source, /runtimeSlots/)
  assert.match(source, /runtime\.can_manage/)
  assert.match(source, /capacityDraft >= runtime\.capacity_limit/)
  assert.match(source, /Math\.max\(runtime\.value\.configured_capacity \|\| 1, runtime\.value\.active_count \|\| 0\)/)
  assert.match(source, /equipmentApi\.updateResearchCapacity\(capacity\)/)
  assert.match(source, /缩容不会中断运行中的任务/)
  assert.match(apiSource, /getResearchRuntime: \(\) => apiGet\('\/api\/equipment\/runtime'\)/)
  assert.match(apiSource, /method: 'PUT'[\s\S]*?JSON\.stringify\(\{ capacity \}\)/)
})
