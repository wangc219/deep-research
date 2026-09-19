import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {Activity, AlignLeft, Archive, ArrowUp, BarChart3, BookOpenCheck, Bot, BrainCircuit, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, ClipboardCheck, Clock3, Command, Copy, CornerDownLeft, Database, Download, Eye, FileCheck2, FileSpreadsheet, FlaskConical, Gauge, GitCompare, History, Keyboard, Layers3, Lightbulb, ListFilter, MessageSquare, Pencil, Play, Plus, Printer, RefreshCw, Save, Search, Send, ShieldAlert, ShieldCheck, Sparkles, Star, Trash2, Upload, Wrench, X, Zap} from 'lucide-react';
import './styles.css';
import './responsive-nav.css';
import './live.css';
import './blueprint.css';
import './agent-selection.css';
import './research-launch.css';
// Loaded last: shared design tokens plus the polish layer that harmonises the
// chrome above (focus rings, motion, status pills, scrollbars).
import './theme.css';
import {FRONTEND_FEATURE_FLAGS, isFrontendFeatureEnabled} from './feature-flags.js';
import {searchQueryItems} from './query-search.js';
import {ErrorBoundary, Skeleton, ToastHost, clearPersisted, copyWithToast, downloadText, notify, relativeTime, useOverlay, usePersistentDraft, usePersistentState} from './ux.jsx';
import {DeepThinkingDock} from './features/deep-thinking/DeepThinkingPanel.jsx';
import {openDeepThinking} from './features/deep-thinking/open-deep-thinking.js';

if (FRONTEND_FEATURE_FLAGS.benchmark) void import('./benchmark.css');

// The default API stays alongside the application, including when it is deployed below '/'.
const api = (import.meta.env.VITE_API_BASE_URL || `${import.meta.env.BASE_URL}api/v1`).replace(/\/$/, '');
const DEFAULT_EXECUTION_PROFILE_ID = 'winning_swarm_dynamic_v2';
const RUN_PAGE_SIZE = 12;
const COMPOSER_QUERY_DRAFT_KEY = 'composer.query';
const COMPOSER_SUPPLEMENT_DRAFT_KEY = 'composer.supplement';
const extensionModules = import.meta.glob('./features/*/index.jsx', {eager: true});
const workbenchExtensions = Object.values(extensionModules)
  .map(module => module.default)
  .filter(extension => extension?.id && extension?.Component && isFrontendFeatureEnabled(extension.id));
const SHOW_BENCHMARK_EVOLUTION = false;
const SELECTABLE_BUSINESS_AGENT_IDS = new Set(['combat_scenario', 'international_situation', 'operational_employment', 'opponent_monitoring', 'system_confrontation', 'weapon_equipment']);
const DISCOVERY_AGENT_IDS = new Set([...SELECTABLE_BUSINESS_AGENT_IDS, 'case_research', 'technology_radar', 'cross_domain_fusion', 'nontraditional_security']);
const ACTIVE_RUN_STATUSES = new Set(['queued', 'planning', 'researching', 'recalling', 'synthesizing', 'reviewing', 'reporting', 'pause_requested', 'cancel_requested']);
const businessAgents = catalog => (catalog?.agents || []).filter(agent => SELECTABLE_BUSINESS_AGENT_IDS.has(agent.agent_id));
const runtimeHandlesRun = (run, runtime = {}) => (runtime.active_run_ids || []).includes(run.run_id) || (runtime.workers || []).some(worker => worker.online && worker.current_run_id === run.run_id);
const isRunActive = (run, runtime = {}) => ACTIVE_RUN_STATUSES.has(run?.status) || runtimeHandlesRun(run || {}, runtime);
const S_AGENT_ARCHITECTURE = [
  {step: 1, agent_id: 'winning_s1_opponent', name: '对手分析 Agent', task: '深度挖掘对手体系薄弱环节、关键依赖与替代假设。', skills: ['defense_decomposition', 'ooda_vulnerability_analysis'], harness: 'winning_step_v1', semantics: ['可与 S2 并行', '可跳步', '可回溯']},
  {step: 2, agent_id: 'winning_s2_operations', name: '作战运用审查 Agent', task: '审视我方现有战法、任务链、协同关系与失败模式。', skills: ['winning_path_analysis', 'doctrine_operational_review'], harness: 'winning_step_v1', semantics: ['可与 S1 并行', '可跳步', '可回溯']},
  {step: 3, agent_id: 'winning_s3_breakthrough', name: '突破口思考 Agent', task: '生成潜在突破方向，以反事实与效果链验证机会线索。', skills: ['effect_chain_analysis', 'counterfactual_triz_innovation'], harness: 'winning_step_v1', semantics: ['多输入汇聚', '可并行推演', '可回溯']},
  {step: 4, agent_id: 'winning_s4_capability', name: '装备能力映射 Agent', task: '把战法与任务效果映射为装备能力、功能、性能和体系接口。', skills: ['capability_mapping', 'dotmlpf_capability_mapping'], harness: 'winning_step_v1', semantics: ['可与 S5 迭代', '可并行展开', '可回溯']},
  {step: 5, agent_id: 'winning_s5_gap', name: '创新颠覆候选组合评审 Agent', task: '先在同一制胜维度内按综合评分择优，再跨维度覆盖互异关系；最多保留 7 个，不足时不凑数。', skills: ['gap_quantification', 'equipment_system_gap_assessment'], harness: 'winning_step_v1', semantics: ['同维度择优', '跨维度覆盖', '名称冻结']},
  {step: 6, agent_id: 'winning_s6_image', name: '能力图像综合 Agent', task: '融合差距与前序认识，排序形成装备能力需求图像。', skills: ['capability_image_generation', 'capability_portfolio_synthesis'], harness: 'winning_step_v1', semantics: ['收敛输出', '保留冲突', '可回溯']},
];
const S5_SCORE_DIMENSIONS = [
  {key: 'innovation', label: '创新性', weight: .3},
  {key: 'demand', label: '需求性', weight: .3},
  {key: 'feasibility', label: '科学可行性', weight: .2},
  {key: 'effectiveness', label: '效能性', weight: .1},
  {key: 'development', label: '发展性', weight: .1},
];
const normalizedS5Scores = value => Object.fromEntries(S5_SCORE_DIMENSIONS.flatMap(({key}) => {
  const score = Number(value?.[key]);
  return Number.isFinite(score) ? [[key, Math.max(0, Math.min(1, score))]] : [];
}));
const portfolioS5Scores = item => {
  const scores = normalizedS5Scores(item?.s5_dimension_scores);
  const text = String(item?.innovation_basis || item?.score_basis || '');
  const aliases = {innovation: '创新性', demand: '需求性', feasibility: '科学可行性', effectiveness: '效能性', development: '发展性'};
  for (const [key, label] of Object.entries(aliases)) {
    if (Number.isFinite(scores[key])) continue;
    const match = text.match(new RegExp(`${label}\\s*[=:：]\\s*(0(?:\\.\\d+)?|1(?:\\.0+)?)`, 'i'));
    if (match) scores[key] = Math.max(0, Math.min(1, Number(match[1])));
  }
  return scores;
};
const weightedS5Score = value => {
  const scores = normalizedS5Scores(value);
  if (!S5_SCORE_DIMENSIONS.every(({key}) => Number.isFinite(scores[key]))) return null;
  return S5_SCORE_DIMENSIONS.reduce((total, {key, weight}) => total + scores[key] * weight, 0);
};
const LOOP_ARCHITECTURE = [
  {key: 'inner', level: 'L1', name: '步骤门控', description: '优先执行本地确定性检查；仅证据、必填结构或军事作用机理存在实质缺口时局部修复。'},
  {key: 'middle', level: 'L2', name: '因果复核', description: '仅在跨步骤断链或高风险矛盾时触发模型复核，并只重跑受影响的 S Agent。'},
  {key: 'outer', level: 'L3', name: '残差回溯', description: '只对会改变能力结论的证据残差定向补强，不因一般覆盖标签不足重跑全链。'},
  {key: 'meta', level: 'L4', name: '元循环', description: '调整 A–H 蓝图、S Agent 强度与动态专用 Agent，保持有界重规划。'},
];
const nav = [
  ['runs', '研究任务', Archive], ['capabilities', '能力图像', FlaskConical],
  ['favorites', '收藏', Star],
  ['reports', '研究报告', FileCheck2],
  ...(FRONTEND_FEATURE_FLAGS.benchmark ? [['benchmark', '测试 Benchmark', Gauge]] : []),
  ...workbenchExtensions.map(extension => [extension.id, extension.label, extension.icon]),
];
const TASK_WORKSPACE_VIEWS = ['capabilities', 'reports'];
const TASK_ARTIFACT_VIEWS = ['interactions', 'evidence', 'winning'];
const FAVORITE_SCOPE_GLOBAL = 'global';
const FAVORITE_SCOPE_PRIVATE = 'private';
const FAVORITE_PAGE_SIZE = 12;
const FAVORITE_MODULE_KEYS = ['overview', 'technology_implementation', 'operational_process', 'capability_effects', 'winning_logic'];
const FAVORITE_META_STORAGE_KEY = 'equipment-dr.favorite-meta.v1';
const readFavoriteMeta = () => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(FAVORITE_META_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter(([, value]) => value && typeof value === 'object').map(([key, value]) => [String(key), {
      displayName: String(value.displayName || '').slice(0, 160),
      note: String(value.note || '').slice(0, 1200),
    }]));
  } catch (_error) {
    return {};
  }
};
const writeFavoriteMeta = value => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(FAVORITE_META_STORAGE_KEY, JSON.stringify(value || {}));
  } catch (_error) { /* Private browsing or quota limits should not block CRUD. */ }
};
// Run IDs come from persisted task/artifact directories and are opaque. Keep
// them encoded whenever they are interpolated into an API path so punctuation
// in a legacy ID cannot change the route being requested.
const runApiPath = (runId, suffix = '') => `/runs/${encodeURIComponent(String(runId ?? '').trim())}${suffix}`;
const deepScopeHeadersForRun = run => {
  const scope = run?.scope && typeof run.scope === 'object' ? run.scope : run || {};
  const headers = {'X-Role': 'analyst'};
  for (const [field, header] of [['tenant_id', 'X-Tenant-ID'], ['workspace_id', 'X-Workspace-ID'], ['project_id', 'X-Project-ID'], ['profile_id', 'X-Profile-ID']]) {
    const value = String(scope[field] ?? '').trim();
    if (value) headers[header] = value;
  }
  const stages = Array.isArray(scope.stage_scope) ? scope.stage_scope.filter(Boolean).join(',') : String(scope.stage_scope ?? '').trim();
  if (stages) headers['X-Evolution-Stage-Scope'] = stages;
  return headers;
};
const normalizeFavoriteText = value => String(value ?? '').normalize('NFKC').replace(/\s+/g, ' ').trim().toLocaleLowerCase();
// Small deterministic client fingerprint for idempotency keys.  The server
// remains authoritative (it hashes the full request payload); this keeps a
// changed Query/focus from colliding with a previous reference-research
// attempt while avoiding long/unescaped candidate names in HTTP headers.
const stableClientHash = value => {
  const source = String(value ?? '');
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
};
const favoriteCardKey = row => {
  const source = row && typeof row === 'object' ? row : {};
  // Keep this fallback identical to the API's uniqueness fence: stable card
  // binding/capability IDs win, then normalized name + classification.  The
  for (const field of ['card_binding_id', 'card_id', 'capability_id']) {
    const explicit = normalizeFavoriteText(source[field]);
    if (explicit) return explicit;
  }
  // A server-projected key is useful for legacy snapshots that have no
  // binding/capability identifier; it is only consulted after strong IDs.
  const serverKey = normalizeFavoriteText(source.card_key);
  if (serverKey) return serverKey;
  const classification = source.capability_classification || {};
  const primary = normalizeFavoriteText(classification.primary_dimension || classification.primary || '');
  const secondary = classification.secondary_dimensions || classification.secondary || '';
  const secondaryValues = Array.isArray(secondary) ? secondary : [secondary];
  const dimensions = [primary, ...secondaryValues.map(normalizeFavoriteText)].filter(Boolean).join('+');
  return [normalizeFavoriteText(source.name || source.title), dimensions].filter(Boolean).join('|');
};
const favoriteIndexKey = (runId, row) => `${String(runId || row?.run_id || '').trim()}::${favoriteCardKey(row)}`;
const favoriteSnapshot = favorite => {
  if (!favorite || typeof favorite !== 'object') return {};
  const raw = favorite.snapshot ?? favorite.snapshot_json ?? favorite.card ?? favorite.capability ?? null;
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) return raw;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch (_error) { /* Preserve the flattened favorite when legacy JSON is malformed. */ }
  }
  return favorite;
};
const favoriteRunId = favorite => {
  const snapshot = favoriteSnapshot(favorite);
  return String(favorite?.run_id || favorite?.source_run_id || snapshot.run_id || '').trim();
};
const favoriteKeyFromItem = favorite => {
  const snapshot = favoriteSnapshot(favorite);
  // Reuse the same precedence and normalization as capability rows.  A
  // favorite response may expose a canonical `card_key` while its snapshot
  // still carries the original-cased binding ID; indexing the latter would
  // make an already-saved star look absent after a reload.
  return favoriteCardKey({
    ...snapshot,
    card_key: favorite?.card_key || snapshot.card_key || '',
    card_binding_id: favorite?.card_binding_id || snapshot.card_binding_id || '',
    card_id: favorite?.card_id || snapshot.card_id || '',
    capability_id: favorite?.capability_id || snapshot.capability_id || '',
  });
};
const favoriteRowsFromPayload = payload => {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== 'object') return [];
  return [payload.items, payload.favorites, payload.results, payload.rows].find(Array.isArray) || [];
};
const favoriteBoolean = value => typeof value === 'boolean' ? value : ['1', 'true', 'yes', 'y', 'on', '是', '有'].includes(String(value ?? '').trim().toLocaleLowerCase());
const capabilityPortraitIsComplete = row => {
  const source = row && typeof row === 'object' ? row : {};
  const normalized = value => normalizeFavoriteText(value);
  const authoringStatuses = ['portrait_authoring_status', 's6_authoring_status'].map(field => normalized(source[field])).filter(Boolean);
  const status = String(source.portrait_authoring_status || source.s6_authoring_status || '').trim();
  const normalizedStatus = normalized(status);
  if (['is_reference', 'reference_only', 'is_reference_equipment', 'reference_candidate'].some(field => favoriteBoolean(source[field]))) return false;
  if (['s6_authoring_failed', 'authoring_failed', 'is_temporary', 'is_provisional', 'pending_authoring'].some(field => favoriteBoolean(source[field]))) return false;
  const provenance = ['analysis_provenance_status', 'provenance_status', 'selection_status'].map(field => normalized(source[field])).filter(Boolean);
  const types = ['capability_type', 'type', 'kind', 'card_type'].map(field => normalized(source[field])).filter(Boolean);
  const referenceOrTemporary = [...types, ...provenance].some(value => ['reference', 'reference_equipment', 'reference_candidate', 's5', 'temporary', 'provisional'].includes(value) || /(?:^|[_\-\s])(reference|temporary|provisional|s5)(?:$|[_\-\s])/.test(value) || ['参考', '临时', '待成稿'].some(marker => value.includes(marker)));
  if (referenceOrTemporary) return false;
  const disallowedStatus = value => {
    if (!value) return false;
    if (value === 'authored_quality_limited' || (value === 'limited_quality' && normalizedStatus === 'authored_quality_limited')) return false;
    const negativeMarkers = 's5|fallback|limited|pending|provisional|failed|failure|error|rejected|cancelled|canceled|draft|incomplete|unfinished';
    const tokenized = value.replace(/[_\-\s]+/g, '_').replace(new RegExp(`(?:^|_)(?:not|no|non)_(?:${negativeMarkers})(?=_|$)`, 'g'), '_').replace(/^_+|_+$/g, '');
    const rejectedTokens = new Set(['s5', 'fallback', 'limited', 'pending', 'provisional', 'failed', 'failure', 'error', 'rejected', 'cancelled', 'canceled', 'draft', 'incomplete', 'unfinished']);
    return tokenized.split('_').some(token => rejectedTokens.has(token)) || ['回退', '受限', '失败', '错误', '拒绝', '驳回', '取消', '待核验', '待验证', '待审核', '审核中', '未核验', '未验证', '待校准', '待成稿', '临时', '参考', '未完成', '未成稿', '草稿'].some(marker => value.includes(marker));
  };
  if ([...authoringStatuses, ...provenance, ...types].some(disallowedStatus)) return false;
  if (['pending', 'unverified', 'rejected', '待核验', '待验证'].includes(normalized(source.verification_status)) || disallowedStatus(normalized(source.verification_status)) || favoriteBoolean(source.confidence_limited)) return false;
  const modules = source.capability_portrait_modules;
  const hasModules = modules && typeof modules === 'object' && FAVORITE_MODULE_KEYS.every(key => String(modules[key] || '').trim());
  const portrait = String(source.deep_capability_portrait || source.capability_image || '').trim();
  if (hasModules) return true;
  const legacyCompatible = !status || ['legacy_v1', 'legacy_derived', 'structured_unspecified'].includes(normalizedStatus);
  if (!portrait || !(normalizedStatus.startsWith('s6_authored') || normalizedStatus === 'authored_semantically_consistent' || normalizedStatus === 'authored_quality_limited' || legacyCompatible)) return false;
  // Legacy cards may only have the labeled portrait string. Require all five
  // sections before enabling the star so the UI boundary matches the API.
  const parsed = typeof parseCapabilityPortrait === 'function' ? parseCapabilityPortrait(portrait) : null;
  const parsedLabels = new Set((parsed?.points || []).map(item => item.label));
  return Boolean(parsed?.overview && ['装备与技术实现', '关键作战流程', '形成能力与作战效果'].every(label => parsedLabels.has(label)) && (parsedLabels.has('制胜逻辑机理') || parsedLabels.has('制胜逻辑')));
};
const readNavigationState = () => {
  const params = new URLSearchParams(window.location.search);
  const requestedView = params.get('view') || 'runs';
  return {
    view: nav.some(([id]) => id === requestedView) || requestedView === 'query-library' ? requestedView : 'runs',
    runId: params.get('run') || '',
    scope: params.get('scope') || FAVORITE_SCOPE_GLOBAL,
    cap: params.get('cap') || '',
  };
};
const LLM_PRESETS = {
  openai: {label: 'GPT / OpenAI', api_protocol: 'responses', base_url: 'https://api.openai.com/v1', model: 'gpt-5.5'},
  deepseek: {label: 'DeepSeek', api_protocol: 'chat_completions', base_url: 'https://api.deepseek.com', model: 'deepseek-chat'},
  zhipu: {label: '智谱 GLM', api_protocol: 'chat_completions', base_url: 'https://yunwu.ai/v1', model: 'glm-5.2'},
  custom: {label: '自定义中转站', api_protocol: 'chat_completions', base_url: '', model: ''},
};
const COMMAND_KEY_LABEL = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || '') ? '⌘' : 'Ctrl';
const OVERLAY_SELECTOR = '.drawer-backdrop, .command-palette-backdrop, .shortcut-sheet-backdrop';
const isTypingTarget = target => Boolean(target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)));
const shuffleRecommendations = items => {
  const rows = [...items];
  for (let index = rows.length - 1; index > 0; index -= 1) {
    const target = Math.floor(Math.random() * (index + 1));
    [rows[index], rows[target]] = [rows[target], rows[index]];
  }
  return rows;
};
function App() {
  const initialNavigation = useMemo(() => readNavigationState(), []);
  const [view, setView] = useState(initialNavigation.view);
  const [favoriteScope, setFavoriteScope] = useState(initialNavigation.scope === FAVORITE_SCOPE_PRIVATE ? FAVORITE_SCOPE_PRIVATE : FAVORITE_SCOPE_GLOBAL);
  const [focusCardKey, setFocusCardKey] = useState(initialNavigation.cap || '');
  const [runs, setRuns] = useState([]);
  const [runTotal, setRunTotal] = useState(0);
  const [runStatusCounts, setRunStatusCounts] = useState({});
  const [hasMoreRuns, setHasMoreRuns] = useState(false);
  const [catalog, setCatalog] = useState({routes: [], agents: [], interaction_modes: [], discovery_branches: [], execution_profiles: [], report_templates: [], provider: {}});
  const [pendingQuery, setPendingQuery] = useState(null);
  const [selected, setSelected] = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const [healthy, setHealthy] = useState(false);
  const [enabledExtensionIds, setEnabledExtensionIds] = useState([]);
  const [runtime, setRuntime] = useState({worker_online: false, pending_count: 0, workers: [], worker_capacity: 0, configured_worker_capacity: 1, active_count: 0, available_slots: 0, active_run_ids: []});
  // `loaded` separates "no tasks" from "not fetched yet"; before it flips the
  // list shows placeholders instead of claiming the workspace is empty.
  const [loaded, setLoaded] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  // Favorites are deliberately indexed at the app boundary so capability
  // cards rendered in the task workspace and report fallback share one
  // authoritative optimistic state.  The API remains the source of truth;
  // this index only avoids duplicate per-card reads.
  const [favoriteIndex, setFavoriteIndex] = useState({});
  const [favoritesLoaded, setFavoritesLoaded] = useState(false);
  const favoriteIndexRef = useRef({});
  const favoriteRequestsRef = useRef(new Map());
  const loadInFlightRef = useRef(null);
  const loadMoreInFlightRef = useRef(null);
  const runOffsetRef = useRef(0);
  const hasMoreRunsRef = useRef(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedView = params.get('view');
    if ((requestedView === 'benchmark' && !FRONTEND_FEATURE_FLAGS.benchmark)
      || (requestedView === 'ablation' && !FRONTEND_FEATURE_FLAGS.ablation)) {
      params.delete('view');
      params.delete('run');
      params.delete('scope');
      params.delete('cap');
      window.history.replaceState({view: 'runs', runId: ''}, '', `${params.size ? `?${params}` : ''}${window.location.hash}`);
    }
  }, []);
  const navigate = (nextView, options = {}) => {
    const nextRun = options.run === undefined ? activeRun : options.run;
    const params = new URLSearchParams(window.location.search);
    if (nextView === 'runs') params.delete('view'); else params.set('view', nextView);
    if (nextRun?.run_id && (TASK_WORKSPACE_VIEWS.includes(nextView) || TASK_ARTIFACT_VIEWS.includes(nextView))) params.set('run', nextRun.run_id); else params.delete('run');
    if (nextView === 'favorites') {
      params.set('scope', options.scope || params.get('scope') || FAVORITE_SCOPE_GLOBAL);
      params.delete('cap');
      params.delete('run');
    } else if (nextView === 'capabilities') {
      params.delete('scope');
      if (options.cap !== undefined) {
        if (options.cap) params.set('cap', options.cap); else params.delete('cap');
      }
    } else {
      params.delete('scope');
      params.delete('cap');
    }
    const nextUrl = `${params.size ? `?${params}` : ''}${window.location.hash}`;
    window.history[options.replace ? 'replaceState' : 'pushState']({view:nextView, runId:nextRun?.run_id || '', scope: params.get('scope') || FAVORITE_SCOPE_GLOBAL, cap: params.get('cap') || ''}, '', nextUrl);
    setView(nextView);
    setFavoriteScope(nextView === 'favorites' && (options.scope || params.get('scope')) === FAVORITE_SCOPE_PRIVATE ? FAVORITE_SCOPE_PRIVATE : FAVORITE_SCOPE_GLOBAL);
    setFocusCardKey(nextView === 'capabilities' ? (options.cap || params.get('cap') || '') : '');
    if (options.run !== undefined) { setActiveRun(nextRun || null); setSelected(null); }
    if (options.scroll !== false) window.scrollTo({top:0, behavior: options.instant ? 'auto' : 'smooth'});
  };
  const syncFavoriteIndex = async () => {
    // The API caps a page at 200 rows. Walk all pages so the app-wide index
    // remains correct even after a workspace grows beyond that limit.
    const rows = [];
    let offset = 0;
    while (true) {
      const result = await requestResult(`/favorites?scope=global&limit=200&offset=${offset}`, {headers: {'X-Role': 'analyst'}});
      if (!result.ok) return false;
      const pageRows = favoriteRowsFromPayload(result.data);
      rows.push(...pageRows);
      const hasMore = Boolean(result.data?.has_more);
      if (!hasMore || !pageRows.length || rows.length >= 10000) break;
      offset += pageRows.length;
    }
    const next = {};
    rows.forEach(item => {
      const runId = favoriteRunId(item);
      const key = favoriteKeyFromItem(item);
      if (runId && key) next[`${runId}::${key}`] = item;
    });
    favoriteIndexRef.current = next;
    setFavoriteIndex(next);
    setFavoritesLoaded(true);
    return true;
  };
  const updateFavoriteIndex = (row, runId, favorite, favorited = true) => {
    const effectiveRunId = String(runId || favoriteRunId(favorite) || row?.run_id || '').trim();
    const key = favoriteCardKey(row || favoriteSnapshot(favorite));
    if (!effectiveRunId || !key) return;
    setFavoriteIndex(current => {
      const next = {...current};
      const indexKey = `${effectiveRunId}::${key}`;
      if (favorited) next[indexKey] = favorite || next[indexKey] || {run_id: effectiveRunId, card_key: key, snapshot: row};
      else delete next[indexKey];
      favoriteIndexRef.current = next;
      return next;
    });
  };
  const toggleFavorite = async (row, runId, desired) => {
    const effectiveRunId = String(runId || '').trim();
    const indexKey = favoriteIndexKey(effectiveRunId, row);
    if (!effectiveRunId || (desired && !capabilityPortraitIsComplete(row))) {
      notify('仅完整 S6 能力画像可收藏', 'error');
      return {ok: false, detail: '仅完整 S6 能力画像可收藏'};
    }
    const previous = favoriteIndexRef.current[indexKey] || null;
    const requestKey = indexKey;
    if (favoriteRequestsRef.current.has(requestKey)) return favoriteRequestsRef.current.get(requestKey);
    // Star clicks are optimistic. A failed write restores the previous
    // index entry, including a prior server favorite object.
    updateFavoriteIndex(row, effectiveRunId, desired ? (previous || {run_id: effectiveRunId, card_key: favoriteCardKey(row), snapshot: row}) : null, desired);
    const pending = (async () => {
      let result;
      if (desired) {
        result = await requestResult('/favorites', {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'},
          body: JSON.stringify({
            scope: FAVORITE_SCOPE_GLOBAL,
            run_id: effectiveRunId,
            card_key: favoriteCardKey(row),
            card_binding_id: row.card_binding_id || row.card_id || '',
            capability_id: row.capability_id || '',
          }),
        });
        if (result.ok) {
          const saved = result.data?.favorite || result.data;
          updateFavoriteIndex(row, effectiveRunId, saved && typeof saved === 'object' ? {...saved, run_id: saved.run_id || effectiveRunId, card_key: saved.card_key || favoriteCardKey(row), snapshot: saved.snapshot || saved.snapshot_json || row} : {run_id: effectiveRunId, card_key: favoriteCardKey(row), snapshot: row}, true);
        }
      } else {
        const favoriteId = previous?.favorite_id || previous?.id || row.favorite_id || '';
        if (!favoriteId) {
          // The capability endpoint may have reported `favorited` before the
          // app-wide index completed its first read. Refresh once to resolve
          // the durable id before declaring the removal impossible.
          await syncFavoriteIndex();
        }
        const resolved = favoriteIndexRef.current[indexKey];
        const resolvedId = favoriteId || resolved?.favorite_id || resolved?.id || '';
        result = resolvedId
          ? await requestResult(`/favorites/${encodeURIComponent(String(resolvedId))}`, {method: 'DELETE', headers: {'X-Role': 'analyst'}})
          : {ok: false, status: 404, detail: '未找到收藏记录'};
        if (result.ok) updateFavoriteIndex(row, effectiveRunId, null, false);
      }
      if (!result.ok) {
        updateFavoriteIndex(row, effectiveRunId, previous, Boolean(previous));
        const detail = String(result.detail || '');
        notify(result.status === 403 ? '公共收藏仅管理员可取消，请联系管理员' : detail || (desired ? '收藏失败，请稍后重试' : '取消收藏失败，请稍后重试'), 'error');
      } else if (desired) {
        notify('已加入公共收藏', 'ok');
      } else {
        notify('已取消收藏', 'ok');
      }
      return result;
    })().finally(() => favoriteRequestsRef.current.delete(requestKey));
    favoriteRequestsRef.current.set(requestKey, pending);
    return pending;
  };
  const updateFavorite = async (item, fields = {}) => {
    const favoriteId = String(item?.favorite_id || item?.id || '').trim();
    if (!favoriteId) return {ok: false, status: 404, detail: '未找到收藏记录'};
    const result = await requestResult(`/favorites/${encodeURIComponent(favoriteId)}`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'},
      body: JSON.stringify(fields),
    });
    if (result.ok) {
      const saved = result.data?.favorite || result.data;
      const snapshot = favoriteSnapshot(saved);
      const merged = {
        ...item,
        ...(saved && typeof saved === 'object' ? saved : {}),
        favorite_id: saved?.favorite_id || favoriteId,
        run_id: saved?.run_id || item.run_id,
        card_key: saved?.card_key || item.card_key || favoriteCardKey(item),
        snapshot: snapshot && typeof snapshot === 'object' && Object.keys(snapshot).length
          ? snapshot
          : item.snapshot || favoriteSnapshot(item),
      };
      updateFavoriteIndex(item, item.run_id, merged, true);
      return {...result, favorite: merged};
    }
    return result;
  };
  useEffect(() => { void syncFavoriteIndex(); }, []);
  const load = ({markSynced = true} = {}) => {
    // Polling must not overlap: an older, slower response arriving after a
    // newer one can make the UI jump backwards between snapshots.
    if (loadInFlightRef.current) return loadInFlightRef.current;
    const pending = (async () => {
      // Paint the task list as soon as its response crosses the tunnel. The
      // catalog and runtime diagnostics are independent and must not delay
      // the first useful screen.
      const page = await request(`/runs?compact=true&limit=${RUN_PAGE_SIZE}&offset=0`, {items: null});
      const runRows = Array.isArray(page?.items) ? page.items : null;
      if (runRows) {
        runOffsetRef.current = Math.max(runOffsetRef.current, runRows.length);
        hasMoreRunsRef.current = Boolean(page.has_more);
        setRunTotal(Number(page.total || runRows.length));
        setRunStatusCounts(page.status_counts || {});
        setHasMoreRuns(hasMoreRunsRef.current);
        // Refresh the newest window in place and retain pages the user already
        // loaded. This keeps polling cheap across the tunnel without making old
        // cards disappear while someone is reading them.
        setRuns(current => {
          const newestIds = new Set(runRows.map(item => item.run_id));
          const merged = [...runRows, ...current.filter(item => !newestIds.has(item.run_id))];
          // New tasks can shift every offset based page by one. Advance from the
          // number of cards currently retained so the next request continues
          // immediately after the visible prefix.
          runOffsetRef.current = merged.length;
          return merged;
        });
        setActiveRun(current => {
          const locationRunId = new URLSearchParams(window.location.search).get('run');
          const targetId = current?.run_id || locationRunId;
          const latest = rows => [...rows].sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')))[0];
          const next = targetId ? runRows.find(item => item.run_id === targetId) : latest(runRows.filter(item => item.status === 'completed')) || latest(runRows) || null;
          if (!next) return current;
          return current && current.run_id === next.run_id && current.status === next.status && current.updated_at === next.updated_at ? current : next;
        });
        const locationRunId = new URLSearchParams(window.location.search).get('run');
        if (locationRunId && !runRows.some(item => item.run_id === locationRunId)) {
          void request(runApiPath(locationRunId), null, {headers: {'X-Role': 'analyst'}}).then(detail => {
            if (!detail?.run_id) return;
            setActiveRun(current => current?.run_id ? current : detail);
          });
        }
        setSelected(current => {
          if (!current) return current;
          const next = runRows.find(item => item.run_id === current.run_id);
          return next && current.status === next.status && current.updated_at === next.updated_at ? current : next || current;
        });
      }
      setLoaded(true);
      const [config, health, runtimeHealth] = await Promise.all([
        request('/catalog', {routes: [], agents: [], interaction_modes: [], discovery_branches: [], execution_profiles: [], report_templates: [], provider: {}}), request('/health', null), request('/runtime-health', {worker_online: false, pending_count: 0, workers: [], worker_capacity: 0, configured_worker_capacity: 1, active_count: 0, available_slots: 0, active_run_ids: []}),
      ]);
      setCatalog(current => JSON.stringify(current) === JSON.stringify(config) ? current : config);
      setHealthy(health?.status === 'ok');
      setRuntime(current => JSON.stringify(current) === JSON.stringify(runtimeHealth) ? current : runtimeHealth);
      // Background polling stays visually quiet; explicit refreshes still
      // update the freshness label.
      if (markSynced && health?.status === 'ok') setLastSyncedAt(Date.now());
    })();
    loadInFlightRef.current = pending;
    return pending.finally(() => { if (loadInFlightRef.current === pending) loadInFlightRef.current = null; });
  };
  const loadMoreRuns = async () => {
    if (!hasMoreRunsRef.current) return;
    if (loadMoreInFlightRef.current) return loadMoreInFlightRef.current;
    if (loadInFlightRef.current) await loadInFlightRef.current;
    if (!hasMoreRunsRef.current) return;
    const offset = runOffsetRef.current;
    const pending = request(`/runs?compact=true&limit=${RUN_PAGE_SIZE}&offset=${offset}`, {items: null}).then(page => {
      // A tunnel timeout must not turn the end of the list into a false
      // result or reset the counters for cards already on screen.
      if (!Array.isArray(page?.items)) return;
      const rows = page.items;
      runOffsetRef.current = offset + rows.length;
      hasMoreRunsRef.current = Boolean(page?.has_more);
      setRunTotal(Number(page?.total || runOffsetRef.current));
      setRunStatusCounts(page?.status_counts || {});
      setHasMoreRuns(hasMoreRunsRef.current);
      setRuns(current => {
        const known = new Set(current.map(item => item.run_id));
        return [...current, ...rows.filter(item => !known.has(item.run_id))];
      });
    }).finally(() => { if (loadMoreInFlightRef.current === pending) loadMoreInFlightRef.current = null; });
    loadMoreInFlightRef.current = pending;
    return pending;
  };
  const removeRuns = runIds => {
    const removed = new Set(runIds || []);
    if (!removed.size) return;
    const removedLoadedCount = runs.filter(item => removed.has(item.run_id)).length;
    runOffsetRef.current = Math.max(0, runOffsetRef.current - removedLoadedCount);
    setRuns(current => {
      return current.filter(item => !removed.has(item.run_id));
    });
    setRunTotal(value => Math.max(0, value - removed.size));
  };
  // Background polling stays silent; only an explicit refresh reports progress,
  // so the toolbar spinner never flickers on its own every five seconds.
  const refresh = async () => { setSyncing(true); try { await load(); } finally { setSyncing(false); } };
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (!document.hidden) void load({markSynced: false}); }, 5000);
    const refreshWhenVisible = () => { if (!document.hidden) void load({markSynced: false}); };
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', refreshWhenVisible); };
  }, []);
  const knownRunStatusRef = useRef(null);
  useEffect(() => {
    const currentStatuses = new Map(runs.map(run => [run.run_id, run.status]));
    const previousStatuses = knownRunStatusRef.current;
    knownRunStatusRef.current = currentStatuses;
    // The first payload only seeds the baseline, otherwise a reload would
    // announce every historical task at once.
    if (!previousStatuses) return;
    runs.forEach(run => {
      const before = previousStatuses.get(run.run_id);
      if (!before || before === run.status) return;
      if (run.status === 'completed') notify(`研究完成：${run.topic}`, 'ok', 6000);
      else if (run.status === 'failed') notify(`研究失败：${run.topic}`, 'error', 6000);
    });
  }, [runs]);
  useEffect(() => {
    // Long runs are usually watched from a background tab; the count in the tab
    // title is the cheapest possible progress indicator.
    const activeRuns = runs.filter(run => isRunActive(run, runtime)).length;
    document.title = activeRuns ? `(${activeRuns} 进行中) 创新为帆 探索未至之境` : '创新为帆 探索未至之境';
  }, [runs, runtime]);
  useEffect(() => {
    // Two workbench-wide keys: the command palette and the shortcut sheet. Both
    // stay out of the way while the user is typing.
    const onKeyDown = event => {
      if ((event.metaKey || event.ctrlKey) && (event.key === 'k' || event.key === 'K')) {
        event.preventDefault();
        setShortcutsOpen(false);
        setPaletteOpen(value => !value);
        return;
      }
      if (event.key !== '?' || isTypingTarget(event.target) || document.querySelector(OVERLAY_SELECTOR)) return;
      event.preventDefault();
      setShortcutsOpen(true);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
  useEffect(() => {
    const onPopState = () => {
      const next = readNavigationState();
      setView(next.view);
      setFavoriteScope(next.scope === FAVORITE_SCOPE_PRIVATE ? FAVORITE_SCOPE_PRIVATE : FAVORITE_SCOPE_GLOBAL);
      setFocusCardKey(next.cap || '');
      setSelected(null);
      setActiveRun(current => next.runId ? runs.find(item => item.run_id === next.runId) || current : current);
      window.scrollTo({top:0});
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [runs]);
  useEffect(() => {
    let cancelled = false;
    Promise.all(workbenchExtensions.map(async extension => {
      try {
        const response = await fetch(`${api}${extension.probePath || `/${extension.id}s/overview`}`, {headers:{'X-Role':'analyst'}});
        return response.ok ? extension.id : null;
      } catch (_reason) { return null; }
    })).then(ids => { if (!cancelled) setEnabledExtensionIds(ids.filter(Boolean)); });
    return () => { cancelled = true; };
  }, []);
  const visibleNav = nav.filter(([id]) => id !== 'query-library' && (!workbenchExtensions.some(extension => extension.id === id) || enabledExtensionIds.includes(id)));
  const openRun = run => { setActiveRun(run); setSelected(run); };
  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-mark"><img src={`${import.meta.env.BASE_URL}favicon.svg`} alt=""/></div><div className="brand-copy"><b>JS装备需求挖掘</b><span>DEEP RESEARCH WORKBENCH</span></div>
      <button className="command-trigger" onClick={() => setPaletteOpen(true)} title={`打开命令面板（${COMMAND_KEY_LABEL} + K）`}><Search size={14}/><span>搜索任务、跳转视图…</span><kbd>{COMMAND_KEY_LABEL}</kbd><kbd>K</kbd></button>
      <div className={`service-state ${healthy && runtime.worker_online ? 'online' : 'offline'}`} title={runtime.worker_online ? `在线 Worker ${runtime.online_worker_count || 0} 个；可用槽位 ${runtime.available_slots || 0}；活动任务 ${(runtime.active_run_ids || []).join('、') || '无'}；排队 ${runtime.pending_count || 0} 项` : '请启动独立 research worker'}><i/>{!healthy ? 'API 未连接' : runtime.worker_online ? `并行槽位 ${runtime.active_count || 0}/${runtime.worker_capacity || 0} · 排队 ${runtime.pending_count || 0}` : 'Worker 未启动'}</div>
      <button className="topbar-help icon-button" onClick={() => setShortcutsOpen(true)} title="查看键盘快捷键（?）" aria-label="查看键盘快捷键"><Keyboard size={16}/></button>
    </header>
    <aside className="sidebar">
      <div className="sidebar-label">功能导航</div>
      <div className="sidebar-nav">{visibleNav.map(([id, label, Icon]) => <button key={id} data-view={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => navigate(id)}><span className="sidebar-icon"><Icon size={19}/></span><span className="sidebar-button-copy"><b>{label}</b></span><ChevronRight className="sidebar-chevron" size={15}/></button>)}</div>
      <div className="sidebar-note"><span className="sidebar-note-icon"><ShieldCheck size={16}/></span><span><b>可信研究环境</b><small>最小权限 · 全程审计留痕</small></span></div>
    </aside>
    <nav className="mobile-nav" aria-label="研究工作台导航">{visibleNav.map(([id, label, Icon]) => <button key={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={event => { navigate(id); event.currentTarget.scrollIntoView({behavior:'smooth', block:'nearest', inline:'center'}); }}><Icon size={16}/><span>{label}</span></button>)}</nav>
    <main><ErrorBoundary resetKey={view} fallback={(error, retry) => <WorkbenchErrorView error={error} retry={retry} home={() => { navigate('runs', {run: null}); retry(); }}/>}>{view === 'runs' ? <RunPage runs={runs} runTotal={runTotal} runStatusCounts={runStatusCounts} hasMoreRemoteRuns={hasMoreRuns} loadMoreRuns={loadMoreRuns} removeRuns={removeRuns} catalog={catalog} runtime={runtime} refresh={refresh} loaded={loaded} syncing={syncing} lastSyncedAt={lastSyncedAt} initialQuery={pendingQuery} clearInitialQuery={() => setPendingQuery(null)} openQueryLibrary={() => navigate('query-library')} open={openRun} openArtifact={(run, target) => navigate(target, {run})}/> : view === 'favorites' ? <FavoritesPage scope={favoriteScope} runs={runs} favoriteItems={Object.values(favoriteIndex)} favoriteIndex={favoriteIndex} navigate={navigate} onFavoriteToggle={toggleFavorite} onFavoriteUpdate={updateFavorite} onRefresh={syncFavoriteIndex}/> : FRONTEND_FEATURE_FLAGS.benchmark && view === 'benchmark' ? <BenchmarkPage/> : workbenchExtensions.some(extension => extension.id === view) ? React.createElement(workbenchExtensions.find(extension => extension.id === view).Component, {apiBase: api, onUseQuery: queryItem => { setPendingQuery(queryItem); navigate('runs'); }, onDirectResearch: queryItem => { setPendingQuery(queryItem); navigate('runs'); }, onBatchResearchStarted: count => { setPendingQuery(null); notify(`已批量创建并启动 ${count} 个研究任务`, 'ok'); void refresh(); }, onBack: () => navigate('runs')}) : <WorkspacePage view={view} run={activeRun} runs={runs} runTotal={runTotal} runStatusCounts={runStatusCounts} hasMoreRuns={hasMoreRuns} loadMoreRuns={loadMoreRuns} catalog={catalog} runtime={runtime} loaded={loaded} navigate={navigate} focusCardKey={focusCardKey} favoriteIndex={favoriteIndex} onFavoriteToggle={toggleFavorite} selectRun={run => navigate(view, {run, scroll:false})}/>}</ErrorBoundary></main>
    {selected && (
      <RunDrawer run={selected} catalog={catalog} close={() => setSelected(null)} inspect={target => navigate(target, {run:selected})} changed={updated => { setSelected(updated); setActiveRun(current => current?.run_id === updated.run_id ? updated : current); void load(); }}/>
    )}
    <CommandPalette open={paletteOpen} close={() => setPaletteOpen(false)} runs={runs} navItems={visibleNav} view={view} navigate={navigate} openRun={openRun} refresh={refresh} openShortcuts={() => { setPaletteOpen(false); setShortcutsOpen(true); }}/>
    <ShortcutSheet open={shortcutsOpen} close={() => setShortcutsOpen(false)}/>
    {activeRun && (TASK_WORKSPACE_VIEWS.includes(view) || TASK_ARTIFACT_VIEWS.includes(view)) && <DeepThinkingDock apiBase={api} run={activeRun} onChanged={() => { void load({markSynced: false}); }}/>}
    <BackToTop/>
    <ToastHost/>
  </div>;
}

function RunPage({runs, runTotal, runStatusCounts, hasMoreRemoteRuns, loadMoreRuns, removeRuns, catalog, runtime, refresh, loaded, syncing, lastSyncedAt, initialQuery, clearInitialQuery, openQueryLibrary, open, openArtifact}) {
  const [query, setQuery] = useState('');
  // Only the three tab values are remembered; a narrow dropdown status would
  // otherwise come back after a reload and look like an empty task list.
  const [status, setStatus] = usePersistentState('runs.status', 'all', {allowed: ['all', 'active', 'completed']});
  const pageSize = 12; const [visibleLimit, setVisibleLimit] = useState(pageSize);
  const runScrollRef = useRef(null); const loadMoreRef = useRef(null); const searchRef = useRef(null);
  const stableRunOrderRef = useRef([]);
  const [selectedIds, setSelectedIds] = useState([]); const [deleting, setDeleting] = useState(false); const [stopping, setStopping] = useState(false); const [resumingRunId, setResumingRunId] = useState(''); const [deleteError, setDeleteError] = useState('');
  const [focusRunId, setFocusRunId] = useState('');
  const matchesStatus = run => status === 'all' ? run.status !== 'archived' : status === 'active' ? isRunActive(run, runtime) : run.status === status;
  const orderedRuns = useMemo(() => {
    const currentById = new Map(runs.map(run => [run.run_id, run]));
    const retainedIds = stableRunOrderRef.current.filter(runId => currentById.has(runId));
    const retainedSet = new Set(retainedIds);
    const currentIds = runs.map(run => run.run_id);
    const firstRetainedIndex = currentIds.findIndex(runId => retainedSet.has(runId));
    const newIdsBeforeRetained = currentIds
      .slice(0, firstRetainedIndex < 0 ? currentIds.length : firstRetainedIndex)
      .filter(runId => !retainedSet.has(runId));
    const newIdsAfterRetained = currentIds
      .slice(firstRetainedIndex < 0 ? currentIds.length : firstRetainedIndex)
      .filter(runId => !retainedSet.has(runId));
    // /runs is ordered by updated_at. Active tasks refresh that timestamp
    // frequently, so blindly accepting every poll order makes cards swap
    // positions under the pointer. Keep existing cards anchored; new tasks
    // enter at the front while a page loaded by scrolling stays at the end.
    stableRunOrderRef.current = [
      ...newIdsBeforeRetained,
      ...retainedIds,
      ...newIdsAfterRetained,
    ];
    return stableRunOrderRef.current.map(runId => currentById.get(runId)).filter(Boolean);
  }, [runs]);
  const visible = orderedRuns.filter(run => (!query || `${run.topic} ${run.supplemental_information || ''} ${run.run_id}`.toLowerCase().includes(query.toLowerCase())) && matchesStatus(run));
  const pageRows = visible.slice(0, visibleLimit);
  const hasMoreVisibleRuns = pageRows.length < visible.length;
  useEffect(() => {
    setVisibleLimit(pageSize);
    if (runScrollRef.current) runScrollRef.current.scrollTop = 0;
  }, [query, status]);
  useEffect(() => {
    const onKeyDown = event => {
      // "/" jumps to this list's own search; ⌘K belongs to the command palette.
      const wantsSearch = !event.metaKey && !event.ctrlKey && !event.altKey && event.key === '/' && !isTypingTarget(event.target);
      // Open overlays own the keyboard while they are visible.
      if (!wantsSearch || !searchRef.current || document.querySelector(OVERLAY_SELECTOR)) return;
      event.preventDefault();
      searchRef.current.focus();
      searchRef.current.select();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
  useEffect(() => {
    const root = runScrollRef.current; const target = loadMoreRef.current;
    if (!root || !target || (!hasMoreVisibleRuns && !hasMoreRemoteRuns)) return undefined;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        if (hasMoreVisibleRuns) setVisibleLimit(value => Math.min(visible.length, value + pageSize));
        else void loadMoreRuns();
      }
    }, {root, rootMargin: '0px 0px 220px 0px', threshold: 0.01});
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMoreVisibleRuns, hasMoreRemoteRuns, visible.length, visibleLimit, loadMoreRuns]);
  useEffect(() => {
    if (!focusRunId || query || status !== 'all') return undefined;
    const card = runScrollRef.current?.querySelector(`[data-run-id="${CSS.escape(focusRunId)}"]`);
    if (!card) return undefined;
    card.scrollIntoView({behavior:'smooth', block:'center'});
    card.classList.add('run-card-spotlight');
    const timer = setTimeout(() => {
      card.classList.remove('run-card-spotlight');
      setFocusRunId('');
    }, 1800);
    return () => clearTimeout(timer);
  }, [focusRunId, runs, query, status, visibleLimit]);
  const focusRunCard = runId => {
    setQuery('');
    setStatus('all');
    setFocusRunId(runId);
  };
  const workerForRun = run => (runtime.workers || []).find(worker => worker.online && worker.current_run_id === run.run_id);
  const workerSlotIndex = worker => worker && worker.status !== 'internal'
    ? (runtime.workers || [])
      .filter(item => item.online && item.status !== 'internal')
      .sort((a, b) => String(a.worker_id || '').localeCompare(String(b.worker_id || '')))
      .findIndex(item => item.worker_id === worker.worker_id) + 1
    : null;
  const queuePosition = run => (runtime.pending_run_ids || []).indexOf(run.run_id) + 1;
  const deletable = visible;
  const selectedDeletable = selectedIds.filter(id => deletable.some(run => run.run_id === id));
  const currentCount = Math.max(0, Number(runTotal || runs.length) - Number(runStatusCounts.archived || 0));
  const completed = Number(runStatusCounts.completed ?? runs.filter(run => run.status === 'completed').length);
  const activeCount = [...ACTIVE_RUN_STATUSES].reduce((total, value) => total + Number(runStatusCounts[value] || 0), 0) || runs.filter(run => isRunActive(run, runtime)).length;
  const toggleSelected = id => setSelectedIds(rows => rows.includes(id) ? rows.filter(item => item !== id) : [...rows, id]);
  const deleteRuns = async ids => {
    if (!ids.length || !window.confirm(`确定永久删除 ${ids.length} 个任务吗？运行中的任务将先停止并终止全部 Agent 进程；任务数据和产物不可恢复。`)) return;
    setDeleting(true); setDeleteError('');
    const result = await request('/runs/permanent-delete', null, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({run_ids: ids})});
    setDeleting(false);
    if (!result) { setDeleteError('永久删除失败，请检查 API 服务后重试。'); notify('永久删除失败，请检查 API 服务。', 'error'); return; }
    setSelectedIds(rows => rows.filter(id => !result.deleted.includes(id)));
    removeRuns(result.deleted || []);
    if (result.rejected?.length) setDeleteError(result.rejected.map(item => `${item.run_id}：${item.reason}`).join('；'));
    if (result.deleted?.length) notify(`已永久删除 ${result.deleted.length} 个研究任务`, 'ok');
    void refresh();
  };
  const stopRun = async run => {
    if (!run || !isRunActive(run, runtime) || !window.confirm(`确定停止研究任务“${run.topic}”吗？将终止该任务启动的所有 Agent 进程。`)) return;
    setStopping(true); setDeleteError('');
    const result = await requestResult(runApiPath(run.run_id, '/stop'), {method: 'POST', headers: {'Idempotency-Key': `stop:${run.run_id}`, 'X-Role': 'analyst'}});
    setStopping(false);
    if (!result.ok) { setDeleteError(`停止任务失败：${result.detail || '请检查 Worker 状态。'}`); notify('停止任务失败，请检查 Worker 状态。', 'error'); return; }
    notify(`已请求停止：${run.topic}`, 'info');
    await refresh();
  };
  const resumeRun = async run => {
    if (!run || run.status !== 'failed' || resumingRunId) return;
    setResumingRunId(run.run_id); setDeleteError('');
    const result = await requestResult(runApiPath(run.run_id, '/resume'), {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID(), 'X-Role': 'analyst'}});
    setResumingRunId('');
    if (!result.ok) { setDeleteError(`断点恢复失败：${result.detail || '请检查 Worker 与模型配置。'}`); notify('断点恢复失败，请检查 Worker 状态。', 'error'); return; }
    notify(`已从断点继续：${run.topic}`, 'ok');
    await refresh();
  };
  const renderInlineBuilder = (queryItem, executionProfileId, onExecutionProfileChange, modelProfileId, startRequestId, onSubmitStateChange) => <CreateRun inline catalog={catalog} runtime={runtime} initialQuery={queryItem} executionProfileId={executionProfileId} onExecutionProfileChange={onExecutionProfileChange} modelProfileId={modelProfileId} startRequestId={startRequestId} onSubmitStateChange={onSubmitStateChange} openQueryLibrary={openQueryLibrary} done={(run, started) => { clearInitialQuery(); clearPersisted(COMPOSER_QUERY_DRAFT_KEY); clearPersisted(COMPOSER_SUPPLEMENT_DRAFT_KEY); void refresh(); notify(started ? `研究任务已启动：${run.topic}` : '研究草稿已创建', 'ok'); started ? focusRunCard(run.run_id) : open(run); }}/>;
  return <>
    <ResearchQueryEntry catalog={catalog} runtime={runtime} openQueryLibrary={openQueryLibrary} initialQuery={initialQuery} renderInlineBuilder={renderInlineBuilder}/>
    <PageTitle eyebrow="RESEARCH WORKSPACE" title="研究任务与运行记录" subtitle="Query 审核后可直接带入研究任务；运行过程、证据、能力画像和报告持续留痕。">
      <span className="sync-state">{!loaded ? '正在同步数据…' : lastSyncedAt ? `数据已同步 · ${relativeTime(lastSyncedAt)}` : 'API 未连接 · 数据可能不完整'}</span>
      <button className="icon-button" title="刷新任务" disabled={syncing} onClick={refresh}><RefreshCw className={syncing ? 'spin' : ''} size={17}/></button>
    </PageTitle>
    {!runtime.worker_online && <section className="worker-warning"><CircleAlert size={18}/><div><b>研究 Worker 未在线</b><span>任务无法执行。请运行 <code>./scripts/start-local.sh</code> 或启动 Compose 服务。</span></div></section>}
    {runtime.worker_online && <ParallelRuntimePanel runtime={runtime} runs={runs} onCapacityChanged={refresh}/>}
    <WorkspacePulse runs={runs} runtime={runtime} runStatusCounts={runStatusCounts} onView={openQueryLibrary}/>
    {deleteError && <p className="form-error"><CircleAlert size={15}/>{deleteError}</p>}
    <section className="research-run-center">
      <div className="research-run-toolbar">
        <div className="run-status-tabs" aria-label="研究任务状态筛选">
          <button className={status === 'all' ? 'active' : ''} onClick={() => setStatus('all')}><Archive size={15}/>全部 <em>{currentCount}</em></button>
          <button className={status === 'active' ? 'active' : ''} onClick={() => setStatus('active')}><Clock3 size={15}/>进行中 <em>{activeCount}</em></button>
          <button className={status === 'completed' ? 'active' : ''} onClick={() => setStatus('completed')}><CheckCircle2 size={15}/>已完成 <em>{completed}</em></button>
        </div>
        <button className="run-refresh-button" disabled={syncing} onClick={refresh}><RefreshCw className={syncing ? 'spin' : ''} size={15}/>{syncing ? '同步中' : '刷新'}</button>
      </div>
      <div className="run-live-note"><Zap size={15}/><b>实时</b><span>多智能体编排器每次运行都会沉淀报告、证据与可追溯的执行轨迹。</span></div>
      <div className="run-search-row">
        <div className="searchbox"><Search size={16}/><input ref={searchRef} value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索研究主题或运行 ID（按 / 聚焦）"/>{query && <button className="searchbox-clear" type="button" title="清空搜索" aria-label="清空搜索" onClick={() => { setQuery(''); searchRef.current?.focus(); }}><X size={13}/></button>}</div>
        <label className="filter-select"><ListFilter size={15}/><select value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部当前任务</option><option value="active">全部进行中</option><option value="draft">草稿</option><option value="queued">已排队</option><option value="researching">研究中</option><option value="recalling">再调中</option><option value="synthesizing">S1–S6 / 综合中</option><option value="reviewing">审计中</option><option value="reporting">报告生成中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="archived">已归档</option></select></label>
        {selectedDeletable.length > 0 && <button className="danger" disabled={deleting || stopping} onClick={() => deleteRuns(selectedDeletable)}><Trash2 size={15}/>{deleting ? '删除中' : `永久删除 (${selectedDeletable.length})`}</button>}
        {selectedIds.length > 0 && <button type="button" disabled={deleting || stopping} onClick={() => setSelectedIds([])}><X size={14}/>清除选择</button>}
        <span>{visible.length} 项结果</span>
      </div>
      {!loaded && !runs.length ? <div className="research-run-grid skeleton-grid" aria-hidden="true">{[0, 1, 2, 3, 4, 5].map(index => <RunCardSkeleton key={index}/>)}</div> : visible.length === 0 ? <Empty text={query || status !== 'all' ? '当前已加载任务中没有符合条件的结果' : '暂无研究任务。在页面顶部输入 Query 即可启动第一次研究。'}>
        {(query || status !== 'all') && <button type="button" onClick={() => { setQuery(''); setStatus('all'); }}><X size={14}/>清除筛选条件</button>}
        {hasMoreRemoteRuns && <button type="button" onClick={() => void loadMoreRuns()}><RefreshCw size={14}/>加载更早任务</button>}
      </Empty> : <div className="research-run-scroll" ref={runScrollRef} aria-label="研究任务连续滚动列表"><div className="research-run-grid">{pageRows.map(run => {
        const assignedWorker = workerForRun(run); const position = queuePosition(run); const orphanedActive = isRunActive(run, runtime) && !assignedWorker && !['queued', 'pause_requested', 'cancel_requested'].includes(run.status); const displayStatus = orphanedActive && position > 0 ? 'queued' : run.status;
        const artifactCounts = run.artifact_counts || {}; const sourceCount = Number(artifactCounts.sources || run.result?.source_count || 0); const evidenceCount = Number(artifactCounts.evidence || run.result?.evidence_count || 0); const candidateCount = Number(artifactCounts.capabilities || run.result?.capability_count || 0); const winningStepCount = Number(artifactCounts.winning_steps || run.result?.stage_count || 0); const reportCount = Number(artifactCounts.reports || (run.result?.report_available ? 1 : 0));
        const runtimeText = assignedWorker ? assignedWorker.status === 'internal' ? `S6 内部并行 · ${assignedWorker.worker_id}` : `槽位 #${workerSlotIndex(assignedWorker) || '?'} · ${assignedWorker.worker_id}` : position > 0 ? `队列第 ${position} 位` : orphanedActive ? '执行已中断，等待人工断点恢复' : run.status === 'draft' ? '等待启动' : formatRunUpdatedAt(run.updated_at);
        return <article className={`research-run-card ${displayStatus}`} data-run-id={run.run_id} key={run.run_id}>
          <div className="run-card-heading"><label className="run-card-select" title="选择任务"><input type="checkbox" aria-label={`选择 ${run.topic}`} checked={selectedIds.includes(run.run_id)} onChange={() => toggleSelected(run.run_id)}/></label><button className="run-card-title" onClick={() => open(run)}><b>{run.topic}</b><small>{run.supplemental_information || run.run_id}</small></button><Status value={displayStatus}/></div>
          <div className="run-card-counts" aria-label="研究产物数量"><span><b>{sourceCount}</b> 信源</span><span><b>{evidenceCount}</b> 证据</span><span><b>{candidateCount}</b> 能力图像</span><span><b>{winningStepCount}</b> S1–S6</span><span><b>{reportCount}</b> 报告</span></div>
          {run.status === 'completed' && <button type="button" className="run-card-capability-preview" onClick={() => openArtifact(run, 'capabilities')}><span className="run-card-capability-icon"><FlaskConical size={14}/></span><span className="run-card-capability-copy"><b>能力图像 <em>{candidateCount}</em></b><small>点击查看完整能力画像与论证</small></span><ChevronRight size={14}/></button>}
          <div className="run-card-artifacts" aria-label="研究产物快捷入口">
            <button type="button" onClick={() => openArtifact(run, 'interactions')}><Layers3 size={13}/>交互过程</button>
            <button type="button" onClick={() => openArtifact(run, 'evidence')}><Search size={13}/>证据中心<span>{evidenceCount}</span></button>
            <button type="button" onClick={() => openArtifact(run, 'winning')}><BrainCircuit size={13}/>S1–S6 Agent<span>{winningStepCount}</span></button>
            {run.status !== 'completed' && candidateCount > 0 && <button type="button" onClick={() => openArtifact(run, 'capabilities')}><FlaskConical size={13}/>能力图像<span>{candidateCount}</span></button>}
            {reportCount > 0 && <button type="button" onClick={() => openArtifact(run, 'reports')}><FileCheck2 size={13}/>研究报告<span>{reportCount}</span></button>}
          </div>
          <div className="run-card-meta"><span title={runActualAgentTitle(run)}>{runtimeText}</span></div>
          {run.status === 'failed' && <div className="run-card-recovery"><div><CircleAlert size={15}/><span><b>任务执行中断</b><small>已保留检查点，可从上次进度继续</small></span></div><button type="button" className="primary" disabled={resumingRunId === run.run_id || Boolean(resumingRunId)} onClick={() => void resumeRun(run)}><RefreshCw size={14} className={resumingRunId === run.run_id ? 'spin' : ''}/>{resumingRunId === run.run_id ? '恢复中' : '从断点继续'}</button></div>}
          <div className="run-card-footer"><span className={`run-mode-label ${run.execution?.mode === 'real' ? 'real' : 'fake'}`}><i/>{run.execution?.mode === 'real' ? '真实运行' : '离线模拟'}</span><span>{run.execution?.mode === 'real' ? `${providerDisplayLabel(run.execution?.provider)} · ` : ''}{modelDisplayLabel(run.execution?.model || catalog.provider.model || 'gpt-5.5')}</span><div>{isRunActive(run, runtime) && <button className="icon-button row-stop" disabled={stopping} title="停止研究任务并终止所有 Agent 进程" onClick={() => stopRun(run)}><X size={15}/></button>}<button className="icon-button" title="打开研究详情" onClick={() => open(run)}><Eye size={16}/></button><button className="icon-button row-delete" disabled={deleting || stopping} title="永久删除任务及后端数据（会先停止任务并终止全部 Agent 进程）" onClick={() => deleteRuns([run.run_id])}><Trash2 size={15}/></button></div></div>
        </article>;
      })}</div><div className="run-scroll-loader" ref={loadMoreRef}>{hasMoreVisibleRuns || hasMoreRemoteRuns ? `继续滚动加载更早任务 · 已载入 ${runs.length} / ${runTotal || runs.length}` : `已载入全部 ${visible.length} 项`}</div></div>}
    </section>
  </>;
}

function WorkspacePulse({runs, runtime, runStatusCounts = {}, onView}) {
  const activeFromCounts = [...ACTIVE_RUN_STATUSES].reduce((total, value) => total + Number(runStatusCounts[value] || 0), 0);
  const active = activeFromCounts || runs.filter(run => isRunActive(run, runtime)).length;
  const completed = Number(runStatusCounts.completed ?? runs.filter(run => run.status === 'completed').length);
  const failed = Number(runStatusCounts.failed ?? runs.filter(run => run.status === 'failed').length);
  const recent = [...runs].filter(run => run.status === 'completed').sort((a,b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))[0];
  return <section className="workspace-pulse" aria-label="研究工作台概览">
    <div className="pulse-heading"><div><span>WORKSPACE PULSE</span><b>今天的研究进展</b></div><small>{active ? `${active} 个任务正在推进` : '当前没有运行中的任务'}</small></div>
    <div className="pulse-metrics">
      <article className="pulse-metric active"><span>进行中</span><strong>{active}</strong><small>{runtime.pending_count || 0} 个排队</small></article>
      <article className="pulse-metric success"><span>已完成</span><strong>{completed}</strong><small>可直接阅读报告</small></article>
      <article className="pulse-metric warn"><span>需要处理</span><strong>{failed}</strong><small>{failed ? '可从断点继续' : '暂无异常任务'}</small></article>
    </div>
    <div className="pulse-next"><div><span className="pulse-next-icon"><Sparkles size={16}/></span><span><b>{recent ? '继续使用最近成果' : '从一个研究问题开始'}</b><small>{recent ? recent.topic : '输入 Query，系统会自动规划信源、Agent 和报告结构。'}</small></span></div><button type="button" onClick={recent ? () => window.scrollTo({top:0, behavior:'smooth'}) : onView}>{recent ? '新建研究' : '打开问题库'}<ChevronRight size={14}/></button></div>
  </section>;
}

function ModelProfileSwitcher({profiles, value, onChange}) {
  const allRows = (profiles?.profiles || []).filter(item => !item?.deprecated);
  const providerLabel = item => {
    const text = `${item?.id || ''} ${item?.provider || ''} ${item?.label || ''}`.toLowerCase();
    if (text.includes('deepseek')) return 'DeepSeek';
    if (text.includes('queen') || text.includes('qwen') || text.includes('dashscope')) return 'Queen';
    if (String(item?.label || '').trim()) return String(item.label).split('/')[0].trim();
    return 'GPT';
  };
  const rows = allRows;
  const [doctoring, setDoctoring] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => { setMessage(''); }, [value]);
  if (!rows.length) return null;
  const current = rows.find(item => item.id === value) || rows[0];
  const currentLabel = providerLabel(current);
  const doctorMessage = data => {
    if (data?.errors?.length) return data.errors.join('；');
    if (!data?.model) return '接口可达，但未配置模型 ID（请在 .env 填写对应 MODEL）';
    if (data?.model_available === false) return `接口可达，但模型 ${data.model} 不在 /models 列表`;
    if (data?.reachable && data?.model_available == null) return '接口可达；网关未返回完整模型列表（中转站常见），可直接试用';
    return '健康检查通过';
  };
  const doctor = async () => {
    setDoctoring(current.id); setMessage('');
    const result = await requestResult(`/model-profiles/${encodeURIComponent(current.id)}/doctor`, {method: 'POST', headers: {'X-Role': 'analyst'}});
    setDoctoring('');
    if (!result.ok) { setMessage(result.detail || '健康检查失败'); return; }
    setMessage(doctorMessage(result.data));
  };
  return <section className="model-profile-switcher" aria-label="本任务模型设置">
    <div className="model-profile-summary"><span className="model-profile-kicker"><BrainCircuit size={15}/>本任务模型</span><b>{currentLabel}</b><small>仅用于本次研究任务</small></div>
    <div className="model-profile-actions"><select aria-label="选择本任务模型" value={current.id} onChange={event => onChange(event.target.value)}>{rows.map(item => <option key={item.id} value={item.id}>{providerLabel(item)}</option>)}</select><button type="button" disabled={doctoring !== ''} onClick={doctor}>{doctoring ? '检查中…' : '检查'}</button></div>
    <small className="model-profile-message">{message || '仅用于本次研究任务；下一条任务可重新选择。'}</small>
  </section>;
}

function runAgentSelectionLabel(run) {
  const count = Number(run.actual_agent_count || 0);
  return count > 0 ? `${count} 路` : '待调用';
}

function runActualAgentTitle(run) {
  const ids = run.actual_agent_ids || [];
  return ids.length ? `实际调用 ${ids.length} 个多源基线 Agent：${ids.map(agentModelLabel).join('、')}` : '尚未产生多源基线 Agent 调用';
}

function runRouteSelectionLabel(run) {
  return run.interaction_mode === 'autonomous' ? '自动' : routeLabel(run.research_route);
}

function formatRunUpdatedAt(value) {
  if (!value) return '尚无运行记录';
  // Anything inside the last day reads relatively ("12 分钟前"); older records
  // keep the absolute stamp so the audit trail stays unambiguous.
  const label = relativeTime(value);
  return label ? `更新于 ${label}` : '已更新';
}

function ResearchQueryEntry({catalog, runtime, openQueryLibrary, initialQuery, renderInlineBuilder}) {
  // A half-written Query survives a reload or a detour into the query library
  // instead of being retyped. Cleared once a run actually starts.
  const [query, setQuery] = usePersistentDraft(COMPOSER_QUERY_DRAFT_KEY, {limit: 4000});
  const [supplement, setSupplement] = usePersistentDraft(COMPOSER_SUPPLEMENT_DRAFT_KEY);
  const [modelProfileId, setModelProfileId] = usePersistentState('runs.modelProfileId', '');
  const [selectedRecommendation, setSelectedRecommendation] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [recommendationIndex, setRecommendationIndex] = useState(0);
  const [recommendationPaused, setRecommendationPaused] = useState(false);
  const [recommendationLoading, setRecommendationLoading] = useState(true);
  const [recommendationError, setRecommendationError] = useState('');
  const [executionProfileId, setExecutionProfileId] = useState(DEFAULT_EXECUTION_PROFILE_ID);
  const [runConfigOpen, setRunConfigOpen] = useState(false);
  const [startRequestId, setStartRequestId] = useState(0);
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState('');
  const modelProfileRows = (catalog.model_profiles || catalog.provider?.model_profiles)?.profiles || [];
  const resolvedModelProfileId = useMemo(() => {
    const ids = modelProfileRows.map(item => item.id).filter(Boolean);
    if (ids.includes(modelProfileId)) return modelProfileId;
    const preferred = (catalog.model_profiles || catalog.provider?.model_profiles)?.active_profile
      || (catalog.model_profiles || catalog.provider?.model_profiles)?.default_profile
      || ids[0]
      || '';
    return ids.includes(preferred) ? preferred : '';
  }, [modelProfileId, modelProfileRows]);
  useEffect(() => {
    if (resolvedModelProfileId && resolvedModelProfileId !== modelProfileId) setModelProfileId(resolvedModelProfileId);
  }, [resolvedModelProfileId, modelProfileId]);
  const refreshRecommendations = async () => {
    setRecommendationLoading(true);
    const pageSize = 200;
    const firstPage = await request(`/query-library/queries?limit=${pageSize}&offset=0`, null);
    if (!firstPage) {
      setRecommendationError('问题库暂时无法连接');
      setRecommendationLoading(false);
      return;
    }
    const remainingOffsets = Array.from({length:Math.max(0, Math.ceil((firstPage.total || 0) / pageSize) - 1)}, (_, index) => (index + 1) * pageSize);
    const remainingPages = await Promise.all(remainingOffsets.map(offset => request(`/query-library/queries?limit=${pageSize}&offset=${offset}`, {items:[]})));
    const candidates = [firstPage, ...remainingPages].flatMap(page => page.items || []).filter(item => item.status !== 'archived' && item.query);
    setRecommendations(shuffleRecommendations(candidates));
    setRecommendationIndex(0);
    setRecommendationError(candidates.length ? '' : '问题库中暂无可推荐 Query');
    setRecommendationLoading(false);
  };
  useEffect(() => { void refreshRecommendations(); }, []);
  useEffect(() => {
    if (!initialQuery?.query) return;
    setSelectedRecommendation(initialQuery);
    setQuery(initialQuery.query);
    setSupplement(initialQuery.supplemental_information || '');
  }, [initialQuery?.query_id, initialQuery?.version, initialQuery?.query]);
  useEffect(() => {
    if (recommendationPaused || recommendations.length < 2) return undefined;
    const timer = setInterval(() => {
      if (!document.hidden) setRecommendationIndex(index => (index + 1) % recommendations.length);
    }, 5000);
    return () => clearInterval(timer);
  }, [recommendationPaused, recommendations.length]);
  const moveRecommendation = direction => setRecommendationIndex(index => (index + direction + recommendations.length) % recommendations.length);
  const chooseRecommendation = (item, index) => { setRecommendationIndex(index); setSelectedRecommendation(item); setQuery(item.query); setSupplement(item.supplemental_information || ''); };
  const openSupplement = () => { setRunConfigOpen(true); window.requestAnimationFrame(() => document.getElementById('research-query-supplement')?.focus()); };
  const triggerStart = () => {
    setLaunchError('');
    setRunConfigOpen(true);
    setStartRequestId(value => value + 1);
  };
  const activeQuery = selectedRecommendation ? {...selectedRecommendation, query:query.trim(), supplemental_information:supplement.trim()} : {query:query.trim(), supplemental_information:supplement.trim(), generation_rationale:'用户在研究首页直接输入 Query。', source_references:[], status:'published', source_type:'manual'};
  return <section className="research-query-home">
    <div className="research-query-hero">
      <span>DEEP RESEARCH QUERY</span>
      <h1>创新为帆 探索未至之境</h1>
      <div className={`research-query-composer ${runConfigOpen ? 'config-open' : ''}`}>
        <textarea id="research-query-input" aria-label="Deep Research Query" value={query} onChange={event => { setQuery(event.target.value); setSelectedRecommendation(null); }} onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && query.trim() && runtime.worker_online && !launching) { event.preventDefault(); triggerStart(); } }} placeholder="输入需要进行 Deep Research 的 Query，例如：研究低空无人装备在强对抗环境中的体系能力缺口" maxLength={4000}/>
        <div className="research-query-input-state"><span>{query.trim() ? `已输入 ${query.trim().length} 字` : '等待输入研究问题'}</span><span><kbd>⌘/Ctrl</kbd> + <kbd>Enter</kbd> 快速启动</span>{query && <button aria-label="清空 Query" onClick={() => { setQuery(''); setSupplement(''); setSelectedRecommendation(null); document.getElementById('research-query-input')?.focus(); }}><X size={12}/>清空</button>}</div>
        <ModelProfileSwitcher profiles={catalog.model_profiles || catalog.provider?.model_profiles} value={resolvedModelProfileId} onChange={setModelProfileId} />
        <footer><div className="research-query-footer-left"><button onClick={openSupplement}><Plus size={14}/>补充背景与约束</button><ResearchModePicker profiles={catalog.execution_profiles || []} value={executionProfileId} onChange={setExecutionProfileId}/></div><div className="research-query-footer-right"><button onClick={openQueryLibrary}><Sparkles size={15}/>AI 生成 Query</button><button className={`research-config-trigger ${runConfigOpen ? 'active' : ''}`} onClick={() => setRunConfigOpen(value => !value)}><Wrench size={14}/>{runConfigOpen ? '收起运行配置' : '研究运行配置'}<ChevronDown size={13}/></button><button className="primary research-start-trigger" disabled={!query.trim() || !runtime.worker_online || launching} title={!runtime.worker_online ? '研究 Worker 未在线' : launching ? '正在创建并启动研究任务' : '按当前模式和配置直接启动研究'} onClick={triggerStart}><Play size={14}/>{launching ? '启动中…' : '启动研究'}</button></div></footer>
        <div className="research-query-inline-config-shell" hidden={!runConfigOpen} aria-hidden={!runConfigOpen}>
          <textarea id="research-query-supplement" className="research-query-supplement" value={supplement} onChange={event => setSupplement(event.target.value)} placeholder="可选：补充作战场景、时间范围、约束、前提假设或希望覆盖的技术/装备类型。" maxLength={8000}/>
          {renderInlineBuilder(activeQuery, executionProfileId, setExecutionProfileId, resolvedModelProfileId, startRequestId, state => { setLaunching(Boolean(state?.submitting)); if (state?.error) setLaunchError(state.error); })}
        </div>
        {launchError && <p className="form-error research-launch-error"><CircleAlert size={15}/>{launchError}</p>}
      </div>
      <div className="research-query-suggestions">
        <div className="research-query-suggestion-heading"><span><small>问题库灵感推荐</small><em><i/>全库 {recommendations.length || 0} 条 · 自动轮播 · 点击即可带入研究</em></span><button className="suggestion-refresh" disabled={recommendationLoading} onClick={refreshRecommendations}><RefreshCw className={recommendationLoading ? 'spin' : ''} size={12}/>{recommendationLoading ? '读取中' : '重新排序'}</button></div>
        {recommendationLoading && !recommendations.length && <div className="recommendation-skeleton" aria-hidden="true">{[0, 1, 2].map(index => <div key={index}><Skeleton width="44%" height={9}/><Skeleton width="88%" height={15}/><Skeleton width="100%" height={10}/><Skeleton width="74%" height={10}/></div>)}</div>}
        {recommendations.length > 0 && <div className="recommendation-carousel">
          <button type="button" className="recommendation-playback" aria-label={recommendationPaused ? '继续自动轮播' : '暂停自动轮播'} onClick={() => setRecommendationPaused(value => !value)}>{recommendationPaused ? '继续轮播' : '暂停轮播'}</button>
          <button className="recommendation-arrow previous" aria-label="上一条推荐 Query" onClick={() => moveRecommendation(-1)}><ChevronLeft size={20}/></button>
          <div className="recommendation-stage">{recommendations.map((item, index) => {
            const forwardOffset = (index - recommendationIndex + recommendations.length) % recommendations.length;
            const offset = forwardOffset > recommendations.length / 2 ? forwardOffset - recommendations.length : forwardOffset;
            if (Math.abs(offset) > 2) return null;
            const positionClass = offset === 0 ? 'current' : offset === -1 ? 'previous' : offset === 1 ? 'next' : offset < 0 ? 'far-previous' : 'far-next';
            return <button title={item.query} data-carousel-offset={offset} className={`recommendation-card ${positionClass} ${query === item.query ? 'selected' : ''}`} key={item.query_id} onClick={() => chooseRecommendation(item, index)}><span>{item.source_type === 'agent' ? 'AGENT DISCOVERY' : item.source_type === 'import' ? 'CURATED INSIGHT' : 'RESEARCH IDEA'}{query === item.query && <CheckCircle2 size={14}/>}</span><b>{item.query}</b><p>{item.supplemental_information || item.generation_rationale || '点击将此 Query 带入研究任务。'}</p></button>;
          })}</div>
          <button className="recommendation-arrow next" aria-label="下一条推荐 Query" onClick={() => moveRecommendation(1)}><ChevronRight size={20}/></button>
        </div>}
        {recommendations.length > 1 && <div className="recommendation-progress"><div><i style={{width:`${((recommendationIndex + 1) / recommendations.length) * 100}%`}}/></div><span>{recommendationIndex + 1} / {recommendations.length}</span></div>}
        {recommendationError && <em className="recommendation-error">{recommendationError}</em>}
      </div>
    </div>
  </section>;
}

function ResearchModePicker({profiles, value, onChange}) {
  const fallbackProfiles = [
    {id:'legacy_v1', name:'传统固定编排', short_name:'传统模式', description:'固定流程执行，适合兼容回滚与对照。', default:false, badge:'兼容'},
    {id:'optimized_v2', name:'协同优化编排', short_name:'协同模式', description:'3–4 个业务 Agent 并行，并进入 S1–S6 Cohort。', recommended:true, badge:'推荐'},
    {id:'swarm_quality_v1', name:'质量残差蜂群', short_name:'质量集群', description:'按质量残差弹性孵化，最多 12 个 Agent。', evaluation_only:true, badge:'高质量'},
    {id:'winning_swarm_dynamic_v2', name:'Mission Graph 动态蜂群', short_name:'动态蜂群', description:'8–21 个实例动态孵化，提供最高并发能力。', default:true, evaluation_only:true, badge:'最高并发'},
  ];
  const items = profiles.length ? profiles.filter(item => item.selectable !== false) : fallbackProfiles;
  const selected = items.find(item => item.id === value) || items.find(item => item.recommended) || items.find(item => item.default) || fallbackProfiles[1];
  const selectProfile = (event, profileId) => {
    onChange(profileId);
    event.currentTarget.closest('details')?.removeAttribute('open');
  };
  return <details className="research-mode-picker">
    <summary><Layers3 size={15}/><span><small>研究模式</small><b>{selected.short_name || selected.name}</b></span><ChevronDown size={14}/></summary>
    <div className="research-mode-menu">
      <header><span><b>选择研究模式</b><small>模式将直接控制后端 Agent 编排与并发策略</small></span><em>{items.length} 种</em></header>
      <div>{items.map(item => <button type="button" className={item.id === selected.id ? 'selected' : ''} key={item.id} onClick={event => selectProfile(event, item.id)}><span className="mode-icon"><Layers3 size={16}/></span><span><b>{item.short_name || item.name}<em>{item.badge || (item.recommended ? '推荐' : item.default ? '兼容' : item.evaluation_only ? '挑战者' : '')}</em></b><small>{item.description}</small><code>{item.id}</code></span>{item.id === selected.id && <CheckCircle2 size={17}/>}</button>)}</div>
      <div className="research-mode-menu-note"><ShieldCheck size={13}/>所选模式随研究任务保存，可在草稿阶段修改并由 Worker 原样执行。</div>
    </div>
  </details>;
}

function ReportTemplatePicker({templates, value, onChange}) {
  const fallbackTemplates = [
    {id:'project_argument_v1', name:'项目论证五章模板', short_name:'项目论证五章', description:'需求分析、项目画像、总体方案、关键技术与研制基础。', default:true},
    {id:'three_layer_nine_item', name:'三层九项模板', short_name:'三层九项', description:'需求挖掘、技术攻关、能力图像与效能贡献结构。', default:false},
  ];
  const items = templates.length ? templates : fallbackTemplates;
  const selected = items.find(item => item.id === value) || items.find(item => item.default) || fallbackTemplates[0];
  return <section className="report-template-picker" aria-label="报告撰写模板">
    <header><span><b>报告模板</b><small>任务启动后固定结构</small></span><em>{selected.short_name || selected.name}</em></header>
    <div>{items.map(item => <button type="button" aria-pressed={item.id === selected.id} className={item.id === selected.id ? 'selected' : ''} key={item.id} onClick={() => onChange(item.id)}><span><FileSpreadsheet size={15}/><b>{item.short_name || item.name.replace('模板', '')}</b>{item.default && <em>推荐</em>}</span><small>{item.description}</small>{item.id === selected.id && <CheckCircle2 size={16}/>}</button>)}</div>
  </section>;
}

function ParallelRuntimePanel({runtime, runs, onCapacityChanged}) {
  const runById = new Map((runs || []).map(run => [run.run_id, run]));
  const workers = (runtime.workers || []).filter(worker => worker.online).sort((a, b) => (a.slot_index || 0) - (b.slot_index || 0));
  const researchWorkers = workers.filter(worker => worker.status !== 'internal');
  const internalWorkers = workers.filter(worker => worker.status === 'internal' && worker.current_run_id);
  const [editing, setEditing] = useState(false);
  const [desired, setDesired] = useState(runtime.configured_worker_capacity || Math.max(1, runtime.worker_capacity || 1));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (!saving) setDesired(runtime.configured_worker_capacity || 1); }, [runtime.configured_worker_capacity, saving]);
  const capacityLimit = runtime.capacity_limit || 8;
  const applyCapacity = async () => {
    setSaving(true); setError('');
    const result = await requestResult('/runtime-capacity', {method:'PUT', headers:{'Content-Type':'application/json','X-Role':'analyst'}, body:JSON.stringify({capacity:desired})});
    setSaving(false);
    if (!result.ok) { setError(result.detail || '槽位设置失败'); return; }
    setEditing(false);
    await onCapacityChanged?.();
  };
  const transitionText = runtime.capacity_transition === 'scaling_up'
    ? `正在扩容到 ${runtime.configured_worker_capacity} 个槽位`
    : runtime.capacity_transition === 'scaling_down'
      ? runtime.active_count > 0
        ? `运行中任务结束后缩容到 ${runtime.configured_worker_capacity} 个槽位`
        : `正在缩容到 ${runtime.configured_worker_capacity} 个槽位`
      : '';
  return <section className="parallel-runtime" aria-label="研究任务并行执行状态">
    <header><div><Activity size={17}/><span><b>{runtime.parallel_enabled ? '多任务并行执行已启用' : '单任务执行模式'}</b><small>研究槽位运行独立任务；S6 画像使用任务内部并行，不占研究槽位{runtime.internal_count ? `（当前 ${runtime.internal_count} 个内部并行）` : ''}</small></span></div><div className="parallel-runtime-actions"><em>{runtime.available_slots || 0} 个可用槽位</em><button onClick={() => { setEditing(value => !value); setError(''); }}><Wrench size={13}/>设置槽位</button></div></header>
    {editing && <div className="slot-capacity-editor"><span><b>并行研究任务槽位</b><small>可同时运行 1–{capacityLimit} 个研究任务；缩容不会中断正在运行的任务。</small></span><div><button aria-label="减少槽位" disabled={desired <= 1 || saving} onClick={() => setDesired(value => Math.max(1, value - 1))}>−</button><strong>{desired}</strong><button aria-label="增加槽位" disabled={desired >= capacityLimit || saving} onClick={() => setDesired(value => Math.min(capacityLimit, value + 1))}>＋</button><button className="primary" disabled={saving || desired === runtime.configured_worker_capacity} onClick={applyCapacity}>{saving ? '应用中' : '应用'}</button></div>{error && <p>{error}</p>}</div>}
    {transitionText && <div className="slot-capacity-transition"><RefreshCw className="spin" size={13}/>{transitionText}</div>}
    <div className="parallel-worker-grid">{researchWorkers.map((worker, index) => { const run = runById.get(worker.current_run_id); const busy = worker.status === 'working' && worker.current_run_id; return <article className={busy ? 'busy' : 'idle'} key={worker.worker_id}><span>槽位 #{index + 1}</span><b>{busy ? run?.topic || worker.current_run_id : '等待研究任务'}</b><small>{busy ? worker.current_run_id : worker.worker_id}</small></article>; })}</div>
    {internalWorkers.length > 0 && <div className="parallel-internal-runtime" aria-label="S6 内部并行任务"><header><span><Zap size={14}/><span><b>S6 能力画像内部并行</b><small>由研究任务内部管理，不占用研究槽位</small></span></span><em>{internalWorkers.length} 个运行中</em></header><div className="parallel-internal-grid">{internalWorkers.map(worker => <article key={worker.worker_id}><b>{runById.get(worker.current_run_id)?.topic || 'S6 能力画像内部并行'}</b><small>{worker.current_run_id}</small></article>)}</div></div>}
    {runtime.pending_count > 0 && <footer><Clock3 size={14}/>当前有 {runtime.pending_count} 个任务排队；任一槽位释放后按创建顺序自动执行。</footer>}
  </section>;
}

function CreateRun({catalog, done, runtime, initialQuery, openQueryLibrary, inline = false, executionProfileId: controlledExecutionProfileId = '', onExecutionProfileChange, modelProfileId = '', startRequestId = 0, onSubmitStateChange}) {
  const workerOnline = runtime.worker_online;
  const [topic, setTopic] = useState(initialQuery?.query || ''); const [supplementalInformation, setSupplementalInformation] = useState(initialQuery?.supplemental_information || ''); const [route, setRoute] = useState('auto'); const [interactionMode, setInteractionMode] = useState('expert'); const [branch, setBranch] = useState('auto'); const [localExecutionProfileId, setLocalExecutionProfileId] = useState(DEFAULT_EXECUTION_PROFILE_ID); const [reportTemplateMode, setReportTemplateMode] = useState('project_argument_v1'); const [agents, setAgents] = useState([]); const [rounds, setRounds] = useState(2); const [submitting, setSubmitting] = useState(false); const [error, setError] = useState(''); const [agentPreview, setAgentPreview] = useState(null);
  const executionProfileId = controlledExecutionProfileId || localExecutionProfileId;
  const setExecutionProfileId = value => { setLocalExecutionProfileId(value); onExecutionProfileChange?.(value); };
  const [libraryQueries, setLibraryQueries] = useState([]); const [librarySearch, setLibrarySearch] = useState(''); const [libraryLoading, setLibraryLoading] = useState(true); const [selectedQueryId, setSelectedQueryId] = useState(initialQuery?.query_id || ''); const [libraryError, setLibraryError] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const submitLockRef = useRef(false);
  const pendingCreateRequestRef = useRef({key:'', fingerprint:''});
  const availableAgents = useMemo(() => businessAgents(catalog), [catalog.agents]);
  const routeDef = catalog.routes.find(item => item.id === route) || {required_tags: []};
  const branchDef = catalog.discovery_branches?.find(item => item.id === branch);
  const defaultAgentIds = useMemo(() => executionProfileId !== 'legacy_v1' ? agentPreview?.selected_agent_ids || [] : [], [agentPreview, executionProfileId]);
  const defaultAgentIdSet = useMemo(() => new Set(defaultAgentIds), [defaultAgentIds]);
  const manualAgentIds = useMemo(() => agents.filter(id => !defaultAgentIdSet.has(id)), [agents, defaultAgentIdSet]);
  const effectiveAgentIds = useMemo(() => [...new Set([...defaultAgentIds, ...manualAgentIds])], [defaultAgentIds, manualAgentIds]);
  const provided = useMemo(() => new Set(availableAgents.filter(agent => effectiveAgentIds.includes(agent.agent_id)).flatMap(agent => agent.capability_tags)), [effectiveAgentIds, availableAgents]);
  const previewPlan = useMemo(() => new Map((agentPreview?.plan || []).map(item => [item.agent_id, item])), [agentPreview]);
  const visibleLibraryQueries = useMemo(() => {
    return searchQueryItems(libraryQueries, librarySearch);
  }, [libraryQueries, librarySearch]);
  const selectedLibraryQuery = libraryQueries.find(item => item.query_id === selectedQueryId) || (initialQuery?.query_id === selectedQueryId ? initialQuery : null);
  useEffect(() => {
    if (inline) { setLibraryLoading(false); return undefined; }
    let cancelled = false;
    setLibraryLoading(true); setLibraryError('');
    request('/query-library/queries?status=published&limit=200', null, {headers: {'X-Role': 'analyst'}}).then(value => {
      if (cancelled) return;
      if (!value) setLibraryError('Query 库读取失败，仍可直接输入研究问题。');
      setLibraryQueries(value?.items || []);
    }).finally(() => { if (!cancelled) setLibraryLoading(false); });
    return () => { cancelled = true; };
  }, [inline]);
  useEffect(() => {
    setSelectedQueryId(initialQuery.query_id || '');
    setTopic(initialQuery.query || '');
    setSupplementalInformation(initialQuery.supplemental_information || '');
  }, [initialQuery?.query_id, initialQuery?.version, initialQuery?.query, initialQuery?.supplemental_information]);
  useEffect(() => {
    const templates = catalog.report_templates || [];
    if (!templates.length || templates.some(item => item.id === reportTemplateMode)) return;
    setReportTemplateMode(templates.find(item => item.default)?.id || templates[0].id);
  }, [catalog.report_templates, reportTemplateMode]);
  useEffect(() => {
    let cancelled = false;
    if (!topic.trim()) { setAgentPreview(null); return undefined; }
    const timer = setTimeout(() => {
      request('/agent-selection-preview', null, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({topic: topic.trim(), supplemental_information: supplementalInformation.trim(), research_route: route, interaction_mode: interactionMode, discovery_branch: branch})}).then(value => { if (!cancelled) setAgentPreview(value); });
    }, 280);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [topic, supplementalInformation, route, interactionMode, branch]);
  const toggle = id => setAgents(rows => rows.includes(id) ? rows.filter(item => item !== id) : [...rows, id]);
  const submit = async (startImmediately = true) => {
    if (submitLockRef.current) return;
    if (startImmediately && !workerOnline) { setError('研究 Worker 未在线，已阻止任务进入无人消费的队列；你仍可先保存为草稿。'); return; }
    if (startImmediately && catalog.provider.default_mode === 'real' && catalog.provider.codex_available === false) { setError('后端未检测到 Agent 运行组件；可先保存草稿，配置运行环境后再启动。'); return; }
    // A deliberate start action is the analyst confirmation. Avoid native
    // confirm dialogs: embedded browsers can leave them hidden while blocking
    // the JavaScript thread, which makes the launch button appear unresponsive.
    const analystConfirmed = startImmediately;
    submitLockRef.current = true;
    setSubmitting(true); setError('');
    const submittedAgentIds = executionProfileId !== 'legacy_v1' ? manualAgentIds : effectiveAgentIds;
    const createPayload = {topic: topic.trim(), supplemental_information: supplementalInformation.trim(), research_route: route, interaction_mode: interactionMode, discovery_branch: branch, execution_profile_id: executionProfileId, report_template_mode: reportTemplateMode, selected_agent_ids: submittedAgentIds, max_rounds: rounds, analyst_confirmed: analystConfirmed, source_query_id: selectedLibraryQuery?.query_id || '', source_query_version: selectedLibraryQuery?.version || null, publish_source_query_on_create: startImmediately && selectedLibraryQuery?.status === 'draft', model_profile_id: modelProfileId};
    const createFingerprint = JSON.stringify(createPayload);
    if (pendingCreateRequestRef.current.fingerprint !== createFingerprint) pendingCreateRequestRef.current = {key:crypto.randomUUID(), fingerprint:createFingerprint};
    const createRequestId = pendingCreateRequestRef.current.key;
    const createdResult = await requestResult('/runs', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst', 'Idempotency-Key': createRequestId}, body: createFingerprint}, {timeoutMs:15000});
    if (!createdResult.ok || !createdResult.data?.run_id) {
      if (createdResult.status) pendingCreateRequestRef.current = {key:'', fingerprint:''};
      submitLockRef.current = false;
      setSubmitting(false);
      setError(`任务创建失败：${createdResult.detail || '请检查配置和 API 服务。'}`);
      return;
    }
    const created = createdResult.data;
    pendingCreateRequestRef.current = {key:'', fingerprint:''};
    if (!startImmediately) { submitLockRef.current = false; setSubmitting(false); done(created, false); return; }
    const started = await requestResult(runApiPath(created.run_id, '/start'), {method: 'POST', headers: {'Idempotency-Key': `start:${createRequestId}`, 'X-Role': 'analyst'}}, {timeoutMs:15000});
    submitLockRef.current = false;
    setSubmitting(false);
    if (started.ok) done(started.data, true); else setError(`任务已保存为草稿，但启动失败：${started.detail || '请检查 Agent、API Key 和 Worker 环境。'}`);
    if (!started.ok) done(created, false);
  };
  useEffect(() => { onSubmitStateChange?.({submitting, error}); }, [submitting, error]);
  useEffect(() => { if (startRequestId > 0) void submit(true); }, [startRequestId]);
  const disabled = submitting || !topic.trim();
  const startDisabled = disabled || (catalog.provider.default_mode === 'real' && catalog.provider.codex_available === false);
  return <section className={`create-panel ${inline ? 'inline-research-config' : ''}`} id="research-task-builder">
    {inline ? <header className="inline-research-config-heading"><div><Wrench size={17}/><span><b>研究运行配置</b><small>{initialQuery?.query_id ? `${initialQuery.source_type === 'agent' ? 'Agent 生成' : initialQuery.source_type === 'import' ? '资料导入' : '人工录入'} · ${initialQuery.query_id}` : '当前为用户输入 Query'}</small></span></div><button onClick={openQueryLibrary}><Search size={14}/>更换 Query</button></header> : <div className="panel-kicker"><Sparkles size={16}/>确认研究问题并启动</div>}
    {!inline && (initialQuery ? <section className="selected-research-query"><header><div><CheckCircle2 size={18}/><span><b>Query 已带入研究任务</b><small>{initialQuery.query_id ? `${initialQuery.source_type === 'agent' ? 'Agent 生成' : initialQuery.source_type === 'import' ? '资料导入' : '人工输入'} · ${initialQuery.query_id} · v${initialQuery.version}` : '用户直接输入'}</small></span></div><button onClick={openQueryLibrary}><Search size={14}/>重新选择</button></header>{initialQuery.generation_rationale && <p><Lightbulb size={14}/>{initialQuery.generation_rationale}</p>}</section> : <section className="create-query-source">
      <header><div><Database size={17}/><span><b>从已发布 Query 库选择</b><small>选中后自动带入研究问题、补充角度与来源版本</small></span></div><div className="create-query-header-actions"><button type="button" onClick={openQueryLibrary}><Sparkles size={14}/>生成或审核 Query</button>{selectedLibraryQuery && <button type="button" onClick={() => setSelectedQueryId('')}><X size={14}/>改为人工输入</button>}</div></header>
      <div className="create-query-toolbar"><Field label="搜索已发布 Query"><div className="create-query-search"><Search size={15}/><input value={librarySearch} onChange={event => setLibrarySearch(event.target.value)} placeholder="输入研究方向、生成理由或分析维度" disabled={!libraryQueries.length}/></div></Field><div className="create-query-library-summary"><BookOpenCheck size={16}/><span><b>{libraryQueries.length} 条可用 Query</b><small>草稿需先在需求 Query 工作区审核发布</small></span></div></div>
      {libraryError ? <p className="create-query-message"><CircleAlert size={14}/>{libraryError}</p> : libraryLoading ? <p className="create-query-message"><RefreshCw className="spin" size={14}/>正在读取 Query 库…</p> : <div className="create-query-list" role="listbox" aria-label="已发布 Query 列表">{visibleLibraryQueries.length ? visibleLibraryQueries.map(item => <button type="button" role="option" aria-selected={selectedQueryId === item.query_id} className={selectedQueryId === item.query_id ? 'selected' : ''} key={item.query_id} onClick={() => { setSelectedQueryId(item.query_id); setTopic(item.query); setSupplementalInformation(item.supplemental_information || ''); }}><span><b>{item.source_type === 'agent' ? 'Agent 生成' : item.source_type === 'manual' ? '人工录入' : '资料导入'}</b><em>v{item.version} · {item.source_references?.length || 0} 个来源</em></span><p>{item.query}</p>{selectedQueryId === item.query_id && <CheckCircle2 size={16}/>}</button>) : <p className="create-query-message">没有匹配的已发布 Query，可前往工作区生成或审核</p>}</div>}
      {selectedLibraryQuery && <section className="selected-query-context"><div><Lightbulb size={15}/><span><b>选题理由</b><p>{selectedLibraryQuery.generation_rationale || '未填写生成理由，建议在启动前确认研究价值与边界。'}</p></span></div><div><FileSpreadsheet size={15}/><span><b>来源线索</b><p>{selectedLibraryQuery.source_references?.length ? selectedLibraryQuery.source_references.slice(0, 3).map(item => item.title).join('、') : '暂无直接来源，研究阶段需独立采集正式证据。'}</p></span></div></section>}
    </section>)}
    {!inline && <Field label="最终研究问题"><textarea className="research-topic-input" value={topic} maxLength={4000} onChange={event => setTopic(event.target.value)} placeholder="输入可直接提交 Deep Research 的完整研究问题"/><small className="field-hint">{topic.length}/4000 · 支持长 Query，并保留来源版本</small></Field>}
    <ReportTemplatePicker templates={catalog.report_templates || []} value={reportTemplateMode} onChange={setReportTemplateMode}/>
    {!inline && <Field label="补充信息（可选）"><textarea className="supplement-input" value={supplementalInformation} maxLength={8000} onChange={event => setSupplementalInformation(event.target.value)} placeholder="可补充思考问题、发散维度、前提假设或约束。主控 Agent 会压缩为结构化简报后传递给后续 Agent。"/><small className="field-hint">{supplementalInformation.length}/8000 · 原文留存审计，下游默认只接收精简结构化简报</small></Field>}
    <button type="button" className={`research-advanced-toggle ${advancedOpen ? 'open' : ''}`} onClick={() => setAdvancedOpen(value => !value)}><Wrench size={15}/><span><b>{advancedOpen ? '收起高级编排选项' : '高级编排选项'}</b><small>当前：专家模式 · 自动分支 · 2 轮 · 系统自动选择 Agent</small></span><ChevronDown size={16}/></button>
    {advancedOpen && <>
    <div className="form-grid">{!inline && <Field label="研究主题"><input value={topic} onChange={event => setTopic(event.target.value)} placeholder="例如：低空无人作战体系能力缺口"/></Field>}<Field label="交互模式"><select value={interactionMode} onChange={event => setInteractionMode(event.target.value)}>{(catalog.interaction_modes || []).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="A–H 发现分支"><select value={branch} onChange={event => setBranch(event.target.value)}><option value="auto">Agent 自动选择</option>{(catalog.discovery_branches || []).map(item => <option key={item.id} value={item.id}>{item.id} · {item.name}</option>)}</select></Field><Field label="运行模式"><select value={executionProfileId} onChange={event => { const value = event.target.value; setExecutionProfileId(value); if (value !== 'legacy_v1' && rounds > 3) setRounds(3); }}>{(catalog.execution_profiles || [{id:'legacy_v1',name:'Legacy v1'}]).filter(item => item.selectable !== false).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="研究路线"><select value={route} onChange={event => setRoute(event.target.value)}><option value="auto">按发现分支自动映射</option>{catalog.routes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="最大研究轮次"><select value={rounds} onChange={event => setRounds(Number(event.target.value))}>{[1, 2, 3, ...(executionProfileId === 'legacy_v1' ? [4, 5] : [])].map(value => <option key={value} value={value}>{value === 2 ? '2 轮（推荐）' : `${value} 轮`}</option>)}</select></Field></div>
    {agentPreview?.structured_query_brief?.supplement_present && <section className="supplement-brief"><header><BrainCircuit size={16}/><span><b>主控 Agent 结构化简报</b><small>下游 Agent 将接收以下精简信息</small></span></header><p>{agentPreview.structured_query_brief.supplement_summary}</p><div>{(agentPreview.structured_query_brief.expansion_dimensions || []).map(item => <em key={item}>{item}</em>)}</div></section>}
    <div className="blueprint-note"><Gauge size={18}/><span><b>{(catalog.execution_profiles || []).find(item => item.id === executionProfileId)?.name || executionProfileId}</b>{(catalog.execution_profiles || []).find(item => item.id === executionProfileId)?.description || '使用受控分支编排、风险门控与可恢复审计。'}</span></div>
    <div className="blueprint-note"><BrainCircuit size={18}/><span><b>{interactionMode === 'autonomous' ? '智能元编排' : '专家约束编排'}</b>{branchDef ? `${branchDef.id} · ${branchDef.name}；系统将自动调度 ${branchDef.specialist_agent_ids.length ? branchDef.specialist_agent_ids.join('、') : '通用基线'} Agent。` : '编排器将从 A–H 中选择主分支和最多两个次分支，并生成执行波次。'}</span></div>
    {branchDef?.step_modes?.length > 0 && <div className="branch-step-preview"><span>本分支 S1–S6 强度</span>{branchDef.step_modes.map(item => <b className={item.execution_mode} key={item.step}>S{item.step}<em>{stepModeLabel(item.execution_mode)}</em></b>)}</div>}
    <div className="agent-section"><div className="section-heading"><div><b>业务 Agent</b><span>{executionProfileId !== 'legacy_v1' ? '质量型挑战者保留系统默认选择；可继续勾选其他角色作为人工追加，不会覆盖默认编排。' : 'Legacy v1 使用人工显式选择；未选择时由旧版覆盖策略补足。'}</span></div><span className="selection-count">{executionProfileId !== 'legacy_v1' && agentPreview ? `默认 ${defaultAgentIds.length} + 追加 ${manualAgentIds.length} = ${effectiveAgentIds.length}` : manualAgentIds.length ? `人工选择 ${manualAgentIds.length}` : agentPreview ? `预计 ${agentPreview.selected_agent_ids.length} 个` : '智能分析中'}</span></div><div className="agent-selector">{availableAgents.map(agent => { const preview = previewPlan.get(agent.agent_id); const defaultSelected = defaultAgentIdSet.has(agent.agent_id); const manualSelected = manualAgentIds.includes(agent.agent_id); return <label className={`agent-choice ${defaultSelected || manualSelected ? 'selected' : ''} ${defaultSelected ? 'recommended default-selected' : ''} ${manualSelected ? 'manual-added' : ''}`} key={agent.agent_id}><input type="checkbox" checked={defaultSelected || manualSelected} disabled={defaultSelected} aria-label={`${agent.display_name}${defaultSelected ? '（系统默认）' : '（可人工追加）'}`} onChange={() => { if (!defaultSelected) toggle(agent.agent_id); }}/><Bot size={18}/><span><b>{agent.display_name}{defaultSelected && <i>{preview?.mode === 'required' ? '默认·必需' : '默认·参考'}</i>}{manualSelected && <i className="manual">{executionProfileId !== 'legacy_v1' ? '人工追加' : '人工选择'}</i>}</b><small>{agent.description}</small><em>{agent.capability_tags.join(' · ')}</em>{preview && <strong>{preview.reason}</strong>}</span></label>; })}</div>{agentPreview ? <><div className="agent-selection-preview"><header><BrainCircuit size={16}/><span><b>{agentPreview.primary_branch} · {agentPreview.branch_name}</b><small>{agentPreview.policy}</small></span></header><div>{agentPreview.plan.map(item => <span key={item.agent_id}><b>{item.display_name}</b><em>{item.mode === 'required' ? '默认必需' : '默认参考'}</em><small>{item.reason}</small></span>)}</div><footer>{executionProfileId !== 'legacy_v1' ? manualAgentIds.length ? `人工追加：${manualAgentIds.map(agentModelLabel).join('、')}；执行时与默认 Agent 合并。` : '可在上方勾选未入选角色，作为人工追加项。' : manualAgentIds.length ? `人工选择：${manualAgentIds.map(agentModelLabel).join('、')}。` : '可在上方人工选择业务 Agent。'}{agentPreview.callback_agent_ids?.length > 0 ? ` 缺口触发回调：${agentPreview.callback_agent_ids.map(agentModelLabel).join('、')}` : ''}</footer></div><div className="coverage-box"><span>{executionProfileId !== 'legacy_v1' ? '最终执行覆盖（默认 + 人工追加）' : '人工选择覆盖'}</span>{routeDef.required_tags.map(tag => <b className={provided.has(tag) ? 'covered' : 'missing'} key={tag}>{tag}</b>)}</div></> : <div className="coverage-box"><span>输入研究主题后，将即时预览默认 Agent；此前人工勾选项会作为追加项保留。</span></div>}</div>
    </>}
    <div className="create-actions"><span>{selectedLibraryQuery?.status === 'draft' ? '当前 Query 待审核；启动研究时将自动审核发布并记录来源版本。' : runtime.available_slots > 0 ? `当前有 ${runtime.available_slots} 个并行槽位可立即执行。` : `当前槽位已满，启动后将进入队列（前方 ${runtime.pending_count || 0} 项）。`}</span><div className="create-buttons"><button disabled={disabled} onClick={() => submit(false)}><Save size={15}/>保存草稿</button>{!inline && <button className="primary" disabled={startDisabled} onClick={() => submit(true)}>{submitting ? '正在处理' : '创建并启动研究'}<ChevronDown size={16}/></button>}</div></div>
    {error && <p className="form-error"><CircleAlert size={15}/>{error}</p>}
  </section>;
}

function WorkspacePage({view, run, runs, runTotal, runStatusCounts = {}, hasMoreRuns, loadMoreRuns, catalog, runtime, loaded, navigate, focusCardKey = '', favoriteIndex = {}, onFavoriteToggle, selectRun}) {
  const [payload, setPayload] = useState(null); const [loading, setLoading] = useState(false);
  const [taskQuery, setTaskQuery] = useState(''); const [taskStatus, setTaskStatus] = useState('all');
  // Keep the capability-page task navigator visible on first render so the
  // current research task and available task list are immediately discoverable.
  const [taskPickerOpen, setTaskPickerOpen] = useState(true);
  const fullWidthCapabilities = view === 'capabilities';
  const [resumingReport, setResumingReport] = useState(false); const [reportResumeError, setReportResumeError] = useState(''); const [earlyCapabilityRows, setEarlyCapabilityRows] = useState(null);
  const contentRef = useRef(null);
  const stageNavRef = useRef(null);
  const live = useLiveInteractions(run, view === 'interactions' || (view === 'reports' && !['completed', 'cancelled', 'archived'].includes(run?.status)));
  useEffect(() => { setTaskQuery(''); setTaskStatus('all'); }, [view]);
  /* The stage strip scrolls sideways once the window is narrow, and the stage
     you just opened can land outside the visible slice. Nudge it into view so
     the current position is always legible. */
  useEffect(() => {
    const strip = stageNavRef.current;
    const active = strip?.querySelector('button.active');
    if (!active || strip.scrollWidth <= strip.clientWidth) return;
    active.scrollIntoView({behavior: 'smooth', block: 'nearest', inline: 'center'});
  }, [view]);
  useEffect(() => { setResumingReport(false); setReportResumeError(''); }, [run?.run_id]);
  // Keep the last rendered artifact while a background poll refreshes it. The
  // previous implementation cleared `payload` on every status transition,
  // briefly replacing a perfectly usable page with a skeleton (visible as
  // frequent flashing during long runs).
  useEffect(() => { setPayload(null); setEarlyCapabilityRows(null); }, [view, run?.run_id]);
  // Deep-thinking/reference-research merges are append-only and can land
  // after the report body was first read.  Refresh the report's capability
  // projection on the shared change signal so the visible "深研补充（待核验）"
  // section is updated without rewriting the stored report text.
  useEffect(() => {
    if (view !== 'reports' || !run?.run_id) return undefined;
    let cancelled = false;
    const refreshCapabilities = async event => {
      const changedRunId = String(event?.detail?.runId || '').trim();
      if (changedRunId && changedRunId !== String(run.run_id)) return;
      const inlineCapability = event?.detail?.capability;
      if (inlineCapability && typeof inlineCapability === 'object') {
        setEarlyCapabilityRows(current => {
          const rows = Array.isArray(current) ? current : [];
          const identity = String(inlineCapability.hypothesis_id || inlineCapability.card_binding_id || inlineCapability.capability_id || '').trim();
          if (!identity) return rows;
          const index = rows.findIndex(row => String(row?.hypothesis_id || row?.card_binding_id || row?.capability_id || '').trim() === identity);
          if (index < 0) return [...rows, inlineCapability];
          return rows.map((row, rowIndex) => rowIndex === index ? {...row, ...inlineCapability} : row);
        });
      }
      const value = await request(runApiPath(run.run_id, '/capabilities'), [], {headers: deepScopeHeadersForRun(run)});
      if (!cancelled && Array.isArray(value) && value.length) setEarlyCapabilityRows(value);
    };
    window.addEventListener('equipment-capabilities-changed', refreshCapabilities);
    return () => { cancelled = true; window.removeEventListener('equipment-capabilities-changed', refreshCapabilities); };
  }, [view, run?.run_id]);
  useEffect(() => {
    let cancelled = false;
    if (view === 'interactions') return undefined;
    if (!run) { setLoading(false); return undefined; }
    const routes = {evidence: '/domain/EvidenceCard', winning: '/winning-mechanism'};
    setLoading(true);
    let load;
    if (view === 'capabilities') {
      const projectCapabilities = (rows, interactions = null) => {
        const candidates = interactions?.workflow?.swarm_cluster?.candidate_lineage || [];
        const portfolio = interactions?.workflow?.swarm_cluster?.final_equipment_portfolio
          || interactions?.workflow?.swarm_cluster?.portfolio_decision?.final_equipment_portfolio
          || [];
        const portfolioByHypothesis = new Map(portfolio.filter(item => item?.hypothesis_id).map(item => [String(item.hypothesis_id), item]));
        const portfolioByName = new Map(portfolio.filter(item => item?.name).map(item => [normalizeFavoriteText(item.name), item]));
        const sourceRows = Array.isArray(rows) ? rows : [];
        const legacyFailures = sourceRows.filter(row => String(row.portrait_authoring_status || '').startsWith('legacy') && (!(row.operational_process || []).length || !String(row.scientific_principle || '').trim() || !String(row.capability_outcome || '').trim() || !String(row.winning_mechanism || '').trim()));
        const failedNames = new Set([...candidates.filter(candidate => candidate.s6_authoring_failed === true).flatMap(candidate => [weaponCandidateTitle(candidate), weaponCandidateForm(candidate)]), ...legacyFailures.flatMap(row => [row.name, row.equipment_form])].map(value => String(value || '').trim()).filter(Boolean));
        const migratedReferences = legacyFailures.map(row => ({hypothesis_id: row.hypothesis_id || row.capability_id, title: row.name, primary_equipment_identity: row.equipment_form || row.name, reference_overview: row.problem_statement || row.capability_gap || row.source_winning_logic, status: 'reference', selection_status: 'reference', s6_eligible: false, s6_authoring_failed: true}));
        const scoredRows = sourceRows.map(row => {
          const portfolioItem = portfolioByHypothesis.get(String(row?.hypothesis_id || '')) || portfolioByName.get(normalizeFavoriteText(row?.name || row?.equipment_form));
          return portfolioItem ? {...row, s5_dimension_scores: portfolioS5Scores(portfolioItem), s5_weighted_score: portfolioItem.s5_weighted_score ?? weightedS5Score(portfolioS5Scores(portfolioItem)), s5_innovation_basis: portfolioItem.innovation_basis || ''} : row;
        });
        return {rows: scoredRows.filter(row => !failedNames.has(String(row.name || '').trim()) && !failedNames.has(String(row.equipment_form || '').trim())), referenceWeapons: [...candidates.filter(candidate => candidate.s6_eligible !== true && hasWeaponCandidateIdentity(candidate)), ...migratedReferences]};
      };
      // Capability images are the page's primary content. Render them as soon
      // as the small image artifact arrives, then enrich with candidate lineage
      // in the background for legacy/reference cards.
      load = request(runApiPath(run.run_id, '/capabilities'), null, {headers: {'X-Role': 'analyst'}}).then(rows => {
        if (Array.isArray(rows) && rows.length) return rows;
        return request(runApiPath(run.run_id, '/capabilities'), [], {headers: {'X-Role': 'analyst'}});
      }).then(rows => {
        const initial = projectCapabilities(rows);
        if (!cancelled) setPayload(initial);
        void request(runApiPath(run.run_id, '/interactions?compact=true'), null, {headers: {'X-Role': 'analyst'}}).then(interactions => {
          if (!cancelled) setPayload(current => ({...(current || initial), ...projectCapabilities(rows, interactions)}));
        });
        return initial;
      });
    } else if (view === 'reports') {
      // Start both reads together, but publish the small S6 artifact as soon as
      // it arrives. Waiting for the report promise here would defeat the
      // report page's early-capability contract on a slow report response.
      void request(runApiPath(run.run_id, '/capabilities'), [], {headers: {'X-Role': 'analyst'}}).then(capabilities => {
        if (!cancelled) setEarlyCapabilityRows(Array.isArray(capabilities) ? capabilities : []);
      });
      load = request(runApiPath(run.run_id, '/report'), null, {headers: {'X-Role': 'analyst'}});
    } else {
      load = request(runApiPath(run.run_id, routes[view]), null, {headers: {'X-Role': 'analyst'}});
    }
    load.then(value => {
      // An empty/failed report read must not replace the null sentinel: doing
      // so would make the renderer choose ReportView with a blank body and
      // hide an already durable capability image. Keep polling until a real
      // report body arrives or an explicit Reporter failure is observed.
      if (!cancelled && (view !== 'reports' || (typeof value === 'string' && value.trim()))) {
        setPayload(value);
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [view, run?.run_id, run?.status]);
  // S6 persists capability_images.json immediately before the potentially
  // long-running Reporter call. The first parallel request can race that
  // write, so keep checking the small capability endpoint independently of
  // the report request. Once the image is visible, continue a low-frequency
  // report poll so the completed正文 replaces the image without requiring a
  // manual refresh or a run-status transition. Stop only after正文 or a
  // terminal Reporter event is observed; there is no report hard timeout.
  const reportLifecycleStatus = latestReporterPhaseStatus(
    live.data?.events || [],
    run?.status === 'completed',
    // Do not fold a generic run failure into the Reporter lifecycle here.
    // The run may have failed upstream while a deferred Reporter process is
    // still flushing its artifact.
    false,
  );
  const reporterEvents = live.data?.events || [];
  const reporterStarted = reporterEvents.some(event => {
    const details = event.details || {};
    return (
      (event.event_type === 'agent_task_delegated' && details.target_agent_id === 'reporter')
      || event.actor === 'reporter'
      || String(event.event_type || '').startsWith('report_model_')
      || event.event_type === 'report_completed'
    );
  });
  const explicitReporterFailure = reporterEvents.some(
    event => event.event_type === 'report_model_failed',
  );
  // A prior failed attempt must not permanently stop polling after checkpoint
  // resume. The lifecycle reducer lets later Reporter activity move the phase
  // back to running; only the current failure/cancellation state is terminal.
  const reportTerminalFailure = explicitReporterFailure
    || reportLifecycleStatus === 'failed'
    // A run-level failure can be emitted before the deferred Reporter flushes
    // its artifact. Keep polling in that case; only an explicit Reporter
    // failure or cancellation/archive is terminal for the report pane.
    || ['cancelled', 'archived'].includes(run?.status)
    || (run?.status === 'failed' && !reporterStarted);
  useEffect(() => {
    const reportBodyReady = payload != null && String(payload).trim().length > 0;
    if (view !== 'reports' || !run || reportBodyReady || reportTerminalFailure) return undefined;
    // A run can reach a terminal status while the Reporter is still flushing
    // its file. Keep polling for completed/failed runs until the report itself
    // or an explicit Reporter terminal event is observed; only cancellation
    // and archival are final for this view.
    if (['cancelled', 'archived'].includes(run.status)) return undefined;
    let cancelled = false;
    let inFlight = false;
    const pollReportAndCapabilities = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        // Keep these requests independent: a slow/blocked report read must not
        // delay the capability image, which is intentionally available first.
        const reportRequest = request(runApiPath(run.run_id, '/report'), null, {headers: {'X-Role': 'analyst'}}).then(report => {
          if (!cancelled && typeof report === 'string' && report.trim()) setPayload(report);
        });
        const capabilitiesRequest = earlyCapabilityRows?.length
          ? Promise.resolve()
          : request(runApiPath(run.run_id, '/capabilities'), [], {headers: {'X-Role': 'analyst'}}).then(capabilities => {
            if (!cancelled && Array.isArray(capabilities) && capabilities.length) setEarlyCapabilityRows(capabilities);
          });
        await Promise.allSettled([reportRequest, capabilitiesRequest]);
      } finally {
        inFlight = false;
      }
    };
    const timer = setInterval(() => { void pollReportAndCapabilities(); }, earlyCapabilityRows?.length ? 4000 : 1500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [view, run?.run_id, run?.status, payload, earlyCapabilityRows?.length, reportTerminalFailure]);
  const item = nav.find(row => row[0] === view); const current = view === 'interactions' ? live.data : payload; const busy = view === 'interactions' ? live.loading : view === 'reports' ? loading || (live.loading && !live.data) : loading;
  const hasTaskNavigator = ['interactions', 'evidence', 'winning', 'capabilities', 'reports'].includes(view); const availableRuns = (runs || []).filter(itemRun => itemRun.status !== 'archived'); const visibleRuns = availableRuns.filter(itemRun => (!taskQuery.trim() || `${itemRun.topic} ${itemRun.supplemental_information || ''} ${itemRun.run_id}`.toLowerCase().includes(taskQuery.trim().toLowerCase())) && (taskStatus === 'all' || taskStatus === 'active' && isRunActive(itemRun, runtime) || taskStatus === itemRun.status)); const contextLabel = {interactions:'当前交互任务',evidence:'当前证据任务',winning:'当前 S1–S6 任务',capabilities:'当前能力画像任务',reports:'当前研究报告'}[view] || '当前研究任务';
  const reportPhase = (live.data?.workflow?.phases || []).find(phase => phase.id === 'report');
  const reportPhaseStatus = run?.status === 'completed' ? 'completed' : reportPhase?.status || latestReporterPhaseStatus(live.data?.events || [], false, run?.status === 'failed');
  const reportFailureEvent = [...(live.data?.events || [])].reverse().find(event => event.event_type === 'report_model_failed');
  const reportFailureDetail = reportPhase?.error || reportFailureEvent?.details?.detail || run?.error || '';
  const resumeReport = async () => { if (!run || run.status !== 'failed') return; setResumingReport(true); setReportResumeError(''); const result = await requestResult(runApiPath(run.run_id, '/resume'), {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID(), 'X-Role': 'analyst'}}); setResumingReport(false); if (result.ok) { setPayload(null); selectRun(result.data); } else setReportResumeError(result.detail || '断点恢复失败，请检查 Worker 与模型配置。'); };
  const chooseTask = itemRun => {
    selectRun(itemRun);
    setTaskPickerOpen(false);
    if (window.matchMedia('(max-width: 900px)').matches) {
      window.requestAnimationFrame(() => contentRef.current?.scrollIntoView({behavior:'smooth', block:'start'}));
    }
  };
  const earlyCapabilityLabel = ['completed', 'failed', 'cancelled', 'archived'].includes(run?.status)
    ? '报告正文暂不可读，先展示已完成的能力图像'
    : '报告仍在后台撰写，先展示已完成的能力图像';
  const capabilityProps = {favoriteIndex, onFavoriteToggle, highlightedCardKey: focusCardKey, run};
  const content = !run ? (loaded ? <Empty text="请选择研究任务"/> : <PaneSkeleton/>) : busy && current == null && !(view === 'reports' && earlyCapabilityRows?.length) ? <PaneSkeleton/> : view === 'reports' && reportPhaseStatus === 'failed' ? <ReportFailureView run={run} detail={reportFailureDetail} resuming={resumingReport} resume={resumeReport} error={reportResumeError} capabilityRows={earlyCapabilityRows || []} {...capabilityProps}/> : current == null && view === 'reports' && earlyCapabilityRows?.length ? <section className="report-view enhanced"><div><span><FileCheck2 size={18}/><b>研究报告</b></span><em>{earlyCapabilityLabel}</em></div><CapabilityImageView rows={earlyCapabilityRows} referenceWeapons={[]} runId={run?.run_id} run={run} {...capabilityProps}/></section> : current == null ? <Empty text={run?.historical_snapshot ? '历史快照未包含原始产物' : run.status === 'completed' ? '产物读取失败，请刷新后重试' : '任务完成后可查看本页'}/> : view === 'interactions' ? <InteractionView data={current} live={live.connected && !['completed', 'failed', 'cancelled', 'archived'].includes(run.status)} completed={run.status === 'completed'} terminalStatus={run.status}/> : view === 'reports' ? <ReportView text={current} run={run} capabilityRows={earlyCapabilityRows || []} {...capabilityProps}/> : view === 'winning' ? <WinningMechanismView data={current}/> : <ObjectGrid view={view} rows={current} runId={run?.run_id} run={run} {...capabilityProps}/>;
  const availableTotal = Math.max(0, Number(runTotal || availableRuns.length) - Number(runStatusCounts.archived || 0));
  return <><PageTitle eyebrow={hasTaskNavigator ? '交互中心' : '研究运行产物'} title={item?.[1] || '研究运行产物'} subtitle={hasTaskNavigator ? '直接选择研究任务，连续查看交互、证据、S Agent、能力画像和研究报告产物。' : run ? `当前任务：${run.topic}` : '请在研究任务列表中选择一项运行。'}/>{hasTaskNavigator && <nav className="workspace-stage-nav" ref={stageNavRef} aria-label="当前任务产物导航"><button onClick={() => navigate('runs', {run:null})}><Archive size={15}/>研究任务</button><section className="workspace-artifact-card" aria-label="当前任务产物导航"><span>当前任务产物</span><div>{[['capabilities','能力图像',FlaskConical],['reports','研究报告',FileCheck2]].map(([stage,label,StageIcon]) => <button key={stage} className={view === stage ? 'active' : ''} aria-current={view === stage ? 'page' : undefined} disabled={!run} onClick={() => navigate(stage, {run})}><StageIcon size={15}/>{label}</button>)}</div></section></nav>}{hasTaskNavigator ? <div className={`task-review-workspace ${run ? 'has-selected-task' : ''} ${fullWidthCapabilities ? 'capability-workspace' : ''}`}><section className="task-review-rail">{fullWidthCapabilities && <button type="button" className="task-picker-toggle" aria-expanded={!run || taskPickerOpen} aria-controls="capability-task-picker" onClick={() => setTaskPickerOpen(open => !open)} disabled={!run}><ListFilter size={17}/><span><b>研究任务</b><small>{run ? run.topic : '选择任务，查看能力画像'}</small></span><em>{!run || taskPickerOpen ? '收起任务列表' : '切换任务'}</em><ChevronDown size={16}/></button>}<div id={fullWidthCapabilities ? 'capability-task-picker' : undefined} hidden={fullWidthCapabilities && !!run && !taskPickerOpen}><header><div><ListFilter size={17}/><span><b>研究任务</b><small>{visibleRuns.length} / {availableTotal}</small></span></div></header><div className="task-review-filters"><div className="searchbox"><Search size={15}/><input value={taskQuery} onChange={event => setTaskQuery(event.target.value)} placeholder="搜索任务或运行 ID"/></div><select value={taskStatus} onChange={event => setTaskStatus(event.target.value)}><option value="all">全部状态</option><option value="active">进行中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="draft">草稿</option></select></div><div className="task-review-list">{visibleRuns.length ? visibleRuns.map(itemRun => <button className={run?.run_id === itemRun.run_id ? 'selected' : ''} key={itemRun.run_id} onClick={() => chooseTask(itemRun)}><span><b>{itemRun.topic}</b><small>{itemRun.run_id}</small></span><div><Status value={itemRun.status}/><em>{routeLabel(itemRun.research_route)}</em></div></button>) : !loaded ? <div className="task-row-skeletons" aria-hidden="true">{[0, 1, 2, 3, 4].map(index => <TaskRowSkeleton key={index}/>)}</div> : <Empty text="当前已加载任务中没有匹配结果"/>}{hasMoreRuns && <button type="button" className="task-review-load-more" onClick={() => void loadMoreRuns()}><RefreshCw size={13}/>加载更早任务</button>}</div></div></section><section ref={contentRef} className={`task-review-content ${view}`}>{run && <header className="task-review-context"><div><span>{contextLabel}</span><b>{run.topic}</b><small>{run.run_id} · {routeLabel(run.research_route)} · {statusLabel(run.status)}</small></div><Status value={run.status}/></header>}{content}</section></div> : content}</>;
}

function BenchmarkPage() {
  const [overview, setOverview] = useState(null); const [detail, setDetail] = useState(null); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [datasetId, setDatasetId] = useState('fixture-smoke'); const [datasetName, setDatasetName] = useState('expert-local-v1'); const [total, setTotal] = useState(132); const [pilotCount, setPilotCount] = useState(12); const [allowUnreviewed, setAllowUnreviewed] = useState(false); const [file, setFile] = useState(null); const [importing, setImporting] = useState(false);
  const [datasetQueries, setDatasetQueries] = useState([]); const [queryLoading, setQueryLoading] = useState(false); const [querySearch, setQuerySearch] = useState(''); const [querySplitFilter, setQuerySplitFilter] = useState('all'); const [selectedQueryIds, setSelectedQueryIds] = useState([]);
  const [projectRunByQuery, setProjectRunByQuery] = useState({}); const [baselineReports, setBaselineReports] = useState([]); const [baselineReportByQuery, setBaselineReportByQuery] = useState({});
  const [mode, setMode] = useState('fake'); const [split, setSplit] = useState('pilot'); const [limit, setLimit] = useState(1); const [evalId, setEvalId] = useState(''); const [externalConfirmed, setExternalConfirmed] = useState(false); const [starting, setStarting] = useState(false); const [baselineConcurrency, setBaselineConcurrency] = useState(4);
  const [useAgent, setUseAgent] = useState(true); const [useBareLlm, setUseBareLlm] = useState(true); const [useZhipu, setUseZhipu] = useState(true);
  const [agentCredentialSource, setAgentCredentialSource] = useState('project_env'); const [agentPreset, setAgentPreset] = useState('custom'); const [agentBaseUrl, setAgentBaseUrl] = useState(''); const [agentApiKey, setAgentApiKey] = useState(''); const [agentModel, setAgentModel] = useState(LLM_PRESETS.openai.model); const [agentReasoning, setAgentReasoning] = useState('high');
  const [llmCredentialSource, setLlmCredentialSource] = useState('project_env'); const [llmPreset, setLlmPreset] = useState('custom'); const [llmProtocol, setLlmProtocol] = useState(LLM_PRESETS.openai.api_protocol); const [llmBaseUrl, setLlmBaseUrl] = useState(''); const [llmApiKey, setLlmApiKey] = useState(''); const [llmModel, setLlmModel] = useState(LLM_PRESETS.openai.model); const [llmTemperature, setLlmTemperature] = useState(0.2);
  const [zhipuCredentialSource, setZhipuCredentialSource] = useState('eval_env'); const [zhipuBaseUrl, setZhipuBaseUrl] = useState(LLM_PRESETS.zhipu.base_url); const [zhipuApiKey, setZhipuApiKey] = useState(''); const [zhipuModel, setZhipuModel] = useState(LLM_PRESETS.zhipu.model); const [zhipuTemperature, setZhipuTemperature] = useState(0.2);
  const [judgeMode, setJudgeMode] = useState('fake'); const [judgeRuntime, setJudgeRuntime] = useState('llm_api'); const judgeAuthMode = 'eval_api_key'; const [judgeCredentialSource, setJudgeCredentialSource] = useState('project_env'); const [judgePreset, setJudgePreset] = useState('custom'); const [judgeProtocol, setJudgeProtocol] = useState(LLM_PRESETS.openai.api_protocol); const [judgeBaseUrl, setJudgeBaseUrl] = useState(''); const [judgeApiKey, setJudgeApiKey] = useState(''); const [judgeModel, setJudgeModel] = useState(LLM_PRESETS.openai.model); const [judgeTemperature, setJudgeTemperature] = useState(0); const [judgeMaxTokens, setJudgeMaxTokens] = useState(2500); const [judgeReplicas, setJudgeReplicas] = useState(2); const [environmentDefaultsApplied, setEnvironmentDefaultsApplied] = useState(false);
  const [judgePrompt, setJudgePrompt] = useState(''); const [judgePromptInitialized, setJudgePromptInitialized] = useState(false);
  const [recordEditor, setRecordEditor] = useState(null); const [savingRecord, setSavingRecord] = useState(false); const [deletingRecord, setDeletingRecord] = useState(''); const [cancellingRecord, setCancellingRecord] = useState('');
  const load = async (preferredRun = null) => {
    const value = await request('/benchmarks/overview', null, {headers: {'X-Role': 'analyst'}});
    if (!value) { setError('Benchmark API 不可用，请确认后端已重启并包含 evals 旁路模块。'); setLoading(false); return; }
    setOverview(value); setLoading(false);
    if (!judgePromptInitialized && value.judge_prompt?.content) { setJudgePrompt(value.judge_prompt.content); setJudgePromptInitialized(true); }
    if (!value.datasets.some(item => item.dataset_id === datasetId) && value.datasets.length) setDatasetId(value.datasets[0].dataset_id);
    const target = preferredRun === false ? value.runs[0]?.eval_id : preferredRun || detail?.eval_id || value.runs[0]?.eval_id;
    if (target) {
      const runDetail = await request(`/benchmarks/runs/${target}`, null, {headers: {'X-Role': 'analyst'}});
      if (runDetail) { setDetail(runDetail); if (!['queued', 'running', 'cancelling'].includes(runDetail.status)) { const reports = await request(`/benchmarks/reports?dataset_id=${encodeURIComponent(runDetail.dataset_id || datasetId)}`, null, {headers: {'X-Role': 'analyst'}}); if ((runDetail.dataset_id || datasetId) === datasetId) setBaselineReports(reports?.reports || []); } }
    } else setDetail(null);
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    const projectEnvironment = overview?.configuration?.project_environment;
    if (!projectEnvironment || environmentDefaultsApplied) return;
    if (projectEnvironment.base_url) { setAgentBaseUrl(projectEnvironment.base_url); setLlmBaseUrl(projectEnvironment.base_url); setJudgeBaseUrl(projectEnvironment.base_url); }
    if (projectEnvironment.model) { setAgentModel(projectEnvironment.model); setLlmModel(projectEnvironment.model); setJudgeModel(projectEnvironment.model); }
    if (projectEnvironment.api_protocol) { setLlmProtocol(projectEnvironment.api_protocol); setJudgeProtocol(projectEnvironment.api_protocol); }
    setEnvironmentDefaultsApplied(true);
  }, [overview?.configuration?.project_environment, environmentDefaultsApplied]);
  useEffect(() => { if (!datasetId) return; let cancelled = false; setQueryLoading(true); setSelectedQueryIds([]); setProjectRunByQuery({}); setBaselineReportByQuery({}); Promise.all([request(`/benchmarks/datasets/${encodeURIComponent(datasetId)}/queries`, null, {headers: {'X-Role': 'analyst'}}), request(`/benchmarks/reports?dataset_id=${encodeURIComponent(datasetId)}`, null, {headers: {'X-Role': 'analyst'}})]).then(([queryValue, reportValue]) => { if (!cancelled) { setDatasetQueries(queryValue?.queries || []); setBaselineReports(reportValue?.reports || []); } }).finally(() => { if (!cancelled) setQueryLoading(false); }); return () => { cancelled = true; }; }, [datasetId]);
  useEffect(() => { const researchRuns = overview?.research_runs || []; if (!selectedQueryIds.length || !researchRuns.length) return; setProjectRunByQuery(current => { const next = {...current}; selectedQueryIds.forEach(queryId => { if (next[queryId]) return; const query = datasetQueries.find(item => item.query_id === queryId); const exact = researchRuns.find(run => String(run.topic || '').trim() === String(query?.query || '').trim()); if (exact) next[queryId] = exact.run_id; }); return next; }); }, [selectedQueryIds.join('|'), datasetQueries, overview?.research_runs]);
  useEffect(() => { if (!selectedQueryIds.length) return; const systems = [...(useAgent ? ['generic_agent'] : []), ...(useBareLlm ? ['bare_llm'] : []), ...(useZhipu ? ['zhipu_llm'] : [])]; setBaselineReportByQuery(current => { const next = {...current}; selectedQueryIds.forEach(queryId => { const row = {...(next[queryId] || {})}; systems.forEach(systemId => { if (Object.prototype.hasOwnProperty.call(row, systemId)) return; row[systemId] = baselineReports.find(report => report.query_id === queryId && report.system_id === systemId)?.report_id || 'fresh'; }); next[queryId] = row; }); return next; }); }, [selectedQueryIds.join('|'), useAgent, useBareLlm, useZhipu, baselineReports]);
  useEffect(() => { if (!detail || !['queued', 'running', 'cancelling'].includes(detail.status)) return undefined; const timer = setInterval(() => void load(detail.eval_id), 1800); return () => clearInterval(timer); }, [detail?.eval_id, detail?.status]);
  const projectEnvironment = overview?.configuration?.project_environment || {};
  const credentialReady = (source, apiKey) => source === 'project_env' ? Boolean(projectEnvironment.ready) : Boolean(apiKey);
  const selectAgentCredentialSource = value => { setAgentCredentialSource(value); if (value === 'project_env') { setAgentBaseUrl(projectEnvironment.base_url || ''); setAgentModel(projectEnvironment.model || LLM_PRESETS.openai.model); } };
  const selectLlmCredentialSource = value => { setLlmCredentialSource(value); if (value === 'project_env') { setLlmBaseUrl(projectEnvironment.base_url || ''); setLlmModel(projectEnvironment.model || LLM_PRESETS.openai.model); setLlmProtocol(projectEnvironment.api_protocol || 'responses'); } };
  const selectJudgeCredentialSource = value => { setJudgeCredentialSource(value); if (value === 'project_env') { setJudgeBaseUrl(projectEnvironment.base_url || ''); setJudgeModel(projectEnvironment.model || LLM_PRESETS.openai.model); setJudgeProtocol(projectEnvironment.api_protocol || 'responses'); } };
  const importDefault = async () => {
    setImporting(true); setError('');
    const result = await requestResult('/benchmarks/datasets/default-import', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({dataset_id: datasetName, total, pilot_count: pilotCount, allow_unreviewed: allowUnreviewed})});
    setImporting(false); if (!result.ok) { setError(result.detail || '导入失败'); return; } setDatasetId(result.data.dataset_id); await load();
  };
  const uploadDataset = async () => {
    if (!file) { setError('请先选择 .xlsx 或 .jsonl 文件。'); return; }
    setImporting(true); setError('');
    try {
      const content = await fileToBase64(file);
      const result = await requestResult('/benchmarks/datasets/upload', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({dataset_id: datasetName, filename: file.name, content_base64: content, total, pilot_count: pilotCount, allow_unreviewed: allowUnreviewed})});
      if (!result.ok) setError(result.detail || '上传导入失败'); else { setDatasetId(result.data.dataset_id); await load(); }
    } catch (reason) { setError(reason?.message || '读取本地文件失败'); }
    setImporting(false);
  };
  const start = async ({prepareOnly = false} = {}) => {
    const effectiveJudgeMode = prepareOnly ? 'none' : judgeMode;
    const agentExecutionRequired = useAgent && (prepareOnly || selectedQueryIds.some(queryId => (baselineReportByQuery[queryId]?.generic_agent || 'fresh') === 'fresh'));
    const llmExecutionRequired = useBareLlm && (prepareOnly || selectedQueryIds.some(queryId => (baselineReportByQuery[queryId]?.bare_llm || 'fresh') === 'fresh'));
    const zhipuExecutionRequired = useZhipu && (prepareOnly || selectedQueryIds.some(queryId => (baselineReportByQuery[queryId]?.zhipu_llm || 'fresh') === 'fresh'));
    const externalDataRequired = (mode === 'real' && (agentExecutionRequired || llmExecutionRequired || zhipuExecutionRequired)) || effectiveJudgeMode === 'real';
    if (externalDataRequired && !externalConfirmed) { setError('真实运行或真实评审必须确认 Query、回答与必要上下文会发送至外部模型服务。'); return; }
    if (!useAgent && !useBareLlm && !useZhipu) { setError('请至少选择一个 baseline。'); return; }
    if (!selectedQueryIds.length) { setError('请先选择要执行或评审的 Query。'); return; }
    const missingProjectRuns = selectedQueryIds.filter(queryId => !projectRunByQuery[queryId]);
    if (effectiveJudgeMode !== 'none' && missingProjectRuns.length) { setError(`以下 Query 尚未选择项目研究报告：${missingProjectRuns.join('、')}`); return; }
    if (mode === 'real' && agentExecutionRequired && (!agentBaseUrl.trim() || !credentialReady(agentCredentialSource, agentApiKey) || !agentModel.trim())) { setError('通用 Codex Agent 真实模式需要可用的项目环境凭据，或填写本轮 API URL、API Key 和模型。'); return; }
    if (mode === 'real' && llmExecutionRequired && (!llmBaseUrl.trim() || !credentialReady(llmCredentialSource, llmApiKey) || !llmModel.trim())) { setError('纯 LLM 真实模式需要可用的项目环境凭据，或填写本轮 API URL、API Key 和模型。'); return; }
    const zhipuCredentialReady = zhipuCredentialSource === 'eval_env' ? Boolean(config?.providers?.zhipu?.ready) : Boolean(zhipuApiKey);
    if (mode === 'real' && zhipuExecutionRequired && (!zhipuBaseUrl.trim() || !zhipuCredentialReady || !zhipuModel.trim())) { setError('智谱 GLM 真实模式需要配置评测环境凭据，或填写本轮 API URL、API Key 和模型。'); return; }
    const judgeNeedsApi = true;
    if (effectiveJudgeMode === 'real' && !judgeModel.trim()) { setError('真实评审需要填写评审专家模型。'); return; }
    if (effectiveJudgeMode === 'real' && judgeNeedsApi && (!judgeBaseUrl.trim() || !credentialReady(judgeCredentialSource, judgeApiKey))) { setError('当前评审方式需要可用的项目环境凭据，或填写本轮 API URL 和 API Key。'); return; }
    const missingPromptPlaceholders = (overview?.judge_prompt?.required_placeholders || []).filter(item => !judgePrompt.includes(item));
    if (effectiveJudgeMode !== 'none' && (!judgePrompt.trim() || missingPromptPlaceholders.length)) { setError(`评审 Prompt 不能为空并须保留占位符：${missingPromptPlaceholders.join('、') || 'QUERY、ANSWER_A、ANSWER_B、PAIR_ID'}`); return; }
    setStarting(true); setError('');
    const baselines = [...(useAgent ? ['generic_agent'] : []), ...(useBareLlm ? ['bare_llm'] : []), ...(useZhipu ? ['zhipu_llm'] : [])];
    const systems = baselines;
    const genericAgent = useAgent ? {credential_source: agentCredentialSource, auth_mode: 'eval_api_key', base_url: agentBaseUrl.trim(), api_key: agentCredentialSource === 'manual' ? agentApiKey : '', model: agentModel.trim(), reasoning_effort: agentReasoning} : null;
    const bareLlm = useBareLlm ? {credential_source: llmCredentialSource, api_protocol: llmProtocol, base_url: llmBaseUrl.trim(), api_key: llmCredentialSource === 'manual' ? llmApiKey : '', model: llmModel.trim(), temperature: Number(llmTemperature)} : null;
    const zhipuLlm = useZhipu ? {credential_source: zhipuCredentialSource, base_url: zhipuBaseUrl.trim(), api_key: zhipuCredentialSource === 'manual' ? zhipuApiKey : '', model: zhipuModel.trim(), temperature: Number(zhipuTemperature)} : null;
    const judgeLlm = effectiveJudgeMode === 'real' ? {credential_source: judgeCredentialSource, runtime: judgeRuntime, auth_mode: judgeAuthMode, api_protocol: judgeRuntime === 'codex_cli' ? 'responses' : judgeProtocol, base_url: judgeBaseUrl.trim(), api_key: judgeCredentialSource === 'manual' ? judgeApiKey : '', model: judgeModel.trim(), temperature: Number(judgeTemperature), max_output_tokens: Number(judgeMaxTokens), replicas: Number(judgeReplicas)} : null;
    const projectRuns = effectiveJudgeMode === 'none' ? {} : Object.fromEntries(selectedQueryIds.map(queryId => [queryId, projectRunByQuery[queryId]]));
    const savedBaselineReports = prepareOnly ? {} : Object.fromEntries(selectedQueryIds.map(queryId => { const selected = baselineReportByQuery[queryId] || {}; return [queryId, Object.fromEntries(baselines.map(systemId => [systemId, selected[systemId]]).filter(([, reportId]) => reportId && reportId !== 'fresh'))]; }).filter(([, reports]) => Object.keys(reports).length));
    const result = await requestResult('/benchmarks/runs', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({eval_id: evalId.trim() || null, dataset_id: datasetId, systems, pairwise_systems: effectiveJudgeMode === 'none' ? [] : baselines, project_runs: projectRuns, baseline_reports: savedBaselineReports, baseline_concurrency: Number(baselineConcurrency), generic_agent: genericAgent, bare_llm: bareLlm, zhipu_llm: zhipuLlm, judge_llm: judgeLlm, judge_prompt: effectiveJudgeMode === 'none' ? null : judgePrompt, query_ids: selectedQueryIds, split, limit, mode, judge_mode: effectiveJudgeMode, confirm_external_data: externalConfirmed})});
    setStarting(false); if (!result.ok) { setError(result.detail || 'Benchmark 启动失败'); return; } setAgentApiKey(''); setLlmApiKey(''); setZhipuApiKey(''); setJudgeApiKey(''); setDetail(result.data); setEvalId(''); await load(result.data.eval_id);
  };
  const applyAgentPreset = value => { const preset = LLM_PRESETS[value]; setAgentCredentialSource('manual'); setAgentPreset(value); setAgentBaseUrl(preset.base_url); setAgentModel(preset.model); };
  const applyLlmPreset = value => { const preset = LLM_PRESETS[value]; setLlmCredentialSource('manual'); setLlmPreset(value); setLlmProtocol(preset.api_protocol); setLlmBaseUrl(preset.base_url); setLlmModel(preset.model); };
  const applyJudgePreset = value => { const preset = LLM_PRESETS[value]; setJudgeCredentialSource('manual'); setJudgePreset(value); setJudgeProtocol(preset.api_protocol); setJudgeBaseUrl(preset.base_url); setJudgeModel(preset.model); };
  const openBenchmarkRecord = async evalIdValue => { const value = await request(`/benchmarks/runs/${evalIdValue}`, null, {headers: {'X-Role': 'analyst'}}); if (value) setDetail(value); };
  const editBenchmarkRecord = run => setRecordEditor({eval_id: run.eval_id, display_name: run.display_name || '', notes: run.notes || ''});
  const saveBenchmarkRecord = async () => { if (!recordEditor) return; setSavingRecord(true); setError(''); const result = await requestResult(`/benchmarks/runs/${recordEditor.eval_id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({display_name: recordEditor.display_name, notes: recordEditor.notes})}); setSavingRecord(false); if (!result.ok) { setError(result.detail || '评测记录保存失败'); return; } setRecordEditor(null); setDetail(current => current?.eval_id === result.data.eval_id ? {...current, ...result.data} : current); await load(result.data.eval_id); };
  const deleteBenchmarkRecord = async run => { if (['queued', 'running', 'cancelling'].includes(run.status) || !window.confirm(`确定删除评测记录 ${run.display_name || run.eval_id} 及其 outputs/evals 产物吗？此操作不可恢复。`)) return; setDeletingRecord(run.eval_id); setError(''); const result = await requestResult(`/benchmarks/runs/${run.eval_id}`, {method: 'DELETE', headers: {'X-Role': 'analyst'}}); setDeletingRecord(''); if (!result.ok) { setError(result.detail || '评测记录删除失败'); return; } if (detail?.eval_id === run.eval_id) setDetail(null); if (recordEditor?.eval_id === run.eval_id) setRecordEditor(null); await load(false); };
  const cancelBenchmarkRecord = async run => { if (!['queued', 'running', 'cancelling'].includes(run.status) || run.status === 'cancelling' || !window.confirm(`确定停止 Benchmark ${run.display_name || run.eval_id} 吗？\n\n系统会停止后续 Query 和评审；已经发出的外部模型请求会在当前调用返回后收敛。`)) return; setCancellingRecord(run.eval_id); setError(''); const result = await requestResult(`/benchmarks/runs/${run.eval_id}/cancel`, {method: 'POST', headers: {'X-Role': 'analyst'}}); setCancellingRecord(''); if (!result.ok) { setError(result.detail || '停止 Benchmark 失败'); return; } setDetail(current => current?.eval_id === run.eval_id ? {...current, ...result.data} : current); await load(run.eval_id); };
  const config = overview?.configuration; const datasets = overview?.datasets || []; const runs = overview?.runs || []; const researchRuns = overview?.research_runs || []; const currentDataset = datasets.find(item => item.dataset_id === datasetId);
  const agentExecutionRequired = useAgent && selectedQueryIds.some(queryId => (baselineReportByQuery[queryId]?.generic_agent || 'fresh') === 'fresh');
  const llmExecutionRequired = useBareLlm && selectedQueryIds.some(queryId => (baselineReportByQuery[queryId]?.bare_llm || 'fresh') === 'fresh');
  const zhipuExecutionRequired = useZhipu && selectedQueryIds.some(queryId => (baselineReportByQuery[queryId]?.zhipu_llm || 'fresh') === 'fresh');
  const selectedSystemCount = Number(judgeMode !== 'none') + Number(useAgent) + Number(useBareLlm) + Number(useZhipu);
  const configuredSystemsReady = !agentExecutionRequired || mode === 'fake' || Boolean(config?.codex_cli?.present && agentBaseUrl.trim() && credentialReady(agentCredentialSource, agentApiKey) && agentModel.trim());
  const llmReady = !llmExecutionRequired || mode === 'fake' || Boolean(llmBaseUrl.trim() && credentialReady(llmCredentialSource, llmApiKey) && llmModel.trim());
  const zhipuCredentialReady = zhipuCredentialSource === 'eval_env' ? Boolean(config?.providers?.zhipu?.ready) : Boolean(zhipuApiKey);
  const zhipuReady = !zhipuExecutionRequired || mode === 'fake' || Boolean(zhipuBaseUrl.trim() && zhipuCredentialReady && zhipuModel.trim());
  const prepareAgentReady = !useAgent || mode === 'fake' || Boolean(config?.codex_cli?.present && agentBaseUrl.trim() && credentialReady(agentCredentialSource, agentApiKey) && agentModel.trim());
  const prepareLlmReady = !useBareLlm || mode === 'fake' || Boolean(llmBaseUrl.trim() && credentialReady(llmCredentialSource, llmApiKey) && llmModel.trim());
  const prepareZhipuReady = !useZhipu || mode === 'fake' || Boolean(zhipuBaseUrl.trim() && zhipuCredentialReady && zhipuModel.trim());
  const requiredPromptPlaceholders = overview?.judge_prompt?.required_placeholders || []; const promptReady = judgeMode === 'none' || Boolean(judgePrompt.trim() && requiredPromptPlaceholders.every(item => judgePrompt.includes(item))); const judgeReady = (judgeMode !== 'real' || Boolean(judgeModel.trim() && judgeBaseUrl.trim() && credentialReady(judgeCredentialSource, judgeApiKey) && (judgeRuntime !== 'codex_cli' || config?.codex_cli?.present))) && promptReady;
  const projectReportsReady = judgeMode === 'none' || (selectedQueryIds.length > 0 && selectedQueryIds.every(queryId => projectRunByQuery[queryId]));
  const ready = selectedQueryIds.length > 0 && configuredSystemsReady && llmReady && zhipuReady && judgeReady && projectReportsReady;
  const externalDataRequired = (mode === 'real' && (agentExecutionRequired || llmExecutionRequired || zhipuExecutionRequired)) || judgeMode === 'real';
  const baselinePrepareReady = selectedQueryIds.length > 0 && (useAgent || useBareLlm || useZhipu) && prepareAgentReady && prepareLlmReady && prepareZhipuReady;
  const baselinePrepareExternal = mode === 'real' && (useAgent || useBareLlm || useZhipu);
  const externalConfirmationRelevant = externalDataRequired || baselinePrepareExternal;
  const visibleQueries = datasetQueries.filter(item => (querySplitFilter === 'all' || item.split === querySplitFilter) && (!querySearch.trim() || `${item.query_id} ${item.query} ${item.region} ${item.domain}`.toLowerCase().includes(querySearch.trim().toLowerCase())));
  const readinessIssues = [...(!selectedQueryIds.length ? ['请选择 Query'] : []), ...(!projectReportsReady ? ['绑定全部项目报告'] : []), ...(!configuredSystemsReady ? ['通用 Codex Agent API 配置不完整'] : []), ...(!llmReady ? ['纯 LLM 配置不完整'] : []), ...(!zhipuReady ? ['智谱 GLM 配置不完整'] : []), ...(!judgeReady ? ['评审专家或 Prompt 配置不完整'] : []), ...(externalDataRequired && !externalConfirmed ? ['确认外部数据传输'] : [])]; const toggleQuery = queryId => setSelectedQueryIds(rows => rows.includes(queryId) ? rows.filter(item => item !== queryId) : [...rows, queryId]); const selectVisibleQueries = () => setSelectedQueryIds(rows => [...new Set([...rows, ...visibleQueries.map(item => item.query_id)])]);
  if (loading && !overview) return <><PageTitle eyebrow="评测旁路" title="测试 Benchmark" subtitle="正在加载评测配置与本地 Query 数据集。"/><Empty text="正在读取 Benchmark 状态"/></>;
  return <>
    <PageTitle eyebrow="评测旁路" title="测试 Benchmark" subtitle="baseline 报告可提前执行并保存；正式评审时按 Query 直接选取，无需重复调用模型。"><button className="icon-button" title="刷新 Benchmark" onClick={() => load()}><RefreshCw size={17}/></button></PageTitle>
    <section className="metric-strip benchmark-metrics"><Metric label="Query 数据集" value={datasets.length} icon={Database}/><Metric label="本轮 Query" value={selectedQueryIds.length || currentDataset?.query_count || 0} icon={FileSpreadsheet}/><Metric label="参测系统" value={selectedSystemCount} icon={Gauge}/><Metric label="所选配置就绪" value={ready ? '是' : '否'} icon={ready ? CheckCircle2 : CircleAlert}/></section>
    <section className="benchmark-boundary"><ShieldCheck size={18}/><div><b>报告复用 + baseline 旁路</b><span>项目报告来自正常研究任务；Benchmark 仅写 outputs/evals 并执行 baseline 与匿名评审。</span></div><em>existing report vs baseline</em></section>
    {SHOW_BENCHMARK_EVOLUTION && <EvolutionPanel evolution={overview?.evolution} reload={() => load(false)}/>}
    {error && <p className="form-error benchmark-error"><CircleAlert size={15}/>{error}</p>}
    <div className="benchmark-layout">
      <section className="benchmark-config-stack">
        <article className="benchmark-panel">
          <header><div><FileSpreadsheet size={18}/><span><b>1. 导入 Query 数据集</b><small>严格专家集或本地候选测试集</small></span></div><span className={`benchmark-ready ${overview?.default_workbook?.available ? 'yes' : ''}`}>{overview?.default_workbook?.available ? '默认文件可用' : '默认文件不可用'}</span></header>
          <div className="benchmark-source"><small>默认专家表</small><p title={overview?.default_workbook?.path}>{overview?.default_workbook?.filename || '未配置'}</p></div>
          <div className="benchmark-form-grid"><Field label="数据集 ID"><input value={datasetName} onChange={event => setDatasetName(event.target.value)} placeholder="expert-local-v1"/></Field><Field label="总题量"><input type="number" min="1" max="300" value={total} onChange={event => setTotal(Number(event.target.value))}/></Field><Field label="Pilot 数量"><input type="number" min="0" max={total} value={pilotCount} onChange={event => setPilotCount(Number(event.target.value))}/></Field></div>
          <label className="benchmark-check"><input type="checkbox" checked={allowUnreviewed} onChange={event => setAllowUnreviewed(event.target.checked)}/><span><b>允许未完成专家复核的候选</b><small>仅用于本地功能测试；取消勾选后严格要求复核/仲裁通过、可研究且质量 ≥ 3。</small></span></label>
          <div className="benchmark-import-actions"><button disabled={importing || !overview?.default_workbook?.available} onClick={importDefault}><Database size={15}/>{importing ? '导入中' : '导入默认专家表'}</button><label className="file-button"><Upload size={15}/><span>{file ? file.name : '选择本地 .xlsx/.jsonl'}</span><input type="file" accept=".xlsx,.jsonl" onChange={event => setFile(event.target.files?.[0] || null)}/></label><button className="primary" disabled={importing || !file} onClick={uploadDataset}>上传并导入</button></div>
          <div className="dataset-list">{datasets.map(item => <button className={datasetId === item.dataset_id ? 'selected' : ''} key={item.dataset_id} onClick={() => setDatasetId(item.dataset_id)}><span><b>{item.dataset_id}</b><small>{datasetModeLabel(item.selection_mode)} · {item.source_name}</small></span><em>{item.query_count} 条</em></button>)}</div>
          <section className="benchmark-query-picker"><div className="benchmark-query-picker-head"><span><b>选择本轮 Query</b><small>{selectedQueryIds.length ? `已选择 ${selectedQueryIds.length} 条；本轮只运行所选题目` : '未选择时使用下方数据划分和题数'}</small></span><em>{visibleQueries.length} / {datasetQueries.length}</em></div><div className="benchmark-query-toolbar"><div className="searchbox"><Search size={15}/><input value={querySearch} onChange={event => setQuerySearch(event.target.value)} placeholder="搜索 Query、区域或领域"/></div><select value={querySplitFilter} onChange={event => setQuerySplitFilter(event.target.value)}><option value="all">全部划分</option><option value="pilot">Pilot</option><option value="test">Test</option></select><button disabled={!visibleQueries.length} onClick={selectVisibleQueries}>选择当前筛选</button><button disabled={!selectedQueryIds.length} onClick={() => setSelectedQueryIds([])}>清空</button></div><div className="benchmark-query-list">{queryLoading ? <Empty text="正在读取 Query"/> : visibleQueries.length ? visibleQueries.map(item => <label className={selectedQueryIds.includes(item.query_id) ? 'selected' : ''} key={item.query_id}><input type="checkbox" checked={selectedQueryIds.includes(item.query_id)} onChange={() => toggleQuery(item.query_id)}/><span><b>{item.query_id} · {item.query}</b><small>{item.region} · {item.domain} · {difficultyLabel(item.difficulty)} · {item.split === 'pilot' ? 'Pilot' : 'Test'}</small></span></label>) : <Empty text="没有匹配的 Query"/>}</div></section>
          <section className="benchmark-project-reports"><div className="benchmark-query-picker-head"><span><b>绑定项目研究报告</b><small>{judgeMode === 'none' ? '预执行 baseline 时可暂不绑定；开始评审后再选择完整方法报告' : '完整方法不重跑；每条 Query 复用已完成研究任务报告'}</small></span><em>{selectedQueryIds.filter(queryId => projectRunByQuery[queryId]).length} / {selectedQueryIds.length}</em></div>{selectedQueryIds.length ? selectedQueryIds.map(queryId => { const query = datasetQueries.find(item => item.query_id === queryId); return <Field label={`${queryId} · ${query?.query || ''}`} key={queryId}><select value={projectRunByQuery[queryId] || ''} onChange={event => setProjectRunByQuery(rows => ({...rows, [queryId]: event.target.value}))}><option value="">{judgeMode === 'none' ? '暂不绑定（仅预执行 baseline）' : '选择已完成研究任务'}</option>{researchRuns.map(run => <option value={run.run_id} key={run.run_id}>{run.topic} · {run.run_id}</option>)}</select></Field>; }) : <Empty text="先选择 Query，再绑定对应研究任务报告"/>}</section>
          <section className="benchmark-project-reports benchmark-baseline-reports"><div className="benchmark-query-picker-head"><span><b>选择 baseline 报告</b><small>默认复用该 Query 最近一次保存的报告；选择“本轮重新执行”会生成新的可复用报告</small></span><em>{baselineReports.length} 份已保存</em></div>{selectedQueryIds.length ? selectedQueryIds.map(queryId => { const query = datasetQueries.find(item => item.query_id === queryId); const systems = [...(useAgent ? ['generic_agent'] : []), ...(useBareLlm ? ['bare_llm'] : []), ...(useZhipu ? ['zhipu_llm'] : [])]; return <div className="benchmark-baseline-query" key={queryId}><b>{queryId} · {query?.query || ''}</b>{systems.map(systemId => { const reports = baselineReports.filter(report => report.query_id === queryId && report.system_id === systemId); return <Field label={benchmarkSystemLabel(systemId)} key={systemId}><select value={baselineReportByQuery[queryId]?.[systemId] || 'fresh'} onChange={event => setBaselineReportByQuery(rows => ({...rows, [queryId]: {...(rows[queryId] || {}), [systemId]: event.target.value}}))}><option value="fresh">本轮重新执行并保存</option>{reports.map(report => <option value={report.report_id} key={report.report_id}>{report.query || query?.query || report.source_eval_id} · {report.model_snapshot?.model || report.model_snapshot?.provider?.model || '已保存模型'} · {new Date(report.created_at).toLocaleString()}</option>)}</select></Field>; })}</div>; }) : <Empty text="先选择 Query，再选择复用报告或本轮重新执行"/>}</section>
        </article>
        <article className="benchmark-panel">
          <header><div><Play size={18}/><span><b>2. 配置并启动 baseline</b><small>可先只执行并保存 baseline；评审时直接复用所选报告</small></span></div><span className={`benchmark-ready ${ready ? 'yes' : ''}`}>{ready ? '配置就绪' : '检查配置'}</span></header>
          <div className="benchmark-systems"><label className={judgeMode !== 'none' ? 'selected' : ''}><input type="checkbox" checked={judgeMode !== 'none'} readOnly/><span><b>项目研究报告</b><small>{judgeMode === 'none' ? '预执行阶段可不选择' : '复用上方已完成任务'}</small></span></label><label className={useAgent ? 'selected' : ''}><input type="checkbox" checked={useAgent} onChange={event => setUseAgent(event.target.checked)}/><span><b>通用 Agent</b><small>{agentExecutionRequired ? '本轮执行并保存' : '全部复用已保存报告'}</small></span></label><label className={useBareLlm ? 'selected' : ''}><input type="checkbox" checked={useBareLlm} onChange={event => setUseBareLlm(event.target.checked)}/><span><b>纯 LLM</b><small>{llmExecutionRequired ? '本轮执行并保存' : '全部复用已保存报告'}</small></span></label><label className={useZhipu ? 'selected' : ''}><input type="checkbox" checked={useZhipu} onChange={event => setUseZhipu(event.target.checked)}/><span><b>智谱 GLM</b><small>{zhipuExecutionRequired ? '本轮执行并保存' : '全部复用已保存报告'}</small></span></label></div>
          {useAgent && <section className="benchmark-llm-config agent"><div className="benchmark-judge-title"><Bot size={16}/><span><b>通用 Codex Agent 接口</b><small>默认复用项目环境 URL 与 API Key；密钥仅由后端读取，不下发浏览器</small></span></div><div className="benchmark-form-grid llm-top"><Field label="凭据来源"><select value={agentCredentialSource} onChange={event => selectAgentCredentialSource(event.target.value)}><option value="project_env">项目环境（默认）</option><option value="manual">本次手动填写</option></select></Field><Field label="服务预设"><select value={agentPreset} onChange={event => applyAgentPreset(event.target.value)}>{Object.entries(LLM_PRESETS).map(([id, preset]) => <option value={id} key={id}>{preset.label}</option>)}</select></Field><Field label="推理强度"><select value={agentReasoning} onChange={event => setAgentReasoning(event.target.value)}><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">XHigh</option><option value="max">Max</option></select></Field></div><div className="benchmark-form-grid llm-main"><Field label="Codex Base URL"><input value={agentBaseUrl} readOnly={agentCredentialSource === 'project_env'} onChange={event => setAgentBaseUrl(event.target.value)} placeholder="https://api.example.com/v1"/></Field><Field label="Codex 模型"><input value={agentModel} onChange={event => setAgentModel(event.target.value)} placeholder="模型 ID"/></Field></div><Field label="Codex API Key（不落盘）"><input type="password" autoComplete="new-password" readOnly={agentCredentialSource === 'project_env'} value={agentCredentialSource === 'manual' ? agentApiKey : ''} onChange={event => setAgentApiKey(event.target.value)} placeholder={agentCredentialSource === 'project_env' ? projectEnvironment.api_key_present ? `已从 ${projectEnvironment.api_key_env} 加载（不下发）` : `项目环境 ${projectEnvironment.api_key_env || 'API Key'} 未配置` : mode === 'fake' ? '离线模式可留空' : '仅在本次运行内存中使用'}/></Field><small className="benchmark-llm-note">项目环境模式使用 {projectEnvironment.base_url_env || '项目 Base URL 变量'} 与 {projectEnvironment.api_key_env || '项目 API Key 变量'}；切换服务预设会自动改为手动模式。</small></section>}
          {useBareLlm && <section className="benchmark-llm-config"><div className="benchmark-form-grid llm-top"><Field label="凭据来源"><select value={llmCredentialSource} onChange={event => selectLlmCredentialSource(event.target.value)}><option value="project_env">项目环境（默认）</option><option value="manual">本次手动填写</option></select></Field><Field label="服务预设"><select value={llmPreset} onChange={event => applyLlmPreset(event.target.value)}>{Object.entries(LLM_PRESETS).map(([id, preset]) => <option value={id} key={id}>{preset.label}</option>)}</select></Field><Field label="API 协议"><select value={llmProtocol} onChange={event => setLlmProtocol(event.target.value)}><option value="responses">Responses</option><option value="chat_completions">Chat Completions</option></select></Field></div><div className="benchmark-form-grid llm-main"><Field label="Base URL"><input value={llmBaseUrl} readOnly={llmCredentialSource === 'project_env'} onChange={event => setLlmBaseUrl(event.target.value)} placeholder="https://api.example.com/v1"/></Field><Field label="模型"><input value={llmModel} onChange={event => setLlmModel(event.target.value)} placeholder="模型 ID"/></Field></div><Field label="API Key（不落盘）"><input type="password" autoComplete="new-password" readOnly={llmCredentialSource === 'project_env'} value={llmCredentialSource === 'manual' ? llmApiKey : ''} onChange={event => setLlmApiKey(event.target.value)} placeholder={llmCredentialSource === 'project_env' ? projectEnvironment.api_key_present ? `已从 ${projectEnvironment.api_key_env} 加载（不下发）` : `项目环境 ${projectEnvironment.api_key_env || 'API Key'} 未配置` : mode === 'fake' ? '离线模式可留空' : '仅在本次运行内存中使用'}/></Field><Field label="温度"><input type="number" min="0" max="2" step="0.1" value={llmTemperature} onChange={event => setLlmTemperature(event.target.value)}/></Field><small className="benchmark-llm-note">默认复用项目环境的 Responses 兼容服务；输出预算由 baseline 后端预设统一管理。</small></section>}
          {useZhipu && <section className="benchmark-llm-config zhipu"><div className="benchmark-judge-title"><Bot size={16}/><span><b>智谱 GLM 报告生成</b><small>使用 OpenAI 兼容 Chat Completions；与其他 baseline 共用报告任务书，不启用联网工具</small></span></div><div className="benchmark-form-grid llm-top"><Field label="凭据来源"><select value={zhipuCredentialSource} onChange={event => setZhipuCredentialSource(event.target.value)}><option value="eval_env">评测环境（默认）</option><option value="manual">本次手动填写</option></select></Field><Field label="API 协议"><input value="Chat Completions" readOnly/></Field></div><div className="benchmark-form-grid llm-main"><Field label="智谱 Base URL"><input value={zhipuBaseUrl} readOnly={zhipuCredentialSource === 'eval_env'} onChange={event => setZhipuBaseUrl(event.target.value)} placeholder={LLM_PRESETS.zhipu.base_url}/></Field><Field label="智谱模型"><input value={zhipuModel} onChange={event => setZhipuModel(event.target.value)} placeholder="glm-5.2"/></Field></div><Field label="智谱 API Key（不落盘）"><input type="password" autoComplete="new-password" readOnly={zhipuCredentialSource === 'eval_env'} value={zhipuCredentialSource === 'manual' ? zhipuApiKey : ''} onChange={event => setZhipuApiKey(event.target.value)} placeholder={zhipuCredentialSource === 'eval_env' ? config?.providers?.zhipu?.api_key_present ? `已从 ${config.providers.zhipu.api_key_env} 加载（不下发）` : `评测环境 ${config?.providers?.zhipu?.api_key_env || 'EQUIPMENT_EVAL_ZHIPU_API_KEY'} 未配置` : mode === 'fake' ? '离线模式可留空' : '仅在本次运行内存中使用'}/></Field><Field label="温度"><input type="number" min="0" max="2" step="0.1" value={zhipuTemperature} onChange={event => setZhipuTemperature(event.target.value)}/></Field><small className="benchmark-llm-note">评测环境模式读取 EQUIPMENT_EVAL_ZHIPU_BASE_URL / EQUIPMENT_EVAL_ZHIPU_API_KEY；输出预算由 baseline 后端预设统一管理。</small></section>}
          <div className="benchmark-pair-plan"><ClipboardCheck size={15}/><span>{(useAgent || useBareLlm || useZhipu) ? judgeMode === 'none' ? <>本轮仅准备 baseline 报告：{[...(useAgent ? ['通用 Codex Agent'] : []), ...(useBareLlm ? ['纯 LLM'] : []), ...(useZhipu ? ['智谱 GLM'] : [])].map(item => <em key={item}>{item}</em>)}</> : <>本轮盲评对比：{[...(useAgent ? ['完整方法 vs 通用 Codex Agent'] : []), ...(useBareLlm ? ['完整方法 vs 纯 LLM'] : []), ...(useZhipu ? ['完整方法 vs 智谱 GLM'] : [])].map(item => <em key={item}>{item}</em>)}</> : '请先在上方选择至少一个 baseline'}</span></div>
          <div className="benchmark-form-grid run"><Field label="数据划分"><select disabled={selectedQueryIds.length > 0} value={split} onChange={event => setSplit(event.target.value)}><option value="pilot">Pilot</option><option value="test">Test</option><option value="all">全部</option></select></Field><Field label={selectedQueryIds.length ? '已选题数' : '本轮题数'}><input type="number" min="1" max="132" disabled={selectedQueryIds.length > 0} value={selectedQueryIds.length || limit} onChange={event => setLimit(Number(event.target.value))}/></Field><Field label="Baseline 并行槽位"><select value={baselineConcurrency} onChange={event => setBaselineConcurrency(Number(event.target.value))}><option value="2">2</option><option value="4">4（推荐）</option><option value="6">6</option><option value="8">8</option></select></Field><Field label="运行 ID（可选）"><input value={evalId} onChange={event => setEvalId(event.target.value)} placeholder="自动生成"/></Field></div>
          <section className="benchmark-baseline-prepare"><div><Zap size={17}/><span><b>提前并行生成 baseline</b><small>忽略已保存选择，按 Query × baseline 类型重新并行执行；完成后自动保存并可供后续评审直接复用。</small></span></div><button disabled={starting || !baselinePrepareReady || (baselinePrepareExternal && !externalConfirmed)} onClick={() => start({prepareOnly:true})}>{starting ? '正在创建任务' : `并行生成 ${selectedQueryIds.length * (Number(useAgent) + Number(useBareLlm) + Number(useZhipu))} 份报告`}</button></section>
          <div className="benchmark-mode"><button className={mode === 'fake' ? 'selected' : ''} onClick={() => setMode('fake')}><ShieldCheck size={16}/><span><b>离线冒烟</b><small>不调用外部模型，验证完整链路</small></span></button><button className={mode === 'real' ? 'selected danger-mode' : ''} onClick={() => setMode('real')}><ShieldAlert size={16}/><span><b>真实测试</b><small>调用外部模型和公开网页搜索</small></span></button></div>
          <section className="benchmark-judge-config"><div className="benchmark-judge-title"><ClipboardCheck size={17}/><span><b>评审专家</b><small>Codex 或直连 LLM 作为专家，对每个 baseline 与完整方法的匿名回答分别盲评</small></span></div><Field label="评审方式"><select value={judgeMode} onChange={event => setJudgeMode(event.target.value)}><option value="none">暂不评审</option><option value="fake">离线评审（链路测试）</option><option value="real">真实专家评审</option></select></Field>{judgeMode === 'real' && <div className="benchmark-judge-fields"><div className="benchmark-form-grid llm-top"><Field label="评审运行器"><select value={judgeRuntime} onChange={event => setJudgeRuntime(event.target.value)}><option value="llm_api">直连 LLM API</option><option value="codex_cli">Codex CLI（Responses）</option></select></Field><Field label="凭据来源"><select value={judgeCredentialSource} onChange={event => selectJudgeCredentialSource(event.target.value)}><option value="project_env">项目环境（默认）</option><option value="manual">本次手动填写</option></select></Field>{judgeRuntime === 'codex_cli' ? <Field label="Codex 接入方式"><input value={judgeCredentialSource === 'project_env' ? '项目环境凭据（后端读取）' : '本次手动 URL / API Key'} readOnly/></Field> : <Field label="评审协议"><select value={judgeProtocol} onChange={event => setJudgeProtocol(event.target.value)}><option value="responses">Responses</option><option value="chat_completions">Chat Completions</option></select></Field>}</div>{judgeRuntime === 'llm_api' && <Field label="评审服务"><select value={judgePreset} onChange={event => applyJudgePreset(event.target.value)}>{Object.entries(LLM_PRESETS).map(([id, preset]) => <option value={id} key={id}>{preset.label}</option>)}</select></Field>}<div className="benchmark-form-grid llm-main"><Field label="评审 Base URL"><input value={judgeBaseUrl} readOnly={judgeCredentialSource === 'project_env'} onChange={event => setJudgeBaseUrl(event.target.value)} placeholder="https://api.example.com/v1"/></Field><Field label="评审模型"><input value={judgeModel} onChange={event => setJudgeModel(event.target.value)} placeholder="模型 ID"/></Field></div><Field label="评审 API Key（不落盘）"><input type="password" autoComplete="new-password" readOnly={judgeCredentialSource === 'project_env'} value={judgeCredentialSource === 'manual' ? judgeApiKey : ''} onChange={event => setJudgeApiKey(event.target.value)} placeholder={judgeCredentialSource === 'project_env' ? projectEnvironment.api_key_present ? `已从 ${projectEnvironment.api_key_env} 加载（不下发）` : `项目环境 ${projectEnvironment.api_key_env || 'API Key'} 未配置` : '仅在本次评审内存中使用'}/></Field><div className="benchmark-form-grid judge-numbers">{judgeRuntime === 'llm_api' && <><Field label="温度"><input type="number" min="0" max="2" step="0.1" value={judgeTemperature} onChange={event => setJudgeTemperature(event.target.value)}/></Field><Field label="最大输出 Tokens"><input type="number" min="256" max="32000" value={judgeMaxTokens} onChange={event => setJudgeMaxTokens(event.target.value)}/></Field></>}<Field label="独立评审次数"><select value={judgeReplicas} onChange={event => setJudgeReplicas(Number(event.target.value))}><option value="1">1 次</option><option value="2">2 次</option><option value="3">3 次</option></select></Field></div><small className="benchmark-llm-note">默认复用项目环境 URL、模型与 API Key；Key 仅在后端运行内存中解析。切换评审服务预设会自动改为手动模式，每次评审覆盖正序与反序 Pair。</small></div>}</section>
          {judgeMode !== 'none' && <section className="benchmark-prompt-editor"><header><div><FileCheck2 size={16}/><span><b>Pairwise 评审 Prompt</b><small>{overview?.judge_prompt?.filename || 'pairwise_prompt_v1.md'} · 每次运行保存独立快照</small></span></div><button type="button" onClick={() => setJudgePrompt(overview?.judge_prompt?.content || '')}><RefreshCw size={13}/>恢复默认</button></header><textarea value={judgePrompt} maxLength={overview?.judge_prompt?.max_chars || 60000} spellCheck={false} onChange={event => setJudgePrompt(event.target.value)} aria-label="Pairwise 评审 Prompt"/><footer><span>{judgePrompt.length} / {overview?.judge_prompt?.max_chars || 60000} 字符</span><span className={promptReady ? 'ready' : 'missing'}>{promptReady ? '占位符完整' : '缺少必要占位符'}</span></footer></section>}
          {externalConfirmationRelevant && <label className="benchmark-check external"><input type="checkbox" checked={externalConfirmed} onChange={event => setExternalConfirmed(event.target.checked)}/><span><b>我确认允许外部数据传输</b><small>Query、参测回答与必要上下文将发送至已配置的运行模型或评审专家服务。</small></span></label>}
          {readinessIssues.length > 0 && <div className="benchmark-readiness-issues"><CircleAlert size={15}/><span><b>启动前还需完成</b><small>{readinessIssues.join(' · ')}</small></span></div>}
          <button className="primary benchmark-start" disabled={starting || !datasetId || (!useAgent && !useBareLlm && !useZhipu) || !ready || (externalDataRequired && !externalConfirmed)} onClick={() => start()}><Play size={16}/>{starting ? '正在创建任务' : judgeMode === 'none' ? `执行并保存 baseline 报告` : `启动 ${mode === 'fake' ? '离线' : '真实'}评审`}</button>
        </article>
      </section>
      <section className="benchmark-results-stack">
        <article className="benchmark-panel benchmark-history"><header><div><Clock3 size={18}/><span><b>评测结果记录</b><small>查看、停止、命名、备注或删除 Benchmark 记录</small></span></div><em>{runs.length} 条</em></header>{recordEditor && <section className="benchmark-record-editor"><Field label="记录名称"><input value={recordEditor.display_name} maxLength={120} onChange={event => setRecordEditor({...recordEditor, display_name:event.target.value})} placeholder={recordEditor.eval_id}/></Field><Field label="备注"><textarea value={recordEditor.notes} maxLength={2000} onChange={event => setRecordEditor({...recordEditor, notes:event.target.value})} placeholder="记录用途、配置说明或复核结论"/></Field><div><button onClick={() => setRecordEditor(null)}>取消</button><button className="primary" disabled={savingRecord} onClick={saveBenchmarkRecord}>{savingRecord ? '保存中' : '保存记录'}</button></div></section>}{runs.length ? <div className="benchmark-record-list">{runs.map(run => { const active = ['queued', 'running', 'cancelling'].includes(run.status); return <article className={detail?.eval_id === run.eval_id ? 'selected' : ''} key={run.eval_id}><button className="benchmark-record-main" onClick={() => openBenchmarkRecord(run.eval_id)}><span><b>{run.display_name || run.eval_id}</b><small>{run.display_name ? `${run.eval_id} · ` : ''}{run.dataset_id} · {run.mode === 'fake' ? '离线' : '真实'} · {run.limit} 条</small></span><Status value={benchmarkStatus(run.status)}/></button><div className="benchmark-record-actions">{active && <button className="stop" title={run.status === 'cancelling' ? '正在停止' : '停止 Benchmark'} disabled={run.status === 'cancelling' || cancellingRecord === run.eval_id} onClick={() => cancelBenchmarkRecord(run)}><X size={14}/></button>}<button title="编辑评测记录" disabled={active} onClick={() => editBenchmarkRecord(run)}><Pencil size={14}/></button><button className="delete" title="删除评测记录" disabled={active || deletingRecord === run.eval_id} onClick={() => deleteBenchmarkRecord(run)}><Trash2 size={14}/></button></div></article>; })}</div> : <Empty text="尚无评测结果记录"/>}</article>
        <BenchmarkResult detail={detail} onCancel={cancelBenchmarkRecord} cancelling={cancellingRecord === detail?.eval_id} queryLookup={detail && detail.dataset_id === datasetId ? Object.fromEntries(datasetQueries.map(item => [item.query_id, item.query])) : {}}/>
      </section>
    </div>
  </>;
}

function EvolutionPanel({evolution, reload}) {
  const [busy, setBusy] = useState(''); const [error, setError] = useState('');
  if (!evolution) return null;
  const act = async (action, profileId = '') => { setBusy(`${action}:${profileId}`); setError(''); const path = action === 'rollback' ? '/benchmarks/evolution/rollback' : `/benchmarks/evolution/profiles/${encodeURIComponent(profileId)}/${action}`; const result = await requestResult(path, {method:'POST', headers:{'X-Role':'admin'}}); setBusy(''); if (!result.ok) { setError(result.detail || '操作失败'); return; } await reload?.(); };
  return <section className="benchmark-evolution"><header><div><GitCompare size={18}/><span><b>Harness Champion / Challenger</b><small>只允许声明式路由、依赖、Prompt、模型层级和预算变更；晋级必须人工批准</small></span></div><em>Champion · {evolution.champion_profile_id}</em></header><div className="benchmark-profile-list">{(evolution.profiles || []).map(profile => <article className={profile.status} key={profile.profile_id}><div><b>{profile.profile_id}</b><small>{profile.hypothesis}</small><code>{profile.config_hash?.slice(0,12)}</code></div><span>{profile.status === 'champion' ? '当前 Champion' : profile.approved ? '已批准' : '待批准'}</span><div>{profile.status !== 'champion' && !profile.approved && <button disabled={!!busy} onClick={() => act('approve', profile.profile_id)}>批准</button>}{profile.status !== 'champion' && profile.approved && <button className="primary" disabled={!!busy} onClick={() => act('activate', profile.profile_id)}>激活</button>}</div></article>)}</div><footer><span>Test 与自定义 Judge Prompt 运行只能作探索性记录，不进入官方进化。</span><button disabled={!!busy || !evolution.profiles?.some(item => item.status === 'archived')} onClick={() => act('rollback')}>回滚 Champion</button></footer>{error && <p className="form-error"><CircleAlert size={14}/>{error}</p>}</section>;
}

function BenchmarkResult({detail, queryLookup = {}, onCancel, cancelling = false}) {
  const [expandedAnswers, setExpandedAnswers] = useState({}); const [fullAnswers, setFullAnswers] = useState({}); const [answerLoading, setAnswerLoading] = useState('');
  useEffect(() => { setExpandedAnswers({}); setFullAnswers({}); setAnswerLoading(''); }, [detail?.eval_id]);
  if (!detail) return <article className="benchmark-panel benchmark-detail"><Empty text="启动或选择一次 Benchmark 查看结果"/></article>;
  const summary = detail.summary || {}; const rows = detail.results || []; const completed = rows.filter(row => row.status === 'completed').length;
  const running = ['queued', 'running', 'cancelling'].includes(detail.status);
  const expectedTotal = Math.max(rows.length, (Number(detail.limit) || 0) * (detail.systems?.length || 0)) || rows.length;
  const progress = detail.progress || {}; const progressPercent = Number.isFinite(Number(progress.percent)) ? Number(progress.percent) : Math.min(100, Math.round(completed / Math.max(1, expectedTotal) * 100));
  const pairResults = detail.pair_results || (detail.pair_result && detail.pairwise_system ? {[detail.pairwise_system]: detail.pair_result} : {});
  const pairCount = detail.pair_result?.pair_count ?? Object.values(pairResults).reduce((sum, row) => sum + (row.pair_count || 0), 0);
  const judgeResults = detail.judge_results || (detail.judge_result && detail.pairwise_system ? {[detail.pairwise_system]: detail.judge_result} : {});
  const legacyBaseline = detail.pairwise_system || Object.keys(summary.systems || {}).find(system => system !== 'full_method') || 'baseline';
  const comparisons = summary.comparisons
    ? (summary.baseline_order || Object.keys(summary.comparisons)).filter(key => summary.comparisons[key]).map(key => [key, summary.comparisons[key]])
    : summary.systems ? [[legacyBaseline, summary]] : [];
  const queryGroups = []; const queryIndex = new Map();
  rows.forEach(row => { if (!queryIndex.has(row.query_id)) { queryIndex.set(row.query_id, queryGroups.length); queryGroups.push({query_id: row.query_id, rows: []}); } queryGroups[queryIndex.get(row.query_id)].rows.push(row); });
  const toggleAnswer = async (key, row) => { if (expandedAnswers[key]) { setExpandedAnswers(current => ({...current, [key]: false})); return; } if (row.answer_truncated && !fullAnswers[key]) { setAnswerLoading(key); const value = await request(`/benchmarks/runs/${detail.eval_id}/results/${row.query_id}/${row.system_id}`, null, {headers: {'X-Role': 'analyst'}}); setAnswerLoading(''); if (value?.answer) setFullAnswers(current => ({...current, [key]: value.answer})); } setExpandedAnswers(current => ({...current, [key]: true})); };
  return <article className="benchmark-panel benchmark-detail"><header><div><BarChart3 size={18}/><span><b>{detail.display_name || detail.eval_id}</b><small>{detail.display_name ? `${detail.eval_id} · ` : ''}{detail.dataset_id} · {detail.split === 'manual' ? '手选 Query' : detail.split} · {detail.limit} 条</small></span></div><div className="benchmark-detail-actions">{running && detail.status !== 'cancelling' && <button className="benchmark-stop" disabled={cancelling} onClick={() => onCancel?.(detail)}><X size={14}/>{cancelling ? '停止中' : '停止'}</button>}<Status value={benchmarkStatus(detail.status)}/></div></header>
    {detail.notes && <p className="benchmark-record-notes">{detail.notes}</p>}
    {detail.merged_record_count > 1 && <details className="benchmark-merged-records"><summary><FileCheck2 size={14}/>已将 {detail.merged_record_count} 条同链路记录合并展示</summary><div><article><b>{detail.display_name || detail.eval_id}</b><small>{detail.eval_id} · 最终评测结果</small></article>{(detail.merged_source_records || []).map(row => <article key={row.eval_id}><b>{row.display_name || row.eval_id}</b><small>{row.eval_id} · {row.record_role === 'baseline_preparation' ? 'Baseline 预生成来源' : '历史评测来源'}</small></article>)}</div></details>}
    {running && <div className={`benchmark-progress ${detail.status === 'cancelling' ? 'cancelling' : ''}`}><div className="benchmark-progress-track"><i style={{width: `${progressPercent}%`}}/></div><span>{benchmarkStageLabel(detail.stage, detail.status)}{progress.total ? ` · ${progress.completed} / ${progress.total}` : ''}</span></div>}
    <div className="benchmark-result-metrics"><div><small>已完成结果</small><b>{completed} / {expectedTotal}</b></div><div><small>盲化配对</small><b>{pairCount || 0}</b></div><div><small>运行 / 评审</small><b>{detail.mode === 'fake' ? '离线' : '真实'} · {benchmarkJudgeLabel(detail.judge_mode)}</b></div></div>
    {(detail.saved_baseline_reports?.length > 0 || Object.keys(detail.baseline_reports || {}).length > 0) && <div className="benchmark-report-reuse"><FileCheck2 size={14}/><span>本轮新保存 {detail.saved_baseline_reports?.length || 0} 份 baseline 报告；复用 {Object.values(detail.baseline_reports || {}).reduce((sum, row) => sum + Object.keys(row || {}).length, 0)} 份已保存报告。</span></div>}
    {comparisons.length > 0 && <div className="benchmark-comparisons">{comparisons.map(([baseline, comparison]) => <BenchmarkComparison key={baseline} baseline={baseline} comparison={comparison} judgeInfo={judgeResults[baseline]}/>)}</div>}
    {detail.residuals?.length > 0 && <details className="benchmark-residuals"><summary><GitCompare size={14}/>查看 {detail.residuals.length} 条 Query 残差归因</summary>{detail.residuals.map(item => { const gaps = Object.entries(item.nine_dimension_gaps || {}).filter(([key,value]) => key !== 'communication_efficiency' && value > 0).sort((a,b) => b[1]-a[1]); return <article key={item.residual_id}><header><b>{item.query_id}</b><span>{item.execution_profile_id}</span><em>{item.exploratory_only ? '探索性' : '可进入开发/Pilot'}</em></header><p>{gaps.length ? gaps.slice(0,3).map(([key,value]) => `${benchmarkDimensionLabel(key)} +${Math.round(value*100)}%`).join(' · ') : '未发现相对 baseline 的正向差距'}</p>{(item.missing_branch_products?.length || item.citation_issues?.length) > 0 && <small>{[...(item.missing_branch_products || []).map(value => `缺产物:${value}`), ...(item.citation_issues || []).map(value => `引用:${value}`)].slice(0,4).join(' · ')}</small>}</article>})}</details>}
    {queryGroups.length > 0 && <div className="benchmark-query-results">{queryGroups.map(group => <section className="benchmark-query-group" key={group.query_id}>
      <header><b>{group.query_id}</b>{queryLookup[group.query_id] && <p>{queryLookup[group.query_id]}</p>}</header>
      <div className="benchmark-query-answers">{group.rows.map(row => { const key = `${group.query_id}:${row.system_id}`; const expanded = !!expandedAnswers[key]; const answer = fullAnswers[key] || row.answer; return <article className={`${row.status} ${row.system_id === 'full_method' ? 'ours' : ''}`} key={key}>
        <header><b>{benchmarkSystemLabel(row.system_id)}{row.model_snapshot?.reused_baseline_report_id ? ' · 已复用' : ''}</b><span>引用 {row.citations?.length || 0}</span><Status value={row.status}/></header>
        {answer && <p className={expanded ? 'expanded' : ''}>{answer}</p>}
        {row.answer && (row.answer.length > 220 || row.answer_truncated) && <button className="benchmark-answer-toggle" disabled={answerLoading === key} onClick={() => toggleAnswer(key, row)}>{answerLoading === key ? '正在读取全文' : expanded ? '收起' : row.answer_truncated ? '读取并展开全文' : '展开全文'}</button>}
        {row.error && <p className="error-text">{row.error}</p>}
      </article>; })}</div>
    </section>)}</div>}
    {detail.error && <p className="form-error"><CircleAlert size={15}/>{detail.error}</p>}
  </article>;
}

function BenchmarkComparison({baseline, comparison, judgeInfo}) {
  const systems = comparison.systems || {};
  const full = systems.full_method || {}; const base = systems[baseline] || {};
  const fullRate = Number(full.score_rate || 0); const baseRate = Number(base.score_rate || 0);
  const verdict = Math.abs(fullRate - baseRate) < 0.005 ? {label: '双方持平', tone: 'tie'} : fullRate > baseRate ? {label: '完整方法领先', tone: 'win'} : {label: `${benchmarkSystemLabel(baseline)} 领先`, tone: 'loss'};
  const dimensions = Object.entries(comparison.dimension_votes || {}).filter(([dimension]) => dimension !== 'communication_efficiency');
  const runtime = comparison.runtime || {}; const fullRuntime = runtime.full_method || {}; const baseRuntime = runtime[baseline] || {};
  const judgeIds = Object.keys(judgeInfo?.usage || {});
  return <section className="benchmark-comparison">
    <header><div><b>完整方法</b><i>VS</i><b>{benchmarkSystemLabel(baseline)}</b></div><em className={`verdict ${verdict.tone}`}>{verdict.label}</em></header>
    <div className="benchmark-vs-grid">{[['full_method', full], [baseline, base]].map(([system, row]) => <div className={system === 'full_method' ? 'ours' : ''} key={system}><small>{benchmarkSystemLabel(system)}</small><b>{row.wins ?? 0} 胜 · {row.ties ?? 0} 平 · {row.losses ?? 0} 负</b><div className="score-bar"><i style={{width: `${Math.round((row.score_rate || 0) * 100)}%`}}/></div><span>得分率 {Math.round((row.score_rate || 0) * 100)}%{row.bootstrap_95pct ? ` · 95% CI ${row.bootstrap_95pct.map(value => `${Math.round(value * 100)}%`).join('–')}` : ''}</span></div>)}</div>
    {dimensions.length > 0 && <div className="benchmark-dimensions"><small>分维度评审票型（完整方法 : 平 : baseline）</small>{dimensions.map(([dimension, votes]) => { const ours = votes.full_method || 0; const theirs = votes[baseline] || 0; const ties = votes.tie || 0; const total = Math.max(1, ours + theirs + ties); return <div key={dimension}><span>{benchmarkDimensionLabel(dimension)}</span><div className="dim-bar"><i className="ours" style={{width: `${ours / total * 100}%`}}/><i className="tie" style={{width: `${ties / total * 100}%`}}/><i className="theirs" style={{width: `${theirs / total * 100}%`}}/></div><em>{ours}:{ties}:{theirs}</em></div>; })}</div>}
    <div className="benchmark-runtime-compare"><div><small>完整方法</small><span>成功率 {Math.round((fullRuntime.completion_rate || 0) * 100)}% · 均次成本 {Number(fullRuntime.mean_estimated_cost || 0).toFixed(4)}</span></div><div><small>{benchmarkSystemLabel(baseline)}</small><span>成功率 {Math.round((baseRuntime.completion_rate || 0) * 100)}% · 均次成本 {Number(baseRuntime.mean_estimated_cost || 0).toFixed(4)}</span></div></div>
    <footer><span>{comparison.query_count || 0} 条 Query · {comparison.judgment_count || 0} 次评审判定{judgeIds.length ? ` · 评审专家 ${judgeIds.length} 名` : ''}</span></footer>
  </section>;
}

function useLiveInteractions(run, enabled) {
  const [data, setData] = useState(null); const [loading, setLoading] = useState(false); const [connected, setConnected] = useState(false);
  const dataRunRef = useRef('');
  useEffect(() => {
    if (!enabled || !run) { dataRunRef.current = ''; setConnected(false); setData(null); setLoading(false); return undefined; }
    // Status changes are common while a run is active. Do not clear an
    // already-rendered snapshot before the replacement request completes;
    // doing so caused the interaction/report pane to flash its skeleton.
    const runChanged = dataRunRef.current !== run.run_id;
    if (runChanged) { dataRunRef.current = run.run_id; setData(null); setLoading(true); setConnected(false); }
    else setLoading(current => current || data == null);
    let cancelled = false; let refreshTimer = null; let disconnectTimer = null;
    const refresh = () => request(runApiPath(run.run_id, '/interactions?compact=true'), null, {headers: {'X-Role': 'analyst'}}).then(value => { if (!cancelled && value) setData(value); }).finally(() => { if (!cancelled) setLoading(false); });
    const scheduleRefresh = () => { if (refreshTimer) clearTimeout(refreshTimer); refreshTimer = setTimeout(() => void refresh(), 120); };
    void refresh();
    if (['completed', 'failed', 'cancelled', 'archived'].includes(run.status)) { setConnected(false); return () => { cancelled = true; if (refreshTimer) clearTimeout(refreshTimer); }; }
    const source = new EventSource(`${api}${runApiPath(run.run_id, '/events')}`);
    source.onopen = () => {
      if (disconnectTimer) { clearTimeout(disconnectTimer); disconnectTimer = null; }
      if (!cancelled) setConnected(true);
    };
    // EventSource emits `error` during normal automatic reconnects. Debounce
    // the offline state so a transient network hiccup does not make the live
    // indicator visibly blink on every retry.
    source.onerror = () => {
      if (cancelled || disconnectTimer) return;
      disconnectTimer = setTimeout(() => { disconnectTimer = null; if (!cancelled && source.readyState === EventSource.CLOSED) setConnected(false); }, 3000);
    };
    const eventTypes = ['run_created', 'run_status_changed', 'run_recovered', 'run_started', 'discovery_meta_loop_evaluated', 'baseline_pipeline_started', 'baseline_discovery_started', 'baseline_discovery_lane_started', 'baseline_discovery_lane_completed', 'baseline_discovery_lane_limited', 'baseline_discovery_completed', 'baseline_provider_neutral_source_anchor_fallback', 'baseline_model_queue_started', 'baseline_model_call_started', 'baseline_model_call_progress', 'baseline_model_call_completed', 'baseline_analysis_started', 'baseline_analysis_completed', 'baseline_materialization_progress', 'baseline_wave_started', 'baseline_wave_completed', 'agent_task_delegated', 'agent_harness_completed', 'task_received', 'tool_call', 'tool_result', 'evidence_assessed', 'baseline_result', 'savepoint', 'baseline_agent_completed', 'baseline_agents_summarized', 'packet_admission_evaluated', 'packet_admission_reused', 'discovery_convergence_completed', 'discovery_convergence_reused', 'winning_input_prepared', 'winning_resources_projected', 'winning_model_result_reused', 'winning_model_queue_started', 'winning_model_call_started', 'winning_model_call_progress', 'winning_model_call_completed', 'swarm_planned', 'specialist_recruitment_planned', 'specialist_spawned', 'specialist_session_started', 'specialist_session_completed', 'specialist_completed', 'specialist_pruned', 'winning_mission_graph_planned', 'winning_s3_s4_naming_plan_allocated', 'winning_query_equipment_blueprint_planned', 'winning_pre_generation_active_angle_selection_fallback', 'winning_pre_generation_angle_portfolio_planned', 'winning_s3_active_agents_materialized', 'winning_s3_first_pass_self_admission_completed', 'winning_s3_s4_candidate_output_bounded', 'winning_s3_s4_creative_iteration_limited', 'winning_s3_s4_name_authoring_diagnostic', 'winning_reasoning_seed_published', 'winning_specialized_seed_authored', 'winning_specialized_seed_empty', 'winning_specialized_seed_recovered', 'winning_s3_empty_angle_reallocated', 'winning_agent_instance_recruited', 'winning_agent_instance_ready', 'winning_agent_instance_retry_scheduled', 'winning_agent_session_started', 'winning_agent_waiting', 'winning_agent_session_completed', 'winning_agent_instance_failed', 'winning_agent_instance_cancelled', 'winning_semantic_clustering_started', 'winning_semantic_clustering_bounded', 'winning_semantic_clustering_completed', 'winning_semantic_clustering_failed', 'winning_candidate_competition_converged', 'winning_candidate_branch_created', 'winning_candidate_pre_s5_residual_recorded', 'winning_candidate_rejected_before_ledger', 'winning_candidate_review_scope_planned', 'winning_candidate_summary_quality_advisory', 'winning_candidate_ledger_frozen', 'winning_contribution_queued', 'winning_contribution_rejected', 'winning_contribution_rebase_required', 'winning_contribution_hypothesis_remapped', 'winning_contribution_merged', 'winning_s5_parallel_score_started', 'winning_s5_parallel_score_completed', 'winning_s5_contract_gate_rejected', 'winning_s5_invalid_decision_rejected', 'winning_s5_invalid_merge_rejected', 'winning_s5_portfolio_fallback_activated', 'winning_s5_portfolio_frozen', 'winning_full_pool_portfolio_decision', 'winning_full_pool_portfolio_review_repaired', 'winning_full_pool_portfolio_review_rescued', 'winning_full_pool_portfolio_review_completed', 'winning_s5_handoff_quality_gate_completed', 'winning_s6_parallel_authoring_configured', 'winning_s6_card_authoring_started', 'winning_s6_card_authoring_retry_started', 'winning_s6_card_authoring_completed', 'winning_s6_card_authoring_reused', 'winning_s6_card_authoring_limited', 'winning_s6_card_authoring_rescue_started', 'winning_s6_card_authoring_rescued', 'winning_s6_card_quality_advisory', 'winning_s6_card_quality_enhancement_limited', 'winning_s6_card_quality_enhancement_completed', 'winning_s6_low_repair_started', 'winning_s6_low_repair_completed', 'winning_s6_low_repair_limited', 'winning_s6_release_gate_evaluated', 'winning_portfolio_merge_completed', 'hypothesis_created', 'hypothesis_merged', 'hypothesis_rejected', 'swarm_gate_evaluated', 'promotion_candidate_created', 'winning_subagent_completed', 'winning_inner_loop_evaluated', 'winning_middle_loop_evaluated', 'winning_outer_loop_evaluated', 'winning_reasoning_step_completed', 'winning_stage_completed', 'recall_requested', 'recall_task_completed', 'coverage_recomputed_after_recall', 'winning_stage_gate_reevaluated', 'capability_image_created', 'winning_quality_judge_recruited', 'winning_quality_judge_started', 'winning_quality_judge_assessed', 'winning_quality_judge_completed', 'winning_quality_judge_failed', 'winning_quality_repair_planned', 'winning_quality_repair_completed', 'winning_quality_repair_failed', 'audit_model_fallback', 'audit_model_pending', 'audit_model_unavailable', 'audit_completed', 'audit_delivery_blocked', 'report_quality_gate_limited', 'report_delivery_resume_gate_evaluated', 'report_model_queue_started', 'report_model_call_started', 'report_model_call_progress', 'report_model_call_completed', 'report_model_fallback', 'report_model_failed', 'report_completed', 'expert_feedback_submitted', 'expert_feedback_handoff_loaded', 'run_result_saved', 'run_failed'];
    eventTypes.push('run_orphan_process_cleanup');
    eventTypes.forEach(type => source.addEventListener(type, scheduleRefresh));
    return () => { cancelled = true; source.close(); if (refreshTimer) clearTimeout(refreshTimer); if (disconnectTimer) clearTimeout(disconnectTimer); };
  // Re-open the stream when a run becomes terminal, but retain the existing
  // snapshot and live state during ordinary status transitions.
  }, [enabled, run?.run_id, run?.status]);
  return {data, loading, connected};
}

function InteractionView({data, live, completed, terminalStatus}) {
  const [filter, setFilter] = useState('all');
  const agents = data.agents || []; const events = data.events || []; const workflow = data.workflow || {};
  const cluster = workflow.swarm_cluster || {};
  const swarmMembers = cluster.members?.length ? cluster.members : workflow.dynamic_agents || [];
  const activeIds = new Set(workflow.active_agent_ids?.length ? workflow.active_agent_ids : events.flatMap(event => [event.actor, event.details?.target_agent_id]).filter(Boolean));
  const activeAgents = agents.filter(agent => activeIds.has(agent.agent_id));
  const activeBusinessAgents = activeAgents.filter(agent => DISCOVERY_AGENT_IDS.has(agent.agent_id));
  const dynamicMap = Object.fromEntries(swarmMembers.map((agent, index) => [agent.agent_instance_id || agent.agent_id || agent.id || `dynamic-${index}`, agent]));
  const map = {...Object.fromEntries(agents.map(agent => [agent.agent_id, agent])), ...dynamicMap};
  const baselinePlanMap = Object.fromEntries((workflow.discovery?.baseline_agent_plan || []).map(item => [item.agent_id, item]));
  const filterAgents = [...new Map([...activeAgents, ...swarmMembers.map((agent, index) => ({...agent, agent_id: agent.agent_instance_id || agent.agent_id || agent.id || `dynamic-${index}`, display_name: agent.display_name || '动态专用 Agent'}))].map(agent => [agent.agent_id, agent])).values()];
  const visible = (filter === 'all' ? events : events.filter(event => event.actor === filter || event.details?.target_agent_id === filter)).slice(-60);
  const failed = terminalStatus === 'failed' || workflow.status === 'failed';
  const failure = workflow.failure || {};
  return <><div className={`live-state ${live ? 'connected' : ''}`}><i/>{live ? '实时接收关键流程' : '关键流程审计回放'}</div>{failed && <section className="workflow-failure"><CircleAlert size={18}/><div><b>{failure.phase ? `${failure.phase === 's_agents' ? 'S1–S6 制胜机理阶段' : failure.phase} 已停止` : '任务已停止'}</b><span>{agentFacingText(failure.detail || '已保留基线证据、检查点与可恢复的执行上下文。')}</span></div></section>}<section className="metric-strip interaction-metrics"><Metric label="全部事件" value={data.counts?.events || 0} icon={Activity}/><Metric label="关键事件" value={data.counts?.visible_events ?? events.length} icon={Layers3}/><Metric label="业务 Agent" value={activeBusinessAgents.length} icon={Bot}/><Metric label="保存点" value={data.counts?.savepoints || 0} icon={ClipboardCheck}/></section><WorkflowOverview events={events} workflow={workflow} agents={agents} live={live} completed={completed}/><DynamicSwarmInteractionPanel cluster={cluster} members={swarmMembers} live={live}/><section className="agent-map compact-agent-map"><div className="section-heading"><div><b>本次参与的业务 Agent</b><span>由主控 Agent 结合 A–H 分支路径与当前输入选择；分支自动加入的案例、技术、跨域与非传统安全专项 Agent 也在此显示。</span></div></div><div className="agent-chip-grid">{activeBusinessAgents.map(agent => { const plan = baselinePlanMap[agent.agent_id] || {}; return <article className="agent-chip" key={agent.agent_id}><Bot size={16}/><div><b>{agent.display_name}{plan.mode && <em className={`agent-plan-mode ${plan.mode}`}>{baselineAgentModeLabel(plan.mode)}</em>}</b><small>{agent.harness_profile || '受控运行'}</small><span>{(agent.skill_ids || []).slice(0, 2).join(' · ') || '专业分析'}</span></div></article>; })}</div>{activeBusinessAgents.length === 0 && <small className="agent-overflow">主控 Agent 正在按分支路径判断本次需要的业务 Agent。</small>}</section><section className="event-filter compact-filter"><span>关键事件</span><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部 Agent</option>{filterAgents.map(agent => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}</select><em>显示 {visible.length} / {data.counts?.events || events.length}</em></section><section className="event-timeline compact-timeline">{visible.map((event, index) => <InteractionEvent key={`${event.event_id}-${index}`} event={event} agent={map[event.actor]}/>)}</section></>;
}

function DynamicSwarmInteractionPanel({cluster, members, live}) {
  if (!cluster?.enabled && !members?.length) return null;
  const rows = members || [];
  const counts = cluster.counts || {};
  const graph = cluster.mission_graph || {};
  const rolePools = cluster.role_pools || ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'].map(mission_node => ({mission_node, count: rows.filter(item => item.mission_node === mission_node).length}));
  const specialists = cluster.dynamic_specialists || rows.filter(item => item.recruitment_planned);
  const candidates = cluster.candidate_lineage || [];
  const visibleCandidates = candidates.filter(candidate => {
    const title = cleanWeaponCandidateText(candidate.title);
    const form = weaponCandidateForm(candidate);
    const isSelected = candidate.s6_eligible === true || candidate.portfolio_status === 'selected' || candidate.selection_status === 'selected';
    // Lineage-only event shells have an id but no authored equipment identity.
    // Keep them in the audit trail, not in the user-facing weapon board.
    return Boolean(title || form || isSelected);
  });
  const ledger = cluster.hypothesis_ledger || {};
  const receipts = cluster.merge_receipts || [];
  const portfolio = cluster.final_equipment_portfolio || cluster.portfolio_decision?.final_equipment_portfolio || [];
  const s6Cards = cluster.s6_authored_cards || [];
  const s6Gate = cluster.s6_release_gate || {};
  const s6Authoring = cluster.s6_authoring || {};
  const portfolioGate = cluster.portfolio_decision?.quality_gate || {};
  const waves = [1, 2, 3].map(wave => ({wave, label: {1: '问题发散', 2: '开放创作', 3: '组合决策'}[wave], members: rows.filter(item => Number(item.wave || 0) === wave)}));
  const completed = Number(counts.completed || 0) + Number(counts.merged || 0);
  const memberPurpose = member => userFacingSwarmMemberPurpose(member);
  return <section className="dynamic-swarm-panel">
    <header><div><Layers3 size={18}/><span><b>动态制胜 Agent 集群</b><small>S1–S6 为种子角色池，依赖满足即并行启动；质量残差可招聘额外 Codex CLI 专用 Agent，贡献只合并到声明候选。</small></span></div><em className={live && Number(counts.running || 0) > 0 ? 'live' : ''}>{live && Number(counts.running || 0) > 0 ? '实时调度' : '可审计回放'}</em></header>
    <div className="dynamic-swarm-counts"><span><small>实例总数</small><b>{counts.total ?? rows.length}</b></span><span><small>创建/执行中</small><b>{Number(counts.recruiting || 0) + Number(counts.running || 0)}</b></span><span><small>完成</small><b>{completed}</b></span><span><small>账本版本</small><b>v{ledger.version || 0}</b></span><span><small>最终装备方向</small><b>{portfolio.length}</b></span></div>
    <div className="swarm-role-pools">{rolePools.map(pool => <div key={pool.mission_node}><b>{pool.mission_node}<i>×{pool.count || 0}</i></b><span>{swarmNodeLabel(pool.mission_node)}</span></div>)}<div className="specialists"><b>专用<i>×{specialists.length}</i></b><span>残差触发招聘</span></div></div>
    {graph.graph_id && <div className="swarm-graph-contract"><span>Mission Graph <code>{graph.graph_id}</code></span><span>并发上限 <b>{graph.maximum_concurrency || 6}</b></span><span>实际峰值 <b>{graph.maximum_observed_concurrency ?? '—'}</b></span><span>实例边界 <b>{graph.minimum_instances || 8}–{graph.maximum_instances || 21}</b></span><span>{graph.merge_strategy || '版本化账本 Merge'}</span></div>}
    <div className="dynamic-swarm-waves">{waves.map(wave => <section key={wave.wave} className={`dynamic-swarm-wave wave-${wave.wave}`}><header><i>W{wave.wave}</i><span><b>{wave.label}</b><small>{wave.members.length} 个实例</small></span></header><div>{wave.members.length ? wave.members.map((member, index) => <article className={`dynamic-swarm-member status-${member.status || 'planned'}`} key={member.agent_instance_id || member.agent_id || `${wave.wave}-${index}`}><header><i>{member.mission_node || index + 1}</i><div><b>{userFacingSwarmMemberName(member)}</b><small>{swarmNodeLabel(member.mission_node)}</small></div><span className={`swarm-member-status ${member.status || 'planned'}`}>{swarmMemberStatusLabel(member)}</span></header><details className="dynamic-swarm-purpose"><summary><span>{memberPurpose(member)}</span><em>展开职责</em></summary><p>{memberPurpose(member)}</p></details><div className="dynamic-swarm-routing"><span>候选 <code>{shortIdentifier(member.hypothesis_id || '开放新建')}</code></span><span>Merge <b>{member.merge_target || '未声明'}</b></span></div>{member.depends_on?.length > 0 && <div className="swarm-dependencies"><small>依赖</small>{member.depends_on.slice(0, 3).map(item => <code key={item}>{shortIdentifier(item)}</code>)}</div>}{member.trigger_residuals?.length > 0 && <div className="dynamic-swarm-residuals">{member.trigger_residuals.slice(0, 3).map(item => <span key={item}>{item}</span>)}</div>}{member.prune_reason && <div className="dynamic-swarm-decision rejected"><CircleAlert size={13}/><span>回收原因：{agentFacingText(member.prune_reason)}</span></div>}{member.portfolio_status === 'selected' && <div className="dynamic-swarm-decision accepted"><CheckCircle2 size={13}/><span>贡献已纳入独立装备卡</span></div>}{member.portfolio_status === 'rejected' && <div className="dynamic-swarm-decision not-selected"><CheckCircle2 size={13}/><span>执行结论已沉淀为候选约束或变体，不重复单列装备卡</span></div>}{member.status === 'merged' && !member.portfolio_status && <div className="dynamic-swarm-decision accepted"><CheckCircle2 size={13}/><span>贡献已定向合并</span></div>}<details className="dynamic-swarm-technical"><summary>角色合同与独立会话</summary><dl><dt>脱敏会话引用</dt><dd><code>{member.session_ref || member.agent_instance_id || '待启动'}</code></dd><dt>执行后端</dt><dd>{member.execution_backend === 'independent_codex_cli' ? '独立 Codex CLI' : member.execution_backend || member.provider_type || '受控模型会话'}</dd><dt>上下文隔离</dt><dd>{member.context_isolation || 'ephemeral'}</dd><dt>Skill</dt><dd>{(member.skill_ids || []).join(' · ') || '受治理共享 Skill'}</dd><dt>递归招聘</dt><dd>{member.allow_child_spawn === true ? '允许' : '禁止'}</dd></dl></details></article>) : <div className="dynamic-swarm-empty"><RefreshCw size={14}/><span>等待依赖满足或开放探索容量释放</span></div>}</div></section>)}</div>
    {visibleCandidates.length > 0 && <section className="swarm-candidate-board"><header><div><b>候选军事装备</b><small>按组合价值与独立性排序</small></div><em>{visibleCandidates.length} 条</em></header><div>{visibleCandidates.map(candidate => { const status = candidate.selection_status || candidate.status || 'created'; const isReference = !candidate.s6_eligible && ['reference', 'rejected', 'contribution_rejected'].includes(status); const weaponName = weaponCandidateTitle(candidate); const overview = swarmCandidateOverview(candidate); return <article key={candidate.hypothesis_id} className={`candidate-${isReference ? 'reference' : status}`}><header><b title={weaponName || candidate.hypothesis_id}>{weaponName || shortIdentifier(candidate.hypothesis_id)}</b><span>{swarmCandidateStatusLabel(status)}</span></header>{overview && <p className="candidate-winning-summary">{overview}</p>}<div className="candidate-score" title="组合评分"><i style={{width: `${Math.max(0, Math.min(100, Number(candidate.score || 0) * 100))}%`}}/><em>{Math.round(Number(candidate.score || 0) * 100)}</em></div>{candidate.s6_eligible && <small className="candidate-selection-reason">入选依据：{agentFacingText(candidate.selection_reason || '进入本轮 S6 详细画像。')}</small>}{candidate.related_hypothesis_ids?.length > 0 && <small className="candidate-related-hypotheses">关联候选：{candidate.related_hypothesis_ids.map(shortIdentifier).join(' · ')}</small>}</article>; })}</div></section>}
    {receipts.length > 0 && <details className="swarm-merge-receipts"><summary>Merge Receipt 与版本重基（{receipts.length}）</summary><div>{receipts.slice(-12).map(receipt => <div key={receipt.receipt_id}><code>{shortIdentifier(receipt.contribution_id)}</code><span>{shortIdentifier(receipt.hypothesis_id)} → {receipt.merge_target}</span><b className={receipt.status}>{receipt.rebase_required ? '需重基' : receipt.status}</b><em>v{receipt.base_ledger_version ?? '?'}→v{receipt.resulting_ledger_version ?? '?'}</em></div>)}</div></details>}
    {portfolio.length > 0 && <section className="swarm-equipment-portfolio"><header><div><b>最终前瞻军事装备组合</b><small>S5 按创新性30%＋需求性30%＋科学可行性20%＋效能性10%＋发展性10%综合评分，最多保留 7 个；不足时不凑数，S5不改名不补写装备</small></div><em>{portfolio.length} 条</em></header><div>{portfolio.map((item, index) => { const innovationPriority = Number(item.innovation_priority); const scoreMap = portfolioS5Scores(item); const storedWeightedScore = Number(item.s5_weighted_score); const weightedScore = Number.isFinite(storedWeightedScore) && storedWeightedScore > 0 ? storedWeightedScore : weightedS5Score(scoreMap); const scoreLabels = [['创新', scoreMap.innovation], ['需求', scoreMap.demand], ['可行', scoreMap.feasibility], ['效能', scoreMap.effectiveness], ['发展', scoreMap.development]]; return <article className={Number.isFinite(weightedScore) && weightedScore >= .7 ? 'innovation-priority' : ''} key={item.hypothesis_id || `${item.name}-${index}`}><i>{index + 1}</i><div><b>{item.name || '前瞻装备方向'}</b><p className="winning-summary">{item.concise_winning_summary || (item.mission_effects || []).slice(0, 2).join('；') || item.military_value || '制胜说明待补充'}</p><small>{(item.equipment_forms || []).join(' · ') || item.equipment_form || item.type || '具体装备形态'}</small>{item.innovation_basis && <small className="innovation-basis">新质依据：{agentFacingText(item.innovation_basis)}</small>}{scoreLabels.some(([, value]) => Number.isFinite(Number(value))) && <small className="innovation-basis s5-score-line">S5评分：{scoreLabels.filter(([, value]) => Number.isFinite(Number(value))).map(([label, value]) => `${label}${Math.round(Number(value) * 100)}`).join(' · ')}{Number.isFinite(weightedScore) ? ` · 综合${Math.round(weightedScore * 100)}` : ''}</small>}<footer><span>{item.type || 'new'}</span>{Number.isFinite(innovationPriority) && <span className="innovation-score">创新优先 {Math.round(innovationPriority * 100)}</span>}</footer></div></article>; })}</div></section>}
    {(s6Authoring.started > 0 || s6Cards.length > 0 || s6Gate.status) && <section className="swarm-s6-gate"><header><div><b>S6 原创能力画像</b><small>单卡独立成稿；不会把 S5 入选组合冒充为 S6 画像</small></div><em className={s6Gate.passed ? 'passed' : 'limited'}>{s6Gate.passed ? '画像交付门通过' : s6Gate.status === 'failed' ? '画像交付门未通过' : '画像交付受限'}</em></header><div className="swarm-s6-stats"><span>成稿 {s6Cards.length}/{s6Authoring.started || s6Gate.card_count || s6Cards.length}</span><span>复用 {s6Authoring.reused || 0}</span><span>受限回退 {s6Authoring.limited || 0}</span><span>硬门问题 {(s6Gate.issues || []).length}</span></div>{s6Gate.issues?.length > 0 && <ul>{s6Gate.issues.slice(0, 4).map((issue, index) => <li key={`${issue}-${index}`}>{issue}</li>)}</ul>}</section>}
  </section>;
}

function swarmMemberStatusLabel(member = {}) {
  const status = String(member.status || 'planned');
  if (member.portfolio_status === 'selected' || member.merge_status === 'accepted') return '贡献已纳入';
  if (member.portfolio_status === 'rejected') return '贡献已沉淀';
  return {planned:'待调度',recruiting:'会话创建中',queued:'等待执行',running:'执行中',completed:'执行完成',merged:'贡献已合并',pruned:'已回收',skipped:'已回收',failed:'执行失败'}[status] || '待调度';
}
const INTERNAL_SWARM_COPY_PATTERN = /独立检验Query蓝图制胜命题|制胜命题验证|概念性工作名|Query因果|当前唯一任务主题为|将候选制胜机理收敛为具体装备构型|多样性侦察员建议从/;
function userFacingSwarmMemberName(member = {}) {
  const raw = String(member.display_name || member.name || '').trim();
  if (raw === '独立组合评审') return '创新候选快速筛选';
  const legacyDimensionAgent = raw.match(/^(?:.+?)维度创新装备 Agent\s*([A-Z])$/i);
  if (legacyDimensionAgent) return `开放创新武器 Agent ${legacyDimensionAgent[1].toUpperCase()}`;
  if (INTERNAL_SWARM_COPY_PATTERN.test(raw)) return `${swarmNodeLabel(member.mission_node)}推演 Agent`;
  return agentFacingText(raw || `${swarmNodeLabel(member.mission_node)} Agent`);
}
function userFacingSwarmMemberPurpose(member = {}) {
  const raw = String(member.role_purpose || member.purpose || '').trim();
  if (raw && !INTERNAL_SWARM_COPY_PATTERN.test(raw)) return agentFacingText(raw);
  return {
    S1: '分析对手体系、任务链断点及可能的反适应路径。',
    S2: '比较不同作战运用路径及其直接军事效果。',
    S3: '在分配的制胜维度内比较至少三种武器架构，创造可直接形成战果的新质候选；可舍弃前置启发。',
    S4: '在与 S3 不同的制胜维度内独立重构新质候选，避开已占用本体、机理和接敌关系。',
    S5: '先在同一制胜维度内按综合评分择优，再跨维度覆盖互异关系，最多保留7个；不改名、不补写装备。',
    S6: '对 S5 入选装备逐项形成独立能力画像，继承冻结名称与制胜逻辑。',
  }[member.mission_node] || '围绕当前质量缺口执行定向分析。';
}
function swarmCandidateStatusLabel(value) { return {created:'已创建',contribution_queued:'贡献排队',rebase_required:'版本重基',merged:'已合并',selected:'入选',selected_pending_verification:'新质方向·待核验',merged_as_variant:'参考变体',not_selected_capacity:'参考武器',reference:'参考武器',rejected:'参考武器',contribution_rejected:'参考武器'}[value] || value || '演化中'; }
function cleanWeaponCandidateText(value) {
  return String(value || '').replace(/_/g, ' ')
    .replace(/^(?:(?:[A-H]\s*[-/]?\s*)?S[1-6](?:\s*[-/]?\s*(?:候选)?[A-Z一二三四五六\d]+)?|(?:竞争分支|候选)(?:[A-Z一二三四五六\d-]+)?|[A-H])\s*[：:—–/-]*\s*/i, '')
    .replace(/\bS[1-6]\b\s*[-_/：:]*/gi, '')
    .replace(/^(?:红队保留|红队|保留参考|参考武器)\s*[：:—–/-]*\s*/, '')
    .split(/\s*(?:·|\||；|;)\s*(?:主装备)?(?:装备)?(?:形态|接口形态|接口|任务接口)\s*[：:]/, 1)[0]
    .replace(/^(?:(?:主装备)?(?:装备)?形态|接口形态|接口|任务接口|(?:[Qq]uery)(?:相关|专属)?(?:型号|装备)?|相关型号)\s*[：:]\s*/, '')
    .trim();
}
function weaponCandidateTitle(candidate = {}) {
  const title = cleanWeaponCandidateText(candidate.title);
  const head = title.split(/[：:；;。]/, 1)[0].trim();
  // S3/S4/S5 already apply the Codex semantic naming contract before a
  // candidate reaches the ledger. Do not hide that governed title behind a
  // local vocabulary of familiar weapon suffixes: novel identities such as
  // “无人母机” are intentionally allowed to fall outside that vocabulary.
  if (head) return head;
  if (title) return title;
  return weaponCandidateForm(candidate);
}
function weaponCandidateForm(candidate = {}) {
  const forms = Array.isArray(candidate.equipment_forms) ? candidate.equipment_forms : [];
  const normalized = forms.map(cleanWeaponCandidateText).filter(Boolean);
  return normalized.slice(0, 2).join(' · ');
}
function hasWeaponCandidateIdentity(candidate = {}) {
  return Boolean(weaponCandidateTitle(candidate) || weaponCandidateForm(candidate));
}
function normalizeWeaponIdentity(value) {
  return cleanWeaponCandidateText(value)
    .toLowerCase()
    .replace(/[“”"'‘’（）()、，。；：:·丨|/\\\s_-]+/g, '')
    .trim();
}
function referenceWeaponDuplicatesCapability(candidate = {}, rows = []) {
  const candidateIdentity = [weaponCandidateTitle(candidate), weaponCandidateForm(candidate)]
    .map(normalizeWeaponIdentity)
    .filter(value => value.length >= 6);
  if (!candidateIdentity.length) return false;
  return rows.some(row => {
    const rowIdentity = [row?.name, row?.equipment_form, row?.equipment_category, row?.capability_image]
      .map(normalizeWeaponIdentity)
      .filter(value => value.length >= 6);
    return candidateIdentity.some(candidateValue => rowIdentity.some(rowValue => (
      candidateValue === rowValue
      || candidateValue.length >= 10 && rowValue.length >= 10 && (candidateValue.includes(rowValue) || rowValue.includes(candidateValue))
    )));
  });
}
function swarmCandidateOverview(candidate = {}) {
  const generatedOverview = String(candidate.reference_overview || '').trim();
  const form = weaponCandidateForm(candidate);
  const weaponName = weaponCandidateTitle(candidate);
  const removeFormAlias = text => {
    if (!text || !form || form === weaponName) return text;
    const escapedForm = form.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return text
      .replace(new RegExp(`\\s*[（(]\\s*${escapedForm}\\s*[）)]`, 'g'), '')
      .trim();
  };
  if (generatedOverview) return removeFormAlias(generatedOverview);
  const authoredFallbacks = [
    candidate.decisive_advantage_thesis,
    candidate.novelty_delta,
    candidate.project_function,
    ...(Array.isArray(candidate.direct_military_effects) ? candidate.direct_military_effects : [candidate.direct_military_effects]),
  ].map(value => String(value || '').trim()).filter(Boolean);
  if (authoredFallbacks.length) return removeFormAlias(authoredFallbacks[0]);
  return '';
}
function swarmNodeLabel(value) { return {S1:'对手体系',S2:'竞争战法',S3:'开放创作',S4:'开放创作',S5:'创新筛选',S6:'能力画像'}[value] || '专用角色'; }
function shortIdentifier(value) { const text = String(value || ''); return text.length > 24 ? `${text.slice(0, 10)}…${text.slice(-8)}` : text; }

function WorkflowOverview({events, workflow, agents, live, completed}) {
  const has = type => events.some(event => event.event_type === type);
  const metaReview = workflow.l4 || [...events].reverse().find(event => event.event_type === 'discovery_meta_loop_evaluated')?.details || {};
  const discovery = workflow.discovery || {};
  const execution = workflow.execution || {};
  const baselinePhase = (workflow.phases || []).find(item => item.id === 'baseline') || {};
  const baselineDone = normalizeWorkflowStatus(baselinePhase.status) === 'completed';
  const completedBaselineIds = new Set(events.filter(event => event.event_type === 'baseline_agent_completed').map(event => event.actor));
  const completedAgents = baselineDone ? (baselinePhase.agent_ids || []).length : completedBaselineIds.size;
  const agentMap = Object.fromEntries((agents || []).map(agent => [agent.agent_id, agent]));
  const baselineAgentIds = new Set([...(baselinePhase.agent_ids || []), ...completedBaselineIds]);
  const runningBaselineIds = baselineDone ? [] : [...new Set(events.filter(event => ['task_received', 'baseline_pipeline_started', 'baseline_discovery_started', 'baseline_discovery_lane_started', 'baseline_discovery_lane_completed', 'baseline_discovery_completed', 'baseline_model_queue_started', 'baseline_model_call_started', 'baseline_model_call_progress', 'baseline_model_call_completed', 'baseline_analysis_started', 'baseline_analysis_completed', 'baseline_materialization_progress', 'baseline_wave_started'].includes(event.event_type)).flatMap(event => ['baseline_pipeline_started', 'baseline_wave_started'].includes(event.event_type) ? event.details?.agent_ids || [] : [event.details?.agent_id || event.actor]))].filter(agentId => baselineAgentIds.has(agentId) && !completedBaselineIds.has(agentId));
  const runningBaselineNames = runningBaselineIds.map(agentId => agentMap[agentId]?.display_name || agentId).slice(0, 3);
  const baselineProgress = runningBaselineIds.map(agentId => {
    const agentEvents = events.filter(event => (event.details?.agent_id || event.actor) === agentId);
    const laneStarted = agentEvents.filter(event => event.event_type === 'baseline_discovery_lane_started');
    const laneCompleted = agentEvents.filter(event => event.event_type === 'baseline_discovery_lane_completed');
    const discoveryDone = [...agentEvents].reverse().find(event => event.event_type === 'baseline_discovery_completed');
    const analysisStarted = agentEvents.some(event => event.event_type === 'baseline_analysis_started');
    const analysisDone = agentEvents.some(event => event.event_type === 'baseline_analysis_completed');
    const materialization = [...agentEvents].reverse().find(event => event.event_type === 'baseline_materialization_progress')?.details;
    const latestQueue = [...agentEvents].reverse().find(event => event.event_type === 'baseline_model_queue_started');
    const latestCall = [...agentEvents].reverse().find(event => event.event_type === 'baseline_model_call_started');
    const latestCallProgress = [...agentEvents].reverse().find(event => event.event_type === 'baseline_model_call_progress');
    const latestCallDone = [...agentEvents].reverse().find(event => event.event_type === 'baseline_model_call_completed');
    const waitingForSlot = latestQueue && (!latestCall || Number(latestQueue.sequence || 0) > Number(latestCall.sequence || 0));
    const modelRunning = latestCall && (!latestCallDone || Number(latestCall.sequence || 0) > Number(latestCallDone.sequence || 0));
    const slotText = latestCall?.details?.concurrency_limit ? `${latestCall.details.active_calls || 0}/${latestCall.details.concurrency_limit} 槽` : '';
    const queueText = Number(latestCall?.details?.queue_wait_seconds || 0) > 0 ? ` · 排队 ${Math.round(latestCall.details.queue_wait_seconds)} 秒` : '';
    const elapsedText = modelRunning && Number(latestCallProgress?.details?.elapsed_seconds || 0) > 0 ? ` · 已执行 ${Math.round(latestCallProgress.details.elapsed_seconds)} 秒` : '';
    const laneTotal = Number(laneStarted[0]?.details?.lane_count || laneStarted.length || 0);
    const stage = materialization ? `并行材料化 ${materialization.attempted_count || 0}/${materialization.candidate_count || 0} · 本批 ${materialization.parallel_batch_size || 1} 路 · 接纳 ${materialization.accepted_count || 0}/${materialization.target_count || 0}${materialization.cache_hit_count ? ` · 缓存复用 ${materialization.cache_hit_count}` : ''}${materialization.continued_after_threshold ? ' · 已达门槛，继续扩展异源/反证' : materialization.quality_threshold_met ? ' · 多源候选完成' : ''}` : waitingForSlot ? `等待模型槽位 · ${latestQueue.details?.active || 0}/${latestQueue.details?.limit || 0} 使用中` : analysisDone ? '结构化分析完成，准备材料化' : analysisStarted ? `结构化分析中 · ${discoveryDone?.details?.source_count || 0} 个来源${modelRunning && slotText ? ` · ${slotText}${queueText}${elapsedText}` : ''}` : discoveryDone ? `检索完成 · ${discoveryDone.details?.source_count || 0} 个来源` : laneTotal ? `并行检索 ${laneCompleted.length}/${laneTotal} 通道${modelRunning && slotText ? ` · ${slotText}${queueText}${elapsedText}` : ''}` : '准备检索';
    return `${agentMap[agentId]?.display_name || agentId}：${stage}`;
  }).slice(0, 2);
  const baselineDetail = `${completedAgents}${baselineAgentIds.size ? ` / ${baselineAgentIds.size}` : ''} 个 Agent 已完成${baselineProgress.length ? ` · ${baselineProgress.join('；')}` : runningBaselineNames.length ? ` · 正在执行 ${runningBaselineNames.join('、')}` : ''}`;
  const fallbackSteps = events.filter(event => event.event_type === 'winning_subagent_completed' && event.details?.execution_mode !== 'dynamic').map(event => ({...event.details, agent_id: event.actor}));
  const planByStep = new Map([...fallbackSteps, ...(workflow.step_plan || [])].map(item => [Number(item.step), item]));
  const dynamicProfile = execution.profile_id === 'winning_swarm_dynamic_v2';
  const workflowDynamicAgents = Array.isArray(workflow.dynamic_agents) ? workflow.dynamic_agents : [];
  const dynamicCandidates = workflowDynamicAgents.length ? workflowDynamicAgents : (Array.isArray(metaReview.dynamic_subagents) ? metaReview.dynamic_subagents : []);
  const dynamicAgents = [...new Map(dynamicCandidates.map((agent, index) => [`${agent.display_name || agent.name || agent.agent_id || agent.id || `dynamic-${index}`}|${normalizeMergeTarget(agent)}`, agent])).values()];
  const s3Materialization = [...events].reverse().find(event => event.event_type === 'winning_s3_active_agents_materialized');
  const activeS3InstanceIds = new Set(stringList(s3Materialization?.details?.active_instance_ids));
  const stepCards = S_AGENT_ARCHITECTURE.map(meta => {
    const plan = planByStep.get(meta.step) || {};
    const agent = agentMap[plan.agent_id] || agentMap[meta.agent_id] || {};
    const rawNodeMembers = dynamicAgents.filter(item => {
      if (normalizeMergeTarget(item) !== `S${meta.step}` || item.inactive_capacity) return false;
      if (normalizeWorkflowStatus(plan.status) === 'completed' && ['planned', 'recruiting', 'queued', 'running'].includes(String(item.status || 'planned').toLowerCase())) return false;
      if (meta.step !== 3 || activeS3InstanceIds.size === 0) return true;
      return activeS3InstanceIds.has(String(item.agent_instance_id || item.id || item.agent_id || ''));
    });
    const nodeMembers = [...new Map(rawNodeMembers.map((item, index) => [String(item.agent_instance_id || item.id || item.agent_id || `${normalizeMergeTarget(item)}-${index}`), item])).values()];
    const hasActualDecision = plan.decision_finalized === true || nodeMembers.length > 0 || fallbackSteps.some(item => Number(item.step) === meta.step);
    const provisionalDynamic = dynamicProfile && !hasActualDecision;
    const executionMode = nodeMembers.length || provisionalDynamic ? 'dynamic' : plan.execution_mode || plan.mode || 'standard';
    const completedEvent = fallbackSteps.some(item => Number(item.step) === meta.step && item.execution_mode !== 'skip' && item.status !== 'skipped_by_branch_blueprint');
    let status = provisionalDynamic ? 'pending' : normalizeSAgentStatus(plan.status, executionMode, completedEvent);
    const memberStatuses = nodeMembers.map(item => String(item.status || 'planned').toLowerCase());
    const dynamicCompleted = memberStatuses.filter(item => ['completed', 'merged'].includes(item)).length;
    const dynamicActive = memberStatuses.some(item => ['recruiting', 'queued', 'running'].includes(item));
    const dynamicTerminal = memberStatuses.length > 0 && memberStatuses.every(item => ['completed', 'merged', 'pruned', 'failed', 'skipped'].includes(item));
    const canonicalTerminal = ['completed', 'skipped', 'failed'].includes(status);
    if (!canonicalTerminal && dynamicActive) status = 'running';
    else if (!canonicalTerminal && dynamicTerminal && dynamicCompleted > 0) status = 'completed';
    else if (!canonicalTerminal && dynamicTerminal && memberStatuses.includes('failed')) status = 'failed';
    else if (!canonicalTerminal && nodeMembers.length) status = 'pending';
    const projectedCycle = Number(plan.middle_cycle || 0);
    const middleCycle = Number.isFinite(projectedCycle) ? Math.max(0, projectedCycle) : 0;
    const skills = stringList(plan.skill_ids || plan.skills || agent.skill_ids || agent.skills || meta.skills);
    const harness = plan.harness_profile || plan.harness || agent.harness_profile || meta.harness;
    const semantics = [...new Set([
      ...(plan.parallel_group ? [`并行组 ${plan.parallel_group}`] : []),
      ...(stringList(plan.depends_on).length ? [`依赖 ${stringList(plan.depends_on).map(value => normalizeStepRef(value)).join('/')}`] : []),
      ...meta.semantics,
    ])].slice(0, 4);
    const mergedAgents = nodeMembers;
    const backtrackCount = Number(plan.backtrack_count ?? events.filter(event => eventTargetsStep(event, meta.step, plan.agent_id || meta.agent_id)).length);
    const projectedName = plan.name || plan.label?.replace(/^S\d+\s*/, '') || agent.display_name?.replace(/^S\d+\s*/, '') || meta.name;
    const dynamicResultSummary = nodeMembers.length ? `动态蜂群 ${dynamicCompleted} / ${nodeMembers.length} 个实例完成` : '';
    return {...meta, ...plan, agent_id: plan.agent_id || meta.agent_id, name: ensureAgentSuffix(projectedName), task: plan.task || plan.description || agent.description || meta.task, executionMode, status, provisionalDynamic, middleCycle, skills, harness, semantics, mergedAgents, result_summary: provisionalDynamic ? '' : dynamicResultSummary || plan.result_summary || '', dynamicCompleted, dynamicTotal: nodeMembers.length, backtrackCount: Number.isFinite(backtrackCount) ? Math.max(0, backtrackCount) : 0};
  });
  const otherDynamicAgents = dynamicAgents.filter(item => !/^S[1-6]$/.test(normalizeMergeTarget(item)));
  const completedSteps = stepCards.filter(item => item.status === 'completed').length;
  const unsettledSteps = stepCards.filter(item => !['completed', 'skipped'].includes(item.status));
  const unsettledStepText = unsettledSteps.map(item => `S${item.step}${item.status === 'running' ? '仍在收敛' : item.status === 'failed' ? '未通过' : '待调度'}`).join('、');
  const stepProgressDetail = `${completedSteps} / 6 个专用 Agent 已完成${unsettledStepText ? ` · ${unsettledStepText}${stepCards.find(item => item.step === 6)?.status === 'completed' ? '；S6 已完成能力图像综合' : ''}` : ''}`;
  const stageGates = Array.isArray(workflow.stage_gates) ? workflow.stage_gates : [];
  const restrictedGates = stageGates.filter(item => item.gate_passed === false);
  const branchText = discovery.primary_branch ? `${discovery.primary_branch}${discovery.branch_name ? ` · ${discovery.branch_name}` : ''}` : '需求解析与路径选择';
  const stepModeChanges = metaReview.step_mode_changes?.length ? metaReview.step_mode_changes.map(item => `S${item.step} ${stepModeLabel(item.previous_mode)}→${stepModeLabel(item.mode)}`).join('、') : metaReview.step_mode_overrides?.length ? metaReview.step_mode_overrides.map(item => `S${item.step}→${stepModeLabel(item.mode)}`).join('、') : '';
  const l4Changes = [metaReview.added_secondary_branches?.length ? `参考分支 ${metaReview.added_secondary_branches.join('/')}` : '', stepModeChanges, metaReview.dynamic_subagents?.length ? `新增 ${metaReview.dynamic_subagents.length} 个动态 Agent` : ''].filter(Boolean).join('；');
  // Older runs could finish Reporter after an audit timeout. Once a report is
  // durably completed, replay the audit as a completed/limited fast path
  // rather than surfacing the obsolete pending label forever.
  const auditPending = (has('audit_model_pending') || has('audit_model_unavailable')) && !has('report_completed');
  const auditComplete = !auditPending && (completed || has('audit_completed') || has('report_completed') || has('run_result_saved'));
  const reportStatus = latestReporterPhaseStatus(events, completed);
  const latestWinningProgress = [...events].reverse().find(event => ['winning_model_queue_started', 'winning_model_call_started', 'winning_model_call_progress', 'winning_model_call_completed'].includes(event.event_type));
  const latestWinningDetails = latestWinningProgress?.details || {};
  const winningRuntimeDetail = latestWinningDetails.current_step ? ` · 当前 ${latestWinningDetails.current_step}${Number(latestWinningDetails.elapsed_seconds || 0) > 0 ? ` · 已耗时 ${Math.round(latestWinningDetails.elapsed_seconds)} 秒` : ''}` : '';
  const latestReportProgress = [...events].reverse().find(event => ['report_model_queue_started', 'report_model_call_started', 'report_model_call_progress', 'report_model_call_completed'].includes(event.event_type));
  const latestReportDetails = latestReportProgress?.details || {};
  const reportRuntimeDetail = latestReportDetails.current_step ? `${latestReportDetails.current_step}${Number(latestReportDetails.elapsed_seconds || 0) > 0 ? ` · 已耗时 ${Math.round(latestReportDetails.elapsed_seconds)} 秒` : ''}` : '独立报告 Agent 正在撰写';
  const phaseFallbacks = [
    {id: 'blueprint', label: 'A–H 蓝图', status: has('run_started') || has('discovery_meta_loop_evaluated') ? 'completed' : 'pending', detail: metaReview.replan_required ? `${branchText}；L4 已调整` : branchText},
    {id: 'baseline', label: '前置专业研究', status: has('baseline_agents_summarized') ? 'completed' : has('baseline_pipeline_started') || has('baseline_discovery_started') || has('baseline_wave_started') ? 'running' : 'pending', detail: baselineDetail},
    {id: 'convergence', label: '收敛融合', status: has('discovery_convergence_completed') ? 'completed' : 'pending', detail: '跨背景、场景与分支聚合'},
    {id: 's_agents', label: 'S1–S6 Agent', status: completedSteps > 0 || latestWinningProgress || has('winning_stage_completed') || has('capability_image_created') ? (stepCards.every(item => ['completed', 'skipped'].includes(item.status)) ? 'completed' : 'running') : 'pending', detail: `${stepProgressDetail}${winningRuntimeDetail}${restrictedGates.length ? ` · ${restrictedGates.map(item => item.layer).join('/')} 门控受限` : ''}`},
    {id: 'audit', label: '业务审计', status: auditPending ? 'pending' : auditComplete ? 'completed' : events.some(event => event.actor === 'auditor') ? 'running' : 'pending', detail: auditPending ? '业务审计进行中 · 报告可继续审阅' : auditComplete ? '业务审计完成' : events.some(event => event.actor === 'auditor') ? '正在执行业务审计（快速判断业务实质与安全风险）' : '等待进入业务审计'},
    {id: 'report', label: '报告交付', status: reportStatus, detail: reportStatus === 'completed' ? '研究报告已生成' : reportStatus === 'failed' ? '独立报告生成失败，未使用降级模板；可从检查点恢复' : reportStatus === 'running' ? reportRuntimeDetail : '等待审计通过'},
  ];
  const rawPhases = Array.isArray(workflow.phases) ? workflow.phases : [];
  const phaseById = new Map(rawPhases.map((item, index) => [item.id || phaseFallbacks[index]?.id, item]));
  const phases = phaseFallbacks.map(fallback => { const projected = phaseById.get(fallback.id) || {}; const projectedStatus = normalizeWorkflowStatus(projected.status ?? projected.completed, fallback.status); const useProjectedProgress = projectedStatus === 'failed' || workflowStatusRank(projectedStatus) >= workflowStatusRank(fallback.status); return {...fallback, ...projected, label: fallback.id === 'audit' ? fallback.label : projected.label || projected.name || fallback.label, detail: fallback.id === 'baseline' || fallback.id === 'audit' ? fallback.detail : useProjectedProgress ? projected.detail || projected.summary || fallback.detail : fallback.detail, status: useProjectedProgress ? projectedStatus : fallback.status}; });
  const loops = workflow.loops || {};
  const loopEventTypes = {inner: 'winning_inner_loop_evaluated', middle: 'winning_middle_loop_evaluated', outer: 'winning_outer_loop_evaluated', meta: 'discovery_meta_loop_evaluated'};
  const firstPending = phases.findIndex(item => !['completed', 'skipped'].includes(item.status));
  return <section className="workflow-overview">
    <header><div><Layers3 size={18}/><span><b>架构执行总览</b><small>A–H 发现蓝图、六个专用 Agent 与四层循环</small></span></div><div className="workflow-badges">{execution.provider && <span>Agent</span>}{discovery.primary_branch && <span>主分支 {discovery.primary_branch}</span>}{discovery.secondary_branches?.length > 0 && <span>参考分支 {discovery.secondary_branches.join('/')}</span>}<em className={live ? 'live' : ''}>{live ? '运行中' : '审计回放'}</em></div></header>
    <div className="workflow-phases workflow-phases-six">{phases.map((phase, index) => <article className={`${phase.status} ${phase.status === 'completed' ? 'done' : index === firstPending && live && phase.status === 'pending' ? 'active' : ''}`} key={phase.id}><i>{phase.status === 'completed' ? <CheckCircle2 size={15}/> : index + 1}</i><div><b>{phase.label}</b><small>{phase.detail}</small></div></article>)}</div>
    <div className="s-agent-overview"><div className="s-agent-overview-title"><div><Bot size={17}/><span><b>S1–S6 专用 Agent</b><small>{dynamicProfile ? `动态蜂群根据依赖和质量残差实时调度；${unsettledStepText ? `当前 ${unsettledStepText}，${stepCards.find(item => item.step === 6)?.status === 'completed' ? 'S6 已完成能力图像综合。' : ''}` : '六个节点均已收敛。'}` : '当前主/参考分支通过执行强度影响每个 Agent；支持并行与定向回溯。'}</small></span></div><em title={stepProgressDetail}>{completedSteps} / 6 已完成</em></div><div className="s-agent-grid">{stepCards.map(agent => <article className={`s-agent-card mode-${agent.executionMode} status-${agent.status}`} key={agent.step}>
      <header><i>S{agent.step}</i><div><b>{agent.name}</b><small>独立受控会话</small></div><span className={`s-agent-status ${agent.status}`}>{sAgentStatusLabel(agent.status)}</span></header>
      <p>{agent.task}</p>
      {agent.status === 'running' && agent.current_step && <div className="s-agent-result-preview"><small>当前步骤</small><span>{agent.current_step}{Number(agent.elapsed_seconds || 0) > 0 ? ` · 已耗时 ${Math.round(agent.elapsed_seconds)} 秒` : ''}</span></div>}
      {agent.result_summary && <div className="s-agent-result-preview"><small>本轮结果</small><span>{agentFacingText(agent.result_summary)}</span></div>}
      <div className="s-agent-runtime"><span className={`step-mode ${agent.executionMode}`}>{agent.executionMode === 'dynamic' ? '动态调度' : stepModeLabel(agent.executionMode)}</span><span>{agent.provisionalDynamic ? '等待执行判定' : agent.dynamicTotal > 0 ? `蜂群 ${agent.dynamicCompleted}/${agent.dynamicTotal}` : agent.middleCycle > 0 ? `L2 第 ${agent.middleCycle} 轮` : 'L2 未进入'}</span><span>回溯 {agent.backtrackCount} 次</span></div>
      {agent.status === 'skipped' && <small className="s-agent-skip-reason">由 {discovery.primary_branch || '当前'} 分支蓝图按业务路径跳过</small>}
      <details className="s-agent-tech"><summary>Skill、Harness 与编排说明</summary><div><code>{agent.agent_id}</code><div className="s-agent-skills"><small>核心 Skill</small><p>{agent.skills.slice(0, 3).map(skill => <em key={skill}>{skill}</em>)}</p></div><div className="s-agent-harness"><span>Harness</span><code>{agent.harness}</code></div><div className="s-agent-semantics">{agent.semantics.map(item => <span key={item}>{item}</span>)}</div></div></details>
      {agent.mergedAgents.length > 0 && <div className="s-agent-dynamic">{agent.mergedAgents.map((item, index) => <span key={item.agent_id || item.id || index}><Bot size={12}/><b>{userFacingSwarmMemberName({...item, mission_node: item.mission_node || `S${agent.step}`})}</b><small>合并到 S{agent.step}</small></span>)}</div>}
    </article>)}</div>{otherDynamicAgents.length > 0 && <div className="dynamic-agent-other">{otherDynamicAgents.map((item, index) => <span key={item.agent_id || item.id || index}><Bot size={12}/><b>{userFacingSwarmMemberName(item)}</b><small>合并到 {normalizeMergeTarget(item) || '待编排节点'}</small></span>)}</div>}</div>
    <div className="loop-overview">{LOOP_ARCHITECTURE.map(loop => { const projected = typeof loops[loop.key] === 'object' ? loops[loop.key] : {}; const count = loopCount(loops[loop.key], loop.key === 'meta' ? Number(metaReview.cycle || 0) : 0); const latest = [...events].reverse().find(event => event.event_type === loopEventTypes[loop.key]); return <article className={count > 0 ? 'used' : ''} key={loop.key}><header><i>{loop.level}</i><div><b>{loop.name}</b><span>{count} 次</span></div></header><p>{projected.description || loop.description}</p><small className="loop-latest">{latest ? `最近：${loopEventDecision(latest)}` : '最近：尚无判定'}</small></article>; })}</div>
    {metaReview.replan_required && <div className="l4-summary"><BrainCircuit size={15}/><span><b>L4 元循环调整</b>{l4Changes || metaReview.rationale || '已形成有界调整'}</span></div>}
  </section>;
}

function InteractionEvent({event, agent}) {
  const tool = event.details?.tool_name;
  const eventSummary = event.event_type === 'baseline_agent_completed' ? completedResearchSummary(event.summary) : event.summary;
  const summary = agentFacingText(eventSummary);
  const longSummary = summary.length > 260 || /^\s*[\[{]/.test(summary);
  const swarmLifecycle = ['specialist_recruitment_planned','specialist_spawned','specialist_session_started','specialist_session_completed','specialist_completed','specialist_pruned','winning_agent_waiting'].includes(event.event_type);
  const detailKeys = event.event_type === 'discovery_meta_loop_evaluated' ? ['cycle','primary_branch','added_secondary_branches','step_mode_overrides','dynamic_subagents','stop_reason'] : swarmLifecycle ? ['wave','batch','archetype','hypothesis_id','merge_target','mission_node','execution_backend','context_isolation','session_ref','status','reason','running_instances','note','attempt','resume_count'] : ['wave','batch','agent_id','session_ref','attempt','resume_count','archetype','hypothesis_id','merge_target','score','residuals','reasons','rejection_reasons','step','steps','current_step','elapsed_seconds','phase','execution_mode','status','passed'];
  const detailRows = detailKeys.filter(key => event.details?.[key] !== undefined).slice(0, 10).map(key => [key, event.details[key]]);
  const eventAgent = {...(agent || {}), display_name: agent?.display_name || event.details?.display_name || event.actor, mission_node: agent?.mission_node || event.details?.mission_node || event.details?.merge_target};
  return <article className={`event-card ${event.category}`}><div className="event-dot">{event.category === 'tool' ? <Wrench size={15}/> : event.actor === 'orchestrator' ? <Layers3 size={15}/> : <Bot size={15}/>}</div><div className="event-content"><div className="event-top"><b>{userFacingSwarmMemberName(eventAgent)}</b><span>{displayEventLabel(event.event_type)}</span></div><h3>{agentFacingText(tool || event.title)}</h3>{longSummary ? <details className="event-summary-details"><summary><span>{summary}</span><em>展开完整内容</em></summary><p>{summary}</p></details> : <p>{summary}</p>}{(event.input_refs?.length > 0 || event.output_refs?.length > 0 || detailRows.length > 0) && <details className="event-key-details"><summary>关键详情</summary><div className="event-detail-grid">{event.input_refs?.length > 0 && <Detail label="输入引用" value={agentFacingText(event.input_refs.slice(0, 4).join(' · '))}/>} {event.output_refs?.length > 0 && <Detail label="输出引用" value={agentFacingText(event.output_refs.slice(0, 4).join(' · '))}/>} {detailRows.map(([key, value]) => <Detail key={key} label={fieldLabel(key)} value={formatValue(value)}/>)}</div></details>}</div></article>;
}

function ObjectGrid({view, rows, runId, run = null, ...favoriteProps}) {
  const list = Array.isArray(rows) ? rows : Array.isArray(rows?.rows) ? rows.rows : [];
  const referenceWeapons = Array.isArray(rows?.referenceWeapons) ? rows.referenceWeapons : [];
  if (!list.length && !referenceWeapons.length) return <Empty text="本次运行没有可展示对象"/>;
  if (view === 'capabilities') return <CapabilityImageView rows={list} referenceWeapons={referenceWeapons} runId={runId} run={run} {...favoriteProps}/>;
  const query = [run?.topic, run?.supplemental_information].filter(Boolean).join('\n');
  return <section className="object-grid">{list.map((row, index) => {
    const label = objectTitle(view, row, index);
    // Evidence/stage rows can have a display title without representing an
    // equipment identity.  Keep the single-equipment deep-thinking contract
    // explicit: only rows carrying an equipment form or server lineage ID
    // may open a bound dialogue; generic evidence remains read-only here.
    const equipmentTarget = Boolean(
      row?.primary_equipment_identity
      || row?.equipment_form
      || row?.equipment_forms?.length
      || row?.equipment_category
      || row?.capability_id
      || row?.card_binding_id
      || row?.candidate_id
      || row?.hypothesis_id
    );
    const evidenceRefs = row?.evidence_ids || row?.evidence_refs || row?.input_refs || [];
    const context = {
      runId,
      kind: 'deep-thinking',
      title: `${view === 'evidence' ? '证据' : 'S1–S6'}追问 · ${label}`,
      query,
      candidate: row,
      current_result_context: {
        selected: row,
        view,
        evidence_refs: Array.isArray(evidenceRefs) ? evidenceRefs : [],
      },
    };
    return <article className="object-card" key={row.evidence_id || row.stage_id || row.capability_id || index}><div className="object-card-head"><b>{label}</b><span>{row.layer || row.priority || row.source_tier || `#${index + 1}`}</span></div>{Object.entries(row).filter(([key, value]) => !['created_at', 'schema_version'].includes(key) && value !== '' && value != null).slice(0, 10).map(([key, value]) => <Detail key={key} label={fieldLabel(key)} value={formatValue(value)}/>)}<footer className="object-card-actions">{equipmentTarget ? <button type="button" className="deep-followup-button" onClick={() => openDeepThinking(context)}><BrainCircuit size={13}/>深度追问</button> : <span className="deep-followup-hint">请从具体装备卡进入深度思考</span>}</footer></article>;
  })}</section>;
}
const CAPABILITY_PORTRAIT_LABELS = ['概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果', '制胜逻辑机理与对抗边界', '制胜逻辑机理', '制胜逻辑', '发展与验证路径', '决策与考核口径'];
const WEAPON_DIMENSION_GUIDE = {
  damage: ['毁伤维度', '直接破坏目标，或削弱目标的结构、功能与作战效能。'],
  strike: ['打击维度', '对指定目标实施远程或近程攻击并施加军事效果。'],
  penetration: ['突防维度', '突破敌方防御体系并进入目标有效作用区域。'],
  interception: ['拦截维度', '发现、跟踪并阻断敌方目标行动。'],
  suppression: ['压制维度', '降低敌方感知、通信、火力或行动能力。'],
  denial: ['拒止维度', '阻止敌方进入特定区域、实施行动或持续作战。'],
  reconnaissance: ['侦察感知维度', '发现、识别、定位目标并感知作战环境。'],
  early_warning: ['预警维度', '提前发现威胁并形成有效响应窗口。'],
  electronic_countermeasure: ['电子对抗维度', '干扰、削弱或影响敌方电子信息系统。'],
  deterrence: ['威慑维度', '通过可信军事能力影响敌方判断、决策与行为。'],
  survivability: ['生存抗毁维度', '提高装备在威胁环境下的生存、恢复与持续作战能力。'],
  battlefield_control: ['战场控制维度', '改变特定区域、空间或时间维度上的作战主动权。'],
};
function normalizeWeaponDimensions(classification = {}) {
  if (!classification || typeof classification !== 'object') return {primary: '', secondary: [], basis: ''};
  const primary = String(classification.primary_dimension || classification.primary || '').trim();
  const rawSecondary = classification.secondary_dimensions || classification.secondary || [];
  const secondary = Array.isArray(rawSecondary) ? rawSecondary.map(item => String(item).trim()).filter(Boolean) : String(rawSecondary).split(/[、,，;；]/).map(item => item.trim()).filter(Boolean);
  const primaryLabel = weaponDimensionLabel(primary);
  const seen = new Set([primaryLabel || primary]);
  const uniqueSecondary = secondary.filter(item => {
    const label = weaponDimensionLabel(item);
    if (!label || seen.has(label)) return false;
    // An equipment title or form is not a capability dimension.
    if (/弹|弹药|导弹|巡飞|母弹|平台|战斗体|舱|无人机|无人艇|无人车/.test(item) && !/维度$/.test(item)) return false;
    seen.add(label);
    return true;
  });
  return {primary, secondary: uniqueSecondary.slice(0, 2), basis: String(classification.classification_basis || '').trim()};
}
function weaponDimensionLabel(value) {
  const key = String(value || '').trim();
  const match = WEAPON_DIMENSION_GUIDE[key];
  if (match) return match[0];
  const inferred = [
    [/毁伤|摧毁|杀伤|破坏/, 'damage'],
    [/突防|穿透|渗透/, 'penetration'],
    [/拦截|阻断目标/, 'interception'],
    [/压制|抑制/, 'suppression'],
    [/拒止|禁入|区域控制/, 'denial'],
    [/侦察|感知|探测|识别/, 'reconnaissance'],
    [/预警|提前发现/, 'early_warning'],
    [/电子对抗|干扰|电磁/, 'electronic_countermeasure'],
    [/威慑/, 'deterrence'],
    [/生存|抗毁|恢复|韧性/, 'survivability'],
    [/战场控制|作战主动权|时空控制/, 'battlefield_control'],
    [/打击|弹药|巡猎|攻击|火力/, 'strike'],
  ].find(([pattern]) => pattern.test(key));
  if (inferred) return WEAPON_DIMENSION_GUIDE[inferred[1]][0];
  return key;
}
function WeaponDimensions({classification}) {
  const dimensions = normalizeWeaponDimensions(classification);
  if (!dimensions.primary && !dimensions.secondary.length) return null;
  const values = [dimensions.primary, ...dimensions.secondary].filter(Boolean);
  return <section className="capability-dimensions"><div className="capability-dimensions-head"><b>武器维度</b><span>按当前装备的主要战果与作战节点匹配，维度不限制 S6 继续推演新的能力关系。</span></div><div className="capability-dimension-tags">{values.map((value, index) => <span className={index === 0 ? 'primary' : ''} key={`${value}-${index}`}><i>{index === 0 ? '主' : '辅'}</i>{weaponDimensionLabel(value)}</span>)}</div>{dimensions.basis && <p>{dimensions.basis}</p>}</section>;
}
function capabilityClassificationText(value) {
  if (value == null || value === '') return '—';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).filter(Boolean).join('、') || '—';
  const dimensions = normalizeWeaponDimensions(value);
  const labels = [dimensions.primary, ...dimensions.secondary].filter(Boolean).map(weaponDimensionLabel);
  return labels.length ? labels.join('、') : JSON.stringify(value);
}
function parseCapabilityPortrait(value) {
  const normalized = sanitizeCapabilityPortraitText(completeCapabilityText(value)).replace(/\r/g, '').replace(/\s+/g, ' ').trim();
  if (!normalized) return {overview:'', points:[]};
  const labelPattern = new RegExp(`(${CAPABILITY_PORTRAIT_LABELS.join('|')})\\s*[：:]`, 'g');
  const matches = [...normalized.matchAll(labelPattern)];
  if (!matches.length) return {overview:normalized.replace(/^[-*•]\s*/, ''), points:[]};
  const cleanSectionText = text => sanitizeCapabilityPortraitSection(text.replace(/(?:^|\s)[-*•]\s*$/, '').trim());
  const cleanOverviewText = text => cleanSectionText(text).replace(/^[【\[]?能力分类\s*[：:][^。】\]]*[。】\]]?\s*/, '').trim();
  let overview = cleanOverviewText(normalized.slice(0, matches[0].index));
  const points = [];
  matches.forEach((match, index) => {
    const text = cleanSectionText(normalized.slice(match.index + match[0].length, matches[index + 1]?.index ?? normalized.length));
    if (!text) return;
    if (match[1] === '概述') {
      if (!overview) overview = cleanOverviewText(text);
      return;
    }
    const label = match[1] === '制胜逻辑机理与对抗边界' ? '制胜逻辑机理' : match[1];
    points.push({label, text});
  });
  return {overview, points};
}
const PORTRAIT_SCHEMA_LEAK_KEY_PATTERN = /\b(?:key_technologies|system_architecture|implementation_path|key_bottlenecks|keyword_context|intelligence_requirement|latency_requirement|coordination_requirement|enabling_technologies|module_content|operational_steps|capability_portrait_modules)\b/;
function sanitizeCapabilityPortraitSection(text) {
  const raw = String(text || '').trim();
  if (!raw) return '';
  if (!PORTRAIT_SCHEMA_LEAK_KEY_PATTERN.test(raw) && !/^\s*[{\[].*[}\]]\s*$/s.test(raw)) return raw;
  return raw
    .replace(new RegExp(PORTRAIT_SCHEMA_LEAK_KEY_PATTERN.source, 'g'), ' ')
    .replace(/['"]?[a-z][a-z0-9]*(?:_[a-z0-9]+)+['"]?\s*:/g, ' ')
    .replace(/[{}\[\]'"]/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/(?:；|;|,|，){2,}/g, '；')
    .trim()
    .replace(/^[，,；;。:：\s]+|[，,；;。:：\s]+$/g, '');
}
function sanitizeCapabilityPortraitText(value) {
  const text = String(value || '');
  if (!text || (!PORTRAIT_SCHEMA_LEAK_KEY_PATTERN.test(text) && !/\{['"]?[a-z]+_[a-z0-9_]+/.test(text))) return text;
  return text
    .replace(new RegExp(PORTRAIT_SCHEMA_LEAK_KEY_PATTERN.source, 'g'), ' ')
    .replace(/['"]?[a-z][a-z0-9]*(?:_[a-z0-9]+)+['"]?\s*:/g, ' ')
    .replace(/[{}\[\]'=]/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/(?:；|;|,|，){2,}/g, '；')
    .trim();
}
function tableTextWeight(value) {
  const text = String(value || '').replace(/\s/g, '');
  if (!text) return 1;
  const cjk = (text.match(/[\u3400-\u9fff]/g) || []).length;
  const latin = (text.match(/[A-Za-z0-9]/g) || []).length * 0.65;
  const punctuation = (text.match(/[，。；：、,.!?！？;:/（）()【】\[\]“”"'·-]/g) || []).length * 0.2;
  return Math.max(1, cjk + latin + punctuation);
}
function adaptiveTableWidths(rows = [], minimums = [], maximums = []) {
  const count = minimums.length;
  if (!count) return [];
  const safeRows = Array.isArray(rows) ? rows : [];
  const weights = Array.from({length: count}, (_, column) => {
    const values = safeRows.map(row => tableTextWeight(row?.[column]));
    const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 1;
    return Math.sqrt(Math.max(1, average));
  });
  const minimumTotal = minimums.reduce((sum, value) => sum + value, 0);
  const remaining = Math.max(0, 100 - minimumTotal);
  const weightTotal = weights.reduce((sum, value) => sum + value, 0) || count;
  const widths = minimums.map((minimum, index) => minimum + remaining * (weights[index] / weightTotal));
  if (maximums.length === count) {
    let excess = widths.reduce((sum, value, index) => sum + Math.max(0, value - maximums[index]), 0);
    while (excess > 0.01) {
      const flexible = widths.map((value, index) => value < maximums[index] - 0.01 ? index : -1).filter(index => index >= 0);
      if (!flexible.length) break;
      const share = excess / flexible.length;
      flexible.forEach(index => { widths[index] += share; });
      widths.forEach((value, index) => { if (value > maximums[index]) widths[index] = maximums[index]; });
      excess = 100 - widths.reduce((sum, value) => sum + value, 0);
    }
  }
  const rounded = widths.map(value => Number(value.toFixed(2)));
  rounded[rounded.length - 1] = Number((rounded[rounded.length - 1] + (100 - rounded.reduce((sum, value) => sum + value, 0))).toFixed(2));
  return rounded;
}
function adaptivePageProfile(rows = []) {
  const cellWeights = rows.flatMap(row => row.map(tableTextWeight));
  const totalWeight = cellWeights.reduce((sum, value) => sum + value, 0);
  const largestCell = Math.max(0, ...cellWeights);
  const useA3 = totalWeight > 2200 || largestCell > 700 || rows.length > 4;
  return useA3
    ? {pageClass: 'page-a3', width: 16838, height: 23811, contentWidth: 22371}
    : {pageClass: 'page-a4', width: 11906, height: 16838, contentWidth: 15398};
}
// Deep-research projections carry provenance and verification metadata in
// several generations of the API.  Keep the display/export boundary tolerant
// of those aliases while preserving the immutable formal card as the default
// baseline.
function capabilityDeepMeta(row = {}) {
  const sourceRow = row && typeof row === 'object' ? row : {};
  const deepSource = sourceRow.is_deep_research
    || /deep|reference_weapon|supplement|深研/i.test(String(sourceRow.source || sourceRow.version_source || ''))
    || sourceRow.version_no != null
    || sourceRow.version != null;
  const status = String(
    sourceRow.verification_status
    || sourceRow.version_status
    || sourceRow.status
    || (sourceRow.confidence_limited || deepSource ? 'pending_verification' : 'formal'),
  ).trim().toLowerCase();
  const source = String(
    sourceRow.source
    || sourceRow.version_source
    || (sourceRow.is_deep_research ? 'reference_weapon_deep_research' : 'formal_s6'),
  ).trim();
  // `research_version` is the sidecar/API alias used by older deep-research
  // projections.  Do not render an opaque version_id as "v…" when a numeric
  // version is unavailable; the id remains available in the session ledger.
  const version = sourceRow.version_no ?? sourceRow.version ?? sourceRow.research_version ?? '';
  const statusLabel = ['verified', 'formal', 'approved', 'accepted'].includes(status)
    ? '已核验'
    : status === 'rejected'
      ? '已驳回'
      : ['rolled_back', 'rollback'].includes(status)
        ? '已回滚'
        : '待核验';
  return {status, source, version: String(version || '').replace(/^v/i, ''), statusLabel};
}
// Deep research keeps the formal S6 card immutable and appends versioned
// projections.  Use the server-bound lineage first when grouping those rows;
// fall back to a normalized name only for legacy artifacts that predate the
// binding fields.  This is display-only and never changes the exported/raw
// capability snapshot.
function capabilityLineageKey(row = {}) {
  const source = row && typeof row === 'object' ? row : {};
  // Hypothesis is the version-chain boundary.  A new divergent hypothesis
  // can intentionally reuse the parent card binding, but it must render as a
  // separate chain; otherwise the UI falsely presents an unrelated direction
  // as v2/v3 of the original card.  Card binding/capability IDs remain useful
  // fallbacks for older formal snapshots that predate hypothesis persistence.
  for (const field of ['hypothesis_id', 'card_binding_id', 'capability_id']) {
    const value = normalizeFavoriteText(source[field]);
    if (value) return `${field}:${value}`;
  }
  const name = normalizeFavoriteText(source.name || source.title || source.capability_name);
  const form = normalizeFavoriteText(source.equipment_form || source.equipment_category);
  return `legacy:${name}|${form}`;
}
function capabilityVersionRank(row = {}, index = 0) {
  const meta = capabilityDeepMeta(row);
  const formal = ['formal', 'verified', 'approved', 'accepted'].includes(meta.status);
  const parsed = Number(meta.version);
  return [formal ? 0 : 1, Number.isFinite(parsed) && parsed > 0 ? parsed : formal ? 1 : 999999, index];
}
function CapabilityPortrait({value}) { const {overview, points} = parseCapabilityPortrait(value); const modules = [{label:'概述', text:overview}, ...points].filter(item => item.text); return <section className="capability-portrait"><small>装备能力画像 · 五模块作战论证</small><div className="capability-portrait-cards">{modules.map((item, index) => <article className="capability-portrait-card" key={`${item.label}-${index}`}><b>{item.label}</b><p>{item.text}</p></article>)}</div></section>; }

function CapabilityImageView({rows, referenceWeapons = [], runId = '', run = null, favoriteIndex = {}, onFavoriteToggle, highlightedCardKey = ''}) {
  const confidencePercent = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
  const [snapshotRows, setSnapshotRows] = useState(null);
  const [versionLedger, setVersionLedger] = useState([]);
  const [versionManagerOpen, setVersionManagerOpen] = useState(false);
  const [versionManagerLoading, setVersionManagerLoading] = useState(false);
  const [versionManagerError, setVersionManagerError] = useState('');
  const [versionMutationBusy, setVersionMutationBusy] = useState({});
  const [referenceResearchJobs, setReferenceResearchJobs] = useState([]);
  const [referenceResearchBusy, setReferenceResearchBusy] = useState({});
  const [referenceResearchError, setReferenceResearchError] = useState('');
  const referenceResearchAttemptRef = useRef({});
  const referenceResearchJobsRef = useRef([]);
  const referenceResearchRequestRef = useRef(0);
  const capabilitySnapshotRequestRef = useRef(0);
  // Keep an optimistic local projection while the parent workspace is still
  // polling.  The API also projects these sidecar cards from /capabilities,
  // so the local state is only a short-lived bridge after a button click.
  useEffect(() => { setSnapshotRows(null); }, [runId, rows]);
  const displayedRows = Array.isArray(snapshotRows) ? snapshotRows : (Array.isArray(rows) ? rows : []);
  const visibleReferenceWeapons = referenceWeapons.filter(candidate => hasWeaponCandidateIdentity(candidate) && !referenceWeaponDuplicatesCapability(candidate, displayedRows));
  const [feedbackItems, setFeedbackItems] = useState([]);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackTarget, setFeedbackTarget] = useState('');
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackVerdict, setFeedbackVerdict] = useState('needs_revision');
  const [feedbackExpertScores, setFeedbackExpertScores] = useState(() => Object.fromEntries(S5_SCORE_DIMENSIONS.map(({key}) => [key, ''])));
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackError, setFeedbackError] = useState('');
  const [feedbackLoadError, setFeedbackLoadError] = useState('');
  const feedbackDialogRef = useOverlay(feedbackOpen, {onEscape: () => setFeedbackOpen(false)});
  // Run IDs are opaque identifiers. Keep them as one path segment even when a
  // legacy/artifact-backed ID contains punctuation that has a meaning in a
  // URL. This also keeps the GET and POST endpoints on exactly the same ID.
  const encodedRunId = encodeURIComponent(String(runId || '').trim());
  const loadVersionLedger = async (silent = false) => {
    if (!encodedRunId) return [];
    if (!silent) setVersionManagerLoading(true);
    const result = await requestResult(`/runs/${encodedRunId}/capability-versions`, {headers: deepScopeHeadersForRun(run)});
    if (!silent) setVersionManagerLoading(false);
    if (!result.ok) {
      if (!silent) setVersionManagerError(result.detail || '无法读取深研版本。');
      return [];
    }
    const versions = Array.isArray(result.data?.versions) ? result.data.versions : [];
    setVersionLedger(versions);
    setVersionManagerError('');
    return versions;
  };
  const deepQuery = [run?.topic, run?.supplemental_information].filter(value => String(value || '').trim()).join('\n') || '当前研究 Query';
  const compactDeepText = value => String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, 900);
  const compactCapabilityContext = useMemo(() => displayedRows.slice(0, 16).map(row => ({
    capability_id: row?.capability_id || '',
    card_binding_id: row?.card_binding_id || '',
    hypothesis_id: row?.hypothesis_id || '',
    name: row?.name || '',
    capability_classification: row?.capability_classification || {},
    confidence: row?.confidence,
    verification_status: row?.verification_status || '',
    source: row?.source || '',
    deep_capability_portrait: compactDeepText(row?.deep_capability_portrait || row?.capability_image),
    capability_portrait_modules: row?.capability_portrait_modules || undefined,
    evidence_ids: Array.isArray(row?.evidence_ids) ? row.evidence_ids.slice(0, 8) : [],
  })), [displayedRows]);
  const compactReferenceContext = useMemo(() => visibleReferenceWeapons.slice(0, 16).map(candidate => ({
    capability_id: candidate?.capability_id || '',
    card_binding_id: candidate?.card_binding_id || '',
    hypothesis_id: candidate?.hypothesis_id || '',
    title: weaponCandidateTitle(candidate),
    equipment_form: weaponCandidateForm(candidate),
    overview: compactDeepText(swarmCandidateOverview(candidate)),
    score: candidate?.score ?? candidate?.evaluation_score ?? candidate?.composite_score ?? null,
  })), [visibleReferenceWeapons]);
  const openDeepContext = (kind, target = {}, focus = '') => {
    openDeepThinking({
      runId,
      kind,
      title: target.title || target.name || target.capability_name || (kind === 'deep-thinking' ? '当前研究的深度思考' : ''),
      capability_id: target.capability_id || '',
      card_binding_id: target.card_binding_id || target.row?.card_binding_id || '',
      capability_name: target.capability_name || target.name || target.title || '',
      hypothesis_id: target.hypothesis_id || '',
      candidate: target.candidate || target.reference_weapon || target.row || target || {},
      reference_weapon: target.reference_weapon || target.candidate || target.row || target || {},
      query: deepQuery,
      focus,
      current_result_context: {
        selected: target.row || target.candidate || target,
        capability_cards: compactCapabilityContext,
        reference_weapons: compactReferenceContext,
      },
    });
  };
  const loadCapabilitySnapshot = async () => {
    const requestId = ++capabilitySnapshotRequestRef.current;
    if (!encodedRunId) return null;
    const result = await requestResult(`/runs/${encodedRunId}/capabilities`, {headers: deepScopeHeadersForRun(run)});
    if (requestId !== capabilitySnapshotRequestRef.current) return null;
    if (!result.ok || !Array.isArray(result.data)) return null;
    setSnapshotRows(result.data);
    return result.data;
  };
  const loadReferenceResearch = async (silent = false) => {
    const requestId = ++referenceResearchRequestRef.current;
    if (!encodedRunId) return null;
    const result = await requestResult(`/runs/${encodedRunId}/deep-thinking/reference-research`, {headers: deepScopeHeadersForRun(run)});
    if (requestId !== referenceResearchRequestRef.current) return null;
    if (!result.ok) {
      if (!silent) setReferenceResearchError(result.detail || '无法读取参考武器深研状态。');
      return null;
    }
    setReferenceResearchError('');
    const jobs = (Array.isArray(result.data?.jobs) ? result.data.jobs : [])
      .map(normalizeReferenceResearchJob)
      .filter(Boolean);
    setReferenceResearchJobs(jobs);
    // The sidecar is intentionally included in the same capabilities view by
    // the API.  Reading it here keeps the card visible before the parent
    // workspace's normal polling cycle catches up.
    const research = Array.isArray(result.data?.research) ? result.data.research : [];
    if (research.length) setSnapshotRows(current => {
      const base = Array.isArray(current) ? current : displayedRows;
      const byKey = new Map(base.map(item => [String(item?.hypothesis_id || item?.capability_id || ''), item]));
      research.forEach(item => {
        const key = String(item?.hypothesis_id || item?.capability_id || '');
        if (key) byKey.set(key, item);
      });
      return [...byKey.values()];
    });
    return {jobs, research};
  };
  useEffect(() => { void loadReferenceResearch(true); void loadVersionLedger(true); }, [encodedRunId]);
  useEffect(() => { referenceResearchJobsRef.current = referenceResearchJobs; }, [referenceResearchJobs]);
  useEffect(() => {
    if (!encodedRunId) return undefined;
    let cancelled = false;
    const terminalReferenceStatuses = new Set(['completed', 'failed', 'failed_to_queue', 'cancelled', 'archived', 'partial', 'blocked', 'rejected']);
    const poll = async () => {
      if (cancelled) return;
      const active = referenceResearchJobsRef.current.some(rawJob => {
        const job = normalizeReferenceResearchJob(rawJob);
        return Boolean(job && !terminalReferenceStatuses.has(String(job.status || '').toLowerCase()) && !job.merged);
      });
      if (!active) return;
      const snapshot = await loadReferenceResearch(true);
      if (cancelled || !snapshot?.jobs?.length) return;
      // Ask the durable job endpoint for active dialogue turns as well so the
      // card status and pending-version projection update promptly after a
      // worker tick.  The current flow has no child Run to poll.
      const activeJobs = snapshot.jobs.filter(item => !terminalReferenceStatuses.has(String(item?.status || '').toLowerCase()) && item?.job_id);
      await Promise.all(activeJobs.slice(0, 8).map(async item => {
        const response = await requestResult(`/runs/${encodedRunId}/deep-thinking/jobs/${encodeURIComponent(item.job_id)}`, {headers: deepScopeHeadersForRun(run)});
        if (cancelled || !response.ok) return;
        const latest = normalizeReferenceResearchJob(response.data?.job || response.data);
        if (!latest || typeof latest !== 'object') return;
        setReferenceResearchJobs(current => current.map(row => String(row?.job_id || '') === String(item.job_id) ? latest : row));
      }));
    };
    const timer = setInterval(() => { void poll(); }, 3000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [encodedRunId]);
  useEffect(() => {
    const onCapabilitiesChanged = event => {
      if (event?.detail?.runId && String(event.detail.runId) !== String(runId)) return;
      void loadCapabilitySnapshot();
      void loadReferenceResearch(true);
      void loadVersionLedger(true);
    };
    window.addEventListener('equipment-capabilities-changed', onCapabilitiesChanged);
    return () => window.removeEventListener('equipment-capabilities-changed', onCapabilitiesChanged);
  }, [encodedRunId, runId]);
  const normalizeReferenceResearchJob = job => {
    if (!job || typeof job !== 'object') return null;
    const payload = job.payload && typeof job.payload === 'object' ? job.payload : {};
    const candidate = job.candidate && typeof job.candidate === 'object'
      ? job.candidate
      : payload.candidate && typeof payload.candidate === 'object' ? payload.candidate : {};
    const localResult = job.local_result && typeof job.local_result === 'object' ? job.local_result : {};
    return {
      ...job,
      hypothesis_id: job.hypothesis_id || payload.hypothesis_id || candidate.hypothesis_id || localResult.hypothesis_id || '',
      capability_name: job.capability_name || payload.capability_name || candidate.title || candidate.name || candidate.equipment_form || localResult.name || '',
      candidate,
      query_snapshot_hash: job.query_snapshot_hash || payload.query_snapshot_hash || '',
      focus_hash: job.focus_hash || payload.focus_hash || '',
      local_result: localResult,
    };
  };
  const referenceResearchKey = candidate => String(candidate?.hypothesis_id || candidate?.candidate_id || candidate?.id || weaponCandidateTitle(candidate) || weaponCandidateForm(candidate) || '').trim();
  const referenceResearchIdentityMatches = (candidate, rawJob) => {
    const item = normalizeReferenceResearchJob(rawJob);
    if (!item || !candidate) return false;
    const itemCandidate = item.candidate && typeof item.candidate === 'object' ? item.candidate : {};
    // Hypothesis/candidate IDs are the canonical single-equipment boundary.
    // Do not fall back to a shared card_binding_id when both sides carry a
    // hypothesis: two divergent hypotheses may intentionally share a parent
    // card but must show independent research status on their own cards.
    const candidateHypothesis = normalizeFavoriteText(candidate?.hypothesis_id);
    const itemHypothesis = normalizeFavoriteText(item?.hypothesis_id || itemCandidate?.hypothesis_id);
    if (candidateHypothesis || itemHypothesis) return Boolean(candidateHypothesis && itemHypothesis && candidateHypothesis === itemHypothesis);
    const candidateStrongValues = [candidate?.candidate_id, candidate?.card_binding_id, candidate?.capability_id]
      .map(value => normalizeFavoriteText(value)).filter(Boolean);
    const itemStrongValues = [item?.candidate_id, item?.card_binding_id, item?.capability_id, itemCandidate?.candidate_id, itemCandidate?.card_binding_id, itemCandidate?.capability_id]
      .map(value => normalizeFavoriteText(value)).filter(Boolean);
    if (candidateStrongValues.length || itemStrongValues.length) {
      return candidateStrongValues.length > 0 && itemStrongValues.length > 0 && candidateStrongValues.some(value => itemStrongValues.includes(value));
    }
    const candidateNames = [
      weaponCandidateTitle(candidate),
      weaponCandidateForm(candidate),
    ].map(value => normalizeFavoriteText(value)).filter(Boolean);
    const itemNames = [
      item?.capability_name,
      weaponCandidateTitle(itemCandidate),
      weaponCandidateForm(itemCandidate),
    ].map(value => normalizeFavoriteText(value)).filter(Boolean);
    return candidateNames.some(value => itemNames.includes(value));
  };
  const referenceResearchJobFor = candidate => referenceResearchJobs.find(rawItem => referenceResearchIdentityMatches(candidate, rawItem));
  const startReferenceResearch = async candidate => {
    const key = referenceResearchKey(candidate);
    if (!encodedRunId || !key || referenceResearchBusy[key]) return;
    const name = weaponCandidateTitle(candidate) || weaponCandidateForm(candidate) || '参考武器方向';
    const focus = `围绕“${name}”改写既有装备假设，提出新的构型、作用机理、作战角色和直接军事效果。`;
    // 定向深研和连续追问共用同一对话入口。
    openDeepContext('reference-research', {
      candidate,
      reference_weapon: candidate,
      hypothesis_id: candidate?.hypothesis_id || '',
      title: `参考武器深度研究 · ${name}`,
      capability_name: name,
    }, focus);
  };
  useEffect(() => {
    let cancelled = false;
    setFeedbackItems([]);
    setFeedbackLoadError('');
    if (!encodedRunId) return undefined;
    requestResult(`/runs/${encodedRunId}/expert-feedback`, {headers: {'X-Role': 'analyst'}}).then(result => {
      if (cancelled) return;
      if (!result.ok) {
        setFeedbackLoadError(result.detail || '无法读取当前任务的专家反馈。');
        return;
      }
      const items = Array.isArray(result.data) ? result.data : result.data?.items;
      setFeedbackItems(Array.isArray(items) ? items : []);
    });
    return () => { cancelled = true; };
  }, [encodedRunId]);
  useEffect(() => {
    const targetKey = String(highlightedCardKey || '').trim();
    if (!targetKey) return undefined;
    const target = [...document.querySelectorAll('.capability-sheet')].find(node => node.dataset.cardKey === targetKey);
    if (!target) return undefined;
    target.scrollIntoView({behavior: 'smooth', block: 'start'});
    target.classList.add('capability-highlight');
    const timer = setTimeout(() => target.classList.remove('capability-highlight'), 2600);
    return () => clearTimeout(timer);
  }, [highlightedCardKey, rows]);
  const capabilityVersionGroups = useMemo(() => {
    const groups = new Map();
    displayedRows.forEach((row, index) => {
      const key = capabilityLineageKey(row) || `row:${index}`;
      if (!groups.has(key)) groups.set(key, {key, rows: []});
      groups.get(key).rows.push({row, index});
    });
    return [...groups.values()].map(group => {
      const ordered = group.rows.slice().sort((left, right) => {
        const a = capabilityVersionRank(left.row, left.index);
        const b = capabilityVersionRank(right.row, right.index);
        for (let index = 0; index < a.length; index += 1) {
          if (a[index] !== b[index]) return a[index] - b[index];
        }
        return 0;
      });
      const name = ordered[0]?.row?.name || ordered[0]?.row?.title || ordered[0]?.row?.capability_name || '未命名能力';
      const hasVersionChain = ordered.length > 1 || ordered.some(({row}) => {
        const meta = capabilityDeepMeta(row);
        return Boolean(row?.is_deep_research || meta.version || meta.source !== 'formal_s6');
      });
      return {...group, rows: ordered, name, hasVersionChain};
    });
  }, [displayedRows]);
  const feedbackCapability = displayedRows.find(row => String(row.capability_id || row.name) === feedbackTarget);
  const feedbackModelScores = portfolioS5Scores(feedbackCapability);
  const storedFeedbackWeighted = feedbackCapability?.s5_weighted_score;
  const feedbackModelWeighted = weightedS5Score(feedbackModelScores) ?? (storedFeedbackWeighted != null && Number.isFinite(Number(storedFeedbackWeighted)) ? Number(storedFeedbackWeighted) : null);
  const parsedFeedbackExpertScores = Object.fromEntries(S5_SCORE_DIMENSIONS.flatMap(({key}) => {
    const raw = String(feedbackExpertScores[key] ?? '').trim();
    const value = Number(raw);
    return raw && Number.isFinite(value) ? [[key, value / 100]] : [];
  }));
  const feedbackExpertWeighted = weightedS5Score(parsedFeedbackExpertScores);
  const resetFeedbackScores = () => setFeedbackExpertScores(Object.fromEntries(S5_SCORE_DIMENSIONS.map(({key}) => [key, ''])));
  const openFeedback = target => { setFeedbackTarget(target || ''); setFeedbackVerdict('needs_revision'); resetFeedbackScores(); setFeedbackOpen(true); setFeedbackError(''); };
  const submitFeedback = async event => {
    event.preventDefault();
    if (!encodedRunId) { setFeedbackError('当前任务缺少有效运行 ID，请刷新任务后重试。'); return; }
    if (!feedbackComment.trim()) { setFeedbackError('请填写反馈意见。'); return; }
    if (feedbackCapability && !S5_SCORE_DIMENSIONS.every(({key}) => Number.isFinite(parsedFeedbackExpertScores[key]) && parsedFeedbackExpertScores[key] >= 0 && parsedFeedbackExpertScores[key] <= 1)) { setFeedbackError('请为五个维度填写 0–100 分。'); return; }
    setFeedbackSaving(true); setFeedbackError('');
    const capability = feedbackCapability;
    const feedbackPayload = {capability_id: capability?.capability_id || '', hypothesis_id: capability?.hypothesis_id || '', capability_name: capability?.name || '本任务整体能力画像', comment: feedbackComment.trim(), verdict: capability ? feedbackVerdict : 'needs_revision', rating: capability ? Math.max(1, Math.min(5, Math.round((feedbackExpertWeighted || 0) * 5))) : null, dimensions: capability ? S5_SCORE_DIMENSIONS.map(({key}) => key) : [], target_agent_ids: capability ? ['S5'] : [], stage_scope: capability ? ['S5'] : [], model_dimension_scores: capability ? feedbackModelScores : {}, expert_dimension_scores: capability ? parsedFeedbackExpertScores : {}, reviewer_role: 'expert'};
    // Keep retries of the same visible submission idempotent while allowing a
    // genuinely new comment to create a new feedback record.  The server is
    // authoritative; this key is only a stable request hint.
    const feedbackKey = `feedback:${encodedRunId}:${stableClientHash(JSON.stringify(feedbackPayload))}`;
    const result = await requestResult(`/runs/${encodedRunId}/expert-feedback`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst', 'Idempotency-Key': feedbackKey}, body: JSON.stringify(feedbackPayload)});
    setFeedbackSaving(false);
    if (!result.ok) {
      const detail = String(result.detail || '');
      setFeedbackError(/run\s+not\s+found|任务不存在/i.test(detail) ? '任务记录已过期，请刷新任务列表后重新选择。' : detail || '反馈保存失败，请稍后重试。');
      return;
    }
    const saved = result.data?.feedback || (result.data?.feedback_id ? result.data : null);
    if (!saved) { setFeedbackError('反馈接口返回了无效结果，请刷新后重试。'); return; }
    setFeedbackItems(current => [...current, saved]); setFeedbackLoadError(''); setFeedbackComment(''); resetFeedbackScores(); setFeedbackOpen(false);
  };
  const feedbackCount = feedbackItems.length;
  const versionStatusLabel = status => ({formal:'正式基线', verified:'已核验', pending_verification:'待核验', pending:'待核验', rejected:'已驳回', rolled_back:'已回滚', deleted:'已删除', partial:'部分结果', blocked:'已阻塞', failed:'失败', cancelled:'已取消'}[String(status || '').toLowerCase()] || String(status || '待核验'));
  const mutateCapabilityVersion = async (version, mode = 'delete') => {
    const versionId = String(version?.version_id || '').trim();
    if (!encodedRunId || !versionId || versionMutationBusy[versionId]) return;
    const name = version?.snapshot?.name || version?.snapshot?.title || `v${version?.version_no || '?'}`;
    const action = mode === 'restore' ? 'restore' : mode === 'purge' ? 'purge' : 'delete';
    if (action === 'delete' && !window.confirm(`确定删除深研版本“${name} · v${version?.version_no || '?'}”吗？\n\n正式 S6 基线不受影响，删除后可在版本管理中恢复。`)) return;
    if (action === 'purge' && !window.confirm(`确定永久删除深研版本“${name} · v${version?.version_no || '?'}”吗？\n\n此操作不可恢复，版本将从账本中彻底移除。`)) return;
    setVersionMutationBusy(current => ({...current, [versionId]: true}));
    setVersionManagerError('');
    const mutationNonce = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const suffix = action === 'restore'
      ? `/capability-versions/${encodeURIComponent(versionId)}/restore`
      : action === 'purge'
        ? `/capability-versions/${encodeURIComponent(versionId)}/permanent`
        : `/capability-versions/${encodeURIComponent(versionId)}`;
    const result = await requestResult(`/runs/${encodedRunId}${suffix}`, {
      method: action === 'restore' ? 'POST' : 'DELETE',
      headers: {...deepScopeHeadersForRun(run), 'Idempotency-Key': `${action}-version:${versionId}:${mutationNonce}`},
    });
    setVersionMutationBusy(current => ({...current, [versionId]: false}));
    if (!result.ok) {
      const failLabel = action === 'restore' ? '版本恢复失败。' : action === 'purge' ? '永久删除失败。' : '版本删除失败。';
      setVersionManagerError(result.detail || failLabel);
      notify(action === 'restore' ? '版本恢复失败' : action === 'purge' ? '永久删除失败' : '版本删除失败', 'error');
      return;
    }
    await Promise.all([loadVersionLedger(true), loadCapabilitySnapshot(), loadReferenceResearch(true)]);
    window.dispatchEvent(new CustomEvent('equipment-capabilities-changed', {detail: {runId}}));
    notify(action === 'restore' ? '深研版本已恢复' : action === 'purge' ? '深研版本已永久删除' : '深研版本已删除，可在版本管理中恢复', 'ok');
  };
  const capabilityTableHeaders = ['装备', '来源 / 版本状态', '能力分类', '概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果', '制胜逻辑'];
  const capabilityTableRows = useMemo(() => displayedRows.map(row => {
    const parsed = parseCapabilityPortrait(completeCapabilityText(row.deep_capability_portrait || row.capability_image));
    const points = Object.fromEntries(parsed.points.map(item => [item.label, item.text]));
    const meta = capabilityDeepMeta(row);
    const equipmentName = capabilityEquipmentName(row) || '—';
    const equipmentDirection = capabilityEquipmentDirection(row);
    const name = `${equipmentName}${equipmentDirection ? `\n装备方向：${equipmentDirection}` : ''}${meta.version ? `（v${meta.version}）` : ''}${meta.statusLabel === '待核验' && (row.is_deep_research || meta.version || meta.source !== 'formal_s6') ? ' · 待核验' : ''}`;
    const versionLabel = meta.version ? `v${meta.version}` : 'v1';
    return [name, `${meta.source || 'formal_s6'} · ${versionLabel} · ${meta.statusLabel}`, capabilityClassificationText(row.capability_classification), parsed.overview || '—', points['装备与技术实现'] || '—', points['关键作战流程'] || '—', points['形成能力与作战效果'] || '—', points['制胜逻辑'] || points['制胜逻辑机理'] || '—'];
  }), [displayedRows]);
  const capabilityColumnWidths = useMemo(() => adaptiveTableWidths(capabilityTableRows, [10, 10, 8, 11, 12, 11, 12, 11], [18, 18, 14, 20, 22, 20, 22, 20]), [capabilityTableRows]);
  const capabilityPageProfile = useMemo(() => adaptivePageProfile(capabilityTableRows), [capabilityTableRows]);
  const referenceTableRows = useMemo(() => visibleReferenceWeapons.map(candidate => [weaponCandidateTitle(candidate) || '—', `${swarmCandidateOverview(candidate) || '暂无参考概述'} · 来源：参考武器候选 · 状态：待核验`]), [visibleReferenceWeapons]);
  const referenceColumnWidths = useMemo(() => adaptiveTableWidths(referenceTableRows, [20, 52], [38, 80]), [referenceTableRows]);
  const exportCapabilityCards = async () => {
    try {
      const {Document: WordDocument, Packer, Paragraph: WordParagraph, Table: WordTable, TableRow: WordTableRow, TableCell: WordTableCell, TextRun: WordTextRun, HeadingLevel, WidthType, AlignmentType, PageOrientation, TableLayoutType, ShadingType, BorderStyle, VerticalAlign} = await import('docx');
      const title = `能力画像_${new Date().toISOString().slice(0, 10)}`;
      const rowsForWord = capabilityTableRows;
      const border = {style: BorderStyle.SINGLE, size: 1, color: 'D9D9D9'};
      const makeTable = (head, data, widths) => new WordTable({width: {size: 100, type: WidthType.PERCENTAGE}, columnWidths: widths, layout: TableLayoutType.FIXED, borders: {top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border}, rows: [head, ...data].map((line, rowIndex) => new WordTableRow({tableHeader: rowIndex === 0, cantSplit: rowIndex === 0, children: line.map((cell, cellIndex) => new WordTableCell({width: {size: widths[cellIndex], type: WidthType.DXA}, shading: rowIndex === 0 ? {fill: 'EAF0FF', type: ShadingType.SOLID} : rowIndex % 2 === 0 ? {fill: 'FBFCFF', type: ShadingType.SOLID} : undefined, verticalAlign: VerticalAlign.CENTER, margins: {top: 90, bottom: 90, left: 110, right: 110}, children: [new WordParagraph({alignment: cellIndex < 2 ? AlignmentType.CENTER : AlignmentType.LEFT, spacing: {after: 0}, children: [new WordTextRun({text: String(cell), bold: rowIndex === 0, size: rowIndex === 0 ? 18 : 17, font: {ascii: 'Arial', hAnsi: 'Arial', eastAsia: 'Microsoft YaHei'}, color: rowIndex === 0 ? '243B7A' : '26344D'})]})]}))}))});
      const refRows = visibleReferenceWeapons.map(candidate => [weaponCandidateTitle(candidate) || '—', `${swarmCandidateOverview(candidate) || '暂无参考概述'} · 来源：参考武器候选 · 状态：待核验`]);
      const totalDxa = capabilityPageProfile.contentWidth;
      const toDxa = widths => { const values = widths.map(value => Math.round(totalDxa * value / 100)); values[values.length - 1] += totalDxa - values.reduce((sum, value) => sum + value, 0); return values; };
      const doc = new WordDocument({sections: [{properties: {page: {size: {orientation: PageOrientation.LANDSCAPE, width: capabilityPageProfile.width, height: capabilityPageProfile.height}, margin: {top: 720, bottom: 720, left: 720, right: 720}}}, children: [new WordParagraph({heading: HeadingLevel.TITLE, alignment: AlignmentType.CENTER, spacing: {after: 260}, children: [new WordTextRun({text: '能力画像', bold: true, size: 30, color: '000000'})]}), makeTable(capabilityTableHeaders, rowsForWord, toDxa(capabilityColumnWidths)), ...(refRows.length ? [new WordParagraph({pageBreakBefore: capabilityPageProfile.pageClass === 'page-a3', keepNext: true, spacing: {before: 360, after: 140}, children: [new WordTextRun({text: '参考装备', bold: true, size: 24, color: '000000'})]}), makeTable(['参考装备', '概述'], refRows, toDxa(referenceColumnWidths))] : [])]}]});
      const blob = await Packer.toBlob(doc); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${title}.docx`; link.click(); URL.revokeObjectURL(url); notify('能力画像 DOCX 已导出', 'ok');
    } catch (error) {
      console.error('DOCX export failed', error); notify('DOCX 导出失败，请稍后重试', 'error');
    }
  };
  const renderCapabilityCard = ({row, index}) => {
    const portrait = completeCapabilityText(row.deep_capability_portrait || row.capability_image);
    const meta = capabilityDeepMeta(row);
    const equipmentName = capabilityEquipmentName(row) || row.name || '未命名装备';
    const equipmentDirection = capabilityEquipmentDirection(row) || capabilityDisplayEquipmentForm(row);
    const pendingVerification = ['pending', 'pending_verification', 'unverified'].includes(meta.status) || row.confidence_limited === true;
    // A ledger-backed formal S6 baseline also carries version_no=v1.  Version
    // metadata alone must not relabel that immutable baseline as a deep result
    // or expose a delete control that the server will correctly reject.
    const formalBaseline = meta.status === 'formal' && meta.source === 'formal_s6' && !row.is_deep_research;
    const deepResearch = !formalBaseline && Boolean(row.is_deep_research || meta.source !== 'formal_s6' || meta.version);
    const components = row.confidence_components || {};
    const scoreTitle = `证据贴合 ${Math.round((components.evidence_fit || 0) * 100)}% · 前瞻可验证 ${Math.round((components.foresight || 0) * 100)}%`;
    const cardFeedback = feedbackItems.filter(item => (item.capability_id && item.capability_id === row.capability_id) || (item.capability_name && item.capability_name === row.name));
    const cardKey = favoriteCardKey(row);
    const favorite = favoriteIndex?.[favoriteIndexKey(runId, row)] || (row.favorited ? {favorite_id: row.favorite_id || row.id || '', card_key: cardKey} : null);
    const favorited = Boolean(favorite || row.favorited);
    const favoriteEligible = capabilityPortraitIsComplete(row) && !pendingVerification;
    const favoritePending = Boolean(favorite?.pending);
    return <article className={`capability-sheet${pendingVerification ? ' pending-verification' : ''}${deepResearch ? ' deep-research-capability' : ''}`} data-card-key={cardKey} key={`${row.capability_id || row.name || 'capability'}-${index}`}>
      <header><div><div className="capability-title-row"><div className="capability-identity"><span>装备名称</span><h2>{equipmentName}{meta.version ? <small className="capability-version-label">v{meta.version}</small> : null}</h2>{equipmentDirection && <p><b>装备方向</b>{equipmentDirection}</p>}</div>{deepResearch && <span className="capability-source-badge deep-research-source">深研结果</span>}<button type="button" className={`favorite-star${favorited ? ' is-favorited' : ''}${favoritePending ? ' is-pending' : ''}`} disabled={(!favoriteEligible && !favorited) || favoritePending || !onFavoriteToggle} aria-pressed={favorited} aria-label={favorited ? `取消收藏：${equipmentName}` : `收藏：${equipmentName}`} title={!favoriteEligible && !favorited ? '仅完整 S6 能力画像可收藏' : favorited ? '取消收藏' : '收藏能力画像'} onClick={() => void onFavoriteToggle(row, runId, !favorited)}><Star size={17} fill={favorited ? 'currentColor' : 'none'}/></button></div><div className="capability-card-actions"><button type="button" onClick={() => openFeedback(row.capability_id || row.name)}><MessageSquare size={13}/>针对本卡反馈</button><button type="button" className="deep-followup-button" onClick={() => openDeepContext('capability-followup', {row, ...row, capability_name: equipmentName}, `以“${equipmentName}”为种子，从不同制胜角度改写其构型、作用机理与作战角色。`)}><BrainCircuit size={13}/>定向深研 / 追问</button>{deepResearch && row.version_id && <button type="button" className="capability-version-delete" disabled={Boolean(versionMutationBusy[row.version_id])} onClick={() => void mutateCapabilityVersion({version_id: row.version_id, version_no: row.version_no || meta.version, status: meta.status, snapshot: row})}><Trash2 size={13}/>{versionMutationBusy[row.version_id] ? '删除中…' : '删除此版本'}</button>}{cardFeedback.length > 0 && <span><MessageSquare size={12}/> {cardFeedback.length} 条反馈</span>}{deepResearch && <span className="deep-job-chip">{meta.statusLabel} · {meta.source || '深研来源'}</span>}</div></div><div className="capability-score" title={scoreTitle}><b>{confidencePercent(row.confidence)}</b><small>{pendingVerification ? '综合置信度（待核验）' : '综合置信度'}</small></div></header>
      <WeaponDimensions classification={row.capability_classification}/>{portrait ? <CapabilityPortrait value={portrait}/> : <div className="capability-legacy-note">等待 S6 单卡成稿</div>}
    </article>;
  };
  return <section className="capability-view">
    <div className="capability-toolbar"><div><b>能力画像成果</b><small>深研命名复用 S3/S4 的 A–O 类型分配；画像正文严格复用 S6 五栏原始写作规范，并保留可删除、可恢复的版本链</small></div><div><button type="button" className="deep-toolbar-button" onClick={() => openDeepContext('deep-thinking', {title: '当前研究的深度思考'}, '选择一个目标装备，经内部多维深度发散形成新质构型、机理与作战角色，并收敛为五栏能力画像。')}><BrainCircuit size={14}/>深度思考 Agent</button><button type="button" className={versionManagerOpen ? 'is-active' : ''} onClick={() => { const next = !versionManagerOpen; setVersionManagerOpen(next); if (next) void loadVersionLedger(); }}><GitCompare size={14}/>深研版本管理</button><button type="button" onClick={() => void exportCapabilityCards()}><Download size={14}/>导出 DOCX</button><button type="button" className="primary" onClick={() => window.print()}><Printer size={14}/>打印 / 导出 PDF</button></div></div>
    {versionManagerOpen && <section className="capability-version-manager"><header><div><GitCompare size={16}/><span><b>深研版本管理</b><small>正式 S6 基线不可删除；深研版本可先隐藏后恢复，也可对已隐藏版本永久删除。</small></span></div><button type="button" className="icon-button" onClick={() => setVersionManagerOpen(false)} aria-label="关闭版本管理"><X size={16}/></button></header>{versionManagerError && <p className="form-error"><CircleAlert size={14}/>{versionManagerError}</p>}{versionManagerLoading ? <div className="capability-version-manager-empty"><RefreshCw size={15} className="spin"/>正在读取版本链…</div> : versionLedger.length ? <div className="capability-version-manager-list">{versionLedger.slice().reverse().map(version => { const status = String(version.status || 'pending_verification').toLowerCase(); const deleted = status === 'deleted'; const formal = status === 'formal'; const versionName = version?.snapshot?.name || version?.snapshot?.title || '未命名能力画像'; const busy = Boolean(versionMutationBusy[version.version_id]); return <article className={deleted ? 'is-deleted' : ''} key={version.version_id}><div><b>{versionName}</b><span><em>v{version.version_no || '?'}</em><small className={`version-manager-status ${status}`}>{versionStatusLabel(status)}</small><small>{version.created_at ? new Date(version.created_at).toLocaleString('zh-CN', {hour12:false}) : ''}</small></span></div>{formal ? <span className="version-manager-protected"><ShieldCheck size={13}/>不可变基线</span> : deleted ? <div className="version-manager-actions"><button type="button" className="version-restore-button" disabled={busy} onClick={() => void mutateCapabilityVersion(version, 'restore')}>{busy ? <RefreshCw size={13} className="spin"/> : <History size={13}/>} {busy ? '处理中…' : '恢复'}</button><button type="button" className="capability-version-purge" disabled={busy} onClick={() => void mutateCapabilityVersion(version, 'purge')}>{busy ? <RefreshCw size={13} className="spin"/> : <Trash2 size={13}/>} {busy ? '处理中…' : '永久删除'}</button></div> : <button type="button" className="capability-version-delete" disabled={busy} onClick={() => void mutateCapabilityVersion(version, 'delete')}>{busy ? <RefreshCw size={13} className="spin"/> : <Trash2 size={13}/>} {busy ? '处理中…' : '删除'}</button>}</article>; })}</div> : <div className="capability-version-manager-empty">当前任务尚无深研版本。</div>}</section>}
    <div className={`capability-print-table ${capabilityPageProfile.pageClass}`}><h1>能力画像</h1><table><colgroup>{capabilityColumnWidths.map((width, index) => <col key={`cap-col-${index}`} style={{width: `${width}%`}} />)}</colgroup><thead><tr>{capabilityTableHeaders.map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{capabilityTableRows.map((cells, index) => <tr key={`print-${displayedRows[index]?.version_id || displayedRows[index]?.capability_id || 'capability'}-${index}`}>{cells.map((cell, cellIndex) => <td key={`${index}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table>{referenceTableRows.length > 0 && <section className={`capability-reference-print-block ${capabilityPageProfile.pageClass === 'page-a3' ? 'page-break-before' : ''}`}><h2>参考装备</h2><table><colgroup>{referenceColumnWidths.map((width, index) => <col key={`ref-col-${index}`} style={{width: `${width}%`}} />)}</colgroup><thead><tr><th>参考装备</th><th>概述</th></tr></thead><tbody>{referenceTableRows.map((cells, index) => <tr key={`print-ref-${index}`}>{cells.map((cell, cellIndex) => <td key={`${index}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></section>}</div>
    <section className="expert-feedback-panel"><header><div><span className="expert-feedback-icon"><MessageSquare size={17}/></span><span><b>专家审核反馈</b><small>画像卡反馈统一记录五维评分与意见；任务整体反馈保留为文字意见。</small></span></div><div className="expert-feedback-head-actions"><em>{feedbackCount ? `已记录 ${feedbackCount} 条` : '尚未反馈'}</em><button type="button" className="primary" onClick={() => openFeedback('')}><MessageSquare size={14}/>提交反馈</button></div></header><div className="expert-feedback-learning"><Sparkles size={15}/><span><b>记忆处理 Agent 已接入</b><small>自动去重、压缩、相关性评分，并限制每个后续 Agent 读取的记忆数量，避免多卡反馈造成上下文噪声。</small></span></div>{feedbackLoadError && <p className="form-error"><CircleAlert size={14}/>{feedbackLoadError}</p>}{feedbackCount > 0 && <div className="expert-feedback-history">{feedbackItems.slice(-3).reverse().map(item => <article key={item.feedback_id}><header><span className="feedback-verdict processed">已处理</span><b>{item.capability_name || '本任务整体'}</b>{Number.isFinite(Number(item.expert_weighted_score)) && item.expert_weighted_score != null && <span className="feedback-score-chip">专家综合 {Math.round(Number(item.expert_weighted_score) * 100)}</span>}<small>{item.created_at ? new Date(item.created_at).toLocaleString('zh-CN', {hour12:false}) : ''}</small></header><p>{item.comment || '未填写反馈意见。'}</p>{item.learning_signal && <div><Sparkles size={13}/><span><b>已提炼高价值记忆 · {Array.isArray(item.target_agent_ids) ? item.target_agent_ids.join('、') : '自动路由'}</b>{item.learning_signal}</span></div>}</article>)}</div>}</section>
    {feedbackOpen && <div className="expert-feedback-modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setFeedbackOpen(false); }}><form className="expert-feedback-form portfolio-score-feedback-form" ref={feedbackDialogRef} role="dialog" aria-modal="true" aria-label="提交专家审核意见" onSubmit={submitFeedback} onMouseDown={event => event.stopPropagation()}><header><div><b>{feedbackCapability ? '针对本卡反馈' : '提交专家审核意见'}</b><small>{feedbackCapability ? `${feedbackCapability.name || '能力画像'} · 五维评分与 S5 保持同一口径` : '任务整体反馈将自动处理后路由给相关 S1–S6 Agent。'}</small></div><button type="button" className="icon-button" onClick={() => setFeedbackOpen(false)} aria-label="关闭反馈表单"><X size={16}/></button></header><label className="expert-feedback-target"><span>反馈对象</span><select value={feedbackTarget} onChange={event => { setFeedbackTarget(event.target.value); setFeedbackVerdict('needs_revision'); resetFeedbackScores(); }}><option value="">本任务整体能力画像</option>{displayedRows.map((row, index) => <option key={`${row.version_id || row.capability_id || row.name || 'capability'}-${index}`} value={row.capability_id || row.name}>{row.name}</option>)}</select></label>{feedbackCapability && <><section className="portfolio-score-comparison" aria-label="模型评分与专家评分对照"><header><span>评分维度</span><span>当前 S5</span><span>专家评分</span></header>{S5_SCORE_DIMENSIONS.map(({key, label, weight}) => <label key={key}><span><b>{label}</b><small>权重 {Math.round(weight * 100)}%</small></span><output>{Number.isFinite(feedbackModelScores[key]) ? Math.round(feedbackModelScores[key] * 100) : '—'}</output><span className="portfolio-score-input"><input type="number" min="0" max="100" step="1" inputMode="numeric" value={feedbackExpertScores[key]} onChange={event => setFeedbackExpertScores(current => ({...current, [key]: event.target.value}))} aria-label={`${label}专家评分`} required/><em>分</em></span></label>)}<footer><span>综合评分</span><output>{feedbackModelWeighted == null ? '—' : Math.round(feedbackModelWeighted * 100)}</output><b>{feedbackExpertWeighted == null ? '待填写' : Math.round(feedbackExpertWeighted * 100)}</b></footer></section><label><span>审核结论</span><select value={feedbackVerdict} onChange={event => setFeedbackVerdict(event.target.value)}><option value="approved">认可画像</option><option value="needs_revision">建议修订</option><option value="rejected">建议淘汰</option></select></label></>}<label><span>反馈意见</span><textarea value={feedbackComment} onChange={event => setFeedbackComment(event.target.value)} maxLength={4000} placeholder={feedbackCapability ? '说明评分差异、关键依据或需要修订的判断……' : '指出整体画像中最有价值、最不准确或需要补强的地方……'} required/></label>{feedbackCapability && <div className="portfolio-calibration-note"><Sparkles size={14}/><span><b>评分校准样本</b><small>模型原分、专家分与差值一并保存；通过回放或专家裁决验证后，才用于后续 S5 评分校准。</small></span></div>}{feedbackError && <p className="form-error"><CircleAlert size={14}/>{feedbackError}</p>}<footer><small>{feedbackCapability ? '权重仍按 30/30/20/10/10 计算并定向路由到 S5' : '保存后自动提炼、去重并路由到相关 Agent'}</small><button type="submit" className="primary" disabled={feedbackSaving}>{feedbackSaving ? '保存中…' : feedbackCapability ? '提交评分反馈' : '提交反馈'}<Send size={14}/></button></footer></form></div>}
    {capabilityVersionGroups.map(group => <section className={`capability-version-group${group.hasVersionChain ? ' has-version-chain' : ''}`} key={group.key}>{group.hasVersionChain && <header className="capability-version-group-header"><div><GitCompare size={14}/><b>{group.name}</b></div><span>{group.rows.length > 1 ? `正式版本 + ${group.rows.length - 1} 个深研版本` : '深研版本'}</span></header>}{group.rows.map(item => renderCapabilityCard(item))}</section>)}
    {visibleReferenceWeapons.length > 0 && <section className="capability-reference-library"><header><div><b>参考武器</b><small>仅展示具备明确装备名称或形态、但未进入本轮 S6 详细画像的候选；深度研究锁定单个装备，在当前 Query 下对话式发散，不重新执行完整 S1–S6</small></div><em>{visibleReferenceWeapons.length} 条</em></header>{referenceResearchError && <p className="reference-research-error"><CircleAlert size={13}/>{referenceResearchError}</p>}<div className="capability-reference-grid">{visibleReferenceWeapons.map((candidate, index) => { const weaponName = weaponCandidateTitle(candidate); const equipmentForm = weaponCandidateForm(candidate); const overview = swarmCandidateOverview(candidate); const researchKey = referenceResearchKey(candidate); const job = referenceResearchJobFor(candidate); const busy = Boolean(referenceResearchBusy[researchKey]); const jobStatus = String(job?.status || '').toLowerCase(); const merged = Boolean(job?.merged || String(job?.merge_status || '').toLowerCase() === 'merged_pending_verification'); return <article className={`capability-reference-card${merged ? ' deep-research-started' : ''}`} key={candidate.hypothesis_id || `${weaponName}-${index}`}><header><span className="capability-reference-badge">参考</span><span><b>{weaponName || equipmentForm}</b>{equipmentForm && equipmentForm !== weaponName && <small>{equipmentForm}</small>}</span></header><p>{overview || '暂无参考概述。'}</p><footer className="capability-reference-actions"><span className="reference-research-status">{busy ? <><RefreshCw size={12} className="spin"/>打开中…</> : merged ? <><CheckCircle2 size={12}/>已固定到能力画像页</> : jobStatus === 'failed_to_queue' || jobStatus === 'failed' ? <><CircleAlert size={12}/>排队失败，可重试</> : job ? <><Clock3 size={12}/>研究任务：{statusLabel(jobStatus)}</> : '创新候选 · 可继续深挖'}</span><div><button type="button" className="reference-research-button" disabled={busy || merged || !encodedRunId} onClick={() => void startReferenceResearch(candidate)}>{busy ? '打开中…' : merged ? '已固定到能力画像页' : '定向深研 / 追问'}<BrainCircuit size={13}/></button></div></footer></article>; })}</div></section>}
  </section>;
}
const FAVORITE_MODULE_LABELS = {
  overview: '概述',
  technology_implementation: '装备与技术实现',
  operational_process: '关键作战流程',
  capability_effects: '形成能力与作战效果',
  winning_logic: '制胜逻辑机理',
};
function FavoritePortrait({row}) {
  const [readingModule, setReadingModule] = useState(null);
  const modules = row?.capability_portrait_modules && typeof row.capability_portrait_modules === 'object'
    ? row.capability_portrait_modules
    : {};
  let entries = FAVORITE_MODULE_KEYS
    .map(key => ({key, label: FAVORITE_MODULE_LABELS[key], text: String(modules[key] || '').trim()}))
    .filter(item => item.text);
  if (entries.length < FAVORITE_MODULE_KEYS.length) {
    const parsed = parseCapabilityPortrait(completeCapabilityText(row?.deep_capability_portrait || row?.capability_image));
    const parsedByLabel = new Map([['概述', parsed.overview], ...parsed.points.map(item => [item.label, item.text])]);
    entries = FAVORITE_MODULE_KEYS.map(key => ({
      key,
      label: FAVORITE_MODULE_LABELS[key],
      text: String(modules[key] || parsedByLabel.get(FAVORITE_MODULE_LABELS[key]) || (key === 'winning_logic' ? parsedByLabel.get('制胜逻辑') || parsedByLabel.get('制胜逻辑机理') : '') || '').trim(),
    })).filter(item => item.text);
  }
  const showModule = index => setReadingModule({...entries[index], index});
  useEffect(() => {
    if (!readingModule) return undefined;
    const handleReaderKey = event => {
      if (event.key === 'Escape') setReadingModule(null);
      if (event.key === 'ArrowLeft' && readingModule.index > 0) showModule(readingModule.index - 1);
      if (event.key === 'ArrowRight' && readingModule.index < entries.length - 1) showModule(readingModule.index + 1);
    };
    window.addEventListener('keydown', handleReaderKey);
    return () => window.removeEventListener('keydown', handleReaderKey);
  }, [readingModule?.index]);
  if (!entries.length) return <div className="favorite-empty-portrait">该收藏未保存可展示的画像正文。</div>;
  return <section className="favorite-portrait" aria-label="五模块能力画像"><div className="favorite-portrait-grid">{entries.map((item, index) => <button type="button" key={item.key} className={`favorite-module favorite-module-${item.key}`} onClick={() => showModule(index)} aria-haspopup="dialog"><span><b>{item.label}</b><small>{item.text}</small></span><ChevronRight size={16}/></button>)}</div>{readingModule && <div className="favorite-reader-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setReadingModule(null); }}><button type="button" className="favorite-reader-nav previous" disabled={readingModule.index === 0} onClick={() => showModule(readingModule.index - 1)} aria-label="查看上一栏"><ChevronLeft size={22}/><span>上一栏</span></button><article className="favorite-reader" role="dialog" aria-modal="true" aria-labelledby="favorite-reader-title"><header><div><span>{String(readingModule.index + 1).padStart(2, '0')} / {String(entries.length).padStart(2, '0')}</span><h3 id="favorite-reader-title">{readingModule.label}</h3></div><button type="button" onClick={() => setReadingModule(null)} aria-label="关闭阅读窗口"><X size={18}/></button></header><div className="favorite-reader-body"><p>{readingModule.text}</p></div></article><button type="button" className="favorite-reader-nav next" disabled={readingModule.index === entries.length - 1} onClick={() => showModule(readingModule.index + 1)} aria-label="查看下一栏"><ChevronRight size={22}/><span>下一栏</span></button></div>}</section>;
}
function FavoriteDimensions({classification}) {
  const dimensions = normalizeWeaponDimensions(classification);
  const values = [dimensions.primary, ...dimensions.secondary].filter(Boolean);
  if (!values.length) return null;
  return <div className="favorite-dimensions" aria-label="武器维度"><b>维度</b>{values.map((value, index) => <span className={index === 0 ? 'primary' : ''} key={`${value}-${index}`}>{weaponDimensionLabel(value)}</span>)}</div>;
}
function favoriteDisplayRow(item) {
  const snapshot = favoriteSnapshot(item);
  return {
    ...(snapshot && typeof snapshot === 'object' ? snapshot : {}),
    favorite_id: item?.favorite_id || item?.id || snapshot.favorite_id || '',
    scope: item?.scope || snapshot.scope || FAVORITE_SCOPE_GLOBAL,
    owner_id: item?.owner_id || snapshot.owner_id || '',
    card_key: item?.card_key || snapshot.card_key || favoriteCardKey(snapshot),
    run_id: item?.run_id || item?.source_run_id || snapshot.run_id || '',
    display_name: item?.display_name ?? snapshot.display_name ?? '',
    note: item?.note ?? snapshot.note ?? '',
    tags: Array.isArray(item?.tags) ? item.tags : Array.isArray(snapshot.tags) ? snapshot.tags : [],
    source_topic: item?.source_topic || snapshot.source_topic || '',
    source_status: item?.source_status || snapshot.source_status || '',
    source_deleted: favoriteBoolean(item?.source_deleted ?? snapshot.source_deleted),
    created_at: item?.created_at || snapshot.created_at || '',
    updated_at: item?.updated_at || snapshot.updated_at || '',
  };
}
const favoriteRowId = item => String(item?.favorite_id || item?.id || item?.card_key || `${item?.run_id || ''}-${item?.name || ''}`);
function FavoritesPage({scope = FAVORITE_SCOPE_GLOBAL, runs = [], favoriteItems = [], navigate, onFavoriteToggle, onFavoriteUpdate, onRefresh}) {
  const [rows, setRows] = useState(() => favoriteItems.map(favoriteDisplayRow));
  const [query, setQuery] = useState('');
  const [capabilityType, setCapabilityType] = useState('all');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(favoriteItems.length);
  const [loading, setLoading] = useState(scope === FAVORITE_SCOPE_GLOBAL);
  const [error, setError] = useState('');
  const [busyIds, setBusyIds] = useState(() => new Set());
  const [loadedSourceRuns, setLoadedSourceRuns] = useState({});
  const [favoriteMeta, setFavoriteMeta] = useState(() => readFavoriteMeta());
  const [editingId, setEditingId] = useState('');
  const [editDraft, setEditDraft] = useState({displayName: '', note: '', tags: ''});
  const [savingEditId, setSavingEditId] = useState('');
  const [editError, setEditError] = useState('');
  const loadSequenceRef = useRef(0);
  const pageSize = FAVORITE_PAGE_SIZE;
  const loadPage = async (targetPage = 1) => {
    const sequence = ++loadSequenceRef.current;
    if (scope !== FAVORITE_SCOPE_GLOBAL) {
      setRows([]); setTotal(0); setLoading(false); setError('');
      return;
    }
    setLoading(true); setError('');
    const params = new URLSearchParams({scope: FAVORITE_SCOPE_GLOBAL, limit: String(pageSize), offset: String((targetPage - 1) * pageSize)});
    if (query.trim()) params.set('search', query.trim());
    if (capabilityType !== 'all') params.set('capability_type', capabilityType);
    const result = await requestResult(`/favorites?${params.toString()}`, {headers: {'X-Role': 'analyst'}});
    if (sequence !== loadSequenceRef.current) return;
    if (!result.ok) {
      setError(result.detail || '收藏加载失败，请重试。');
      setLoading(false);
      return;
    }
    const items = favoriteRowsFromPayload(result.data);
    setRows(items.map(favoriteDisplayRow));
    setTotal(Number(result.data?.total ?? items.length));
    setPage(targetPage);
    setLoading(false);
    if (targetPage === 1 && typeof onRefresh === 'function') void onRefresh();
  };
  useEffect(() => { setPage(1); void loadPage(1); }, [scope, query, capabilityType]);
  const maxPage = Math.max(1, Math.ceil(total / pageSize));
  const runById = useMemo(() => new Map([...runs, ...Object.values(loadedSourceRuns)].map(run => [String(run.run_id), run])), [runs, loadedSourceRuns]);
  const changeScope = nextScope => {
    if (nextScope === FAVORITE_SCOPE_PRIVATE) {
      navigate('favorites', {scope: FAVORITE_SCOPE_PRIVATE});
      return;
    }
    navigate('favorites', {scope: FAVORITE_SCOPE_GLOBAL});
  };
  const startEdit = item => {
    const itemId = favoriteRowId(item);
    setEditError('');
    setEditingId(itemId);
    setEditDraft({
      // The server owns editable favorite metadata.  Do not fall back to the
      // legacy browser-local cache here: an intentionally cleared field must
      // stay cleared after a reload.
      displayName: String(item.display_name || item.name || item.title || '').slice(0, 400),
      note: String(item.note ?? '').slice(0, 4000),
      tags: Array.isArray(item.tags) ? item.tags.join(', ') : '',
    });
  };
  const cancelEdit = () => {
    setEditError('');
    setEditingId('');
    setEditDraft({displayName: '', note: '', tags: ''});
  };
  const saveEdit = async (event, item) => {
    event.preventDefault();
    const itemId = favoriteRowId(item);
    if (!itemId || savingEditId) return;
    const displayName = String(editDraft.displayName || '').trim().slice(0, 400);
    const note = String(editDraft.note || '').trim().slice(0, 4000);
    const tags = [...new Set(String(editDraft.tags || '').split(/[,，]/).map(value => value.trim()).filter(Boolean))].slice(0, 20);
    setSavingEditId(itemId);
    setEditError('');
    const result = typeof onFavoriteUpdate === 'function'
      ? await onFavoriteUpdate(item, {display_name: displayName, note, tags})
      : await requestResult(`/favorites/${encodeURIComponent(itemId)}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'},
        body: JSON.stringify({display_name: displayName, note, tags}),
      });
    setSavingEditId('');
    if (!result?.ok) {
      setEditError(result?.status === 403 ? '当前身份没有编辑该公共收藏的权限。' : result?.detail || '收藏信息保存失败，请重试。');
      return;
    }
    const saved = result.favorite || result.data?.favorite || result.data || {};
    const updated = favoriteDisplayRow({...item, ...saved, snapshot: saved.snapshot || item.snapshot || favoriteSnapshot(item)});
    setRows(current => current.map(row => favoriteRowId(row) === itemId ? updated : row));
    // Metadata used to be browser-local in an early UI build.  Prefer the
    // server-owned fields now and remove the stale fallback so a reload cannot
    // overwrite the saved presentation values.
    const nextMeta = {...favoriteMeta};
    delete nextMeta[itemId];
    setFavoriteMeta(nextMeta);
    writeFavoriteMeta(nextMeta);
    cancelEdit();
    notify('收藏卡片信息已更新', 'ok');
  };
  const remove = async item => {
    const itemId = favoriteRowId(item);
    if (busyIds.has(itemId)) return;
    setBusyIds(current => new Set([...current, itemId]));
    setRows(current => current.filter(row => row !== item));
    const result = await onFavoriteToggle?.(item, item.run_id, false);
    if (!result?.ok) {
      await loadPage(page);
    } else {
      // Keep the optimistic list and its surrounding pagination metadata in
      // sync.  When the deleted card was the only item on the last page,
      // reload the now-valid previous page instead of leaving an empty page
      // with a stale total.
      const nextTotal = Math.max(0, total - 1);
      const nextPage = Math.min(page, Math.max(1, Math.ceil(nextTotal / pageSize)));
      setTotal(nextTotal);
      // Refill only when a later row should move onto this page or when the
      // deletion invalidated the current last-page number.  The normal final
      // page stays fully optimistic and avoids an unnecessary round trip.
      if (nextPage !== page || total > page * pageSize) {
        await loadPage(nextPage);
      }
      const nextMeta = {...favoriteMeta};
      delete nextMeta[itemId];
      setFavoriteMeta(nextMeta);
      writeFavoriteMeta(nextMeta);
    }
    setBusyIds(current => { const next = new Set(current); next.delete(itemId); return next; });
  };
  const open = async item => {
    const runId = String(item.run_id || '').trim();
    const sourceUnavailable = item.source_deleted || /deleted|删除|unavailable|不可读/i.test(String(item.source_status || ''));
    if (!runId || sourceUnavailable) return;
    let run = runById.get(runId);
    if (!run) {
      run = await request(runApiPath(runId), null, {headers: {'X-Role': 'analyst'}});
      if (!run?.run_id) return;
      setLoadedSourceRuns(current => ({...current, [runId]: run}));
    }
    navigate('capabilities', {run, cap: item.card_key || favoriteCardKey(item)});
  };
  const sourceLabel = item => {
    if (item.source_deleted || /deleted|删除/i.test(String(item.source_status || ''))) return '原任务已删除';
    const run = runById.get(String(item.run_id || ''));
    if (run?.status === 'archived' || /archiv|归档/i.test(String(item.source_status || ''))) return '来源任务已归档';
    return item.source_topic || run?.topic || item.run_id || '来源任务未知';
  };
  return <section className="favorites-page">
    <PageTitle eyebrow="能力资产" title="收藏" subtitle="保存完整能力画像快照，来源任务归档或删除后仍可独立审阅。"><button type="button" onClick={() => void loadPage(page)} disabled={loading}><RefreshCw size={14} className={loading ? 'spin' : ''}/>刷新</button></PageTitle>
    <section className="favorites-shell">
      <header className="favorites-header"><div><span className="favorites-eyebrow"><Star size={16}/>能力画像收藏</span><h2>{scope === FAVORITE_SCOPE_PRIVATE ? '个人收藏' : '公共收藏'}</h2><p>{scope === FAVORITE_SCOPE_PRIVATE ? '个人收藏将随账户登录启用，当前不会读取或写入匿名数据。' : `${total} 张完整能力画像快照`}</p></div><div className="favorites-scope-tabs" role="tablist" aria-label="收藏范围"><button type="button" role="tab" aria-selected={scope === FAVORITE_SCOPE_GLOBAL} className={scope === FAVORITE_SCOPE_GLOBAL ? 'active' : ''} onClick={() => changeScope(FAVORITE_SCOPE_GLOBAL)}>公共收藏</button><button type="button" role="tab" aria-selected={scope === FAVORITE_SCOPE_PRIVATE} className={scope === FAVORITE_SCOPE_PRIVATE ? 'active' : ''} onClick={() => changeScope(FAVORITE_SCOPE_PRIVATE)}>个人收藏</button></div></header>
      {scope === FAVORITE_SCOPE_PRIVATE ? <div className="favorites-login-placeholder"><Star size={26}/><h3>登录后使用个人收藏</h3><p>当前版本只开放公共收藏；接入账户体系后，个人收藏会按账户隔离。</p></div> : <>
        <div className="favorites-filters"><label className="searchbox"><Search size={15}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索收藏名称" aria-label="搜索收藏名称"/></label><select value={capabilityType} onChange={event => setCapabilityType(event.target.value)} aria-label="按能力类型筛选"><option value="all">全部能力类型</option><option value="new_capability">新能力</option><option value="upgrade">能力升级</option></select></div>
        {error && <div className="favorites-error"><CircleAlert size={16}/><span>{error}</span><button type="button" onClick={() => void loadPage(page)}>重试</button></div>}
        {loading && !rows.length ? <div className="favorites-loading"><RefreshCw size={20} className="spin"/>正在加载收藏…</div> : !rows.length ? <Empty text={query || capabilityType !== 'all' ? '没有匹配的收藏' : '还没有收藏完整能力画像'}><button type="button" onClick={() => navigate('capabilities')}>去能力图像页看看</button></Empty> : <div className="favorites-list">{rows.map(item => { const run = runById.get(String(item.run_id || '')); const sourceUnavailable = item.source_deleted || /deleted|删除|unavailable|不可读/i.test(String(item.source_status || '')); const itemId = favoriteRowId(item); const displayName = String(item.display_name || item.name || item.title || '未命名能力画像'); const note = String(item.note ?? ''); const tags = Array.isArray(item.tags) ? item.tags : []; return <article className={`favorite-card${sourceUnavailable ? ' source-unavailable' : ''}`} key={itemId}><header><div><div className="favorite-card-title"><span className="favorite-badge"><Star size={13} fill="currentColor"/>已收藏</span><h3>{displayName}</h3></div><div className="favorite-card-meta">{(item.equipment_form || item.equipment_category) && <span>{item.equipment_form || item.equipment_category}</span>}<span>{item.capability_type === 'upgrade' ? '能力升级' : '新能力'}</span>{tags.map(tag => <span key={`${itemId}-tag-${tag}`}>#{tag}</span>)}</div></div><div className="favorite-card-actions"><button type="button" className="favorite-open" disabled={sourceUnavailable} onClick={() => void open(item)} title={sourceUnavailable ? '来源不可读，仅保留快照' : !run ? '将按需读取来源任务' : '返回原能力卡并定位'}><Eye size={14}/>{sourceUnavailable ? '仅查看快照' : '查看原卡'}</button><button type="button" className="favorite-edit" onClick={() => startEdit(item)} aria-expanded={editingId === itemId} title="编辑收藏显示信息"><Pencil size={14}/>编辑</button><button type="button" className="favorite-remove" disabled={busyIds.has(itemId)} onClick={() => void remove(item)}><Trash2 size={14}/>取消收藏</button></div></header>{editingId === itemId && <form className="favorite-edit-form" onSubmit={event => void saveEdit(event, item)}><label><span>显示名称</span><input value={editDraft.displayName} maxLength={400} onChange={event => setEditDraft(current => ({...current, displayName: event.target.value}))} placeholder={item.name || '未命名能力画像'}/></label><label><span>备注</span><textarea value={editDraft.note} maxLength={4000} onChange={event => setEditDraft(current => ({...current, note: event.target.value}))} placeholder="记录复核结论、使用场景或后续动作"/></label><label><span>标签</span><input value={editDraft.tags} maxLength={1200} onChange={event => setEditDraft(current => ({...current, tags: event.target.value}))} placeholder="用逗号分隔，例如：重点、待复核"/><small>保存到服务器；原始五模块能力快照保持不变。</small></label>{editError && <p className="form-error"><CircleAlert size={14}/>{editError}</p>}<div><button type="button" onClick={cancelEdit} disabled={savingEditId === itemId}>取消</button><button type="submit" className="primary" disabled={savingEditId === itemId}><Save size={13}/>{savingEditId === itemId ? '保存中…' : '保存'}</button></div></form>}{note && <div className="favorite-note"><span><Pencil size={12}/>备注</span><p>{note}</p></div>}<FavoriteDimensions classification={item.capability_classification}/><FavoritePortrait row={item}/><div className="favorite-card-source"><span>{sourceLabel(item)}</span><time dateTime={item.created_at || undefined}>收藏时间：{item.created_at ? new Date(item.created_at).toLocaleString('zh-CN', {hour12:false}) : '—'}</time></div></article>; })}</div>}
        {maxPage > 1 && <footer className="favorites-pager"><span>第 {page} / {maxPage} 页 · 共 {total} 条</span><button type="button" disabled={page <= 1 || loading} onClick={() => void loadPage(page - 1)}><ChevronLeft size={14}/>上一页</button><button type="button" disabled={page >= maxPage || loading} onClick={() => void loadPage(page + 1)}>下一页<ChevronRight size={14}/></button></footer>}
      </>}
    </section>
  </section>;
}
const CAPABILITY_NAMED_EQUIPMENT_RE = /[“"「『]([^”"」』\n]{2,80}(?:巡飞弹|导弹|弹药|无人机|无人艇|无人车|无人潜航器|鱼雷|火箭弹|炸弹|武器系统|效应器|平台))[”"」』]/g;
function capabilityEquipmentDirection(row = {}) {
  const explicit = row.equipment_direction || row.equipmentDirection || row.equipment_direction_name || row.innovation_variant_name;
  if (String(explicit || '').trim()) {
    const value = String(explicit).trim();
    return value.endsWith('型') ? `${value}装备` : value;
  }
  const name = String(row.name || '').trim();
  if (!/(?:型|方向|类别|路线|构型)$/.test(name)) return '';
  return name.endsWith('型') ? `${name}装备` : name;
}
function capabilityEquipmentName(row = {}) {
  const direction = capabilityEquipmentDirection(row);
  const explicit = row.equipment_name || row.equipmentName || row.weapon_name || row.primary_equipment_name;
  if (String(explicit || '').trim() && String(explicit).trim() !== direction) return String(explicit).trim();
  const name = String(row.name || row.title || row.capability_name || '').trim();
  if (name && name !== direction && !/(?:型|方向|类别|路线|构型)$/.test(name)) return name;
  const modules = row.capability_portrait_modules && typeof row.capability_portrait_modules === 'object'
    ? Object.values(row.capability_portrait_modules)
    : [];
  const portrait = [row.deep_capability_portrait, row.capability_image, ...modules]
    .map(value => String(value || '').trim())
    .filter(Boolean)
    .join(' ');
  CAPABILITY_NAMED_EQUIPMENT_RE.lastIndex = 0;
  const match = CAPABILITY_NAMED_EQUIPMENT_RE.exec(portrait);
  return String(match?.[1] || '').trim() || name || direction;
}
function capabilityDisplayEquipmentForm(row = {}) { const name = String(row.name || ''); const form = String(row.equipment_form || row.equipment_category || ''); const kind = value => /无人机|无人平台|无人艇|无人车|无人潜航/.test(value) ? 'platform' : /拦截弹|巡飞|导弹|弹药|鱼雷|水雷/.test(value) ? 'munition' : /激光武器|高功率微波|定向能/.test(value) ? 'directed-energy' : ''; return kind(name) && kind(form) && kind(name) !== kind(form) ? String(row.primary_equipment_identity || row.name) : form; }
function completeCapabilityText(value) {
  let text = String(value || '');
  const placeholder = /(^|[；;，,\n])\s*(?:string|array|object|null|number|boolean)\s*(?=($|[；;，,。\n]))/gi;
  let previous = '';
  while (previous !== text) { previous = text; text = text.replace(placeholder, '$1'); }
  return text.replace(/；；+/g, '；').replace(/;;+/g, ';').replace(/[；;]。/g, '。').trim();
}
function recallStatusLabel(value) { return {pending:'等待路由',routed:'执行中',completed:'已完成',limited:'受限未执行'}[value] || value || '未知'; }
function completedRecallClosure(recalls = [], workflow = {}) {
  if (!recalls.length || recalls.some(item => item.status !== 'completed')) return false;
  const phaseStatus = new Map((workflow.phases || []).map(item => [item.id, item.status]));
  return workflow.status === 'completed'
    && ['s_agents', 'audit', 'report'].every(phase => phaseStatus.get(phase) === 'completed');
}
function effectiveStageGatePassed(stage, recalls, workflow) {
  return Boolean(stage.gate_passed || completedRecallClosure(recalls, workflow));
}
function stageGateLabel(stage, recalls, workflow) {
  const related = (recalls || []).filter(item => item.source_layer === stage.layer);
  const statuses = new Set(related.map(item => item.status));
  if (effectiveStageGatePassed(stage, recalls, workflow)) return completedRecallClosure(recalls, workflow) ? '补证后通过' : statuses.has('completed') ? '再调后通过' : '门控通过';
  if (statuses.has('routed')) return '再调执行中';
  if (statuses.has('pending')) return '等待再调';
  if (statuses.has('completed')) return '补证完成·待闭环';
  if (statuses.has('limited')) return '再调受限';
  return '门控未通过';
}
function WinningSwarmPanel({swarm}) {
  const tasks = swarm.task_graph || []; const finalists = swarm.finalists || []; const hypotheses = swarm.hypotheses || []; const rejections = swarm.rejections || []; const budget = swarm.budget || {}; const waves = swarm.waves || []; const core = swarm.core_schedule || {}; const coreWaves = core.logical_waves || []; const finalMerge = swarm.final_merge || {};
  return <section className="winning-swarm-panel"><div className="section-heading"><div><b>制胜机理弹性 Agent 群</b><span>三波开放探索；S1–S6 按依赖动态调度，原始会话隔离，只有绑定候选与目标节点且通过门控的贡献进入共享账本。</span></div><em>{finalists.length} 条最终候选</em></div><div className="swarm-metrics"><div><small>动态实例</small><b>{budget.completed_instances ?? tasks.length} / {budget.maximum_instances || 12}</b></div><div><small>专用波次</small><b>{waves.length} / {budget.maximum_waves || 3}</b></div><div><small>S Agent</small><b>{core.completed_steps?.length || 0} / {core.active_steps?.length || 0}</b></div><div><small>最终合并</small><b>{finalMerge.passed ? '门控通过' : swarm.stop_reason || '运行中'}</b></div></div><div className="swarm-wave-grid">{waves.map(item => <article key={item.wave}><i>W{item.wave}</i><div><b>{item.wave === 1 ? '问题发散' : item.wave === 2 ? '开放创作' : '组合决策'}</b><small>{item.task_ids?.length || 0} 个专用 Agent</small></div></article>)}</div>{coreWaves.length > 0 && <div className="core-schedule"><header><b>S1–S6 动态 DAG</b><small>{core.merge_strategy || '依赖满足后并行、拓扑顺序合并'}</small></header><div className="core-wave-grid">{coreWaves.map(item => <article key={item.wave}><i>C{item.wave}</i><div><b>{item.core_agents?.join(' + ')}</b><small>{item.parallel ? '无写入冲突，并行执行' : '依赖满足后执行'}</small></div></article>)}</div></div>}{finalists.length > 0 && <div className="swarm-finalists">{finalists.map((item, index) => <article key={item.hypothesis_id}><header><i>{index + 1}</i><div><b>{item.title}</b><small>{item.equipment_forms?.join(' · ') || '装备形态待验证'}</small></div><em>{Math.round((item.score || 0) * 100)}%</em></header><p>{item.novelty_delta || item.changed_confrontation_variable}</p><div><span>证据 {item.evidence_ids?.length || 0}</span><span>残差 {item.residuals?.length || 0}</span><span>{item.status || 'finalist'}</span></div>{item.failure_boundaries?.length > 0 && <small>失效边界：{item.failure_boundaries.slice(0, 2).join('；')}</small>}</article>)}</div>}{rejections.length > 0 && <details className="swarm-rejections"><summary>查看 {rejections.length} 条淘汰记录</summary>{rejections.slice(0, 8).map((item, index) => <p key={`${item.hypothesis_id}-${index}`}><b>{item.hypothesis_id}</b><span>{(item.reasons || []).join('；') || item.stage}</span></p>)}</details>}</section>;
}
function WinningMechanismView({data}) {
  const input = data.inputs?.at(-1); const resources = data.resources?.at(-1); const nodes = data.reasoning_nodes || []; const stages = data.stages || []; const recalls = data.recalls || []; const stepPlan = data.workflow?.step_plan || []; const swarm = data.swarm || {};
  if (!input) return <Empty text="本次运行尚未形成 S1–S6 Agent 输入包"/>;
  const nodeByStep = new Map(nodes.map(node => [Number(node.step), node]));
  const planByStep = new Map(stepPlan.map(item => [Number(item.step), item]));
  const dynamicProfile = data.workflow?.execution?.profile_id === 'winning_swarm_dynamic_v2';
  return <div className="winning-view s-agent-results-view">
    <section className="winning-input"><div><span>S1–S6 Agent 输入包</span><h2>{input.problem_frame?.objective}</h2><p>{input.problem_frame?.route_frame}</p></div><dl><dt>研究路线</dt><dd>{routeLabel(input.research_route)}</dd><dt>输入 Packet</dt><dd>{input.packet_ids?.length || 0}</dd><dt>证据索引</dt><dd>{input.evidence_index?.length || 0}</dd><dt>当前轮次</dt><dd>{input.round_budget?.current_round} / {input.round_budget?.maximum_rounds}</dd></dl></section>
    {swarm.policy?.enabled && <WinningSwarmPanel swarm={swarm}/>}
    <section className="winning-resource-section"><div className="section-heading"><div><b>共享受控资源</b><span>各 Agent 读取投影后的理论、案例、前沿证据与问题链，不共享其他 Agent 原始会话。</span></div></div><div className="winning-resources"><ResourceBlock title="理论工具库" rows={resources?.theory_tools} label="name"/><ResourceBlock title="战例库" rows={resources?.case_resources} label="evidence_id"/><ResourceBlock title="前沿情报库" rows={resources?.frontier_resources} label="evidence_id"/><ResourceBlock title="问题链" rows={resources?.question_chain} label="question"/></div></section>
    <section className="s-agent-result-section"><div className="section-heading"><div><b>六个专用 Agent 结果</b><span>按 Agent 展示“认识—证据—置信度—下一步建议”；卡片顺序仅用于编号，不代表固定串联。</span></div><small>{nodes.length} 个结果节点</small></div><div className="s-agent-result-grid">{S_AGENT_ARCHITECTURE.map(meta => {
      const plan = planByStep.get(meta.step) || {}; const skipped = (plan.execution_mode === 'skip' || plan.status === 'skipped') && (!dynamicProfile || plan.decision_finalized === true); const node = skipped ? null : nodeByStep.get(meta.step); const relatedRecalls = recalls.filter(item => recallMatchesStep(item, meta.step, meta.agent_id)); const question = resources?.question_chain?.[meta.step - 1]; const nextSuggestion = formatNextAction(node?.next_action) || node?.next_step_suggestion || node?.next_step || relatedRecalls.at(-1)?.reason || question?.question || '未记录显式下一步建议；以循环门控和开放问题为准。';
      return <article className={`s-agent-result-card ${node ? 'completed' : skipped ? 'skipped' : 'pending'}`} key={meta.step}><header><i>S{meta.step}</i><div><b>{meta.name}</b><small>{meta.task}</small></div><span>{node ? `已形成 · 回溯 ${plan.backtrack_count ?? relatedRecalls.length}` : skipped ? `${stepModeLabel(plan.execution_mode)} · 蓝图跳过` : '待执行'}</span></header>{node ? <><h3>{agentFacingText(node.title)}</h3><div className="s-agent-result-quad"><section className="recognition"><small>认识</small><p>{agentFacingText(node.summary)}</p></section><section><small>证据</small><p>{node.evidence_ids?.length ? node.evidence_ids.slice(0, 4).join(' · ') : '暂无可展示证据编号'}</p></section><section><small>置信度</small><b>{Math.round((node.confidence || 0) * 100)}%</b></section><section className="next"><small>下一步建议</small><p>{agentFacingText(nextSuggestion)}</p></section></div><details><summary>输入、假设与追溯</summary><div><Detail label="输入引用" value={agentFacingText((node.input_refs || []).join(' · ') || '—')}/><Detail label="关键假设" value={agentFacingText((node.assumptions || []).join('；') || '—')}/></div></details></> : <p className="s-agent-result-empty">{skipped ? `当前 ${data.workflow?.discovery?.primary_branch || 'A–H'} 分支按业务路径跳过该 Agent，不生成虚假结果。` : '该 Agent 尚未形成结果节点。'}</p>}<footer><span>{meta.skills.slice(0, 2).join(' · ')}</span><code>{meta.harness}</code></footer></article>;
    })}</div></section>
    {stages.length > 0 && <section className="s-agent-loop-results"><div className="section-heading"><div><b>循环门控结果</b><span>L1 内循环、L2 中循环与 L3 外循环检查六个 Agent 结果的证据、连续性和跨场景覆盖。</span></div></div><div>{stages.map(stage => { const passed = effectiveStageGatePassed(stage, recalls, data.workflow); return <article key={stage.stage_id} className={passed ? 'passed' : 'limited'}><header><i>{stage.layer}</i><div><b>{stage.title}</b><small>置信度 {Math.round((stage.confidence || 0) * 100)}% · 证据 {stage.evidence_ids?.length || 0}</small></div><em>{stageGateLabel(stage, recalls, data.workflow)}</em></header>{passed && !stage.gate_passed ? <p className="gate-reconciled"><CheckCircle2 size={13}/>定向补证、覆盖重算及后续交付已形成完整闭环，历史门控残差不再阻止本层通过。</p> : stage.gate_reasons?.length > 0 && <p>{stage.gate_reasons.join('；')}</p>}<details><summary>{passed && !stage.gate_passed ? '查看历史门控与本层输出' : '查看本层输出'}</summary><div>{passed && !stage.gate_passed && <Detail label="历史门控残差" value={stage.gate_reasons?.join('；') || '—'}/>} {Object.entries(stage.outputs || {}).filter(([key]) => key !== 'reasoning_refs').map(([key, value]) => <Detail key={key} label={fieldLabel(key)} value={formatValue(value)}/>)}</div></details></article>; })}</div></section>}
    {recalls.length > 0 && <section className="winning-recalls s-agent-recalls"><div className="section-heading"><div><b>定向回溯与再调</b><span>按 S Agent、能力标签或返回节点补充，不把整个流程无差别重跑。</span></div></div>{recalls.map(item => <article key={item.recall_id}><b>{item.source_layer} → {normalizeStepRef(item.return_node)}</b><span>{agentModelLabel(item.target_agent_id || item.target_capability_tag)}</span><p>{item.reason}</p><small>{recallStatusLabel(item.status)}</small></article>)}</section>}
  </div>;
}
function ResourceBlock({title, rows = [], label}) { return <article><b>{title}</b><span>{rows.length} 项</span><ul>{rows.slice(0, 5).map((row, index) => <li key={`${title}-${index}`}>{row[label] || formatValue(row)}</li>)}</ul></article>; }
function markdownTableCells(line) {
  const text = String(line || '').trim().replace(/^\|/, '').replace(/\|$/, '');
  const cells = []; let cell = ''; let escaped = false;
  for (const character of text) {
    if (character === '|' && !escaped) { cells.push(cell.trim()); cell = ''; continue; }
    cell += character;
    escaped = character === '\\' && !escaped;
    if (character !== '\\') escaped = false;
  }
  cells.push(cell.trim());
  return cells;
}
function isMarkdownTableDivider(line) {
  const cells = markdownTableCells(line);
  return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
}
function summarizeBaselineGapTable(content) {
  const lines = String(content || '').split('\n');
  const result = []; let inTargetSection = false; let converted = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading) {
      const title = heading[2].replace(/[*_`]/g, '').trim();
      inTargetSection = /^现役(?:任务链)?基线与五档差距(?:如下)?$/.test(title);
      result.push(inTargetSection ? `${heading[1]} 现役基线与五档差距综述` : line);
      continue;
    }
    if (inTargetSection && !converted && line.includes('|') && isMarkdownTableDivider(lines[index + 1])) {
      const headers = markdownTableCells(line);
      const rows = []; index += 2;
      while (index < lines.length && lines[index].includes('|') && !/^\s*$/.test(lines[index])) {
        rows.push(markdownTableCells(lines[index]));
        index += 1;
      }
      const overview = rows.map((row, rowIndex) => {
        const title = (row[0] || `第 ${rowIndex + 1} 档`).replace(/\*\*|__/g, '').trim();
        const details = headers.slice(1).map((header, cellIndex) => {
          const value = row[cellIndex + 1]?.replace(/\*\*|__/g, '').trim();
          return value ? `${(header || `字段 ${cellIndex + 2}`).replace(/\*\*|__/g, '').trim()}为${value}` : '';
        }).filter(Boolean);
        return `${title}方面，${details.join('；')}。`;
      }).join('');
      result.push('', overview);
      converted = true;
      index -= 1;
      continue;
    }
    result.push(line);
  }
  return result.join('\n');
}
function decodeReportHtmlEntities(value) {
  return String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&amp;/gi, '&');
}
function reportHtmlCellText(value) {
  return decodeReportHtmlEntities(String(value || '')
    .replace(/<br\s*\/?\s*>/gi, '；')
    .replace(/<\/p>\s*<p\b[^>]*>/gi, '；')
    .replace(/<[^>]+>/g, ''))
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\|/g, '\\|');
}
function normalizeReportHtmlTables(value) {
  return String(value || '').replace(/<table\b[^>]*>[\s\S]*?<\/table>/gi, table => {
    const rows = [...table.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map(match => (
      [...match[1].matchAll(/<(th|td)\b[^>]*>([\s\S]*?)<\/\1>/gi)].map(cell => ({
        header: cell[1].toLowerCase() === 'th',
        text: reportHtmlCellText(cell[2]),
      }))
    )).filter(row => row.length);
    if (!rows.length) return table;
    const width = Math.max(...rows.map(row => row.length));
    const normalizedRows = rows.map(row => Array.from({length: width}, (_, index) => row[index]?.text || ''));
    const firstRowIsHeader = rows[0].some(cell => cell.header);
    const header = firstRowIsHeader ? normalizedRows[0] : Array.from({length: width}, (_, index) => `字段 ${index + 1}`);
    const body = firstRowIsHeader ? normalizedRows.slice(1) : normalizedRows;
    return `\n\n| ${header.join(' | ')} |\n| ${header.map(() => '---').join(' | ')} |${body.length ? `\n${body.map(row => `| ${row.join(' | ')} |`).join('\n')}` : ''}\n\n`;
  });
}
function reportHasWeaponEquipmentTable(markdown) {
  return /(^|\n)\s*\|\s*(?:武器装备|装备系统方向|装备方向|具体装备方向)\s*\|/m.test(String(markdown || ''));
}
function reportTableCellText(value, limit = 280) {
  const text = String(value || '').replace(/\s+/g, ' ').replace(/\|/g, '／').trim();
  if (!text) return '—';
  if (text.length <= limit) return text;
  const clipped = text.slice(0, limit);
  const boundary = Math.max(clipped.lastIndexOf('。'), clipped.lastIndexOf('；'), clipped.lastIndexOf('，'));
  return `${boundary > 80 ? clipped.slice(0, boundary + 1) : clipped}…`;
}
function reportCellLooksThinOrTruncated(value, equipmentName = '') {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text || text === '—') return true;
  const name = String(equipmentName || '').trim();
  if (name && (text === name || text.startsWith(`${name}；`) || text.startsWith(`${name};`)) && text.length < name.length + 24) {
    return true;
  }
  if (/[。！？；…]$/.test(text) && text.length >= 28) return false;
  if (/当前同$|同类装$|同类装备$|形成能$|作战概$|待核验$/.test(text)) return true;
  if (!/[。！？；]/.test(text) && text.length < 48) return true;
  if (/[，、：:]$/.test(text)) return true;
  return false;
}
function pickReportTableCell(...candidates) {
  for (const candidate of candidates) {
    const text = String(candidate || '').replace(/\s+/g, ' ').trim();
    if (!text || text === '—') continue;
    return text;
  }
  return '';
}
function capabilityRowToEquipmentTableCells(row = {}) {
  const equipmentName = capabilityEquipmentName(row) || capabilityDisplayEquipmentForm(row) || '—';
  const equipmentDirection = capabilityEquipmentDirection(row);
  const name = [equipmentName, equipmentDirection && `装备方向：${equipmentDirection}`]
    .filter(Boolean)
    .join(' · ');
  const parsed = parseCapabilityPortrait(completeCapabilityText(row.deep_capability_portrait || row.capability_image));
  const point = label => parsed.points.find(item => item.label === label)?.text || '';
  const modules = row.capability_portrait_modules && typeof row.capability_portrait_modules === 'object'
    ? row.capability_portrait_modules
    : {};
  const technologies = Array.isArray(row.enabling_technologies)
    ? row.enabling_technologies.filter(Boolean).join('、')
    : '';
  const techCandidates = [
    point('装备与技术实现'),
    modules.equipment_and_technology,
    modules.key_technologies,
    technologies,
    row.capability_outcome,
    row.winning_mechanism,
    modules.capability_effects,
    row.equipment_form,
    row.equipment_category,
  ];
  const effectCandidates = [
    point('形成能力与作战效果'),
    modules.capability_effects,
    row.mission_effect,
    row.capability_outcome,
    row.military_utility,
    row.capability_gap,
  ];
  const conceptCandidates = [
    point('关键作战流程'),
    modules.operational_process,
    row.operational_mechanism,
    row.strike_countermeasure_value,
    row.source_winning_logic,
    modules.capability_effects,
  ];
  const pickPreferringComplete = (candidates) => {
    const usable = candidates
      .map(item => String(item || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    return pickReportTableCell(
      ...usable.filter(item => !reportCellLooksThinOrTruncated(item, name)),
      ...usable,
    );
  };
  return [
    name,
    pickPreferringComplete(techCandidates),
    pickPreferringComplete(effectCandidates),
    pickPreferringComplete(conceptCandidates),
  ].map(cell => reportTableCellText(cell));
}
function buildWeaponEquipmentMarkdownTable(capabilityRows = []) {
  const rows = (Array.isArray(capabilityRows) ? capabilityRows : [])
    .map(capabilityRowToEquipmentTableCells)
    .filter(cells => cells[0] && cells[0] !== '—');
  if (!rows.length) return '';
  return [
    '| 武器装备 | 核心技术 | 形成能力 | 作战概念与主要效果 |',
    '| --- | --- | --- | --- |',
    ...rows.map(cells => `| ${cells.join(' | ')} |`),
  ].join('\n');
}
function reportLooksLikeProjectArgument(source) {
  return /^##\s*[一二三四五][、.．]?\s*(需求分析|项目画像|总体方案|关键技术|研制基础)\s*$/m.test(String(source || ''));
}
function reportLooksLikeThreeLayer(source) {
  return /^##\s*第[一二三]层/m.test(String(source || '')) || /^###\s*[①-⑨]/m.test(String(source || ''));
}
function resolvedReportTemplateMode(run, markdown = '') {
  const value = String(run?.report_template_mode || '').trim();
  if (value === 'project_argument_v1' || value === 'three_layer_nine_item') return value;
  const source = String(markdown || '');
  const project = reportLooksLikeProjectArgument(source);
  const threeLayer = reportLooksLikeThreeLayer(source);
  if (project && !threeLayer) return 'project_argument_v1';
  if (threeLayer && !project) return 'three_layer_nine_item';
  return '';
}
function ensureReportWeaponEquipmentTable(markdown, capabilityRows = [], templateMode = '') {
  const source = String(markdown || '');
  if (!source.trim() || reportHasWeaponEquipmentTable(source)) return source;
  const table = buildWeaponEquipmentMarkdownTable(capabilityRows);
  if (!table) return source;
  const block = `\n\n${table}\n`;
  const mode = templateMode === 'project_argument_v1' || templateMode === 'three_layer_nine_item'
    ? templateMode
    : resolvedReportTemplateMode(null, source);
  const projectMode = mode === 'project_argument_v1';
  const threeLayerMode = mode === 'three_layer_nine_item';
  if ((projectMode || !threeLayerMode) && /^###\s*（一）装备图像概述\s*$/m.test(source)) {
    return source.replace(/(^###\s*（一）装备图像概述\s*$)/m, `$1${block}`);
  }
  if ((threeLayerMode || !projectMode) && /^###\s*⑦\s*装备能力图像\s*$/m.test(source)) {
    return source.replace(/(^###\s*⑦\s*装备能力图像\s*$)/m, `$1${block}`);
  }
  if (projectMode && /^##\s*二[、.．]?\s*项目画像\s*$/m.test(source)) {
    return source.replace(
      /(^##\s*二[、.．]?\s*项目画像\s*$)/m,
      `$1\n\n### （一）装备图像概述${block}`,
    );
  }
  if (threeLayerMode && (/^##\s*第三层[：:].*能力图像/m.test(source) || /^##\s*第三层/m.test(source))) {
    return source.replace(
      /(^##\s*第三层[^\n]*$)/m,
      `$1\n\n### ⑦ 装备能力图像${block}`,
    );
  }
  if (projectMode) return `${source.trimEnd()}\n\n### （一）装备图像概述${block}`;
  if (threeLayerMode) return `${source.trimEnd()}\n\n### ⑦ 装备能力图像${block}`;
  return source;
}
function normalizeReportMarkdownTables(value) {
  const lines = String(value || '').split('\n');
  const result = [];
  let inTable = false;
  let sawDivider = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed.startsWith('|')) {
      inTable = false;
      sawDivider = false;
      result.push(line);
      continue;
    }
    if (isMarkdownTableDivider(trimmed)) {
      // Keep only the first separator in a contiguous table; later `|---|`
      // rows were incorrectly inserted between data rows and must not render
      // as literal cells.
      if (inTable && sawDivider) continue;
      inTable = true;
      sawDivider = true;
      result.push(trimmed);
      continue;
    }
    const closed = trimmed.endsWith('|') ? trimmed : `${trimmed} |`;
    if (!inTable) {
      inTable = true;
      sawDivider = false;
      result.push(closed);
      const next = (lines[index + 1] || '').trim();
      if (next.startsWith('|') && !isMarkdownTableDivider(next)) {
        const width = Math.max(1, markdownTableCells(closed).length);
        result.push(`| ${Array.from({length: width}, () => '---').join(' | ')} |`);
        sawDivider = true;
      }
      continue;
    }
    result.push(closed);
  }
  return result.join('\n');
}
function splitLongReportParagraph(block, softLimit = 360, hardLimit = 480) {
  const compact = String(block || '').replace(/\s+/g, ' ').trim();
  if (!compact || compact.length <= hardLimit) return [String(block || '').trim()].filter(Boolean);
  if (/^#{1,6}\s|^\||^>\s|^```|^[-*+]\s|^\d+[.)、]\s/.test(compact)) {
    return [String(block || '').trim()].filter(Boolean);
  }
  const sentences = compact.match(/[^。！？!?；;]+[。！？!?；;]?/g) || [compact];
  const paragraphs = [];
  let current = '';
  for (const sentence of sentences) {
    const piece = sentence.trim();
    if (!piece) continue;
    if (current && current.length + piece.length > softLimit) {
      paragraphs.push(current.trim());
      current = piece;
    } else {
      current = `${current}${piece}`;
    }
  }
  if (current.trim()) paragraphs.push(current.trim());
  return paragraphs.length ? paragraphs : [compact];
}
function splitReportPnSegments(block) {
  const text = String(block || '').trim();
  if (!text || /^#{1,6}\s|^\||^```/.test(text)) return [text].filter(Boolean);
  // Promote each ``**装备名（Pn）。**`` (or plain ``装备名（Pn）。``) into its own
  // H4 section so P1–P7 never collapse into one continuous reading block.
  const labelRe = /\*\*\s*([^*]+?)\s*[（(](P[1-9])[）)]\s*[。.]?\s*\*\*/g;
  let matches = [...text.matchAll(labelRe)];
  if (!matches.length) {
    const plainRe = /(?:^|(?<=[。！？\n]))\s*([^\n。！？]{1,80}?)\s*[（(](P[1-9])[）)]\s*[。.]?\s*/g;
    matches = [...text.matchAll(plainRe)];
  }
  if (!matches.length) return [text];
  const segments = [];
  if (matches[0].index > 0) {
    const preamble = text.slice(0, matches[0].index).trim();
    if (preamble) segments.push(preamble);
  }
  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const end = index + 1 < matches.length ? matches[index + 1].index : text.length;
    const name = String(match[1] || '').trim();
    const code = match[2];
    const body = text.slice(match.index + match[0].length, end).trim();
    if (!name || !code) {
      if (body) segments.push(body);
      continue;
    }
    segments.push(body ? `#### ${code} ${name}\n\n${body}` : `#### ${code} ${name}`);
  }
  return segments.length ? segments : [text];
}
function segmentReportParagraphs(value) {
  const source = String(value || '');
  const lines = source.split('\n');
  const prepared = [];
  let inFence = false;
  for (const line of lines) {
    if (/^\s*```/.test(line)) inFence = !inFence;
    const stripped = line.trim();
    if (
      !inFence
      && stripped
      && prepared.length
      && /^#{1,6}\s/.test((prepared[prepared.length - 1] || '').trim())
      && !stripped.startsWith('#')
      && prepared[prepared.length - 1].trim() !== ''
    ) {
      prepared.push('');
    }
    if (!inFence && /^(?:[-*+]|\d+[.)、])\s/.test(stripped) && prepared.length && prepared[prepared.length - 1].trim()) {
      prepared.push('');
    }
    // Keep each Pn item on its own block even when the source omits blank lines.
    if (
      !inFence
      && /(?:^|\*\*)\s*[^*\n]{0,80}?（P[1-9]）/.test(stripped)
      && prepared.length
      && prepared[prepared.length - 1].trim()
      && !/^#{1,6}\s/.test(stripped)
    ) {
      prepared.push('');
    }
    prepared.push(line);
  }
  const normalized = prepared.join('\n').replace(/\n{3,}/g, '\n\n');
  const blocks = [];
  let fence = false;
  let buffer = [];
  const flush = () => {
    const block = buffer.join('\n').trim();
    buffer = [];
    if (!block) return;
    if (fence || block.startsWith('|') || /^#{1,6}\s/m.test(block) || /^(?:[-*+]|\d+[.)、])\s/m.test(block) || block.startsWith('>')) {
      blocks.push(block);
      return;
    }
    for (const segment of splitReportPnSegments(block)) {
      if (/^####\s+P[1-9]\b/.test(segment)) {
        blocks.push(segment);
        continue;
      }
      blocks.push(...splitLongReportParagraph(segment));
    }
  };
  for (const line of normalized.split('\n')) {
    if (/^\s*```/.test(line)) {
      if (!fence) flush();
      fence = !fence;
      buffer.push(line);
      if (!fence) flush();
      continue;
    }
    if (fence) {
      buffer.push(line);
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    buffer.push(line);
  }
  flush();
  return blocks.join('\n\n');
}
function reportMarkdown(value) {
  const content = segmentReportParagraphs(
    normalizeReportBareUrls(
      normalizeReportMarkdownTables(
        normalizeReportHtmlTables(agentFacingText(value, {preserveLayout: true})),
      ),
    )
      .replace(/\\\*\\\*([^\n]+?)\\\*\\\*/g, '**$1**')
      .replace(/\*\*([^*\n]+?)\s+\*\*/g, '**$1**')
      .replace(/(\*\*[^*\n]+?\*\*)(?=[\u3400-\u9fffA-Za-z0-9])/g, '$1 '),
  );
  const expanded = content.replace(/五档差距判断如下[。:：]\s*([^\n]+)/g, (full, body) => {
    const tiers = String(body).split(/\s*(?=第[一二三四五]档(?:是|为)?)/).filter(Boolean);
    if (tiers.length !== 5) return full;
    return `五档差距判断如下：\n\n${tiers.map((tier, index) => {
      const match = tier.match(/^第([一二三四五])档(?:是|为)?\s*(.*)$/);
      return match ? `${index + 1}. **第${match[1]}档**：${match[2].trim()}` : `${index + 1}. ${tier.trim()}`;
    }).join('\n\n')}`;
  });
  return summarizeBaselineGapTable(expanded);
}
function normalizeReportBareUrls(value) {
  const source = String(value || '');
  return source.replace(/https?:\/\/[^\s<>\u3000-\u303f\uff00-\uffef()[\]{}"']+/g, (matched, offset) => {
    const prefix = source.slice(Math.max(0, offset - 2), offset);
    if (prefix.endsWith('](') || source[offset - 1] === '<') return matched;
    const trailing = matched.match(/[.,;:!?]+$/)?.[0] || '';
    const url = trailing ? matched.slice(0, -trailing.length) : matched;
    return `<${url}>${trailing}`;
  });
}
/* Keep the narrative readable for Chinese readers. Expand common English
   abbreviations in the report body while leaving the formal source index,
   code fences, URLs, and evidence identifiers untouched. This is deliberately
   display-side as well as export-side so copy/download actions match what the
   reader sees without mutating the stored research artifact. */
function normalizeReportAbbreviations(value) {
  const source = String(value || '');
  const replacements = [
    [/DARPA\s+CODE/g, '美国国防高级研究计划局“受限环境协同作战”项目'],
    [/CJADC2/g, '联合全域指挥控制'],
    [/GNSS/g, '全球导航卫星系统'],
    [/GPS/g, '全球定位系统'],
    [/\bQuery\b/g, '查询问题'],
    [/ISR\s*\/\s*C2/g, '侦察监视情报与指挥控制'],
    [/\bISR\b/g, '侦察监视情报'],
    [/\bC2\b/g, '指挥控制'],
    [/\bDOD\b|\bDoD\b/g, '美国国防部'],
  ];
  let inFence = false;
  let inSourceIndex = false;
  return source.split('\n').map(line => {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      return line;
    }
    if (/核心公开来源索引|正式证据引用说明|证据引用说明|参考文献|来源索引/.test(line)) {
      inSourceIndex = true;
      return line;
    }
    if (inFence || inSourceIndex) return line;
    return replacements.reduce((current, [pattern, replacement]) => current.replace(pattern, replacement), line);
  }).join('\n');
}
/* Keep the report body readable by reserving visible hyperlinks for the
   compact source index. The first two inline citations remain clickable so a
   reader can still jump to a key source without turning the prose into a link
   catalogue. Copy/download actions continue to use the original Markdown. */
function compactReportInlineLinks(value) {
  const source = String(value || '');
  const lines = source.split('\n');
  let inlineLinks = 0;
  let inSourceIndex = false;
  let inFence = false;
  return lines.map(line => {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      return line;
    }
    if (/核心公开来源索引|正式证据引用说明|证据引用说明|参考文献|来源索引/.test(line)) {
      inSourceIndex = true;
      return line;
    }
    if (inFence || inSourceIndex) return line;
    return line
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (full, label, url) => {
        inlineLinks += 1;
        return inlineLinks <= 2 ? full : label;
      })
      .replace(/<https?:\/\/[^>\s]+>/g, full => {
        inlineLinks += 1;
        return inlineLinks <= 2 ? full : '（来源链接见文末索引）';
      });
  }).join('\n');
}
function buildDeepResearchSupplementMarkdown(rows = []) {
  const items = Array.isArray(rows) ? rows : [];
  const deepRows = items.filter(row => {
    const meta = capabilityDeepMeta(row);
    return Boolean(
      row?.is_deep_research
      || ['pending', 'pending_verification', 'unverified'].includes(meta.status)
      || row?.confidence_limited === true
      || /deep|reference_weapon|supplement|深研/i.test(`${meta.source} ${row?.source || ''}`),
    );
  });
  if (!deepRows.length) return '';
  const lines = [
    '## 深研补充（待核验）',
    '',
    '以下内容来自深度追问或参考武器定向深研，原始报告正文保持不变；正式采纳前需完成审核。',
    '',
  ];
  deepRows.forEach(row => {
    const meta = capabilityDeepMeta(row);
    const name = row.name || row.title || row.capability_name || '未命名能力';
    const evidence = row.evidence_ids || row.evidence_refs || [];
    const body = String(row.deep_capability_portrait || row.capability_image || row.reference_overview || row.overview || '').trim();
    lines.push(
      `### ${name}${meta.version ? ` · v${meta.version}` : ''}`,
      '',
      `- 状态：${meta.statusLabel}`,
      `- 来源：${meta.source || 'deep-thinking'}`,
      `- 证据引用：${Array.isArray(evidence) ? evidence.length : 0} 条`,
      '',
      body || '深研任务已启动，详细能力画像将在校验通过后补充。',
      '',
    );
  });
  return lines.join('\n');
}
function ReportView({text, run, capabilityRows = []}) {
  const raw = typeof text === 'string' ? text : formatValue(text);
  const deepSupplement = raw.includes('深研补充（待核验）') ? '' : buildDeepResearchSupplementMarkdown(capabilityRows);
  const enriched = ensureReportWeaponEquipmentTable(
    deepSupplement ? `${raw}\n\n${deepSupplement}` : raw,
    capabilityRows,
    resolvedReportTemplateMode(run, raw),
  );
  // Normalize after enrichment as the deterministic capability table can add
  // text that was not present in the stored report body.
  const content = reportMarkdown(normalizeReportAbbreviations(enriched));
  const displayContent = compactReportInlineLinks(content);
  const filename = `${String(run?.topic || 'research-report').replace(/[\\/:*?"<>|\s]+/g, '-').slice(0, 60)}-${run?.run_id || 'report'}.md`;
  const articleRef = useRef(null);
  const tocRef = useRef(null);
  const [headings, setHeadings] = useState([]);
  const [tocOpen, setTocOpen] = useState(false);
  useEffect(() => {
    // Headings are read back from the rendered DOM and jumped to by index, so
    // the outline cannot drift out of sync with slugs generated elsewhere.
    const article = articleRef.current;
    if (!article) return undefined;
    const collect = () => {
      const next = [...article.querySelectorAll('h1, h2, h3, h4')].map((node, index) => ({index, level: Number(node.tagName[1]) || 2, label: (node.textContent || '').trim()})).filter(item => item.label);
      setHeadings(current => current.length === next.length && current.every((item, index) => item.label === next[index].label) ? current : next);
    };
    collect();
    const observer = new MutationObserver(collect);
    observer.observe(article, {childList: true, subtree: true});
    return () => observer.disconnect();
  }, [displayContent]);
  useEffect(() => {
    if (!tocOpen) return undefined;
    const onPointerDown = event => { if (!tocRef.current?.contains(event.target)) setTocOpen(false); };
    const onKeyDown = event => { if (event.key === 'Escape') setTocOpen(false); };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => { document.removeEventListener('pointerdown', onPointerDown); document.removeEventListener('keydown', onKeyDown); };
  }, [tocOpen]);
  const jump = index => {
    const node = articleRef.current?.querySelectorAll('h1, h2, h3, h4')[index];
    setTocOpen(false);
    if (node) node.scrollIntoView({behavior: 'smooth', block: 'start'});
  };
  return <section className="report-view enhanced"><div><span><FileCheck2 size={18}/><b>研究报告</b></span><em>{run?.topic}</em><div className="report-view-actions">{headings.length > 1 && <div className="report-toc" ref={tocRef}><button type="button" aria-expanded={tocOpen} title="报告目录" onClick={() => setTocOpen(value => !value)}><AlignLeft size={14}/>目录<ChevronDown className={tocOpen ? 'flip' : ''} size={13}/></button>{tocOpen && <div className="report-toc-menu">{headings.map(item => <button type="button" key={`${item.index}-${item.label}`} className={`toc-level-${item.level}`} onClick={() => jump(item.index)}>{item.label}</button>)}</div>}</div>}<button type="button" title="复制报告 Markdown" onClick={() => void copyWithToast(content, '研究报告')}><Copy size={14}/>复制 Markdown</button><button type="button" title="下载为 Markdown 文件" onClick={() => { const saved = downloadText(filename, content); notify(saved ? '报告已开始下载' : '报告下载失败', saved ? 'ok' : 'error'); }}><Download size={14}/>下载 .md</button><button type="button" title="打印报告或另存为 PDF" onClick={() => window.print()}><Printer size={14}/>打印</button></div></div><article className="report-markdown" ref={articleRef}><ReactMarkdown remarkPlugins={[remarkGfm]} components={{a: ({node: _node, children, ...props}) => <a {...props} target="_blank" rel="noreferrer">{children}</a>, table: ({node: _node, children, ...props}) => <div className="report-table-scroll"><table {...props}>{children}</table></div>}}>{displayContent}</ReactMarkdown></article></section>;
}
function ReportFailureView({run, detail, resuming, resume, error, capabilityRows = [], ...favoriteProps}) { const reason = agentFacingText(String(detail || 'Reporter 未能完成独立深度撰写。').slice(0, 600)); return <section className="report-view enhanced"><div><span><CircleAlert size={18}/><b>报告生成失败</b></span><Status value="failed"/></div><article className="empty"><CircleAlert size={22}/><section><b>未使用确定性降级模板</b><p>{reason}</p>{run?.status === 'failed' && <button className="primary" disabled={resuming} onClick={resume}><RefreshCw size={14}/>{resuming ? '正在恢复' : '从检查点继续生成'}</button>}{error && <p className="form-error">{error}</p>}</section></article>{capabilityRows.length > 0 && <section className="report-failure-capabilities"><div><span><FlaskConical size={18}/><b>已完成的能力图像</b></span><em>报告正文暂不可读，先展示已完成的能力图像</em></div><CapabilityImageView rows={capabilityRows} referenceWeapons={[]} runId={run?.run_id} {...favoriteProps}/></section>}</section>; }
function RunDrawer({run, catalog, close, inspect, changed}) {
  const done = run.status === 'completed'; const canEdit = run.status === 'draft'; const canArchive = ['draft', 'completed', 'failed', 'cancelled'].includes(run.status);
  const canStop = ACTIVE_RUN_STATUSES.has(run.status);
  const [editing, setEditing] = useState(false); const [saving, setSaving] = useState(false); const [archiveConfirm, setArchiveConfirm] = useState(false); const [error, setError] = useState(''); const [historyRows, setHistoryRows] = useState([]);
  const [form, setForm] = useState(() => runForm(run, catalog));
  const historyTypes = new Set(historyRows.map(row => row.event_type));
  const historyActors = new Set(historyRows.map(row => row.actor || row.details?.actor || row.payload?.event?.actor || row.payload?.actor));
  const reportStageFailed = run.status === 'failed' && (historyTypes.has('report_model_failed') || historyActors.has('reporter'));
  const stageIndex = done ? 5 : historyTypes.has('report_completed') || historyActors.has('reporter') ? 4 : historyTypes.has('audit_completed') || historyTypes.has('audit_model_fallback') || historyTypes.has('audit_model_pending') || historyTypes.has('audit_model_unavailable') || historyActors.has('auditor') ? 3 : historyTypes.has('winning_subagent_completed') || historyTypes.has('winning_stage_completed') || historyTypes.has('capability_image_created') ? 2 : historyTypes.has('baseline_pipeline_started') || historyTypes.has('baseline_agent_completed') ? 1 : ({queued:0, planning:0}[run.status] ?? -1);
  const loadHistory = () => request(runApiPath(run.run_id, '/history?compact=true&limit=48'), [], {headers: {'X-Role': 'analyst'}}).then(rows => setHistoryRows(compactRunHistoryRows(rows)));
  useEffect(() => { setForm(runForm(run, catalog)); setEditing(false); setArchiveConfirm(false); setError(''); void loadHistory(); }, [run.run_id]);
  // Escape leaves the editor first so an accidental press cannot discard a
  // half-written draft, and only closes the drawer on the second press. The
  // overlay hook also traps Tab inside the drawer, freezes the page behind it
  // and returns focus to the row that opened it.
  const drawerRef = useOverlay(true, {onEscape: () => { if (editing) { setEditing(false); return; } close(); }});
  const set = (key, value) => setForm(current => ({...current, [key]: value}));
  const toggleAgent = id => set('selected_agent_ids', form.selected_agent_ids.includes(id) ? form.selected_agent_ids.filter(item => item !== id) : [...form.selected_agent_ids, id]);
  const save = async () => { setSaving(true); setError(''); const updated = await request(runApiPath(run.run_id), null, {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({topic: form.topic, supplemental_information: form.supplemental_information, research_route: form.research_route, interaction_mode: form.interaction_mode, discovery_branch: form.discovery_branch, execution_profile_id: form.execution_profile_id, report_template_mode: form.report_template_mode, selected_agent_ids: form.selected_agent_ids, max_rounds: Number(form.max_rounds), analyst_confirmed: run.analyst_confirmed || false})}); setSaving(false); if (updated) { changed(updated); setEditing(false); notify('草稿已保存', 'ok'); void loadHistory(); } else { setError('保存失败。仅草稿任务可编辑。'); notify('草稿保存失败', 'error'); } };
  const archive = async () => { setSaving(true); const updated = await request(runApiPath(run.run_id), null, {method: 'DELETE', headers: {'X-Role': 'analyst'}}); setSaving(false); if (updated) { changed(updated); notify(`已归档：${run.topic}`, 'ok'); close(); } else { setError('归档失败。运行中的任务不能归档。'); notify('归档失败，运行中的任务不能归档。', 'error'); } };
  const stop = async () => { if (!window.confirm(`确定停止研究任务“${run.topic}”吗？将终止该任务启动的所有 Agent 进程。`)) return; setSaving(true); setError(''); const result = await requestResult(runApiPath(run.run_id, '/stop'), {method:'POST', headers:{'Idempotency-Key':`stop:${run.run_id}`, 'X-Role':'analyst'}}); setSaving(false); if (result.ok) { changed(result.data); notify('已请求停止任务', 'info'); void loadHistory(); } else { setError(result.detail || '停止任务失败。'); notify('停止任务失败', 'error'); } };
  const resume = async () => { setSaving(true); setError(''); const result = await requestResult(runApiPath(run.run_id, '/resume'), {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID(), 'X-Role': 'analyst'}}); setSaving(false); if (result.ok) { changed(result.data); notify('已从断点继续执行', 'ok'); void loadHistory(); } else { setError(result.detail || '断点恢复失败，请检查 Worker 与模型配置。'); notify('断点恢复失败', 'error'); } };
  const harnessLabel = run.execution_profile_id === 'winning_swarm_dynamic_v2' ? 'Winning Swarm Dynamic v2 Challenger' : run.execution_profile_id === 'swarm_quality_v1' ? 'Swarm Quality v1 Challenger' : run.execution_profile_id === 'optimized_v2' ? 'Optimized v2 Challenger' : 'Legacy v1';
  return <div className="drawer-backdrop" onClick={close}><aside className="run-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-label={`研究任务详情：${run.topic}`} onClick={event => event.stopPropagation()}><button className="drawer-close icon-button" title="关闭" onClick={close}><X size={16}/></button><span className="drawer-eyebrow">研究任务 · <em className="drawer-run-id">{run.run_id}</em><button type="button" className="inline-copy" title="复制运行 ID" aria-label="复制运行 ID" onClick={() => void copyWithToast(run.run_id, '运行 ID')}><Copy size={12}/></button></span>{editing ? <section className="drawer-editor"><Field label="研究主题"><input value={form.topic} onChange={event => set('topic', event.target.value)}/></Field><Field label="补充信息（可选）"><textarea className="supplement-input" value={form.supplemental_information} maxLength={8000} onChange={event => set('supplemental_information', event.target.value)}/></Field><div className="drawer-edit-grid"><Field label="研究路线"><select value={form.research_route} onChange={event => set('research_route', event.target.value)}><option value="auto">按发现分支自动映射</option>{catalog.routes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="交互模式"><select value={form.interaction_mode} onChange={event => set('interaction_mode', event.target.value)}>{(catalog.interaction_modes || []).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="A–H 发现分支"><select value={form.discovery_branch} onChange={event => set('discovery_branch', event.target.value)}><option value="auto">Agent 自动选择</option>{(catalog.discovery_branches || []).map(item => <option key={item.id} value={item.id}>{item.id} · {item.name}</option>)}</select></Field><Field label="运行模式"><select value={form.execution_profile_id} onChange={event => set('execution_profile_id', event.target.value)}>{(catalog.execution_profiles || [{id:'legacy_v1',name:'Legacy v1'}]).filter(item => item.selectable !== false).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="最大轮次"><select value={form.max_rounds} onChange={event => set('max_rounds', Number(event.target.value))}>{[1,2,3,...(form.execution_profile_id === 'legacy_v1' ? [4,5] : [])].map(item => <option key={item} value={item}>{item} 轮</option>)}</select></Field></div><div className="drawer-agent-list">{businessAgents(catalog).map(agent => <label key={agent.agent_id} className={form.selected_agent_ids.includes(agent.agent_id) ? 'selected' : ''}><input type="checkbox" checked={form.selected_agent_ids.includes(agent.agent_id)} onChange={() => toggleAgent(agent.agent_id)}/><span>{agent.display_name}</span></label>)}</div><div className="drawer-editor-actions"><button onClick={() => setEditing(false)}><X size={15}/>取消</button><button className="primary" disabled={saving || !form.topic.trim()} onClick={save}><Save size={15}/>{saving ? '保存中' : '保存草稿'}</button></div></section> : <><h2>{run.topic}</h2><Status value={run.status}/>{run.supplemental_information && <section className="drawer-supplement"><b>用户补充信息</b><p>{run.supplemental_information}</p><small>执行时由主控 Agent 压缩并结构化传递</small></section>}<dl><dt>研究路线</dt><dd>{routeLabel(run.research_route)}</dd><dt>交互模式</dt><dd>{run.interaction_mode === 'autonomous' ? '智能元编排' : '专家约束编排'}</dd><dt>A–H 分支</dt><dd>{run.discovery_branch === 'auto' ? 'Agent 自动选择' : run.discovery_branch}</dd><dt>Harness</dt><dd>{harnessLabel}</dd><dt>执行方式</dt><dd><ExecutionBadge execution={run.execution}/></dd><dt>业务 Agent</dt><dd>{run.selected_agent_ids.length ? run.selected_agent_ids.map(agentModelLabel).join('、') : '由编排 Agent 智能选择'}</dd><dt>最大轮次</dt><dd>{run.max_rounds}</dd></dl><div className="drawer-steps">{['问题解析与任务委派', '基线 Agent 研判', 'S1–S6 轻量门控与按需回溯', '五判据审计', '研究报告输出'].map((item, index) => { const failed = reportStageFailed && index === 4; return <div key={item}><i className={failed ? 'failed' : index < stageIndex ? 'done' : index === stageIndex ? 'active' : ''}/><span>{item}</span>{failed && <Status value="failed"/>}</div>; })}</div>{(done || ['queued', 'planning', 'researching', 'recalling', 'synthesizing', 'reviewing', 'reporting', 'failed', 'cancel_requested'].includes(run.status)) && <div className="drawer-actions">{canStop && <button className="danger" disabled={saving} onClick={stop}><X size={15}/>{saving ? '停止中' : '停止任务'}</button>}<button onClick={() => inspect('interactions')}><History size={15}/>交互过程</button>{run.status === 'failed' && <button className="primary" disabled={saving} onClick={resume}>{saving ? '恢复中' : '从断点继续'}</button>}{done && <><button onClick={() => inspect('evidence')}>证据中心</button><button onClick={() => inspect('winning')}>S1–S6 Agent</button><button className="primary" onClick={() => inspect('capabilities')}>能力画像</button></>}</div>}{canEdit && <button className="drawer-manage" onClick={() => setEditing(true)}><Pencil size={15}/>编辑草稿</button>}{canArchive && <div className="archive-action">{archiveConfirm ? <><span>归档后任务从当前列表隐藏，审计产物仍保留。</span><button onClick={() => setArchiveConfirm(false)}>取消</button><button className="danger" disabled={saving} onClick={archive}><Trash2 size={14}/>确认归档</button></> : <button onClick={() => setArchiveConfirm(true)}><Archive size={15}/>归档任务</button>}</div>}</>}{error && <p className="form-error"><CircleAlert size={15}/>{error}</p>}<section className="run-history"><div><History size={16}/><b>执行历史</b><span>{historyRows.length} 个事件</span></div>{historyRows.length ? historyRows.slice(-24).reverse().map(row => <article key={row.sequence}><i/><span><b>{eventLabel(row.event_type)}</b><small>#{row.sequence} · {historySummary(row, run.result?.audit_status)}</small></span></article>) : <p>尚无历史事件</p>}</section></aside></div>;
}

/* ------------------------------------------------------------- placeholders */

/* Loading placeholders mirror the footprint of the real content, so the first
   paint already shows the page's shape and nothing jumps when data lands. */
function RunCardSkeleton() {
  return <article className="research-run-card skeleton-card"><Skeleton width="32%" height={10}/><Skeleton width="88%" height={17}/><Skeleton width="64%" height={12}/><div><Skeleton width={82} height={20} radius={999}/><Skeleton width={104} height={20} radius={999}/></div><Skeleton width="44%" height={10}/></article>;
}
function TaskRowSkeleton() {
  return <div className="task-row-skeleton"><Skeleton width="74%" height={12}/><Skeleton width="46%" height={9}/></div>;
}
function PaneSkeleton() {
  return <div className="pane-skeleton" aria-hidden="true"><Skeleton width="28%" height={15}/><Skeleton width="100%" height={11}/><Skeleton width="95%" height={11}/><Skeleton width="86%" height={11}/><Skeleton width="22%" height={15}/><Skeleton width="97%" height={11}/><Skeleton width="90%" height={11}/><Skeleton width="78%" height={11}/></div>;
}

/* ------------------------------------------------------- failure fallback */

/* Rendered by the ErrorBoundary in place of a blank workbench: the chrome and
   every other view stay usable, and backend work is untouched. */
function WorkbenchErrorView({error, retry, home}) {
  const detail = String(error?.stack || error?.message || error || '未知渲染错误');
  return <section className="workbench-error" role="alert">
    <span className="workbench-error-badge"><ShieldAlert size={22}/></span>
    <div><b>当前视图渲染时出现异常</b><p>后台研究任务不受影响，其余视图仍可正常使用。可以重试渲染，或返回任务列表继续操作。</p><code>{detail.slice(0, 400)}</code></div>
    <div className="workbench-error-actions"><button className="primary" onClick={retry}><RefreshCw size={15}/>重试渲染</button><button onClick={home}><Archive size={15}/>返回任务列表</button><button onClick={() => void copyWithToast(detail, '错误信息')}><Copy size={15}/>复制错误信息</button></div>
  </section>;
}

/* --------------------------------------------------------- command palette */

/* One keyboard entry point for everything the chrome exposes: views, recent
   research tasks and the few actions people repeat all day. Navigation only —
   nothing here changes data. */
function CommandPalette({open, close, runs, navItems, view, navigate, openRun, refresh, openShortcuts}) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);
  const containerRef = useOverlay(open, {onEscape: close});
  useEffect(() => {
    if (!open) return undefined;
    setQuery('');
    setCursor(0);
    const timer = setTimeout(() => inputRef.current?.focus(), 30);
    return () => clearTimeout(timer);
  }, [open]);
  if (!open) return null;
  const keyword = query.trim().toLowerCase();
  const hit = (...fields) => !keyword || fields.some(field => String(field ?? '').toLowerCase().includes(keyword));
  const viewItems = navItems.filter(([id, label]) => hit(label, id)).map(([id, label, Icon]) => ({key: `view:${id}`, group: '视图', Icon, label, hint: view === id ? '当前视图' : '前往', act: () => navigate(id)}));
  const runItems = runs.filter(run => hit(run.topic, run.run_id)).slice(0, 6).map(run => ({key: `run:${run.run_id}`, group: '研究任务', Icon: FlaskConical, label: run.topic, hint: `${statusLabel(run.status)} · ${routeLabel(run.research_route)}`, act: () => openRun(run)}));
  const actionItems = [
    {key: 'act:new', Icon: Play, label: '新建研究任务', hint: '定位到 Query 输入框', act: () => { navigate('runs'); setTimeout(() => { const input = document.getElementById('research-query-input'); input?.focus(); input?.scrollIntoView({behavior: 'smooth', block: 'center'}); }, 90); }},
    {key: 'act:library', Icon: BookOpenCheck, label: '打开问题库', hint: 'Query Library', act: () => navigate('query-library')},
    {key: 'act:refresh', Icon: RefreshCw, label: '刷新任务与运行时数据', hint: '重新拉取 API', act: () => void refresh()},
    {key: 'act:shortcuts', Icon: Keyboard, label: '查看键盘快捷键', hint: '?', act: openShortcuts},
  ].filter(item => hit(item.label, item.hint)).map(item => ({...item, group: '快捷操作'}));
  // With a keyword the intent is almost always "find that task", so matching
  // runs lead; the idle palette leads with navigation.
  const items = keyword ? [...runItems, ...viewItems, ...actionItems] : [...viewItems, ...runItems, ...actionItems];
  const active = items.length ? Math.min(cursor, items.length - 1) : 0;
  const activate = item => { close(); item.act(); };
  const onKeyDown = event => {
    if (!items.length) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); setCursor((active + 1) % items.length); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setCursor((active - 1 + items.length) % items.length); }
    else if (event.key === 'Enter') { event.preventDefault(); activate(items[active]); }
  };
  return <div className="command-palette-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="command-palette" ref={containerRef} role="dialog" aria-modal="true" aria-label="命令面板">
      <div className="command-palette-input"><Search size={17}/><input ref={inputRef} value={query} placeholder="搜索研究任务、跳转视图或执行操作…" aria-label="命令面板搜索" onChange={event => { setQuery(event.target.value); setCursor(0); }} onKeyDown={onKeyDown}/><kbd>Esc</kbd></div>
      <div className="command-palette-list" role="listbox" aria-label="命令面板结果">
        {items.length ? items.map((item, index) => <React.Fragment key={item.key}>
          {(index === 0 || items[index - 1].group !== item.group) && <div className="command-palette-group">{item.group}</div>}
          <button type="button" role="option" aria-selected={index === active} className={index === active ? 'active' : ''} ref={index === active ? node => node?.scrollIntoView({block: 'nearest'}) : undefined} onMouseMove={() => setCursor(index)} onClick={() => activate(item)}>
            <item.Icon size={16}/><span>{item.label}</span><em>{item.hint}</em>
          </button>
        </React.Fragment>) : <p className="command-palette-empty">没有匹配的任务、视图或操作</p>}
      </div>
      <footer><span><kbd>↑</kbd><kbd>↓</kbd>选择</span><span><kbd><CornerDownLeft size={11}/></kbd>确认</span><span><kbd>{COMMAND_KEY_LABEL}</kbd><kbd>K</kbd>随时唤起</span></footer>
    </div>
  </div>;
}

/* ------------------------------------------------------------- shortcut help */

const SHORTCUT_SECTIONS = [
  ['全局', [[[COMMAND_KEY_LABEL, 'K'], '唤起命令面板：搜索任务、切换视图、执行常用操作'], [['?'], '打开本快捷键说明'], [['Esc'], '关闭命令面板、任务抽屉，或先退出草稿编辑']]],
  ['命令面板', [[['↑', '↓'], '在结果之间移动'], [['Enter'], '打开当前选中的视图或研究任务']]],
  ['研究任务列表', [[['/'], '定位到任务搜索框']]],
  ['Query 输入', [[[COMMAND_KEY_LABEL, 'Enter'], '在 Query 输入框内直接启动研究'], [['Tab'], '按顺序在输入框与操作按钮间移动']]],
];

function ShortcutSheet({open, close}) {
  const containerRef = useOverlay(open, {onEscape: close});
  if (!open) return null;
  return <div className="shortcut-sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="shortcut-sheet" ref={containerRef} role="dialog" aria-modal="true" aria-label="键盘快捷键">
      <header><span><Keyboard size={17}/><b>键盘快捷键</b></span><button className="icon-button" title="关闭" aria-label="关闭" onClick={close}><X size={16}/></button></header>
      <div className="shortcut-sheet-body">{SHORTCUT_SECTIONS.map(([section, rows]) => <section key={section}><small>{section}</small>{rows.map(([keys, description]) => <div key={description}><span>{keys.map((key, index) => <kbd key={`${key}-${index}`}>{key}</kbd>)}</span><em>{description}</em></div>)}</section>)}</div>
    </div>
  </div>;
}

/* ------------------------------------------------------------- back to top */

/* Long report and timeline pages scroll far past the topbar; this brings the
   controls back without a manual scroll. */
function BackToTop() {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 420);
    onScroll();
    window.addEventListener('scroll', onScroll, {passive: true});
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  if (!visible) return null;
  return <button type="button" className="back-to-top" title="回到页面顶部" aria-label="回到页面顶部" onClick={() => window.scrollTo({top: 0, behavior: 'smooth'})}><ArrowUp size={17}/></button>;
}

function providerDisplayLabel() { return 'Agent'; }
function modelDisplayLabel(model) {
  const value = String(model || '').toLowerCase();
  if (value.includes('deepseek')) return 'DeepSeek';
  if (value.includes('gpt') || value.includes('openai')) return 'GPT';
  return 'GPT';
}
function completedResearchSummary(value) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  const prescriptive = [
    /^(?:后续|下一步|后置(?:环节|Agent|智能体)?|后续研究|后续工作|进一步).{0,18}(?:应|应当|需要|需|必须|建议|优先|重点|继续|核验|验证|关注)/,
    /^(?:应|应当|需要|需|必须|建议|请|务必|继续|优先|重点关注)/,
    /(?:装备与技术|技术|装备|研究|证据|验证|核验)优先级应/,
  ];
  return text.split(/(?<=[。！？!?；;])/).filter(part => !prescriptive.some(pattern => pattern.test(part.trim()))).join('').trim();
}
function agentFacingText(value, {preserveLayout = false} = {}) {
  const raw = String(value ?? '');
  if (!preserveLayout && raw.includes('独立检验Query蓝图制胜命题')) return '围绕当前作战矛盾独立推演并检验制胜路径。';
  if (!preserveLayout && /^\s*制胜命题验证\s*[：:]/.test(raw)) return '制胜命题推演';
  const sanitized = raw
    .replace(/(?:概念性工作名|Query因果)\s*[：:]\s*[^；。\n]*[；。]?/g, '')
    .replace(/\u7532\u65b9可读能力画像报告/g, '能力画像研究报告')
    .replace(/\u7532\u65b9能力画像报告/g, '能力画像研究报告')
    .replace(/\u7532\u65b9报告/g, '研究报告')
    .replace(/\u7532\u65b9/g, '项目')
    .replace(/codex\s*子\s*agent/gi, '专用 Agent')
    .replace(/codex[\s_-]*cli/gi, 'Agent')
    .replace(/codex\s*专用\s*agent/gi, '专用 Agent')
    .replace(/自定义\s*agent/gi, 'Agent')
    .replace(/codex/gi, 'Agent');
  const cleaned = (preserveLayout ? sanitized : sanitized.replace(/\s{2,}/g, ' ')).trim();
  return cleaned || '制胜关系分析';
}
function runForm(run) { return {topic: run.topic, supplemental_information: run.supplemental_information || '', research_route: run.research_route, interaction_mode: run.interaction_mode || 'expert', discovery_branch: run.discovery_branch || 'auto', execution_profile_id: run.execution_profile_id || 'legacy_v1', report_template_mode: run.report_template_mode === 'three_layer_nine_item' || run.report_template_mode === 'project_argument_v1' ? run.report_template_mode : 'project_argument_v1', selected_agent_ids: [...run.selected_agent_ids], max_rounds: run.max_rounds}; }
function agentModelLabel(id) { return {orchestrator:'编排器',scenario_divergence:'场景发散',case_research:'案例研究',technology_radar:'技术雷达',opponent_monitoring:'对手监测',system_confrontation:'体系对抗',cross_domain_fusion:'跨域融合',nontraditional_security:'非传统安全',international_situation:'国际形势',combat_scenario:'作战场景',weapon_equipment:'武器装备',operational_employment:'作战运用',convergence_fusion:'收敛融合',winning_mechanism:'S Agent 编排器',winning_dynamic_specialist:'动态专用 Agent 模板',winning_s1_opponent:'S1 对手分析',winning_s2_operations:'S2 作战运用审查',winning_s3_breakthrough:'S3 突破口思考',winning_s4_capability:'S4 装备能力映射',winning_s5_gap:'S5 创新颠覆候选组合评审',winning_s6_image:'S6 能力图像综合',winning_step_critic:'步骤批判',winning_round_critic:'中循环批判',auditor:'审计',reporter:'报告'}[id] || id; }
function stringList(value) { if (value == null || value === '') return []; const rows = Array.isArray(value) ? value : [value]; return rows.map(item => typeof item === 'object' && item !== null ? item.skill_id || item.id || item.name || '' : String(item)).filter(Boolean); }
function ensureAgentSuffix(value) { const text = agentFacingText(value || '专用 Agent').trim(); return /agent$/i.test(text) ? text : `${text} Agent`; }
function normalizeStepRef(value) { const text = String(value ?? '').trim(); if (!text) return '—'; if (text.toLowerCase() === 'convergence') return '收敛融合'; const match = text.match(/(?:winning_s|step[_ -]?|^s?)([1-6])(?:\b|_)/i); return match ? `S${match[1]}` : text; }
function normalizeMergeTarget(item = {}) { const published = item.handoff_policy?.publish_to; const value = item.target_step ?? item.merge_into_step ?? item.merge_target ?? item.target ?? (Array.isArray(published) ? published[0] : published); return value == null || value === '' ? '' : normalizeStepRef(value); }
function normalizeSAgentStatus(value, executionMode, completedEvent = false) { const status = String(value || '').toLowerCase(); if (executionMode === 'skip' || status.includes('skip')) return 'skipped'; if (['completed', 'complete', 'done', 'success', 'succeeded'].includes(status) || completedEvent) return 'completed'; if (['running', 'started', 'in_progress', 'active'].includes(status)) return 'running'; if (['failed', 'error', 'cancelled'].includes(status)) return 'failed'; return 'pending'; }
function latestReporterPhaseStatus(events = [], runCompleted = false, runFailed = false) { let status = 'pending'; let started = false; events.forEach(event => { const details = event.details || {}; const delegated = event.event_type === 'agent_task_delegated' && details.target_agent_id === 'reporter'; const activity = event.actor === 'reporter' && (['task_received', 'tool_call', 'tool_result'].includes(event.event_type) || event.event_type.startsWith('report_model_')); if (delegated || activity) { started = true; status = 'running'; } if (event.event_type === 'report_model_failed') { started = true; status = 'failed'; } else if (event.event_type === 'report_completed') { started = true; status = 'completed'; } }); if (runCompleted) return 'completed'; if (runFailed && started && status !== 'completed') return 'failed'; return status; }
function normalizeWorkflowStatus(value, fallback = 'pending') { if (value === true) return 'completed'; if (value === false || value == null || value === '') return fallback; const status = String(value).toLowerCase(); if (['completed', 'complete', 'done', 'success', 'succeeded'].includes(status)) return 'completed'; if (['running', 'started', 'in_progress', 'active'].includes(status)) return 'running'; if (status.includes('skip')) return 'skipped'; if (['failed', 'error', 'cancelled'].includes(status)) return 'failed'; return 'pending'; }
function workflowStatusRank(value) { return {failed: 0, pending: 0, running: 1, skipped: 2, completed: 3}[value] ?? 0; }
function sAgentStatusLabel(value) { return {pending:'待调度',running:'执行中',completed:'已完成',skipped:'已跳步',failed:'失败'}[value] || value; }
function loopCount(value, fallback = 0) { if (typeof value === 'object' && value !== null) value = value.count ?? value.iterations ?? value.value; const count = Number(value); return Number.isFinite(count) ? Math.max(0, count) : Math.max(0, Number(fallback) || 0); }
function recallMatchesStep(item, step, agentId) { const text = [item.return_node, item.target_agent_id, item.target_capability_tag].filter(Boolean).join(' ').toLowerCase(); return text.includes(String(agentId).toLowerCase()) || new RegExp(`(?:^|[^0-9])s?${step}(?:[^0-9]|$)`, 'i').test(text); }
function eventTargetsStep(event, step, agentId) { const details = event.details || {}; const realBacktrack = event.event_type === 'recall_requested' || (['winning_inner_loop_evaluated', 'winning_middle_loop_evaluated', 'winning_outer_loop_evaluated'].includes(event.event_type) && details.passed === false && (['retry', 'recall', 'backtrack'].includes(String(details.recommended_action || '').toLowerCase()) || Number(details.rerun_from_step || details.backtrack_to_step || 0) > 0 || (details.return_node != null && details.return_node !== ''))); if (!realBacktrack) return false; const text = [event.actor, details.target_agent_id, details.rerun_from_step, details.backtrack_to_step, details.return_node, details.return_nodes, details.step].flat().filter(value => value != null).join(' ').toLowerCase(); return text.includes(String(agentId).toLowerCase()) || new RegExp(`(?:^|[^0-9])s?${step}(?:[^0-9]|$)`, 'i').test(text); }
function formatNextAction(value) { if (!value) return ''; if (typeof value === 'string') return value; if (typeof value !== 'object') return String(value); const action = {continue:'继续',parallel:'并行展开',backtrack:'回溯',recall:'定向再调',stop:'提交门控'}[value.action] || value.action || ''; const target = Number(value.target_step || 0) > 0 ? `S${value.target_step}` : ''; return [action, target, value.reason].filter(Boolean).join(' · '); }
function loopEventDecision(event) { const details = event.details || {}; const decision = details.passed === true ? '通过' : details.passed === false ? '需回溯' : details.replan_required === true ? '触发重规划' : details.status ? formatValue(details.status) : event.summary || event.title || '已完成判定'; const target = details.rerun_from_step ?? details.return_node ?? details.target_agent_id; return agentFacingText(`${decision}${target != null && target !== '' ? ` · 目标 ${normalizeStepRef(target)}` : ''}`); }
function compactRunHistoryRows(rows = []) { const seenProgress = new Set(); const completedActors = new Set(); return [...rows].reverse().filter(row => { const event = row.payload?.event || {}; const details = event.payload || {}; const actor = event.actor || details.agent_instance_id || details.agent_id || ''; if (['baseline_model_call_completed', 'winning_model_call_completed', 'report_model_call_completed', 'winning_agent_session_completed'].includes(row.event_type)) completedActors.add(actor); if (!['baseline_model_call_progress', 'winning_model_call_progress', 'report_model_call_progress', 'winning_agent_waiting'].includes(row.event_type)) return true; const key = `${row.event_type}|${actor}|${details.phase || ''}|${details.current_step || ''}`; if ((actor && completedActors.has(actor)) || seenProgress.has(key)) return false; seenProgress.add(key); return true; }).reverse().map(row => row.payload?.event?.payload?.event_type === 'winning_portfolio_gap_completion_planned' ? {...row, event_type: 'recall_requested'} : row); }
function historySummary(row, finalAuditStatus = '') { const payload = row.payload || {}; const event = payload.event || {}; const details = event.payload || {}; if (details.event_type === 'winning_portfolio_gap_completion_planned') return `组合评审后合格方向 ${details.passed_count || 0}/${details.finalist_minimum || 5}，仅在需要时补充互异制胜维度；复用既有账本，未重跑前序阶段`; if (row.event_type === 'winning_model_call_progress' && Number(details.batch || 0) >= 6) return `组合评审后定向补强 · ${details.current_step || details.mission_node || '残差修复'} · 已耗时 ${Number(details.elapsed_seconds || 0).toFixed(1)} 秒（未重跑前序阶段）`; let summary = event.summary || failureReasonText(payload.error) || payload.status || payload.prior_status || payload.research_route || row.event_type; if (row.event_type === 'baseline_agent_completed') summary = completedResearchSummary(summary); const auditRelated = row.event_type === 'audit_completed' || event.actor === 'auditor' || ['review_audit', 'write_audit'].includes(event.payload?.tool_name); if (finalAuditStatus === 'approved' && auditRelated && /limited|受限/i.test(String(summary))) return '模型审计初始状态待收敛（最终已通过）'; return agentFacingText(summary); }
function failureReasonText(value) { const reason = String(value || '').trim(); if (!reason) return ''; if (reason === 'wall-clock budget expired') return '制胜机理阶段外层 900 秒墙钟预算到期，已完成结果未被接纳'; return reason; }
function PageTitle({eyebrow, title, subtitle, children}) { return <div className="page-title"><div><span>{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></div><div className="title-actions">{children}</div></div>; }
function Metric({label, value, icon: Icon}) { return <article className="metric"><div><span>{label}</span><b>{value}</b></div><Icon size={20}/></article>; }
function Field({label, children}) { return <label className="field"><span>{label}</span>{children}</label>; }
function TagGroup({label, items}) { return <div className="tag-group"><small>{label}</small><p>{(items || []).map(item => <em key={item}>{item}</em>)}</p></div>; }
function Detail({label, value}) { return <div className="detail"><small>{label}</small><p>{value}</p></div>; }
function Status({value}) { return <span className={`status ${value}`}><i/>{statusLabel(value)}</span>; }
function ExecutionBadge({execution = {}}) { const real = execution.mode === 'real'; return <span className={`execution ${real ? 'real' : 'fake'}`}><i/>{real ? `${providerDisplayLabel(execution.provider)} · ${modelDisplayLabel(execution.model || 'gpt-5.5')}` : 'Fake · 离线'}</span>; }
function Empty({text, children}) { return <div className="empty"><Activity size={23}/>{text}{children ? <div className="empty-actions">{children}</div> : null}</div>; }
async function request(path, fallback, options) { try { const response = await fetch(`${api}${path}`, options); if (!response.ok) return fallback; return (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : await response.text(); } catch { return fallback; } }
async function requestResult(path, options = {}, requestOptions = {}) {
  const controller = new AbortController();
  const timeoutMs = Number(requestOptions.timeoutMs || 0);
  const timer = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(`${api}${path}`, {...options, signal: options.signal || controller.signal});
    const data = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : await response.text();
    return response.ok ? {ok:true,data} : {ok:false,status:response.status,detail:typeof data === 'object' ? data.detail : data};
  } catch (error) {
    return {ok:false,detail:error?.name === 'AbortError' ? `请求超时（${Math.round(timeoutMs / 1000)} 秒），任务状态未确定，请刷新任务列表确认。` : '无法连接 API 服务。'};
  } finally {
    if (timer) clearTimeout(timer);
  }
}
async function fileToBase64(file) { const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ''; const chunk = 32768; for (let index = 0; index < bytes.length; index += chunk) binary += String.fromCharCode(...bytes.subarray(index, index + chunk)); return btoa(binary); }
function datasetModeLabel(value) { return {fixture:'内置冒烟',expert_approved:'专家通过集',local_candidate_test:'本地候选测试集',local_jsonl_test:'本地 JSONL 测试集'}[value] || value || '本地数据集'; }
function benchmarkSystemLabel(value) { return {full_method:'完整方法',generic_agent:'通用 Codex Agent',bare_llm:'纯 LLM',zhipu_llm:'智谱 GLM'}[value] || value; }
function benchmarkJudgeLabel(value) { return {none:'不评审',fake:'离线评审',real:'真实专家评审'}[value] || value || '不评审'; }
function benchmarkDimensionLabel(value) { return {task_fulfillment:'任务完成度',facts_and_citations:'事实与引用',analysis_depth:'分析深度',equipment_demand_value:'装备需求价值',uncertainty:'不确定性说明',route_task_fulfillment:'路径与任务完成',evidence_and_factuality:'证据与事实可靠性',causal_and_mechanism_depth:'因果与机理深度',military_operational_value:'军事运用价值',capability_mapping_and_demand_quality:'能力映射与需求质量',novelty_and_foresight:'前瞻新颖性',system_and_cross_scenario_robustness:'体系与跨场景稳健性',uncertainty_and_validation:'不确定性与验证'}[value] || value; }
function benchmarkStageLabel(stage, status) { if (status === 'cancelling') return '正在停止：等待当前外部调用安全结束'; return {queued:'任务已排队，等待执行',running_baselines:'正在执行 baseline 回答',building_pairs:'正在匿名化并生成正反序配对',judging:'评审专家正在进行匿名盲评',aggregating:'正在汇总胜平负、置信区间与仲裁队列'}[stage] || 'Benchmark 正在执行'; }
function difficultyLabel(value) { return {easy:'简单',medium:'中等',hard:'困难'}[value] || value; }
function benchmarkStatus(value) { return {queued:'queued',running:'researching',cancelling:'cancel_requested',cancelled:'cancelled',completed:'completed',completed_with_failures:'failed',failed:'failed'}[value] || value; }
function objectTitle(view, row, index) { if (view === 'evidence') return agentFacingText(row.source_title || row.claim || `证据 ${index + 1}`); if (view === 'winning') return agentFacingText(`${row.layer || '阶段'} ${row.title || '制胜机理分析'}`); return agentFacingText(row.name || `能力画像 ${index + 1}`); }
function fieldLabel(key) { return {claim: '支撑主张', excerpt: '证据摘录', quality_assessment: '质量评估', source_location: '来源位置', source_url: '来源地址', created_by: '创建 Agent', layer: '分析层级', gate_passed: '门控结果', capability_id: '能力编号', name: '名称', equipment_category: '装备类别', capability_type: '类型', source_winning_logic: '来源制胜逻辑', related_scenario: '关联场景', priority: '优先级', capability_gap: '能力差距', capability_image: '能力画像', tool_name: '工具名称', allowed_tools: '允许工具', context_sections: '可见上下文', api_key_env: '密钥环境变量', base_url_host: '模型 URL 主机', replan_required: '是否重规划', step_mode_overrides: 'S 步骤调整', execution_mode: '执行强度', middle_cycle: '中循环轮次', current_step: '当前步骤', elapsed_seconds: '已耗时（秒）', phase: '调用阶段', steps: '涉及步骤', added_secondary_branches: '新增参考分支', dynamic_subagents: '动态专用 Agent', stop_reason: '停止原因', wave: '群控波次', batch: '并行批次', archetype: '专用角色', role_purpose: '角色任务', trigger_residuals: '触发残差', hypothesis_id: '候选假设', merge_target: '合并节点', provider_type: 'Provider 类型', execution_backend: '执行后端', context_isolation: '上下文隔离', runtime_profile_id: 'Runtime Profile', skill_ids: '受治理 Skill', allow_child_spawn: '允许递归招聘', session_ref: '会话引用', expected_quality_gain: '预期质量增益', incremental_quality: '实际质量增益', score: '质量分', residuals: '质量残差', reasons: '淘汰原因', reason: '回收原因', rejection_reasons: '驳回原因' }[key] || key.replaceAll('_', ' '); }
function stepModeLabel(value) { return {deep:'深入',standard:'标准',light:'弱化',skip:'跳过',dynamic:'动态'}[value] || value || '标准'; }
function baselineAgentModeLabel(value) { return {required:'必需',reference:'参考',callback:'回调'}[value] || value || ''; }
function formatValue(value) { if (Array.isArray(value)) return agentFacingText(value.map(item => typeof item === 'object' ? JSON.stringify(item) : item).join('；')); if (typeof value === 'object') return agentFacingText(JSON.stringify(value, null, 2)); if (typeof value === 'boolean') return value ? '通过' : '未通过'; return agentFacingText(value); }
function eventLabel(value) { return {run_created: '任务创建', run_updated: '草稿更新', run_archived: '任务归档', run_status_changed: '状态变化', run_recovered: '中断恢复', run_result_saved: '交付完成', run_failed: '运行失败', run_started: '任务启动', expert_feedback_submitted: '专家审核反馈', expert_feedback_handoff_loaded: '反馈记忆已注入后续任务', discovery_meta_loop_evaluated: 'L4 元循环', baseline_pipeline_started: '研究流水线启动', baseline_discovery_started: '多源检索启动', baseline_discovery_lane_started: '检索通道启动', baseline_discovery_lane_completed: '检索通道完成', baseline_discovery_completed: '多源检索完成', baseline_model_queue_started: '模型调用排队', baseline_model_call_started: '模型调用启动', baseline_model_call_progress: '模型持续执行', baseline_model_call_completed: '模型调用完成', baseline_analysis_started: '结构化分析启动', baseline_analysis_completed: '结构化分析完成', baseline_materialization_progress: '证据材料化进度', baseline_wave_started: '研究波次启动', baseline_wave_completed: '研究波次完成', agent_task_delegated: 'Agent 委派', agent_harness_completed: 'Harness 完成', task_received: '任务接收', tool_call: '工具调用', tool_result: '工具结果', domain_tool_invoked: '领域工具', evidence_assessed: '证据评分', baseline_result: '阶段结果', savepoint: '保存点', baseline_agent_completed: '专业研究完成', baseline_agents_summarized: '基线汇总', packet_admission_evaluated: 'Packet 门控', packet_admission_reused: 'Packet 门控复用', discovery_convergence_completed: '收敛融合', discovery_convergence_reused: '收敛结果复用', winning_model_queue_started: 'S Agent 排队', winning_model_call_started: 'S Agent 启动', winning_model_call_progress: 'S Agent 持续执行', winning_model_call_completed: 'S Agent 模型完成', swarm_planned: 'Agent 群规划', specialist_recruitment_planned: '专用 Agent 招聘', specialist_spawned: '专用 Agent 孵化', specialist_session_started: '独立 CLI 会话启动', specialist_session_completed: '独立 CLI 会话结束', specialist_completed: '专用 Agent 完成', specialist_pruned: '专用 Agent 回收', winning_mission_graph_planned: '动态任务图规划', winning_agent_instance_recruited: '残差触发招聘', winning_agent_instance_ready: '实例依赖就绪', winning_agent_session_started: '独立 CLI 会话启动', winning_agent_waiting: '动态 Agent 持续执行', winning_agent_session_completed: '动态 Agent 会话完成', winning_agent_instance_failed: '实例失败隔离', winning_agent_instance_cancelled: '实例取消回收', winning_s6_card_authoring_limited: 'S6 单卡受限交付', hypothesis_created: '候选假设创建', hypothesis_merged: '候选贡献合并', hypothesis_rejected: '候选假设淘汰', swarm_gate_evaluated: 'Agent 群门控', promotion_candidate_created: 'Agent 晋级候选', winning_subagent_completed: 'S Agent 完成', winning_inner_loop_evaluated: '内循环批判', winning_middle_loop_evaluated: '中循环批判', winning_outer_loop_evaluated: '外循环复核', winning_reasoning_step_completed: 'S Agent 结果固化', winning_stage_completed: 'L1-L3 门控', recall_requested: '定向再调', recall_task_completed: '再调完成', coverage_recomputed_after_recall: '再调覆盖重算', winning_stage_gate_reevaluated: '再调门控重评', capability_image_created: '能力画像', audit_model_fallback: '审计降级', audit_completed: '审计完成', audit_release_reconciled: '最终审计通过', report_model_queue_started: 'Reporter 排队', report_model_call_started: 'Reporter 启动', report_model_call_progress: 'Reporter 持续撰写', report_model_call_completed: 'Reporter 模型完成', report_model_failed: '报告生成失败（未降级）', report_completed: '报告完成'}[value] || value; }
const DYNAMIC_SWARM_EVENT_LABELS = {run_manual_resume_required:'等待人工断点恢复',winning_mission_graph_planned:'动态任务图规划',winning_s3_s4_naming_plan_allocated:'S3/S4 命名分配完成',winning_query_equipment_blueprint_planned:'Query 装备发散蓝图规划',winning_pre_generation_active_angle_selection_fallback:'制胜维度选择回退',winning_pre_generation_angle_portfolio_planned:'S3/S4 制胜维度分配',winning_s3_active_agents_materialized:'S3/S4 开放创作 Agent 已确定',winning_s3_first_pass_self_admission_completed:'S3/S4 创作首稿已完成',winning_s3_s4_candidate_output_bounded:'S3/S4 候选数量边界',winning_s3_s4_creative_iteration_limited:'S3/S4 创作迭代受限',winning_s3_s4_name_authoring_diagnostic:'S3/S4 命名一致性诊断',winning_reasoning_seed_published:'S1/S2 推理种子发布',winning_specialized_seed_authored:'专用 Agent 候选生成',winning_s5_portfolio_frozen:'S5 多样化组合已冻结',winning_s5_parallel_score_started:'S5 并行评分开始',winning_s5_parallel_score_completed:'S5 并行评分完成',winning_s5_contract_gate_rejected:'S5 具体武器合同拒绝',winning_s5_invalid_decision_rejected:'S5 无效判定拒绝',winning_s5_invalid_merge_rejected:'S5 无效合并拒绝',winning_s5_portfolio_fallback_activated:'S5 评分回退启用',winning_full_pool_portfolio_decision:'S5 全池组合判定',winning_full_pool_portfolio_review_repaired:'S5 全池评审修复',winning_full_pool_portfolio_review_rescued:'S5 全池评审救援',winning_full_pool_portfolio_review_completed:'S5 全池评审完成',winning_s5_handoff_quality_gate_completed:'S5 交接质量门完成',winning_semantic_clustering_started:'候选语义聚类开始',winning_semantic_clustering_bounded:'候选语义聚类受限',winning_semantic_clustering_completed:'候选语义聚类完成',winning_semantic_clustering_failed:'候选语义聚类失败',winning_s6_parallel_authoring_configured:'S6 并行画像配置完成',winning_s6_card_authoring_started:'S6 单卡画像开始',winning_s6_card_authoring_retry_started:'S6 单卡画像重试开始',winning_s6_card_authoring_completed:'S6 原创画像完成',winning_s6_card_authoring_reused:'S6 画像复用',winning_s6_card_authoring_limited:'S6 单卡受限回退',winning_s6_card_authoring_rescue_started:'S6 单卡画像救援开始',winning_s6_card_authoring_rescued:'S6 单卡画像救援完成',winning_s6_card_quality_advisory:'S6 单卡质量提示',winning_s6_card_quality_enhancement_limited:'S6 单卡质量增强受限',winning_s6_card_quality_enhancement_completed:'S6 单卡质量增强完成',winning_s6_low_repair_started:'S6 低成本修复开始',winning_s6_low_repair_completed:'S6 低成本修复完成',winning_s6_low_repair_limited:'S6 低成本修复受限',winning_s6_release_gate_evaluated:'S6 画像交付门评估',winning_agent_instance_recruited:'定向质量残差招聘',winning_agent_instance_ready:'实例依赖就绪',winning_agent_instance_retry_scheduled:'动态 Agent 重试排程',winning_agent_session_started:'独立 CLI 会话启动',winning_agent_waiting:'动态 Agent 持续执行',winning_agent_session_completed:'动态 Agent 会话完成',winning_agent_instance_failed:'实例失败隔离',winning_agent_instance_cancelled:'实例取消回收',winning_candidate_branch_created:'候选分支创建',winning_candidate_pre_s5_residual_recorded:'候选进入 S5 前残差记录',winning_candidate_rejected_before_ledger:'候选入账前拒绝',winning_candidate_review_scope_planned:'候选评审范围规划',winning_candidate_summary_quality_advisory:'候选摘要质量提示',winning_candidate_ledger_frozen:'候选账本更新',winning_contribution_queued:'贡献进入 Merge 队列',winning_contribution_rejected:'贡献越界拒绝',winning_contribution_rebase_required:'贡献版本重基',winning_contribution_hypothesis_remapped:'候选贡献 ID 重映射',winning_contribution_merged:'贡献定向合并',winning_portfolio_merge_completed:'S5 多样化装备组合完成',report_quality_gate_limited:'报告质量门未通过（等待修复）',report_delivery_resume_gate_evaluated:'报告门复核'};
const ADDITIONAL_EVENT_LABELS = {baseline_discovery_lane_limited:'检索通道受限',baseline_provider_neutral_source_anchor_fallback:'来源锚点回退',expert_feedback_submitted:'专家审核反馈',expert_feedback_handoff_loaded:'反馈记忆已注入',winning_s3_empty_angle_reallocated:'S3 空维度席位重分配',winning_specialized_seed_empty:'专用 Agent 未生成候选',winning_specialized_seed_recovered:'专用候选恢复',winning_candidate_competition_converged:'候选竞争收敛',winning_quality_judge_recruited:'质量评审实例招募',winning_quality_judge_started:'质量评审启动',winning_quality_judge_assessed:'质量评审单项完成',winning_quality_judge_completed:'质量评审完成',winning_quality_judge_failed:'质量评审失败',winning_quality_repair_planned:'质量残差修复规划',winning_quality_repair_completed:'质量残差修复完成',winning_quality_repair_failed:'质量残差修复失败',audit_delivery_blocked:'审计交付受阻'};
function displayEventLabel(value) { return ADDITIONAL_EVENT_LABELS[value] || DYNAMIC_SWARM_EVENT_LABELS[value] || eventLabel(value); }
function routeLabel(value) { return {new_winning_mechanism: '新制胜机理', traditional_gap: '传统能力缺口', war_case_learning: '局部战争案例', auto: '自动'}[value] || value; }
function statusLabel(value) { return {queued: '已排队', draft: '草稿', planning: '规划中', researching: '研究中', recalling: '再调中', synthesizing: 'S1–S6 综合中', reviewing: '审计中', reporting: '报告生成中', pause_requested: '请求暂停', paused: '已暂停', cancel_requested: '正在停止', cancelled: '已取消', completed: '已完成', failed: '失败', archived: '已归档'}[value] || value; }
const rootElement = document.getElementById('root');
const appRoot = globalThis.__equipmentDeepResearchRoot || createRoot(rootElement);
globalThis.__equipmentDeepResearchRoot = appRoot;
appRoot.render(<App/>);
