import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {Activity, Archive, BarChart3, BookOpenCheck, Bot, BrainCircuit, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, ClipboardCheck, Clock3, Database, Eye, FileCheck2, FileSpreadsheet, FlaskConical, Gauge, GitCompare, History, Layers3, Lightbulb, ListFilter, Pencil, Play, Plus, Radar, RefreshCw, Save, Search, ShieldAlert, ShieldCheck, Sparkles, Trash2, Upload, Wrench, X, Zap} from 'lucide-react';
import './styles.css';
import './responsive-nav.css';
import './live.css';
import './blueprint.css';
import './benchmark.css';
import './agent-selection.css';
import './research-launch.css';

const api = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
const DEFAULT_EXECUTION_PROFILE_ID = 'winning_swarm_dynamic_v2';
const extensionModules = import.meta.glob('./features/*/index.jsx', {eager: true});
const workbenchExtensions = Object.values(extensionModules)
  .map(module => module.default)
  .filter(extension => extension?.id && extension?.Component);
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
  {step: 5, agent_id: 'winning_s5_gap', name: '装备现状与差距 Agent', task: '盘点现役与在研能力，对齐基准并形成五档能力差距。', skills: ['gap_quantification', 'equipment_system_gap_assessment'], harness: 'winning_step_v1', semantics: ['可与 S4 迭代', '可跳步', '可回溯']},
  {step: 6, agent_id: 'winning_s6_image', name: '能力图像综合 Agent', task: '融合差距与前序认识，排序形成装备能力需求图像。', skills: ['capability_image_generation', 'capability_portfolio_synthesis'], harness: 'winning_step_v1', semantics: ['收敛输出', '保留冲突', '可回溯']},
];
const LOOP_ARCHITECTURE = [
  {key: 'inner', level: 'L1', name: '步骤门控', description: '优先执行本地确定性检查；仅证据、必填结构或军事作用机理存在实质缺口时局部修复。'},
  {key: 'middle', level: 'L2', name: '因果复核', description: '仅在跨步骤断链或高风险矛盾时触发模型复核，并只重跑受影响的 S Agent。'},
  {key: 'outer', level: 'L3', name: '残差回溯', description: '只对会改变能力结论的证据残差定向补强，不因一般覆盖标签不足重跑全链。'},
  {key: 'meta', level: 'L4', name: '元循环', description: '调整 A–H 蓝图、S Agent 强度与动态专用 Agent，保持有界重规划。'},
];
const nav = [
  ['runs', '研究任务', Archive], ['interactions', '交互过程', Layers3], ['evidence', '证据中心', Search],
  ['winning', 'S1–S6 Agent', BrainCircuit], ['capabilities', '能力画像', FlaskConical],
  ['reports', '报告评审', FileCheck2], ['benchmark', '测试 Benchmark', Gauge],
  ...workbenchExtensions.map(extension => [extension.id, extension.label, extension.icon]),
];
const LLM_PRESETS = {
  openai: {label: 'GPT / OpenAI', api_protocol: 'responses', base_url: 'https://api.openai.com/v1', model: 'gpt-5.5'},
  deepseek: {label: 'DeepSeek', api_protocol: 'chat_completions', base_url: 'https://api.deepseek.com', model: 'deepseek-chat'},
  qwen: {label: '千问', api_protocol: 'chat_completions', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus'},
  zhipu: {label: '智谱 GLM', api_protocol: 'chat_completions', base_url: 'https://yunwu.ai/v1', model: 'glm-5.2'},
  custom: {label: '自定义中转站', api_protocol: 'chat_completions', base_url: '', model: ''},
};
const shuffleRecommendations = items => {
  const rows = [...items];
  for (let index = rows.length - 1; index > 0; index -= 1) {
    const target = Math.floor(Math.random() * (index + 1));
    [rows[index], rows[target]] = [rows[target], rows[index]];
  }
  return rows;
};
function App() {
  const [view, setView] = useState('runs');
  const [runs, setRuns] = useState([]);
  const [catalog, setCatalog] = useState({routes: [], agents: [], interaction_modes: [], discovery_branches: [], execution_profiles: [], report_templates: [], provider: {}});
  const [pendingQuery, setPendingQuery] = useState(null);
  const [selected, setSelected] = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const [healthy, setHealthy] = useState(false);
  const [enabledExtensionIds, setEnabledExtensionIds] = useState([]);
  const [runtime, setRuntime] = useState({worker_online: false, pending_count: 0, workers: [], worker_capacity: 0, configured_worker_capacity: 1, active_count: 0, available_slots: 0, active_run_ids: []});
  const load = async () => {
    const [runRows, config, health, runtimeHealth] = await Promise.all([
      request('/runs', []), request('/catalog', {routes: [], agents: [], interaction_modes: [], discovery_branches: [], execution_profiles: [], report_templates: [], provider: {}}), request('/health', null), request('/runtime-health', {worker_online: false, pending_count: 0, workers: [], worker_capacity: 0, configured_worker_capacity: 1, active_count: 0, available_slots: 0, active_run_ids: []}),
    ]);
    setRuns(runRows); setCatalog(config); setHealthy(health?.status === 'ok'); setRuntime(runtimeHealth);
    setActiveRun(current => current ? runRows.find(item => item.run_id === current.run_id) || current : current);
    setSelected(current => current ? runRows.find(item => item.run_id === current.run_id) || current : current);
  };
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (!document.hidden) void load(); }, 5000);
    const refreshWhenVisible = () => { if (!document.hidden) void load(); };
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', refreshWhenVisible); };
  }, []);
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
      <div className="brand-mark"><Radar size={20}/></div><div className="brand-copy"><b>装备能力图像</b><span>DEEP RESEARCH WORKBENCH</span></div>
      <div className="topbar-route">市场需求挖掘 · S1–S6 Agent · 能力画像</div>
      <div className={`service-state ${healthy && runtime.worker_online ? 'online' : 'offline'}`} title={runtime.worker_online ? `在线 Worker ${runtime.online_worker_count || 0} 个；可用槽位 ${runtime.available_slots || 0}；活动任务 ${(runtime.active_run_ids || []).join('、') || '无'}；排队 ${runtime.pending_count || 0} 项` : '请启动独立 research worker'}><i/>{!healthy ? 'API 未连接' : runtime.worker_online ? `并行槽位 ${runtime.active_count || 0}/${runtime.worker_capacity || 0} · 排队 ${runtime.pending_count || 0}` : 'Worker 未启动'}</div>
    </header>
    <aside className="sidebar"><div className="sidebar-label">研究工作台</div>{visibleNav.map(([id, label, Icon]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}><Icon size={18}/><span>{label}</span></button>)}<div className="sidebar-note"><ShieldCheck size={15}/><span>最小权限 · 审计留痕</span></div></aside>
    <nav className="mobile-nav" aria-label="研究工作台导航">{visibleNav.map(([id, label, Icon]) => <button key={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}><Icon size={16}/><span>{label}</span></button>)}</nav>
    <main>{view === 'runs' ? <RunPage runs={runs} catalog={catalog} runtime={runtime} refresh={load} initialQuery={pendingQuery} clearInitialQuery={() => setPendingQuery(null)} openQueryLibrary={() => { setView('query-library'); window.scrollTo({top: 0}); }} open={openRun} watch={run => { setActiveRun(run); setSelected(null); setView('interactions'); }}/> : view === 'benchmark' ? <BenchmarkPage/> : workbenchExtensions.some(extension => extension.id === view) ? React.createElement(workbenchExtensions.find(extension => extension.id === view).Component, {apiBase: api, onUseQuery: queryItem => { setPendingQuery(queryItem); setView('runs'); }, onDirectResearch: queryItem => { setPendingQuery(queryItem); setView('runs'); }, onBack: () => setView('runs')}) : <WorkspacePage view={view} run={activeRun} runs={runs} catalog={catalog} runtime={runtime} selectRun={run => { setActiveRun(run); setSelected(null); }}/>}</main>
    {selected && (
      <RunDrawer run={selected} catalog={catalog} close={() => setSelected(null)} inspect={target => { setView(target); setSelected(null); }} changed={updated => { setSelected(updated); setActiveRun(current => current?.run_id === updated.run_id ? updated : current); void load(); }}/>
    )}
  </div>;
}

function RunPage({runs, catalog, runtime, refresh, initialQuery, clearInitialQuery, openQueryLibrary, open, watch}) {
  const [query, setQuery] = useState(''); const [status, setStatus] = useState('all');
  const pageSize = 12; const [visibleLimit, setVisibleLimit] = useState(pageSize);
  const runScrollRef = useRef(null); const loadMoreRef = useRef(null);
  const [selectedIds, setSelectedIds] = useState([]); const [deleting, setDeleting] = useState(false); const [deleteError, setDeleteError] = useState('');
  const [runSummaries, setRunSummaries] = useState({});
  const matchesStatus = run => status === 'all' ? run.status !== 'archived' : status === 'active' ? isRunActive(run, runtime) : run.status === status;
  const visible = runs.filter(run => (!query || `${run.topic} ${run.supplemental_information || ''} ${run.run_id}`.toLowerCase().includes(query.toLowerCase())) && matchesStatus(run));
  const pageRows = visible.slice(0, visibleLimit);
  const hasMoreRuns = pageRows.length < visible.length;
  useEffect(() => {
    setVisibleLimit(pageSize);
    if (runScrollRef.current) runScrollRef.current.scrollTop = 0;
  }, [query, status]);
  useEffect(() => {
    const root = runScrollRef.current; const target = loadMoreRef.current;
    if (!root || !target || !hasMoreRuns) return undefined;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setVisibleLimit(value => Math.min(visible.length, value + pageSize));
      }
    }, {root, rootMargin: '0px 0px 220px 0px', threshold: 0.01});
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMoreRuns, visible.length, visibleLimit]);
  useEffect(() => {
    const pending = pageRows.filter(run => run.status === 'completed' && runSummaries[run.run_id] === undefined);
    if (!pending.length) return undefined;
    let cancelled = false;
    Promise.all(pending.map(async run => [run.run_id, await request(`/runs/${run.run_id}/summary`, null)]))
      .then(rows => { if (!cancelled) setRunSummaries(current => ({...current, ...Object.fromEntries(rows)})); });
    return () => { cancelled = true; };
  }, [pageRows.map(run => `${run.run_id}:${run.status}`).join('|')]);
  const workerForRun = run => (runtime.workers || []).find(worker => worker.online && worker.current_run_id === run.run_id);
  const isActivelyHandled = run => Boolean(workerForRun(run));
  const queuePosition = run => (runtime.pending_run_ids || []).indexOf(run.run_id) + 1;
  const deletable = visible.filter(run => !isActivelyHandled(run));
  const pageDeletable = pageRows.filter(run => !isActivelyHandled(run));
  const selectedDeletable = selectedIds.filter(id => deletable.some(run => run.run_id === id));
  const currentCount = runs.filter(run => run.status !== 'archived').length;
  const completed = runs.filter(run => run.status === 'completed').length;
  const activeCount = runs.filter(run => isRunActive(run, runtime)).length;
  const toggleSelected = id => setSelectedIds(rows => rows.includes(id) ? rows.filter(item => item !== id) : [...rows, id]);
  const deleteRuns = async ids => {
    if (!ids.length || !window.confirm(`确定永久删除 ${ids.length} 个任务及其全部运行数据吗？此操作不可恢复。`)) return;
    setDeleting(true); setDeleteError('');
    const result = await request('/runs/permanent-delete', null, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({run_ids: ids})});
    setDeleting(false);
    if (!result) { setDeleteError('永久删除失败，请检查 API 服务后重试。'); return; }
    setSelectedIds(rows => rows.filter(id => !result.deleted.includes(id)));
    if (result.rejected?.length) setDeleteError(result.rejected.map(item => `${item.run_id}：${item.reason}`).join('；'));
    void refresh();
  };
  const renderInlineBuilder = (queryItem, executionProfileId, onExecutionProfileChange, startRequestId) => <CreateRun inline catalog={catalog} runtime={runtime} initialQuery={queryItem} executionProfileId={executionProfileId} onExecutionProfileChange={onExecutionProfileChange} startRequestId={startRequestId} openQueryLibrary={openQueryLibrary} done={(run, started) => { clearInitialQuery(); void refresh(); started ? watch(run) : open(run); }}/>;
  return <>
    <ResearchQueryEntry catalog={catalog} runtime={runtime} openQueryLibrary={openQueryLibrary} initialQuery={initialQuery} renderInlineBuilder={renderInlineBuilder}/>
    <PageTitle eyebrow="RESEARCH WORKSPACE" title="研究任务与运行记录" subtitle="Query 审核后可直接带入研究任务；运行过程、证据、能力画像和报告持续留痕。">
      <button className="icon-button" title="刷新任务" onClick={refresh}><RefreshCw size={17}/></button>
    </PageTitle>
    <section className="metric-strip parallel-metrics"><Metric label="当前任务" value={currentCount} icon={Archive}/><Metric label="已完成" value={completed} icon={CheckCircle2}/><Metric label="并行执行" value={`${runtime.active_count || 0} / ${runtime.worker_capacity || 0}`} icon={Layers3}/><Metric label="队列等待" value={runtime.pending_count || 0} icon={Clock3}/><Metric label="默认模型" value={catalog.provider.model || 'gpt-5.5'} icon={Sparkles}/></section>
    {!runtime.worker_online && <section className="worker-warning"><CircleAlert size={18}/><div><b>研究 Worker 未在线</b><span>任务无法执行。请运行 <code>./scripts/start-local.sh</code> 或启动 Compose 服务。</span></div></section>}
    {runtime.worker_online && <ParallelRuntimePanel runtime={runtime} runs={runs} onCapacityChanged={refresh}/>}
    {deleteError && <p className="form-error"><CircleAlert size={15}/>{deleteError}</p>}
    <section className="research-run-center">
      <div className="research-run-toolbar">
        <div className="run-status-tabs" aria-label="研究任务状态筛选">
          <button className={status === 'all' ? 'active' : ''} onClick={() => setStatus('all')}><Archive size={15}/>全部 <em>{currentCount}</em></button>
          <button className={status === 'active' ? 'active' : ''} onClick={() => setStatus('active')}><Clock3 size={15}/>进行中 <em>{activeCount}</em></button>
          <button className={status === 'completed' ? 'active' : ''} onClick={() => setStatus('completed')}><CheckCircle2 size={15}/>已完成 <em>{completed}</em></button>
        </div>
        <button className="run-refresh-button" onClick={refresh}><RefreshCw size={15}/>刷新</button>
      </div>
      <div className="run-live-note"><Zap size={15}/><b>实时</b><span>多智能体编排器每次运行都会沉淀报告、证据与可追溯的执行轨迹。</span></div>
      <div className="run-search-row">
        <div className="searchbox"><Search size={16}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索研究主题或运行 ID"/></div>
        <label className="filter-select"><ListFilter size={15}/><select value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部当前任务</option><option value="active">全部进行中</option><option value="draft">草稿</option><option value="queued">已排队</option><option value="researching">研究中</option><option value="recalling">再调中</option><option value="synthesizing">S1–S6 / 综合中</option><option value="reviewing">审计中</option><option value="reporting">报告生成中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="archived">已归档</option></select></label>
        <label className="run-select-page"><input type="checkbox" aria-label="选择已加载的可删除任务" checked={pageDeletable.length > 0 && pageDeletable.every(run => selectedIds.includes(run.run_id))} onChange={event => setSelectedIds(event.target.checked ? [...new Set([...selectedIds, ...pageDeletable.map(run => run.run_id)])] : selectedIds.filter(id => !pageDeletable.some(run => run.run_id === id)))}/><span>选择已加载</span></label>
        {selectedDeletable.length > 0 && <button className="danger" disabled={deleting} onClick={() => deleteRuns(selectedDeletable)}><Trash2 size={15}/>{deleting ? '删除中' : `永久删除 (${selectedDeletable.length})`}</button>}
        <span>{visible.length} 项结果</span>
      </div>
      {visible.length === 0 ? <Empty text="暂无匹配的研究任务"/> : <div className="research-run-scroll" ref={runScrollRef} aria-label="研究任务连续滚动列表"><div className="research-run-grid">{pageRows.map(run => {
        const assignedWorker = workerForRun(run); const position = queuePosition(run); const orphanedActive = isRunActive(run, runtime) && !assignedWorker && !['queued', 'pause_requested', 'cancel_requested'].includes(run.status); const displayStatus = orphanedActive && position > 0 ? 'queued' : run.status; const canDelete = !assignedWorker;
        const summary = runSummaries[run.run_id] || {}; const store = summary.store_summary || {}; const sourceCount = Number(summary.source_materials?.length || store.baseline_packet_count || 0); const evidenceCount = Number(store.materialized_evidence_count || store.evidence_count || summary.evidence_assessments?.length || 0); const candidateCount = Number(store.capability_image_count || run.result?.capability_count || 0); const reportCount = Number(store.report_count || (run.result?.report_path ? 1 : 0));
        const runtimeText = assignedWorker ? `槽位 #${assignedWorker.slot_index || '?'} · ${assignedWorker.worker_id}` : position > 0 ? `队列第 ${position} 位` : orphanedActive ? '等待 Worker 自动恢复' : run.status === 'draft' ? '等待启动' : formatRunUpdatedAt(run.updated_at);
        return <article className={`research-run-card ${displayStatus}`} key={run.run_id}>
          <div className="run-card-heading"><label className="run-card-select" title={canDelete ? '选择任务' : '在线 Worker 正在处理'}><input type="checkbox" aria-label={`选择 ${run.topic}`} disabled={!canDelete} checked={selectedIds.includes(run.run_id)} onChange={() => toggleSelected(run.run_id)}/></label><button className="run-card-title" onClick={() => open(run)}><b>{run.topic}</b><small>{run.supplemental_information || run.run_id}</small></button><Status value={displayStatus}/></div>
          <div className="run-card-counts"><span><b>{sourceCount}</b> 信源</span><span><b>{evidenceCount}</b> 证据</span><span><b>{candidateCount}</b> 候选</span><span><b>{reportCount}</b> 报告</span></div>
          <div className="run-card-meta"><span title={run.interaction_mode === 'autonomous' ? `系统实际命中：${routeLabel(run.research_route)}` : undefined}>{runRouteSelectionLabel(run)}路线 · {runAgentSelectionLabel(run)}</span><span title={runActualAgentTitle(run)}>{runtimeText}</span></div>
          <div className="run-card-footer"><span className={`run-mode-label ${run.execution?.mode === 'real' ? 'real' : 'fake'}`}><i/>{run.execution?.mode === 'real' ? '真实运行' : '离线模拟'}</span><span>{run.execution?.mode === 'real' ? `${providerDisplayLabel(run.execution?.provider)} · ` : ''}{run.execution?.model || catalog.provider.model || 'gpt-5.5'}</span><div><button className="icon-button" title="打开研究详情" onClick={() => open(run)}><Eye size={16}/></button><button className="icon-button row-delete" disabled={!canDelete || deleting} title={canDelete ? '永久删除任务及后端数据' : '在线 Worker 正在处理，暂不能永久删除'} onClick={() => deleteRuns([run.run_id])}><Trash2 size={15}/></button></div></div>
        </article>;
      })}</div><div className={`run-scroll-loader ${hasMoreRuns ? '' : 'complete'}`} ref={loadMoreRef}><span>{hasMoreRuns ? `继续下滑加载 · 已显示 ${pageRows.length} / ${visible.length}` : `已显示全部 ${visible.length} 项`}</span>{hasMoreRuns && <button onClick={() => setVisibleLimit(value => Math.min(visible.length, value + pageSize))}>加载更多</button>}</div></div>}
    </section>
  </>;
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
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '已更新';
  return `更新于 ${date.toLocaleDateString('zh-CN', {month:'2-digit', day:'2-digit'})} ${date.toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', hour12:false})}`;
}

