import React, {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {Archive, ArrowDown, ArrowUp, BookOpen, BrainCircuit, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, Clock3, Copy, CornerDownRight, FileText, GitBranch, GitCompare, Layers, ListPlus, MessageSquare, Package, Pencil, Plug, Plus, Puzzle, Quote, RefreshCw, RotateCcw, Save, Search, Send, Settings2, Slash, Sparkles, Square, Target, Trash2, X} from 'lucide-react';
import {useOverlay} from '../../ux.jsx';
import {
  normalizeDeepCapabilityCatalog,
  normalizeDeepWorkspaceResources,
  reconcileActiveSkillIds,
  toggleActiveSkillId,
} from './deep-capabilities.js';
import {
  OPEN_DEEP_THINKING_EVENT,
  clearDeepThinkingLocation,
  readDeepThinkingLocation,
  writeDeepThinkingLocation,
} from './open-deep-thinking.js';
import {
  DEEP_STAGES,
  THREAD_NEAR_BOTTOM_PX,
  anchorWelcomeSuggestion,
  branchActiveSkillIds,
  directionFollowUp,
  deepForkIdempotencyKey,
  extractDeepFollowUps,
  filterDeepSlashCommands,
  formatQuotedDeepMessage,
  furthestDeepStage,
  inferProcessRosterMode,
  isTerminalJob,
  isThreadNearBottom,
  matchDeepSlashCommand,
  mergeDeepJobState,
  mergeDeliberationProposals,
  normalizeDeepStage,
  uniqueNamedValues,
  parseQuotedDeepMessage,
  parseDeepTargetIdentity,
  pickDeepSessionForTarget,
  shouldShowJumpToLatest,
  projectDeepAgentActivity,
  projectDeepActivityRoster,
  projectDeepContextUsage,
  projectDeepMemory,
  projectLiveConversationFeedback,
  queuedSteerStatuses,
  resolveDeepHistoryFilterAfterMutation,
  resolveDeepBranchNavigation,
  resolveDeepRequestRole,
  resolveDeepTurnFocus,
  resolveBranchSkillSelection,
} from './deep-thinking-state.js';
import './deep-thinking.css';

/*
 * A bounded expert conversation surface.
 *
 * The server stores only visible messages and structured context references;
 * this component therefore deliberately renders the answer/artifact contract
 * and never exposes a provider trace or hidden chain of thought.  It is kept
 * independent from the large workbench component so capability cards and the
 * global launcher can share exactly the same interaction semantics.
 */

const MAX_MESSAGE_CHARS = 8000;
const CARD_AUTHORING_CONFIRMATION = '确认将当前已收敛方向形成五栏能力卡。请保持装备身份、作用机理与直接军事价值一致，不再扩展新的候选方向。';
const EMPTY_WORKSPACE_RESOURCES = Object.freeze({
  schema_version: 'deep-workspace-resources-v1',
  workspace: {workspace_id: '', identity_fingerprint: ''},
  resources: {config: [], skill: [], plugin: []},
  limits: {max_resource_bytes: 2 * 1024 * 1024, editable_kinds: ['config', 'skill', 'plugin']},
});
const safeText = value => String(value ?? '').trim();
const encodeRun = value => encodeURIComponent(safeText(value));
const newRequestNonce = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const prefersReducedMotion = () => (
  typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches
);
const copyText = async value => {
  const text = safeText(value);
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to execCommand */
  }
  try {
    const node = document.createElement('textarea');
    node.value = text;
    node.setAttribute('readonly', '');
    node.style.position = 'fixed';
    node.style.opacity = '0';
    document.body.appendChild(node);
    node.select();
    const ok = document.execCommand('copy');
    node.remove();
    return ok;
  } catch {
    return false;
  }
};
const resizeComposer = node => {
  if (!node) return;
  node.style.height = 'auto';
  node.style.height = `${Math.min(180, Math.max(54, node.scrollHeight))}px`;
};
const DEFAULT_BRANCH_ID = 'main';
const EMPTY_DEEP_CAPABILITY_CATALOG = normalizeDeepCapabilityCatalog({});
const DEEP_STEER_MODES = [
  {id: 'steer', label: '纳入当前研究', detail: '在最近安全阶段立即纳入', icon: CornerDownRight},
  {id: 'queue', label: '排到下一轮', detail: '当前结果保留，随后自动继续', icon: ListPlus},
  {id: 'interrupt_steer', label: '中断旧方向并纠偏', detail: '保留阶段成果，后续优先执行新意图', icon: RotateCcw},
  {id: 'interrupt_send', label: '中断并作为新问题', detail: '停止旧轮，立即开始独立后续轮', icon: Send},
];
const steerStatusLabel = (status, mode = '') => {
  const normalized = safeText(status).toLowerCase();
  if (normalized === 'applied') return '已纳入当前研究';
  if (normalized === 'parked') return '已排队下一轮';
  if (normalized === 'cancelled') return '已取消';
  if (normalized === 'claimed') return '正在纳入';
  if (normalized === 'queued' || mode === 'queue') return '已接收，等待下一轮';
  return '已接收，等待纳入';
};

const researchMemoryStatusLabel = status => ({
  stable: '稳定',
  exploring: '探索中',
  retained: '保留',
  open: '待检验',
  challenged: '受质疑',
  rejected: '已排除',
}[safeText(status).toLowerCase()] || safeText(status));

const researchActionLabel = action => ({
  diverge: '开放发散',
  challenge: '对抗检验',
  synthesize: '综合归纳',
  deepen: '定向深化',
  research_council: '多席独立探索',
  author_s6: '形成能力画像',
  inspect_memory: '读取记忆',
}[safeText(action).toLowerCase()] || safeText(action));

