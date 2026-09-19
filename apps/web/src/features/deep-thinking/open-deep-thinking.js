/** Event name used to open the deep-thinking panel from outside React trees. */
export const OPEN_DEEP_THINKING_EVENT = 'equipment:open-deep-thinking';

export const DEEP_THINKING_QUERY_KEYS = Object.freeze({
  open: 'deep',
  sessionId: 'session',
  branchId: 'branch',
  targetIdentity: 'target',
});

const clean = value => String(value ?? '').trim();

/** Read the shareable portion of the deep-research workspace location. */
export function readDeepThinkingLocation(search = globalThis.location?.search || '') {
  const params = new URLSearchParams(search);
  const openValue = clean(params.get(DEEP_THINKING_QUERY_KEYS.open)).toLowerCase();
  return {
    open: ['1', 'true', 'open'].includes(openValue),
    sessionId: clean(params.get(DEEP_THINKING_QUERY_KEYS.sessionId)),
    branchId: clean(params.get(DEEP_THINKING_QUERY_KEYS.branchId)) || 'main',
    targetIdentity: clean(params.get(DEEP_THINKING_QUERY_KEYS.targetIdentity)),
  };
}

/**
 * Update only deep-research parameters and preserve the host workbench route.
 * Opening creates one history entry; subsequent session/branch changes replace
 * that entry so Back closes the workspace in a single step.
 */
export function writeDeepThinkingLocation(next = {}, {replace = false} = {}) {
  if (typeof window === 'undefined') return '';
  const params = new URLSearchParams(window.location.search);
  const current = readDeepThinkingLocation(params.toString());
  const state = {...current, ...next, open: next.open ?? true};
  if (state.open) params.set(DEEP_THINKING_QUERY_KEYS.open, '1');
  else params.delete(DEEP_THINKING_QUERY_KEYS.open);
  for (const [field, key] of Object.entries(DEEP_THINKING_QUERY_KEYS)) {
    if (field === 'open') continue;
    const value = clean(state[field]);
    if (value && !(field === 'branchId' && value === 'main')) params.set(key, value);
    else params.delete(key);
  }
  const url = `${window.location.pathname}${params.size ? `?${params}` : ''}${window.location.hash}`;
  const historyState = {...(window.history.state || {}), deepOpen: Boolean(state.open)};
  window.history[replace ? 'replaceState' : 'pushState'](historyState, '', url);
  return url;
}

export function clearDeepThinkingLocation({replace = false} = {}) {
  return writeDeepThinkingLocation({
    open: false,
    sessionId: '',
    branchId: '',
    targetIdentity: '',
  }, {replace});
}

/**
 * Open the deep-thinking dock for one concrete equipment / research target.
 * Kept in a non-JSX module so Fast Refresh can treat panel components as a
 * pure component boundary.
 */
export function openDeepThinking(context = {}) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(OPEN_DEEP_THINKING_EVENT, {detail: context}));
}