function ResearchQueryEntry({catalog, runtime, openQueryLibrary, initialQuery, renderInlineBuilder}) {
  const [query, setQuery] = useState('');
  const [supplement, setSupplement] = useState('');
  const [selectedRecommendation, setSelectedRecommendation] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [recommendationIndex, setRecommendationIndex] = useState(0);
  const [recommendationPaused, setRecommendationPaused] = useState(false);
  const [recommendationLoading, setRecommendationLoading] = useState(true);
  const [recommendationError, setRecommendationError] = useState('');
  const [executionProfileId, setExecutionProfileId] = useState(DEFAULT_EXECUTION_PROFILE_ID);
  const [runConfigOpen, setRunConfigOpen] = useState(false);
  const [startRequestId, setStartRequestId] = useState(0);
  const [manualPickerOpen, setManualPickerOpen] = useState(false);
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
    const timer = setInterval(() => setRecommendationIndex(index => (index + 1) % recommendations.length), 3400);
    return () => clearInterval(timer);
  }, [recommendationPaused, recommendations.length]);
  const moveRecommendation = direction => setRecommendationIndex(index => (index + direction + recommendations.length) % recommendations.length);
  const chooseRecommendation = (item, index) => { setRecommendationIndex(index); setSelectedRecommendation(item); setQuery(item.query); setSupplement(item.supplemental_information || ''); };
  const openSupplement = () => { setRunConfigOpen(true); window.requestAnimationFrame(() => document.getElementById('research-query-supplement')?.focus()); };
  const activeQuery = selectedRecommendation ? {...selectedRecommendation, query:query.trim(), supplemental_information:supplement.trim()} : {query:query.trim(), supplemental_information:supplement.trim(), generation_rationale:'用户在研究首页直接输入 Query。', source_references:[], status:'published', source_type:'manual'};
  return <section className="research-query-home">
    <div className="research-query-hero">
      <span>DEEP RESEARCH QUERY</span>
      <h1>你的研究，从一个好 Query 开始</h1>
      <p>直接输入需要 Deep Research 的完整问题，或点击推荐 Query 自动回填。</p>
      <div className={`research-query-composer ${runConfigOpen ? 'config-open' : ''}`}>
        <textarea id="research-query-input" value={query} onChange={event => { setQuery(event.target.value); setSelectedRecommendation(null); }} placeholder="输入需要进行 Deep Research 的 Query，例如：研究低空无人装备在强对抗环境中的体系能力缺口" maxLength={4000}/>
        <footer><div className="research-query-footer-left"><button onClick={openSupplement}><Plus size={14}/>补充背景与约束</button><ResearchModePicker profiles={catalog.execution_profiles || []} value={executionProfileId} onChange={setExecutionProfileId}/></div><div className="research-query-footer-right"><button className="manual-query-picker-trigger" onClick={() => setManualPickerOpen(true)}><ListFilter size={15}/>人工选取 Query</button><button onClick={openQueryLibrary}><Sparkles size={15}/>AI 生成 Query</button><button className={`research-config-trigger ${runConfigOpen ? 'active' : ''}`} onClick={() => setRunConfigOpen(value => !value)}><Wrench size={14}/>{runConfigOpen ? '收起运行配置' : '研究运行配置'}<ChevronDown size={13}/></button><button className="primary research-start-trigger" disabled={!query.trim() || !runtime.worker_online} title={!runtime.worker_online ? '研究 Worker 未在线' : '按当前模式和配置直接启动研究'} onClick={() => setStartRequestId(value => value + 1)}><Play size={14}/>启动研究</button></div></footer>
        <div className="research-query-inline-config-shell" hidden={!runConfigOpen} aria-hidden={!runConfigOpen}>
          <textarea id="research-query-supplement" className="research-query-supplement" value={supplement} onChange={event => setSupplement(event.target.value)} placeholder="可选：补充作战场景、时间范围、约束、前提假设或希望覆盖的技术/装备类型。" maxLength={8000}/>
          {renderInlineBuilder(activeQuery, executionProfileId, setExecutionProfileId, startRequestId)}
        </div>
      </div>
      <div className="research-query-suggestions" onMouseEnter={() => setRecommendationPaused(true)} onMouseLeave={() => setRecommendationPaused(false)}>
        <div className="research-query-suggestion-heading"><span><small>问题库灵感推荐</small><em><i/>全库 {recommendations.length || 0} 条 · 自动轮播 · 点击即可带入研究</em></span><button className="suggestion-refresh" disabled={recommendationLoading} onClick={refreshRecommendations}><RefreshCw className={recommendationLoading ? 'spin' : ''} size={12}/>{recommendationLoading ? '读取中' : '重新排序'}</button></div>
        {recommendations.length > 0 && <div className="recommendation-carousel">
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
    <ManualQueryPicker open={manualPickerOpen} close={() => setManualPickerOpen(false)} choose={item => { setSelectedRecommendation(item); setQuery(item.query); setSupplement(item.supplemental_information || ''); setManualPickerOpen(false); void refreshRecommendations(); }}/>
  </section>;
}

function ManualQueryPicker({open, close, choose}) {
  const [tab, setTab] = useState('library');
  const [queryCategory, setQueryCategory] = useState('all');
  const [queries, setQueries] = useState([]);
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');
  const [summary, setSummary] = useState(null);
  const [file, setFile] = useState(null);
  const [longText, setLongText] = useState('');
  const [sourceName, setSourceName] = useState('市场需求深度挖掘长 Query');
  const loadQueries = async preferredId => {
    setLoading(true); setError('');
    const first = await requestResult('/query-library/queries?status=published&limit=200&offset=0');
    if (!first.ok) { setLoading(false); setError(first.detail || 'Query 库读取失败'); return; }
    const total = Number(first.data.total || 0);
    const offsets = Array.from({length: Math.max(0, Math.ceil(total / 200) - 1)}, (_, index) => (index + 1) * 200);
    const pages = await Promise.all(offsets.map(offset => requestResult(`/query-library/queries?status=published&limit=200&offset=${offset}`)));
    const rows = [first.data, ...pages.filter(item => item.ok).map(item => item.data)].flatMap(page => page.items || []);
    setQueries(rows);
    if (preferredId || (!selectedId && rows.length)) setSelectedId(preferredId || rows[0].query_id);
    setLoading(false);
  };
  useEffect(() => { if (open) void loadQueries(); }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = event => { if (event.key === 'Escape') close(); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, close]);
  if (!open) return null;
  const isLongQuery = item => String(item.generation_rationale || '').includes('长 Query');
  const longQueryCount = queries.filter(isLongQuery).length;
  const standardQueryCount = queries.length - longQueryCount;
  const categoryQueries = queryCategory === 'long' ? queries.filter(isLongQuery) : queryCategory === 'standard' ? queries.filter(item => !isLongQuery(item)) : queries;
  const keyword = search.trim().toLowerCase();
  const visible = keyword ? categoryQueries.filter(item => `${item.query} ${item.supplemental_information || ''} ${item.generation_rationale || ''}`.toLowerCase().includes(keyword)) : categoryQueries;
  const selected = queries.find(item => item.query_id === selectedId);
  const finishImport = async (result, targetCategory = 'all') => {
    setImporting(false);
    if (!result.ok) { setError(result.detail || '导入失败'); return; }
    setSummary(result.data);
    setTab('library');
    setQueryCategory(targetCategory);
    await loadQueries(result.data.items?.[0]?.query_id || '');
  };
  const importFile = async () => {
    if (!file) { setError('请先选择 .xlsx 或 .csv 文件。'); return; }
    setImporting(true); setError(''); setSummary(null);
    try {
      const contentBase64 = await fileToBase64(file);
      await finishImport(await requestResult('/query-library/imports/file', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({filename:file.name, content_base64:contentBase64, status:'published'})}));
    } catch (reason) { setImporting(false); setError(reason.message || '文件读取失败'); }
  };
  const importText = async () => {
    if (!longText.trim()) { setError('请粘贴编号 Query 列表。'); return; }
    setImporting(true); setError(''); setSummary(null);
    await finishImport(await requestResult('/query-library/imports/text', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content:longText, source_name:sourceName.trim() || '人工导入长 Query', status:'published'})}), 'long');
  };
  return <div className="manual-query-modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <section className="manual-query-modal" role="dialog" aria-modal="true" aria-label="人工选取或导入 Query">
      <header><div><Database size={20}/><span><b>人工选取 Query</b><small>从统一 Query Library 选取，或导入 Excel、CSV 与长问题列表</small></span></div><button className="icon-button" onClick={close} aria-label="关闭"><X size={18}/></button></header>
      <nav><button className={tab === 'library' ? 'active' : ''} onClick={() => setTab('library')}><BookOpenCheck size={15}/>选取 Query</button><button className={tab === 'file' ? 'active' : ''} onClick={() => setTab('file')}><FileSpreadsheet size={15}/>导入表格</button><button className={tab === 'text' ? 'active' : ''} onClick={() => setTab('text')}><Pencil size={15}/>导入长 Query</button></nav>
      {summary && <div className="manual-query-import-summary"><CheckCircle2 size={16}/><span><b>导入完成：新增 {summary.imported_count || 0} 条 · 发布已有草稿 {summary.promoted_count || 0} 条</b><small>跳过已发布重复项 {summary.skipped_count || 0} 条 · 无效 {summary.invalid_count || 0} 条</small></span></div>}
      {error && <p className="manual-query-error"><CircleAlert size={15}/>{error}</p>}
      {tab === 'library' && <div className="manual-query-library-pane"><div className="manual-query-category-filter"><button className={queryCategory === 'all' ? 'active' : ''} onClick={() => setQueryCategory('all')}>全部 <em>{queries.length}</em></button><button className={queryCategory === 'standard' ? 'active' : ''} onClick={() => setQueryCategory('standard')}>常规 Query <em>{standardQueryCount}</em></button><button className={queryCategory === 'long' ? 'active' : ''} onClick={() => setQueryCategory('long')}>长 Query <em>{longQueryCount}</em></button></div><label><Search size={16}/><input autoFocus value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索研究方向、场景、技术或制胜机理"/><em>{visible.length} / {categoryQueries.length}</em></label>{loading ? <div className="manual-query-loading"><RefreshCw className="spin" size={16}/>正在读取 Query Library…</div> : <div className="manual-query-select-list">{visible.length ? visible.map(item => <button className={`${selectedId === item.query_id ? 'selected' : ''} ${isLongQuery(item) ? 'long-query' : ''}`} key={item.query_id} onClick={() => setSelectedId(item.query_id)}><span><em>{isLongQuery(item) ? '长 Query' : item.source_type === 'import' ? '资料导入' : item.source_type === 'agent' ? 'AI 生成' : '人工录入'}</em><small>v{item.version}</small></span><b>{item.query}</b><p>{item.supplemental_information || item.generation_rationale || '无补充说明'}</p>{selectedId === item.query_id && <CheckCircle2 size={17}/>}</button>) : <div className="manual-query-loading">没有匹配的 Query</div>}</div>}</div>}
      {tab === 'file' && <div className="manual-query-import-pane"><div className="manual-query-import-guide"><Upload size={25}/><span><b>导入 Query 列表</b><small>支持 .xlsx / .csv；自动识别“研究方向、核心研究重点、一级领域、重点层级”等列，导入后立即发布到统一问题库。</small></span></div><label className="manual-query-file"><input type="file" accept=".xlsx,.csv" onChange={event => setFile(event.target.files?.[0] || null)}/><span>{file ? file.name : '选择 Excel 或 CSV 文件'}</span></label><button className="primary" disabled={!file || importing} onClick={importFile}>{importing ? '正在导入…' : '导入并加入 Query Library'}</button></div>}
      {tab === 'text' && <div className="manual-query-import-pane long-text"><label><span>来源名称</span><input value={sourceName} maxLength={300} onChange={event => setSourceName(event.target.value)} placeholder="例如：市场需求深度挖掘分类提问"/></label><label><span>编号 Query 列表</span><textarea value={longText} maxLength={100000} onChange={event => setLongText(event.target.value)} placeholder={'1、深度研究……\n2、【需求扫描】面向未来5—15年……\n\n四、分类提问\n1、【局部战争启示】深度研究……'}/><small>按“1、/ 2、”自动拆分；“四、……”等章节标题不会被误导入。每条 Query 最长 4000 字，保留完整原文。</small></label><button className="primary" disabled={!longText.trim() || importing} onClick={importText}>{importing ? '正在解析并导入…' : '解析并导入长 Query'}</button></div>}
      <footer><span>{selected ? `已选择：${selected.query}` : '请选择一条 Query'}</span><div><button onClick={close}>取消</button><button className="primary" disabled={!selected || tab !== 'library'} onClick={() => choose(selected)}>带入研究问题</button></div></footer>
    </section>
  </div>;
}