function ContextUsageChip({usage, memory, branchLabel = '主线', activeSkillCount = 0, open, onToggle}) {
  const dialogRef = useOverlay(Boolean(open), {onEscape: onToggle});
  if (!usage) return null;
  const percent = Math.round((Number(usage.share) || 0) * 100);
  const label = percent > 0 ? `上下文 ${percent}%` : '上下文';
  return (
    <div className={`deep-context-usage${open ? ' open' : ''}${usage.compacted ? ' compacted' : ''}`}>
      <button
        type="button"
        className="deep-context-usage-trigger"
        aria-expanded={open}
        aria-label={`${label}，查看当前窗口与决策记忆`}
        data-testid="deep-context-usage"
        onClick={onToggle}
      >
        <Layers size={12}/>
        <b>{label}</b>
        {usage.compacted && <em>已压缩</em>}
        <svg className="deep-context-usage-ring" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6" />
          <circle cx="8" cy="8" r="6" style={{strokeDasharray: `${Math.max(0, Math.min(100, percent)) * 0.377} 37.7`}} />
        </svg>
      </button>
      {open && createPortal(
        <div className="deep-memory-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onToggle?.(); }}>
          <div className="deep-context-usage-pop deep-memory-drawer" ref={dialogRef} role="dialog" aria-modal="true" aria-label="会话窗口与决策记忆" onMouseDown={event => event.stopPropagation()}>
            <header>
              <span><BookOpen size={13}/><b>会话窗口与决策记忆</b></span>
              <button type="button" autoFocus aria-label="关闭决策记忆" onClick={onToggle}><X size={13}/></button>
            </header>
            <p>当前仅回放最近 {usage.living_turns || 0} 轮；更早的 {usage.archived_turns || 0} 轮压缩为公开决策记忆。</p>
            <ul className="deep-memory-metrics">
              <li><span>可见消息</span><b>{usage.visible_messages || 0}</b></li>
              <li><span>用户约束</span><b>{usage.constraint_count || 0}</b></li>
              <li><span>已裁决方向</span><b>{usage.decision_count || 0}</b></li>
              <li><span>待追问</span><b>{usage.open_question_count || 0}</b></li>
              <li><span>研究前沿</span><b>{usage.frontier_count || 0}</b></li>
              <li><span>关键假设</span><b>{usage.assumption_count || 0}</b></li>
              <li><span>探索视角</span><b>{usage.explored_lens_count || 0}</b></li>
              <li><span>待补缺口</span><b>{usage.research_gap_count || 0}</b></li>
              <li><span>本轮 Skill</span><b>{activeSkillCount}</b></li>
            </ul>
            <div className="deep-memory-scroll">
              <section className="deep-memory-objective">
                <span><Target size={12}/>{branchLabel} · 当前目标</span>
                <p>{memory?.current_objective || usage.current_objective || '尚未形成分支目标。'}</p>
              </section>
              {memory?.summaries?.length > 0 && <section><b>压缩摘要</b><ul>{memory.summaries.map(item => <li key={item}>{item}</li>)}</ul></section>}
              {memory?.last_research_strategy && <section className="deep-memory-strategy"><b>上轮研究策略{memory.research_iteration > 0 ? ` · 第 ${memory.research_iteration} 轮` : ''}</b><p>{[memory.last_research_strategy.mode && researchActionLabel(memory.last_research_strategy.mode), ...(memory.last_research_strategy.actions || []).map(researchActionLabel)].filter((item, index, rows) => item && rows.indexOf(item) === index).join(' → ') || '自适应研究'}</p>{memory.last_research_strategy.rationale && <small>{memory.last_research_strategy.rationale}</small>}</section>}
              {memory?.research_frontier?.length > 0 && <section><b>当前研究前沿</b><div className="deep-memory-directions">{memory.research_frontier.map((item, index) => <article key={`${item.direction}-${index}`}><span>{item.direction || '待命名方向'}{item.status && <em>{researchMemoryStatusLabel(item.status)}</em>}</span>{item.why_promising && <small>{item.why_promising}</small>}{item.next_probe && <small>下一探针：{item.next_probe}</small>}</article>)}</div></section>}
              {memory?.assumption_ledger?.length > 0 && <section><b>关键假设变化</b><div className="deep-memory-assumptions">{memory.assumption_ledger.map((item, index) => <article key={`${item.assumption}-${index}`}><span>{item.assumption}{item.status && <em>{researchMemoryStatusLabel(item.status)}</em>}</span>{(item.direction || item.rationale) && <small>{[item.direction, item.rationale].filter(Boolean).join(' · ')}</small>}</article>)}</div></section>}
              {memory?.explored_lenses?.length > 0 && <section><b>已探索视角</b><div className="deep-memory-tags">{memory.explored_lenses.map(item => <span key={item}>{item}</span>)}</div></section>}
              {memory?.directions?.length > 0 && <section><b>候选方向</b><div className="deep-memory-directions">{memory.directions.map(item => <article key={item.name}><span>{item.name}{item.stable && <em>稳定</em>}</span>{(item.winning_angle || item.equipment_form) && <small>{[item.winning_angle, item.equipment_form].filter(Boolean).join(' · ')}</small>}</article>)}</div></section>}
              {memory?.constraints?.length > 0 && <section><b>用户约束</b><ul>{memory.constraints.map(item => <li key={item}>{item}</li>)}</ul></section>}
              {memory?.decisions?.length > 0 && <section><b>已裁决</b><ul>{memory.decisions.map((item, index) => <li key={`${item.candidate}-${index}`}><strong>{item.candidate || '未命名方向'}</strong>{item.reason ? `：${item.reason}` : ''}</li>)}</ul></section>}
              {memory?.rejected?.length > 0 && <section><b>已排除</b><ul>{memory.rejected.map((item, index) => <li key={`${item.candidate}-${index}`}><strong>{item.candidate || '未命名方向'}</strong>{item.reason ? `：${item.reason}` : ''}</li>)}</ul></section>}
              {memory?.open_questions?.length > 0 && <section><b>未决问题</b><ul>{memory.open_questions.map(item => <li key={item}>{item}</li>)}</ul></section>}
              {memory?.research_gaps?.length > 0 && <section><b>下一轮可补充</b><ul>{memory.research_gaps.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></section>}
              {!memory?.has_memory && <small>完成首轮深研后，这里会沉淀分支目标、约束、裁决与待追问项。</small>}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

const workspaceResourceKindLabel = kind => ({
  config: '配置',
  skill: 'Skill',
  plugin: 'Plugin',
}[safeText(kind)] || '资源');

function DeepCapabilityDrawer({
  catalog,
  loading,
  error,
  selectedSkillIds,
  pluginPendingId,
  workspaceResources = EMPTY_WORKSPACE_RESOURCES,
  workspaceResourceLoading = false,
  workspaceResourceError = '',
  workspaceResourceDraft = null,
  workspaceResourceSaving = false,
  workspacePackageDraft = null,
  workspacePackageSaving = false,
  onToggleSkill,
  onTogglePlugin,
  onReload,
  onReloadWorkspaceResources,
  onOpenWorkspaceResource,
  onCreateWorkspaceResource,
  onChangeWorkspaceResourceDraft,
  onCloseWorkspaceResource,
  onSaveWorkspaceResource,
  onMergeWorkspaceResource,
  onDeleteWorkspaceResource,
  onRestoreWorkspaceResource,
  onOpenWorkspacePluginPackage,
  onChangeWorkspacePackageDraft,
  onPreviewWorkspacePluginPackage,
  onApplyWorkspacePluginPackage,
  onCloseWorkspacePluginPackage,
  onClose,
}) {
  const [query, setQuery] = useState('');
  const dialogRef = useOverlay(true, {onEscape: onClose});
  const normalizedQuery = safeText(query).toLowerCase();
  const selected = new Set(selectedSkillIds);
  const visibleSkills = catalog.skills.filter(skill => {
    if (!normalizedQuery) return true;
    return `${skill.skill_id} ${skill.description} ${(skill.triggers || []).join(' ')}`.toLowerCase().includes(normalizedQuery);
  });
  const declaredMcp = [];
  const seenMcp = new Set();
  [
    ...(catalog.mcp_host?.servers || []),
    ...catalog.mcp_servers,
    ...catalog.plugins.flatMap(plugin => plugin.mcp_servers || []),
  ].forEach(server => {
    if (!server?.server_id || seenMcp.has(server.server_id)) return;
    seenMcp.add(server.server_id);
    declaredMcp.push(server);
  });
  const workspaceResourceRows = ['skill', 'plugin', 'config'].flatMap(kind => (
    (workspaceResources.resources?.[kind] || []).map(name => ({kind, name}))
  ));
  const maxSkills = catalog.limits.max_active_skills;
  const canReload = /读取|加载|无法|失败|not found/i.test(error);
  const mcpStatusLabel = server => ({
    declaration_only: '已声明 · 未接入执行',
    connected: '已接入执行',
    ready: '连接就绪',
    registered: '已连接 · 无可用工具',
    host_configured: '部署已配置 · 按轮连接',
    disabled: '已声明 · 已停用',
  }[safeText(server?.execution_status).toLowerCase()] || '已声明 · 未接入执行');
  return (
    <div className="deep-capability-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose?.(); }}>
      <aside className="deep-capability-drawer" ref={dialogRef} role="dialog" aria-modal="true" aria-label="深研能力目录" onMouseDown={event => event.stopPropagation()}>
        <header>
          <div><span><Puzzle size={14}/>能力目录</span><h3>Plugin 与程序化 Skill</h3></div>
          <button type="button" className="icon-button" aria-label="关闭能力目录" onClick={onClose}><X size={16}/></button>
        </header>
        <div className="deep-capability-drawer-body">
          {error && <div className="deep-capability-error"><CircleAlert size={13}/><span>{error}</span>{canReload && <button type="button" onClick={onReload}><RefreshCw size={12}/>重试</button>}</div>}
          <section className="deep-capability-section">
            <div className="deep-capability-section-title"><span><Package size={13}/><b>Agent Plugin</b></span><em>{catalog.plugins.length}</em></div>
            {catalog.plugins.length ? <div className="deep-plugin-list">{catalog.plugins.map(plugin => (
              <article key={plugin.plugin_id} className={plugin.enabled ? 'enabled' : ''}>
                <div><b>{plugin.display_name || plugin.plugin_id}</b><small>{plugin.category || plugin.plugin_id}</small>{plugin.description && <p>{plugin.description}</p>}</div>
                <label className="deep-plugin-toggle"><input type="checkbox" checked={plugin.enabled} disabled={pluginPendingId === plugin.plugin_id} onChange={event => onTogglePlugin(plugin, event.target.checked)}/><span aria-hidden="true"/>{pluginPendingId === plugin.plugin_id ? '保存中' : plugin.enabled ? '已启用' : '未启用'}</label>
              </article>
            ))}</div> : <p className="deep-capability-empty">当前仅加载内置 Skill。</p>}
          </section>
          <section className="deep-capability-section">
            <div className="deep-capability-section-title"><span><Plug size={13}/><b>MCP 能力</b></span><em>{declaredMcp.length}</em></div>
            {declaredMcp.length ? <div className="deep-mcp-list">{declaredMcp.map(server => <div key={server.server_id}><span><b>{server.server_id}</b><small>{server.transport || '未指定 transport'}{server.source === 'deployment_host' && server.allowed_tools?.length ? ` · ${server.allowed_tools.length} 个白名单工具` : ''}</small></span><em>{mcpStatusLabel(server)}</em></div>)}</div> : <p className="deep-capability-empty">暂无 MCP 声明或部署连接。</p>}
            {catalog.mcp_host?.reload === 'per_turn' && <p className="deep-capability-note">部署配置按轮热重载；进行中的研究继续使用其已租用连接。</p>}
          </section>
          <section className="deep-capability-section deep-workspace-resource-section">
            <div className="deep-capability-section-title">
              <span><FileText size={13}/><b>装备工作区</b></span>
              <em>{workspaceResourceRows.length}</em>
            </div>
            <div className="deep-workspace-resource-actions">
              <button type="button" onClick={() => onCreateWorkspaceResource?.('skill')}><Plus size={12}/>新建 Skill</button>
              <button type="button" onClick={() => onCreateWorkspaceResource?.('plugin')}><Package size={12}/>新建 Plugin</button>
              <button type="button" onClick={() => onCreateWorkspaceResource?.('config')}><Settings2 size={12}/>新建配置</button>
              <button type="button" onClick={onReloadWorkspaceResources} disabled={workspaceResourceLoading}>{workspaceResourceLoading ? <RefreshCw size={12} className="spin"/> : <RefreshCw size={12}/>}刷新</button>
            </div>
            {workspaceResourceError && <p className="deep-capability-error"><CircleAlert size={13}/><span>{workspaceResourceError}</span></p>}
            {workspaceResourceDraft ? (
              <div className="deep-workspace-resource-editor">
                <header>
                  <span><b>{workspaceResourceKindLabel(workspaceResourceDraft.kind)}</b><small>{workspaceResourceDraft.name}</small></span>
                  <button type="button" className="icon-button" aria-label="关闭资源编辑" onClick={onCloseWorkspaceResource}><X size={14}/></button>
                </header>
                <textarea
                  value={workspaceResourceDraft.content || ''}
                  onChange={event => onChangeWorkspaceResourceDraft?.({...workspaceResourceDraft, content: event.target.value, validation: null})}
                  spellCheck={false}
                />
                {workspaceResourceDraft.validation && (
                  <div className={`deep-workspace-resource-validation ${workspaceResourceDraft.validation.valid ? 'valid' : 'invalid'}`}>
                    {workspaceResourceDraft.validation.valid ? <CheckCircle2 size={12}/> : <CircleAlert size={12}/>} 
                    <span>
                      <b>{workspaceResourceDraft.validation.valid ? '能力合同有效' : '能力合同无效'}</b>
                      {(workspaceResourceDraft.validation.errors || workspaceResourceDraft.validation.warnings || []).map(item => <small key={item}>{item}</small>)}
                    </span>
                  </div>
                )}
                {workspaceResourceDraft.mergeResult && (
                  <div className={`deep-workspace-resource-validation ${workspaceResourceDraft.mergeResult.conflicted ? 'invalid' : 'valid'}`}>
                    {workspaceResourceDraft.mergeResult.conflicted ? <CircleAlert size={12}/> : <GitCompare size={12}/>} 
                    <span><b>{workspaceResourceDraft.mergeResult.conflicted ? `合并存在 ${workspaceResourceDraft.mergeResult.conflicts?.length || 0} 处冲突` : '合并预览已生成'}</b><small>{workspaceResourceDraft.mergeResult.conflicted ? '请处理冲突标记后再保存。' : '当前草稿已基于最新服务器版本合并。'}</small></span>
                  </div>
                )}
                {Array.isArray(workspaceResourceDraft.versions) && workspaceResourceDraft.versions.length > 0 && (
                  <details className="deep-workspace-resource-history">
                    <summary>版本历史 · {workspaceResourceDraft.versions.length}</summary>
                    <div>
                      {workspaceResourceDraft.versions.map(version => (
                        <span key={version.version_id}>
                          <b>{version.deleted ? '已删除' : '版本'}</b>
                          <small>{version.created_at ? new Date(version.created_at).toLocaleString('zh-CN', {hour12:false}) : ''}</small>
                          <code>{String(version.sha256 || '').slice(0, 12)}</code>
                          {!version.deleted && version.sha256 !== workspaceResourceDraft.sha256 && <button type="button" onClick={() => onRestoreWorkspaceResource?.(workspaceResourceDraft, version)} disabled={workspaceResourceSaving}>恢复</button>}
                        </span>
                      ))}
                    </div>
                  </details>
                )}
                <footer>
                  {workspaceResourceDraft.kind === 'plugin' && workspaceResourceDraft.name.endsWith('/plugin.json') && <button type="button" disabled={workspaceResourceSaving || workspacePackageSaving} onClick={() => onOpenWorkspacePluginPackage?.(workspaceResourceDraft)}><Package size={12}/>打开包编辑器</button>}
                  {!workspaceResourceDraft.isNew && workspaceResourceDraft.version_id && <button type="button" disabled={workspaceResourceSaving} onClick={() => onMergeWorkspaceResource?.(workspaceResourceDraft)}><GitCompare size={12}/>合并草稿</button>}
                  <button type="button" className="danger" disabled={workspaceResourceSaving || workspaceResourceDraft.isNew} onClick={() => onDeleteWorkspaceResource?.(workspaceResourceDraft)}><Trash2 size={12}/>删除</button>
                  <button type="button" disabled={workspaceResourceSaving} onClick={() => onSaveWorkspaceResource?.(workspaceResourceDraft)}>{workspaceResourceSaving ? <RefreshCw size={12} className="spin"/> : <Save size={12}/>}保存</button>
                </footer>
              </div>
            ) : workspaceResourceLoading && !workspaceResourceRows.length ? (
              <p className="deep-capability-empty"><RefreshCw size={13} className="spin"/>读取工作区资源…</p>
            ) : workspaceResourceRows.length ? (
              <div className="deep-workspace-resource-list">
                {workspaceResourceRows.map(item => (
                  <button type="button" key={`${item.kind}:${item.name}`} onClick={() => onOpenWorkspaceResource?.(item.kind, item.name)}>
                    <span>{workspaceResourceKindLabel(item.kind)}</span>
                    <b>{item.name}</b>
                  </button>
                ))}
              </div>
            ) : (
              <p className="deep-capability-empty">当前装备工作区暂无可编辑资源。</p>
            )}
            {workspacePackageDraft && (
              <div className="deep-workspace-resource-editor deep-workspace-package-editor">
                <header>
                  <span><b>Plugin 包编辑器</b><small>{workspacePackageDraft.pluginId}</small></span>
                  <button type="button" className="icon-button" aria-label="关闭 Plugin 包编辑器" onClick={onCloseWorkspacePluginPackage}><X size={14}/></button>
                </header>
                <p className="deep-capability-note">包级预览会同时处理 manifest、Skill、MCP 声明和删除项；提交前会重新检查每个文件的版本。</p>
                {Object.entries(workspacePackageDraft.files || {}).map(([name, content]) => (
                  <label className="deep-workspace-package-file" key={name}>
                    <span><FileText size={12}/><b>{name}</b><button type="button" className="icon-button" aria-label={`从包中删除 ${name}`} onClick={() => { const files = {...workspacePackageDraft.files}; delete files[name]; onChangeWorkspacePackageDraft?.({...workspacePackageDraft, files, mergeResult: null}); }}><Trash2 size={11}/></button></span>
                    <textarea value={content} onChange={event => onChangeWorkspacePackageDraft?.({...workspacePackageDraft, files: {...workspacePackageDraft.files, [name]: event.target.value}, mergeResult: null})} spellCheck={false}/>
                  </label>
                ))}
                {workspacePackageDraft.mergeResult && (
                  <div className={`deep-workspace-resource-validation ${workspacePackageDraft.mergeResult.conflicted ? 'invalid' : 'valid'}`}>
                    {workspacePackageDraft.mergeResult.conflicted ? <CircleAlert size={12}/> : <CheckCircle2 size={12}/>}<span><b>{workspacePackageDraft.mergeResult.conflicted ? `包级合并存在 ${workspacePackageDraft.mergeResult.files?.filter(item => item.conflicted).length || 0} 个冲突文件` : workspacePackageDraft.mergeResult.applied ? 'Plugin 包已原子提交' : '包级合并可提交'}</b><small>{workspacePackageDraft.mergeResult.conflicted ? '处理冲突后重新预览。' : '管理员提交会在 Workspace 锁内批量写入。'}</small></span>
                  </div>
                )}
                <footer>
                  <button type="button" disabled={workspacePackageSaving} onClick={() => onPreviewWorkspacePluginPackage?.(workspacePackageDraft)}><GitCompare size={12}/>预览包合并</button>
                  <button type="button" disabled={workspacePackageSaving || workspacePackageDraft.mergeResult?.conflicted || !workspacePackageDraft.mergeResult?.atomic_ready} onClick={() => onApplyWorkspacePluginPackage?.(workspacePackageDraft)}>{workspacePackageSaving ? <RefreshCw size={12} className="spin"/> : <Save size={12}/>}管理员原子提交</button>
                </footer>
              </div>
            )}
          </section>
          <section className="deep-capability-section deep-skill-catalog">
            <div className="deep-capability-section-title"><span><BookOpen size={13}/><b>程序化 Skill</b></span><em>{selectedSkillIds.length}/{maxSkills}</em></div>
            <label className="deep-capability-search"><Search size={13}/><input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索 Skill" aria-label="搜索 Skill"/></label>
            {loading && !catalog.skills.length ? <p className="deep-capability-empty"><RefreshCw size={13} className="spin"/>读取能力目录…</p> : <div className="deep-skill-list">{visibleSkills.map(skill => (
              <article key={skill.skill_id} className={selected.has(skill.skill_id) ? 'selected' : ''}>
                <label>
                  <input type="checkbox" checked={selected.has(skill.skill_id)} onChange={event => onToggleSkill(skill.skill_id, event.target.checked)}/>
                  <span><b>{skill.skill_id}</b><small>{skill.source === 'workspace' ? '装备工作区' : skill.source === 'plugin' ? `Plugin · ${skill.plugin_id}` : '内置能力'}{skill.recommended ? ' · 推荐' : ''}</small></span>
                </label>
                {skill.description && <p>{skill.description}</p>}
                {(skill.steps.length > 0 || skill.allowed_tools.length > 0 || skill.quality_gates.length > 0 || skill.required_artifacts.length > 0 || skill.stop_conditions.length > 0) && <details><summary>程序合同</summary><dl>{skill.steps.length > 0 && <><dt>步骤</dt><dd>{skill.steps.join(' → ')}</dd></>}{skill.allowed_tools.length > 0 && <><dt>工具边界</dt><dd>{skill.allowed_tools.join(' · ')}</dd></>}{skill.required_artifacts.length > 0 && <><dt>必需产物</dt><dd>{skill.required_artifacts.join(' · ')}</dd></>}{skill.quality_gates.length > 0 && <><dt>质量门</dt><dd>{skill.quality_gates.join('；')}</dd></>}{skill.stop_conditions.length > 0 && <><dt>停止条件</dt><dd>{skill.stop_conditions.join('；')}</dd></>}</dl></details>}
              </article>
            ))}{!visibleSkills.length && !loading && <p className="deep-capability-empty">没有匹配的 Skill。</p>}</div>}
          </section>
        </div>
        <footer><span>已选择 {selectedSkillIds.length} / {maxSkills}</span><button type="button" onClick={onClose}>完成</button></footer>
      </aside>
    </div>
  );
}

const branchMessagePath = (messages = [], branchId = DEFAULT_BRANCH_ID, branches = []) => {
  const rows = messages.filter(item => item && typeof item === 'object');
  const wanted = safeText(branchId) || DEFAULT_BRANCH_ID;
  if (wanted === DEFAULT_BRANCH_ID) {
    return rows.filter(item => (safeText(item.branch_id) || DEFAULT_BRANCH_ID) === DEFAULT_BRANCH_ID);
  }
  const branchRows = rows.filter(item => (safeText(item.branch_id) || DEFAULT_BRANCH_ID) === wanted);
  const branch = branches.find(item => safeText(item?.branch_id) === wanted);
  const byId = new Map(rows.map(item => [safeText(item.message_id), item]).filter(([id]) => id));
  let current = branchRows[branchRows.length - 1] || byId.get(safeText(branch?.forked_from_message_id));
  if (!current) return rows.filter(item => (safeText(item.branch_id) || DEFAULT_BRANCH_ID) === DEFAULT_BRANCH_ID);
  const path = [];
  const seen = new Set();
  while (current) {
    const messageId = safeText(current.message_id);
    if (messageId && seen.has(messageId)) break;
    if (messageId) seen.add(messageId);
    path.push(current);
    current = byId.get(safeText(current.parent_message_id));
  }
  path.reverse();
  const firstIndex = rows.indexOf(path[0]);
  const legacyPrefix = firstIndex > 0
    ? rows.slice(0, firstIndex).filter(item => (
      (safeText(item.branch_id) || DEFAULT_BRANCH_ID) === DEFAULT_BRANCH_ID
      && !seen.has(safeText(item.message_id))
    ))
    : [];
  return [...legacyPrefix, ...path];
};
const sessionKindLabel = kind => ({
  'deep-thinking': '深度思考 Agent',
  'capability-followup': '单装备深研',
  'reference-research': '参考武器深研',
}[safeText(kind).toLowerCase().replace(/_/g, '-')] || '专家会话');
const sessionStatusLabel = status => ({active: '可继续', running: '思考中', queued: '待处理', completed: '已完成', failed: '失败', cancelled: '已取消', partial: '部分完成', blocked: '已阻塞', rejected: '已驳回', archived: '已归档'}[status] || status || '可继续');
const jobStatusLabel = status => ({queued: '待处理', running: '思考中', partial: '部分完成', completed: '已完成', failed: '失败', blocked: '已阻塞', cancelled: '已取消', rejected: '已驳回'}[String(status || '').toLowerCase()] || String(status || '思考中'));
const friendlyDeepJobError = value => {
  const text = safeText(value);
  if (!text) return '';
  if (/模型提供方不可用|provider.?unavailable|api[_ ]?key|authentication/i.test(text)) {
    return '模型提供方暂不可用，已返回可见上下文分析；可点重试继续本轮问题。';
  }
  if (/Provider(?:Request|Retryable|Capacity|Authentication)?Error|timed?\s*out|timeout/i.test(text)) {
    return '深研服务暂时中断，已保留各 Agent 的阶段成果；可重试当前问题。';
  }
  return text;
};
const isQualityAdvisoryText = value => /(?:证据|发布|质量|evidence|publish).{0,12}(?:门|核验|检查|gate)|(?:门|核验|检查|gate).{0,12}(?:证据|发布|质量|evidence|publish)/i.test(safeText(value));
const normalizeCapabilityVersionStatus = value => {
  const status = safeText(value).toLowerCase().replace(/-/g, '_');
  return ({
    approved: 'verified',
    accepted: 'verified',
    pending: 'pending_verification',
    unverified: 'pending_verification',
    rollback: 'rolled_back',
    rolledback: 'rolled_back',
  })[status] || status;
};
const activeStageLabel = stage => {
  const normalized = normalizeDeepStage(stage);
  return DEEP_STAGES.find(([key]) => key === normalized)?.[1] || stage || '阶段';
};
const eventDelta = item => (item?.delta && typeof item.delta === 'object' ? item.delta : {});
const eventRole = item => safeText(eventDelta(item).role || item?.role);
const eventAxis = item => safeText(eventDelta(item).axis || item?.axis);
const eventAgentId = item => safeText(eventDelta(item).agent_id || item?.agent_id);
const eventProposalNames = item => {
  const names = eventDelta(item).proposal_names || item?.proposal_names;
  return Array.isArray(names) ? names.map(safeText).filter(Boolean).slice(0, 3) : [];
};
const eventProposalBriefs = item => {
  const briefs = eventDelta(item).proposal_briefs || item?.proposal_briefs;
  if (!Array.isArray(briefs)) return [];
  return briefs
    .filter(brief => brief && typeof brief === 'object' && safeText(brief.name))
    .filter(brief => {
      const name = safeText(brief.name);
      return name.length >= 2 && name.length <= 48;
    })
    .slice(0, 3);
};
const eventRound = item => safeText(eventDelta(item).round || item?.round).toLowerCase();
const eventCompletedCount = item => {
  const value = Number(eventDelta(item).completed_count || item?.completed_count);
  return Number.isFinite(value) && value > 0 ? value : 0;
};
const eventTotalCount = item => {
  const value = Number(eventDelta(item).total_count || item?.total_count);
  return Number.isFinite(value) && value > 0 ? value : 0;
};
const isColumnAuthorEvent = item => /第\s*\d+\s*栏/.test(eventRole(item)) || eventRound(item) === 'authoring';
const isParallelCouncilEvent = item => Boolean(
  eventDelta(item).parallel
  || eventDelta(item).parallel_group
  || item?.parallel
  || item?.parallel_group
) && !isColumnAuthorEvent(item);
const visibleProgress = (events = [], activeJob = null, sending = false) => {
  const values = [Number(activeJob?.progress) || 0];
  events.forEach(item => {
    const value = Number(item?.progress);
    if (Number.isFinite(value) && value > 0) values.push(value);
  });
  const progress = Math.max(0, ...values);
  if (sending) return Math.max(0.03, Math.min(1, progress || 0.04));
  return Math.max(0, Math.min(1, progress));
};
const stageStripState = (stageEvents = [], activeJob = null) => {
  const jobStage = normalizeDeepStage(activeJob?.stage);
  const jobStatus = safeText(activeJob?.status).toLowerCase();
  const running = Boolean(activeJob && !isTerminalJob(activeJob));
  const order = DEEP_STAGES.map(([key]) => key);
  const latestByStage = {};
  stageEvents.forEach(event => {
    if (['deep_agent_started', 'deep_agent_progress', 'deep_agent_completed', 'deep_agent_failed'].includes(safeText(event?.event_type))) return;
    const key = normalizeDeepStage(event?.stage);
    if (!order.includes(key)) return;
    latestByStage[key] = event;
  });
  return DEEP_STAGES.map(([key, label]) => {
    const event = latestByStage[key];
    const eventStatus = safeText(event?.status).toLowerCase();
    const eventKind = safeText(eventDelta(event).kind);
    let status = 'idle';
    if (['failed', 'blocked'].includes(eventStatus) || (jobStatus === 'failed' && jobStage === key && eventStatus !== 'completed' && eventKind !== 'answer')) status = 'failed';
    else if (eventStatus === 'partial' && eventKind !== 'answer') status = 'partial';
    else if (jobStatus === 'partial' && jobStage === key && eventStatus !== 'completed' && eventKind !== 'answer') status = 'partial';
    else if (running && jobStage === key && eventStatus !== 'completed' && eventKind !== 'answer') status = 'running';
    else if ((eventStatus === 'completed' || eventKind === 'answer') || (!running && event)) status = 'completed';
    return {key, label, status};
  });
};
const legacyChildRunLabel = job => {
  const childRunId = safeText(job?.child_run_id);
  if (!childRunId) return '';
  // New contextual dialogue jobs never create a child Run.  If an older
  // durable row still carries one, make the compatibility nature explicit
  // instead of presenting it as part of the current single-equipment flow.
  return '历史兼容流程（当前对话不创建子运行）';
};

// Keep the conversation surface explicit about what the current turn has
// actually produced.  Stage progress alone can look "complete" while the
// dialogue has only emitted an exploratory summary, so this status is derived
// from the visible artifact/version contract and never from hidden provider
// state.
function deepResultState({activeJob, session, artifacts = [], versions = [], stageEvents = [], sending = false, lastAnswer = null, jobError = ''} = {}) {
  const jobStatus = safeText(activeJob?.status).toLowerCase();
  const sessionStatus = safeText(session?.status).toLowerCase();
  const latestStage = [...stageEvents].reverse().find(event => safeText(event?.stage));
  const artifactRows = artifacts
    .map(item => item?.payload && typeof item.payload === 'object' ? item.payload : item)
    .filter(item => item && typeof item === 'object');
  // ``capabilityVersions`` is card-scoped and may include the immutable
  // formal v1 baseline.  Do not let an unrelated/formal row make a global
  // conversation look verified.  Restrict status inference to the artifact's
  // own lineage (or the session's explicit hypothesis) and only use non-formal
  // rows when the session has a binding but no materialized artifact yet.
  const sessionHypothesis = safeText(session?.hypothesis_id);
  const sessionBinding = safeText(session?.card_binding_id);
  const relevantVersions = versions.filter(version => {
    const versionId = safeText(version?.version_id);
    const versionHypothesis = safeText(version?.hypothesis_id);
    const versionBinding = safeText(version?.card_binding_id);
    const versionStatus = safeText(version?.status).toLowerCase();
    const formalBaseline = ['formal', 'baseline'].includes(versionStatus);
    const matchesArtifact = artifactRows.some(artifact => (
      (safeText(artifact?.version_id) && safeText(artifact?.version_id) === versionId)
      || (safeText(artifact?.hypothesis_id) && safeText(artifact?.hypothesis_id) === versionHypothesis)
      || (safeText(artifact?.capability_id) && safeText(artifact?.capability_id) === safeText(version?.snapshot?.capability_id))
    ));
    // Formal/baseline rows are immutable context for a follow-up, never a
    // result of the current deep turn.  Exclude them even when they share a
    // hypothesis/capability identity with a legacy artifact or session.
    if (formalBaseline) return false;
    if (matchesArtifact) return true;
    if (sessionHypothesis && versionHypothesis) return sessionHypothesis === versionHypothesis;
    return Boolean(sessionBinding && versionBinding === sessionBinding);
  });
  const versionStatuses = [
    ...relevantVersions.map(item => normalizeCapabilityVersionStatus(item?.status)),
    // SQL is authoritative when present, but a session can briefly expose a
    // freshly persisted artifact before the version list refresh completes.
    // Include only non-formal artifact statuses as a bounded compatibility
    // bridge; an immutable formal baseline must never mark this turn verified.
    ...artifactRows
      .map(item => normalizeCapabilityVersionStatus(item?.version_status || item?.verification_status || item?.status))
      .filter(status => status && !['formal', 'baseline'].includes(status)),
  ].filter(Boolean);
  // A formal baseline is the immutable input to a follow-up, not a result of
  // the current turn.  Only an explicitly reviewed deep version should make
  // this panel claim that the newly produced result is verified.
  const hasVerifiedVersion = versionStatuses.some(status => ['verified', 'approved', 'accepted'].includes(status));
  const hasPendingVersion = versionStatuses.some(status => ['pending', 'pending_verification', 'unverified'].includes(status));
  const hasMergedArtifact = artifactRows.some(item => ['merged', 'merged_pending_verification', 'accepted'].includes(safeText(item?.merge_status || item?.status).toLowerCase()));
  const hasCandidate = artifactRows.length > 0;
  const hasVisibleStageSummary = stageEvents.some(event => (
    safeText(event?.delta?.text) || safeText(event?.text) || safeText(event?.summary)
  ));
  const finalization = safeText(lastAnswer?.finalization_status || lastAnswer?.orchestration?.finalization_status).toLowerCase();
  const visibleMessages = Array.isArray(session?.messages) ? session.messages : [];
  const latestMessage = visibleMessages[visibleMessages.length - 1];
  const awaitingConfirmation = (
    safeText(latestMessage?.role).toLowerCase() === 'assistant'
    && /#{1,6}\s*是否形成能力卡/.test(safeText(latestMessage?.content))
  );
  const researchAssessment = lastAnswer?.research_assessment && typeof lastAnswer.research_assessment === 'object'
    ? lastAnswer.research_assessment
    : null;
  const qualityGate = lastAnswer?.quality_gate && typeof lastAnswer.quality_gate === 'object' ? lastAnswer.quality_gate : null;
  const researchGaps = (
    Array.isArray(researchAssessment?.research_gaps)
      ? researchAssessment.research_gaps
      : Array.isArray(lastAnswer?.research_gaps)
        ? lastAnswer.research_gaps
        : Array.isArray(qualityGate?.block_reasons)
          ? qualityGate.block_reasons
          : []
  ).map(safeText).filter(Boolean);
  const analysisOnlyFromEvents = stageEvents.some(event => {
    const text = safeText(event?.delta?.text || event?.text || event?.summary);
    return text.includes('未写入正式') || text.includes('发布质量门未通过');
  });
  const researchComplete = researchAssessment?.research_complete ?? lastAnswer?.research_complete;
  const qualityAdvisory = researchComplete === false
    || finalization === 'analysis_only'
    || qualityGate?.publishable === false
    || analysisOnlyFromEvents
    || isQualityAdvisoryText(activeJob?.error || jobError);
  const terminalFailure = (
    ['failed', 'blocked', 'partial', 'cancelled', 'rejected'].includes(jobStatus)
    || ['failed', 'blocked', 'partial', 'cancelled'].includes(sessionStatus)
  );
  const legacyQualityOnlyBlock = (
    (jobStatus === 'blocked' || sessionStatus === 'blocked')
    && isQualityAdvisoryText(activeJob?.error || jobError)
  );

  if (sending || (activeJob && !isTerminalJob(activeJob))) {
    const stage = safeText(activeJob?.stage || latestStage?.stage);
    const rosterMode = inferProcessRosterMode(stageEvents, {sending: true, activeStage: stage});
    const detailByMode = {
      deepen: stage ? `当前阶段：${activeStageLabel(stage)}。内部沿多维度多角度发散后，再收敛到你的问题。` : '正在内部多维发散并收敛到本轮问题。',
      card: stage ? `当前阶段：${activeStageLabel(stage)}。沿已收敛方向写入五栏能力画像。` : '正在沿已收敛方向成卡。',
      command: stage ? `当前阶段：${activeStageLabel(stage)}。正在读取决策记忆或命令。` : '正在处理命令。',
      pending: '问题已进入创新舱，正在选择本轮研究动作。',
      explore: stage ? `当前活动：${activeStageLabel(stage)}。专家将根据问题动态选择角度并持续回传。` : '正在围绕当前装备持续展开高价值探索。',
    };
    return {
      tone: 'running',
      title: rosterMode === 'deepen' ? '创新舱正在内部多维发散' : rosterMode === 'card' ? '创新舱正在成卡' : '创新舱深度研究进行中',
      detail: detailByMode[rosterMode] || detailByMode.explore,
    };
  }
  if (terminalFailure && !legacyQualityOnlyBlock) {
    const cancelled = jobStatus === 'cancelled' || sessionStatus === 'cancelled';
    return {
      tone: 'partial',
      title: cancelled ? '任务已取消 · 阶段成果已保留' : '阶段成果已保留',
      detail: friendlyDeepJobError(activeJob?.error) || (cancelled ? '任务已取消；可见分析、证据和草稿仍可继续查看或重试。' : '本轮未完整发布；可见分析、证据和草稿仍可继续查看或重试。'),
    };
  }
  if (hasVerifiedVersion) {
    return {
      tone: 'verified',
      title: '成果已固定 · 已核验',
      detail: '版本链已通过核验；原始正式卡保持不可变。',
    };
  }
  if (hasMergedArtifact || hasPendingVersion) {
    return {
      tone: 'pending',
      title: '成果已固定到能力画像页',
      detail: '新质装备五栏画像已写入当前任务的能力画像导航页，并保留为待评议版本。',
    };
  }
  if (hasCandidate) {
    return {
      tone: 'candidate',
      title: '已形成候选成果',
      detail: '候选卡已生成，可继续追问、评议或固定到能力画像。',
    };
  }
  if (finalization === 'awaiting_user_confirmation' || awaitingConfirmation) {
    return {
      tone: 'summary',
      title: '已发现值得继续深挖的方向',
      detail: '专家已完成价值判断；继续追问不会自动成卡，只有你确认后才会形成五栏能力画像。',
    };
  }
  if (finalization === 'research_complete' || researchComplete === true) {
    return {
      tone: 'summary',
      title: '本轮探索已完成',
      detail: researchGaps.length
        ? `已保留当前成果；下一轮可优先补充：${researchGaps.slice(0, 2).join('；')}`
        : '候选方向、复核意见与决策记忆已保留，可继续追问或切换分支。',
    };
  }
  if (qualityAdvisory) {
    return {
      tone: 'summary',
      title: '本轮探索已形成可继续成果',
      detail: researchGaps.length
        ? `已保留当前方向；下一轮可优先补充：${researchGaps.slice(0, 2).join('；')}`
        : '已保留当前分析与候选方向，可继续追问、切换分支或形成能力画像。',
    };
  }
  if (hasVisibleStageSummary || sessionStatus === 'completed' || jobStatus === 'completed') {
    return {
      tone: 'summary',
      title: '已形成可见发散摘要',
      detail: '当前轮次尚未形成稳定能力卡；可继续追问或提出新的发散方向。',
    };
  }
  return {
    tone: 'idle',
    title: '等待深度思考',
    detail: '发送问题后，这里会按实际研究活动持续回传候选方向、复核意见与能力画像。',
  };
}

const splitQueryDisplay = (value) => {
  const full = safeText(value);
  if (!full) return {topic: '未命名 Query 任务', background: '', backgroundPreview: '', full: '', hasBackground: false};
  const parts = full.split(/\n+/).map(part => part.replace(/\s+/g, ' ').trim()).filter(Boolean);
  const topic = parts[0] || '未命名 Query 任务';
  const background = parts.slice(1).join(' ');
  const backgroundPreview = background.length > 42 ? `${background.slice(0, 42)}…` : background;
  return {topic, background, backgroundPreview, full, hasBackground: Boolean(background)};
};
const sessionRunId = item => safeText(item?.parent_run_id || item?.run_id);
const groupSessions = (groups = [], {archived = false} = {}) => (
  (Array.isArray(groups) ? groups : [])
    .map(group => {
      const sessions = (Array.isArray(group?.sessions) ? group.sessions : [])
        .filter(item => {
          const status = safeText(item?.status).toLowerCase();
          return archived ? status === 'archived' : status !== 'archived';
        });
      if (!sessions.length) return null;
      return {
        ...group,
        sessions,
        session_count: sessions.length,
      };
    })
    .filter(Boolean)
);
const artifactId = artifact => safeText(artifact?.artifact_id || artifact?.capability_id || artifact?.hypothesis_id);
const MESSAGE_STATUS_RANK = {
  queued: 0,
  accepted: 1,
  claimed: 2,
  applied: 3,
  parked: 3,
  cancelled: 3,
  completed: 3,
};
const optimisticMessageMatch = (left, right) => {
  if (!left?.pending) return false;
  if (safeText(left.role).toLowerCase() !== safeText(right?.role).toLowerCase()) return false;
  if (safeText(left.content) !== safeText(right?.content)) return false;
  if ((safeText(left.branch_id) || DEFAULT_BRANCH_ID) !== (safeText(right?.branch_id) || DEFAULT_BRANCH_ID)) return false;
  const leftParent = safeText(left.parent_message_id);
  const rightParent = safeText(right?.parent_message_id);
  if (leftParent && rightParent && leftParent !== rightParent) return false;
  const leftTime = Date.parse(left.created_at || '') || 0;
  const rightTime = Date.parse(right?.created_at || '') || 0;
  return !leftTime || !rightTime || Math.abs(rightTime - leftTime) <= 120000;
};
const mergeTranscriptMessage = (previous, incoming) => {
  const previousStatus = safeText(previous?.status).toLowerCase();
  const incomingStatus = safeText(incoming?.status).toLowerCase();
  const keepPreviousStatus = (
    (MESSAGE_STATUS_RANK[previousStatus] ?? -1)
    > (MESSAGE_STATUS_RANK[incomingStatus] ?? -1)
  );
  const fromServer = Boolean(
    safeText(incoming?.message_id)
    && !safeText(incoming?.message_id).startsWith('local-')
  );
  return {
    ...previous,
    ...incoming,
    status: keepPreviousStatus ? previous.status : (incoming.status || previous.status),
    pending: fromServer ? false : Boolean(incoming?.pending ?? previous?.pending),
  };
};
const mergeTranscriptMessages = (session, extras = []) => {
  if (!session || typeof session !== 'object') {
    if (!extras.length) return session;
    return {messages: extras};
  }
  const current = Array.isArray(session.messages) ? session.messages : [];
  const incoming = extras.filter(item => item && typeof item === 'object' && safeText(item.content));
  if (!incoming.length) return session;
  const next = [...current];
  incoming.forEach(item => {
    const id = safeText(item.message_id);
    const existingIndex = next.findIndex(row => {
      if (id && safeText(row?.message_id) === id) return true;
      return optimisticMessageMatch(row, item);
    });
    if (existingIndex >= 0) {
      const previous = next[existingIndex];
      next[existingIndex] = mergeTranscriptMessage(previous, item);
      return;
    }
    next.push(item);
  });
  return {...session, messages: next};
};
const applySessionSnapshot = (current, incoming, extras = []) => {
  const base = incoming && typeof incoming === 'object' ? incoming : current;
  if (!base) return mergeTranscriptMessages(current, extras);
  const currentMessages = Array.isArray(current?.messages) ? current.messages : [];
  const serverMessages = Array.isArray(base.messages) ? base.messages : [];
  return mergeTranscriptMessages(
    {...current, ...base, messages: currentMessages},
    [...serverMessages, ...extras],
  );
};
const localStageEvent = ({stage, status, text, progress = 0}) => ({
  stage,
  status,
  progress,
  delta: {kind: 'summary', text},
  local: true,
});
const PORTRAIT_MODULE_DEFS = [
  ['overview', '概述'],
  ['technology_implementation', '装备与技术实现'],
  ['operational_process', '关键作战流程'],
  ['capability_effects', '能力与作战效果'],
  ['winning_logic', '制胜逻辑机理'],
];
const PORTRAIT_LABEL_ALIASES = {
  概述: '概述',
  装备与技术实现: '装备与技术实现',
  关键作战流程: '关键作战流程',
  形成能力与作战效果: '能力与作战效果',
  能力与作战效果: '能力与作战效果',
  制胜逻辑机理与对抗边界: '制胜逻辑机理',
  制胜逻辑机理: '制胜逻辑机理',
  制胜逻辑: '制胜逻辑机理',
};

function parseMarkdownSections(content) {
  const text = safeText(content);
  if (!text || !/^#{1,3}\s+/m.test(text)) return [];
  return text.split(/^#{1,3}\s+/m).filter(Boolean).map(part => {
    const newline = part.indexOf('\n');
    if (newline < 0) return {title: part.trim(), text: ''};
    return {title: part.slice(0, newline).trim(), text: part.slice(newline + 1).trim()};
  }).filter(item => item.title);
}

function extractPortraitModules(source = {}) {
  const modules = [];
  const push = (label, text) => {
    const body = safeText(text);
    if (!label || !body) return;
    if (modules.some(item => item.label === label)) return;
    modules.push({label, text: body});
  };
  const draft = source.capability_card_draft && typeof source.capability_card_draft === 'object'
    ? source.capability_card_draft
    : source;
  PORTRAIT_MODULE_DEFS.forEach(([key, label]) => {
    push(label, draft?.[key] || source?.[key]);
  });
  if (modules.length >= 3) return modules;

  const raw = safeText(
    source.deep_capability_portrait
    || source.capability_image
    || source.summary
    || source.overview
    || source.text
    || (typeof source === 'string' ? source : ''),
  );
  if (!raw) return modules;

  const headingPattern = /(?:^|\n)\s*(?:#{1,4}\s*)?(概述|装备与技术实现|关键作战流程|形成能力与作战效果|能力与作战效果|制胜逻辑机理与对抗边界|制胜逻辑机理|制胜逻辑)\s*[:：]?\s*/g;
  const matches = [...raw.matchAll(headingPattern)];
  if (matches.length) {
    matches.forEach((match, index) => {
      const label = PORTRAIT_LABEL_ALIASES[match[1]] || match[1];
      const start = match.index + match[0].length;
      const end = matches[index + 1]?.index ?? raw.length;
      push(label, raw.slice(start, end));
    });
    return modules;
  }

  const colonPattern = /(概述|装备与技术实现|关键作战流程|形成能力与作战效果|能力与作战效果|制胜逻辑机理与对抗边界|制胜逻辑机理|制胜逻辑)\s*[：:]/g;
  const colonMatches = [...raw.matchAll(colonPattern)];
  if (colonMatches.length) {
    colonMatches.forEach((match, index) => {
      const label = PORTRAIT_LABEL_ALIASES[match[1]] || match[1];
      const start = match.index + match[0].length;
      const end = colonMatches[index + 1]?.index ?? raw.length;
      push(label, raw.slice(start, end));
    });
  }
  return modules;
}

function looksLikeCompleteAnswerDump(text) {
  const value = safeText(text);
  return value.length > 360 && /###\s*本轮完整结果/.test(value);
}

function AssistantMarkdown({children, className = ''}) {
  const content = safeText(children);
  if (!content) return null;
  return (
    <div className={`deep-md ${className}`.trim()}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

function PortraitViewer({portrait, onClose}) {
  const dialogRef = useOverlay(Boolean(portrait), {onEscape: onClose});
  if (!portrait) return null;
  const modules = Array.isArray(portrait.modules) ? portrait.modules.filter(item => safeText(item?.text)) : [];
  return (
    <div className="deep-portrait-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose?.(); }} role="presentation">
      <section className="deep-portrait-viewer" ref={dialogRef} role="dialog" aria-modal="true" aria-label="五栏能力画像" onMouseDown={event => event.stopPropagation()}>
        <header>
          <div>
            <span><Sparkles size={14}/>五栏能力画像</span>
            <h3>{safeText(portrait.name) || '未命名能力画像'}</h3>
            {portrait.meta && <small>{portrait.meta}</small>}
          </div>
          <button type="button" className="icon-button" autoFocus aria-label="关闭能力画像" onClick={() => onClose?.()}><X size={16}/></button>
        </header>
        {modules.length ? (
          <div className="deep-portrait-grid">
            {modules.map(item => (
              <article key={item.label}>
                <b>{item.label}</b>
                <AssistantMarkdown>{item.text}</AssistantMarkdown>
              </article>
            ))}
          </div>
        ) : (
          <div className="deep-portrait-fallback">
            <AssistantMarkdown>{portrait.fallback || '暂无五栏能力画像正文。'}</AssistantMarkdown>
          </div>
        )}
      </section>
    </div>
  );
}

function CompleteAnswerView({content, onOpenPortrait, portraitName = ''}) {
  const sections = parseMarkdownSections(content);
  if (!sections.length) {
    return <AssistantMarkdown className="deep-answer-fallback">{content || '正在整理可见回答…'}</AssistantMarkdown>;
  }
  return (
    <div className="deep-answer-sections">
      {sections.map(section => {
        const isPortrait = section.title.includes('五栏能力画像');
        if (isPortrait) {
          const modules = extractPortraitModules({text: section.text});
          return (
            <section key={section.title} className="deep-answer-section deep-answer-portrait-teaser">
              <div className="deep-answer-section-head">
                <h3>{section.title}</h3>
                <button
                  type="button"
                  className="deep-portrait-open"
                  onClick={() => onOpenPortrait?.({
                    name: portraitName || '本轮五栏能力画像',
                    modules,
                    fallback: section.text,
                    meta: '对话内预览 · 点击查看完整五栏',
                  })}
                >
                  <Sparkles size={13}/>点击查看完整画像
                </button>
              </div>
              <p className="deep-answer-portrait-hint">已生成可点击的美观五栏能力画像，可在对话窗口直接展开查看。</p>
              {modules.length > 0 && (
                <div className="deep-portrait-mini">
                  {modules.slice(0, 5).map(item => (
                    <button
                      type="button"
                      key={item.label}
                      onClick={() => onOpenPortrait?.({
                        name: portraitName || '本轮五栏能力画像',
                        modules,
                        fallback: section.text,
                        meta: '对话内预览',
                      })}
                    >
                      <b>{item.label}</b>
                      <span>{safeText(item.text).slice(0, 72)}{safeText(item.text).length > 72 ? '…' : ''}</span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          );
        }
        return (
          <section key={section.title} className="deep-answer-section">
            <h3>{section.title}</h3>
            {section.title.includes('本轮完整结果') && <p className="deep-answer-complete-kicker">以下为本轮定向深研完整汇总，可直接审阅候选装备与后续追问。</p>}
            <AssistantMarkdown>{section.text}</AssistantMarkdown>
          </section>
        );
      })}
    </div>
  );
}

function UserMessageText({content}) {
  const parsed = parseQuotedDeepMessage(content);
  const slash = matchDeepSlashCommand(parsed.content);
  return (
    <>
      {parsed.quotedContext ? <blockquote className="deep-user-quote">{parsed.quotedContext}</blockquote> : null}
      {slash
        ? <p><code className="deep-slash-token">{slash.command}</code>{parsed.content.slice(slash.command.length)}</p>
        : <p>{parsed.content}</p>}
    </>
  );
}

function AssistantQuoteAction({containerRef, onQuote}) {
  const [action, setAction] = useState(null);
  useEffect(() => {
    if (!onQuote) return undefined;
    const update = () => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || !selection.rangeCount) {
        setAction(null);
        return;
      }
      const excerpt = selection.toString().replace(/\u00a0/g, ' ').replace(/\r\n?/g, '\n').trim().slice(0, 4000);
      if (!excerpt) {
        setAction(null);
        return;
      }
      const node = selection.anchorNode;
      const element = node instanceof Element ? node : node?.parentElement;
      const selectable = element?.closest?.('[data-assistant-selectable="true"]');
      const container = containerRef.current;
      if (!selectable || !container?.contains(selectable)) {
        setAction(null);
        return;
      }
      const range = selection.getRangeAt(0);
      let rect = range.getBoundingClientRect();
      if (!rect.width && !rect.height) {
        rect = [...range.getClientRects()].find(item => item.width || item.height)
          || selectable.getBoundingClientRect();
      }
      if (!rect.width && !rect.height) {
        setAction(null);
        return;
      }
      const box = container.getBoundingClientRect();
      const visibleTop = 8;
      const visibleBottom = Math.max(visibleTop, box.height - 36);
      let top = rect.top - box.top - 8;
      if (rect.bottom < box.top) top = visibleTop;
      else if (rect.top > box.bottom) top = visibleBottom;
      setAction({
        text: excerpt,
        left: Math.max(12, Math.min(box.width - 12, rect.left + Math.max(rect.width, 1) / 2 - box.left)),
        top: Math.max(visibleTop, Math.min(visibleBottom, top)),
      });
    };
    document.addEventListener('selectionchange', update);
    containerRef.current?.addEventListener('scroll', update, {passive: true});
    return () => {
      document.removeEventListener('selectionchange', update);
      containerRef.current?.removeEventListener('scroll', update);
    };
  }, [containerRef, onQuote]);
  if (!action) return null;
  return (
    <button
      type="button"
      className="deep-quote-action"
      style={{left: action.left, top: action.top}}
      onMouseDown={event => event.preventDefault()}
      onClick={() => {
        onQuote(action.text);
        window.getSelection()?.removeAllRanges();
        setAction(null);
      }}
    >
      <Quote size={12}/>引用追问
    </button>
  );
}

function MessageBubble({message, onOpenPortrait, artifacts = [], steerReceipt = null, onCancelSteer, onFork, onQuote, onCopy, copied = false, branchPending = false, branchDisabled = false}) {
  const role = safeText(message?.role) === 'user' ? 'user' : 'assistant';
  const content = safeText(message?.content);
  const messageKind = safeText(message?.message_kind);
  const steerMode = safeText(steerReceipt?.mode || message?.steer_mode);
  const steerStatus = safeText(steerReceipt?.status || message?.status);
  const isSteer = role === 'user' && (messageKind === 'steer' || Boolean(steerReceipt));
  const canCancelSteer = Boolean(
    isSteer
    && steerReceipt?.steer_id
    && ['accepted', 'pending', 'queued'].includes(steerStatus.toLowerCase()),
  );
  const refs = Array.isArray(message?.artifact_refs) ? message.artifact_refs.map(safeText).filter(Boolean) : [];
  const linkedArtifacts = artifacts.filter(item => {
    const payload = item?.payload && typeof item.payload === 'object' ? item.payload : item;
    const id = artifactId(payload);
    return id && refs.includes(id);
  });
  const openLinkedPortrait = (artifact) => {
    const payload = artifact?.payload && typeof artifact.payload === 'object' ? artifact.payload : artifact;
    const modules = extractPortraitModules(payload);
    onOpenPortrait?.({
      name: safeText(payload?.name || payload?.title || payload?.capability_name) || '五栏能力画像',
      modules,
      fallback: safeText(payload?.deep_capability_portrait || payload?.capability_image || payload?.summary),
      meta: '已固定到能力画像导航页 · 对话内查看',
    });
  };
  return <article
    className={`deep-message ${role}${message?.pending ? ' pending' : ''}${isSteer ? ' steer' : ''}`}
    data-thread-display-unit="true"
    data-prompt-id={role === 'user' ? safeText(message?.message_id) : undefined}
  >
    <div className="deep-message-meta"><span className="deep-message-avatar">{role === 'user' ? '你' : 'AI'}</span><b>{role === 'user' ? (isSteer ? '追问与纠偏' : '专家') : '创新舱'}</b><small>{message?.pending ? '正在接收' : (message?.created_at ? new Date(message.created_at).toLocaleString('zh-CN', {hour12: false}) : '')}</small></div>
    <div className="deep-message-body" data-assistant-selectable={role === 'assistant' ? 'true' : undefined}>{role === 'assistant' ? <CompleteAnswerView content={content || '正在整理可见回答…'} onOpenPortrait={onOpenPortrait}/> : <UserMessageText content={content}/>}</div>
    {isSteer && <div className={`deep-steer-receipt ${steerStatus || 'accepted'}`} aria-live="polite"><span><CheckCircle2 size={12}/>{steerStatusLabel(steerStatus, steerMode)}</span>{canCancelSteer && <button type="button" onClick={() => onCancelSteer?.(steerReceipt)}> 取消</button>}</div>}
    {(refs.length > 0 || linkedArtifacts.length > 0) && (
      <div className="deep-message-artifact-ref">
        {linkedArtifacts.length > 0 ? linkedArtifacts.map(item => {
          const payload = item?.payload && typeof item.payload === 'object' ? item.payload : item;
          const name = safeText(payload?.name || payload?.title || '五栏能力画像');
          return (
            <button type="button" key={artifactId(payload) || name} className="deep-message-portrait-link" onClick={() => openLinkedPortrait(item)}>
              <Sparkles size={13}/>点击查看：{name}
            </button>
          );
        }) : (
          <button
            type="button"
            className="deep-message-portrait-link"
            onClick={() => {
              const latest = artifacts[artifacts.length - 1];
              if (latest) openLinkedPortrait(latest);
              else onOpenPortrait?.({name: '五栏能力画像', modules: [], fallback: '画像已生成，请在下方候选卡中打开。', meta: '对话引用'});
            }}
          >
            <Sparkles size={13}/>已生成五栏能力画像，点击查看
          </button>
        )}
      </div>
    )}
    {safeText(message?.message_id) && !message?.pending && (
      <div className="deep-message-actions">
        <button type="button" onClick={() => onCopy?.(content, message.message_id)} title="复制这段内容">{copied ? <Check size={12}/> : <Copy size={12}/>}{copied ? '已复制' : '复制'}</button>
        {role === 'assistant' && <button type="button" onClick={() => onQuote?.(content.slice(0, 800))} title="引用后继续追问"><Quote size={12}/>引用</button>}
        {role === 'assistant' && <button type="button" disabled={branchDisabled || branchPending} onClick={() => onFork?.(message)} title="从这条结论创建独立研究分支">{branchPending ? <RefreshCw size={12} className="spin"/> : <GitBranch size={12}/>}从此分支继续</button>}
      </div>
    )}
  </article>;
}
const responseError = (response, fallback) => {
  if (!response) return fallback;
  const detail = response.detail || response.error || response.message;
  return safeText(detail) || fallback;
};

async function apiRequest(apiBase, path, options = {}) {
  try {
    const headers = {...(options.headers || {})};
    const response = await fetch(`${String(apiBase || '').replace(/\/$/, '')}${path}`, {
      ...options,
      headers,
    });
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) return {ok: false, status: response.status, detail: responseError(payload, `请求失败（${response.status}）`), data: payload};
    return {ok: true, status: response.status, data: payload};
  } catch (error) {
    return {ok: false, status: 0, detail: error?.message || '网络连接失败，请稍后重试。'};
  }
}

// Scope headers are derived from the server-projected run context.  They are
// advisory on the client (the API remains authoritative) but allow strict
// deployments to keep the same tenant/workspace boundary on fetch streams.
function deepScopeHeaders(context = {}, {legacyRole = 'analyst'} = {}) {
  const scope = context?.scope && typeof context.scope === 'object' ? context.scope : context;
  const headers = {'X-Role': resolveDeepRequestRole(context, legacyRole)};
  for (const [key, header] of [['tenant_id', 'X-Tenant-ID'], ['workspace_id', 'X-Workspace-ID'], ['project_id', 'X-Project-ID'], ['profile_id', 'X-Profile-ID']]) {
    const value = safeText(scope?.[key]);
    if (value) headers[header] = value;
  }
  const stages = Array.isArray(scope?.stage_scope) ? scope.stage_scope.filter(Boolean).join(',') : safeText(scope?.stage_scope);
  if (stages) headers['X-Evolution-Stage-Scope'] = stages;
  return headers;
}

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

/**
 * Read one bounded SSE response.  The deep stream deliberately closes after a
 * quiet window; the caller reconnects with the last sequence so no stage
 * increment is lost.  Fetch is used instead of EventSource so authenticated
 * scope headers can be carried in strict deployments.
 */
async function readDeepEventStream(url, {headers = {}, lastEventId = 0, signal, onEvent} = {}) {
  const response = await fetch(url, {headers: {'Accept': 'text/event-stream', ...headers, 'Last-Event-ID': String(lastEventId || 0)}, signal});
  if (!response.ok) throw new Error(`SSE 请求失败（${response.status}）`);
  if (!response.body?.getReader) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = 'message';
  let eventId = '';
  let data = [];
  const emit = () => {
    if (!data.length) { eventType = 'message'; eventId = ''; return; }
    onEvent?.({type: eventType, data: data.join('\n'), lastEventId: eventId});
    eventType = 'message'; eventId = ''; data = [];
  };
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line) { emit(); continue; }
        if (line.startsWith(':')) continue;
        const separator = line.indexOf(':');
        const field = separator >= 0 ? line.slice(0, separator) : line;
        const valueText = separator >= 0 ? line.slice(separator + 1).replace(/^ /, '') : '';
        if (field === 'event') eventType = valueText || 'message';
        else if (field === 'id') eventId = valueText;
        else if (field === 'data') data.push(valueText);
      }
      if (done) {
        // A compliant SSE server normally terminates every field with a
        // newline, but a proxy can close immediately after the final `data:`
        // line.  Parse that bounded tail before flushing so the last stage
        // increment is not lost on a reconnect boundary.
        if (buffer) {
          const line = buffer;
          buffer = '';
          if (line.startsWith(':')) {
            // heartbeat/comment; intentionally ignored
          } else {
            const separator = line.indexOf(':');
            const field = separator >= 0 ? line.slice(0, separator) : line;
            const valueText = separator >= 0 ? line.slice(separator + 1).replace(/^ /, '') : '';
            if (field === 'event') eventType = valueText || 'message';
            else if (field === 'id') eventId = valueText;
            else if (field === 'data') data.push(valueText);
          }
        }
        emit();
        break;
      }
    }
  } finally {
    try { reader.releaseLock(); } catch { /* already released */ }
  }
}

function contextTitle(context, run) {
  const selected = context?.current_result_context?.selected;
  return safeText(context?.title || context?.capability_name || context?.candidate?.title || context?.candidate?.name || selected?.title || selected?.name)
    || (run ? '当前研究 Query' : '深度思考 Agent');
}

// A global launcher is retained for discoverability, but every actual deep
// turn must be bound to one server-resolvable equipment identity.  Display
// labels such as “当前研究的深度思考” are intentionally not identities.
const GENERIC_DEEP_TARGET_LABELS = new Set([
  '当前研究的深度思考',
  '当前研究 Query',
  '深度思考 Agent',
  '当前能力画像',
]);
const deepEquipmentLabel = target => {
  const source = target && typeof target === 'object' ? target : {};
  const value = safeText(source.title || source.name || source.primary_equipment_identity || source.equipment_form || source.capability_name);
  return GENERIC_DEEP_TARGET_LABELS.has(value) ? '' : value;
};
const deepEquipmentIdentity = target => {
  const source = target && typeof target === 'object' ? target : {};
  for (const field of ['hypothesis_id', 'card_binding_id', 'capability_id', 'candidate_id', 'card_id']) {
    const value = safeText(source[field]);
    if (value) return `${field}:${value}`;
  }
  const label = deepEquipmentLabel(source);
  return label ? `name:${label}` : '';
};
const deepTargetKind = (target, fallback = 'deep-thinking') => {
  const normalizedFallback = safeText(fallback).toLowerCase().replace(/_/g, '-');
  if (['capability-followup', 'reference-research'].includes(normalizedFallback)) return normalizedFallback;
  const source = target && typeof target === 'object' ? target : {};
  const reference = source.is_reference === true
    || source.reference_only === true
    || source.s6_eligible === false
    || ['reference', 'reference_candidate', 'reference_equipment'].includes(safeText(source.selection_status || source.capability_type).toLowerCase());
  return reference ? 'reference-research' : 'capability-followup';
};
// A capability card and a reference candidate can legitimately carry the same
// hypothesis/candidate identity while exposing different deep-turn semantics.
// Keep the target kind in the picker key so selecting one never resolves to
// the other when the two arrays are merged into a global launcher context.
const deepTargetOptionKey = option => {
  const kind = safeText(option?.kind || deepTargetKind(option?.value));
  const identity = deepEquipmentIdentity(option?.value);
  return identity ? `${kind}:${identity}` : '';
};
const deepTargetFromContext = context => {
  const source = context && typeof context === 'object' ? context : {};
  // Some legacy launchers populate both aliases and leave a generic display
  // object in ``candidate`` while the canonical target is in
  // ``reference_weapon`` or ``current_result_context.selected``.  Resolve the
  // first identity-bearing object instead of letting that placeholder shadow
  // a valid single-equipment target.
  const candidates = [
    source.candidate,
    source.reference_weapon,
    source.current_result_context?.selected,
  ];
  const selected = candidates.find(item => item && typeof item === 'object' && deepEquipmentIdentity(item));
  if (!selected) {
    const restored = parseDeepTargetIdentity(source.target_identity || source.targetIdentity);
    if (!restored) return null;
    return restored;
  }
  return {
    kind: deepTargetKind(selected, source.kind),
    value: selected,
  };
};
const deepTargetOptionsFromContext = context => {
  const source = context && typeof context === 'object' ? context : {};
  const current = source.current_result_context && typeof source.current_result_context === 'object'
    ? source.current_result_context
    : {};
  const options = [];
  const seen = new Set();
  const add = (value, kind) => {
    if (!value || typeof value !== 'object') return;
    const identity = deepEquipmentIdentity(value);
    if (!identity) return;
    const key = `${kind}:${identity}`;
    if (seen.has(key)) return;
    seen.add(key);
    options.push({kind, value});
  };
  (Array.isArray(current.capability_cards) ? current.capability_cards : []).forEach(value => add(value, 'capability-followup'));
  (Array.isArray(current.reference_weapons) ? current.reference_weapons : []).forEach(value => add(value, 'reference-research'));
  const explicit = deepTargetFromContext(source);
  if (explicit) add(explicit.value, explicit.kind);
  return options.slice(0, 32);
};

const jobDisplayLabel = () => '单装备深研对话';

const WELCOME_SUGGESTION_POOL = [
  '从新质直接杀伤角度深度发散：改写发现—进入—毁伤关系，提出可独立部署的颠覆性武器装备概念',
  '重构交战闭环：明确打击对象、直接毁伤机理与任务失能判据，拒绝单纯增程增速',
  '以前沿新质技术赋能切入：把新机理落到具体武器本体，并闭合到可观察的物理毁伤结果',
  '围绕成本交换与反适应韧性发散：提出低价换高代价、对手难按旧杀伤链计价的直接杀伤装备',
  '从杀伤链反转与任务窗口掠夺出发，形成能夺取先机并直接毁伤关键目标的新质装备',
  '把感知、电磁与自主能力作为突防赋能，终点收敛到传统火力无法替代的物理毁伤机理',
  '若技术代差窗口极短，怎样在窗口内形成可验证的直接毁伤与任务失能优势？',
  '跳出平台换壳：以分布式、可消耗、可重组单元形成一型颠覆性直接杀伤装备',
  '以静默、通信受限或补给受阻为边界，提出仍能独立完成毁伤闭环的装备形态',
  '从目标脆弱性倒推装备：哪一种新作用机理能用更小代价造成不可逆任务失能？',
  '用蜂群、诱骗与真假混编服务于进入和命中，最终收敛为一型直接杀伤装备',
  '把可生产性与战损替换纳入制胜方程，反向推导可持续消耗的颠覆性杀伤装备',
  '当传统杀伤链在复杂地形失效时，重建从自主发现到直接毁伤的单装闭环',
  '从对手最低成本反制倒推：哪一种直接毁伤路径最难被现有防御低成本化解？',
  '以多域信息赋能单装，但以物理毁伤为唯一终点，发散传统手册之外的新质装备路径',
];

const shufflePick = (items, count) => {
  const pool = [...items];
  for (let index = pool.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [pool[index], pool[swapIndex]] = [pool[swapIndex], pool[index]];
  }
  return pool.slice(0, Math.min(count, pool.length));
};

const randomWelcomeSuggestions = (context, count = 3) => {
  const equipment = deepEquipmentLabel(
    context?.focused_equipment
    || context?.candidate
    || context?.reference_weapon
    || {name: context?.capability_name || context?.title},
  );
  const picked = shufflePick(WELCOME_SUGGESTION_POOL, count);
  if (!equipment) return picked;
  const bodyIndex = picked.findIndex(item => !item.startsWith('围绕') && !item.includes(equipment));
  const sourceIndex = bodyIndex >= 0 ? bodyIndex : 0;
  const anchored = anchorWelcomeSuggestion(equipment, picked[sourceIndex]);
  return [anchored, ...picked.filter((_, index) => index !== sourceIndex)];
};

function StageStrip({stages = []}) {
  if (!stages.length) return null;
  return <nav className="deep-stage-strip" aria-label="已发生的研究活动" style={{'--deep-stage-count': stages.length}}>
    <span><BrainCircuit size={13}/>研究轨迹</span>
    {stages.map((item, index) => (
      <div key={item.key} className={`deep-stage-${item.status}`}>
        <i aria-hidden="true">{item.status === 'completed' ? <Check size={11}/> : index + 1}</i>
        <span><b>{item.label}</b><small>{item.status === 'running' ? '正在进行' : item.status === 'completed' ? '已记录' : item.status === 'partial' ? '已保留摘要' : item.status === 'failed' ? '可重试' : ''}</small></span>
      </div>
    ))}
  </nav>;
}

function DeliberationBoard({answer, stageEvents = [], sending = false, onFocusDirection}) {
  const dialogue = Array.isArray(answer?.agent_dialogue) ? answer.agent_dialogue : [];
  const directions = Array.isArray(answer?.concept_directions) ? answer.concept_directions : [];
  const reviews = Array.isArray(answer?.adjudication?.candidate_reviews) ? answer.adjudication.candidate_reviews : [];
  const researchAssessment = answer?.research_assessment && typeof answer.research_assessment === 'object'
    ? answer.research_assessment
    : null;
  const qualityGate = answer?.quality_gate && typeof answer.quality_gate === 'object' ? answer.quality_gate : null;
  const proposers = dialogue.filter(item => safeText(item?.round) === 'divergence');
  const later = dialogue.filter(item => ['critique', 'synthesis'].includes(safeText(item?.round)));
  const eventCards = (!proposers.length ? stageEvents : [])
    .map(event => {
      const text = safeText(event?.delta?.text || event?.text || event?.summary);
      const stage = normalizeDeepStage(event?.stage);
      const round = eventRound(event);
      if (!text || (stage !== 's3_divergence' && round !== 'divergence')) return null;
      if (safeText(eventDelta(event).kind || event?.kind) !== 'answer' && eventProposalNames(event).length === 0) return null;
      const axis = eventAxis(event) || safeText(text.split('：')[0]).slice(0, 40);
      const names = eventProposalNames(event);
      const [axisPart, ...rest] = text.split('：');
      return {
        axis: axis || safeText(axisPart).slice(0, 40),
        summary: rest.join('：').replace(/\s*·\s*候选：.*$/, '').replace(/^\s*-\s.*/gm, '').slice(0, 280),
        proposals: mergeDeliberationProposals(names, text),
      };
    })
    .filter(Boolean)
    .filter((item, index, rows) => rows.findIndex(row => row.axis === item.axis) === index)
    .slice(0, 6);
  const axisRows = proposers.length
    ? proposers.map(item => ({
      axis: safeText(item.axis) || safeText(item.role),
      summary: safeText(item.summary),
      proposals: mergeDeliberationProposals(item.proposal_names, item.summary),
      key: item.agent_id || item.role,
    }))
    : eventCards.map((item, index) => ({...item, key: `${item.axis}-${index}`}));
  const boardCandidates = mergeDeliberationProposals(
    axisRows.flatMap(item => item.proposals || []),
    later.map(item => item.summary),
    reviews.map(item => item.candidate_name),
    directions.map(item => item.innovation_variant_name || item.name),
  );
  const researchGaps = (
    Array.isArray(researchAssessment?.research_gaps)
      ? researchAssessment.research_gaps
      : Array.isArray(answer?.research_gaps)
        ? answer.research_gaps
        : Array.isArray(qualityGate?.block_reasons)
          ? qualityGate.block_reasons
          : []
  ).map(safeText).filter(Boolean).slice(0, 3);
  if (!axisRows.length && !directions.length && !reviews.length && !later.length && !researchGaps.length && !boardCandidates.length) return null;
  const directionNames = new Set(directions.map(item => safeText(item.innovation_variant_name || item.name)).filter(Boolean));
  const chipSeen = new Set(directionNames);
  const uniqueAxisRows = axisRows.map(item => ({
    ...item,
    proposals: uniqueNamedValues(item.proposals, chipSeen),
  }));
  const uniqueBoardCandidates = uniqueNamedValues(boardCandidates, chipSeen);
  const hasAxisChips = uniqueAxisRows.some(item => item.proposals?.length);
  return <section className="deep-deliberation" aria-label="创新议事看板">
    <header>
      <div><Sparkles size={14}/><b>创新议事看板</b></div>
      <small>{axisRows.length ? `${axisRows.length} 路已观察探索` : '动态研究汇总'}{sending ? ' · 实时汇入' : ''}</small>
    </header>
    {uniqueAxisRows.length > 0 && <div className="deep-deliberation-axes">
      {uniqueAxisRows.map(item => (
        <article key={item.key}>
          <b>{item.axis}</b>
          <p>{item.summary}</p>
          {item.proposals?.length > 0 && (
            <span>
              {item.proposals.map(name => (
                <button
                  type="button"
                  key={name}
                  className="deep-deliberation-chip"
                  onClick={() => onFocusDirection?.({name, winning_angle: item.axis})}
                >
                  {name}
                </button>
              ))}
            </span>
          )}
        </article>
      ))}
    </div>}
    {!hasAxisChips && uniqueBoardCandidates.length > 0 && (
      <div className="deep-deliberation-axes">
        <article>
          <b>可继续深化</b>
          <span>
            {uniqueBoardCandidates.map(name => (
              <button
                type="button"
                key={name}
                className="deep-deliberation-chip"
                onClick={() => onFocusDirection?.({name})}
              >
                {name}
              </button>
            ))}
          </span>
        </article>
      </div>
    )}
    {later.length > 0 && <div className="deep-deliberation-review">
      {later.map(item => (
        <p key={item.agent_id || item.role}><b>{friendlyAgentLabel(item.role)}</b>{safeText(item.summary)}{Array.isArray(item.verdicts) && item.verdicts.length > 0 ? `（${item.verdicts.join('；')}）` : ''}</p>
      ))}
    </div>}
    {reviews.length > 0 && <div className="deep-deliberation-verdicts">
      {reviews.slice(0, 6).map(item => (
        <button
          type="button"
          key={`${item.candidate_name}-${item.verdict}`}
          className={`verdict-${safeText(item.verdict).toLowerCase() || 'revise'}`}
          onClick={() => onFocusDirection?.(item)}
        >
          {safeText(item.candidate_name)} · {safeText(item.verdict) || 'revise'}
          {safeText(item.winning_logic_class) ? ` · ${item.winning_logic_class}` : ''}
        </button>
      ))}
    </div>}
    {safeText(answer?.adjudication?.mission_focus) && (
      <p className="deep-deliberation-mission"><Sparkles size={12}/>{safeText(answer.adjudication.mission_focus)}</p>
    )}
    {reviews.some(item => safeText(item.initiative_claim) || safeText(item.counterbalance_claim)) && (
      <div className="deep-deliberation-review">
        {reviews.slice(0, 3).map(item => {
          const initiative = safeText(item.initiative_claim);
          const counterbalance = safeText(item.counterbalance_claim);
          if (!initiative && !counterbalance) return null;
          return <p key={`claim-${item.candidate_name}`}><b>{safeText(item.candidate_name)}</b>{[initiative && `先机：${initiative}`, counterbalance && `制衡：${counterbalance}`].filter(Boolean).join('；')}</p>;
        })}
      </div>
    )}
    {directions.length > 0 && <div className="deep-deliberation-directions">
      {directions.slice(0, 3).map(item => (
        <button
          type="button"
          className="deep-deliberation-direction"
          key={item.name || item.innovation_variant_name}
          onClick={() => onFocusDirection?.(item)}
        >
          <b>{safeText(item.innovation_variant_name || item.name)}</b>
          <small>{[item.winning_angle && `角度：${item.winning_angle}`, item.changed_assumption && `假设：${item.changed_assumption}`, (item.innovation_equipment_form || item.equipment_form) && `构型：${item.innovation_equipment_form || item.equipment_form}`].filter(Boolean).join(' · ')}</small>
        </button>
      ))}
    </div>}
    {researchGaps.length > 0 && <p className="deep-deliberation-note"><BookOpen size={12}/><span><b>下一轮可补充</b>{researchGaps.join('；')}</span></p>}
  </section>;
}

const friendlyProcessText = (value) => {
  let text = safeText(value);
  if (!text) return '';
  const replacements = [
    [/六轴独立发散/g, '深度发散'],
    [/进入六轴独立发散/g, '进入深度发散'],
    [/六个发散轴围绕单个装备并行提案，不复述父任务证据。?/g, '创新舱正在内部多维发散，围绕当前装备收敛高质量候选，不复述父任务证据。'],
    [/六个发散轴围绕单个装备并行提案/g, '创新舱正在内部多维发散并收敛候选'],
    [/(\d+)\s*个发散轴已完成独立提案/g, '$1 路发散 Agent 已完成内部多维提案'],
    [/发散轴已完成独立提案/g, '发散 Agent 已完成内部多维提案'],
    [/哪个发散轴还能继续推翻/g, '哪个内部维度还能继续推翻'],
    [/多轴独立发散/g, '内部多维发散'],
    [/多轴议事/g, '创新议事'],
    [/六轴发散/g, '深度发散'],
    [/对抗裁决 Agent/g, '观点复核 Agent'],
    [/进入对抗裁决/g, '进入交叉复核'],
  ];
  for (const [pattern, replacement] of replacements) text = text.replace(pattern, replacement);
  return text;
};

const processStageCue = (stage, status = '') => {
  const normalized = normalizeDeepStage(stage);
  const failed = ['failed', 'blocked', 'cancelled'].includes(safeText(status).toLowerCase());
  if (failed) {
    return {
      queued: '任务受阻，我先把已形成的阶段反馈留给你。',
      context: '锁定装备时遇到阻碍，可换个角度再试一次。',
      s3_divergence: '深度发散未完整走完，已保留可见摘要。',
      council_critique: '交叉复核尚未完整，已有方向仍可继续追问。',
      s4_mapping: '方向深化未完整完成，可基于已有方向继续追问。',
      s5_adjudication: '交叉复核尚未完整，已有方向仍可继续追问。',
      s6_authoring: '成卡阶段受阻，讨论内容仍可见，但未写入正式版本。',
    }[normalized] || '这一步没有顺利完成，你可以继续追问或重试。';
  }
  return {
    queued: '已收到你的问题，正在排队进入创新舱…',
    context: '先帮你锁定当前装备、Query 与问题焦点。',
    s3_divergence: '开始内部多维深度发散，基于 Query 已有武器边收敛新质装备候选边把可见进展反馈给你。',
    council_critique: '正在交叉复核候选方向的先机、制衡与可落地性。',
    s4_mapping: '正在内部沿多维度、多角度交叉发散，再收敛到你的问题。',
    s5_adjudication: '正在交叉复核候选方向的先机、制衡与可落地性。',
    s6_authoring: '开始收敛成卡，整理可写入五栏能力画像的表述。',
  }[normalized] || (safeText(stage) ? `正在推进「${activeStageLabel(stage)}」…` : '继续为你做内部多维深度发散…');
};

function StreamingLabel({active = false, children}) {
  const label = safeText(children);
  if (!label) return null;
  return <span className={active ? 'deep-streaming-sheen' : undefined} data-sheen-text={active ? label : undefined}>{label}</span>;
}

function ThinkingElapsed({active = false}) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) { setSeconds(0); return undefined; }
    const startedAt = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [active]);
  if (!active || seconds < 2) return null;
  const label = seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
  return <small className="deep-process-elapsed">已深度思考 {label}</small>;
}

const eventToolName = item => safeText(eventDelta(item).tool_name || item?.tool_name);
const eventSkillIds = item => {
  const value = eventDelta(item).active_skill_ids || eventDelta(item).skill_ids || item?.active_skill_ids || item?.skill_ids;
  return Array.isArray(value) ? value.map(safeText).filter(Boolean).slice(0, 8) : [];
};
const friendlyAgentLabel = value => ({
  '对抗裁决 Agent': '观点复核 Agent',
  '并行发散 Agent 组': '开放探索 Agent',
} [safeText(value)] || safeText(value));
const processRoleLabel = item => eventToolName(item)
  ? `工具 · ${eventToolName(item)}`
  : friendlyAgentLabel(eventRole(item))
  || ({context: '研究编排 Agent', s3_divergence: '开放探索 Agent', council_critique: '观点复核 Agent', s4_mapping: '方向深化 Agent', s6_authoring: '能力画像总编'}[normalizeDeepStage(item?.stage)])
  || '创新舱';

function ProcessFeedbackThread({events = [], sending = false, liveAnswer = '', showLiveAnswer = false, activeJob = null, activeSkillIds = [], ownedCandidateNames = [], onQuoteCandidate}) {
  const [clusterOpen, setClusterOpen] = useState(true);
  const clusterTouchedRef = useRef(false);
  const [expandedAgentKey, setExpandedAgentKey] = useState('');
  const timelineRef = useRef(null);
  const activity = useMemo(() => projectDeepAgentActivity(events), [events]);
  useEffect(() => {
    if (sending) {
      setClusterOpen(true);
      clusterTouchedRef.current = false;
      return undefined;
    }
    if (clusterTouchedRef.current) return undefined;
    const timer = setTimeout(() => setClusterOpen(false), 2200);
    return () => clearTimeout(timer);
  }, [sending]);
  useEffect(() => {
    const node = timelineRef.current;
    if (!node || !sending || !clusterOpen) return;
    node.scrollTop = node.scrollHeight;
  }, [clusterOpen, events.length, sending]);
  const latest = events[events.length - 1];
  const announcedSkillIds = [...events].reverse().map(eventSkillIds).find(items => items.length > 0) || [];
  const effectiveSkillIds = announcedSkillIds.length ? announcedSkillIds : activeSkillIds;
  const activeTool = [...events].reverse().find(item => eventToolName(item) && !['completed', 'failed', 'error'].includes(safeText(item?.status).toLowerCase()));
  const activeStage = furthestDeepStage(
    activeJob?.stage,
    latest?.stage,
    sending ? 'context' : '',
  );
  const progress = visibleProgress(events, activeJob, sending);
  const continuingCue = processStageCue(activeStage || (sending ? 'context' : ''), activeJob?.status || latest?.status);
  const activityMode = inferProcessRosterMode(events, {sending, activeStage});
  const liveText = friendlyProcessText(liveAnswer);
  const showLiveBlock = showLiveAnswer && liveText && !looksLikeCompleteAnswerDump(liveText);
  const displayEvents = events
    .filter(item => safeText(item?.delta?.text))
    .filter((item, index, rows) => rows.findIndex(row => (
      normalizeDeepStage(row?.stage) === normalizeDeepStage(item?.stage)
      && processRoleLabel(row) === processRoleLabel(item)
      && safeText(row?.delta?.text) === safeText(item?.delta?.text)
    )) === index)
    .slice(-16);
  const collectLatestByRole = (predicate) => {
    const seen = new Set();
    const rows = [];
    [...events].reverse().forEach(item => {
      const kind = safeText(eventDelta(item).kind || item?.kind);
      if (kind !== 'answer') return;
      if (looksLikeCompleteAnswerDump(item?.delta?.text)) return;
      if (!predicate(item)) return;
      const key = `${processRoleLabel(item)}:${normalizeDeepStage(item?.stage)}`;
      if (seen.has(key)) return;
      seen.add(key);
      rows.unshift(item);
    });
    return rows;
  };
  const parallelAnswers = collectLatestByRole(item => (
    isParallelCouncilEvent(item)
    || (eventRound(item) === 'divergence' && (eventRole(item) || eventProposalNames(item).length > 0))
  ));
  const columnAnswers = collectLatestByRole(isColumnAuthorEvent);
  const critiqueAnswers = collectLatestByRole(item => (
    eventRound(item) === 'critique' || normalizeDeepStage(item?.stage) === 'council_critique'
  ) && !isParallelCouncilEvent(item) && !isColumnAuthorEvent(item));
  const deepenAnswers = collectLatestByRole(item => (
    eventRound(item) === 'deepen'
    || (normalizeDeepStage(item?.stage) === 's4_mapping' && !isColumnAuthorEvent(item) && eventRound(item) !== 'authoring')
  ) && !isParallelCouncilEvent(item));
  const latestCountEvent = [...events].reverse().find(item => eventTotalCount(item) > 0 || eventCompletedCount(item) > 0);
  const completedCount = Math.max(parallelAnswers.length, eventCompletedCount(latestCountEvent));
  const totalCount = eventTotalCount(latestCountEvent);
  const timelineEvents = displayEvents.filter(item => !(
    (isParallelCouncilEvent(item) || isColumnAuthorEvent(item))
    && safeText(eventDelta(item).kind || item?.kind) === 'answer'
  ) && safeText(item?.event_type) !== 'deep_context_compacted');
  if (!sending && !timelineEvents.length && !showLiveBlock && !parallelAnswers.length && !columnAnswers.length && !deepenAnswers.length && !events.some(item => safeText(item?.event_type) === 'deep_context_compacted')) return null;
  const agents = projectDeepActivityRoster(events, {sending}).map(agent => {
    const matched = [...events].reverse().find(item => eventAgentId(item) === agent.agent_id);
    let status = agent.status || safeText(matched?.status).toLowerCase() || 'running';
    if (status === 'queued') status = 'running';
    if (status === 'completed') status = 'done';
    if (matched && safeText(eventDelta(matched).kind) === 'answer' && status === 'running') status = 'done';
    if (['failed', 'blocked', 'partial'].includes(status) && safeText(eventDelta(matched).kind) === 'answer') status = 'done';
    const names = agent.deliverable_refs?.length ? agent.deliverable_refs : matched ? eventProposalNames(matched) : [];
    return {
      ...agent,
      label: friendlyAgentLabel(agent.label),
      status,
      detail: friendlyProcessText(agent.summary || matched?.delta?.text),
      names,
      axis: agent.axis || eventAxis(matched),
    };
  });
  const progressCue = sending
    ? (activityMode === 'explore' && completedCount > 0
      ? totalCount > 0
        ? `开放探索 · 已回传 ${Math.min(completedCount, totalCount)}/${totalCount} 条`
        : `开放探索 · 已回传 ${completedCount} 条`
      : activeStage === 's6_authoring' && columnAnswers.length
        ? `五栏成卡 · 已写入 ${columnAnswers.length}/5 栏`
        : activityMode === 'deepen'
          ? '持续深化 · 动态扩展角度并收敛到本轮问题'
        : (activeStage ? `当前活动 · ${activeStageLabel(activeStage)}` : '正在实时研究'))
    : '研究活动已记录';
  const candidateSeen = new Set(Array.isArray(ownedCandidateNames) ? ownedCandidateNames.map(safeText).filter(Boolean) : []);
  const takeUniqueNames = names => uniqueNamedValues(names, candidateSeen);
  const takeUniqueBriefs = briefs => {
    const rows = [];
    for (const brief of Array.isArray(briefs) ? briefs : []) {
      const name = safeText(brief?.name);
      if (!name || candidateSeen.has(name)) continue;
      candidateSeen.add(name);
      rows.push(brief);
    }
    return rows;
  };
  const renderLiveCard = (item, index) => {
    const briefs = takeUniqueBriefs(eventProposalBriefs(item));
    const names = briefs.length ? [] : takeUniqueNames(eventProposalNames(item));
    const text = friendlyProcessText(item?.delta?.text).replace(/\n- .*$/s, '');
    return (
      <article key={`${processRoleLabel(item)}-${index}`} className={sending ? 'fresh' : ''}>
        <div>
          <em>{eventAxis(item) || activeStageLabel(item.stage)}</em>
          <b>{processRoleLabel(item)}</b>
        </div>
        <p data-assistant-selectable="true">{text}</p>
        {briefs.length > 0 ? (
          <ul>
            {briefs.map(brief => (
              <li key={brief.name}>
                <button type="button" className="deep-process-quote-name" onClick={() => onQuoteCandidate?.(brief.name, brief)}>
                  <strong>{brief.name}</strong>
                </button>
                {[brief.equipment_form, brief.winning_angle, brief.disruptive_difference].filter(Boolean).join(' · ')}
              </li>
            ))}
          </ul>
        ) : names.length > 0 ? (
          <div className="deep-process-candidates">{names.map(name => <button type="button" key={name} onClick={() => onQuoteCandidate?.(name)}>{name}</button>)}</div>
        ) : null}
      </article>
    );
  };
  const compactionEvent = [...events].reverse().find(item => safeText(item?.event_type) === 'deep_context_compacted');
  const runningAgents = agents.filter(item => item.status === 'running').length;
  const doneAgents = agents.filter(item => item.status === 'done').length;
  return (
    <section className="deep-process-console" aria-live="polite" aria-label="多智能体协作进展">
      <header className="deep-process-console-head">
        <div><span className="deep-process-orbit"><BrainCircuit size={15}/></span><span><b><StreamingLabel active={sending}>{sending ? '正在工作' : '本轮工作'}</StreamingLabel></b><small>{sending ? `${Math.max(runningAgents, activity.active_count)} 个 Agent 正在协作` : `${Math.max(doneAgents, activity.completed_count)} 个 Agent 已提交`}</small></span></div>
        <div className="deep-process-head-actions"><div className={`deep-process-live-state${sending ? ' active' : ''}`}><i/>{sending ? 'LIVE' : '已记录'}<ThinkingElapsed active={sending}/></div><button type="button" className="deep-process-toggle" aria-expanded={clusterOpen} aria-label={clusterOpen ? '收起协作现场' : '展开协作现场'} title={clusterOpen ? '收起' : '展开'} onClick={() => { clusterTouchedRef.current = true; setClusterOpen(value => !value); }}>{clusterOpen ? <ChevronDown size={15}/> : <ChevronRight size={15}/>}</button></div>
      </header>
      <div
        className={`deep-process-progress${sending ? ' active' : ''}`}
        role="progressbar"
        aria-label="深度推演进度"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={Math.round(progress * 100)}
      >
        <span style={{width: `${Math.round(progress * 100)}%`}}/>
      </div>
      <div className="deep-process-progress-meta"><span>{progressCue}</span><b>{Math.round(progress * 100)}%</b></div>
      {(effectiveSkillIds.length > 0 || activeTool) && <div className="deep-process-capabilities" aria-label="本轮激活能力"><Puzzle size={12}/>{effectiveSkillIds.map(skillId => <span key={skillId}>${skillId}</span>)}{activeTool && <em><RefreshCw size={10} className={sending ? 'spin' : ''}/>{eventToolName(activeTool)}</em>}</div>}
      {clusterOpen && (
        <div className="deep-process-cluster-body">
          <div className="deep-process-agent-grid">
            {agents.map(agent => (
              <button type="button" className={`deep-process-agent ${agent.status}`} key={agent.key} title={agent.detail || agent.hint} aria-expanded={expandedAgentKey === agent.key} onClick={() => setExpandedAgentKey(current => current === agent.key ? '' : agent.key)}>
                <span>{agent.status === 'done' ? <Check size={12}/> : agent.badge}</span>
                <div><b>{agent.label}</b><small>{agent.status === 'running' ? '正在处理' : agent.status === 'done' ? (agent.names.length ? agent.names[0] : '已提交') : ['failed', 'blocked', 'partial'].includes(agent.status) ? '需要复核' : agent.hint}</small></div>
                {agent.status === 'running' && <i aria-hidden="true"/>}
              </button>
            ))}
          </div>
          {expandedAgentKey && (() => {
            const agent = agents.find(item => item.key === expandedAgentKey);
            if (!agent) return null;
            return <div className={`deep-process-agent-detail ${agent.status}`}><div><b>{agent.label}</b><span>{agent.axis || agent.hint}</span></div><p>{agent.detail || (agent.status === 'waiting' ? '等待上游交接。' : agent.hint)}</p>{agent.names.length > 0 && <div className="deep-process-candidates">{agent.names.map(name => <span key={name}>{name}</span>)}</div>}</div>;
          })()}
          {activity.handoffs.length > 0 && (
            <div className="deep-process-handoffs" aria-label="Agent 交接记录">
              <header><b>协作交接</b><span>{activity.handoffs.length} 次</span></header>
              {activity.handoffs.slice(-4).map(handoff => <article key={handoff.key}><span>{handoff.from_label}</span><CornerDownRight size={13}/><b>{handoff.to_label}</b><p>{handoff.summary}</p>{handoff.deliverable_refs.length > 0 && <div className="deep-process-candidates">{handoff.deliverable_refs.slice(0, 3).map(item => <span key={item}>{item}</span>)}</div>}</article>)}
            </div>
          )}
          <div className="deep-process-timeline">
            <header><b>{sending && <i className="deep-live-dot" aria-hidden="true"/>}{sending ? '即时进展' : '推演时间线'}</b><span>{activeStage ? `当前 · ${activeStageLabel(activeStage)}` : '准备中'}</span></header>
            <div className="deep-process-timeline-scroll" ref={timelineRef}>
            {!timelineEvents.length && sending && (
              <article className="running"><span className="deep-process-node"/><div><b>任务编排 Agent</b><p>问题已进入创新舱，正在锁定 Query 已有武器、研究边界与直接毁伤目标。</p></div><em>刚刚</em></article>
            )}
            {timelineEvents.map((item, index) => {
              const status = safeText(item?.status).toLowerCase() || 'running';
              const rawText = friendlyProcessText(item?.delta?.text);
              const text = looksLikeCompleteAnswerDump(rawText) ? '完整结果已生成，正在写入会话。' : rawText;
              const names = eventProposalNames(item);
              const done = status === 'completed' || safeText(eventDelta(item).kind) === 'answer';
              return <article className={done && status !== 'failed' ? 'completed' : status} key={`${item.sequence ?? index}-${safeText(item.stage)}-${index}`}>
                <span className="deep-process-node">{done ? <Check size={10}/> : null}</span>
                <div><b>{done ? processRoleLabel(item) : <StreamingLabel active={sending && !done}>{processRoleLabel(item)}</StreamingLabel>}</b><p data-assistant-selectable="true">{text || processStageCue(item.stage, status)}</p>{names.length > 0 && <div className="deep-process-candidates">{uniqueNamedValues(names).map(name => <span key={name}>{name}</span>)}</div>}</div>
                <em>{Number(item.progress) > 0 ? `${Math.round(Number(item.progress) * 100)}%` : activeStageLabel(item.stage)}</em>
              </article>;
            })}
            </div>
          </div>
        </div>
      )}
      {!clusterOpen && sending && (
        <div className="deep-process-current-step" aria-live="polite">
          <StreamingLabel active>{agents.find(item => item.status === 'running')?.label || '创新舱正在回传'}</StreamingLabel>
          <small>{friendlyProcessText(agents.find(item => item.status === 'running')?.detail) || continuingCue}</small>
        </div>
      )}
      {activity.interventions.length > 0 && (() => {
        const receipt = activity.interventions[activity.interventions.length - 1];
        return <div className="deep-process-intervention"><MessageSquare size={13}/><span><b>即时追问已接收</b><small>{receipt.summary}</small></span></div>;
      })()}
      {compactionEvent && (
        <div className="deep-process-compaction" aria-label="上下文压缩">
          <Layers size={13}/>
          <span>
            <b>上下文已压缩</b>
            <small>{friendlyProcessText(eventDelta(compactionEvent).text || compactionEvent?.delta?.text)}</small>
          </span>
        </div>
      )}
      {(parallelAnswers.length > 0 || critiqueAnswers.length > 0 || columnAnswers.length > 0 || deepenAnswers.length > 0) && (
        <div className="deep-process-live-feed" aria-live="polite">
          {parallelAnswers.length > 0 && (
            <div className="deep-process-parallel" aria-label="并行处理结果">
              <header><b>{sending ? '并行结果已即时回传' : '本轮并行结果'}</b><span>{parallelAnswers.length} 路</span></header>
              {parallelAnswers.map(renderLiveCard)}
            </div>
          )}
          {critiqueAnswers.length > 0 && (
            <div className="deep-process-parallel deep-process-critique" aria-label="交叉复核结果">
              <header><b>{sending ? '交叉复核已回传' : '交叉复核'}</b><span>{critiqueAnswers.length}</span></header>
              {critiqueAnswers.map(renderLiveCard)}
            </div>
          )}
          {deepenAnswers.length > 0 && (
            <div className="deep-process-parallel deep-process-deepen" aria-label="方向深化结果">
              <header><b>{sending ? '方向深化已回传' : '本轮深化'}</b><span>{deepenAnswers.length}</span></header>
              {deepenAnswers.map(renderLiveCard)}
            </div>
          )}
          {columnAnswers.length > 0 && (
            <div className="deep-process-parallel deep-process-columns" aria-label="五栏成卡回传">
              <header><b>{sending ? '五栏成卡正在逐栏回传' : '五栏成卡回传'}</b><span>{columnAnswers.length}/5</span></header>
              {columnAnswers.map(renderLiveCard)}
            </div>
          )}
        </div>
      )}
      {sending && <footer className="deep-process-wait"><div className="deep-process-typing" aria-hidden="true"><span/><span/><span/></div><span>{continuingCue}</span></footer>}
    </section>
  );
}

function ArtifactCard({artifact, sessionId, apiBase, runId, onMerged, versions = [], scope = {}, onOpenPortrait}) {
  const [merging, setMerging] = useState(false);
  const [error, setError] = useState('');
  // Keep the action state responsive even when the parent session is only
  // refreshed by its polling loop.  The server status remains authoritative,
  // while this local flag closes the feedback gap after a successful merge.
  const [mergedLocally, setMergedLocally] = useState(false);
  const identity = artifactId(artifact);
  useEffect(() => { setMergedLocally(false); setError(''); }, [identity]);
  const name = safeText(artifact?.name || artifact?.title || artifact?.capability_name || '未命名候选能力');
  const summary = safeText(artifact?.deep_capability_portrait || artifact?.capability_image || artifact?.summary || artifact?.overview);
  const matchingVersions = versions.filter(item => (
    (safeText(artifact?.version_id) && safeText(item?.version_id) === safeText(artifact?.version_id))
    || (safeText(artifact?.capability_id) && safeText(item?.snapshot?.capability_id || item?.snapshot?.artifact_id) === safeText(artifact?.capability_id))
    || (safeText(artifact?.hypothesis_id) && safeText(item?.hypothesis_id) === safeText(artifact?.hypothesis_id))
  ));
  // An immutable formal v1 baseline is context, not the result of this turn.
  // Prefer a non-formal row when available so it cannot make an unversioned
  // legacy draft look already projected merely because it shares a hypothesis.
  const deepMatchingVersions = matchingVersions.filter(item => !['formal', 'baseline', 'deleted'].includes(safeText(item?.status).toLowerCase()));
  const version = deepMatchingVersions.find(item => safeText(item?.version_id) === safeText(artifact?.version_id))
    || deepMatchingVersions.find(item => safeText(item?.snapshot?.capability_id || item?.snapshot?.artifact_id) === safeText(artifact?.capability_id))
    || deepMatchingVersions.find(item => safeText(item?.hypothesis_id) && safeText(item?.hypothesis_id) === safeText(artifact?.hypothesis_id));
  const portraitModules = extractPortraitModules({
    ...artifact,
    ...(version?.snapshot && typeof version.snapshot === 'object' ? version.snapshot : {}),
    capability_card_draft: artifact?.capability_card_draft || version?.snapshot?.capability_card_draft,
  });
  // The session artifact is a compatibility projection and can retain the
  // pre-review ``pending`` flag after a reviewer verifies the SQLite row.
  // Prefer the matched durable version status, then fall back to the artifact
  // aliases for legacy/session-only drafts.
  const rawVersionStatus = safeText(version?.status || artifact?.version_status || artifact?.verification_status);
  const versionStatus = normalizeCapabilityVersionStatus(rawVersionStatus || 'pending_verification');
  const rejectedVersion = ['rejected', 'rolled_back', 'deleted'].includes(versionStatus);
  const failedVersion = ['cancelled', 'failed', 'blocked', 'partial'].includes(versionStatus);
  // Modern deep turns persist a pending capability version and project it into
  // the portrait automatically. Keep the legacy explicit merge action only
  // for artifacts that predate the version ledger; otherwise the button would
  // misleadingly suggest that the expert must perform a second merge.
  const projectionState = safeText(artifact?.draft_status || artifact?.merge_status || '').toLowerCase();
  const projectionIncomplete = ['partial', 'failed', 'blocked', 'error'].includes(projectionState)
    || failedVersion
    || rejectedVersion;
  const autoProjected = !projectionIncomplete && Boolean(
    (version?.version_id && !['formal', 'baseline'].includes(versionStatus))
    || (artifact?.version_id && !['formal', 'baseline', 'rejected', 'rolled_back', 'cancelled', 'failed', 'blocked', 'partial'].includes(versionStatus))
    || ['merged_pending_verification', 'merged'].includes(safeText(artifact?.merge_status || '').toLowerCase())
    || artifact?.merged === true,
  );
  const merged = !rejectedVersion && (mergedLocally || ['merged', 'merged_pending_verification', 'accepted'].includes(safeText(artifact?.merge_status || artifact?.status)));
  const projected = !rejectedVersion && (merged || autoProjected);
  const mergeUnavailable = rejectedVersion;
  const versionLabel = version?.version_no ? `v${version.version_no}` : artifact?.version_no ? `v${artifact.version_no}` : '';
  const evidenceRefs = Array.isArray(artifact?.evidence_ids) ? artifact.evidence_ids : Array.isArray(version?.evidence_refs) ? version.evidence_refs : [];
  const openPortrait = () => onOpenPortrait?.({
    name,
    modules: portraitModules,
    fallback: summary,
    meta: [autoProjected || merged ? '已固定到能力画像导航页' : '深度思考生成', versionLabel].filter(Boolean).join(' · '),
  });
  const merge = async () => {
    if (!runId || !sessionId || merging || projected || mergeUnavailable) return;
    setMerging(true); setError('');
    const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/sessions/${encodeURIComponent(sessionId)}/merge`, {
      method: 'POST',
      headers: {...deepScopeHeaders(scope), 'Content-Type': 'application/json', 'Idempotency-Key': `merge:${runId}:${sessionId}:${artifactId(artifact)}`},
      body: JSON.stringify({artifact_id: artifactId(artifact), mode: 'upsert'}),
    });
    setMerging(false);
    if (!result.ok) { setError(result.detail || '并入失败，请确认父任务能力画像已就绪。'); return; }
    // The API may return a durable ``partial`` result when the SQLite ledger
    // or filesystem projection is temporarily unavailable.  HTTP success
    // alone therefore does not mean the card was merged; only the explicit
    // boolean contract may flip the local action state.
    if (result.data?.merged !== true) {
      setError(result.data?.error || '并入尚未完成，已保留草稿；请稍后重试。');
      onMerged?.(result.data);
      return;
    }
    setMergedLocally(true);
    onMerged?.(result.data);
    window.dispatchEvent(new CustomEvent('equipment-capabilities-changed', {detail: {runId, capability: result.data?.capability || artifact}}));
  };
  return <article className={`deep-artifact-card${projected ? ' merged' : ''}`}>
    <header>
      <span className="deep-artifact-icon"><Sparkles size={15}/></span>
      <div>
        <b>{name}</b>
        <small>{autoProjected ? '已固定到能力画像导航页 · 待评议' : merged ? '已固定到能力画像导航页 · 待评议' : '深度思考生成 · 待固定'}{versionLabel ? ` · ${versionLabel}` : ''}</small>
      </div>
      <span className="deep-artifact-status">{autoProjected ? <><CheckCircle2 size={13}/>已固定</> : merged ? <><CheckCircle2 size={13}/>已固定</> : <><Clock3 size={13}/>候选</>}</span>
    </header>
    <button type="button" className="deep-artifact-portrait-launch" onClick={openPortrait}>
      <div className="deep-artifact-portrait-launch-copy">
        <b>五栏能力画像</b>
        <small>{portraitModules.length ? `${portraitModules.length} 栏已就绪 · 点击查看完整美观画像` : '点击查看能力画像'}</small>
      </div>
      <ChevronRight size={15}/>
    </button>
    {portraitModules.length > 0 ? (
      <div className="deep-artifact-portrait-preview">
        {portraitModules.slice(0, 3).map(item => (
          <button type="button" key={item.label} onClick={openPortrait}>
            <b>{item.label}</b>
            <span>{safeText(item.text).slice(0, 56)}{safeText(item.text).length > 56 ? '…' : ''}</span>
          </button>
        ))}
      </div>
    ) : summary ? (
      <button type="button" className="deep-artifact-portrait" onClick={openPortrait}>
        <AssistantMarkdown>{summary.slice(0, 420)}{summary.length > 420 ? '…' : ''}</AssistantMarkdown>
      </button>
    ) : null}
    <div className="deep-artifact-meta"><span className={`deep-version-status ${versionStatus}`}>{versionStatus === 'verified' || versionStatus === 'formal' ? '已核验' : versionStatus === 'rejected' ? '已驳回' : versionStatus === 'rolled_back' ? '已回滚' : '待核验'}</span>{version?.source && <span>来源：{safeText(version.source)}</span>}{evidenceRefs.length > 0 && <span>证据 {evidenceRefs.length} 条</span>}{artifact?.hypothesis_id && <code title={artifact.hypothesis_id}>假设 {safeText(artifact.hypothesis_id).slice(0, 24)}</code>}</div>
    {evidenceRefs.length > 0 && <div className="deep-artifact-evidence">证据引用：{evidenceRefs.slice(0, 6).map((ref, index) => <code key={`${ref}-${index}`}>{safeText(ref)}</code>)}</div>}
    <footer>
      {error && <span className="deep-inline-error"><CircleAlert size={13}/>{error}</span>}
      <button type="button" className="deep-artifact-view" onClick={openPortrait}><Sparkles size={13}/>查看画像</button>
      <button type="button" className="primary" disabled={projected || merging || mergeUnavailable} onClick={() => void merge()}>{merging ? <><RefreshCw size={13} className="spin"/>固定中…</> : rejectedVersion ? <><CircleAlert size={13}/>已驳回 · 请重新追问</> : autoProjected ? <><CheckCircle2 size={13}/>已固定到能力画像页</> : merged ? <><CheckCircle2 size={13}/>已固定到能力画像页</> : <><ArrowUp size={13}/>固定到能力画像页</>}</button>
    </footer>
  </article>;
}

/**
 * The actual panel.  `context` is intentionally plain JSON so callers can
 * pass a capability card, reference candidate, or just the active run query.
 */
export function DeepThinkingPanel({apiBase, run, context = {}, onClose, onChanged, onNavigationChange}) {
  const workbenchRunId = safeText(run?.run_id || context?.runId);
  const requestedBranchId = safeText(context?.branch_id || context?.branchId) || DEFAULT_BRANCH_ID;
  // Launchers create a fresh object while the parent workbench re-renders.
  // Compare the serialized visible context so the stream is not torn down and
  // rebuilt on every polling tick.
  const contextKey = useMemo(() => JSON.stringify(context || {}), [context]);
  const baseContext = useMemo(() => ({
    ...context,
    run_id: workbenchRunId,
    query: context?.query || [run?.topic, run?.supplemental_information].filter(Boolean).join('\n'),
  }), [contextKey, run?.topic, run?.supplemental_information, workbenchRunId]);
  const [sessions, setSessions] = useState([]);
  const [historyGroups, setHistoryGroups] = useState([]);
  const [collapsedGroups, setCollapsedGroups] = useState({});
  const [conversationRunId, setConversationRunId] = useState('');
  const [session, setSession] = useState(null);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [sending, setSending] = useState(false);
  const [draft, setDraft] = useState('');
  const [quotedContext, setQuotedContext] = useState('');
  const [copiedMessageId, setCopiedMessageId] = useState('');
  const [showJumpBottom, setShowJumpBottom] = useState(false);
  const [conversationHandoff, setConversationHandoff] = useState(false);
  const [nextQuestions, setNextQuestions] = useState([]);
  const [error, setError] = useState('');
  const [sessionsError, setSessionsError] = useState('');
  const [showArchivedSessions, setShowArchivedSessions] = useState(false);
  const [renamingSessionId, setRenamingSessionId] = useState('');
  const [renameDraft, setRenameDraft] = useState('');
  const [deleteConfirmSessionId, setDeleteConfirmSessionId] = useState('');
  const [sessionActionId, setSessionActionId] = useState('');
  const [stageEvents, setStageEvents] = useState([]);
  const [streamState, setStreamState] = useState('idle');
  const [activeJob, setActiveJob] = useState(null);
  const [activeBranchId, setActiveBranchId] = useState(
    () => requestedBranchId,
  );
  const [duringRunMode, setDuringRunMode] = useState('steer');
  const [showRunModeMenu, setShowRunModeMenu] = useState(false);
  const [contextUsageOpen, setContextUsageOpen] = useState(false);
  const [selectedSlashIndex, setSelectedSlashIndex] = useState(0);
  const [steerReceipts, setSteerReceipts] = useState({});
  const [steerSubmitting, setSteerSubmitting] = useState(false);
  const [branchActionMessageId, setBranchActionMessageId] = useState('');
  const [jobError, setJobError] = useState('');
  const [capabilityVersions, setCapabilityVersions] = useState([]);
  const [liveAnswer, setLiveAnswer] = useState('');
  const [lastAnswer, setLastAnswer] = useState(null);
  const [portraitViewer, setPortraitViewer] = useState(null);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const [capabilityCatalog, setCapabilityCatalog] = useState(EMPTY_DEEP_CAPABILITY_CATALOG);
  const [capabilityCatalogLoading, setCapabilityCatalogLoading] = useState(false);
  const [capabilityCatalogError, setCapabilityCatalogError] = useState('');
  const capabilityRequestRef = useRef(0);
  const [capabilityDrawerOpen, setCapabilityDrawerOpen] = useState(false);
  const [pluginPendingId, setPluginPendingId] = useState('');
  const [workspaceResources, setWorkspaceResources] = useState(EMPTY_WORKSPACE_RESOURCES);
  const [workspaceResourceLoading, setWorkspaceResourceLoading] = useState(false);
  const [workspaceResourceError, setWorkspaceResourceError] = useState('');
  const [workspaceResourceDraft, setWorkspaceResourceDraft] = useState(null);
  const [workspaceResourceSaving, setWorkspaceResourceSaving] = useState(false);
  const [workspacePackageDraft, setWorkspacePackageDraft] = useState(null);
  const [workspacePackageSaving, setWorkspacePackageSaving] = useState(false);
  const workspaceResourceRequestRef = useRef(0);
  const [selectedSkillIds, setSelectedSkillIds] = useState(
    () => Array.isArray(context?.active_skill_ids) ? context.active_skill_ids.map(safeText).filter(Boolean) : [],
  );
  // The global launcher opens the same panel as card actions, but a turn may
  // only be submitted after one equipment target is selected.  Keep the
  // selection local to this panel so switching a target never mutates the
  // parent result or any formal card snapshot.
  const targetOptions = useMemo(() => deepTargetOptionsFromContext(baseContext), [baseContext]);
  const explicitTarget = useMemo(() => deepTargetFromContext(baseContext), [baseContext]);
  const [selectedTargetIdentity, setSelectedTargetIdentity] = useState(
    () => deepTargetOptionKey(explicitTarget) || safeText(context?.target_identity || context?.targetIdentity),
  );
  const selectedTarget = useMemo(() => {
    if (explicitTarget) return explicitTarget;
    if (!selectedTargetIdentity) return null;
    return targetOptions.find(item => deepTargetOptionKey(item) === selectedTargetIdentity) || null;
  }, [explicitTarget, selectedTargetIdentity, targetOptions]);
  const targetContext = useMemo(() => {
    if (!selectedTarget?.value) return baseContext;
    const value = selectedTarget.value;
    const label = deepEquipmentLabel(value);
    return {
      ...baseContext,
      kind: selectedTarget.kind,
      candidate: value,
      reference_weapon: value,
      capability_id: value.capability_id || baseContext.capability_id || '',
      card_binding_id: value.card_binding_id || baseContext.card_binding_id || '',
      capability_name: baseContext.capability_name && !GENERIC_DEEP_TARGET_LABELS.has(baseContext.capability_name)
        ? baseContext.capability_name
        : label,
      hypothesis_id: value.hypothesis_id || baseContext.hypothesis_id || '',
      title: baseContext.title && !GENERIC_DEEP_TARGET_LABELS.has(baseContext.title)
        ? baseContext.title
        : `${label || '单装备'}深度思考`,
      focused_equipment: value,
      focused_equipment_identity: deepEquipmentIdentity(value),
    };
  }, [baseContext, selectedTarget]);
  // Keep the rest of the panel on the existing `normalizedContext` contract;
  // it now represents the explicitly selected single-equipment target when
  // the panel was opened from the global launcher.
  const normalizedContext = targetContext;
  const explicitDefaultSkillIds = useMemo(
    () => Array.isArray(normalizedContext?.active_skill_ids)
      ? normalizedContext.active_skill_ids.map(safeText).filter(Boolean)
      : [],
    [normalizedContext],
  );
  const kind = safeText(normalizedContext.kind || 'deep-thinking').toLowerCase().replace(/_/g, '-');
  const selectedTargetKey = deepTargetOptionKey(selectedTarget)
    || selectedTargetIdentity
    || safeText(normalizedContext.target_identity || normalizedContext.targetIdentity);
  const runId = safeText(conversationRunId || workbenchRunId);
  const requiresTarget = kind === 'deep-thinking' && !selectedTarget && !session?.session_id;
  const historyQueryLabel = safeText(session?.query || normalizedContext.query || run?.topic);
  const historyQueryParts = useMemo(() => splitQueryDisplay(historyQueryLabel), [historyQueryLabel]);
  const messagesRef = useRef(null);
  const wasSendingRef = useRef(false);
  const autoPositionedSessionRef = useRef('');
  const stickToBottomRef = useRef(true);
  const composerRef = useRef(null);
  const nestedModalOpen = Boolean(contextUsageOpen || portraitViewer || capabilityDrawerOpen);
  const dialogRef = useOverlay(true, {
    onEscape: () => {
      if (portraitViewer) {
        setPortraitViewer(null);
        return;
      }
      if (capabilityDrawerOpen) {
        setCapabilityDrawerOpen(false);
        return;
      }
      if (showRunModeMenu) {
        setShowRunModeMenu(false);
        return;
      }
      if (renamingSessionId) {
        setRenamingSessionId('');
        setRenameDraft('');
        return;
      }
      if (deleteConfirmSessionId) {
        setDeleteConfirmSessionId('');
        return;
      }
      if (quotedContext) {
        setQuotedContext('');
        return;
      }
      if (draft.startsWith('/')) {
        setDraft('');
        return;
      }
      onClose?.();
    },
  });
  // Requests can overlap when an expert rapidly switches sessions or the
  // parent run changes while a poll is in flight. Keep the latest response
  // authoritative so an older response cannot replace the visible transcript.
  const sessionsRequestRef = useRef(0);
  const sessionRequestRef = useRef(0);
  const versionsRequestRef = useRef(0);
  const capabilitySelectionSourceRef = useRef('');
  const selectedSkillScopeRef = useRef({
    sessionId: '',
    branchId: safeText(context?.branch_id || context?.branchId) || DEFAULT_BRANCH_ID,
  });
  const conversationNonceRef = useRef(newRequestNonce());
  const messageNonceRef = useRef(newRequestNonce());
  const forkRequestRef = useRef(new Map());
  const streamCursorRef = useRef(0);
  const streamSessionRef = useRef('');
  const lastQuestionRef = useRef('');
  const lastTurnAuthoringRef = useRef(false);
  // After「新对话」, keep the composer on a blank draft.  Auto-selecting the
  // latest/same-run history row would reopen the previous transcript (and its
  // 最终成果 cards) the next time the session list refreshes.
  const freshCompositionRef = useRef(false);
  const preferredSessionId = safeText(normalizedContext.session_id || normalizedContext.sessionId);
  const activeTurnFocus = resolveDeepTurnFocus(session, normalizedContext.focus);
  const title = contextTitle(normalizedContext, run);
  const focusedEquipmentLabel = deepEquipmentLabel(
    normalizedContext.focused_equipment
    || normalizedContext.candidate
    || normalizedContext.reference_weapon
    || {name: normalizedContext.capability_name},
  );
  const [welcomeSuggestions, setWelcomeSuggestions] = useState(() => randomWelcomeSuggestions(normalizedContext));
  // Keep the stream loop aware of work that starts after an idle stream has
  // been closed, without making the loop poll an inactive session forever.
  const activeJobId = safeText(activeJob?.job_id || activeJob?.id);
  const sendingRef = useRef(false);
  const activeJobRef = useRef(null);
  const streamStateRef = useRef('idle');
  useEffect(() => { sendingRef.current = sending; }, [sending]);
  useEffect(() => { streamStateRef.current = streamState; }, [streamState]);
  useEffect(() => {
    // A card/reference launcher supplies an explicit target.  A global launch
    // starts unbound and must be re-selected whenever its parent context/run
    // changes, preventing a stale equipment identity from leaking into a new
    // Query.
    setSelectedTargetIdentity(
      explicitTarget
        ? deepTargetOptionKey(explicitTarget)
        : safeText(normalizedContext.target_identity || normalizedContext.targetIdentity),
    );
  }, [explicitTarget, normalizedContext.targetIdentity, normalizedContext.target_identity, runId]);
  useEffect(() => {
    setWelcomeSuggestions(randomWelcomeSuggestions(normalizedContext));
  }, [selectedTargetKey, workbenchRunId]);
  useEffect(() => {
    const status = safeText(activeJob?.status).toLowerCase();
    activeJobRef.current = activeJob && !isTerminalJob(activeJob) ? activeJob : null;
  }, [activeJob]);
  const runningBranchId = activeJob && !isTerminalJob(activeJob)
    ? safeText(activeJob.branch_id)
    : '';
  const branchNavigation = resolveDeepBranchNavigation({
    session,
    currentBranchId: activeBranchId,
    requestedBranchId,
    runningBranchId,
    preferredSessionId,
  });
  useEffect(() => {
    setActiveBranchId(current => (
      current === branchNavigation.branchId ? current : branchNavigation.branchId
    ));
  }, [branchNavigation.branchId]);
  const loadCapabilities = useCallback(async ({quiet = false} = {}) => {
    const requestId = ++capabilityRequestRef.current;
    if (!quiet) setCapabilityCatalogLoading(true);
    setCapabilityCatalogError('');
    const capabilityPath = session?.session_id && workbenchRunId
      ? `/runs/${encodeURIComponent(workbenchRunId)}/deep-thinking/sessions/${encodeURIComponent(session.session_id)}/capabilities`
      : '/deep-thinking/capabilities';
    const result = await apiRequest(apiBase, capabilityPath, {
      headers: deepScopeHeaders(normalizedContext),
    });
    if (requestId !== capabilityRequestRef.current) return null;
    setCapabilityCatalogLoading(false);
    if (!result.ok) {
      setCapabilityCatalogError(result.detail || '无法读取深研能力目录。');
      return null;
    }
    const next = normalizeDeepCapabilityCatalog(result.data);
    setCapabilityCatalog(next);
    setSelectedSkillIds(current => reconcileActiveSkillIds(current, next));
    return next;
  }, [apiBase, normalizedContext, session?.session_id, workbenchRunId]);
  useEffect(() => { void loadCapabilities(); }, [loadCapabilities]);
  const workspaceResourceBasePath = useMemo(() => {
    const targetRun = runId || workbenchRunId;
    const sessionId = safeText(session?.session_id);
    return targetRun && sessionId
      ? `/runs/${encodeRun(targetRun)}/deep-thinking/sessions/${encodeURIComponent(sessionId)}/workspace/resources`
      : '';
  }, [runId, session?.session_id, workbenchRunId]);
  const loadWorkspaceResources = useCallback(async ({quiet = false} = {}) => {
    const requestId = ++workspaceResourceRequestRef.current;
    if (!workspaceResourceBasePath) {
      setWorkspaceResources(EMPTY_WORKSPACE_RESOURCES);
      setWorkspaceResourceDraft(null);
      setWorkspaceResourceError('');
      return null;
    }
    if (!quiet) setWorkspaceResourceLoading(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, workspaceResourceBasePath, {
      headers: deepScopeHeaders(normalizedContext),
    });
    if (requestId !== workspaceResourceRequestRef.current) return null;
    if (!quiet) setWorkspaceResourceLoading(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || '无法读取装备工作区资源。');
      setWorkspaceResources(EMPTY_WORKSPACE_RESOURCES);
      return null;
    }
    const next = normalizeDeepWorkspaceResources(result.data);
    setWorkspaceResources(next);
    return next;
  }, [apiBase, normalizedContext, workspaceResourceBasePath]);
  useEffect(() => {
    setWorkspaceResources(EMPTY_WORKSPACE_RESOURCES);
    setWorkspaceResourceDraft(null);
    setWorkspacePackageDraft(null);
    setWorkspaceResourceError('');
    workspaceResourceRequestRef.current += 1;
  }, [workspaceResourceBasePath]);
  useEffect(() => {
    if (!capabilityDrawerOpen || !workspaceResourceBasePath) return;
    void loadWorkspaceResources({quiet: true});
  }, [capabilityDrawerOpen, loadWorkspaceResources, workspaceResourceBasePath]);
  const openWorkspaceResource = async (kind, name) => {
    if (!workspaceResourceBasePath) return;
    const resourceKind = safeText(kind);
    const resourceName = safeText(name);
    if (!resourceKind || !resourceName) return;
    setWorkspaceResourceLoading(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/${encodeURIComponent(resourceKind)}/${resourceName.split('/').map(encodeURIComponent).join('/')}`, {
      headers: deepScopeHeaders(normalizedContext),
    });
    setWorkspaceResourceLoading(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || '无法读取资源内容。');
      return;
    }
    const resource = result.data?.resource || {};
    setWorkspaceResourceDraft({
      kind: safeText(resource.kind || resourceKind),
      name: safeText(resource.name || resourceName),
      content: String(resource.content ?? ''),
      sha256: safeText(resource.sha256),
      version_id: safeText(resource.version_id),
      versions: Array.isArray(resource.versions) ? resource.versions : [],
      validation: resource.validation || null,
      isNew: false,
    });
  };
  const openWorkspacePluginPackage = async draft => {
    if (!workspaceResourceBasePath || draft?.kind !== 'plugin') return;
    const pluginId = safeText(draft.name).split('/')[0];
    const names = (workspaceResources.resources?.plugin || []).filter(name => safeText(name).split('/')[0] === pluginId);
    if (!pluginId || !names.length) return;
    setWorkspacePackageSaving(true);
    setWorkspaceResourceError('');
    const loaded = await Promise.all(names.map(async name => {
      const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/plugin/${name.split('/').map(encodeURIComponent).join('/')}`, {headers: deepScopeHeaders(normalizedContext)});
      return {name, result};
    }));
    setWorkspacePackageSaving(false);
    const failed = loaded.find(item => !item.result.ok);
    if (failed) {
      setWorkspaceResourceError(failed.result.detail || '无法读取 Plugin 包文件。');
      return;
    }
    const files = {};
    const base_versions = {};
    loaded.forEach(({name, result}) => {
      const resource = result.data?.resource || {};
      files[name] = String(resource.content ?? '');
      if (resource.version_id) base_versions[name] = safeText(resource.version_id);
    });
    setWorkspacePackageDraft({pluginId, files, base_versions, mergeResult: null});
  };
  const previewWorkspacePluginPackage = async draft => {
    if (!workspaceResourceBasePath || !draft?.pluginId) return;
    setWorkspacePackageSaving(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/plugin/${encodeURIComponent(draft.pluginId)}/merge-package`, {
      method: 'POST',
      headers: {...deepScopeHeaders(normalizedContext), 'Content-Type': 'application/json'},
      body: JSON.stringify({base_versions: draft.base_versions || {}, files: draft.files || {}}),
    });
    setWorkspacePackageSaving(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || 'Plugin 包合并预览失败。');
      return;
    }
    setWorkspacePackageDraft({...draft, mergeResult: result.data?.merge || {}});
  };
  const applyWorkspacePluginPackage = async draft => {
    if (!workspaceResourceBasePath || !draft?.pluginId || !draft.mergeResult?.atomic_ready) return;
    setWorkspacePackageSaving(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/plugin/${encodeURIComponent(draft.pluginId)}/merge-package/apply`, {
      method: 'POST',
      headers: {...deepScopeHeaders(normalizedContext, {legacyRole: 'admin'}), 'Content-Type': 'application/json', 'Idempotency-Key': `workspace-plugin-package-${draft.pluginId}-${newRequestNonce()}`},
      body: JSON.stringify({base_versions: draft.base_versions || {}, files: draft.files || {}}),
    });
    setWorkspacePackageSaving(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || 'Plugin 包原子提交失败。');
      return;
    }
    setWorkspacePackageDraft({...draft, mergeResult: result.data?.merge || {}});
    await loadWorkspaceResources({quiet: true});
    await loadCapabilities({quiet: true});
  };
  const createWorkspaceResourceDraft = kind => {
    const suffix = new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14);
    const normalizedKind = safeText(kind).toLowerCase();
    const templates = {
      skill: {
        name: `local-skill-${suffix}/SKILL.md`,
        content: `---\nname: local-skill-${suffix}\ndescription: 装备工作区本地程序性 Skill\nprocedure:\n  steps: [提出正交假设, 设计验证探针]\n  required_artifacts: [ProbePlan]\n  quality_gates: [机制差异明确]\n  stop_conditions: [无新增高价值假设]\n---\n记录这个装备专用的研究步骤、工具使用边界和判断标准。\n`,
      },
      plugin: {
        name: `local-plugin-${suffix}/plugin.json`,
        content: `${JSON.stringify({
          $schema: 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
          name: `local-plugin-${suffix}`,
          description: '装备工作区本地 Agent Plugin',
          extensions: {
            'dev.equipment-deep-research': {
              displayName: `本地研究 Plugin ${suffix}`,
              category: '研究能力',
              defaultEnabled: false,
            },
          },
        }, null, 2)}\n`,
      },
      config: {
        name: 'runtime.json',
        content: `${JSON.stringify({
          active_skill_ids: [],
          disabled_skill_ids: [],
          deep_runtime_budget: {max_turns: 12, max_tool_calls: 12},
        }, null, 2)}\n`,
      },
    };
    const template = templates[normalizedKind];
    if (!template) return;
    setWorkspaceResourceError('');
    setWorkspaceResourceDraft({kind: normalizedKind, ...template, isNew: true});
  };
  const saveWorkspaceResource = async draft => {
    if (!workspaceResourceBasePath || !draft) return;
    const kind = safeText(draft.kind);
    const name = safeText(draft.name);
    if (!kind || !name) return;
    setWorkspaceResourceSaving(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/${encodeURIComponent(kind)}/${name.split('/').map(encodeURIComponent).join('/')}`, {
      method: 'PUT',
      headers: {
        ...deepScopeHeaders(normalizedContext, {legacyRole: 'admin'}),
        'Content-Type': 'application/json',
        'Idempotency-Key': `workspace-resource-save-${newRequestNonce()}`,
      },
      body: JSON.stringify({
        content: String(draft.content ?? ''),
        ...(draft.sha256 ? {expected_sha256: draft.sha256} : {}),
      }),
    });
    setWorkspaceResourceSaving(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || '资源保存失败。');
      return;
    }
    setWorkspaceResources(normalizeDeepWorkspaceResources(result.data));
    const resource = result.data?.resource || {};
    setWorkspaceResourceDraft({
      kind: safeText(resource.kind || kind),
      name: safeText(resource.name || name),
      content: String(resource.content ?? draft.content ?? ''),
      sha256: safeText(resource.sha256),
      version_id: safeText(resource.version_id),
      versions: Array.isArray(resource.versions) ? resource.versions : (draft.versions || []),
      validation: resource.validation || result.data?.validation || null,
      isNew: false,
    });
    await loadWorkspaceResources({quiet: true});
    await loadCapabilities({quiet: true});
  };
  const mergeWorkspaceResource = async draft => {
    if (!workspaceResourceBasePath || !draft || draft.isNew || !draft.version_id) return;
    const kind = safeText(draft.kind);
    const name = safeText(draft.name);
    if (!kind || !name) return;
    setWorkspaceResourceSaving(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/${encodeURIComponent(kind)}/${name.split('/').map(encodeURIComponent).join('/')}/merge`, {
      method: 'POST',
      headers: {
        ...deepScopeHeaders(normalizedContext),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({base_version_id: draft.version_id, content: String(draft.content ?? '')}),
    });
    setWorkspaceResourceSaving(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || '草稿合并失败。');
      return;
    }
    const merge = result.data?.merge || {};
    const resource = result.data?.resource || {};
    setWorkspaceResourceDraft({
      ...draft,
      content: String(merge.content ?? draft.content ?? ''),
      sha256: safeText(merge.current_sha256 || resource.sha256),
      version_id: safeText(resource.version_id),
      validation: null,
      mergeResult: merge,
      isNew: false,
    });
  };
  const restoreWorkspaceResource = async (draft, version) => {
    if (!workspaceResourceBasePath || !draft || !version?.version_id || draft.isNew) return;
    const kind = safeText(draft.kind);
    const name = safeText(draft.name);
    if (!kind || !name) return;
    setWorkspaceResourceSaving(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/${encodeURIComponent(kind)}/${name.split('/').map(encodeURIComponent).join('/')}/restore/${encodeURIComponent(version.version_id)}`, {
      method: 'POST',
      headers: {
        ...deepScopeHeaders(normalizedContext, {legacyRole: 'admin'}),
        'Content-Type': 'application/json',
        'Idempotency-Key': `workspace-resource-restore-${newRequestNonce()}`,
      },
      body: JSON.stringify({expected_sha256: draft.sha256 || ''}),
    });
    setWorkspaceResourceSaving(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || '历史版本恢复失败。');
      return;
    }
    const resource = result.data?.resource || {};
    setWorkspaceResourceDraft({
      kind: safeText(resource.kind || kind),
      name: safeText(resource.name || name),
      content: String(resource.content ?? ''),
      sha256: safeText(resource.sha256),
      version_id: safeText(resource.version_id),
      versions: Array.isArray(resource.versions) ? resource.versions : [],
      validation: resource.validation || null,
      isNew: false,
    });
    setWorkspaceResources(normalizeDeepWorkspaceResources(result.data));
    await loadWorkspaceResources({quiet: true});
    await loadCapabilities({quiet: true});
  };
  const deleteWorkspaceResource = async draft => {
    if (!workspaceResourceBasePath || !draft || draft.isNew) return;
    const kind = safeText(draft.kind);
    const name = safeText(draft.name);
    if (!kind || !name) return;
    setWorkspaceResourceSaving(true);
    setWorkspaceResourceError('');
    const result = await apiRequest(apiBase, `${workspaceResourceBasePath}/${encodeURIComponent(kind)}/${name.split('/').map(encodeURIComponent).join('/')}`, {
      method: 'DELETE',
      headers: {
        ...deepScopeHeaders(normalizedContext, {legacyRole: 'admin'}),
        'Idempotency-Key': `workspace-resource-delete-${newRequestNonce()}`,
      },
    });
    setWorkspaceResourceSaving(false);
    if (!result.ok) {
      setWorkspaceResourceError(result.detail || '资源删除失败。');
      return;
    }
    setWorkspaceResourceDraft(null);
    setWorkspaceResources(normalizeDeepWorkspaceResources(result.data));
    await loadWorkspaceResources({quiet: true});
    await loadCapabilities({quiet: true});
  };
  const capabilitySkillKey = capabilityCatalog.skills.map(skill => skill.skill_id).join('|');
  const persistedBranchSkillIds = useMemo(() => branchActiveSkillIds(
    session,
    activeBranchId,
    session?.session_id ? [] : explicitDefaultSkillIds,
  ), [activeBranchId, explicitDefaultSkillIds, session?.active_skill_ids, session?.session_id, session?.working_memory]);
  const persistedBranchSkillKey = persistedBranchSkillIds.join('\u0000');
  useEffect(() => {
    const sessionId = safeText(session?.session_id);
    const branchId = activeBranchId || DEFAULT_BRANCH_ID;
    const scopeChanged = (
      selectedSkillScopeRef.current.sessionId !== sessionId
      || selectedSkillScopeRef.current.branchId !== branchId
    );
    selectedSkillScopeRef.current = {sessionId, branchId};
    if (!capabilityCatalog.skills.length) {
      if (scopeChanged) setSelectedSkillIds([]);
      capabilitySelectionSourceRef.current = '';
      return;
    }
    const sourceKey = `${sessionId}\u0000${branchId}\u0000${persistedBranchSkillKey}`;
    setSelectedSkillIds(current => {
      if (capabilitySelectionSourceRef.current === sourceKey) {
        return reconcileActiveSkillIds(current, capabilityCatalog);
      }
      capabilitySelectionSourceRef.current = sourceKey;
      return reconcileActiveSkillIds(persistedBranchSkillIds, capabilityCatalog);
    });
  }, [activeBranchId, capabilityCatalog.limits.max_active_skills, capabilitySkillKey, persistedBranchSkillKey, session?.session_id]);
  const toggleSkill = (skillId, enabled) => {
    const result = toggleActiveSkillId(selectedSkillIds, skillId, enabled, capabilityCatalog);
    if (result.limited) {
      setCapabilityCatalogError(`每轮最多选择 ${capabilityCatalog.limits.max_active_skills} 个 Skill。`);
      return;
    }
    setCapabilityCatalogError('');
    setSelectedSkillIds(result.selected);
  };
  const togglePlugin = async (plugin, enabled) => {
    const pluginId = safeText(plugin?.plugin_id);
    if (!pluginId || pluginPendingId) return;
    setPluginPendingId(pluginId);
    setCapabilityCatalogError('');
    const pluginPath = plugin.source === 'workspace' && session?.session_id && workbenchRunId
      ? `/runs/${encodeURIComponent(workbenchRunId)}/deep-thinking/sessions/${encodeURIComponent(session.session_id)}/plugins/${encodeURIComponent(pluginId)}`
      : `/deep-thinking/plugins/${encodeURIComponent(pluginId)}`;
    const result = await apiRequest(apiBase, pluginPath, {
      method: 'PATCH',
      headers: {...deepScopeHeaders(normalizedContext, {legacyRole: 'admin'}), 'Content-Type': 'application/json'},
      body: JSON.stringify({enabled: Boolean(enabled)}),
    });
    setPluginPendingId('');
    if (!result.ok) {
      setCapabilityCatalogError(result.detail || 'Plugin 状态保存失败。');
      return;
    }
    await loadCapabilities({quiet: true});
  };
  useEffect(() => {
    if (!branchNavigation.shouldPublish) return;
    onNavigationChange?.({
      sessionId: safeText(session.session_id),
      branchId: activeBranchId || DEFAULT_BRANCH_ID,
      targetIdentity: selectedTargetKey,
    });
  }, [activeBranchId, branchNavigation.shouldPublish, onNavigationChange, selectedTargetKey, session?.session_id]);
  useEffect(() => {
    if (
      preferredSessionId
      && safeText(session?.session_id) === preferredSessionId
      && safeText(session?.status).toLowerCase() === 'archived'
    ) {
      setShowArchivedSessions(true);
    }
  }, [preferredSessionId, session?.session_id, session?.status]);

  const loadSessions = useCallback(async (selectLatest = true) => {
    const requestId = ++sessionsRequestRef.current;
    if (!workbenchRunId && !runId) { setSessions([]); setHistoryGroups([]); setSession(null); return; }
    setLoadingSessions(true); setSessionsError('');
    const query = new URLSearchParams({
      current_run_id: workbenchRunId || runId,
      include_archived: 'true',
      limit: '200',
    });
    const result = await apiRequest(apiBase, `/deep-thinking/sessions/history?${query.toString()}`, {headers: deepScopeHeaders(normalizedContext)});
    if (requestId !== sessionsRequestRef.current) return;
    setLoadingSessions(false);
    if (!result.ok) {
      // Compatibility fallback for older servers without the history route.
      if (runId) {
        const legacy = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/sessions`, {headers: deepScopeHeaders(normalizedContext)});
        if (requestId !== sessionsRequestRef.current) return;
        if (!legacy.ok) { setSessionsError(result.detail || legacy.detail || '无法读取专家会话。'); return; }
        const legacyItems = Array.isArray(legacy.data?.items) ? legacy.data.items : [];
        setSessions(legacyItems);
        setHistoryGroups([{
          group_key: `run:${runId}`,
          query: safeText(normalizedContext.query || run?.topic) || '当前 Query 任务',
          is_current: true,
          session_count: legacyItems.length,
          sessions: legacyItems,
          updated_at: legacyItems[0]?.updated_at || '',
          run_ids: [runId],
        }]);
        if (selectLatest) setSession(current => {
          if (freshCompositionRef.current) return null;
          const next = pickDeepSessionForTarget(legacyItems, {
            ...normalizedContext,
            capability_name: deepEquipmentLabel(normalizedContext.candidate || normalizedContext.reference_weapon || normalizedContext.focused_equipment) || normalizedContext.capability_name,
          }, {
            preferredSessionId,
            currentSessionId: current?.session_id,
            runId: workbenchRunId || runId,
          });
          return next || null;
        });
        return;
      }
      setSessionsError(result.detail || '无法读取专家会话。');
      return;
    }
    const groups = Array.isArray(result.data?.groups) ? result.data.groups : [];
    const items = Array.isArray(result.data?.items) ? result.data.items : [];
    setHistoryGroups(groups);
    setSessions(items);
    setCollapsedGroups(current => {
      const next = {...current};
      groups.forEach(group => {
        const key = safeText(group?.group_key);
        if (!key) return;
        if (group?.is_current) next[key] = false;
        else if (!(key in next)) next[key] = true;
      });
      return next;
    });
    if (selectLatest) setSession(current => {
      if (freshCompositionRef.current) return null;
      const flat = groups.flatMap(group => Array.isArray(group?.sessions) ? group.sessions : []);
      const next = pickDeepSessionForTarget(flat, {
        ...normalizedContext,
        capability_name: deepEquipmentLabel(normalizedContext.candidate || normalizedContext.reference_weapon || normalizedContext.focused_equipment) || normalizedContext.capability_name,
      }, {
        preferredSessionId,
        currentSessionId: current?.session_id,
        runId: workbenchRunId || runId,
      });
      if (next) setConversationRunId(sessionRunId(next) || workbenchRunId || runId);
      return next || null;
    });
  }, [apiBase, normalizedContext, preferredSessionId, run?.topic, runId, workbenchRunId]);

  const openHistorySession = useCallback(async item => {
    const targetRun = sessionRunId(item) || runId || workbenchRunId;
    if (!item?.session_id || !targetRun) return;
    freshCompositionRef.current = false;
    setDeleteConfirmSessionId('');
    setConversationRunId(targetRun);
    setError('');
    setJobError('');
    setActiveJob(null);
    setActiveBranchId(DEFAULT_BRANCH_ID);
    setSteerReceipts({});
    setShowRunModeMenu(false);
    setLiveAnswer('');
    setLastAnswer(null);
    setStageEvents([]);
    setSending(false);
    streamCursorRef.current = 0;
    streamSessionRef.current = '';
    setSession(item);
    onNavigationChange?.({
      sessionId: safeText(item.session_id),
      branchId: DEFAULT_BRANCH_ID,
      targetIdentity: selectedTargetKey,
    });
    const requestId = ++sessionRequestRef.current;
    setLoadingSession(true);
    const result = await apiRequest(apiBase, `/runs/${encodeRun(targetRun)}/deep-thinking/sessions/${encodeURIComponent(item.session_id)}`, {headers: deepScopeHeaders(normalizedContext)});
    if (requestId !== sessionRequestRef.current) return;
    setLoadingSession(false);
    if (!result.ok) { setError(result.detail || '无法读取会话内容。'); return; }
    setSession(result.data?.session || item);
  }, [apiBase, normalizedContext, onNavigationChange, runId, selectedTargetKey, workbenchRunId]);

  const loadSession = useCallback(async (sessionId, {silent = false} = {}) => {
    const requestId = ++sessionRequestRef.current;
    const targetRun = runId || workbenchRunId;
    if (!targetRun || !sessionId) return;
    if (streamSessionRef.current && streamSessionRef.current !== sessionId) setLiveAnswer('');
    if (!silent) {
      setLoadingSession(true);
      setError('');
    }
    const result = await apiRequest(apiBase, `/runs/${encodeRun(targetRun)}/deep-thinking/sessions/${encodeURIComponent(sessionId)}`, {headers: deepScopeHeaders(normalizedContext)});
    if (requestId !== sessionRequestRef.current) return;
    if (!silent) setLoadingSession(false);
    if (!result.ok) {
      if (!silent) setError(result.detail || '无法读取会话内容。');
      return;
    }
    setSession(current => applySessionSnapshot(current, result.data?.session || null));
  }, [apiBase, normalizedContext, runId, workbenchRunId]);

  const loadVersions = useCallback(async (cardBindingId = '', hypothesisId = '', capabilityId = '') => {
    const requestId = ++versionsRequestRef.current;
    const wantedBinding = safeText(cardBindingId);
    const wantedHypothesis = safeText(hypothesisId);
    const wantedCapability = safeText(capabilityId);
    // Version chain is conversation-scoped in the panel: without an explicit
    // binding from the active session, do not fall back to launcher context or
    // a previous turn's rows will linger on the welcome / 新对话 screen.
    if (!runId || (!wantedBinding && !wantedHypothesis && !wantedCapability)) {
      setCapabilityVersions([]);
      return;
    }
    const query = wantedBinding ? `?card_binding_id=${encodeURIComponent(wantedBinding)}` : '';
    const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/capability-versions${query}`, {headers: deepScopeHeaders(normalizedContext)});
    if (requestId !== versionsRequestRef.current) return;
    if (result.ok && Array.isArray(result.data?.versions)) {
      const hiddenStatuses = new Set(['deleted', 'rejected', 'rolled_back', 'cancelled', 'failed', 'blocked']);
      const rows = result.data.versions.filter(version => {
        const status = normalizeCapabilityVersionStatus(version?.status);
        if (hiddenStatuses.has(status)) return false;
        if (wantedBinding && safeText(version?.card_binding_id) === wantedBinding) return true;
        if (wantedHypothesis && safeText(version?.hypothesis_id) === wantedHypothesis) return true;
        const snapshot = version?.snapshot && typeof version.snapshot === 'object' ? version.snapshot : {};
        return Boolean(wantedCapability && safeText(snapshot.capability_id) === wantedCapability);
      });
      setCapabilityVersions(rows);
      return;
    }
    setCapabilityVersions([]);
  }, [apiBase, normalizedContext, runId]);

  useEffect(() => {
    // Invalidate an in-flight request whenever the workbench switches to a new
    // parent run or equipment target.  Selecting another Query's history session
    // only updates conversationRunId and must not wipe the transcript.
    conversationNonceRef.current = newRequestNonce();
    messageNonceRef.current = newRequestNonce();
    sessionsRequestRef.current += 1;
    sessionRequestRef.current += 1;
    versionsRequestRef.current += 1;
    freshCompositionRef.current = false;
    setConversationRunId(workbenchRunId);
    setSession(null);
    setSessions([]);
    setHistoryGroups([]);
    setNextQuestions([]);
    setStageEvents([]);
    setCapabilityVersions([]);
    setActiveJob(null);
    setActiveBranchId(requestedBranchId);
    setSteerReceipts({});
    setShowRunModeMenu(false);
    setSteerSubmitting(false);
    setBranchActionMessageId('');
    forkRequestRef.current.clear();
    setJobError('');
    setLiveAnswer('');
    setLastAnswer(null);
    setShowArchivedSessions(false);
    setRenamingSessionId('');
    setRenameDraft('');
    setDeleteConfirmSessionId('');
    setSessionActionId('');
    streamCursorRef.current = 0;
    streamSessionRef.current = '';
  }, [workbenchRunId, selectedTargetKey]);
  useEffect(() => { void loadSessions(true); }, [loadSessions]);
  useEffect(() => {
    if (!session?.session_id) return;
    void loadSession(session.session_id, {silent: true});
    const timer = setInterval(() => { void loadSession(session.session_id, {silent: true}); }, 8000);
    return () => clearInterval(timer);
  }, [loadSession, session?.session_id]);
  useEffect(() => {
    if (!session?.session_id) {
      versionsRequestRef.current += 1;
      setCapabilityVersions([]);
      return;
    }
    void loadVersions(
      session.card_binding_id || normalizedContext.card_binding_id || '',
      session.hypothesis_id || normalizedContext.hypothesis_id || '',
      session.capability_id || normalizedContext.capability_id || '',
    );
  }, [loadVersions, normalizedContext.card_binding_id, normalizedContext.capability_id, normalizedContext.hypothesis_id, session?.card_binding_id, session?.capability_id, session?.hypothesis_id, session?.session_id]);
  useEffect(() => {
    if (!runId || !session?.session_id || typeof fetch === 'undefined') {
      setStreamState('idle');
      return undefined;
    }
    const sessionId = session.session_id;
    const url = `${String(apiBase || '').replace(/\/$/, '')}/runs/${encodeRun(runId)}/deep-thinking/sessions/${encodeURIComponent(sessionId)}/events`;
    const controller = new AbortController();
    let cancelled = false;
    let endedIdle = false;
    let attempts = 0;
    // A new session starts a new stream.  When reopening the same session the
    // cursor is retained, enabling replay after a transient network failure.
    if (streamSessionRef.current !== sessionId) {
      streamSessionRef.current = sessionId;
      streamCursorRef.current = 0;
      setStageEvents([]);
      setLiveAnswer('');
    }
    const onEvent = event => {
      try {
        const payload = JSON.parse(event.data || '{}');
        const sequence = Number(payload.sequence || event.lastEventId || 0);
        if (sequence && sequence <= streamCursorRef.current) return;
        if (sequence) streamCursorRef.current = sequence;
        setStreamState(current => (current === 'live' ? current : 'live'));
        setStageEvents(current => {
          // Modern events carry the monotonic SQLite sequence.  A few legacy
          // adapters omit it; retain those visible summaries instead of
          // repeatedly replacing every sequence-less row with the latest one.
          if (!sequence) return [...current, payload].slice(-80);
          const next = [...current.filter(item => Number(item.sequence || 0) !== sequence), payload]
            .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0));
          return next.slice(-80);
        });
        const eventType = safeText(payload.event_type);
        const isSteerReceiptEvent = ['deep_steer_accepted', 'deep_steer_applied', 'deep_steer_parked'].includes(eventType);
        if (isSteerReceiptEvent) {
          const messageId = safeText(payload.message_id);
          const steerId = safeText(payload.steer_id);
          const receiptStatus = eventType === 'deep_steer_applied'
            ? 'applied'
            : eventType === 'deep_steer_parked'
              ? 'parked'
              : 'accepted';
          if (messageId || steerId) {
            setSteerReceipts(current => {
              const previous = current[messageId] || Object.values(current).find(item => safeText(item?.steer_id) === steerId) || {};
              const key = messageId || safeText(previous.message_id) || steerId;
              return {
                ...current,
                [key]: mergeTranscriptMessage(previous, {
                  ...payload,
                  message_id: messageId || previous.message_id,
                  steer_id: steerId || previous.steer_id,
                  status: receiptStatus,
                }),
              };
            });
          }
          if (messageId) {
            setSession(current => current ? {
              ...current,
              messages: (Array.isArray(current.messages) ? current.messages : []).map(item => (
                safeText(item?.message_id) === messageId
                  ? mergeTranscriptMessage(item, {status: receiptStatus, message_kind: 'steer'})
                  : item
              )),
            } : current);
          }
          if (eventType === 'deep_steer_parked' && payload.next_job_id) {
            setActiveJob(current => {
              const sourceJobId = safeText(payload.job_id);
              const currentJobId = safeText(current?.job_id || current?.id);
              if (currentJobId && currentJobId !== sourceJobId) return current;
              const next = {
                job_id: safeText(payload.next_job_id),
                parent_job_id: sourceJobId,
                session_id: safeText(payload.session_id) || sessionId,
                branch_id: safeText(payload.branch_id) || DEFAULT_BRANCH_ID,
                stage: 'queued',
                status: 'queued',
                progress: 0,
              };
              const merged = mergeDeepJobState(current, next);
              activeJobRef.current = merged && !isTerminalJob(merged) ? merged : null;
              return merged;
            });
            setSending(true);
          }
          void loadSession(sessionId, {silent: true});
        } else if (eventType === 'deep_branch_created') {
          void loadSession(sessionId, {silent: true});
        }
        // Reopening an existing session can happen while its async job is
        // still running.  Session reads intentionally contain no provider
        // handle, so recover the durable public job id/state from replayed
        // events and resume the normal job poller automatically.
        const eventJobId = safeText(payload.job_id);
        // Content events inherit the producer job id and the public event
        // projection may give them a compatibility `running` status.  They
        // are not job-state transitions: allowing a candidate/message event
        // to update activeJob can resurrect a completed historical turn.
        const isJobStateEvent = eventType === 'deep_stage' || [
          'deep_research_completed',
          'deep_research_failed',
          'deep_research_blocked',
          'deep_job_cancelled',
          'deep_job_interrupted',
        ].includes(eventType);
        if (eventJobId && isJobStateEvent) {
          setActiveJob(current => {
            const sameJob = safeText(current?.job_id || current?.id) === eventJobId;
            const incoming = {
              ...(sameJob && current ? current : {}),
              ...payload,
              job_id: eventJobId,
              session_id: safeText(payload.session_id) || sessionId,
              child_run_id: safeText(payload.child_run_id) || (sameJob ? current?.child_run_id : ''),
              stage: safeText(payload.stage) || (sameJob ? current?.stage : ''),
              status: safeText(payload.status) || (sameJob ? current?.status : 'running'),
              progress: Number(payload.progress) || 0,
              error: friendlyDeepJobError(payload.error) || (sameJob ? current?.error : ''),
            };
            const next = mergeDeepJobState(current, incoming);
            const terminal = isTerminalJob(next);
            activeJobRef.current = terminal ? null : next;
            if (terminal) {
              if (eventType === 'deep_job_interrupted') setSending(true);
              else setSending(false);
              const terminalStatus = safeText(next.status).toLowerCase();
              if (terminalStatus === 'failed' || terminalStatus === 'blocked' || terminalStatus === 'partial') {
                setJobError(friendlyDeepJobError(next.error) || (terminalStatus === 'blocked' ? '本轮质量检查未通过，已保留阶段摘要。' : terminalStatus === 'partial' ? '任务部分完成，已保留阶段摘要；可重试未完成步骤。' : '深度研究任务失败，可重试。'));
              } else {
                // A successful SSE terminal event can arrive before the next
                // poll. Clear any error retained from a historical/previous
                // attempt immediately so a completed turn never shows a
                // stale failure banner or retry action.
                setJobError('');
              }
            }
            return next;
          });
        }
        const deltaText = safeText(payload.delta?.text);
        const isParallelAnswer = Boolean(
          payload.parallel
          || payload.delta?.parallel
          || payload.parallel_group
          || payload.delta?.parallel_group
          || payload.role
          || payload.delta?.role
        );
        if (deltaText && (['answer', 'answer.delta'].includes(safeText(payload.delta?.kind)) || payload.event_type === 'answer.delta') && !isParallelAnswer) {
          setLiveAnswer(current => `${current}${current ? '\n' : ''}${deltaText}`.slice(-12000));
        }
        if (payload.event_type === 'deep_session_message' || payload.event_type === 'deep_thinking_candidate_created' || ['deep_research_completed', 'deep_research_failed', 'deep_research_blocked', 'deep_job_cancelled'].includes(payload.event_type)) {
          // The assistant message is the durable boundary for the streamed
          // answer.  Keep deltas visible until that message arrives, then let
          // the normal transcript render the canonical final text.
          const assistantArrived = payload.event_type === 'deep_session_message' && safeText(payload.role).toLowerCase() === 'assistant';
          if (assistantArrived) setLiveAnswer('');
          if (payload.event_type !== 'deep_session_message' || assistantArrived) {
            void loadSession(sessionId, {silent: true});
            void loadVersions(
              session?.card_binding_id || normalizedContext.card_binding_id || '',
              session?.hypothesis_id || normalizedContext.hypothesis_id || '',
              session?.capability_id || normalizedContext.capability_id || '',
            );
          }
          if (['deep_thinking_candidate_created', 'deep_research_completed'].includes(payload.event_type)) {
            // The capability page is often still showing the parent run while
            // this dialog is open.  Broadcast a read-only refresh signal after
            // the worker has committed its version/session projection so the
            // pending-verification card appears without waiting for the next
            // parent poll.  No artifact body is copied through the event.
            window.dispatchEvent(new CustomEvent('equipment-capabilities-changed', {
              detail: {
                runId,
                sessionId,
                jobId: safeText(payload.job_id),
                versionRefs: Array.isArray(payload.version_refs) ? payload.version_refs : [],
              },
            }));
          }
        }
      } catch { /* malformed provider data is ignored at the public boundary */ }
    };
    const connect = async () => {
      while (!cancelled) {
        try {
          setStreamState(attempts ? 'reconnecting' : 'connecting');
          await readDeepEventStream(url, {headers: deepScopeHeaders(normalizedContext), lastEventId: streamCursorRef.current, signal: controller.signal, onEvent});
          attempts = 0;
          if (cancelled) break;
          // The API closes an idle replay stream by design.  Reopen only while
          // a message/job is active; otherwise an open panel should not cause
          // an endless 350ms request loop.  A later send/job transition is in
          // the effect dependencies below and starts a fresh connection.
          if (!sendingRef.current && !activeJobRef.current) {
            endedIdle = true;
            setStreamState('idle');
            break;
          }
          setStreamState('reconnecting');
          await wait(180);
        } catch (streamError) {
          if (cancelled || controller.signal.aborted) break;
          if (!sendingRef.current && !activeJobRef.current) {
            endedIdle = true;
            setStreamState('idle');
            break;
          }
          attempts += 1;
          setStreamState('error');
          const delay = Math.min(4000, 250 * (2 ** Math.min(attempts - 1, 4)));
          await wait(delay);
        }
      }
      // `idle` is a deliberate terminal state for a bounded replay stream;
      // don't overwrite it with a misleading `closed` label after the loop.
      if (!cancelled && !endedIdle) setStreamState('closed');
    };
    void connect();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [activeJobId, apiBase, loadSession, loadVersions, normalizedContext, runId, session?.card_binding_id, session?.capability_id, session?.hypothesis_id, session?.session_id, streamEpoch]);

  // A 202 response may contain only a durable job reference.  Poll that job
  // until its terminal state, then refresh the session and version ledger.
  const activeJobStatus = `${safeText(activeJob?.status).toLowerCase()}:${safeText(activeJob?.stage).toLowerCase()}`;
  useEffect(() => {
    if (!activeJobId || !runId || isTerminalJob(activeJob)) return undefined;
    let cancelled = false;
    let inFlight = false;
    const poll = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/jobs/${encodeURIComponent(activeJobId)}`, {headers: deepScopeHeaders(normalizedContext)});
      inFlight = false;
      if (cancelled) return;
      if (!result.ok) { setJobError(result.detail || '无法读取深度研究任务状态。'); return; }
      const job = result.data?.job || result.data;
      if (!job || typeof job !== 'object') return;
      setActiveJob(current => {
        const next = mergeDeepJobState(current, job);
        activeJobRef.current = next && !isTerminalJob(next) ? next : null;
        return next;
      });
      const jobText = safeText(job.text);
      if (job.stage && !isTerminalJob(job)) {
        setStageEvents(current => {
          const cue = jobText || processStageCue(job.stage, job.status);
          const last = current[current.length - 1];
          if (safeText(last?.stage) === safeText(job.stage) && safeText(last?.status) === safeText(job.status) && safeText(last?.delta?.text) === cue) return current;
          return [...current, localStageEvent({stage: job.stage, status: job.status, text: cue, progress: Number(job.progress || 0)})].slice(-80);
        });
      }
      const jobSessionId = safeText(job.session_id);
      if (jobSessionId && safeText(session?.session_id) !== jobSessionId) {
        freshCompositionRef.current = false;
        void loadSession(jobSessionId, {silent: true});
      }
      const status = safeText(job.status).toLowerCase();
      if (isTerminalJob(job)) {
        setSending(false);
        if (status === 'failed' || status === 'blocked' || status === 'partial' || status === 'cancelled') setJobError(friendlyDeepJobError(job.error) || (status === 'blocked' ? '本轮质量检查未通过，已保留阶段摘要。' : status === 'partial' ? '任务部分完成，已保留阶段摘要；可重试未完成步骤。' : status === 'cancelled' ? '任务已取消，可重新提交上一个问题。' : '深度研究任务失败，可重试。'));
        else setJobError('');
        if (jobSessionId || session?.session_id) void loadSession(jobSessionId || session.session_id, {silent: true});
        void loadSessions(false);
        void loadVersions(
          session?.card_binding_id || normalizedContext.card_binding_id || '',
          session?.hypothesis_id || normalizedContext.hypothesis_id || '',
          session?.capability_id || normalizedContext.capability_id || '',
        );
      }
    };
    void poll();
    const timer = setInterval(() => { void poll(); }, 800);
    return () => { cancelled = true; clearInterval(timer); };
  }, [activeJobId, activeJobStatus, apiBase, loadSession, loadSessions, loadVersions, normalizedContext, runId, session?.card_binding_id, session?.capability_id, session?.hypothesis_id, session?.session_id]);
  useEffect(() => {
    const node = messagesRef.current;
    if (!node) return;
    const justFinished = wasSendingRef.current && !sending;
    wasSendingRef.current = sending;
    if (!stickToBottomRef.current) return;
    window.requestAnimationFrame(() => {
      if (!stickToBottomRef.current) return;
      if (justFinished) {
        const answers = node.querySelectorAll('.deep-message.assistant');
        const latestAnswer = answers[answers.length - 1];
        if (latestAnswer instanceof HTMLElement) {
          const nodeTop = node.getBoundingClientRect().top;
          const answerTop = latestAnswer.getBoundingClientRect().top;
          node.scrollTop = Math.max(0, node.scrollTop + answerTop - nodeTop - 12);
          return;
        }
      }
      if (sending) node.scrollTop = node.scrollHeight;
    });
  }, [session?.messages?.length, sending, liveAnswer]);
  useEffect(() => {
    const node = messagesRef.current;
    const sessionId = safeText(session?.session_id);
    const messageCount = Array.isArray(session?.messages) ? session.messages.length : 0;
    if (!node || !sessionId || !messageCount || sending) return;
    const positionKey = `${sessionId}:${messageCount}`;
    if (autoPositionedSessionRef.current === positionKey) return;
    autoPositionedSessionRef.current = positionKey;
    stickToBottomRef.current = true;
    setShowJumpBottom(false);
    window.requestAnimationFrame(() => {
      const answers = node.querySelectorAll('.deep-message.assistant');
      const latestAnswer = answers[answers.length - 1];
      if (latestAnswer instanceof HTMLElement) {
        const nodeTop = node.getBoundingClientRect().top;
        const answerTop = latestAnswer.getBoundingClientRect().top;
        node.scrollTop = Math.max(0, node.scrollTop + answerTop - nodeTop - 12);
      } else {
        node.scrollTop = node.scrollHeight;
      }
    });
  }, [session?.messages, session?.session_id, sending]);
  useEffect(() => {
    setContextUsageOpen(false);
    setQuotedContext('');
    setConversationHandoff(true);
    const fade = window.setTimeout(() => setConversationHandoff(false), prefersReducedMotion() ? 80 : 180);
    if (session && composerRef.current && !window.matchMedia('(max-width: 700px)').matches) composerRef.current.focus();
    return () => window.clearTimeout(fade);
  }, [session?.session_id]);
  useLayoutEffect(() => { resizeComposer(composerRef.current); }, [draft, quotedContext]);
  useEffect(() => {
    if (window.matchMedia('(max-width: 700px)').matches) return undefined;
    const timer = window.setTimeout(() => composerRef.current?.focus(), 30);
    return () => window.clearTimeout(timer);
  }, []);

  const registerAcceptedJob = result => {
    const payload = result?.data;
    const job = payload?.job || payload?.deep_job || (payload?.job_id ? payload : null);
    if (!job || typeof job !== 'object') return false;
    setJobError('');
    setActiveJob(current => mergeDeepJobState(current, job));
    return Boolean(job.job_id || job.id);
  };

  const createSession = async (question, {createArtifact = false, activeSkillIds = selectedSkillIds} = {}) => {
    if (!runId) {
      const failure = {ok: false, detail: '当前没有可用的研究任务 Query。'};
      setError(failure.detail);
      return failure;
    }
    if (requiresTarget) {
      const failure = {ok: false, detail: '请先选择一个具体武器/装备，再开始深度发散。'};
      setError(failure.detail);
      return failure;
    }
    const selectedContext = normalizedContext?.current_result_context?.selected;
    const selectedCard = selectedContext && typeof selectedContext === 'object' ? selectedContext : {};
    // Card-scoped launchers historically supplied the selected row only under
    // current_result_context.selected. Promote that visible object into the
    // explicit candidate fields as a compatibility fallback so historical
    // runs without a server-side lineage still receive the right focus.
    const explicitCandidate = normalizedContext.candidate && typeof normalizedContext.candidate === 'object'
      ? normalizedContext.candidate
      : {};
    const candidate = Object.keys(explicitCandidate).length || kind === 'deep-thinking' ? explicitCandidate : selectedCard;
    const explicitWeapon = normalizedContext.reference_weapon && typeof normalizedContext.reference_weapon === 'object'
      ? normalizedContext.reference_weapon
      : {};
    const referenceWeapon = Object.keys(explicitWeapon).length || kind === 'deep-thinking' ? explicitWeapon : (Object.keys(selectedCard).length ? selectedCard : candidate);
    const body = {
      kind,
      title: normalizedContext.title || `${sessionKindLabel(kind)} · ${title}`,
      capability_id: normalizedContext.capability_id || '',
      card_binding_id: normalizedContext.card_binding_id || candidate.card_binding_id || '',
      capability_name: normalizedContext.capability_name || title,
      hypothesis_id: normalizedContext.hypothesis_id || '',
      context_refs: normalizedContext,
      candidate,
      reference_weapon: referenceWeapon,
      question: question || '',
      focus: normalizedContext.focus || '',
      create_artifact: createArtifact,
      active_skill_ids: activeSkillIds,
      auto_merge: false,
    };
    // A new conversation must get a new idempotency key.  Scoping the key
    // only by card/run would make the “新对话” button replay the first session
    // forever; retries of this exact call are still protected by the stable
    // key generated for its invocation.
    const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/sessions`, {method: 'POST', headers: {...deepScopeHeaders(normalizedContext), 'Content-Type': 'application/json', 'Idempotency-Key': `session:${conversationNonceRef.current}`}, body: JSON.stringify(body)});
    if (!result.ok) { setError(result.detail || '新建专家会话失败。'); return result; }
    const accepted = registerAcceptedJob(result);
    const next = result.data?.session || null;
    const jobSessionId = safeText(
      next?.session_id
      || result.data?.job?.session_id
      || result.data?.deep_job?.session_id
      || result.data?.session_id,
    );
    if (next) {
      freshCompositionRef.current = false;
      setSession(current => applySessionSnapshot(current, next, result.data?.user_message ? [result.data.user_message] : []));
      setSessions(current => {
        const merged = applySessionSnapshot(current.find(item => item.session_id === next.session_id) || next, next);
        return [merged, ...current.filter(item => item.session_id !== next.session_id)];
      });
    } else if (jobSessionId) {
      // 202 responses may omit the full session projection but still carry the
      // durable session id on the job. Bind that id explicitly so we never fall
      // back to an older same-run transcript with leftover 最终成果 cards.
      freshCompositionRef.current = false;
      await loadSession(jobSessionId, {silent: true});
    }
    if (Array.isArray(result.data?.answer?.next_questions)) setNextQuestions(result.data.answer.next_questions.slice(0, 4));
    if (result.data?.answer && typeof result.data.answer === 'object') setLastAnswer(result.data.answer);
    onChanged?.(result.data);
    if (!next && !jobSessionId) {
      await wait(300);
      void loadSessions(false);
    } else if (accepted) {
      void loadSessions(false);
    }
    return result;
  };

  const send = async (event, {content: requestedContent = '', createArtifact = false, mode: requestedMode = ''} = {}) => {
    event?.preventDefault();
    const rawContent = safeText(requestedContent || draft) || (
      !requestedContent && quotedContext
        ? '请针对上述引用继续深化：闭合打击对象、直接毁伤机理与任务失能判据。'
        : ''
    );
    const content = formatQuotedDeepMessage(rawContent, requestedContent ? '' : quotedContext);
    const slash = matchDeepSlashCommand(parseQuotedDeepMessage(content).content || content);
    if (slash?.id === 'card') createArtifact = true;
    if (['memory', 'help', 'diverge', 'challenge', 'synthesize'].includes(slash?.id)) createArtifact = false;
    const runningJob = activeJobRef.current || (activeJob && !isTerminalJob(activeJob) ? activeJob : null);
    if (!content || steerSubmitting || !runId || safeText(session?.status).toLowerCase() === 'archived') return;
    if (sending && !runningJob) return;
    if (requiresTarget) {
      setError('请先选择一个具体武器/装备，再开始深度发散。');
      return;
    }
    if (content.length > MAX_MESSAGE_CHARS) { setError(`问题不能超过 ${MAX_MESSAGE_CHARS} 字。`); return; }
    stickToBottomRef.current = true;
    setShowJumpBottom(false);
    const sessionBranches = Array.isArray(session?.branches) ? session.branches : [];
    const jobBranch = safeText(runningJob?.branch_id);
    const branchId = jobBranch || activeBranchId || DEFAULT_BRANCH_ID;
    const turnSkillIds = reconcileActiveSkillIds(resolveBranchSkillSelection({
      session,
      branchId,
      selectedSkillIds,
      selectedSessionId: selectedSkillScopeRef.current.sessionId,
      selectedBranchId: selectedSkillScopeRef.current.branchId,
      defaultSkillIds: session?.session_id ? [] : explicitDefaultSkillIds,
    }), capabilityCatalog);
    const currentPath = branchMessagePath(Array.isArray(session?.messages) ? session.messages : [], branchId, sessionBranches);
    const parentMessageId = safeText(currentPath[currentPath.length - 1]?.message_id);
    const steerMode = DEEP_STEER_MODES.some(item => item.id === requestedMode) ? requestedMode : duringRunMode;
    if (runningJob && session?.session_id) {
      const clientSteerId = newRequestNonce();
      const localMessageId = `local-steer-${clientSteerId}`;
      const optimistic = {
        message_id: localMessageId,
        parent_message_id: parentMessageId,
        branch_id: branchId,
        turn_id: safeText(runningJob.job_id || runningJob.id),
        message_kind: 'steer',
        role: 'user',
        content,
        status: steerMode === 'queue' ? 'queued' : 'accepted',
        created_at: new Date().toISOString(),
        pending: true,
      };
      setSteerSubmitting(true);
      setShowRunModeMenu(false);
      setError('');
      setDraft('');
      setQuotedContext('');
      setSession(current => applySessionSnapshot(current, current, [optimistic]));
      setSteerReceipts(current => ({...current, [localMessageId]: {
        client_steer_id: clientSteerId,
        job_id: safeText(runningJob.job_id || runningJob.id),
        message_id: localMessageId,
        branch_id: branchId,
        mode: steerMode,
        status: steerMode === 'queue' ? 'queued' : 'accepted',
      }}));
      const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/jobs/${encodeURIComponent(safeText(runningJob.job_id || runningJob.id))}/steers`, {
        method: 'POST',
        headers: {...deepScopeHeaders(normalizedContext), 'Content-Type': 'application/json'},
        body: JSON.stringify({
          content,
          mode: steerMode,
          client_steer_id: clientSteerId,
          branch_id: branchId,
          parent_message_id: parentMessageId,
        }),
      });
      setSteerSubmitting(false);
      if (!result.ok) {
        const parsed = parseQuotedDeepMessage(content);
        setQuotedContext(parsed.quotedContext);
        setDraft(parsed.content);
        setError(result.status === 409 ? '当前轮刚刚结束，请再次发送以开始新一轮。' : (result.detail || '未能接收追问，请重试。'));
        setSession(current => current ? {...current, messages: (current.messages || []).filter(item => safeText(item?.message_id) !== localMessageId)} : current);
        setSteerReceipts(current => {
          const next = {...current};
          delete next[localMessageId];
          return next;
        });
        return;
      }
      const steer = result.data?.steer || {};
      const serverMessageId = safeText(steer.message_id) || localMessageId;
      const receiptStatus = steerMode === 'queue' ? 'queued' : 'accepted';
      const serverMessage = {...optimistic, message_id: serverMessageId, status: receiptStatus, pending: false};
      setSession(current => {
        if (!current) return current;
        const rows = Array.isArray(current.messages) ? current.messages : [];
        const withoutLocal = rows.filter(item => safeText(item?.message_id) !== localMessageId);
        const exists = withoutLocal.some(item => safeText(item?.message_id) === serverMessageId);
        return {...current, messages: exists ? withoutLocal : [...withoutLocal, serverMessage]};
      });
      setSteerReceipts(current => {
        const next = {...current};
        delete next[localMessageId];
        next[serverMessageId] = {...steer, job_id: safeText(runningJob.job_id || runningJob.id), mode: steerMode, status: receiptStatus};
        return next;
      });
      void loadSession(session.session_id, {silent: true});
      return;
    }
    const optimistic = {
      message_id: `local-${Date.now()}`,
      parent_message_id: parentMessageId,
      branch_id: branchId,
      message_kind: 'message',
      role: 'user',
      content,
      created_at: new Date().toISOString(),
      pending: true,
    };
    setSending(true); setError(''); setDraft(''); setQuotedContext(''); setLiveAnswer(''); setLastAnswer(null);
    setSession(current => applySessionSnapshot(current, current, [optimistic]));
    setStageEvents(current => [
      ...current.filter(item => !item?.local || safeText(item?.delta?.text) !== processStageCue('queued', 'queued')),
      localStageEvent({stage: 'queued', status: 'queued', text: processStageCue('queued', 'queued'), progress: 0.02}),
    ].slice(-80));
    lastQuestionRef.current = content;
    lastTurnAuthoringRef.current = createArtifact;
    let result;
    if (!session?.session_id) {
      result = await createSession(content, {createArtifact, activeSkillIds: turnSkillIds});
    } else {
      const requestNonce = messageNonceRef.current;
      result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/sessions/${encodeURIComponent(session.session_id)}/messages`, {
        method: 'POST', headers: {...deepScopeHeaders(normalizedContext), 'Content-Type': 'application/json', 'Idempotency-Key': `message:${session.session_id}:${requestNonce}`}, body: JSON.stringify({content, create_artifact: createArtifact, focus: activeTurnFocus, branch_id: branchId, parent_message_id: parentMessageId, active_skill_ids: turnSkillIds}),
      });
      const accepted = result.ok && registerAcceptedJob(result);
      if (result.ok) messageNonceRef.current = newRequestNonce();
      if (result.ok && (result.data?.session || result.data?.user_message)) {
        setSession(current => applySessionSnapshot(current, result.data?.session || current, result.data?.user_message ? [result.data.user_message] : []));
        if (result.data?.session) {
          setSessions(current => current.map(item => item.session_id === result.data.session.session_id ? applySessionSnapshot(item, result.data.session) : item));
        }
        onChanged?.(result.data);
      }
      if (result.ok && Array.isArray(result.data?.answer?.next_questions)) setNextQuestions(result.data.answer.next_questions.slice(0, 4));
      if (result.ok && result.data?.answer && typeof result.data.answer === 'object') setLastAnswer(result.data.answer);
      if (result.ok && accepted) setSending(true);
    }
    if (result && !result.ok) {
      const parsed = parseQuotedDeepMessage(content);
      setQuotedContext(parsed.quotedContext);
      setDraft(parsed.content);
      setError(result.detail || '回答生成失败，可重试。');
      setSession(current => current ? {
        ...current,
        messages: (Array.isArray(current.messages) ? current.messages : []).filter(item => !(item?.pending && safeText(item.content) === content)),
      } : current);
    }
    const responseHasJob = Boolean(result?.ok && (result?.data?.job || result?.data?.deep_job || result?.data?.job_id));
    if (!result?.ok || !responseHasJob) setSending(false);
    else if (!['live', 'connecting', 'reconnecting'].includes(streamStateRef.current)) setStreamEpoch(value => value + 1);
  };

  const cancelActiveJob = async () => {
    if (!runId || !activeJobId || isTerminalJob(activeJob)) return;
    setJobError('');
    const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/jobs/${encodeURIComponent(activeJobId)}/cancel`, {
      method: 'POST',
      headers: {...deepScopeHeaders(normalizedContext), 'Idempotency-Key': `cancel:${activeJobId}`},
      body: JSON.stringify({}),
    });
    if (!result.ok) { setJobError(result.detail || '取消任务失败，请稍后重试。'); return; }
    setActiveJob(current => mergeDeepJobState(
      current,
      result.data?.job || {...current, status: 'cancelled'},
    ));
    setSending(false);
  };

  const cancelSteer = async receipt => {
    const jobId = safeText(receipt?.job_id);
    const steerId = safeText(receipt?.steer_id);
    const messageId = safeText(receipt?.message_id);
    if (!runId || !jobId || !steerId) return;
    const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/jobs/${encodeURIComponent(jobId)}/steers/${encodeURIComponent(steerId)}`, {
      method: 'DELETE',
      headers: deepScopeHeaders(normalizedContext),
    });
    if (!result.ok) {
      setError(result.detail || '取消追问失败，它可能已被纳入当前研究。');
      return;
    }
    setSteerReceipts(current => ({
      ...current,
      [messageId]: mergeTranscriptMessage(receipt, {
        ...result.data?.steer,
        status: 'cancelled',
      }),
    }));
    setSession(current => current ? {
      ...current,
      messages: (current.messages || []).map(item => (
        safeText(item?.message_id) === messageId
          ? mergeTranscriptMessage(item, {status: 'cancelled'})
          : item
      )),
    } : current);
  };

  const switchBranch = branchId => {
    if (sending || (activeJob && !isTerminalJob(activeJob))) return;
    const nextBranchId = safeText(branchId) || DEFAULT_BRANCH_ID;
    setActiveBranchId(nextBranchId);
    onNavigationChange?.({
      sessionId: safeText(session?.session_id),
      branchId: nextBranchId,
      targetIdentity: selectedTargetKey,
    });
    selectedSkillScopeRef.current = {
      sessionId: safeText(session?.session_id),
      branchId: nextBranchId,
    };
    capabilitySelectionSourceRef.current = '';
    setSelectedSkillIds(reconcileActiveSkillIds(
      branchActiveSkillIds(session, nextBranchId, session?.session_id ? [] : explicitDefaultSkillIds),
      capabilityCatalog,
    ));
    setStageEvents([]);
    setLiveAnswer('');
    setLastAnswer(null);
    setNextQuestions([]);
    setJobError('');
    if (activeJob && isTerminalJob(activeJob)) setActiveJob(null);
    setTimeout(() => composerRef.current?.focus(), 0);
  };

  const forkFromMessage = async message => {
    const sessionId = safeText(session?.session_id);
    const messageId = safeText(message?.message_id);
    if (!runId || !sessionId || !messageId || sending || (activeJob && !isTerminalJob(activeJob))) return;
    setBranchActionMessageId(messageId);
    setError('');
    const requestScope = `${sessionId}:${messageId}`;
    const existingRequest = forkRequestRef.current.get(requestScope);
    const existingBranches = (Array.isArray(session?.branches) ? session.branches : [])
      .filter(item => safeText(item?.branch_id) !== DEFAULT_BRANCH_ID);
    const branchOrdinal = existingBranches.length + 1;
    const forkRequest = existingRequest || {
      key: deepForkIdempotencyKey(sessionId, messageId, session?.branches),
      title: `探索分支 ${branchOrdinal}`,
    };
    forkRequestRef.current.set(requestScope, forkRequest);
    const result = await apiRequest(apiBase, `/runs/${encodeRun(runId)}/deep-thinking/sessions/${encodeURIComponent(sessionId)}/branches`, {
      method: 'POST',
      headers: {...deepScopeHeaders(normalizedContext), 'Content-Type': 'application/json', 'Idempotency-Key': forkRequest.key},
      body: JSON.stringify({
        from_message_id: messageId,
        title: forkRequest.title,
      }),
    });
    setBranchActionMessageId('');
    if (!result.ok) {
      setError(result.detail || '创建研究分支失败。');
      return;
    }
    forkRequestRef.current.delete(requestScope);
    const branch = result.data?.branch;
    if (!branch?.branch_id) return;
    setSession(current => {
      if (!current) return current;
      const rows = Array.isArray(current.branches) ? current.branches : [];
      return {...current, branches: [...rows.filter(item => safeText(item?.branch_id) !== safeText(branch.branch_id)), branch]};
    });
    setActiveBranchId(branch.branch_id);
    onNavigationChange?.({
      sessionId: safeText(session?.session_id),
      branchId: safeText(branch.branch_id) || DEFAULT_BRANCH_ID,
      targetIdentity: selectedTargetKey,
    });
    selectedSkillScopeRef.current = {
      sessionId: safeText(session?.session_id),
      branchId: safeText(branch.branch_id) || DEFAULT_BRANCH_ID,
    };
    capabilitySelectionSourceRef.current = '';
    setSelectedSkillIds(reconcileActiveSkillIds(
      branchActiveSkillIds(session, branch.branch_id, []),
      capabilityCatalog,
    ));
    setStageEvents([]);
    setLiveAnswer('');
    setLastAnswer(null);
    setNextQuestions([]);
    setTimeout(() => composerRef.current?.focus(), 0);
  };

  const retryLastQuestion = () => {
    const lastUser = [...(Array.isArray(session?.messages) ? session.messages : [])]
      .reverse()
      .find(item => safeText(item?.role).toLowerCase() === 'user');
    const content = lastQuestionRef.current || safeText(lastUser?.content);
    if (!content) return;
    setActiveJob(null);
    setJobError('');
    setError('');
    messageNonceRef.current = newRequestNonce();
    void send(null, {content, createArtifact: lastTurnAuthoringRef.current});
  };

  const startNew = () => {
    conversationNonceRef.current = newRequestNonce();
    messageNonceRef.current = newRequestNonce();
    freshCompositionRef.current = true;
    // Drop in-flight list/detail responses that would otherwise restore the
    // previous session (and its 最终成果) right after clearing the draft.
    sessionsRequestRef.current += 1;
    sessionRequestRef.current += 1;
    versionsRequestRef.current += 1;
    setConversationRunId(workbenchRunId);
    setSession(null);
    setDraft('');
    setQuotedContext('');
    setNextQuestions([]);
    setError('');
    setJobError('');
    setActiveJob(null);
    setActiveBranchId(DEFAULT_BRANCH_ID);
    selectedSkillScopeRef.current = {sessionId: '', branchId: DEFAULT_BRANCH_ID};
    capabilitySelectionSourceRef.current = '';
    setSelectedSkillIds(reconcileActiveSkillIds(explicitDefaultSkillIds, capabilityCatalog));
    setSteerReceipts({});
    setShowRunModeMenu(false);
    setSteerSubmitting(false);
    setBranchActionMessageId('');
    forkRequestRef.current.clear();
    setSending(false);
    setLiveAnswer('');
    setLastAnswer(null);
    setStageEvents([]);
    setCapabilityVersions([]);
    setShowJumpBottom(false);
    setLoadingSession(false);
    setWelcomeSuggestions(randomWelcomeSuggestions(normalizedContext));
    streamCursorRef.current = 0;
    streamSessionRef.current = '';
    onNavigationChange?.({
      sessionId: '',
      branchId: DEFAULT_BRANCH_ID,
      targetIdentity: selectedTargetKey,
    });
    setTimeout(() => composerRef.current?.focus(), 0);
  };
  const manageSession = async (item, changes) => {
    const targetRun = sessionRunId(item) || runId || workbenchRunId;
    if (!targetRun || !item?.session_id) return;
    setSessionActionId(item.session_id);
    setSessionsError('');
    const result = await apiRequest(apiBase, `/runs/${encodeRun(targetRun)}/deep-thinking/sessions/${encodeURIComponent(item.session_id)}`, {
      method: 'PATCH', headers: {...deepScopeHeaders(normalizedContext), 'Content-Type': 'application/json'}, body: JSON.stringify(changes),
    });
    setSessionActionId('');
    if (!result.ok) { setSessionsError(result.detail || '会话管理失败。'); return false; }
    const updated = result.data?.session;
    if (updated) {
      const merged = {...item, ...updated, run_id: targetRun, parent_run_id: targetRun};
      setSessions(current => current.map(row => row.session_id === merged.session_id ? {...row, ...merged} : row));
      setHistoryGroups(current => current.map(group => ({
        ...group,
        sessions: (group.sessions || []).map(row => row.session_id === merged.session_id ? {...row, ...merged} : row),
      })));
      if (session?.session_id === merged.session_id) {
        if (safeText(merged.status).toLowerCase() === 'archived') startNew();
        else setSession(current => ({...current, ...merged}));
      }
      // Restoring from the archive should immediately return to the active
      // history view; otherwise the successfully restored row stays hidden
      // until the expert manually changes the filter.
      if (changes?.archived === false) {
        setShowArchivedSessions(current => resolveDeepHistoryFilterAfterMutation(current, changes));
      }
      void loadSessions(false);
    }
    return true;
  };
  const deleteSession = async item => {
    const targetRun = sessionRunId(item) || runId || workbenchRunId;
    if (!targetRun || !item?.session_id) return;
    setSessionActionId(item.session_id);
    setSessionsError('');
    const result = await apiRequest(apiBase, `/runs/${encodeRun(targetRun)}/deep-thinking/sessions/${encodeURIComponent(item.session_id)}`, {
      method: 'DELETE', headers: deepScopeHeaders(normalizedContext),
    });
    setSessionActionId('');
    if (!result.ok) { setSessionsError(result.detail || '删除对话失败。'); return; }
    setDeleteConfirmSessionId('');
    setRenamingSessionId(current => current === item.session_id ? '' : current);
    setSessions(current => current.filter(row => row.session_id !== item.session_id));
    setHistoryGroups(current => current
      .map(group => ({...group, sessions: (group.sessions || []).filter(row => row.session_id !== item.session_id)}))
      .filter(group => (group.sessions || []).length > 0)
      .map(group => ({...group, session_count: (group.sessions || []).length})));
    if (session?.session_id === item.session_id) {
      sessionRequestRef.current += 1;
      startNew();
    }
  };
  const beginRenameSession = item => {
    setDeleteConfirmSessionId('');
    setRenamingSessionId(item?.session_id || '');
    setRenameDraft(item?.title || sessionKindLabel(item?.kind));
    setSessionsError('');
  };
  const saveSessionTitle = async item => {
    const nextTitle = safeText(renameDraft);
    if (!nextTitle) { setSessionsError('对话名称不能为空。'); return; }
    if (nextTitle !== safeText(item?.title)) {
      const saved = await manageSession(item, {title: nextTitle});
      if (!saved) return;
    }
    setRenamingSessionId('');
    setRenameDraft('');
  };
  const currentSessions = sessions.filter(item => safeText(item?.status).toLowerCase() !== 'archived');
  const archivedSessions = sessions.filter(item => safeText(item?.status).toLowerCase() === 'archived');
  const visibleGroups = groupSessions(historyGroups, {archived: showArchivedSessions});
  const visibleSessionCount = visibleGroups.reduce((total, group) => total + (group.sessions?.length || 0), 0);
  const viewingArchivedSession = safeText(session?.status).toLowerCase() === 'archived';
  const showTargetPicker = kind === 'deep-thinking' && !selectedTarget && !session?.session_id;
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const branches = (() => {
    const rows = Array.isArray(session?.branches) ? session.branches : [];
    return rows.some(item => safeText(item?.branch_id) === DEFAULT_BRANCH_ID)
      ? rows
      : [{branch_id: DEFAULT_BRANCH_ID, title: '主线', forked_from_message_id: ''}, ...rows];
  })();
  const visibleMessages = branchMessagePath(messages, activeBranchId, branches);
  const userPrompts = visibleMessages.filter(item => safeText(item?.role) === 'user' && safeText(item?.message_id));
  const latestMessage = visibleMessages[visibleMessages.length - 1];
  const selectedSteerMode = DEEP_STEER_MODES.find(item => item.id === duringRunMode) || DEEP_STEER_MODES[0];
  const SelectedSteerModeIcon = selectedSteerMode.icon;
  const jobRunning = Boolean(activeJob && !isTerminalJob(activeJob));
  const syncThreadCamera = useCallback((node = messagesRef.current) => {
    if (!node) return;
    const near = isThreadNearBottom(node, THREAD_NEAR_BOTTOM_PX);
    stickToBottomRef.current = near;
    setShowJumpBottom(shouldShowJumpToLatest(node, THREAD_NEAR_BOTTOM_PX));
  }, []);
  const jumpToLatest = useCallback(() => {
    const node = messagesRef.current;
    if (!node) return;
    stickToBottomRef.current = true;
    setShowJumpBottom(false);
    node.scrollTo({top: node.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth'});
  }, []);
  const jumpToPrompt = useCallback(messageId => {
    const node = messagesRef.current;
    const id = safeText(messageId);
    if (!node || !id) return;
    const escaped = (typeof CSS !== 'undefined' && CSS.escape) ? CSS.escape(id) : id.replace(/"/g, '\\"');
    const target = node.querySelector(`[data-prompt-id="${escaped}"]`);
    if (!(target instanceof HTMLElement)) return;
    stickToBottomRef.current = false;
    target.scrollIntoView({block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth'});
    window.requestAnimationFrame(() => syncThreadCamera());
  }, [syncThreadCamera]);
  const quoteIntoComposer = useCallback((excerpt) => {
    const next = safeText(excerpt).slice(0, 4000);
    if (!next) return;
    setQuotedContext(next);
    setTimeout(() => composerRef.current?.focus(), 0);
  }, []);
  const copyMessage = useCallback(async (value, messageId) => {
    const ok = await copyText(value);
    if (!ok) return;
    setCopiedMessageId(safeText(messageId) || 'copied');
    window.setTimeout(() => setCopiedMessageId(current => (current === (safeText(messageId) || 'copied') ? '' : current)), 1400);
  }, []);
  const focusDirection = item => {
    const prompt = directionFollowUp(item);
    if (!prompt) return;
    const name = safeText(item?.innovation_variant_name || item?.name || item?.candidate_name);
    void send(null, {content: formatQuotedDeepMessage(prompt, name)});
  };
  const contextUsage = useMemo(
    () => projectDeepContextUsage(session, activeBranchId),
    [activeBranchId, session],
  );
  const decisionMemory = useMemo(
    () => projectDeepMemory(session, activeBranchId),
    [activeBranchId, session],
  );
  const activeBranchLabel = safeText(
    branches.find(item => safeText(item?.branch_id) === activeBranchId)?.title,
  ) || (activeBranchId === DEFAULT_BRANCH_ID ? '主线' : '探索分支');
  const slashMatches = !jobRunning && !viewingArchivedSession ? filterDeepSlashCommands(draft) : [];
  useEffect(() => { setSelectedSlashIndex(0); }, [draft]);
  const queuedPrompts = visibleMessages.filter(item => {
    if (safeText(item?.role) !== 'user') return false;
    const receipt = steerReceipts[safeText(item?.message_id)];
    const status = safeText(receipt?.status || item?.status).toLowerCase();
    return (safeText(item?.message_kind) === 'steer' || Boolean(receipt)) && queuedSteerStatuses.has(status) && (jobRunning || status === 'queued');
  });
  const awaitingCardConfirmation = Boolean(
    !sending
    && safeText(latestMessage?.role).toLowerCase() === 'assistant'
    && /#{1,6}\s*是否形成能力卡/.test(safeText(latestMessage?.content))
  );
  const hiddenArtifactStatuses = new Set(['deleted', 'rejected', 'rolled_back', 'cancelled', 'failed', 'blocked', 'formal']);
  const artifacts = (Array.isArray(session?.artifacts) ? session.artifacts : []).filter(item => {
    const payload = item?.payload && typeof item.payload === 'object' ? item.payload : item;
    const artifactSessionId = safeText(item?.source_session_id || payload?.source_session_id);
    if (session?.session_id && artifactSessionId && artifactSessionId !== safeText(session.session_id)) return false;
    const status = normalizeCapabilityVersionStatus(
      payload?.version_status || payload?.verification_status || item?.version_status || item?.status,
    );
    return !hiddenArtifactStatuses.has(status);
  });
  const resultState = deepResultState({activeJob, session, artifacts, versions: capabilityVersions, stageEvents, sending, lastAnswer, jobError});
  const ResultStateIcon = resultState.tone === 'running'
    ? RefreshCw
    : resultState.tone === 'partial' || resultState.tone === 'analysis'
      ? CircleAlert
      : resultState.tone === 'verified' || resultState.tone === 'pending'
        ? CheckCircle2
        : resultState.tone === 'candidate' || resultState.tone === 'summary'
          ? Sparkles
          : Clock3;
  const showLiveAnswer = Boolean(liveAnswer && (sending || (activeJob && !isTerminalJob(activeJob))));
  // Keep the follow-up rail useful even when the model returned no explicit
  // next questions: after a completed round, offer stable deepening moves.
  const hasCompletedRound = visibleMessages.some(item => item?.role === 'assistant' && safeText(item?.content));
  const extractedFollowUps = extractDeepFollowUps({answer: lastAnswer, messages: visibleMessages, limit: 4});
  const followUpQuestions = extractedFollowUps.length
    ? extractedFollowUps
    : (nextQuestions.length
      ? nextQuestions
      : (hasCompletedRound
        ? [
          '继续深化首选方向：闭合打击对象、直接毁伤机理与任务失能判据',
          '假设对手针对性反制，这个方向如何保持制衡优势？',
          '在电磁静默或补给受限的极限条件下，构型如何跃迁？',
        ]
        : []));
  const visibleStageEvents = stageEvents
    .filter(item => safeText(item?.delta?.text || item?.text || item?.summary_text))
    .filter(item => !looksLikeCompleteAnswerDump(item?.delta?.text || item?.text))
    .filter((item, _index, rows) => {
      if (!item?.local) return true;
      return !rows.some(other => (
        !other?.local
        && normalizeDeepStage(other?.stage) === normalizeDeepStage(item.stage)
        && safeText(other?.status) === safeText(item.status)
      ));
    })
    .slice(-48);
  const liveFeedback = useMemo(() => projectLiveConversationFeedback(visibleStageEvents), [visibleStageEvents]);
  const streamingDraft = liveFeedback.markdown
    || (showLiveAnswer && liveAnswer && !looksLikeCompleteAnswerDump(liveAnswer) ? liveAnswer : '');
  const showProcessThread = sending || visibleStageEvents.length > 0 || showLiveAnswer;
  // Keep chronological chat order: expert question → live process feedback →
  // final「本轮完整结果」assistant message. Previously the process thread was
  // appended after every message, so the complete answer appeared first.
  let processInsertIndex = visibleMessages.length;
  if (showProcessThread && visibleMessages.length) {
    processInsertIndex = 0;
    for (let index = visibleMessages.length - 1; index >= 0; index -= 1) {
      if (safeText(visibleMessages[index]?.role).toLowerCase() === 'user') {
        processInsertIndex = index + 1;
        break;
      }
    }
  }
  const leadingMessages = visibleMessages.slice(0, processInsertIndex);
  const trailingMessages = visibleMessages.slice(processInsertIndex);
  const showStreamingBubble = Boolean(
    (sending || showLiveAnswer || liveFeedback.segments.length)
    && !trailingMessages.some(item => (
      safeText(item?.role).toLowerCase() === 'assistant'
      && !item?.pending
      && safeText(item?.content)
    ))
  );
  const liveDeliberationAnswer = (
    lastAnswer?.agent_dialogue?.length || lastAnswer?.concept_directions?.length
      ? lastAnswer
      : liveFeedback.answer
  );
  const boardOwnedCandidateNames = useMemo(() => {
    const answer = liveDeliberationAnswer && typeof liveDeliberationAnswer === 'object' ? liveDeliberationAnswer : {};
    const dialogue = Array.isArray(answer.agent_dialogue) ? answer.agent_dialogue : [];
    const directions = Array.isArray(answer.concept_directions) ? answer.concept_directions : [];
    const reviews = Array.isArray(answer.adjudication?.candidate_reviews) ? answer.adjudication.candidate_reviews : [];
    const proposers = dialogue.filter(item => safeText(item?.round) === 'divergence');
    const eventNames = proposers.length ? [] : visibleStageEvents.flatMap(event => eventProposalNames(event));
    return mergeDeliberationProposals(
      proposers.flatMap(item => item?.proposal_names || []),
      eventNames,
      directions.map(item => item?.innovation_variant_name || item?.name),
      reviews.map(item => item?.candidate_name),
    );
  }, [liveDeliberationAnswer, visibleStageEvents]);
  const qualityAdvisoryBanner = isQualityAdvisoryText(jobError || activeJob?.error);
  const showJobBanner = Boolean(activeJob && !qualityAdvisoryBanner && (
    jobError
    || ['failed', 'blocked', 'partial', 'cancelled', 'rejected'].includes(safeText(activeJob.status).toLowerCase())
  ));
  const latestTrackedStage = [...stageEvents]
    .reverse()
    .find(item => DEEP_STAGES.some(([key]) => key === normalizeDeepStage(item?.stage)));
  const displayedJobStage = isTerminalJob(activeJob)
    ? normalizeDeepStage(activeJob?.stage)
    : furthestDeepStage(activeJob?.stage, latestTrackedStage?.stage);
  const visibleStageStrip = stageStripState(stageEvents, activeJob).filter(item => item.status !== 'idle');
  const showStageStrip = visibleStageStrip.length > 0;
  const showResultState = ['candidate', 'pending', 'verified', 'partial', 'analysis', 'summary'].includes(resultState.tone);
  const renderSessionRow = item => {
    const sessionTitle = safeText(item.title || item.capability_name || sessionKindLabel(item.kind)) || '未命名对话';
    const metaBits = [
      sessionKindLabel(item.kind),
      item.capability_name && item.capability_name !== item.title ? item.capability_name : '',
      item.updated_at ? new Date(item.updated_at).toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '',
    ].filter(Boolean);
    return (
    <div className={`deep-session-row${session?.session_id === item.session_id ? ' active' : ''}`} key={item.session_id}>
      {renamingSessionId === item.session_id ? (
        <form className="deep-session-rename" onSubmit={event => { event.preventDefault(); void saveSessionTitle(item); }}>
          <input autoFocus value={renameDraft} maxLength={240} aria-label="对话名称" onChange={event => setRenameDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') { setRenamingSessionId(''); setRenameDraft(''); } }}/>
          <button type="submit" aria-label="保存对话名称" disabled={sessionActionId === item.session_id}><Check size={13}/></button>
          <button type="button" aria-label="取消重命名" onClick={() => { setRenamingSessionId(''); setRenameDraft(''); }}><X size={13}/></button>
        </form>
      ) : (
        <button type="button" className="deep-session-select" onClick={() => { void openHistorySession(item); }}>
          <span>
            <b title={sessionTitle}>{sessionTitle}</b>
            {metaBits.length > 0 && <small title={metaBits.join(' · ')}>{metaBits.join(' · ')}</small>}
          </span>
          <em className={safeText(item.status).toLowerCase()}>{sessionStatusLabel(item.status)}</em>
        </button>
      )}
      <div className={`deep-session-actions${deleteConfirmSessionId === item.session_id ? ' confirm-delete' : ''}`}>
        {deleteConfirmSessionId === item.session_id ? (
          <>
            <span>删除后无法恢复</span>
            <button type="button" className="danger" onClick={() => void deleteSession(item)} aria-label={`确认删除对话：${sessionTitle}`} disabled={sessionActionId === item.session_id}>{sessionActionId === item.session_id ? <RefreshCw size={11} className="spin"/> : <Trash2 size={11}/>}确认删除</button>
            <button type="button" onClick={() => setDeleteConfirmSessionId('')} aria-label="取消删除" disabled={sessionActionId === item.session_id}>取消</button>
          </>
        ) : (
          <>
            {!showArchivedSessions && <button type="button" onClick={() => beginRenameSession(item)} aria-label={`重命名对话：${sessionTitle}`} title="改名" disabled={sessionActionId === item.session_id}><Pencil size={12}/><span>改名</span></button>}
            {showArchivedSessions
              ? <button type="button" onClick={() => void manageSession(item, {archived: false})} aria-label={`恢复对话：${sessionTitle}`} title="恢复" disabled={sessionActionId === item.session_id}>{sessionActionId === item.session_id ? <RefreshCw size={12} className="spin"/> : <RotateCcw size={12}/>}<span>恢复</span></button>
              : <button type="button" onClick={() => void manageSession(item, {archived: true})} aria-label={`归档对话：${sessionTitle}`} title="归档" disabled={sessionActionId === item.session_id}>{sessionActionId === item.session_id ? <RefreshCw size={12} className="spin"/> : <Archive size={12}/>}<span>归档</span></button>}
            <button type="button" onClick={() => { setRenamingSessionId(''); setDeleteConfirmSessionId(item.session_id); }} aria-label={`删除对话：${sessionTitle}`} title="删除" disabled={sessionActionId === item.session_id}><Trash2 size={12}/><span>删除</span></button>
          </>
        )}
      </div>
    </div>
    );
  };
  return <div className="deep-thinking-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose?.(); }}>
    <section className="deep-thinking-panel" ref={dialogRef} role="dialog" aria-modal={nestedModalOpen ? undefined : true} aria-label={sessionKindLabel(kind)} onMouseDown={event => event.stopPropagation()}>
      {portraitViewer && <PortraitViewer portrait={portraitViewer} onClose={() => setPortraitViewer(null)}/>}
      {capabilityDrawerOpen && (
        <DeepCapabilityDrawer
          catalog={capabilityCatalog}
          loading={capabilityCatalogLoading}
          error={capabilityCatalogError}
          selectedSkillIds={selectedSkillIds}
          pluginPendingId={pluginPendingId}
          workspaceResources={workspaceResources}
          workspaceResourceLoading={workspaceResourceLoading}
          workspaceResourceError={workspaceResourceError}
          workspaceResourceDraft={workspaceResourceDraft}
          workspaceResourceSaving={workspaceResourceSaving}
          workspacePackageDraft={workspacePackageDraft}
          workspacePackageSaving={workspacePackageSaving}
          onToggleSkill={toggleSkill}
          onTogglePlugin={togglePlugin}
          onReload={() => void loadCapabilities()}
          onReloadWorkspaceResources={() => void loadWorkspaceResources()}
          onOpenWorkspaceResource={(kind, name) => void openWorkspaceResource(kind, name)}
          onCreateWorkspaceResource={createWorkspaceResourceDraft}
          onChangeWorkspaceResourceDraft={setWorkspaceResourceDraft}
          onCloseWorkspaceResource={() => setWorkspaceResourceDraft(null)}
          onSaveWorkspaceResource={draft => void saveWorkspaceResource(draft)}
          onMergeWorkspaceResource={draft => void mergeWorkspaceResource(draft)}
          onDeleteWorkspaceResource={draft => void deleteWorkspaceResource(draft)}
          onRestoreWorkspaceResource={(draft, version) => void restoreWorkspaceResource(draft, version)}
          onOpenWorkspacePluginPackage={draft => void openWorkspacePluginPackage(draft)}
          onChangeWorkspacePackageDraft={setWorkspacePackageDraft}
          onPreviewWorkspacePluginPackage={draft => void previewWorkspacePluginPackage(draft)}
          onApplyWorkspacePluginPackage={draft => void applyWorkspacePluginPackage(draft)}
          onCloseWorkspacePluginPackage={() => setWorkspacePackageDraft(null)}
          onClose={() => setCapabilityDrawerOpen(false)}
        />
      )}
      <header className="deep-thinking-header"><div><span className="deep-thinking-eyebrow"><BrainCircuit size={15}/>{sessionKindLabel(kind)}{streamState !== 'idle' && <em className={`deep-stream-state ${streamState}`}>{streamState === 'connecting' ? '连接中' : streamState === 'reconnecting' ? '自动重连' : streamState === 'error' ? '连接受限' : '实时'}</em>}</span><h2>{title}</h2></div><div className="deep-thinking-header-actions">{activeJobId && !isTerminalJob(activeJob) && <button type="button" className="deep-cancel-job" onClick={() => void cancelActiveJob()}><X size={13}/>取消任务</button>}<button type="button" className={`deep-capability-button${capabilityDrawerOpen ? ' active' : ''}`} aria-expanded={capabilityDrawerOpen} onClick={() => setCapabilityDrawerOpen(true)}><Puzzle size={14}/><span>能力</span><em>{selectedSkillIds.length}</em></button><button type="button" className="deep-new-session" onClick={() => { setShowArchivedSessions(false); startNew(); }}><Plus size={14}/><span>新对话</span></button><button type="button" className="icon-button" aria-label="关闭深度思考" title="关闭" onClick={() => onClose?.()}><X size={17}/></button></div></header>
      <div className="deep-thinking-context">
        <div className="deep-context-query" title={historyQueryParts.full || '暂无 Query'}>
          <span>当前 Query</span>
          <p className="deep-context-query-topic">{historyQueryParts.topic || '暂无 Query'}</p>
          {historyQueryParts.hasBackground && <p className="deep-context-query-bg">{historyQueryParts.background}</p>}
        </div>
        {focusedEquipmentLabel && <div className="deep-context-focus"><span>聚焦对象</span><p>{focusedEquipmentLabel}</p></div>}
        <div className="deep-context-council"><span>研究方式</span><p>持续深度发散 · 动态调度专家 · 随时可继续追问</p></div>
        <div className="deep-context-objective"><span>产出硬约束</span><p>新质颠覆 · 直接物理毁伤 · 单装闭环</p></div>
        {runId && runId !== workbenchRunId && <div className="deep-context-focus"><span>历史任务</span><p>正在查看其他 Query 的定向深研会话</p></div>}
      </div>
      {showStageStrip && !showTargetPicker && <StageStrip stages={visibleStageStrip}/>} 
      <div className="deep-thinking-layout">
        <aside className="deep-session-list">
          <header>
            <div><b>定向深研历史</b><span>{visibleSessionCount}</span></div>
            <nav aria-label="对话历史筛选">
              <button type="button" className={!showArchivedSessions ? 'active' : ''} onClick={() => { setDeleteConfirmSessionId(''); setShowArchivedSessions(false); }}>当前 {currentSessions.length}</button>
              <button type="button" className={showArchivedSessions ? 'active' : ''} onClick={() => { setDeleteConfirmSessionId(''); setShowArchivedSessions(true); }}>归档 {archivedSessions.length}</button>
            </nav>
          </header>
          {sessionsError && <p className="deep-panel-error"><CircleAlert size={13}/>{sessionsError}</p>}
          {loadingSessions && !sessions.length ? (
            <p className="deep-session-empty"><RefreshCw size={14} className="spin"/>读取中…</p>
          ) : visibleGroups.length ? visibleGroups.map(group => {
            const groupKey = safeText(group.group_key);
            const collapsed = Boolean(collapsedGroups[groupKey]);
            const queryParts = splitQueryDisplay(group.query);
            const sessionCount = group.session_count || group.sessions.length;
            return (
              <section className={`deep-history-group${group.is_current ? ' current' : ''}${collapsed ? ' collapsed' : ''}`} key={groupKey || group.query}>
                <button type="button" className="deep-history-group-toggle" onClick={() => setCollapsedGroups(current => ({...current, [groupKey]: !collapsed}))} aria-expanded={!collapsed} title={queryParts.full}>
                  <span className="deep-history-group-chevron" aria-hidden="true">{collapsed ? <ChevronRight size={13}/> : <ChevronDown size={13}/>}</span>
                  <span className="deep-history-group-main">
                    <span className="deep-history-group-topic">{queryParts.topic}</span>
                    <span className="deep-history-group-meta">
                      <em className={group.is_current ? 'current' : ''}>{group.is_current ? '当前 Query' : '历史 Query'}</em>
                      <span>{sessionCount} 段对话</span>
                      {queryParts.hasBackground && <span className="deep-history-group-hint">含背景</span>}
                    </span>
                  </span>
                </button>
                {!collapsed && (
                  <div className="deep-history-group-body">
                    {(queryParts.hasBackground || queryParts.topic.length > 28) && (
                      <details className="deep-history-group-query">
                        <summary>
                          <span className="deep-history-group-query-label">完整 Query</span>
                          <span className="deep-history-group-query-preview">
                            {queryParts.hasBackground ? queryParts.backgroundPreview : queryParts.topic}
                          </span>
                        </summary>
                        <div className="deep-history-group-query-body">
                          <p><b>主题</b>{queryParts.topic}</p>
                          {queryParts.hasBackground && <p><b>背景</b>{queryParts.background}</p>}
                        </div>
                      </details>
                    )}
                    <div className="deep-history-group-sessions">{group.sessions.map(renderSessionRow)}</div>
                  </div>
                )}
              </section>
            );
          }) : (
            <p className="deep-session-empty">{showArchivedSessions ? '没有已归档对话' : '还没有定向深研会话'}<br/><small>{showArchivedSessions ? '归档后可在这里恢复或删除' : '按 Query 任务分组后会出现在这里'}</small></p>
          )}
        </aside>
        <main className={`deep-conversation${conversationHandoff ? ' handoff' : ''}`}>
          {showTargetPicker ? (
            <section className="deep-target-picker" aria-label="选择深度思考装备">
              <header><BrainCircuit size={14}/><b>先选择一个具体武器/装备</b></header>
              <p>左侧可浏览全部 Query 下的定向深研历史。开始新对话前，请先选择一张能力卡或参考武器卡。</p>
              {targetOptions.length ? (
                <div className="deep-target-options">
                  {targetOptions.map(option => {
                    const optionKey = deepTargetOptionKey(option);
                    const label = deepEquipmentLabel(option.value) || '未命名装备';
                    const secondary = option.kind === 'reference-research' ? '参考武器 · 定向深研' : '能力画像 · 定向深研';
                    return <button type="button" className="deep-target-option" key={optionKey} onClick={() => { setSelectedTargetIdentity(optionKey); setConversationRunId(workbenchRunId); setError(''); }}><b title={label}>{label}</b><small>{secondary}</small></button>;
                  })}
                </div>
              ) : (
                <p className="deep-target-empty">当前结果中没有可绑定的装备卡。请从具体能力卡或参考武器卡上的“深度追问/定向深研”入口进入，或先打开左侧历史会话。</p>
              )}
            </section>
          ) : (
            <>
              {showJobBanner && <div className={`deep-job-banner ${isTerminalJob(activeJob) ? safeText(activeJob.status).toLowerCase() : 'running'}`}><span><Clock3 size={14}/><b>{jobDisplayLabel(kind)}</b><em>{jobStatusLabel(isTerminalJob(activeJob) ? activeJob.status : 'running')}</em></span><small>{legacyChildRunLabel(activeJob) || (displayedJobStage ? `当前阶段：${activeStageLabel(displayedJobStage)}` : '等待 Worker 返回阶段进度')}</small>{(jobError || activeJob.error) && <span className="deep-inline-error"><CircleAlert size={12}/>{jobError || friendlyDeepJobError(activeJob.error)}</span>}{(jobError || ['failed', 'blocked', 'partial', 'cancelled'].includes(safeText(activeJob.status).toLowerCase())) && <button type="button" onClick={retryLastQuestion}><RefreshCw size={13}/>重试</button>}</div>}
              {session?.session_id && <nav className="deep-branch-bar" aria-label="研究分支"><span><GitBranch size={13}/>研究分支</span><div>{branches.map(branch => {
                const branchId = safeText(branch?.branch_id) || DEFAULT_BRANCH_ID;
                return <button type="button" key={branchId} className={activeBranchId === branchId ? 'active' : ''} disabled={jobRunning && activeBranchId !== branchId} onClick={() => switchBranch(branchId)} title={safeText(branch?.title) || (branchId === DEFAULT_BRANCH_ID ? '主线' : '探索分支')}>{safeText(branch?.title) || (branchId === DEFAULT_BRANCH_ID ? '主线' : '探索分支')}</button>;
              })}</div>{userPrompts.length > 1 && (
                <div className="deep-prompt-nav" aria-label="问题导航">
                  <button type="button" aria-label="上一个问题" disabled={userPrompts.length < 2} onClick={() => {
                    const currentId = [...userPrompts].reverse().find(item => {
                      const el = messagesRef.current?.querySelector(`[data-prompt-id="${CSS.escape(safeText(item.message_id))}"]`);
                      return el instanceof HTMLElement && el.getBoundingClientRect().top >= (messagesRef.current?.getBoundingClientRect().top || 0) - 8;
                    }) || userPrompts[userPrompts.length - 1];
                    const index = Math.max(0, userPrompts.findIndex(item => safeText(item.message_id) === safeText(currentId?.message_id)) - 1);
                    jumpToPrompt(userPrompts[index]?.message_id);
                  }}><ChevronLeft size={13}/></button>
                  <span>{userPrompts.length} 问</span>
                  <button type="button" aria-label="下一个问题" onClick={() => jumpToPrompt(userPrompts[userPrompts.length - 1]?.message_id)}><ChevronDown size={13}/></button>
                </div>
              )}{branches.length > 1 && <small>{branches.length} 条路径上下文相互隔离</small>}</nav>}
              <div className="deep-thread">
              <div
                className="deep-message-scroll"
                ref={messagesRef}
                onScroll={event => syncThreadCamera(event.currentTarget)}
                onWheel={event => {
                  if (event.deltaY < 0) stickToBottomRef.current = false;
                  else if (isThreadNearBottom(event.currentTarget, THREAD_NEAR_BOTTOM_PX + event.deltaY)) {
                    stickToBottomRef.current = true;
                  }
                }}
              >
                <AssistantQuoteAction containerRef={messagesRef} onQuote={excerpt => quoteIntoComposer(excerpt)}/>
                {loadingSession && !visibleMessages.length && !sending ? (
                  <div className="deep-loading"><RefreshCw size={18} className="spin"/>正在读取会话…</div>
                ) : (
                  <>
                    {visibleMessages.length
                      ? leadingMessages.map(message => <MessageBubble key={message.message_id || `${message.role}-${message.created_at}`} message={message} artifacts={artifacts} onOpenPortrait={setPortraitViewer} steerReceipt={steerReceipts[safeText(message.message_id)]} onCancelSteer={cancelSteer} onFork={forkFromMessage} onQuote={excerpt => quoteIntoComposer(excerpt)} onCopy={copyMessage} copied={copiedMessageId === safeText(message.message_id)} branchPending={branchActionMessageId === safeText(message.message_id)} branchDisabled={jobRunning}/>)
                      : <div className="deep-welcome"><span><Sparkles size={19}/></span><h3>战创灵境·新质装备创新舱</h3><p>点选一条建议即可直接开场；也可在下方输入框自定义问题。Enter 发送，Shift+Enter 换行。</p><div className="deep-suggestions">{welcomeSuggestions.map(item => <button type="button" key={item} onClick={() => void send(null, {content: item})}>{item}<ArrowUp size={13}/></button>)}</div></div>}
                    {showProcessThread && (
                      <ProcessFeedbackThread
                        events={visibleStageEvents}
                        sending={sending}
                        liveAnswer={liveAnswer}
                        showLiveAnswer={showLiveAnswer}
                        activeJob={activeJob}
                        activeSkillIds={selectedSkillIds}
                        ownedCandidateNames={boardOwnedCandidateNames}
                        onQuoteCandidate={(name, brief) => {
                          const prompt = directionFollowUp({name, ...brief})
                            || `围绕「${name}」继续深化：闭合打击对象、直接毁伤机理与任务失能判据。`;
                          void send(null, {content: formatQuotedDeepMessage(prompt, name)});
                        }}
                      />
                    )}
                    {showStreamingBubble && (
                      <article className="deep-message assistant streaming" aria-live="polite" aria-label="正在回传的可见结果">
                        <div className="deep-message-meta">
                          <span className="deep-message-avatar">AI</span>
                          <b>创新舱</b>
                          <small><StreamingLabel active={sending}>{sending ? (liveFeedback.running_label || '正在回传可见结果') : '本轮即时结果'}</StreamingLabel></small>
                        </div>
                        <div className="deep-message-body" data-assistant-selectable="true">
                          {streamingDraft
                            ? <AssistantMarkdown className="deep-process-live-text">{streamingDraft}</AssistantMarkdown>
                            : <p><StreamingLabel active>{liveFeedback.running_excerpt || '问题已进入创新舱，完成一路就立刻回传到对话里。'}</StreamingLabel></p>}
                          {sending && <span className="deep-stream-caret" aria-hidden="true"/>}
                        </div>
                      </article>
                    )}
                    {trailingMessages.map(message => <MessageBubble key={message.message_id || `trail-${message.role}-${message.created_at}`} message={message} artifacts={artifacts} onOpenPortrait={setPortraitViewer} steerReceipt={steerReceipts[safeText(message.message_id)]} onCancelSteer={cancelSteer} onFork={forkFromMessage} onQuote={excerpt => quoteIntoComposer(excerpt)} onCopy={copyMessage} copied={copiedMessageId === safeText(message.message_id)} branchPending={branchActionMessageId === safeText(message.message_id)} branchDisabled={jobRunning}/>)}
                  </>
                )}
                {awaitingCardConfirmation && <section className="deep-card-confirmation" aria-label="确认是否形成能力卡"><div><Sparkles size={15}/><span><b>这个方向值得形成能力卡吗？</b><small>确认或输入 /card 后将当前方向整理为五栏画像；后续仍可在任意分支继续探索。</small></span></div><div><button type="button" className="secondary" onClick={() => { setDraft(followUpQuestions[0] || '继续深挖当前方向的关键机理、反制边界与任务失能判据。'); composerRef.current?.focus(); }}>继续深挖</button><button type="button" className="primary" onClick={() => void send(null, {content: CARD_AUTHORING_CONFIRMATION, createArtifact: true})}><CheckCircle2 size={14}/>形成能力卡</button></div></section>}
                {followUpQuestions.length > 0 && visibleMessages.length > 0 && !sending && <div className="deep-next-questions"><span>继续追问 · 点击直接发送</span>{followUpQuestions.map(item => <button type="button" key={item} onClick={() => void send(null, {content: item})}>{item}<ArrowUp size={13}/></button>)}</div>}
                <DeliberationBoard answer={liveDeliberationAnswer} stageEvents={visibleStageEvents} sending={sending} onFocusDirection={focusDirection}/>
                {!sending && showResultState && <section className={`deep-result-state deep-result-state-inline ${resultState.tone}`} aria-live="polite"><span className="deep-result-state-icon"><ResultStateIcon size={14}/></span><div><b>{resultState.title}</b><small>{resultState.detail}</small></div></section>}
                {!sending && artifacts.length > 0 && <section className="deep-artifacts"><header><div><Sparkles size={15}/><b>最终成果 · 五栏能力画像</b></div><span>{artifacts.length} 张候选卡</span></header>{artifacts.slice(-3).reverse().map((artifact, index) => <ArtifactCard key={artifactId(artifact) || index} artifact={artifact?.payload || artifact} sessionId={session?.session_id} apiBase={apiBase} runId={runId} scope={normalizedContext} versions={capabilityVersions} onMerged={onChanged} onOpenPortrait={setPortraitViewer}/>)}</section>}
                {!sending && session?.session_id && (visibleMessages.length > 0 || artifacts.length > 0) && capabilityVersions.length > 0 && <section className="deep-versions"><header><div><GitCompare size={14}/><b>版本链</b></div><span>{capabilityVersions.length} 个版本 · 原卡保持不可变</span></header>{capabilityVersions.slice().reverse().map(version => <article key={version.version_id}><div><b>v{version.version_no || '?'}</b><span className={`deep-version-status ${version.status || 'pending_verification'}`}>{version.status === 'formal' || version.status === 'verified' ? '已核验' : version.status === 'rejected' ? '已驳回' : version.status === 'rolled_back' ? '已回滚' : '待核验'}</span><small>{version.source || 'deep-thinking'} · {version.created_at ? new Date(version.created_at).toLocaleString('zh-CN', {hour12:false}) : ''}</small></div>{version.evidence_refs?.length > 0 && <p>证据 {version.evidence_refs.length} 条：{version.evidence_refs.slice(0, 6).map((ref, index) => <code key={`${version.version_id}-${index}`}>{safeText(ref)}</code>)}</p>}{version.diff && <details><summary>查看结构化差异</summary><pre>{JSON.stringify(version.diff, null, 2)}</pre></details>}</article>)}</section>}
              </div>
              {showJumpBottom && (
                <button type="button" className="deep-jump-bottom" onClick={jumpToLatest}>
                  <ArrowDown size={14}/>回到最新
                </button>
              )}
              </div>
              <form className="deep-composer" onSubmit={send}>
                {queuedPrompts.length > 0 && (
                  <div className="deep-queued-prompts" aria-label="已排队追问">
                    <span>下一轮将继续</span>
                    {queuedPrompts.map(item => {
                      const receipt = steerReceipts[safeText(item.message_id)] || {};
                      const mode = safeText(receipt.mode || item.steer_mode);
                      const modeLabel = DEEP_STEER_MODES.find(entry => entry.id === mode)?.label || steerStatusLabel(receipt.status || item.status, mode);
                      return (
                        <article key={item.message_id}>
                          <b>{modeLabel}</b>
                          <div className="deep-queued-prompt-body">
                            <UserMessageText content={item.content}/>
                          </div>
                          {receipt.steer_id && queuedSteerStatuses.has(safeText(receipt.status).toLowerCase()) && (
                            <button type="button" aria-label="取消这条追问" onClick={() => void cancelSteer(receipt)}><X size={12}/></button>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}
                {quotedContext && (
                  <div className="deep-quoted-context" aria-label="引用片段">
                    <Quote size={13}/>
                    <p>{quotedContext}</p>
                    <button type="button" aria-label="取消引用" onClick={() => setQuotedContext('')}><X size={12}/></button>
                  </div>
                )}
                {slashMatches.length > 0 && (
                  <div className="deep-slash-palette" role="listbox" aria-label="定向深研命令">
                    <span><Slash size={11}/>输入 / 调用命令</span>
                    {slashMatches.map((item, index) => (
                      <button
                        type="button"
                        key={item.id}
                        role="option"
                        aria-selected={index === selectedSlashIndex}
                        className={index === selectedSlashIndex ? 'active' : ''}
                        onMouseEnter={() => setSelectedSlashIndex(index)}
                        onClick={() => {
                          setDraft(`${item.command} `);
                          composerRef.current?.focus();
                        }}
                      >
                        <code>{item.command}</code>
                        <b>{item.label}</b>
                        <small>{item.detail}</small>
                      </button>
                    ))}
                  </div>
                )}
                {selectedSkillIds.length > 0 && (
                  <div className="deep-composer-skills" aria-label="本轮启用的 Skill">
                    <span><Puzzle size={11}/>本轮 Skill</span>
                    <div>{selectedSkillIds.map(skillId => (
                      <button type="button" key={skillId} title={`移除 ${skillId}`} onClick={() => toggleSkill(skillId, false)}>
                        <b>{skillId}</b><X size={10}/>
                      </button>
                    ))}</div>
                  </div>
                )}
                <div className="deep-composer-shell">
                  <textarea
                    ref={composerRef}
                    value={draft}
                    maxLength={MAX_MESSAGE_CHARS}
                    onChange={event => { setDraft(event.target.value); if (error) setError(''); }}
                    onKeyDown={event => {
                      if (event.nativeEvent.isComposing) return;
                      if (slashMatches.length > 0) {
                        if (event.key === 'ArrowDown') {
                          event.preventDefault();
                          setSelectedSlashIndex(current => (current + 1) % slashMatches.length);
                          return;
                        }
                        if (event.key === 'ArrowUp') {
                          event.preventDefault();
                          setSelectedSlashIndex(current => (current - 1 + slashMatches.length) % slashMatches.length);
                          return;
                        }
                        if (event.key === 'Escape') {
                          event.preventDefault();
                          setDraft('');
                          return;
                        }
                        if ((event.key === 'Tab' || event.key === 'Enter') && !matchDeepSlashCommand(draft)) {
                          event.preventDefault();
                          const chosen = slashMatches[selectedSlashIndex] || slashMatches[0];
                          setDraft(`${chosen.command} `);
                          return;
                        }
                      }
                      if (event.key === 'Escape' && quotedContext) {
                        event.preventDefault();
                        setQuotedContext('');
                        return;
                      }
                      if (event.key === 'Tab' && jobRunning && draft.trim() && !event.shiftKey) {
                        event.preventDefault();
                        void send(event, {mode: 'queue'});
                        return;
                      }
                      if (event.key === 'Enter' && !event.shiftKey && !event.altKey) {
                        event.preventDefault();
                        if (draft.trim() || quotedContext) void send(event);
                      }
                    }}
                    placeholder={viewingArchivedSession ? "归档会话只读，恢复后可继续追问…" : (jobRunning ? "正在深度发散：Enter 立即纳入，Tab 排到下一轮，Shift+Enter 换行…" : "继续追问，Enter 发送，Shift+Enter 换行，或输入 / 调用命令…")}
                    aria-label="输入深度思考问题"
                  />
                  {jobRunning && !draft.trim() && !quotedContext ? (
                    <button type="button" className="deep-composer-send stop" aria-label="停止当前研究" onClick={() => void cancelActiveJob()}><Square size={13}/></button>
                  ) : (
                    <button type="submit" className="deep-composer-send" aria-label={jobRunning ? '发送即时追问' : '发送'} disabled={(!draft.trim() && !quotedContext) || !runId || viewingArchivedSession || steerSubmitting || (sending && !activeJobId)}>{steerSubmitting ? <RefreshCw size={15} className="spin"/> : <ArrowUp size={17}/>}</button>
                  )}
                </div>
                {jobRunning && <div className="deep-run-mode-row"><span>本条追问</span><div className="deep-run-mode-selector"><button type="button" aria-haspopup="menu" aria-expanded={showRunModeMenu} onClick={() => setShowRunModeMenu(current => !current)}><SelectedSteerModeIcon size={13}/><b>{selectedSteerMode.label}</b><ChevronDown size={12}/></button>{showRunModeMenu && <div className="deep-run-mode-menu" role="menu">{DEEP_STEER_MODES.map(item => { const ModeIcon = item.icon; return <button type="button" role="menuitem" className={duringRunMode === item.id ? 'active' : ''} key={item.id} onClick={() => { setDuringRunMode(item.id); setShowRunModeMenu(false); composerRef.current?.focus(); }}><ModeIcon size={14}/><span><b>{item.label}</b><small>{item.detail}</small></span>{duringRunMode === item.id && <Check size={13}/>}</button>; })}</div>}</div><small>{selectedSteerMode.detail} · Enter 立即纳入 · Tab 排队</small></div>}
                <div className="deep-composer-footer">
                  <small>{error ? <span className="deep-inline-error"><CircleAlert size={12}/>{error}</span> : (jobRunning ? '生成中也可连续追问；Enter 纳入当前研究，Tab 排到下一轮，空输入框可停止' : '选中回答可引用追问；Enter 发送，Shift+Enter 换行；/card 成卡、/memory 查看记忆')}</small>
                  <div className="deep-composer-meta">
                    <ContextUsageChip usage={contextUsage} memory={decisionMemory} branchLabel={activeBranchLabel} activeSkillCount={selectedSkillIds.length} open={contextUsageOpen} onToggle={() => setContextUsageOpen(current => !current)}/>
                    <span>{draft.length}/{MAX_MESSAGE_CHARS} · {jobRunning ? 'Enter / Tab' : 'Enter 发送'}</span>
                  </div>
                </div>
              </form>
            </>
          )}
        </main>
      </div>
    </section>
  </div>;
}

/**
 * App-level dock. It listens for `equipment:open-deep-thinking`, allowing a
 * capability/reference card (or the capability-page target picker) to open
 * the same panel without introducing a context provider into the existing
 * workbench tree.  It deliberately does not render an unbound floating
 * launcher: a deep turn must start from one concrete equipment target.
 */
export function DeepThinkingDock({apiBase, run, enabled = true, onChanged}) {
  const initialLocation = useMemo(() => readDeepThinkingLocation(), []);
  const [open, setOpen] = useState(initialLocation.open);
  const [context, setContext] = useState({
    kind: 'deep-thinking',
    sessionId: initialLocation.sessionId,
    branchId: initialLocation.branchId,
    targetIdentity: initialLocation.targetIdentity,
  });
  const runId = safeText(run?.run_id);
  const previousRunIdRef = useRef(runId);
  useEffect(() => {
    const openFromEvent = event => {
      const detail = event?.detail || {};
      if (detail.runId && runId && String(detail.runId) !== runId) return;
      const next = {
        ...detail,
        runId: detail.runId || runId,
        sessionId: safeText(detail.sessionId || detail.session_id),
        branchId: safeText(detail.branchId || detail.branch_id) || DEFAULT_BRANCH_ID,
        targetIdentity: safeText(detail.targetIdentity || detail.target_identity),
      };
      setContext(next);
      writeDeepThinkingLocation(next);
      setOpen(true);
    };
    const syncFromLocation = () => {
      const location = readDeepThinkingLocation();
      setOpen(location.open);
      setContext(current => location.open ? {
        ...current,
        runId,
        sessionId: location.sessionId,
        branchId: location.branchId,
        targetIdentity: location.targetIdentity,
      } : {kind: 'deep-thinking'});
    };
    window.addEventListener(OPEN_DEEP_THINKING_EVENT, openFromEvent);
    window.addEventListener('popstate', syncFromLocation);
    return () => {
      window.removeEventListener(OPEN_DEEP_THINKING_EVENT, openFromEvent);
      window.removeEventListener('popstate', syncFromLocation);
    };
  }, [runId]);
  useEffect(() => {
    const previousRunId = previousRunIdRef.current;
    // A dock can survive the task rail changing the selected parent run.  Do
    // not let the old panel's canonical equipment target be submitted against
    // the newly selected run; force a fresh, unbound launcher context.
    if (!runId || (previousRunId && previousRunId !== runId)) {
      setOpen(false);
      setContext({kind: 'deep-thinking'});
      if (readDeepThinkingLocation().open) clearDeepThinkingLocation({replace: true});
    }
    previousRunIdRef.current = runId;
  }, [runId]);
  const close = useCallback(() => {
    const location = readDeepThinkingLocation();
    if (location.open && window.history.state?.deepOpen) {
      window.history.back();
      return;
    }
    clearDeepThinkingLocation({replace: true});
    setOpen(false);
  }, []);
  const syncNavigation = useCallback(next => {
    const navigation = {
      sessionId: safeText(next?.sessionId || next?.session_id),
      branchId: safeText(next?.branchId || next?.branch_id) || DEFAULT_BRANCH_ID,
      targetIdentity: safeText(next?.targetIdentity || next?.target_identity),
    };
    setContext(current => (
      safeText(current.sessionId) === navigation.sessionId
      && (safeText(current.branchId) || DEFAULT_BRANCH_ID) === navigation.branchId
      && safeText(current.targetIdentity) === navigation.targetIdentity
        ? current
        : {...current, ...navigation}
    ));
    const location = readDeepThinkingLocation();
    if (
      !location.open
      || location.sessionId !== navigation.sessionId
      || location.branchId !== navigation.branchId
      || location.targetIdentity !== navigation.targetIdentity
    ) {
      writeDeepThinkingLocation(navigation, {replace: true});
    }
  }, []);
  if (!enabled || !runId) return null;
  return <>{open && <DeepThinkingPanel apiBase={apiBase} run={run} context={{...context, runId}} onClose={close} onChanged={onChanged} onNavigationChange={syncNavigation}/>}</>;
}
