import React, {useEffect, useMemo, useState} from 'react';
import {Beaker, CheckCircle2, CircleAlert, Download, Eye, Play, RefreshCw, Trash2, X} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './styles.css';

const LABELS = {
  full_method: '完整方法',
  no_multisource_baseline: '去多源基线',
  no_winning_mechanism: '去制胜机理',
};
const DIMENSION_LABELS = {
  route_task_fulfillment: '路径与任务完成',
  evidence_and_factuality: '证据与事实可靠性',
  causal_and_mechanism_depth: '因果与机理深度',
  military_operational_value: '军事运用价值',
  capability_mapping_and_demand_quality: '能力映射与需求质量',
  novelty_and_foresight: '前瞻创新性',
  system_and_cross_scenario_robustness: '体系与跨场景稳健性',
  uncertainty_and_validation: '不确定性与验证',
};

function AblationPage({apiBase}) {
  const [overview, setOverview] = useState(null); const [detail, setDetail] = useState(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [datasetId, setDatasetId] = useState('fixture-smoke'); const [queries, setQueries] = useState([]); const [selectedIds, setSelectedIds] = useState([]); const [projectRuns, setProjectRuns] = useState({});
  const [controlSource, setControlSource] = useState('existing'); const [mode, setMode] = useState('fake'); const [judgeMode, setJudgeMode] = useState('fake'); const [confirmed, setConfirmed] = useState(false); const [starting, setStarting] = useState(false);
  const request = async (path, options = {}) => { const {headers = {}, ...rest} = options; const response = await fetch(`${apiBase}${path}`, {...rest, headers: {'X-Role':'analyst', ...headers}}); const payload = await response.json().catch(() => null); if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`); return payload; };
  const load = async preferred => { try { const value = await request('/ablations/overview'); setOverview(value); const target = preferred || detail?.experiment_id || value.runs?.[0]?.experiment_id; if (target) setDetail(await request(`/ablations/runs/${encodeURIComponent(target)}`)); if (!value.datasets?.some(item => item.dataset_id === datasetId) && value.datasets?.length) setDatasetId(value.datasets[0].dataset_id); setError(''); } catch (reason) { setError(reason.message || '消融模块不可用'); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  useEffect(() => { if (!datasetId) return; request(`/ablations/datasets/${encodeURIComponent(datasetId)}/queries`).then(value => { setQueries(value.queries || []); setSelectedIds([]); setProjectRuns({}); }).catch(reason => setError(reason.message)); }, [datasetId]);
  useEffect(() => { if (!detail || !['queued','running','cancelling'].includes(detail.status)) return undefined; const timer = setInterval(() => void load(detail.experiment_id), 1800); return () => clearInterval(timer); }, [detail?.experiment_id, detail?.status]);
  const researchRuns = overview?.research_runs || [];
  useEffect(() => { if (!selectedIds.length || !researchRuns.length) return; setProjectRuns(current => { const next = {...current}; selectedIds.forEach(id => { if (next[id]) return; const query = queries.find(item => item.query_id === id); const exact = researchRuns.find(run => String(run.topic).trim() === String(query?.query || '').trim()); if (exact) next[id] = exact.run_id; }); return next; }); }, [selectedIds.join('|'), queries, researchRuns]);
  const selectedQueries = useMemo(() => queries.filter(item => selectedIds.includes(item.query_id)), [queries, selectedIds]);
  const toggle = id => setSelectedIds(rows => rows.includes(id) ? rows.filter(item => item !== id) : [...rows, id]);
  const start = async () => { if (!selectedIds.length) { setError('请至少选择一条 Query。'); return; } if ((mode === 'real' || judgeMode === 'real') && !confirmed) { setError('真实运行或评审必须确认外部数据发送。'); return; } setStarting(true); setError(''); try { const payload = await request('/ablations/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({dataset_id:datasetId, query_ids:selectedIds, control_source:controlSource, project_runs:projectRuns, mode, judge_mode:judgeMode, confirm_external_data:confirmed})}); setDetail(payload); await load(payload.experiment_id); } catch (reason) { setError(reason.message); } finally { setStarting(false); } };
  const cancel = async () => { if (!detail) return; try { setDetail(await request(`/ablations/runs/${detail.experiment_id}/cancel`, {method:'POST'})); } catch (reason) { setError(reason.message); } };
  const remove = async run => { if (!window.confirm(`确定删除消融实验 ${run.experiment_id} 及全部产物吗？`)) return; try { await request(`/ablations/runs/${run.experiment_id}`, {method:'DELETE'}); if (detail?.experiment_id === run.experiment_id) setDetail(null); await load(); } catch (reason) { setError(reason.message); } };
  if (loading) return <div className="ablation-page"><header><Beaker/><div><span>实验扩展</span><h1>消融实验</h1><p>正在读取消融模块。</p></div></header></div>;
  return <div className="ablation-page">
    <header className="ablation-title"><Beaker size={24}/><div><span>可插拔实验扩展</span><h1>核心环节消融实验</h1><p>去多源基线仅替换为受限通用检索 Agent，并保留 S1–S6 与 L1–L4；去制胜机理仅保留多源基线。</p></div><button onClick={() => load()}><RefreshCw size={15}/>刷新</button></header>
    {error && <div className="ablation-error"><CircleAlert size={16}/>{error}</div>}
    <section className="ablation-matrix">{(overview?.variants || []).map(item => <article key={item.variant_id}><b>{item.label}</b><span>基线：{item.baseline}</span><span>机理：{item.winning}</span><em>循环：{item.loops}</em></article>)}</section>
    <div className="ablation-layout"><section className="ablation-config">
      <h2>配置实验</h2>
      <label>Query 数据集<select value={datasetId} onChange={event => setDatasetId(event.target.value)}>{(overview?.datasets || []).map(item => <option value={item.dataset_id} key={item.dataset_id}>{item.dataset_id} · {item.query_count} 条</option>)}</select></label>
      <div className="ablation-query-list">{queries.map(item => <label className={selectedIds.includes(item.query_id) ? 'selected' : ''} key={item.query_id}><input type="checkbox" checked={selectedIds.includes(item.query_id)} onChange={() => toggle(item.query_id)}/><span><b>{item.query_id}</b>{item.query}<small>{item.domain} · {item.split}</small></span></label>)}</div>
      <div className="ablation-grid"><label>控制组来源<select value={controlSource} onChange={event => setControlSource(event.target.value)}><option value="existing">自动绑定已有完整方法报告（探索性）</option><option value="rerun">同批重新运行完整方法（正式消融）</option></select></label><label>消融运行<select value={mode} onChange={event => setMode(event.target.value)}><option value="fake">离线 Fake</option><option value="real">真实模型</option></select></label><label>Judge<select value={judgeMode} onChange={event => setJudgeMode(event.target.value)}><option value="fake">离线双 Judge</option><option value="real">真实双 Judge（至少2条）</option></select></label></div>
      {controlSource === 'existing' && <section className="ablation-bindings"><h3>自动绑定完整方法报告</h3><p>优先按 Query 主题匹配最新已完成报告；也可手动改选。该模式节省重跑时间，但结果仅作探索性参考。</p>{selectedQueries.map(query => <label key={query.query_id}>{query.query_id} · {query.query}<select value={projectRuns[query.query_id] || ''} onChange={event => setProjectRuns(rows => ({...rows, [query.query_id]:event.target.value}))}><option value="">由后端按主题自动匹配</option>{researchRuns.map(run => <option value={run.run_id} key={run.run_id}>{run.topic} · {run.run_id}</option>)}</select></label>)}</section>}
      {(mode === 'real' || judgeMode === 'real') && <label className="ablation-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/><span>确认 Query、报告和必要上下文会发送给外部模型服务</span></label>}
      <button className="ablation-start" disabled={starting} onClick={start}><Play size={16}/>{starting ? '正在创建' : '启动三组消融实验'}</button>
    </section>
    <section className="ablation-results"><h2>实验记录</h2><div className="ablation-run-list">{(overview?.runs || []).map(run => <article key={run.experiment_id}><button onClick={() => load(run.experiment_id)}><span><b>{run.experiment_id}</b><small>{run.dataset_id} · {run.query_count} 条 · {run.status}</small>{run.live_progress?.current_stage_label && <em>{run.live_progress.current_stage_label}</em>}</span><Eye size={15}/></button><button disabled={['queued','running','cancelling'].includes(run.status)} onClick={() => remove(run)}><Trash2 size={14}/></button></article>)}</div><AblationDetail detail={detail} apiBase={apiBase} cancel={cancel}/></section></div>
  </div>;
}

function AblationDetail({detail, apiBase, cancel}) {
  const [reportData, setReportData] = useState({queries: []});
  const [reportQueryId, setReportQueryId] = useState('');
  useEffect(() => {
    let cancelled = false;
    if (!detail?.experiment_id) { setReportData({queries: []}); return undefined; }
    fetch(`${apiBase}/ablations/runs/${encodeURIComponent(detail.experiment_id)}/reports`, {headers:{'X-Role':'analyst'}})
      .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then(value => { if (!cancelled) { setReportData(value); setReportQueryId(current => current || value.queries?.[0]?.query_id || ''); } })
      .catch(() => { if (!cancelled) setReportData({queries: []}); });
    return () => { cancelled = true; };
  }, [detail?.experiment_id, detail?.status, detail?.progress?.completed, apiBase]);
  if (!detail) return <div className="ablation-empty">选择或启动实验后查看结果。</div>;
  const running = ['queued','running','cancelling'].includes(detail.status);
  const comparisons = Object.entries(detail.summary?.comparisons || {});
  const live = detail.live_progress || {};
  const workflow = [['running_variants','运行实验组'],['validating_variants','有效性检查'],['building_pairs','匿名配对'],['judging','双 Judge'],['aggregating','统计汇总'],['writing_report','报告归档']];
  const foundStage = workflow.findIndex(([id]) => id === detail.stage);
  const stageIndex = detail.status === 'completed' ? workflow.length : Math.max(0, foundStage);
  const reportQuery = (reportData.queries || []).find(item => item.query_id === reportQueryId) || reportData.queries?.[0];
  return <div className="ablation-detail">
    <header><div><b>{detail.experiment_id}</b><span>{detail.status} · {live.current_stage_label || stageLabel(detail.stage)}</span></div>{running && <button onClick={cancel}><X size={14}/>停止</button>}</header>
    {running && <>
      <div className="ablation-current-stage"><span>当前环节</span><b>{live.current_stage_label || stageLabel(detail.stage)}</b><p>{live.current_detail || '正在读取任务事件流'}</p></div>
      <div className="ablation-progress"><i style={{width:`${detail.progress?.percent || 0}%`}}/><span>{detail.progress?.percent || 0}% · 已完成 {live.completed_tasks || 0}/{live.total_tasks || detail.progress?.total || 0} 个实验任务</span></div>
      <div className="ablation-workflow">{workflow.map(([id,label], index) => <span className={index < stageIndex ? 'done' : index === stageIndex ? 'active' : ''} key={id}><i>{index < stageIndex ? '✓' : index + 1}</i>{label}</span>)}</div>
    </>}
    {(live.tasks || []).length > 0 && <div className="ablation-task-progress">{live.tasks.map(task => <article className={task.status} key={`${task.system_id}-${task.query_id}`}><header><b>{LABELS[task.system_id] || task.system_id}</b><span>{task.query_id}</span></header><strong>{task.phase_label}</strong><p>{task.detail}</p>{task.actor && <small>{task.actor} · {formatTime(task.updated_at)}</small>}</article>)}</div>}
    <div className="ablation-validity">{Object.entries(detail.validity || {}).map(([id,row]) => <span className={row.valid ? 'valid' : 'invalid'} key={id}>{row.valid ? <CheckCircle2 size={13}/> : <CircleAlert size={13}/>} {LABELS[id]}：{row.valid ? '有效' : row.reason || '无效'}</span>)}</div>
    {comparisons.map(([id,comparison]) => { const effect = detail.summary.effects?.[id] || {}; const record = ablationQueryRecord(comparison, id); const causal = detail.causal_comparison_valid ?? detail.summary?.causal_comparison_valid; return <article className="ablation-comparison" key={id}><h3>完整方法 vs {LABELS[id]}</h3><div className="ablation-query-outcome"><span><b>{record.wins} 胜</b>完整方法</span><em><b>{record.ties} 平</b>单条 Query 平局</em><span><b>{record.losses} 胜</b>{LABELS[id]}</span></div><AblationRecord record={record} variantLabel={LABELS[id]}/><p>{!causal ? '探索性结果：控制组版本或样本条件不足，不形成方法优劣结论' : effect.status === 'supported' ? '设计贡献得到支持' : effect.status === 'directional' ? '仅有方向性证据' : '当前数据不支持'}</p><JudgeVoteChart comparison={comparison} variant={id}/></article>; })}
    {reportQuery && <section className="ablation-report-compare"><header><div><b>逐 Query 报告对比</b><span>完整报告在实验执行时同步保存到归档</span></div>{(reportData.queries || []).length > 1 && <select value={reportQuery.query_id} onChange={event => setReportQueryId(event.target.value)}>{reportData.queries.map(item => <option value={item.query_id} key={item.query_id}>{item.query_id}</option>)}</select>}</header>{['no_multisource_baseline','no_winning_mechanism'].map(variant => <ReportPair key={variant} full={reportQuery.reports?.full_method} ablated={reportQuery.reports?.[variant]} variant={variant}/>)}</section>}
    {!running && <div className="ablation-downloads"><a href={`${apiBase}/ablations/runs/${detail.experiment_id}/report`} target="_blank" rel="noreferrer"><Eye size={14}/>查看 Markdown 报告</a><a href={`${apiBase}/ablations/runs/${detail.experiment_id}/bundle`}><Download size={14}/>下载完整归档</a></div>}
  </div>;
}

function stageLabel(stage) { return ({queued:'等待调度',running_variants:'运行实验组',validating_variants:'有效性检查',building_pairs:'匿名配对',judging:'双 Judge 评审',aggregating:'统计汇总',writing_report:'生成报告',completed:'已完成',failed:'失败',cancelling:'正在停止'})[stage] || stage; }
function formatTime(value) { if (!value) return ''; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('zh-CN', {hour12:false}); }

function ReportPair({full, ablated, variant}) { return <article className="ablation-report-pair"><h3>完整方法 vs {LABELS[variant]}</h3><div><ReportPane title="完整方法" report={full}/><ReportPane title={LABELS[variant]} report={ablated}/></div></article>; }
function ReportPane({title, report}) { return <section className={`ablation-report-pane ${report?.status || 'pending'}`}><header><b>{title}</b><span>{report ? `${report.status} · ${Math.round(report.duration_seconds || 0)} 秒` : '等待报告'}</span></header>{report?.status === 'completed' && report.answer ? <div className="ablation-report-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{report.answer}</ReactMarkdown></div> : <div className="ablation-report-unavailable">{report?.error || '该实验组报告尚未生成。'}</div>}</section>; }
function ablationQueryRecord(comparison, variant) { const outcomes = Array.isArray(comparison?.query_outcomes) ? comparison.query_outcomes : []; if (outcomes.length) return {wins:outcomes.filter(row => row.winner === 'full_method').length, ties:outcomes.filter(row => row.winner === 'tie').length, losses:outcomes.filter(row => row.winner === variant).length, total:outcomes.length}; const full = comparison?.systems?.full_method || {}; const wins = Number(full.wins || 0); const ties = Number(full.ties || 0); const losses = Number(full.losses || 0); return {wins,ties,losses,total:wins+ties+losses}; }
function AblationRecord({record, variantLabel}) { const result = record.wins > record.losses ? `完整方法净胜 ${record.wins - record.losses} 条 Query` : record.wins < record.losses ? `${variantLabel}净胜 ${record.losses - record.wins} 条 Query` : '双方胜场持平'; return <section className="ablation-record"><div><strong>{record.wins} 胜 · {record.ties} 平 · {record.losses} 负</strong><em>{result}</em></div><p>胜负以完整方法为视角，来自已有逐 Query 评审结果；每条 Query 汇总匿名双 Judge 与正反序判决后只计 1 场{record.total ? `，共 ${record.total} 条 Query` : ''}。</p></section>; }
function JudgeVoteChart({comparison, variant}) { const rows = Object.entries(comparison.dimension_votes || {}); if (!rows.length) return null; return <section className="ablation-votes"><header><div><b>Benchmark 分维度 Judge 票型</b><span>匿名 A/B · 正反序 · 双 Judge；完整方法 · 平 · {LABELS[variant]}</span></div><small>{comparison.judgment_count || 0} 份原始判决</small></header>{rows.map(([dimension,votes]) => { const full = Number(votes.full_method || 0); const tie = Number(votes.tie || 0); const other = Number(votes[variant] || 0); const total = Math.max(1, full + tie + other); return <div className="ablation-vote-row" key={dimension}><span>{DIMENSION_LABELS[dimension] || dimension}</span><div><i className="full" style={{width:`${full/total*100}%`}}/><i className="tie" style={{width:`${tie/total*100}%`}}/><i className="ablated" style={{width:`${other/total*100}%`}}/></div><b>{full}:{tie}:{other}</b></div>; })}<footer><span><i className="full"/>完整方法</span><span><i className="tie"/>平票</span><span><i className="ablated"/>{LABELS[variant]}</span></footer></section>; }

export default {id:'ablation', label:'消融实验', icon:Beaker, probePath:'/ablations/overview', Component:AblationPage};
