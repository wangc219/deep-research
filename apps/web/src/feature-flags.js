const enabledFromEnvironment = value => ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());

// Optional workbench modules stay registered in source but are absent from
// navigation and direct routes unless explicitly enabled at build time.
export const FRONTEND_FEATURE_FLAGS = Object.freeze({
  benchmark: enabledFromEnvironment(import.meta.env.VITE_ENABLE_BENCHMARK),
  ablation: enabledFromEnvironment(import.meta.env.VITE_ENABLE_ABLATION),
});

export const isFrontendFeatureEnabled = featureId => FRONTEND_FEATURE_FLAGS[featureId] ?? true;
