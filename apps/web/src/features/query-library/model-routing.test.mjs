import test from 'node:test';
import assert from 'node:assert/strict';

import {
  platformRunExecution,
  queryGenerationModelConfig,
  queryLineageModelSpec,
} from './model-routing.mjs';

test('embedded Query generation only carries the unified platform model identifier', () => {
  assert.deepEqual(queryGenerationModelConfig({
    platformManaged: true,
    platformModelSpec: ' provider:model ',
    provider: 'legacy',
    baseUrl: 'https://legacy.invalid',
    apiKey: 'must-not-leak',
  }), {model_spec: 'provider:model'});
});

test('batch research inherits the model selected for Query generation', () => {
  assert.deepEqual(platformRunExecution(true, ' provider:model '), {model_spec: 'provider:model'});
  assert.equal(platformRunExecution(false, 'provider:model'), undefined);
  assert.equal(queryLineageModelSpec(
    {generation_id: 'generation-1'},
    [{generation_id: 'generation-1', model_config: {model_spec: ' original:model '}}],
    'current:model',
  ), 'original:model');
  assert.equal(queryLineageModelSpec(
    {generation_id: '', model_spec: ''},
    [],
    'current:model',
  ), 'current:model');
});

test('standalone Query generation keeps its legacy provider contract', () => {
  assert.deepEqual(queryGenerationModelConfig({
    provider: 'codex',
    reasoningEffort: 'xhigh',
    baseUrl: ' https://example.invalid/v1 ',
    apiKey: 'secret',
  }), {
    provider: 'codex',
    model: '',
    reasoning_effort: 'xhigh',
    base_url: 'https://example.invalid/v1',
    api_key: 'secret',
  });
});