function ResearchModePicker({profiles, value, onChange}) {
  const fallbackProfiles = [
    {id:'legacy_v1', name:'传统固定编排', short_name:'传统模式', description:'固定流程执行，适合兼容回滚与对照。', default:false, badge:'兼容'},
    {id:'optimized_v2', name:'协同优化编排', short_name:'协同模式', description:'3–4 个业务 Agent 并行，并进入 S1–S6 Cohort。', recommended:true, badge:'推荐'},
    {id:'swarm_quality_v1', name:'质量残差蜂群', short_name:'质量集群', description:'按质量残差弹性孵化，最多 12 个 Agent。', evaluation_only:true, badge:'高质量'},
    {id:'winning_swarm_dynamic_v2', name:'Mission Graph 动态蜂群', short_name:'动态蜂群', description:'8–16 个实例动态孵化，提供最高并发能力。', default:true, evaluation_only:true, badge:'最高并发'},
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
  const transitionText = runtime.capacity_transition === 'scaling_up' ? `正在扩容到 ${runtime.configured_worker_capacity} 个槽位` : runtime.capacity_transition === 'scaling_down' ? `运行中任务结束后缩容到 ${runtime.configured_worker_capacity} 个槽位` : '';
  return <section className="parallel-runtime" aria-label="研究任务并行执行状态">
    <header><div><Activity size={17}/><span><b>{runtime.parallel_enabled ? '多任务并行执行已启用' : '单任务执行模式'}</b><small>每个槽位使用独立 Runner、Provider 预算、输出目录与异常生命周期</small></span></div><div className="parallel-runtime-actions"><em>{runtime.available_slots || 0} 个可用槽位</em><button onClick={() => { setEditing(value => !value); setError(''); }}><Wrench size={13}/>设置槽位</button></div></header>
    {editing && <div className="slot-capacity-editor"><span><b>研究 Worker 槽位</b><small>可创建 1–{capacityLimit} 个真实执行槽位；缩容不会中断正在运行的任务。</small></span><div><button aria-label="减少槽位" disabled={desired <= 1 || saving} onClick={() => setDesired(value => Math.max(1, value - 1))}>−</button><strong>{desired}</strong><button aria-label="增加槽位" disabled={desired >= capacityLimit || saving} onClick={() => setDesired(value => Math.min(capacityLimit, value + 1))}>＋</button><button className="primary" disabled={saving || desired === runtime.configured_worker_capacity} onClick={applyCapacity}>{saving ? '应用中' : '应用'}</button></div>{error && <p>{error}</p>}</div>}
    {transitionText && <div className="slot-capacity-transition"><RefreshCw className="spin" size={13}/>{transitionText}</div>}
    <div className="parallel-worker-grid">{workers.map(worker => { const run = runById.get(worker.current_run_id); const busy = worker.status === 'working' && worker.current_run_id; return <article className={busy ? 'busy' : 'idle'} key={worker.worker_id}><span>槽位 #{worker.slot_index || '?'}</span><b>{busy ? run?.topic || worker.current_run_id : '等待研究任务'}</b><small>{busy ? worker.current_run_id : worker.worker_id}</small></article>; })}</div>
    {runtime.pending_count > 0 && <footer><Clock3 size={14}/>当前有 {runtime.pending_count} 个任务排队；任一槽位释放后按创建顺序自动执行。</footer>}
  </section>;
}

function CreateRun({catalog, done, runtime, initialQuery, openQueryLibrary, inline = false, executionProfileId: controlledExecutionProfileId = '', onExecutionProfileChange, startRequestId = 0}) {
  const workerOnline = runtime.worker_online;
  const [topic, setTopic] = useState(initialQuery?.query || ''); const [supplementalInformation, setSupplementalInformation] = useState(initialQuery?.supplemental_information || ''); const [route, setRoute] = useState('auto'); const [interactionMode, setInteractionMode] = useState('expert'); const [branch, setBranch] = useState('auto'); const [localExecutionProfileId, setLocalExecutionProfileId] = useState(DEFAULT_EXECUTION_PROFILE_ID); const [reportTemplateMode, setReportTemplateMode] = useState('project_argument_v1'); const [agents, setAgents] = useState([]); const [rounds, setRounds] = useState(2); const [submitting, setSubmitting] = useState(false); const [error, setError] = useState(''); const [agentPreview, setAgentPreview] = useState(null);
  const executionProfileId = controlledExecutionProfileId || localExecutionProfileId;
  const setExecutionProfileId = value => { setLocalExecutionProfileId(value); onExecutionProfileChange?.(value); };
  const [libraryQueries, setLibraryQueries] = useState([]); const [librarySearch, setLibrarySearch] = useState(''); const [libraryLoading, setLibraryLoading] = useState(true); const [selectedQueryId, setSelectedQueryId] = useState(initialQuery?.query_id || ''); const [libraryError, setLibraryError] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
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
    const keyword = librarySearch.trim().toLowerCase();
    if (!keyword) return libraryQueries;
    return libraryQueries.filter(item => `${item.query} ${item.generation_rationale || ''} ${item.supplemental_information || ''}`.toLowerCase().includes(keyword));
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
    if (submitting) return;
    if (startImmediately && !workerOnline) { setError('研究 Worker 未在线，已阻止任务进入无人消费的队列；你仍可先保存为草稿。'); return; }
    if (startImmediately && catalog.provider.default_mode === 'real' && catalog.provider.codex_available === false) { setError('后端未检测到 Agent 运行组件；可先保存草稿，配置运行环境后再启动。'); return; }
    const analystConfirmed = startImmediately ? window.confirm('请确认：研究主题、边界和关键假设已经分析师审核，可进入正式五判据审计。\n\n选择“取消”仍会运行，但报告将标记为待审稿。') : false;
    setSubmitting(true); setError('');
    const created = await request('/runs', null, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({topic, supplemental_information: supplementalInformation, research_route: route, interaction_mode: interactionMode, discovery_branch: branch, execution_profile_id: executionProfileId, report_template_mode: reportTemplateMode, selected_agent_ids: effectiveAgentIds, max_rounds: rounds, analyst_confirmed: analystConfirmed, source_query_id: selectedLibraryQuery?.query_id || '', source_query_version: selectedLibraryQuery?.version || null})});
    if (!created) { setSubmitting(false); setError('任务创建失败。请检查配置和 API 服务。'); return; }
    if (!startImmediately) { setSubmitting(false); done(created, false); return; }
    const started = await requestResult(`/runs/${created.run_id}/start`, {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID(), 'X-Role': 'analyst'}});
    setSubmitting(false);
    if (started.ok) done(started.data, true); else setError(`任务已保存为草稿，但启动失败：${started.detail || '请检查 Agent、API Key 和 Worker 环境。'}`);
  };
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
    <div className="create-actions"><span>{runtime.available_slots > 0 ? `当前有 ${runtime.available_slots} 个并行槽位可立即执行。` : `当前槽位已满，启动后将进入队列（前方 ${runtime.pending_count || 0} 项）。`}</span><div className="create-buttons"><button disabled={disabled} onClick={() => submit(false)}><Save size={15}/>保存草稿</button>{!inline && <button className="primary" disabled={startDisabled} onClick={() => submit(true)}>{submitting ? '正在处理' : '创建并启动研究'}<ChevronDown size={16}/></button>}</div></div>
    {error && <p className="form-error"><CircleAlert size={15}/>{error}</p>}
  </section>;
}

function WorkspacePage({view, run, runs, catalog, runtime, selectRun}) {
  const [payload, setPayload] = useState(null); const [loading, setLoading] = useState(false);
  const [taskQuery, setTaskQuery] = useState(''); const [taskStatus, setTaskStatus] = useState('all');
  const [resumingReport, setResumingReport] = useState(false); const [reportResumeError, setReportResumeError] = useState('');
  const live = useLiveInteractions(run, view === 'interactions' || view === 'reports');
  useEffect(() => { setTaskQuery(''); setTaskStatus('all'); }, [view]);
  useEffect(() => { setResumingReport(false); setReportResumeError(''); }, [run?.run_id]);
  useEffect(() => { let cancelled = false; setPayload(null); if (view === 'interactions') return undefined; if (!run) return undefined; const routes = {evidence: '/domain/EvidenceCard', winning: '/winning-mechanism', capabilities: '/capabilities', reports: '/report'}; setLoading(true); const load = view === 'capabilities' ? Promise.all([request(`/runs/${run.run_id}/capabilities`, null, {headers: {'X-Role': 'analyst'}}), request(`/runs/${run.run_id}/interactions?compact=true`, null, {headers: {'X-Role': 'analyst'}})]).then(([rows, interactions]) => ({rows: Array.isArray(rows) ? rows : [], referenceWeapons: (interactions?.workflow?.swarm_cluster?.candidate_lineage || []).filter(candidate => candidate.s6_eligible !== true)})) : request(`/runs/${run.run_id}${routes[view]}`, null, {headers: {'X-Role': view === 'reports' ? 'reviewer' : 'analyst'}}); load.then(value => { if (!cancelled) setPayload(value); }).finally(() => { if (!cancelled) setLoading(false); }); return () => { cancelled = true; }; }, [view, run?.run_id, run?.status]);
  const item = nav.find(row => row[0] === view); const current = view === 'interactions' ? live.data : payload; const busy = view === 'interactions' ? live.loading : view === 'reports' ? loading || (live.loading && !live.data) : loading;
  const hasTaskNavigator = ['interactions', 'evidence', 'winning', 'capabilities', 'reports'].includes(view); const availableRuns = (runs || []).filter(itemRun => itemRun.status !== 'archived'); const visibleRuns = availableRuns.filter(itemRun => (!taskQuery.trim() || `${itemRun.topic} ${itemRun.supplemental_information || ''} ${itemRun.run_id}`.toLowerCase().includes(taskQuery.trim().toLowerCase())) && (taskStatus === 'all' || taskStatus === 'active' && isRunActive(itemRun, runtime) || taskStatus === itemRun.status)); const contextLabel = {interactions:'当前交互任务',evidence:'当前证据任务',winning:'当前 S1–S6 任务',capabilities:'当前能力画像任务',reports:'当前评审任务'}[view] || '当前研究任务';
  const reportPhase = (live.data?.workflow?.phases || []).find(phase => phase.id === 'report');
  const reportPhaseStatus = reportPhase?.status || latestReporterPhaseStatus(live.data?.events || [], run?.status === 'completed', run?.status === 'failed');
  const reportFailureEvent = [...(live.data?.events || [])].reverse().find(event => event.event_type === 'report_model_failed');
  const reportFailureDetail = reportPhase?.error || reportFailureEvent?.details?.detail || run?.error || '';
  const resumeReport = async () => { if (!run || run.status !== 'failed') return; setResumingReport(true); setReportResumeError(''); const result = await requestResult(`/runs/${run.run_id}/resume`, {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID(), 'X-Role': 'analyst'}}); setResumingReport(false); if (result.ok) { setPayload(null); selectRun(result.data); } else setReportResumeError(result.detail || '断点恢复失败，请检查 Worker 与模型配置。'); };
  const content = !run ? <Empty text="请从左侧选择研究任务"/> : busy && current == null ? <Empty text="正在读取任务产物"/> : view === 'reports' && reportPhaseStatus === 'failed' ? <ReportFailureView run={run} detail={reportFailureDetail} resuming={resumingReport} resume={resumeReport} error={reportResumeError}/> : current == null ? <Empty text={run.status === 'completed' ? '产物读取失败，请刷新后重试' : '任务完成后可查看本页'}/> : view === 'interactions' ? <InteractionView data={current} live={live.connected && !['completed', 'failed', 'cancelled', 'archived'].includes(run.status)} completed={run.status === 'completed'}/> : view === 'reports' ? <ReportView text={current} run={run}/> : view === 'winning' ? <WinningMechanismView data={current}/> : <ObjectGrid view={view} rows={current}/>;
  return <><PageTitle eyebrow={hasTaskNavigator ? '交互中心' : '研究运行产物'} title={view === 'reports' ? '报告评审' : item?.[1]} subtitle={hasTaskNavigator ? '直接选择研究任务，连续查看交互、证据、S Agent、能力画像和报告产物。' : run ? `当前任务：${run.topic}` : '请在研究任务列表中选择一项运行。'}/>{hasTaskNavigator ? <div className="task-review-workspace"><section className="task-review-rail"><header><div><ListFilter size={17}/><span><b>研究任务</b><small>{visibleRuns.length} / {availableRuns.length}</small></span></div></header><div className="task-review-filters"><div className="searchbox"><Search size={15}/><input value={taskQuery} onChange={event => setTaskQuery(event.target.value)} placeholder="搜索任务或运行 ID"/></div><select value={taskStatus} onChange={event => setTaskStatus(event.target.value)}><option value="all">全部状态</option><option value="active">进行中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="draft">草稿</option></select></div><div className="task-review-list">{visibleRuns.length ? visibleRuns.map(itemRun => <button className={run?.run_id === itemRun.run_id ? 'selected' : ''} key={itemRun.run_id} onClick={() => selectRun(itemRun)}><span><b>{itemRun.topic}</b><small>{itemRun.run_id}</small></span><div><Status value={itemRun.status}/><em>{routeLabel(itemRun.research_route)}</em></div></button>) : <Empty text="没有匹配的研究任务"/>}</div></section><section className={`task-review-content ${view}`}>{run && <header className="task-review-context"><div><span>{contextLabel}</span><b>{run.topic}</b><small>{run.run_id} · {routeLabel(run.research_route)} · {statusLabel(run.status)}</small></div><Status value={run.status}/></header>}{content}</section></div> : content}</>;
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
  useEffect(() => {
    if (!enabled || !run) { setConnected(false); setData(null); return undefined; }
    let cancelled = false; let refreshTimer = null; setData(null); setLoading(true);
    const refresh = () => request(`/runs/${run.run_id}/interactions?compact=true`, null, {headers: {'X-Role': 'analyst'}}).then(value => { if (!cancelled && value) setData(value); }).finally(() => { if (!cancelled) setLoading(false); });
    const scheduleRefresh = () => { if (refreshTimer) clearTimeout(refreshTimer); refreshTimer = setTimeout(() => void refresh(), 120); };
    void refresh();
    if (['completed', 'failed', 'cancelled', 'archived'].includes(run.status)) return () => { cancelled = true; if (refreshTimer) clearTimeout(refreshTimer); };
    const source = new EventSource(`${api}/runs/${run.run_id}/events`);
    source.onopen = () => { if (!cancelled) setConnected(true); };
    source.onerror = () => { if (!cancelled) setConnected(false); };
    const eventTypes = ['run_created', 'run_status_changed', 'run_recovered', 'run_started', 'discovery_meta_loop_evaluated', 'baseline_pipeline_started', 'baseline_discovery_started', 'baseline_discovery_lane_started', 'baseline_discovery_lane_completed', 'baseline_discovery_completed', 'baseline_model_queue_started', 'baseline_model_call_started', 'baseline_model_call_progress', 'baseline_model_call_completed', 'baseline_analysis_started', 'baseline_analysis_completed', 'baseline_materialization_progress', 'baseline_wave_started', 'baseline_wave_completed', 'agent_task_delegated', 'agent_harness_completed', 'task_received', 'tool_call', 'tool_result', 'evidence_assessed', 'baseline_result', 'savepoint', 'baseline_agent_completed', 'baseline_agents_summarized', 'packet_admission_evaluated', 'packet_admission_reused', 'discovery_convergence_completed', 'discovery_convergence_reused', 'winning_input_prepared', 'winning_resources_projected', 'winning_model_result_reused', 'winning_model_queue_started', 'winning_model_call_started', 'winning_model_call_progress', 'winning_model_call_completed', 'swarm_planned', 'specialist_recruitment_planned', 'specialist_spawned', 'specialist_session_started', 'specialist_session_completed', 'specialist_completed', 'specialist_pruned', 'winning_mission_graph_planned', 'winning_agent_instance_recruited', 'winning_agent_instance_ready', 'winning_agent_session_started', 'winning_agent_session_completed', 'winning_agent_instance_failed', 'winning_agent_instance_cancelled', 'winning_candidate_branch_created', 'winning_candidate_ledger_frozen', 'winning_contribution_queued', 'winning_contribution_rejected', 'winning_contribution_rebase_required', 'winning_contribution_merged', 'winning_portfolio_merge_completed', 'hypothesis_created', 'hypothesis_merged', 'hypothesis_rejected', 'swarm_gate_evaluated', 'promotion_candidate_created', 'winning_subagent_completed', 'winning_inner_loop_evaluated', 'winning_middle_loop_evaluated', 'winning_outer_loop_evaluated', 'winning_reasoning_step_completed', 'winning_stage_completed', 'recall_requested', 'recall_task_completed', 'coverage_recomputed_after_recall', 'winning_stage_gate_reevaluated', 'capability_image_created', 'audit_model_fallback', 'audit_completed', 'report_model_queue_started', 'report_model_call_started', 'report_model_call_progress', 'report_model_call_completed', 'report_model_fallback', 'report_model_failed', 'report_completed', 'run_result_saved', 'run_failed'];
    eventTypes.forEach(type => source.addEventListener(type, scheduleRefresh));
    return () => { cancelled = true; source.close(); if (refreshTimer) clearTimeout(refreshTimer); setConnected(false); };
  }, [enabled, run?.run_id, run?.status]);
  return {data, loading, connected};
}

