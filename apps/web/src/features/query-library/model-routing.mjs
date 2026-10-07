const normalizedSpec = value => String(value || '').trim();

/**
 * Embedded workbench requests must carry only the platform model identifier.
 * The API middleware resolves credentials server-side and strips every legacy
 * provider/base-url/api-key field before the job is persisted.
 */
export function queryGenerationModelConfig({
  platformManaged = false,
  platformModelSpec = '',
  provider = '',
  reasoningEffort = 'high',
  baseUrl = '',
  apiKey = '',
} = {}) {
  if (platformManaged) return {model_spec: normalizedSpec(platformModelSpec)};
  return {
    provider,
    model: '',
    reasoning_effort: reasoningEffort,
    base_url: String(baseUrl || '').trim(),
    api_key: String(apiKey || '').trim(),
  };
}

/** Keep batch-created runs on the same model selected for Query generation. */
export function platformRunExecution(platformManaged, platformModelSpec = '') {
  return platformManaged ? {model_spec: normalizedSpec(platformModelSpec)} : undefined;
}

/** Generated Query descendants keep the model selected by their generation job. */
export function queryLineageModelSpec(query = {}, generations = [], fallbackModelSpec = '') {
  const direct = normalizedSpec(query?.model_spec);
  if (direct) return direct;
  const generationId = normalizedSpec(query?.generation_id);
  const generation = generationId
    ? generations.find(item => normalizedSpec(item?.generation_id) === generationId)
    : null;
  return normalizedSpec(
    generation?.model_config?.model_spec
      || generation?.provider_snapshot?.model_spec
      || fallbackModelSpec,
  );
}
