import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const panelSource = readFileSync(new URL('./DeepThinkingPanel.jsx', import.meta.url), 'utf8');

test('DeepThinkingDock calls every hook before its disabled-state return', () => {
  const dockStart = panelSource.indexOf('export function DeepThinkingDock');
  const dockSource = panelSource.slice(dockStart);
  const closeHook = dockSource.indexOf('const close = useCallback');
  const navigationHook = dockSource.indexOf('const syncNavigation = useCallback');
  const disabledReturn = dockSource.indexOf('if (!enabled || !runId) return null;');

  assert.ok(dockStart >= 0, 'DeepThinkingDock must exist');
  assert.ok(closeHook >= 0, 'close callback hook must exist');
  assert.ok(navigationHook > closeHook, 'navigation callback must follow close callback');
  assert.ok(disabledReturn > navigationHook, 'disabled return must follow all Dock hooks');
});

test('admin plugin mutation and branch fork carry their route contracts', () => {
  assert.match(
    panelSource,
    /deepScopeHeaders\(normalizedContext, \{legacyRole: 'admin'\}\)/,
    'Plugin PATCH must use the admin legacy fallback instead of analyst',
  );
  assert.match(
    panelSource,
    /'Idempotency-Key': forkRequest\.key/,
    'branch creation must send an idempotency key',
  );
});

test('workspace resource editor uses session-scoped API and idempotent admin writes', () => {
  assert.match(panelSource, /workspace\/resources/);
  assert.match(panelSource, /normalizeDeepWorkspaceResources/);
  assert.match(panelSource, /workspace-resource-save-\$\{newRequestNonce\(\)\}/);
  assert.match(panelSource, /workspace-resource-delete-\$\{newRequestNonce\(\)\}/);
  assert.match(panelSource, /deepScopeHeaders\(normalizedContext, \{legacyRole: 'admin'\}\)/);
  assert.match(panelSource, /<FileText size=\{13\}\/><b>装备工作区<\/b>/);
});

test('nested deep-thinking dialogs own the focus trap and modal state', () => {
  assert.match(panelSource, /useOverlay\(true, \{onEscape: onClose\}\)/);
  assert.match(panelSource, /useOverlay\(Boolean\(portrait\), \{onEscape: onClose\}\)/);
  assert.match(panelSource, /<input autoFocus value=\{query\}/);
  assert.match(panelSource, /className="icon-button" autoFocus aria-label="关闭能力画像"/);
  assert.match(panelSource, /aria-modal=\{nestedModalOpen \? undefined : true\}/);
});

test('memory drawer is an independent modal layered above deep thinking', () => {
  assert.match(panelSource, /const dialogRef = useOverlay\(Boolean\(open\), \{onEscape: onToggle\}\)/);
  assert.match(panelSource, /className="deep-memory-backdrop" role="presentation"/);
  assert.match(panelSource, /className="deep-context-usage-pop deep-memory-drawer" ref=\{dialogRef\} role="dialog" aria-modal="true"/);
  assert.match(panelSource, /<button type="button" autoFocus aria-label="关闭决策记忆"/);
  assert.match(panelSource, /const nestedModalOpen = Boolean\(contextUsageOpen \|\| portraitViewer \|\| capabilityDrawerOpen\)/);
});

test('terminal SSE and polling refreshes preserve the full capability version scope', () => {
  const scopedRefresh = /void loadVersions\(\s*session\?\.card_binding_id \|\| normalizedContext\.card_binding_id \|\| '',\s*session\?\.hypothesis_id \|\| normalizedContext\.hypothesis_id \|\| '',\s*session\?\.capability_id \|\| normalizedContext\.capability_id \|\| '',\s*\)/g;
  assert.equal([...panelSource.matchAll(scopedRefresh)].length, 2, 'SSE and polling terminal paths must pass binding, hypothesis, and capability IDs');
  assert.match(panelSource, /session\?\.card_binding_id, session\?\.capability_id, session\?\.hypothesis_id, session\?\.session_id, streamEpoch/);
  assert.match(panelSource, /session\?\.card_binding_id, session\?\.capability_id, session\?\.hypothesis_id, session\?\.session_id\]\);/);
});

test('research activity is dynamic and quality assessment stays non-blocking', () => {
  assert.match(panelSource, /projectDeepActivityRoster\(events, \{sending\}\)/);
  assert.match(panelSource, /research_assessment/);
  assert.match(panelSource, /research_complete/);
  assert.match(panelSource, /research_gaps/);
  assert.match(panelSource, /当前研究前沿/);
  assert.match(panelSource, /关键假设变化/);
  assert.match(panelSource, /已探索视角/);
  assert.match(panelSource, /下一轮可补充/);
  assert.match(panelSource, /上轮研究策略/);
  assert.match(panelSource, /terminalFailure && !legacyQualityOnlyBlock/);
  assert.doesNotMatch(panelSource, /const PROCESS_AGENTS =/);
  assert.doesNotMatch(panelSource, /未过发布门/);
  assert.doesNotMatch(panelSource, /不再重开三席发散/);
});