function InteractionView({data, live, completed}) {
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
  return <><div className={`live-state ${live ? 'connected' : ''}`}><i/>{live ? '实时接收关键流程' : '关键流程审计回放'}</div><section className="metric-strip interaction-metrics"><Metric label="全部事件" value={data.counts?.events || 0} icon={Activity}/><Metric label="关键事件" value={data.counts?.visible_events ?? events.length} icon={Layers3}/><Metric label="业务 Agent" value={activeBusinessAgents.length} icon={Bot}/><Metric label="保存点" value={data.counts?.savepoints || 0} icon={ClipboardCheck}/></section><WorkflowOverview events={events} workflow={workflow} agents={agents} live={live} completed={completed}/><DynamicSwarmInteractionPanel cluster={cluster} members={swarmMembers} live={live}/><section className="agent-map compact-agent-map"><div className="section-heading"><div><b>本次参与的业务 Agent</b><span>由主控 Agent 结合 A–H 分支路径与当前输入选择；分支自动加入的案例、技术、跨域与非传统安全专项 Agent 也在此显示。</span></div></div><div className="agent-chip-grid">{activeBusinessAgents.map(agent => { const plan = baselinePlanMap[agent.agent_id] || {}; return <article className="agent-chip" key={agent.agent_id}><Bot size={16}/><div><b>{agent.display_name}{plan.mode && <em className={`agent-plan-mode ${plan.mode}`}>{baselineAgentModeLabel(plan.mode)}</em>}</b><small>{agent.harness_profile || '受控运行'}</small><span>{(agent.skill_ids || []).slice(0, 2).join(' · ') || '专业分析'}</span></div></article>; })}</div>{activeBusinessAgents.length === 0 && <small className="agent-overflow">主控 Agent 正在按分支路径判断本次需要的业务 Agent。</small>}</section><section className="event-filter compact-filter"><span>关键事件</span><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部 Agent</option>{filterAgents.map(agent => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}</select><em>显示 {visible.length} / {data.counts?.events || events.length}</em></section><section className="event-timeline compact-timeline">{visible.map((event, index) => <InteractionEvent key={`${event.event_id}-${index}`} event={event} agent={map[event.actor]}/>)}</section></>;
}

function DynamicSwarmInteractionPanel({cluster, members, live}) {
  if (!cluster?.enabled && !members?.length) return null;
  const rows = members || [];
  const counts = cluster.counts || {};
  const graph = cluster.mission_graph || {};
  const rolePools = cluster.role_pools || ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'].map(mission_node => ({mission_node, count: rows.filter(item => item.mission_node === mission_node).length}));
  const specialists = cluster.dynamic_specialists || rows.filter(item => item.recruitment_planned);
  const candidates = cluster.candidate_lineage || [];
  const ledger = cluster.hypothesis_ledger || {};
  const receipts = cluster.merge_receipts || [];
  const portfolio = cluster.final_equipment_portfolio || cluster.portfolio_decision?.final_equipment_portfolio || [];
  const portfolioGate = cluster.portfolio_decision?.quality_gate || {};
  const waves = [1, 2, 3].map(wave => ({wave, label: {1: '广度探索', 2: '定向挑战', 3: '收敛决策'}[wave], members: rows.filter(item => Number(item.wave || 0) === wave)}));
  const completed = Number(counts.completed || 0) + Number(counts.merged || 0);
  const memberPurpose = member => member.role_purpose || '围绕当前质量残差执行定向补强。';
  return <section className="dynamic-swarm-panel">
    <header><div><Layers3 size={18}/><span><b>动态制胜 Agent 集群</b><small>S1–S6 为种子角色池，依赖满足即并行启动；质量残差可招聘额外 Codex CLI 专用 Agent，贡献只合并到声明候选。</small></span></div><em className={live && Number(counts.running || 0) > 0 ? 'live' : ''}>{live && Number(counts.running || 0) > 0 ? '实时调度' : '可审计回放'}</em></header>
    <div className="dynamic-swarm-counts"><span><small>实例总数</small><b>{counts.total ?? rows.length}</b></span><span><small>创建/执行中</small><b>{Number(counts.recruiting || 0) + Number(counts.running || 0)}</b></span><span><small>完成</small><b>{completed}</b></span><span><small>账本版本</small><b>v{ledger.version || 0}</b></span><span><small>最终装备方向</small><b>{portfolio.length}</b></span></div>
    <div className="swarm-role-pools">{rolePools.map(pool => <div key={pool.mission_node}><b>{pool.mission_node}<i>×{pool.count || 0}</i></b><span>{swarmNodeLabel(pool.mission_node)}</span></div>)}<div className="specialists"><b>专用<i>×{specialists.length}</i></b><span>残差触发招聘</span></div></div>
    {graph.graph_id && <div className="swarm-graph-contract"><span>Mission Graph <code>{graph.graph_id}</code></span><span>并发上限 <b>{graph.maximum_concurrency || 6}</b></span><span>实例边界 <b>{graph.minimum_instances || 8}–{graph.maximum_instances || 16}</b></span><span>{graph.merge_strategy || '版本化账本 Merge'}</span></div>}
    <div className="dynamic-swarm-waves">{waves.map(wave => <section key={wave.wave} className={`dynamic-swarm-wave wave-${wave.wave}`}><header><i>W{wave.wave}</i><span><b>{wave.label}</b><small>{wave.members.length} 个实例</small></span></header><div>{wave.members.length ? wave.members.map((member, index) => <article className={`dynamic-swarm-member status-${member.status || 'planned'}`} key={member.agent_instance_id || member.agent_id || `${wave.wave}-${index}`}><header><i>{member.mission_node || index + 1}</i><div><b>{member.display_name || '动态专用 Agent'}</b><small>{member.archetype || member.runtime_profile_id || '按需角色'}</small></div><span className={`swarm-member-status ${member.status || 'planned'}`}>{swarmMemberStatusLabel(member)}</span></header><details className="dynamic-swarm-purpose"><summary><span>{memberPurpose(member)}</span><em>展开职责</em></summary><p>{memberPurpose(member)}</p></details><div className="dynamic-swarm-routing"><span>候选 <code>{shortIdentifier(member.hypothesis_id || '广度新建')}</code></span><span>Merge <b>{member.merge_target || '未声明'}</b></span></div>{member.depends_on?.length > 0 && <div className="swarm-dependencies"><small>依赖</small>{member.depends_on.slice(0, 3).map(item => <code key={item}>{shortIdentifier(item)}</code>)}</div>}{member.trigger_residuals?.length > 0 && <div className="dynamic-swarm-residuals">{member.trigger_residuals.slice(0, 3).map(item => <span key={item}>{item}</span>)}</div>}{member.prune_reason && <div className="dynamic-swarm-decision rejected"><CircleAlert size={13}/><span>回收原因：{agentFacingText(member.prune_reason)}</span></div>}{member.portfolio_status === 'selected' && <div className="dynamic-swarm-decision accepted"><CheckCircle2 size={13}/><span>贡献已纳入独立装备卡</span></div>}{member.portfolio_status === 'rejected' && <div className="dynamic-swarm-decision not-selected"><CheckCircle2 size={13}/><span>执行结论已沉淀为候选约束或变体，不重复单列装备卡</span></div>}{member.status === 'merged' && !member.portfolio_status && <div className="dynamic-swarm-decision accepted"><CheckCircle2 size={13}/><span>贡献已定向合并</span></div>}<details className="dynamic-swarm-technical"><summary>角色合同与独立会话</summary><dl><dt>脱敏会话引用</dt><dd><code>{member.session_ref || member.agent_instance_id || '待启动'}</code></dd><dt>执行后端</dt><dd>{member.execution_backend === 'independent_codex_cli' ? '独立 Codex CLI' : member.execution_backend || member.provider_type || '受控模型会话'}</dd><dt>上下文隔离</dt><dd>{member.context_isolation || 'ephemeral'}</dd><dt>Skill</dt><dd>{(member.skill_ids || []).join(' · ') || '受治理共享 Skill'}</dd><dt>递归招聘</dt><dd>{member.allow_child_spawn === true ? '允许' : '禁止'}</dd></dl></details></article>) : <div className="dynamic-swarm-empty"><RefreshCw size={14}/><span>等待依赖满足或质量残差触发</span></div>}</div></section>)}</div>
    {candidates.length > 0 && <section className="swarm-candidate-board"><header><div><b>候选军事装备</b><small>入选装备须通过单项质量门、对象证据与直接作战属性审查，并按独立性和组合价值进入 S6；其余作为可展开查看的参考武器保留</small></div><em>{candidates.length} 条</em></header><div>{candidates.map(candidate => { const status = candidate.selection_status || candidate.status || 'created'; const isReference = !candidate.s6_eligible && ['reference', 'rejected', 'contribution_rejected'].includes(status); const weaponName = weaponCandidateTitle(candidate); return <article key={candidate.hypothesis_id} className={`candidate-${isReference ? 'reference' : status}`}><header><b title={weaponName || candidate.hypothesis_id}>{weaponName || shortIdentifier(candidate.hypothesis_id)}</b><span>{swarmCandidateStatusLabel(status)}</span></header><div className="candidate-score" title="组合评分：综合质量、证据覆盖、新颖性、反适应稳健性与工程可行性；不是命中概率或武器效能百分比"><i style={{width: `${Math.max(0, Math.min(100, Number(candidate.score || 0) * 100))}%`}}/><em>{Math.round(Number(candidate.score || 0) * 100)}</em></div><p>{weaponCandidateForm(candidate) || '候选装备形态待复核'}</p>{candidate.s6_eligible && <small className="candidate-selection-reason">入选依据：{agentFacingText(candidate.selection_reason || '通过单项质量门，并在证据、独立性、直接作战属性与组合价值排序中进入本轮容量。')}</small>}<details className="candidate-reference-overview"><summary>{candidate.s6_eligible ? '查看候选概述' : '查看参考概述'}</summary><p>{swarmCandidateOverview(candidate)}</p>{candidate.related_hypothesis_ids?.length > 0 && <small>关联候选：{candidate.related_hypothesis_ids.map(shortIdentifier).join(' · ')}</small>}</details><footer><span>Merge {(candidate.merge_targets || []).join('/') || '待贡献'}</span><span>对象证据 {(candidate.evidence_ids || []).length}</span><span>{candidate.s6_eligible ? 'S6并行详细画像' : '参考武器'}</span></footer></article>; })}</div></section>}
    {receipts.length > 0 && <details className="swarm-merge-receipts"><summary>Merge Receipt 与版本重基（{receipts.length}）</summary><div>{receipts.slice(-12).map(receipt => <div key={receipt.receipt_id}><code>{shortIdentifier(receipt.contribution_id)}</code><span>{shortIdentifier(receipt.hypothesis_id)} → {receipt.merge_target}</span><b className={receipt.status}>{receipt.rebase_required ? '需重基' : receipt.status}</b><em>v{receipt.base_ledger_version ?? '?'}→v{receipt.resulting_ledger_version ?? '?'}</em></div>)}</div></details>}
    {portfolio.length > 0 && <section className="swarm-equipment-portfolio"><header><div><b>最终前瞻军事装备组合</b><small>通过证据、因果、装备具体性、失效边界与独立组合评审</small></div><em>{portfolio.length} 条{portfolioGate.direct_combat_equipment_count != null ? ` · 直接战斗装备 ${portfolioGate.direct_combat_equipment_count}` : ''}{portfolioGate.passed === false ? ' · 硬门未通过' : ''}</em></header><div>{portfolio.map((item, index) => <article key={item.hypothesis_id || `${item.name}-${index}`}><i>{index + 1}</i><div><b>{item.name || '前瞻装备方向'}</b><small>{(item.equipment_forms || []).join(' · ') || item.type || '具体装备形态'}</small><p>{(item.mission_effects || []).slice(0, 2).join('；') || '直接军事效果待展示'}</p><footer><span>{item.type || 'new'}</span><span>{item.direct_combat_equipment ? '直接战斗装备' : '体系补链'}</span><span>验证 {(item.validation_plan || []).length}</span><span>边界 {(item.failure_boundaries || []).length}</span></footer></div></article>)}</div></section>}
  </section>;
}

function swarmMemberStatusLabel(member = {}) {
  const status = String(member.status || 'planned');
  if (member.portfolio_status === 'selected' || member.merge_status === 'accepted') return '贡献已纳入';
  if (member.portfolio_status === 'rejected') return '贡献已沉淀';
  return {planned:'待调度',recruiting:'会话创建中',queued:'等待执行',running:'执行中',completed:'执行完成',merged:'贡献已合并',pruned:'已回收',skipped:'已回收',failed:'执行失败'}[status] || '待调度';
}
function swarmCandidateStatusLabel(value) { return {created:'已创建',contribution_queued:'贡献排队',rebase_required:'版本重基',merged:'已合并',selected:'入选',merged_as_variant:'参考变体',not_selected_capacity:'参考武器',reference:'参考武器',rejected:'参考武器',contribution_rejected:'参考武器'}[value] || value || '演化中'; }
function cleanWeaponCandidateText(value) {
  return String(value || '').replace(/_/g, ' ')
    .replace(/^(?:(?:[A-H]\s*[-/]?\s*)?S[1-6](?:\s*[-/]?\s*(?:候选)?[A-Z一二三四五六\d]+)?|(?:竞争分支|候选)(?:[A-Z一二三四五六\d-]+)?|[A-H])\s*[：:—–/-]*\s*/i, '')
    .replace(/\bS[1-6]\b\s*[-_/：:]*/gi, '')
    .replace(/^(?:红队保留|红队|保留参考|参考武器)\s*[：:—–/-]*\s*/, '')
    .split(/\s*(?:·|\||；|;)\s*(?:主装备)?(?:装备)?(?:形态|接口形态|接口|任务接口)\s*[：:]/, 1)[0]
    .replace(/^(?:(?:主装备)?(?:装备)?形态|接口形态|接口|任务接口|(?:[Qq]uery)(?:相关|专属)?(?:型号|装备)?|相关型号)\s*[：:]\s*/, '')
    .trim();
}
function isConcreteWeaponCandidateText(value) {
  const text = String(value || '').trim();
  return /导弹|巡飞|弹药|毁伤弹|拦截弹|无人机|攻击无人机|无人攻击机|无人僚机|无人艇|无人潜航器|无人平台|效应器|火力舱|发射车|武器站|火炮|鱼雷|水雷|激光武器|微波武器/.test(text)
    && !/^(?:内置效应器|效应器|内置载荷|任务载荷|攻击载荷|火力|平台|弹药|弹群)$/.test(text)
    && !/^(?:内置效应器|内置载荷|任务载荷|攻击载荷)\s*[：:]/.test(text)
    && !/证据链|任务链|信息链|杀伤链|闭环|能力|体系|方向|红队保留|竞争分支|颠覆分支|候选|作战模式/.test(text);
}
function weaponCandidateTitle(candidate = {}) {
  const title = cleanWeaponCandidateText(candidate.title);
  const head = title.split(/[：:；;。]/, 1)[0].trim();
  if (isConcreteWeaponCandidateText(head)) return head;
  if (isConcreteWeaponCandidateText(title)) return title;
  const form = weaponCandidateForm(candidate, isConcreteWeaponCandidateText);
  return form || head || title || '待复核具体武器装备';
}
function weaponCandidateForm(candidate = {}, concreteCheck = null) {
  const concrete = concreteCheck || isConcreteWeaponCandidateText;
  const forms = Array.isArray(candidate.equipment_forms) ? candidate.equipment_forms : [];
  const normalized = forms.map(cleanWeaponCandidateText).filter(Boolean);
  return normalized.find(concrete)?.slice(0, 64) || normalized.slice(0, 2).join(' · ');
}
function swarmCandidateOverview(candidate = {}) { const parts = [candidate.novelty_delta, (candidate.mechanism_chain || []).slice(0, 3).join(' → '), (candidate.direct_military_effects || []).slice(0, 2).join('；')].map(value => String(value || '').trim()).filter(Boolean); return parts.join('；') || weaponCandidateForm(candidate) || '该候选作为参考武器保留，可结合后续对象证据与任务适配性继续复核。'; }
function swarmNodeLabel(value) { return {S1:'对手体系',S2:'竞争战法',S3:'颠覆机理',S4:'装备映射',S5:'基线审查',S6:'组合评审'}[value] || '专用角色'; }
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
  const dynamicCandidates = [...(Array.isArray(metaReview.dynamic_subagents) ? metaReview.dynamic_subagents : []), ...(workflow.dynamic_agents || [])];
  const dynamicAgents = [...new Map(dynamicCandidates.map((agent, index) => [`${agent.display_name || agent.name || agent.agent_id || agent.id || `dynamic-${index}`}|${normalizeMergeTarget(agent)}`, agent])).values()];
  const stepCards = S_AGENT_ARCHITECTURE.map(meta => {
    const plan = planByStep.get(meta.step) || {};
    const agent = agentMap[plan.agent_id] || agentMap[meta.agent_id] || {};
    const nodeMembers = dynamicAgents.filter(item => normalizeMergeTarget(item) === `S${meta.step}`);
    const executionMode = nodeMembers.length ? 'dynamic' : plan.execution_mode || plan.mode || 'standard';
    const completedEvent = fallbackSteps.some(item => Number(item.step) === meta.step && item.execution_mode !== 'skip' && item.status !== 'skipped_by_branch_blueprint');
    let status = normalizeSAgentStatus(plan.status, executionMode, completedEvent);
    const memberStatuses = nodeMembers.map(item => String(item.status || 'planned').toLowerCase());
    const dynamicCompleted = memberStatuses.filter(item => ['completed', 'merged'].includes(item)).length;
    const dynamicActive = memberStatuses.some(item => ['recruiting', 'queued', 'running'].includes(item));
    const dynamicTerminal = memberStatuses.length > 0 && memberStatuses.every(item => ['completed', 'merged', 'pruned', 'failed', 'skipped'].includes(item));
    if (dynamicActive) status = 'running';
    else if (dynamicTerminal && dynamicCompleted > 0) status = 'completed';
    else if (dynamicTerminal && memberStatuses.includes('failed')) status = 'failed';
    else if (nodeMembers.length) status = 'pending';
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
    return {...meta, ...plan, agent_id: plan.agent_id || meta.agent_id, name: ensureAgentSuffix(projectedName), task: plan.task || plan.description || agent.description || meta.task, executionMode, status, middleCycle, skills, harness, semantics, mergedAgents, result_summary: plan.result_summary || (nodeMembers.length ? `动态蜂群 ${dynamicCompleted} / ${nodeMembers.length} 个实例完成` : ''), dynamicCompleted, dynamicTotal: nodeMembers.length, backtrackCount: Number.isFinite(backtrackCount) ? Math.max(0, backtrackCount) : 0};
  });
  const otherDynamicAgents = dynamicAgents.filter(item => !/^S[1-6]$/.test(normalizeMergeTarget(item)));
  const completedSteps = stepCards.filter(item => item.status === 'completed').length;
  const stageGates = Array.isArray(workflow.stage_gates) ? workflow.stage_gates : [];
  const restrictedGates = stageGates.filter(item => item.gate_passed === false);
  const branchText = discovery.primary_branch ? `${discovery.primary_branch}${discovery.branch_name ? ` · ${discovery.branch_name}` : ''}` : '需求解析与路径选择';
  const stepModeChanges = metaReview.step_mode_changes?.length ? metaReview.step_mode_changes.map(item => `S${item.step} ${stepModeLabel(item.previous_mode)}→${stepModeLabel(item.mode)}`).join('、') : metaReview.step_mode_overrides?.length ? metaReview.step_mode_overrides.map(item => `S${item.step}→${stepModeLabel(item.mode)}`).join('、') : '';
  const l4Changes = [metaReview.added_secondary_branches?.length ? `参考分支 ${metaReview.added_secondary_branches.join('/')}` : '', stepModeChanges, metaReview.dynamic_subagents?.length ? `新增 ${metaReview.dynamic_subagents.length} 个动态 Agent` : ''].filter(Boolean).join('；');
  const auditComplete = completed || has('audit_completed') || has('report_completed') || has('run_result_saved');
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
    {id: 's_agents', label: 'S1–S6 Agent', status: completedSteps > 0 || latestWinningProgress || has('winning_stage_completed') || has('capability_image_created') ? (stepCards.every(item => ['completed', 'skipped'].includes(item.status)) ? 'completed' : 'running') : 'pending', detail: `${completedSteps} / 6 个专用 Agent 完成${winningRuntimeDetail}${restrictedGates.length ? ` · ${restrictedGates.map(item => item.layer).join('/')} 门控受限` : ''}`},
    {id: 'audit', label: '风险分级审计', status: auditComplete ? 'completed' : has('audit_model_fallback') || events.some(event => event.actor === 'auditor') ? 'running' : 'pending', detail: auditComplete ? (has('audit_model_fallback') ? '确定性审计完成 · 独立模型受限降级' : '确定性审计完成；仅高风险项触发模型复核') : events.some(event => event.actor === 'auditor') ? '正在执行确定性检查或高风险模型复核（优化画像最长 30 秒）' : '等待进入审计'},
    {id: 'report', label: '报告交付', status: reportStatus, detail: reportStatus === 'completed' ? '研究报告已生成' : reportStatus === 'failed' ? '独立报告生成失败，未使用降级模板；可从检查点恢复' : reportStatus === 'running' ? reportRuntimeDetail : '等待审计通过'},
  ];
  const rawPhases = Array.isArray(workflow.phases) ? workflow.phases : [];
  const phaseById = new Map(rawPhases.map((item, index) => [item.id || phaseFallbacks[index]?.id, item]));
  const phases = phaseFallbacks.map(fallback => { const projected = phaseById.get(fallback.id) || {}; const projectedStatus = normalizeWorkflowStatus(projected.status ?? projected.completed, fallback.status); const useProjectedProgress = projectedStatus === 'failed' || workflowStatusRank(projectedStatus) >= workflowStatusRank(fallback.status); return {...fallback, ...projected, label: projected.label || projected.name || fallback.label, detail: fallback.id === 'baseline' ? fallback.detail : useProjectedProgress ? projected.detail || projected.summary || fallback.detail : fallback.detail, status: useProjectedProgress ? projectedStatus : fallback.status}; });
  const loops = workflow.loops || {};
  const loopEventTypes = {inner: 'winning_inner_loop_evaluated', middle: 'winning_middle_loop_evaluated', outer: 'winning_outer_loop_evaluated', meta: 'discovery_meta_loop_evaluated'};
  const firstPending = phases.findIndex(item => !['completed', 'skipped'].includes(item.status));
  return <section className="workflow-overview">
    <header><div><Layers3 size={18}/><span><b>架构执行总览</b><small>A–H 发现蓝图、六个专用 Agent 与四层循环</small></span></div><div className="workflow-badges">{execution.provider && <span>Agent</span>}{discovery.primary_branch && <span>主分支 {discovery.primary_branch}</span>}{discovery.secondary_branches?.length > 0 && <span>参考分支 {discovery.secondary_branches.join('/')}</span>}<em className={live ? 'live' : ''}>{live ? '运行中' : '审计回放'}</em></div></header>
    <div className="workflow-phases workflow-phases-six">{phases.map((phase, index) => <article className={`${phase.status} ${phase.status === 'completed' ? 'done' : index === firstPending && live && phase.status === 'pending' ? 'active' : ''}`} key={phase.id}><i>{phase.status === 'completed' ? <CheckCircle2 size={15}/> : index + 1}</i><div><b>{phase.label}</b><small>{phase.detail}</small></div></article>)}</div>
    <div className="s-agent-overview"><div className="s-agent-overview-title"><div><Bot size={17}/><span><b>S1–S6 专用 Agent</b><small>当前主/参考分支通过执行强度影响每个 Agent；不是固定串联，可跳步、并行与定向回溯。</small></span></div><em>{completedSteps} / 6 完成</em></div><div className="s-agent-grid">{stepCards.map(agent => <article className={`s-agent-card mode-${agent.executionMode} status-${agent.status}`} key={agent.step}>
      <header><i>S{agent.step}</i><div><b>{agent.name}</b><small>独立受控会话</small></div><span className={`s-agent-status ${agent.status}`}>{sAgentStatusLabel(agent.status)}</span></header>
      <p>{agent.task}</p>
      {agent.status === 'running' && agent.current_step && <div className="s-agent-result-preview"><small>当前步骤</small><span>{agent.current_step}{Number(agent.elapsed_seconds || 0) > 0 ? ` · 已耗时 ${Math.round(agent.elapsed_seconds)} 秒` : ''}</span></div>}
      {agent.result_summary && <div className="s-agent-result-preview"><small>本轮结果</small><span>{agentFacingText(agent.result_summary)}</span></div>}
      <div className="s-agent-runtime"><span className={`step-mode ${agent.executionMode}`}>{stepModeLabel(agent.executionMode)}</span><span>{agent.dynamicTotal > 0 ? `蜂群 ${agent.dynamicCompleted}/${agent.dynamicTotal}` : agent.middleCycle > 0 ? `L2 第 ${agent.middleCycle} 轮` : 'L2 未进入'}</span><span>回溯 {agent.backtrackCount} 次</span></div>
      {agent.status === 'skipped' && <small className="s-agent-skip-reason">由 {discovery.primary_branch || '当前'} 分支蓝图按业务路径跳过</small>}
      <details className="s-agent-tech"><summary>Skill、Harness 与编排说明</summary><div><code>{agent.agent_id}</code><div className="s-agent-skills"><small>核心 Skill</small><p>{agent.skills.slice(0, 3).map(skill => <em key={skill}>{skill}</em>)}</p></div><div className="s-agent-harness"><span>Harness</span><code>{agent.harness}</code></div><div className="s-agent-semantics">{agent.semantics.map(item => <span key={item}>{item}</span>)}</div></div></details>
      {agent.mergedAgents.length > 0 && <div className="s-agent-dynamic">{agent.mergedAgents.map((item, index) => <span key={item.agent_id || item.id || index}><Bot size={12}/><b>{item.display_name || item.name || '动态专用 Agent'}</b><small>合并到 S{agent.step}</small></span>)}</div>}
    </article>)}</div>{otherDynamicAgents.length > 0 && <div className="dynamic-agent-other">{otherDynamicAgents.map((item, index) => <span key={item.agent_id || item.id || index}><Bot size={12}/><b>{item.display_name || item.name || '动态专用 Agent'}</b><small>合并到 {normalizeMergeTarget(item) || '待编排节点'}</small></span>)}</div>}</div>
    <div className="loop-overview">{LOOP_ARCHITECTURE.map(loop => { const projected = typeof loops[loop.key] === 'object' ? loops[loop.key] : {}; const count = loopCount(loops[loop.key], loop.key === 'meta' ? Number(metaReview.cycle || 0) : 0); const latest = [...events].reverse().find(event => event.event_type === loopEventTypes[loop.key]); return <article className={count > 0 ? 'used' : ''} key={loop.key}><header><i>{loop.level}</i><div><b>{loop.name}</b><span>{count} 次</span></div></header><p>{projected.description || loop.description}</p><small className="loop-latest">{latest ? `最近：${loopEventDecision(latest)}` : '最近：尚无判定'}</small></article>; })}</div>
    {metaReview.replan_required && <div className="l4-summary"><BrainCircuit size={15}/><span><b>L4 元循环调整</b>{l4Changes || metaReview.rationale || '已形成有界调整'}</span></div>}
  </section>;
}

