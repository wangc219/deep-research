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

test('S6 progress exposes the portrait viewer only from authored columns', () => {
  assert.match(panelSource, /const openS6Portrait = \(\) =>/);
  assert.match(panelSource, /item\.status === 'completed' && safeText\(item\.text\)/);
  assert.match(panelSource, /className="deep-s6-progress-actions"/);
  assert.match(panelSource, /onOpenPortrait=\{openPortrait\}/);
});

test('an incomplete portrait stays viewable but cannot be promoted as a five-column card', () => {
  assert.match(panelSource, /const portraitProgress = s6PortraitCompleteness\(portraitModules\)/);
  assert.match(panelSource, /const mergeUnavailable = rejectedVersion \|\| !portraitProgress\.complete/);
  assert.match(panelSource, /补齐五栏后可成卡/);
  assert.match(panelSource, /能力画像草稿/);
  assert.match(panelSource, /hasPortraitRecord && !hasCompletePortrait/);
  assert.match(panelSource, /能力画像待补全/);
  assert.match(panelSource, /五栏齐全后可选择成卡/);
  assert.match(panelSource, /fallbackModules=\{artifacts\.length === 1 \? currentTurnPortraitModules : \[\]\}/);
});

test('result state only uses events from the current deep-research job', () => {
  const turnEvents = panelSource.indexOf('const turnStageEvents = latestFeedbackJobId');
  const resultState = panelSource.indexOf('const resultState = deepResultState({');

  assert.ok(turnEvents >= 0, 'current-turn event projection must exist');
  assert.ok(resultState > turnEvents, 'result state must be derived after current-turn filtering');
  assert.match(
    panelSource.slice(resultState, resultState + 420),
    /stageEvents: turnStageEvents/,
    'older completed S6 events must not mark the current turn complete',
  );
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

test('completed answer keeps the accumulated innovation-cabin process visible', () => {
  const visibilityStart = panelSource.indexOf('const showStreamingBubble = Boolean(');
  const visibilityEnd = panelSource.indexOf('const liveDeliberationAnswer', visibilityStart);
  const visibilitySource = panelSource.slice(visibilityStart, visibilityEnd);

  assert.ok(visibilityStart >= 0, 'streaming process visibility must be defined');
  assert.match(visibilitySource, /streamingDraft\s*&&\s*\(sending \|\| showLiveAnswer \|\| liveFeedback\.segments\.length\)/);
  assert.doesNotMatch(
    visibilitySource,
    /trailingMessages\.some/,
    'a durable final assistant message must not hide prior process feedback',
  );
  assert.match(panelSource, /本轮过程反馈记录/);
  assert.match(panelSource, /\.slice\(-320\);/);
});

test('the active processing cue stays below every feedback message', () => {
  const trailingMessages = panelSource.indexOf('{trailingMessages.map(message =>');
  const latestCue = panelSource.indexOf('className="deep-process-wait deep-process-wait-latest"');
  const endGap = panelSource.indexOf('className="deep-message-end-gap"');
  assert.ok(trailingMessages >= 0, 'trailing feedback messages must be rendered');
  assert.ok(latestCue > trailingMessages, 'the active cue must follow all current-turn feedback');
  assert.ok(endGap > latestCue, 'only the terminal scroll spacer may follow the active cue');
  assert.equal(panelSource.match(/deep-process-wait deep-process-wait-latest/g)?.length, 1);
});

test('deep conversations can switch the unified model profile per turn', () => {
  assert.match(panelSource, /className="deep-composer-model-picker"/);
  assert.match(panelSource, /className="deep-composer-shell-footer"/);
  assert.match(panelSource, /aria-label="本轮深研模型"/);
  assert.match(panelSource, /跟随任务模型/);
  assert.match(panelSource, /model_profile_id: selectedModelProfileId/);
  assert.doesNotMatch(panelSource, /模型在创建对话时固定/);
  assert.doesNotMatch(panelSource, /Boolean\(session\?\.session_id\)/);
});
