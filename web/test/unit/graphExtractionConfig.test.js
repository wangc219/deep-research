import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyGraphExtractionPreset,
  graphExtractionRiskMessage,
  graphPerformanceOptions,
  unmanagedGraphModelParams,
  matchGraphExtractionPreset
} from '../../src/utils/graphExtractionConfig.js'

test('图谱抽取预设可一键应用并识别自定义配置', () => {
  const form = { concurrency_count: 200, timeout_seconds: 60 }

  assert.equal(applyGraphExtractionPreset(form, 'balanced'), true)
  assert.deepEqual(form, {
    concurrency_count: 8,
    timeout_seconds: 180,
    enable_thinking: true,
    thinking_budget: 2048,
    max_output_tokens: 8192
  })
  assert.equal(matchGraphExtractionPreset(form), 'balanced')

  form.timeout_seconds = 240
  assert.equal(matchGraphExtractionPreset(form), 'custom')
  assert.equal(applyGraphExtractionPreset(form, 'missing'), false)
})

test('均衡默认保留受控思考，历史 JSON 性能参数可无损迁移到表单', () => {
  assert.deepEqual(graphPerformanceOptions(), {
    max_output_tokens: 8192,
    enable_thinking: true,
    thinking_budget: 2048
  })
  const params = {
    temperature: 0.1,
    max_tokens: 12000,
    extra_body: { enable_thinking: true, thinking_budget: 4096, custom: 'keep' }
  }
  assert.deepEqual(graphPerformanceOptions({ model_params: params }), {
    max_output_tokens: 12000,
    enable_thinking: true,
    thinking_budget: 4096
  })
  assert.deepEqual(unmanagedGraphModelParams(params), {
    temperature: 0.1,
    extra_body: { custom: 'keep' }
  })
  assert.equal(params.extra_body.thinking_budget, 4096)
})

test('高风险的 SiliconFlow 并发和过短超时会给出可操作提示', () => {
  const message = graphExtractionRiskMessage({
    model_spec: 'siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash',
    concurrency_count: 200,
    timeout_seconds: 60
  })

  assert.match(message, /自动限制为 16/)
  assert.match(message, /建议至少 180 秒/)
  assert.equal(
    graphExtractionRiskMessage({
      model_spec: 'siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash',
      concurrency_count: 8,
      timeout_seconds: 180
    }),
    ''
  )
})