function InteractionEvent({event, agent}) {
  const tool = event.details?.tool_name;
  const summary = agentFacingText(event.summary);
  const longSummary = summary.length > 260 || /^\s*[\[{]/.test(summary);
  const swarmLifecycle = ['specialist_recruitment_planned','specialist_spawned','specialist_session_started','specialist_session_completed','specialist_completed','specialist_pruned'].includes(event.event_type);
  const detailKeys = event.event_type === 'discovery_meta_loop_evaluated' ? ['cycle','primary_branch','added_secondary_branches','step_mode_overrides','dynamic_subagents','stop_reason'] : swarmLifecycle ? ['wave','batch','archetype','role_purpose','hypothesis_id','merge_target','execution_backend','context_isolation','session_ref','status','reason'] : ['wave','archetype','hypothesis_id','merge_target','score','residuals','reasons','rejection_reasons','step','steps','current_step','elapsed_seconds','phase','execution_mode','status','passed'];
  const detailRows = detailKeys.filter(key => event.details?.[key] !== undefined).slice(0, 10).map(key => [key, event.details[key]]);
  return <article className={`event-card ${event.category}`}><div className="event-dot">{event.category === 'tool' ? <Wrench size={15}/> : event.actor === 'orchestrator' ? <Layers3 size={15}/> : <Bot size={15}/>}</div><div className="event-content"><div className="event-top"><b>{agentFacingText(agent?.display_name || event.details?.display_name || event.actor)}</b><span>{eventLabel(event.event_type)}</span></div><h3>{agentFacingText(tool || event.title)}</h3>{longSummary ? <details className="event-summary-details"><summary><span>{summary}</span><em>展开完整内容</em></summary><p>{summary}</p></details> : <p>{summary}</p>}{(event.input_refs?.length > 0 || event.output_refs?.length > 0 || detailRows.length > 0) && <details className="event-key-details"><summary>关键详情</summary><div className="event-detail-grid">{event.input_refs?.length > 0 && <Detail label="输入引用" value={agentFacingText(event.input_refs.slice(0, 4).join(' · '))}/>} {event.output_refs?.length > 0 && <Detail label="输出引用" value={agentFacingText(event.output_refs.slice(0, 4).join(' · '))}/>} {detailRows.map(([key, value]) => <Detail key={key} label={fieldLabel(key)} value={formatValue(value)}/>)}</div></details>}</div></article>;
}

function ObjectGrid({view, rows}) { const list = Array.isArray(rows) ? rows : Array.isArray(rows?.rows) ? rows.rows : []; const referenceWeapons = Array.isArray(rows?.referenceWeapons) ? rows.referenceWeapons : []; if (!list.length && !referenceWeapons.length) return <Empty text="本次运行没有可展示对象"/>; if (view === 'capabilities') return <CapabilityImageView rows={list} referenceWeapons={referenceWeapons}/>; return <section className="object-grid">{list.map((row, index) => <article className="object-card" key={row.evidence_id || row.stage_id || row.capability_id || index}><div className="object-card-head"><b>{objectTitle(view, row, index)}</b><span>{row.layer || row.priority || row.source_tier || `#${index + 1}`}</span></div>{Object.entries(row).filter(([key, value]) => !['created_at', 'schema_version'].includes(key) && value !== '' && value != null).slice(0, 10).map(([key, value]) => <Detail key={key} label={fieldLabel(key)} value={formatValue(value)}/>)}</article>)}</section>; }
function parseCapabilityPortrait(value) {
  const normalized = completeCapabilityText(value).replace(/\s+(?=- (?:装备与技术实现|关键作战流程|形成能力与作战效果|制胜逻辑机理与对抗边界|发展与验证路径|决策与考核口径)：)/g, '\n');
  const lines = normalized.split('\n').map(item => item.trim()).filter(Boolean);
  const overview = (lines.find(item => !item.startsWith('- ')) || '').replace(/^概述：/, '');
  const points = lines.filter(item => item.startsWith('- ') && !/^- 发展与验证路径[：:]/.test(item)).map(item => {
    const match = item.slice(2).match(/^([^：]+)：(.*)$/);
    return match ? {label:match[1].trim(), text:match[2].trim()} : {label:'论证要点', text:item.slice(2)};
  });
  return {overview, points};
}
function CapabilityPortrait({value}) { const {overview, points} = parseCapabilityPortrait(value); return <section className="capability-portrait"><small>装备能力画像 · 五模块作战论证</small>{overview && <p className="capability-portrait-overview"><b>概述</b>{overview}</p>}{points.length > 0 ? <ul>{points.map((item, index) => <li key={`${item.label}-${index}`}><b>{item.label}</b><span>{item.text}</span></li>)}</ul> : <p>{value}</p>}</section>; }
function CapabilityImageView({rows, referenceWeapons = []}) { const averageConfidence = rows.length ? Math.round(rows.reduce((sum, row) => sum + (row.confidence || 0), 0) / rows.length * 100) : 0; return <section className="capability-view"><div className="capability-summary"><div><span>详细能力画像</span><b>{rows.length}</b></div><div><span>高优先级</span><b>{rows.filter(row => String(row.priority).startsWith('高') || String(row.priority).startsWith('P1')).length}</b></div><div><span>平均置信度</span><b>{averageConfidence}%</b></div></div>{rows.map((row, index) => { const image = completeCapabilityText(row.capability_image); const portrait = completeCapabilityText(row.deep_capability_portrait || image); const structured = row.analysis_provenance_status !== 'legacy_derived'; return <article className="capability-sheet" key={`${row.capability_id || row.name || 'capability'}-${index}`}><header><div><span>{row.capability_type === 'new_capability' ? '新能力方向' : '具体装备方向'}</span><h2>{row.name}</h2></div><div className="capability-score"><b>{Math.round((row.confidence || 0) * 100)}%</b><small>结论置信度</small></div></header>{!structured && <div className="capability-legacy-note">该历史任务采用兼容画像；页面已按现有字段重建精细画像，重新运行可获得更完整的独立综合结论。</div>}<div className="capability-meta"><span><b>编号</b>{row.capability_id}</span><span><b>优先级</b>{row.priority}</span><span><b>任务场景</b>{row.related_scenario}</span></div><CapabilityPortrait value={portrait}/><details className="capability-trace"><summary>查看 S1–S6 论证依据与证据追溯</summary><div><section className="capability-logic"><div><small>来源制胜逻辑</small><p>{row.source_winning_logic}</p></div><div><small>作战运用约束</small><p>{(row.operational_constraints?.length ? row.operational_constraints : row.risk_boundaries || []).join('；')}</p></div></section>{structured && <section className="capability-insight-grid"><CapabilityInsight title="军事运用价值" value={row.military_utility || row.mission_effect}/><CapabilityInsight title="打击 / 反制价值" value={row.strike_countermeasure_value}/><CapabilityInsight title="新颖性" value={row.novelty}/><CapabilityInsight title="前瞻性" value={row.foresight}/></section>}{structured && <div className="capability-columns provenance"><CapabilitySection title="专业 Agent 贡献" rows={(row.agent_contributions || []).map(agentFacingText)}/><CapabilitySection title="证据依据" rows={(row.evidence_basis || []).map(agentFacingText)}/></div>}{structured && <CapabilitySection title="S1–S6 推理引用" rows={row.reasoning_refs || []}/>}</div></details><footer><span>关联证据 {row.evidence_ids?.length || 0} 项</span><code>{(row.evidence_ids || []).slice(0, 5).join(' · ')}</code></footer></article>; })}{referenceWeapons.length > 0 && <section className="capability-reference-library"><header><div><b>参考武器</b><small>未进入本轮 S6 详细画像，不计入上方画像数量；点击卡片查看简要概述</small></div><em>{referenceWeapons.length} 条</em></header><div>{referenceWeapons.map((candidate, index) => { const weaponName = weaponCandidateTitle(candidate); return <details key={candidate.hypothesis_id || `${weaponName}-${index}`}><summary><span><b>{weaponName || `参考武器 ${index + 1}`}</b><small>{weaponCandidateForm(candidate) || '候选装备形态待复核'}</small></span><em>查看概述</em></summary><div><p>{swarmCandidateOverview(candidate)}</p><footer><span>对象证据 {(candidate.evidence_ids || []).length}</span><span>候选置信度 {Math.round(Number(candidate.score || 0) * 100)}%</span><span>不进入 S6 详细撰写</span></footer></div></details>; })}</div></section>}</section>; }
function capabilityDisplayEquipmentForm(row = {}) { const name = String(row.name || ''); const form = String(row.equipment_form || row.equipment_category || ''); const kind = value => /无人机|无人平台|无人艇|无人车|无人潜航/.test(value) ? 'platform' : /拦截弹|巡飞|导弹|弹药|鱼雷|水雷/.test(value) ? 'munition' : /激光武器|高功率微波|定向能/.test(value) ? 'directed-energy' : ''; return kind(name) && kind(form) && kind(name) !== kind(form) ? String(row.primary_equipment_identity || row.name) : form; }
function CapabilityInsight({title, value}) { if (!value) return null; return <div><small>{title}</small><p>{value}</p></div>; }
function CapabilitySection({title, rows}) { if (!rows?.length) return null; return <section className="capability-section"><h3>{title}</h3><ul>{rows.map((row, index) => <li key={`${title}-${index}`}><i>{String(index + 1).padStart(2, '0')}</i><span>{row}</span></li>)}</ul></section>; }
function completeCapabilityText(value) { return String(value || '').trim(); }
function recallStatusLabel(value) { return {pending:'等待路由',routed:'执行中',completed:'已完成',limited:'受限未执行'}[value] || value || '未知'; }
function stageGateLabel(stage, recalls) { const related = (recalls || []).filter(item => item.source_layer === stage.layer); const statuses = new Set(related.map(item => item.status)); if (stage.gate_passed) return statuses.has('completed') ? '再调后通过' : '门控通过'; if (statuses.has('routed')) return '再调执行中'; if (statuses.has('pending')) return '等待再调'; if (statuses.has('completed')) return '再调后仍受限'; if (statuses.has('limited')) return '再调受限'; return '门控未通过'; }
function WinningSwarmPanel({swarm}) {
  const tasks = swarm.task_graph || []; const finalists = swarm.finalists || []; const hypotheses = swarm.hypotheses || []; const rejections = swarm.rejections || []; const budget = swarm.budget || {}; const waves = swarm.waves || []; const core = swarm.core_schedule || {}; const coreWaves = core.logical_waves || []; const finalMerge = swarm.final_merge || {};
  return <section className="winning-swarm-panel"><div className="section-heading"><div><b>制胜机理弹性 Agent 群</b><span>三波有界探索；S1–S6 按依赖动态调度，原始会话隔离，只有绑定候选与目标节点且通过门控的贡献进入共享账本。</span></div><em>{finalists.length} 条最终候选</em></div><div className="swarm-metrics"><div><small>动态实例</small><b>{budget.completed_instances ?? tasks.length} / {budget.maximum_instances || 12}</b></div><div><small>专用波次</small><b>{waves.length} / {budget.maximum_waves || 3}</b></div><div><small>S Agent</small><b>{core.completed_steps?.length || 0} / {core.active_steps?.length || 0}</b></div><div><small>最终合并</small><b>{finalMerge.passed ? '门控通过' : swarm.stop_reason || '运行中'}</b></div></div><div className="swarm-wave-grid">{waves.map(item => <article key={item.wave}><i>W{item.wave}</i><div><b>{item.wave === 1 ? '广度探索' : item.wave === 2 ? '定向挑战' : '收敛决策'}</b><small>{item.task_ids?.length || 0} 个专用 Agent</small></div></article>)}</div>{coreWaves.length > 0 && <div className="core-schedule"><header><b>S1–S6 动态 DAG</b><small>{core.merge_strategy || '依赖满足后并行、拓扑顺序合并'}</small></header><div className="core-wave-grid">{coreWaves.map(item => <article key={item.wave}><i>C{item.wave}</i><div><b>{item.core_agents?.join(' + ')}</b><small>{item.parallel ? '无写入冲突，并行执行' : '依赖满足后执行'}</small></div></article>)}</div></div>}{finalists.length > 0 && <div className="swarm-finalists">{finalists.map((item, index) => <article key={item.hypothesis_id}><header><i>{index + 1}</i><div><b>{item.title}</b><small>{item.equipment_forms?.join(' · ') || '装备形态待验证'}</small></div><em>{Math.round((item.score || 0) * 100)}%</em></header><p>{item.novelty_delta || item.changed_confrontation_variable}</p><div><span>证据 {item.evidence_ids?.length || 0}</span><span>残差 {item.residuals?.length || 0}</span><span>{item.status || 'finalist'}</span></div>{item.failure_boundaries?.length > 0 && <small>失效边界：{item.failure_boundaries.slice(0, 2).join('；')}</small>}</article>)}</div>}{rejections.length > 0 && <details className="swarm-rejections"><summary>查看 {rejections.length} 条淘汰记录</summary>{rejections.slice(0, 8).map((item, index) => <p key={`${item.hypothesis_id}-${index}`}><b>{item.hypothesis_id}</b><span>{(item.reasons || []).join('；') || item.stage}</span></p>)}</details>}</section>;
}
function WinningMechanismView({data}) {
  const input = data.inputs?.at(-1); const resources = data.resources?.at(-1); const nodes = data.reasoning_nodes || []; const stages = data.stages || []; const recalls = data.recalls || []; const stepPlan = data.workflow?.step_plan || []; const swarm = data.swarm || {};
  if (!input) return <Empty text="本次运行尚未形成 S1–S6 Agent 输入包"/>;
  const nodeByStep = new Map(nodes.map(node => [Number(node.step), node]));
  const planByStep = new Map(stepPlan.map(item => [Number(item.step), item]));
  return <div className="winning-view s-agent-results-view">
    <section className="winning-input"><div><span>S1–S6 Agent 输入包</span><h2>{input.problem_frame?.objective}</h2><p>{input.problem_frame?.route_frame}</p></div><dl><dt>研究路线</dt><dd>{routeLabel(input.research_route)}</dd><dt>输入 Packet</dt><dd>{input.packet_ids?.length || 0}</dd><dt>证据索引</dt><dd>{input.evidence_index?.length || 0}</dd><dt>当前轮次</dt><dd>{input.round_budget?.current_round} / {input.round_budget?.maximum_rounds}</dd></dl></section>
    {swarm.policy?.enabled && <WinningSwarmPanel swarm={swarm}/>}
    <section className="winning-resource-section"><div className="section-heading"><div><b>共享受控资源</b><span>各 Agent 读取投影后的理论、案例、前沿证据与问题链，不共享其他 Agent 原始会话。</span></div></div><div className="winning-resources"><ResourceBlock title="理论工具库" rows={resources?.theory_tools} label="name"/><ResourceBlock title="战例库" rows={resources?.case_resources} label="evidence_id"/><ResourceBlock title="前沿情报库" rows={resources?.frontier_resources} label="evidence_id"/><ResourceBlock title="问题链" rows={resources?.question_chain} label="question"/></div></section>
    <section className="s-agent-result-section"><div className="section-heading"><div><b>六个专用 Agent 结果</b><span>按 Agent 展示“认识—证据—置信度—下一步建议”；卡片顺序仅用于编号，不代表固定串联。</span></div><small>{nodes.length} 个结果节点</small></div><div className="s-agent-result-grid">{S_AGENT_ARCHITECTURE.map(meta => {
      const plan = planByStep.get(meta.step) || {}; const skipped = plan.execution_mode === 'skip' || plan.status === 'skipped'; const node = skipped ? null : nodeByStep.get(meta.step); const relatedRecalls = recalls.filter(item => recallMatchesStep(item, meta.step, meta.agent_id)); const question = resources?.question_chain?.[meta.step - 1]; const nextSuggestion = formatNextAction(node?.next_action) || node?.next_step_suggestion || node?.next_step || relatedRecalls.at(-1)?.reason || question?.question || '未记录显式下一步建议；以循环门控和开放问题为准。';
      return <article className={`s-agent-result-card ${node ? 'completed' : skipped ? 'skipped' : 'pending'}`} key={meta.step}><header><i>S{meta.step}</i><div><b>{meta.name}</b><small>{meta.task}</small></div><span>{node ? `已形成 · 回溯 ${plan.backtrack_count ?? relatedRecalls.length}` : skipped ? `${stepModeLabel(plan.execution_mode)} · 蓝图跳过` : '待执行'}</span></header>{node ? <><h3>{agentFacingText(node.title)}</h3><div className="s-agent-result-quad"><section className="recognition"><small>认识</small><p>{agentFacingText(node.summary)}</p></section><section><small>证据</small><p>{node.evidence_ids?.length ? node.evidence_ids.slice(0, 4).join(' · ') : '暂无可展示证据编号'}</p></section><section><small>置信度</small><b>{Math.round((node.confidence || 0) * 100)}%</b></section><section className="next"><small>下一步建议</small><p>{agentFacingText(nextSuggestion)}</p></section></div><details><summary>输入、假设与追溯</summary><div><Detail label="输入引用" value={agentFacingText((node.input_refs || []).join(' · ') || '—')}/><Detail label="关键假设" value={agentFacingText((node.assumptions || []).join('；') || '—')}/></div></details></> : <p className="s-agent-result-empty">{skipped ? `当前 ${data.workflow?.discovery?.primary_branch || 'A–H'} 分支按业务路径跳过该 Agent，不生成虚假结果。` : '该 Agent 尚未形成结果节点。'}</p>}<footer><span>{meta.skills.slice(0, 2).join(' · ')}</span><code>{meta.harness}</code></footer></article>;
    })}</div></section>
    {stages.length > 0 && <section className="s-agent-loop-results"><div className="section-heading"><div><b>循环门控结果</b><span>L1 内循环、L2 中循环与 L3 外循环检查六个 Agent 结果的证据、连续性和跨场景覆盖。</span></div></div><div>{stages.map(stage => <article key={stage.stage_id} className={stage.gate_passed ? 'passed' : 'limited'}><header><i>{stage.layer}</i><div><b>{stage.title}</b><small>置信度 {Math.round((stage.confidence || 0) * 100)}% · 证据 {stage.evidence_ids?.length || 0}</small></div><em>{stageGateLabel(stage, recalls)}</em></header>{stage.gate_reasons?.length > 0 && <p>{stage.gate_reasons.join('；')}</p>}<details><summary>查看本层输出</summary><div>{Object.entries(stage.outputs || {}).filter(([key]) => key !== 'reasoning_refs').map(([key, value]) => <Detail key={key} label={fieldLabel(key)} value={formatValue(value)}/>)}</div></details></article>)}</div></section>}
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
function reportMarkdown(value) {
  const content = agentFacingText(value)
    .replace(/\\\*\\\*([^\n]+?)\\\*\\\*/g, '**$1**')
    .replace(/\*\*([^*\n]+?)\s+\*\*/g, '**$1**')
    .replace(/(\*\*[^*\n]+?\*\*)(?=[\u3400-\u9fffA-Za-z0-9])/g, '$1 ');
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
function ReportView({text, run}) {
  const content = reportMarkdown(typeof text === 'string' ? text : formatValue(text));
  return <section className="report-view enhanced"><div><span><FileCheck2 size={18}/><b>研究报告</b></span><em>{run?.topic}</em></div><article className="report-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{a: ({node: _node, children, ...props}) => <a {...props} target="_blank" rel="noreferrer">{children}</a>}}>{content}</ReactMarkdown></article></section>;
}
function ReportFailureView({run, detail, resuming, resume, error}) { const reason = agentFacingText(String(detail || 'Reporter 未能完成独立深度撰写。').slice(0, 600)); return <section className="report-view enhanced"><div><span><CircleAlert size={18}/><b>报告生成失败</b></span><Status value="failed"/></div><article className="empty"><CircleAlert size={22}/><section><b>未使用确定性降级模板</b><p>{reason}</p>{run?.status === 'failed' && <button className="primary" disabled={resuming} onClick={resume}><RefreshCw size={14}/>{resuming ? '正在恢复' : '从检查点继续生成'}</button>}{error && <p className="form-error">{error}</p>}</section></article></section>; }
function RunDrawer({run, catalog, close, inspect, changed}) {
  const done = run.status === 'completed'; const canEdit = run.status === 'draft'; const canArchive = ['draft', 'completed', 'failed', 'cancelled'].includes(run.status);
  const [editing, setEditing] = useState(false); const [saving, setSaving] = useState(false); const [archiveConfirm, setArchiveConfirm] = useState(false); const [error, setError] = useState(''); const [historyRows, setHistoryRows] = useState([]);
  const [form, setForm] = useState(() => runForm(run, catalog));
  const historyTypes = new Set(historyRows.map(row => row.event_type));
  const historyActors = new Set(historyRows.map(row => row.actor || row.details?.actor || row.payload?.event?.actor || row.payload?.actor));
  const reportStageFailed = run.status === 'failed' && (historyTypes.has('report_model_failed') || historyActors.has('reporter'));
  const stageIndex = done ? 5 : historyTypes.has('report_completed') || historyActors.has('reporter') ? 4 : historyTypes.has('audit_completed') || historyTypes.has('audit_model_fallback') || historyActors.has('auditor') ? 3 : historyTypes.has('winning_subagent_completed') || historyTypes.has('winning_stage_completed') || historyTypes.has('capability_image_created') ? 2 : historyTypes.has('baseline_pipeline_started') || historyTypes.has('baseline_agent_completed') ? 1 : ({queued:0, planning:0}[run.status] ?? -1);
  const loadHistory = () => request(`/runs/${run.run_id}/history`, [], {headers: {'X-Role': 'analyst'}}).then(setHistoryRows);
  useEffect(() => { setForm(runForm(run, catalog)); setEditing(false); setArchiveConfirm(false); setError(''); void loadHistory(); }, [run.run_id]);
  const set = (key, value) => setForm(current => ({...current, [key]: value}));
  const toggleAgent = id => set('selected_agent_ids', form.selected_agent_ids.includes(id) ? form.selected_agent_ids.filter(item => item !== id) : [...form.selected_agent_ids, id]);
  const save = async () => { setSaving(true); setError(''); const updated = await request(`/runs/${run.run_id}`, null, {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Role': 'analyst'}, body: JSON.stringify({topic: form.topic, supplemental_information: form.supplemental_information, research_route: form.research_route, interaction_mode: form.interaction_mode, discovery_branch: form.discovery_branch, execution_profile_id: form.execution_profile_id, report_template_mode: form.report_template_mode, selected_agent_ids: form.selected_agent_ids, max_rounds: Number(form.max_rounds), analyst_confirmed: run.analyst_confirmed || false})}); setSaving(false); if (updated) { changed(updated); setEditing(false); void loadHistory(); } else setError('保存失败。仅草稿任务可编辑。'); };
  const archive = async () => { setSaving(true); const updated = await request(`/runs/${run.run_id}`, null, {method: 'DELETE', headers: {'X-Role': 'analyst'}}); setSaving(false); if (updated) { changed(updated); close(); } else setError('归档失败。运行中的任务不能归档。'); };
  const resume = async () => { setSaving(true); setError(''); const result = await requestResult(`/runs/${run.run_id}/resume`, {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID(), 'X-Role': 'analyst'}}); setSaving(false); if (result.ok) { changed(result.data); void loadHistory(); } else setError(result.detail || '断点恢复失败，请检查 Worker 与模型配置。'); };
  const harnessLabel = run.execution_profile_id === 'winning_swarm_dynamic_v2' ? 'Winning Swarm Dynamic v2 Challenger' : run.execution_profile_id === 'swarm_quality_v1' ? 'Swarm Quality v1 Challenger' : run.execution_profile_id === 'optimized_v2' ? 'Optimized v2 Challenger' : 'Legacy v1';
  return <div className="drawer-backdrop" onClick={close}><aside className="run-drawer" onClick={event => event.stopPropagation()}><button className="drawer-close icon-button" title="关闭" onClick={close}><X size={16}/></button><span className="drawer-eyebrow">研究任务 · {run.run_id}</span>{editing ? <section className="drawer-editor"><Field label="研究主题"><input value={form.topic} onChange={event => set('topic', event.target.value)}/></Field><Field label="补充信息（可选）"><textarea className="supplement-input" value={form.supplemental_information} maxLength={8000} onChange={event => set('supplemental_information', event.target.value)}/></Field><div className="drawer-edit-grid"><Field label="研究路线"><select value={form.research_route} onChange={event => set('research_route', event.target.value)}><option value="auto">按发现分支自动映射</option>{catalog.routes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="交互模式"><select value={form.interaction_mode} onChange={event => set('interaction_mode', event.target.value)}>{(catalog.interaction_modes || []).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="A–H 发现分支"><select value={form.discovery_branch} onChange={event => set('discovery_branch', event.target.value)}><option value="auto">Agent 自动选择</option>{(catalog.discovery_branches || []).map(item => <option key={item.id} value={item.id}>{item.id} · {item.name}</option>)}</select></Field><Field label="运行模式"><select value={form.execution_profile_id} onChange={event => set('execution_profile_id', event.target.value)}>{(catalog.execution_profiles || [{id:'legacy_v1',name:'Legacy v1'}]).filter(item => item.selectable !== false).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="最大轮次"><select value={form.max_rounds} onChange={event => set('max_rounds', Number(event.target.value))}>{[1,2,3,...(form.execution_profile_id === 'legacy_v1' ? [4,5] : [])].map(item => <option key={item} value={item}>{item} 轮</option>)}</select></Field></div><div className="drawer-agent-list">{businessAgents(catalog).map(agent => <label key={agent.agent_id} className={form.selected_agent_ids.includes(agent.agent_id) ? 'selected' : ''}><input type="checkbox" checked={form.selected_agent_ids.includes(agent.agent_id)} onChange={() => toggleAgent(agent.agent_id)}/><span>{agent.display_name}</span></label>)}</div><div className="drawer-editor-actions"><button onClick={() => setEditing(false)}><X size={15}/>取消</button><button className="primary" disabled={saving || !form.topic.trim()} onClick={save}><Save size={15}/>{saving ? '保存中' : '保存草稿'}</button></div></section> : <><h2>{run.topic}</h2><Status value={run.status}/>{run.supplemental_information && <section className="drawer-supplement"><b>用户补充信息</b><p>{run.supplemental_information}</p><small>执行时由主控 Agent 压缩并结构化传递</small></section>}<dl><dt>研究路线</dt><dd>{routeLabel(run.research_route)}</dd><dt>交互模式</dt><dd>{run.interaction_mode === 'autonomous' ? '智能元编排' : '专家约束编排'}</dd><dt>A–H 分支</dt><dd>{run.discovery_branch === 'auto' ? 'Agent 自动选择' : run.discovery_branch}</dd><dt>Harness</dt><dd>{harnessLabel}</dd><dt>执行方式</dt><dd><ExecutionBadge execution={run.execution}/></dd><dt>业务 Agent</dt><dd>{run.selected_agent_ids.length ? run.selected_agent_ids.map(agentModelLabel).join('、') : '由编排 Agent 智能选择'}</dd><dt>最大轮次</dt><dd>{run.max_rounds}</dd></dl><div className="drawer-steps">{['问题解析与任务委派', '基线 Agent 研判', 'S1–S6 轻量门控与按需回溯', '五判据审计', '研究报告输出'].map((item, index) => { const failed = reportStageFailed && index === 4; return <div key={item}><i className={failed ? 'failed' : index < stageIndex ? 'done' : index === stageIndex ? 'active' : ''}/><span>{item}</span>{failed && <Status value="failed"/>}</div>; })}</div>{(done || ['queued', 'planning', 'researching', 'recalling', 'failed'].includes(run.status)) && <div className="drawer-actions"><button onClick={() => inspect('interactions')}><History size={15}/>交互过程</button>{run.status === 'failed' && <button className="primary" disabled={saving} onClick={resume}>{saving ? '恢复中' : '从断点继续'}</button>}{done && <><button onClick={() => inspect('evidence')}>证据中心</button><button onClick={() => inspect('winning')}>S1–S6 Agent</button><button className="primary" onClick={() => inspect('capabilities')}>能力画像</button></>}</div>}{canEdit && <button className="drawer-manage" onClick={() => setEditing(true)}><Pencil size={15}/>编辑草稿</button>}{canArchive && <div className="archive-action">{archiveConfirm ? <><span>归档后任务从当前列表隐藏，审计产物仍保留。</span><button onClick={() => setArchiveConfirm(false)}>取消</button><button className="danger" disabled={saving} onClick={archive}><Trash2 size={14}/>确认归档</button></> : <button onClick={() => setArchiveConfirm(true)}><Archive size={15}/>归档任务</button>}</div>}</>}{error && <p className="form-error"><CircleAlert size={15}/>{error}</p>}<section className="run-history"><div><History size={16}/><b>执行历史</b><span>{historyRows.length} 个事件</span></div>{historyRows.length ? historyRows.slice(-24).reverse().map(row => <article key={row.sequence}><i/><span><b>{eventLabel(row.event_type)}</b><small>#{row.sequence} · {historySummary(row, run.result?.audit_status)}</small></span></article>) : <p>尚无历史事件</p>}</section></aside></div>;
}

function providerDisplayLabel() { return 'Agent'; }
function agentFacingText(value) { return String(value ?? '').replace(/\u7532\u65b9可读能力画像报告/g, '能力画像研究报告').replace(/\u7532\u65b9能力画像报告/g, '能力画像研究报告').replace(/\u7532\u65b9报告/g, '研究报告').replace(/\u7532\u65b9/g, '项目').replace(/codex\s*子\s*agent/gi, '专用 Agent').replace(/codex[\s_-]*cli/gi, 'Agent').replace(/codex\s*专用\s*agent/gi, '专用 Agent').replace(/自定义\s*agent/gi, 'Agent').replace(/codex/gi, 'Agent'); }
function runForm(run) { return {topic: run.topic, supplemental_information: run.supplemental_information || '', research_route: run.research_route, interaction_mode: run.interaction_mode || 'expert', discovery_branch: run.discovery_branch || 'auto', execution_profile_id: run.execution_profile_id || 'legacy_v1', report_template_mode: run.report_template_mode || 'three_layer_nine_item', selected_agent_ids: [...run.selected_agent_ids], max_rounds: run.max_rounds}; }
function agentModelLabel(id) { return {orchestrator:'编排器',scenario_divergence:'场景发散',case_research:'案例研究',technology_radar:'技术雷达',opponent_monitoring:'对手监测',system_confrontation:'体系对抗',cross_domain_fusion:'跨域融合',nontraditional_security:'非传统安全',international_situation:'国际形势',combat_scenario:'作战场景',weapon_equipment:'武器装备',operational_employment:'作战运用',convergence_fusion:'收敛融合',winning_mechanism:'S Agent 编排器',winning_dynamic_specialist:'动态专用 Agent 模板',winning_s1_opponent:'S1 对手分析',winning_s2_operations:'S2 作战运用审查',winning_s3_breakthrough:'S3 突破口思考',winning_s4_capability:'S4 装备能力映射',winning_s5_gap:'S5 装备现状差距',winning_s6_image:'S6 能力图像综合',winning_step_critic:'步骤批判',winning_round_critic:'中循环批判',auditor:'审计',reporter:'报告'}[id] || id; }
function stringList(value) { if (value == null || value === '') return []; const rows = Array.isArray(value) ? value : [value]; return rows.map(item => typeof item === 'object' && item !== null ? item.skill_id || item.id || item.name || '' : String(item)).filter(Boolean); }
function ensureAgentSuffix(value) { const text = agentFacingText(value || '专用 Agent').trim(); return /agent$/i.test(text) ? text : `${text} Agent`; }
function normalizeStepRef(value) { const text = String(value ?? '').trim(); if (!text) return '—'; if (text.toLowerCase() === 'convergence') return '收敛融合'; const match = text.match(/(?:winning_s|step[_ -]?|^s?)([1-6])(?:\b|_)/i); return match ? `S${match[1]}` : text; }
function normalizeMergeTarget(item = {}) { const published = item.handoff_policy?.publish_to; const value = item.target_step ?? item.merge_into_step ?? item.merge_target ?? item.target ?? (Array.isArray(published) ? published[0] : published); return value == null || value === '' ? '' : normalizeStepRef(value); }
function normalizeSAgentStatus(value, executionMode, completedEvent = false) { const status = String(value || '').toLowerCase(); if (executionMode === 'skip' || status.includes('skip')) return 'skipped'; if (['completed', 'complete', 'done', 'success', 'succeeded'].includes(status) || completedEvent) return 'completed'; if (['running', 'started', 'in_progress', 'active'].includes(status)) return 'running'; if (['failed', 'error', 'cancelled'].includes(status)) return 'failed'; return 'pending'; }
function latestReporterPhaseStatus(events = [], runCompleted = false, runFailed = false) { let status = 'pending'; let started = false; events.forEach(event => { const details = event.details || {}; const delegated = event.event_type === 'agent_task_delegated' && details.target_agent_id === 'reporter'; const activity = event.actor === 'reporter' && (['task_received', 'tool_call', 'tool_result'].includes(event.event_type) || event.event_type.startsWith('report_model_')); if (delegated || activity) { started = true; status = 'running'; } if (event.event_type === 'report_model_failed') { started = true; status = 'failed'; } else if (event.event_type === 'report_completed') { started = true; status = 'completed'; } }); if (runCompleted) return 'completed'; if (runFailed && started && status !== 'completed') return 'failed'; return status; }
function normalizeWorkflowStatus(value, fallback = 'pending') { if (value === true) return 'completed'; if (value === false || value == null || value === '') return fallback; const status = String(value).toLowerCase(); if (['completed', 'complete', 'done', 'success', 'succeeded'].includes(status)) return 'completed'; if (['running', 'started', 'in_progress', 'active'].includes(status)) return 'running'; if (status.includes('skip')) return 'skipped'; if (['failed', 'error', 'cancelled'].includes(status)) return 'failed'; return 'pending'; }
function workflowStatusRank(value) { return {failed: 0, pending: 0, running: 1, skipped: 2, completed: 3}[value] ?? 0; }
function sAgentStatusLabel(value) { return {pending:'待执行',running:'执行中',completed:'已完成',skipped:'已跳步',failed:'失败'}[value] || value; }
function loopCount(value, fallback = 0) { if (typeof value === 'object' && value !== null) value = value.count ?? value.iterations ?? value.value; const count = Number(value); return Number.isFinite(count) ? Math.max(0, count) : Math.max(0, Number(fallback) || 0); }
function recallMatchesStep(item, step, agentId) { const text = [item.return_node, item.target_agent_id, item.target_capability_tag].filter(Boolean).join(' ').toLowerCase(); return text.includes(String(agentId).toLowerCase()) || new RegExp(`(?:^|[^0-9])s?${step}(?:[^0-9]|$)`, 'i').test(text); }
function eventTargetsStep(event, step, agentId) { const details = event.details || {}; const realBacktrack = event.event_type === 'recall_requested' || (['winning_inner_loop_evaluated', 'winning_middle_loop_evaluated', 'winning_outer_loop_evaluated'].includes(event.event_type) && details.passed === false && (['retry', 'recall', 'backtrack'].includes(String(details.recommended_action || '').toLowerCase()) || Number(details.rerun_from_step || details.backtrack_to_step || 0) > 0 || (details.return_node != null && details.return_node !== ''))); if (!realBacktrack) return false; const text = [event.actor, details.target_agent_id, details.rerun_from_step, details.backtrack_to_step, details.return_node, details.return_nodes, details.step].flat().filter(value => value != null).join(' ').toLowerCase(); return text.includes(String(agentId).toLowerCase()) || new RegExp(`(?:^|[^0-9])s?${step}(?:[^0-9]|$)`, 'i').test(text); }
function formatNextAction(value) { if (!value) return ''; if (typeof value === 'string') return value; if (typeof value !== 'object') return String(value); const action = {continue:'继续',parallel:'并行展开',backtrack:'回溯',recall:'定向再调',stop:'提交门控'}[value.action] || value.action || ''; const target = Number(value.target_step || 0) > 0 ? `S${value.target_step}` : ''; return [action, target, value.reason].filter(Boolean).join(' · '); }
function loopEventDecision(event) { const details = event.details || {}; const decision = details.passed === true ? '通过' : details.passed === false ? '需回溯' : details.replan_required === true ? '触发重规划' : details.status ? formatValue(details.status) : event.summary || event.title || '已完成判定'; const target = details.rerun_from_step ?? details.return_node ?? details.target_agent_id; return agentFacingText(`${decision}${target != null && target !== '' ? ` · 目标 ${normalizeStepRef(target)}` : ''}`); }
function historySummary(row, finalAuditStatus = '') { const payload = row.payload || {}; const event = payload.event || {}; const summary = event.summary || failureReasonText(payload.error) || payload.status || payload.prior_status || payload.research_route || row.event_type; const auditRelated = row.event_type === 'audit_completed' || event.actor === 'auditor' || event.payload?.tool_name === 'write_audit'; if (finalAuditStatus === 'approved' && auditRelated && /limited|受限/i.test(String(summary))) return '五判据初审待收敛（最终已通过）'; return agentFacingText(summary); }
function failureReasonText(value) { const reason = String(value || '').trim(); if (!reason) return ''; if (reason === 'wall-clock budget expired') return '制胜机理阶段外层 900 秒墙钟预算到期，已完成结果未被接纳'; return reason; }
function PageTitle({eyebrow, title, subtitle, children}) { return <div className="page-title"><div><span>{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></div><div className="title-actions">{children}</div></div>; }
function Metric({label, value, icon: Icon}) { return <article className="metric"><div><span>{label}</span><b>{value}</b></div><Icon size={20}/></article>; }
function Field({label, children}) { return <label className="field"><span>{label}</span>{children}</label>; }
function TagGroup({label, items}) { return <div className="tag-group"><small>{label}</small><p>{(items || []).map(item => <em key={item}>{item}</em>)}</p></div>; }
function Detail({label, value}) { return <div className="detail"><small>{label}</small><p>{value}</p></div>; }
function Status({value}) { return <span className={`status ${value}`}><i/>{statusLabel(value)}</span>; }
function ExecutionBadge({execution = {}}) { const real = execution.mode === 'real'; return <span className={`execution ${real ? 'real' : 'fake'}`}><i/>{real ? `${providerDisplayLabel(execution.provider)} · ${execution.model || '默认模型'}` : 'Fake · 离线'}</span>; }
function Empty({text}) { return <div className="empty"><Activity size={23}/>{text}</div>; }
async function request(path, fallback, options) { try { const response = await fetch(`${api}${path}`, options); if (!response.ok) return fallback; return (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : await response.text(); } catch { return fallback; } }
async function requestResult(path, options) { try { const response = await fetch(`${api}${path}`, options); const data = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : await response.text(); return response.ok ? {ok:true,data} : {ok:false,status:response.status,detail:typeof data === 'object' ? data.detail : data}; } catch { return {ok:false,detail:'无法连接 API 服务。'}; } }
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
function eventLabel(value) { return {run_created: '任务创建', run_updated: '草稿更新', run_archived: '任务归档', run_status_changed: '状态变化', run_recovered: '中断恢复', run_result_saved: '交付完成', run_failed: '运行失败', run_started: '任务启动', discovery_meta_loop_evaluated: 'L4 元循环', baseline_pipeline_started: '研究流水线启动', baseline_discovery_started: '多源检索启动', baseline_discovery_lane_started: '检索通道启动', baseline_discovery_lane_completed: '检索通道完成', baseline_discovery_completed: '多源检索完成', baseline_model_queue_started: '模型调用排队', baseline_model_call_started: '模型调用启动', baseline_model_call_progress: '模型持续执行', baseline_model_call_completed: '模型调用完成', baseline_analysis_started: '结构化分析启动', baseline_analysis_completed: '结构化分析完成', baseline_materialization_progress: '证据材料化进度', baseline_wave_started: '研究波次启动', baseline_wave_completed: '研究波次完成', agent_task_delegated: 'Agent 委派', agent_harness_completed: 'Harness 完成', task_received: '任务接收', tool_call: '工具调用', tool_result: '工具结果', domain_tool_invoked: '领域工具', evidence_assessed: '证据评分', baseline_result: '阶段结果', savepoint: '保存点', baseline_agent_completed: '专业研究完成', baseline_agents_summarized: '基线汇总', packet_admission_evaluated: 'Packet 门控', packet_admission_reused: 'Packet 门控复用', discovery_convergence_completed: '收敛融合', discovery_convergence_reused: '收敛结果复用', winning_model_queue_started: 'S Agent 排队', winning_model_call_started: 'S Agent 启动', winning_model_call_progress: 'S Agent 持续执行', winning_model_call_completed: 'S Agent 模型完成', swarm_planned: 'Agent 群规划', specialist_recruitment_planned: '专用 Agent 招聘', specialist_spawned: '专用 Agent 孵化', specialist_session_started: '独立 CLI 会话启动', specialist_session_completed: '独立 CLI 会话结束', specialist_completed: '专用 Agent 完成', specialist_pruned: '专用 Agent 回收', hypothesis_created: '候选假设创建', hypothesis_merged: '候选贡献合并', hypothesis_rejected: '候选假设淘汰', swarm_gate_evaluated: 'Agent 群门控', promotion_candidate_created: 'Agent 晋级候选', winning_subagent_completed: 'S Agent 完成', winning_inner_loop_evaluated: '内循环批判', winning_middle_loop_evaluated: '中循环批判', winning_outer_loop_evaluated: '外循环复核', winning_reasoning_step_completed: 'S Agent 结果固化', winning_stage_completed: 'L1-L3 门控', recall_requested: '定向再调', recall_task_completed: '再调完成', coverage_recomputed_after_recall: '再调覆盖重算', winning_stage_gate_reevaluated: '再调门控重评', capability_image_created: '能力画像', audit_model_fallback: '审计降级', audit_completed: '审计完成', audit_release_reconciled: '最终审计通过', report_model_queue_started: 'Reporter 排队', report_model_call_started: 'Reporter 启动', report_model_call_progress: 'Reporter 持续撰写', report_model_call_completed: 'Reporter 模型完成', report_model_failed: '报告生成失败（未降级）', report_completed: '报告完成'}[value] || value; }
const DYNAMIC_SWARM_EVENT_LABELS = {winning_mission_graph_planned:'动态任务图规划',winning_agent_instance_recruited:'残差触发招聘',winning_agent_instance_ready:'实例依赖就绪',winning_agent_session_started:'独立 CLI 会话启动',winning_agent_session_completed:'独立 CLI 会话完成',winning_agent_instance_failed:'实例失败隔离',winning_agent_instance_cancelled:'实例取消回收',winning_candidate_branch_created:'候选分支创建',winning_candidate_ledger_frozen:'候选账本更新',winning_contribution_queued:'贡献进入 Merge 队列',winning_contribution_rejected:'贡献越界拒绝',winning_contribution_rebase_required:'贡献版本重基',winning_contribution_merged:'贡献定向合并',winning_portfolio_merge_completed:'装备组合 Merge 完成'};
function displayEventLabel(value) { return DYNAMIC_SWARM_EVENT_LABELS[value] || eventLabel(value); }
function routeLabel(value) { return {new_winning_mechanism: '新制胜机理', traditional_gap: '传统能力缺口', war_case_learning: '局部战争案例', auto: '自动'}[value] || value; }
function statusLabel(value) { return {queued: '已排队', draft: '草稿', planning: '规划中', researching: '研究中', recalling: '再调中', pause_requested: '请求暂停', paused: '已暂停', cancel_requested: '正在停止', cancelled: '已取消', completed: '已完成', failed: '失败', archived: '已归档'}[value] || value; }
const rootElement = document.getElementById('root');
const appRoot = globalThis.__equipmentDeepResearchRoot || createRoot(rootElement);
globalThis.__equipmentDeepResearchRoot = appRoot;
appRoot.render(<App/>);
