import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Plus, RefreshCw, Play, Eye} from 'lucide-react';
import './styles.css';

const api = '/api/v1';
function App() {
  const [runs, setRuns] = useState([]); const [topic, setTopic] = useState(''); const [route, setRoute] = useState('new_winning_mechanism'); const [showForm, setShowForm] = useState(false);
  const load = () => fetch(`${api}/runs`).then(r => r.ok ? r.json() : []).then(setRuns).catch(() => setRuns([]));
  useEffect(load, []);
  async function create() { const r = await fetch(`${api}/runs`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({topic,research_route:route,selected_agent_ids:[],max_rounds:5})}); if (r.ok) {const created=await r.json(); await fetch(`${api}/runs/${created.run_id}/start`, {method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}}); setTopic(''); setShowForm(false); load();}}
  return <div className="shell"><header><div className="brand">装备能力图像 Deep Research</div><span>分析师工作台</span></header><aside><b>研究任务</b><a className="active">任务列表</a><a>证据中心</a><a>制胜机理</a><a>能力画像</a><a>报告评审</a></aside><main><div className="title"><div><h1>研究任务</h1><p>市场需求挖掘与装备能力图像研判</p></div><div className="actions"><button title="刷新" onClick={load}><RefreshCw size={17}/></button><button className="primary" onClick={()=>setShowForm(!showForm)}><Plus size={17}/>新建研究</button></div></div>{showForm&&<section className="form"><label>研究主题<input value={topic} onChange={e=>setTopic(e.target.value)} placeholder="例如：低空无人机探测预警能力"/></label><label>研究路线<select value={route} onChange={e=>setRoute(e.target.value)}><option value="new_winning_mechanism">新制胜机理</option><option value="traditional_gap">传统能力缺口</option><option value="war_case_learning">局部战争案例</option></select></label><button className="primary" disabled={!topic.trim()} onClick={create}><Play size={16}/>创建并启动</button></section>}<section className="table"><div className="tablehead"><span>主题</span><span>路线</span><span>状态</span><span>Agent</span><span>轮次</span><span>操作</span></div>{runs.length===0?<div className="empty">暂无研究任务</div>:runs.map(run=><div className="row" key={run.run_id}><span>{run.topic}</span><span>{routeLabel(run.research_route)}</span><span><i className={`status ${run.status}`}/>{statusLabel(run.status)}</span><span>{run.selected_agent_ids.length || '默认'}</span><span>{run.max_rounds}</span><span><button title="查看"><Eye size={16}/></button></span></div>)}</section></main></div>}
function routeLabel(v){return {new_winning_mechanism:'新制胜机理',traditional_gap:'传统能力缺口',war_case_learning:'局部战争案例',auto:'自动'}[v]||v} function statusLabel(v){return {queued:'已排队',draft:'草稿'}[v]||v}
createRoot(document.getElementById('root')).render(<App/>);
