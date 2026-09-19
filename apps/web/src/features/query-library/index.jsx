import React, {useEffect, useMemo, useState} from 'react';
import {
  Archive,
  ArrowLeft,
  BookOpenCheck,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Database,
  ExternalLink,
  Eye,
  EyeOff,
  FilePlus2,
  Link2,
  Lightbulb,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  WandSparkles,
  X,
} from 'lucide-react';
import './styles.css';
import './embedded.css';
import './navigation.css';
import {autonomousDiscoveryTopic, selectAutonomousDiscoveryAngle} from './autonomous-discovery.mjs';

const STATUS_LABELS = {draft: '待审核', published: '已发布', archived: '已归档'};
const SOURCE_LABELS = {agent: 'Agent 生成', manual: '人工录入', import: '资料导入'};
const displaySourceTitle = title => String(title || '').replace(/^本地语义生成\s*[:：]?\s*/, '态势研判：');
const formatDateTime = value => {
  if (!value) return '时间未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}).format(date);
};
const STAGE_LABELS = {
  queued: '等待生成 Worker',
  web_validation: '联网校验公开线索',
  query_generation: '多维发散生成需求选题',
  persisting: '质量门控与原子入库',
  completed: '生成完成',
  failed: '生成失败',
  cancelled: '已终止',
};
const DIVERGENCE_EXAMPLES = [
  {label: '天基赋能地面导弹', topic: '天基平台与地面导弹平台协同赋能运用', angle: '以天基与地面导弹平台相互赋能为主线，牵引双方装备和体系发展。', demand: '分析当前与未来协同态势、主要协同方式、作战效能提升，以及地面作战中可由天基能力解决的单装与体系痛点。', technology: '分析天基资源能力与规划、天地通信技术途径和水平、天基能力向地面装备映射，以及融合后对导弹能力建设方向的影响。'},
  {label: '海上无人导弹融合', topic: '海上无人平台与导弹融合的新型作战模式', angle: '探索面向远海任务的无人平台与导弹或导弹投送融合模式，牵引无人装备与作战体系发展。', demand: '分析主要海上作战场景、对手装备与威胁形式、侦控抗打等应对模式，以及远海作战难点痛点。', technology: '分析海上无人装备与远海应用技术的发展现状和趋势，识别能够解决关键难点的装备技术组合。'},
  {label: '社会化资源引战', topic: '社会化资源引入作战与国防工业体系发展', angle: '从现代战争形态变化出发，研究社会化力量和资源进入作战体系的新模式。', demand: '总结现代战争对国防工业体系的冲击、社会化资源参战案例与价值，研判未来模式及其可解决的能力痛点。', technology: '分析装备、信息科学、人工智能及其他工业技术如何赋能作战，并拓展认知与心理等非动能维度。'},
];
const parseReferenceUrls = value => [...new Set(value.split(/[\s,，]+/).map(item => item.trim()).filter(Boolean))];

function validateReferenceUrls(urls) {
  if (urls.length > 12) return '最多可添加 12 个参考 URL。';
  for (const value of urls) {
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) throw new Error();
    } catch (_reason) {
      return `参考地址格式不正确：${value}。请使用不含账号密码的公开 HTTPS URL。`;
    }
  }
  return '';
}

function QueryLibraryPage({apiBase, onUseQuery, onDirectResearch, onBatchResearchStarted, onBack, embedded = false}) {
  const [queries, setQueries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [sourceType, setSourceType] = useState('all');
  const [selectedId, setSelectedId] = useState('');
  const [selectedQueryIds, setSelectedQueryIds] = useState([]);
  const [topic, setTopic] = useState('');
  const [generationMode, setGenerationMode] = useState('guided');
  const [supplement, setSupplement] = useState('');
  const [expectedAngle, setExpectedAngle] = useState('');
  const [demandDimension, setDemandDimension] = useState('');
  const [technologyDimension, setTechnologyDimension] = useState('');
  const [generationCount, setGenerationCount] = useState(8);
  const [modelOptions, setModelOptions] = useState({providers: [], default_provider: 'codex', reasoning_efforts: ['low', 'medium', 'high', 'xhigh']});
  const [modelProvider, setModelProvider] = useState('codex');
  const [reasoningEffort, setReasoningEffort] = useState('high');
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [customBaseUrl, setCustomBaseUrl] = useState('');
  const [customApiKey, setCustomApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [referenceOpen, setReferenceOpen] = useState(false);
  const [referenceText, setReferenceText] = useState('https://www.81.cn/');
  const [generationTasks, setGenerationTasks] = useState([]);
  const [deletingGenerationId, setDeletingGenerationId] = useState('');
  const [cancellingGenerationId, setCancellingGenerationId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);

  const request = async (path, options = {}) => {
    const {headers = {}, ...rest} = options;
    const response = await fetch(`${apiBase}${path}`, {
      ...rest,
      headers: {'X-Role': 'analyst', ...headers},
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`);
    return payload;
  };

  const load = async (preferredId = '') => {
    try {
      const payload = await request('/query-library/queries?limit=200');
      const rows = payload.items || [];
      setQueries(rows);
      setSelectedId(current => {
        const target = preferredId || current;
        return rows.some(item => item.query_id === target) ? target : rows[0]?.query_id || '';
      });
      setError('');
    } catch (reason) {
      setError(reason.message || 'Query 库读取失败');
    } finally {
      setLoading(false);
    }
  };

  const loadGenerationTasks = async () => {
    try {
      const payload = await request('/query-library/generations?limit=12');
      setGenerationTasks(payload.items || []);
    } catch (reason) {
      setError(reason.message || '生成任务读取失败');
    }
  };

  useEffect(() => {
    void load();
    void loadGenerationTasks();
    request('/query-library/model-options').then(value => {
      setModelOptions(value);
      setModelProvider(value.default_provider || value.providers?.[0]?.id || 'codex');
    }).catch(() => {});
  }, []);
  useEffect(() => {
    const activeTasks = generationTasks.filter(item => ['queued', 'running'].includes(item.status));
    if (!activeTasks.length) return undefined;
    const timer = setInterval(async () => {
      try {
        const values = await Promise.all(activeTasks.map(item => request(`/query-library/generations/${item.generation_id}`)));
        let completedId = '';
        setGenerationTasks(current => {
          const updates = new Map(values.map(item => [item.generation_id, item]));
          const merged = current.map(item => updates.get(item.generation_id) || item);
          values.forEach(item => {
            if (item.status === 'completed' && current.find(previous => previous.generation_id === item.generation_id)?.status !== 'completed') completedId = item.result_query_ids?.[0] || '';
          });
          return merged;
        });
        if (completedId) {
          await load(completedId);
          setStatus('draft');
          setSourceType('agent');
        }
      } catch (reason) {
        setError(reason.message || '生成状态读取失败');
      }
    }, 1600);
    return () => clearInterval(timer);
  }, [generationTasks.map(item => `${item.generation_id}:${item.status}`).join('|')]);

  const visible = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return queries.filter(item => (
      (status === 'all' ? item.status !== 'archived' : item.status === status)
      && (sourceType === 'all' || item.source_type === sourceType)
      && (!keyword || `${item.query} ${item.supplemental_information} ${item.generation_rationale}`.toLowerCase().includes(keyword))
    ));
  }, [queries, search, status, sourceType]);
  const selected = queries.find(item => item.query_id === selectedId) || null;
  const selectedItems = queries.filter(item => selectedQueryIds.includes(item.query_id));
  const counts = useMemo(() => ({
    total: queries.filter(item => item.status !== 'archived').length,
    draft: queries.filter(item => item.status === 'draft').length,
    published: queries.filter(item => item.status === 'published').length,
    agent: queries.filter(item => item.source_type === 'agent' && item.status !== 'archived').length,
  }), [queries]);
  const referenceUrls = useMemo(() => parseReferenceUrls(referenceText), [referenceText]);
  const environmentDefaults = modelOptions.environment_defaults || {};
  const environmentApiKeyLabel = environmentDefaults.api_key_source || 'EQUIPMENT_DR_API_KEY';
  const environmentBaseUrlLabel = environmentDefaults.base_url_source || 'EQUIPMENT_DR_BASE_URL';

  const generate = async () => {
    if (generationMode === 'guided' && !topic.trim()) { setError('请先输入希望发散思考的装备需求母题。'); return; }
    const referenceError = validateReferenceUrls(referenceUrls);
    if (referenceError) { setError(referenceError); setReferenceOpen(true); return; }
    setSubmitting(true); setError('');
    try {
      const autonomousAngle = generationMode === 'autonomous' ? selectAutonomousDiscoveryAngle(generationTasks) : null;
      const generationTopic = autonomousAngle ? autonomousDiscoveryTopic(autonomousAngle) : topic.trim();
      const generationContext = generationMode === 'autonomous'
        ? `自动态势发散模式。\n本次轮换视角：${autonomousAngle.label}。\n${supplement.trim() ? `用户补充偏好：${supplement.trim()}` : '优先检索该视角下最新、权威的公开态势信号。'}\n因果链：外部态势→任务压力→作战缺口→武器装备能力与发展需求。\n发散框架：同时覆盖需求牵引、技术驱动、体系实战、颠覆逻辑与规模建设。`
        : [
            expectedAngle.trim() && `预期角度：${expectedAngle.trim()}`,
            demandDimension.trim() && `需求牵引维度：${demandDimension.trim()}`,
            technologyDimension.trim() && `技术驱动维度：${technologyDimension.trim()}`,
            supplement.trim() && `其他发散偏好：${supplement.trim()}`,
          ].filter(Boolean).join('\n');
      const modelConfig = {
        provider: modelProvider,
        model: '',
        reasoning_effort: reasoningEffort,
        base_url: customBaseUrl.trim(),
        api_key: customApiKey.trim(),
      };
      const value = await request('/query-library/generations', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID()},
        body: JSON.stringify({
          topic: generationTopic,
          supplemental_information: generationContext,
          reference_urls: referenceUrls,
          count: generationCount,
          model_config: modelConfig,
        }),
      });
      setGenerationTasks(current => [value, ...current.filter(item => item.generation_id !== value.generation_id)].slice(0, 12));
    } catch (reason) {
      setError(reason.message || '生成任务提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const publish = async item => {
    setMutating(true); setError('');
    try {
      const value = await request(`/query-library/queries/${item.query_id}/publish`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({expected_version: item.version}),
      });
      await load(value.query_id);
      return value;
    } catch (reason) {
      setError(reason.message || '发布失败，请刷新后重试');
      return null;
    } finally {
      setMutating(false);
    }
  };

  const toggleQuerySelection = item => {
    setSelectedQueryIds(current => current.includes(item.query_id)
      ? current.filter(id => id !== item.query_id)
      : [...current, item.query_id]);
  };

  const publishSelected = async () => {
    const drafts = selectedItems.filter(item => item.status === 'draft');
    if (!drafts.length) return;
    if (!window.confirm(`确定审核发布选中的 ${drafts.length} 条待审核 Query 吗？`)) return;
    setMutating(true); setError('');
    try {
      await request('/query-library/queries/bulk-status', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query_ids: drafts.map(item => item.query_id), status: 'published', versions: Object.fromEntries(drafts.map(item => [item.query_id, item.version]))}),
      });
      setSelectedQueryIds([]);
      await load();
    } catch (reason) {
      setError(reason.message || '批量审核发布失败');
    } finally { setMutating(false); }
  };

  const startSelectedResearch = async () => {
    const targets = selectedItems.filter(item => item.status !== 'archived');
    if (!targets.length) return;
    if (!window.confirm(`将为选中的 ${targets.length} 条 Query 分别创建并启动研究任务，确认继续吗？`)) return;
    setMutating(true); setError('');
    let publishedById = new Map();
    const batchRequestId = crypto.randomUUID();
    const drafts = targets.filter(item => item.status === 'draft');
    try {
      if (drafts.length) {
        const published = await request('/query-library/queries/bulk-status', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({query_ids: drafts.map(item => item.query_id), status: 'published', versions: Object.fromEntries(drafts.map(item => [item.query_id, item.version]))}),
        });
        publishedById = new Map((published.items || []).map(item => [item.query_id, item]));
      }
    } catch (reason) {
      setMutating(false); setError(reason.message || '批量审核发布失败，未启动研究任务'); return;
    }
    const results = await Promise.all(targets.map(async item => {
      try {
        const current = publishedById.get(item.query_id) || item;
        const body = {
          topic: current.query,
          supplemental_information: current.supplemental_information || '',
          research_route: 'auto', interaction_mode: 'expert', discovery_branch: 'auto',
          execution_profile_id: 'winning_swarm_dynamic_v2', max_rounds: 2,
          selected_agent_ids: [], analyst_confirmed: true,
          source_query_id: current.query_id, source_query_version: current.version,
        };
        const created = await request('/runs', {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': `query-batch:${batchRequestId}:${current.query_id}`}, body: JSON.stringify(body)});
        await request(`/runs/${encodeURIComponent(String(created.run_id || '').trim())}/start`, {method: 'POST', headers: {'Idempotency-Key': `query-batch-start:${batchRequestId}:${created.run_id}`}});
        return {ok: true};
      } catch (reason) { return {ok: false, error: reason.message || '启动失败'}; }
    }));
    setMutating(false);
    const failed = results.filter(item => !item.ok).length;
    if (failed) setError(`${results.length - failed} 条已创建并启动，${failed} 条启动失败，请检查研究 Worker 状态。`);
    else { setError(''); onBatchResearchStarted?.(results.length); onBack?.(); }
    setSelectedQueryIds([]);
    await load();
  };

  const deleteSelectedQueries = async () => {
    const targets = [...selectedItems];
    if (!targets.length || !window.confirm(`确定永久删除选中的 ${targets.length} 条 Query 吗？删除后不可恢复，但不会删除已创建的研究任务。`)) return;
    setMutating(true); setError('');
    const results = await Promise.allSettled(targets.map(item => request(`/query-library/queries/${item.query_id}`, {method: 'DELETE'})));
    const failed = results.filter(item => item.status === 'rejected').length;
    setSelectedQueryIds([]);
    await Promise.all([load(), loadGenerationTasks()]);
    if (failed) setError(`${targets.length - failed} 条已删除，${failed} 条删除失败。`);
    setMutating(false);
  };

  const deleteQuery = async item => {
    if (!window.confirm(`确定永久删除 Query“${item.query}”吗？删除后不可恢复，但不会删除已创建的研究任务。`)) return;
    setMutating(true); setError('');
    try {
      await request(`/query-library/queries/${item.query_id}`, {method: 'DELETE'});
      setSelectedQueryIds(current => current.filter(id => id !== item.query_id));
      await Promise.all([load(), loadGenerationTasks()]);
    } catch (reason) {
      setError(reason.message || 'Query 删除失败');
    } finally { setMutating(false); }
  };

  const deleteGenerationTask = async item => {
    if (['queued', 'running'].includes(item.status)) return;
    if (!window.confirm('删除这条 Query 发散任务记录及其专属本地运行文件？已经入库的 Query 草稿会继续保留。')) return;
    setDeletingGenerationId(item.generation_id); setError('');
    try {
      await request(`/query-library/generations/${item.generation_id}`, {method: 'DELETE'});
      setGenerationTasks(current => current.filter(task => task.generation_id !== item.generation_id));
    } catch (reason) {
      setError(reason.message || '任务记录或本地文件删除失败');
    } finally {
      setDeletingGenerationId('');
    }
  };

  const cancelGenerationTask = async item => {
    if (!['queued', 'running'].includes(item.status)) return;
    if (!window.confirm('确定终止这个 Query 发散任务吗？Worker 会在安全检查点停止当前生成，已产生但尚未入库的内容不会保存。')) return;
    setCancellingGenerationId(item.generation_id); setError('');
    try {
      const value = await request(`/query-library/generations/${item.generation_id}/cancel`, {method: 'POST'});
      setGenerationTasks(current => current.map(task => task.generation_id === value.generation_id ? value : task));
    } catch (reason) {
      setError(reason.message || '任务终止失败');
    } finally {
      setCancellingGenerationId('');
    }
  };

  const archiveQuery = async item => {
    if (!window.confirm('归档后该 Query 将不再出现在研究任务选择器中，历史版本仍会保留。')) return;
    setMutating(true); setError('');
    try {
      await request(`/query-library/queries/${item.query_id}/archive`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({expected_version: item.version}),
      });
      await load();
    } catch (reason) {
      setError(reason.message || '归档失败');
    } finally {
      setMutating(false);
    }
  };

  const useForResearch = async item => {
    const published = item.status === 'published' ? item : await publish(item);
    if (published) onUseQuery?.(published);
  };

  return <div className={`query-library-page ${embedded ? 'embedded' : ''}`}>
    {onBack && <div className="query-library-backbar"><button onClick={onBack}><ArrowLeft size={15}/>返回研究任务</button><span>可围绕母题深度发散，也可让 Agent 自主发现方向；审核后带入 Deep Research。</span></div>}
    <section className="query-generator-hero">
      <div className="query-hero-orb"><WandSparkles size={22}/></div>
      <span className="query-hero-eyebrow">DEMAND DISCOVERY AGENT</span>
      <h1>多维发散思考，发现装备需求 Query</h1>
      <p>可输入选题角度、场景描述或文档材料，也可由 Agent 结合公开态势自主发现方向；从需求牵引、技术驱动、体系实战和颠覆逻辑等维度形成简洁研究选题。</p>
      <div className="query-generation-mode-tabs" aria-label="Query 生成模式">
        <button className={generationMode === 'guided' ? 'active' : ''} onClick={() => setGenerationMode('guided')}><Lightbulb size={15}/><span><b>围绕母题发散</b><small>输入一个方向，向多维度深挖</small></span></button>
        <button className={generationMode === 'autonomous' ? 'active' : ''} onClick={() => { setGenerationMode('autonomous'); setModelProvider('codex'); }}><Sparkles size={15}/><span><b>自动态势发散</b><small>无需母题，Agent 自主发现研究方向</small></span></button>
      </div>
      <div className="query-generator-card">
        {generationMode === 'guided' ? <><label>需求母题 / 发散材料</label><textarea value={topic} onChange={event => setTopic(event.target.value)} placeholder="例如：输入‘复杂电磁环境下精确打击装备能力需求’，Agent 将围绕场景、任务、技术、体系和颠覆方向发散生成多条短 Query。" maxLength={500}/></> : <div className="query-autonomous-context"><Sparkles size={23}/><span><b>快速研判中国周边态势并发现装备发展方向</b><p>聚焦邻国、周边海域、岛链与边境任务环境，检索最新公开信号，再按“外部态势→任务压力→作战缺口→装备需求”快速转译为研究 Query。</p><em>无人、低空反制、颠覆性远打和精打武器是高关注方向，但不设封闭目录或固定配额；由模型根据本次态势因果链自主发现更多高价值武器装备需求。</em></span></div>}
        {generationMode === 'guided' && <div className="query-divergence-framework">
          <div className="query-framework-heading"><span><Sparkles size={15}/><b>多维发散框架</b><small>先明确研究意图，再由 Agent 深度发散，避免只做同义改写</small></span><div>{DIVERGENCE_EXAMPLES.map(example => <button key={example.label} onClick={() => {setTopic(example.topic); setExpectedAngle(example.angle); setDemandDimension(example.demand); setTechnologyDimension(example.technology);}}>{example.label}</button>)}</div></div>
          <label><span><b>预期角度</b><small>希望牵引什么发展</small></span><textarea value={expectedAngle} onChange={event => setExpectedAngle(event.target.value)} placeholder="例如：以天基与地面导弹平台相互赋能为主线，牵引双方装备与体系发展。"/></label>
          <label><span><b>需求牵引维度</b><small>场景、威胁、手段与痛点</small></span><textarea value={demandDimension} onChange={event => setDemandDimension(event.target.value)} placeholder="当前与未来任务场景是什么？对手能力和威胁形式是什么？现有手段有哪些？单装与体系还存在哪些缺口？"/></label>
          <label><span><b>技术驱动维度</b><small>现状、规划与能力映射</small></span><textarea value={technologyDimension} onChange={event => setTechnologyDimension(event.target.value)} placeholder="相关资源和技术能力达到什么水平？成熟度与路线图如何？哪些技术可映射为装备能力并改变发展方向？"/></label>
          <label><span><b>其他发散偏好</b><small>体系、颠覆与规模建设</small></span><textarea id="query-generation-context" value={supplement} onChange={event => setSupplement(event.target.value)} placeholder="可限定作战环境、时间范围，并指定体系韧性、颠覆逻辑、工业化或需要排除的角度。" maxLength={8000}/></label>
        </div>}
        {generationMode === 'autonomous' && <textarea id="query-generation-context" className="query-generation-context autonomous" value={supplement} onChange={event => setSupplement(event.target.value)} placeholder="自主发现偏好（可选）：希望重点关注的装备领域、区域态势、技术方向或时间范围。" maxLength={8000}/>} 
        <div className="query-agent-config">
          <div className="query-count-control"><span><b>生成数量</b><small>按本次需要灵活选择</small></span><div>{[4, 6, 8, 12, 16, 20].map(value => <button className={generationCount === value ? 'active' : ''} key={value} onClick={() => setGenerationCount(value)}>{value}</button>)}</div></div>
          <label><span>Agent</span><select value={modelProvider} onChange={event => setModelProvider(event.target.value)}>{modelOptions.providers?.map(item => <option key={item.id} value={item.id}>{item.id === 'codex' ? '智能体' : item.label}</option>)}</select></label>
          <label><span>思考强度</span><select value={reasoningEffort} onChange={event => setReasoningEffort(event.target.value)}>{(modelOptions.reasoning_efforts || []).map(value => <option key={value} value={value}>{({low: '快速', medium: '均衡', high: '深度', xhigh: '极深'})[value] || value}</option>)}</select></label>
          <button className={`query-connection-toggle ${connectionOpen || customBaseUrl || customApiKey ? 'active' : ''}`} onClick={() => setConnectionOpen(value => !value)}><ShieldCheck size={15}/><span><b>连接设置</b><small>{customApiKey ? '本次密钥已填写' : environmentDefaults.api_key_configured ? '项目环境已配置' : 'URL / API Key'}</small></span></button>
        </div>
        {connectionOpen && <div className="query-provider-connection">
          <label><span><b>API URL</b><small>默认：{environmentBaseUrlLabel}</small></span><input type="url" value={customBaseUrl} onChange={event => setCustomBaseUrl(event.target.value)} placeholder={`留空使用 ${environmentBaseUrlLabel}`} spellCheck={false}/></label>
          <label><span><b>API Key</b><small>{environmentDefaults.api_key_configured ? `已从 ${environmentApiKeyLabel} 配置` : `默认读取 ${environmentApiKeyLabel}`}</small></span><div className="query-api-key-input"><input type={showApiKey ? 'text' : 'password'} value={customApiKey} onChange={event => setCustomApiKey(event.target.value)} placeholder={`留空使用 ${environmentApiKeyLabel}`} autoComplete="new-password" spellCheck={false}/><button type="button" aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'} onClick={() => setShowApiKey(value => !value)}>{showApiKey ? <EyeOff size={15}/> : <Eye size={15}/>}</button></div></label>
          <p><ShieldCheck size={13}/>优先使用本次填写；其次使用 Query 模块专用变量；最后回退到项目通用 EQUIPMENT_DR_BASE_URL / EQUIPMENT_DR_API_KEY。环境密钥不会回显。</p>
        </div>}
        <div className="query-generator-footer">
          <button className={`query-context-toggle ${referenceUrls.length ? 'active' : ''}`} onClick={() => setReferenceOpen(value => !value)}><Link2 size={14}/>参考 URL{referenceUrls.length ? ` · ${referenceUrls.length}` : ''}</button>
          <span>输出 {generationCount} 条 18–25 字短 Query · 详细维度、理由与来源独立保存</span>
          <button className="query-generate-button" disabled={submitting || (generationMode === 'guided' && !topic.trim())} onClick={generate}>{submitting ? <LoaderCircle className="spin" size={16}/> : <Send size={16}/>} {generationMode === 'autonomous' ? '自动发散生成 Query' : '发散生成 Query'}</button>
        </div>
      </div>
      {referenceOpen && <section className="query-reference-url-panel">
        <header><div><Link2 size={17}/><span><b>优先参考 URL</b><small>Agent 将先阅读这些公开网页，再结合联网检索补充军事信息线索</small></span></div><em>{referenceUrls.length}/12</em></header>
        <textarea value={referenceText} onChange={event => setReferenceText(event.target.value)} placeholder={'每行输入一个公开 HTTPS 地址，例如：\nhttps://www.example.gov.cn/equipment-planning\nhttps://www.example.org/research-report'} spellCheck={false}/>
        <footer><span>系统会自动去重，并移除 token、api_key 等敏感查询参数；URL 仅作为 Query 生成线索。</span>{referenceText && <button onClick={() => setReferenceText('')}><X size={13}/>清空</button>}</footer>
      </section>}
      <div className="query-decomposition-guide">
        {generationMode === 'guided'
          ? <article><span>1</span><div><b>输入母题</b><small>可以是一句话，也可以是文档中的长段落</small></div></article>
          : <article><span>1</span><div><b>研判公开态势</b><small>从安全环境、任务与技术信号中自主发现方向</small></div></article>}
        <article><span>2</span><div><b>多维深度发散</b><small>从需求、技术、体系和颠覆角度寻找研究机会</small></div></article>
        <article><span>3</span><div><b>形成短选题</b><small>标题保持简洁，详细研究维度单独保存</small></div></article>
      </div>
      <GenerationTaskSlots generations={generationTasks}/>
      <GenerationTaskList generations={generationTasks} libraryQueries={queries} refresh={() => void loadGenerationTasks()} remove={deleteGenerationTask} cancel={cancelGenerationTask} deletingId={deletingGenerationId} cancellingId={cancellingGenerationId} selectQuery={queryId => { setSelectedId(queryId); window.scrollTo({top: document.querySelector('.query-library-shell')?.offsetTop || 0, behavior: 'smooth'}); }} publishQuery={publish} researchQuery={useForResearch} deleteQuery={deleteQuery}/>
    </section>

    {error && <div className="query-error"><CircleAlert size={16}/>{error}<button onClick={() => setError('')}><X size={14}/></button></div>}

    <section className="query-library-heading">
      <div><span>QUERY LIBRARY</span><h2>装备需求短 Query 库</h2><p>卡片只展示短选题；研究维度、形成理由和来源依据在详情中保留。</p></div>
      <div><button onClick={() => setManualOpen(value => !value)}><FilePlus2 size={15}/>人工录入</button><button onClick={() => { void load(); void loadGenerationTasks(); }}><RefreshCw size={15}/>刷新</button></div>
    </section>

    {manualOpen && <ManualQueryForm request={request} close={() => setManualOpen(false)} saved={item => { setManualOpen(false); void load(item.query_id); }}/>} 

    <section className="query-metrics">
      <Metric icon={Database} label="当前 Query" value={counts.total}/>
      <Metric icon={Clock3} label="待审核" value={counts.draft}/>
      <Metric icon={BookOpenCheck} label="已发布" value={counts.published}/>
      <Metric icon={Sparkles} label="Agent 生成" value={counts.agent}/>
    </section>

    <section className="query-library-shell">
      <div className="query-list-column">
        <div className="query-library-toolbar">
          <label><Search size={15}/><input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索 Query、理由或研究角度"/></label>
          <select value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option><option value="draft">待审核</option><option value="published">已发布</option><option value="archived">已归档</option></select>
          <select value={sourceType} onChange={event => setSourceType(event.target.value)}><option value="all">全部来源</option><option value="agent">Agent 生成</option><option value="manual">人工录入</option><option value="import">资料导入</option></select>
          <span>{visible.length} 条</span>
        </div>
        <div className="query-bulk-toolbar">
          <label><input type="checkbox" aria-label="选择当前筛选结果" checked={visible.length > 0 && visible.every(item => selectedQueryIds.includes(item.query_id))} onChange={event => setSelectedQueryIds(event.target.checked ? [...new Set([...selectedQueryIds, ...visible.map(item => item.query_id)])] : selectedQueryIds.filter(id => !visible.some(item => item.query_id === id)))} /><span>选择当前结果</span></label>
          {selectedQueryIds.length > 0 && <><span className="query-bulk-count">已选 {selectedQueryIds.length} 条</span><button disabled={mutating || !selectedItems.some(item => item.status === 'draft')} onClick={publishSelected}><BookOpenCheck size={14}/>批量审核发布</button><button className="primary" disabled={mutating || !selectedItems.some(item => item.status !== 'archived')} onClick={startSelectedResearch}><Play size={14}/>批量启动研究</button><button className="danger" disabled={mutating} onClick={deleteSelectedQueries}><Trash2 size={14}/>批量删除</button><button disabled={mutating} onClick={() => setSelectedQueryIds([])}><X size={14}/>清除</button></>}
        </div>
        {loading ? <div className="query-empty"><LoaderCircle className="spin"/>正在读取 Query 库</div> : visible.length ? <div className="query-card-grid">{visible.map(item => <QueryCard key={item.query_id} item={item} selected={item.query_id === selectedId} checked={selectedQueryIds.includes(item.query_id)} toggle={() => toggleQuerySelection(item)} choose={() => setSelectedId(item.query_id)}/>)}</div> : <div className="query-empty"><Search/>没有匹配的 Query</div>}
      </div>
      <QueryDetail item={selected} mutating={mutating} publish={publish} archiveQuery={archiveQuery} deleteQuery={deleteQuery} useForResearch={useForResearch}/>
    </section>
  </div>;
}

function GenerationTaskSlots({generations}) {
  const active = generations.filter(item => ['queued', 'running'].includes(item.status));
  return <section className="query-generation-task-slots" aria-live="polite">
    <header>
      <div><Sparkles size={16}/><span><b>Query 发散执行槽位</b><small>独立于研究任务并行槽位，仅显示正在执行的 Query 任务</small></span></div>
      <em>{active.length} 个进行中</em>
    </header>
    {active.length ? <div className="query-generation-task-grid">{active.map(item => <GenerationTaskCard key={item.generation_id} generation={item}/>)}</div> : <div className="query-generation-task-empty"><Clock3 size={15}/>当前没有正在执行的 Query 任务。</div>}
  </section>;
}

function GenerationTaskList({generations, libraryQueries, refresh, remove, cancel, deletingId, cancellingId, selectQuery, publishQuery, researchQuery, deleteQuery}) {
  const [taskFilter, setTaskFilter] = useState('all');
  const [taskSearch, setTaskSearch] = useState('');
  const [collapsedIds, setCollapsedIds] = useState(() => new Set());
  const counts = {
    all: generations.length,
    running: generations.filter(item => ['queued', 'running'].includes(item.status)).length,
    completed: generations.filter(item => item.status === 'completed').length,
  };
  const keyword = taskSearch.trim().toLowerCase();
  const visibleTasks = generations.filter(item => (
    (taskFilter === 'all'
      || (taskFilter === 'running' && ['queued', 'running'].includes(item.status))
      || item.status === taskFilter)
    && (!keyword || `${item.topic} ${item.generation_id} ${item.stage}`.toLowerCase().includes(keyword))
  ));
  const queryById = useMemo(() => new Map(libraryQueries.map(item => [item.query_id, item])), [libraryQueries]);
  const toggleTask = item => {
    setCollapsedIds(current => {
      const next = new Set(current);
      if (next.has(item.generation_id)) next.delete(item.generation_id);
      else next.add(item.generation_id);
      return next;
    });
  };
  return <section className="query-generation-task-list">
    <header className="query-task-list-tabs">
      <div>
        <button className={taskFilter === 'all' ? 'active' : ''} onClick={() => setTaskFilter('all')}><Archive size={15}/>全部 <em>{counts.all}</em></button>
        <button className={taskFilter === 'running' ? 'active' : ''} onClick={() => setTaskFilter('running')}><Clock3 size={15}/>进行中 <em>{counts.running}</em></button>
        <button className={taskFilter === 'completed' ? 'active' : ''} onClick={() => setTaskFilter('completed')}><CheckCircle2 size={15}/>已完成 <em>{counts.completed}</em></button>
      </div>
      <button className="query-task-list-refresh" onClick={refresh}><RefreshCw size={15}/>刷新</button>
    </header>
    <div className="query-task-list-note"><Sparkles size={15}/><b>实时</b><span>Query 发散任务持续沉淀生成状态、产出数量与可追溯的执行时间；删除任务会同步清理专属本地文件。</span></div>
    <div className="query-task-list-toolbar"><label><Search size={16}/><input value={taskSearch} onChange={event => setTaskSearch(event.target.value)} placeholder="搜索发散主题或任务 ID"/></label><span>{visibleTasks.length} 项结果</span></div>
    {visibleTasks.length ? <div className="query-generation-task-list-grid">{visibleTasks.map(item => <GenerationTaskListRow key={item.generation_id} generation={item} expanded={!collapsedIds.has(item.generation_id)} queries={(item.result_query_ids || []).map(queryId => queryById.get(queryId)).filter(Boolean)} toggle={() => toggleTask(item)} remove={remove} cancel={cancel} deleting={deletingId === item.generation_id} cancelling={cancellingId === item.generation_id} selectQuery={selectQuery} publishQuery={publishQuery} researchQuery={researchQuery} deleteQuery={deleteQuery}/>)}</div> : <div className="query-generation-task-empty"><Search size={15}/>没有匹配的 Query 发散任务。</div>}
  </section>;
}

function GenerationTaskListRow({generation, expanded, queries, toggle, remove, cancel, deleting, cancelling, selectQuery, publishQuery, researchQuery, deleteQuery}) {
  const running = ['queued', 'running'].includes(generation.status);
  const completed = generation.status === 'completed';
  const cancelled = generation.status === 'cancelled';
  const resultCount = generation.result_query_ids?.length || 0;
  const handleKeyDown = event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggle();
    }
  };
  return <article className={`query-generation-task-list-row ${generation.status} ${expanded ? 'expanded' : ''}`} role="button" tabIndex={0} aria-expanded={expanded} onClick={toggle} onKeyDown={handleKeyDown}>
    <header><span className="query-generation-task-list-check"><ChevronDown size={12}/></span><b>{generation.topic}</b><em>{running ? <LoaderCircle className="spin" size={12}/> : completed ? <CheckCircle2 size={12}/> : cancelled ? <X size={12}/> : <CircleAlert size={12}/>} {running ? '进行中' : completed ? '已完成' : cancelled ? '已终止' : '失败'}</em></header>
    <p>{generation.supplemental_information || '由 Agent 结合公开态势与输入偏好，多维发散形成装备需求 Query。'}</p>
    <div className="query-generation-task-list-metrics"><span><strong>{generation.requested_count}</strong> 目标</span><span><strong>{resultCount}</strong> 草稿</span><span><strong>{generation.source_references?.length || 0}</strong> 来源</span></div>
    <div className="query-generation-task-list-meta"><span>{STAGE_LABELS[generation.stage] || generation.stage}</span><time dateTime={generation.created_at}>创建于 {formatDateTime(generation.created_at)}</time></div>
    <footer><span><i/>真实运行</span>{running ? <button className="query-generation-task-stop" title="终止当前生成任务" disabled={cancelling} onClick={event => { event.stopPropagation(); cancel(generation); }}>{cancelling ? <LoaderCircle className="spin" size={13}/> : <X size={13}/>}</button> : <button title="删除任务记录" disabled={deleting} onClick={event => { event.stopPropagation(); remove(generation); }}>{deleting ? <LoaderCircle className="spin" size={13}/> : <Trash2 size={13}/>}</button>}</footer>
    {expanded && <section className="query-generation-task-results" onClick={event => event.stopPropagation()}>
      <header><span><Sparkles size={14}/><b>本次生成的 Query</b></span><em>{resultCount} 条</em></header>
      {queries.length ? <ol>{queries.map(item => <li key={item.query_id}><button className="query-result-title" onClick={() => selectQuery?.(item.query_id)}><span>{item.query}</span><small>{STATUS_LABELS[item.status] || item.status}</small></button><div className="query-result-actions"><button title="查看详情" onClick={() => selectQuery?.(item.query_id)}><Eye size={12}/></button>{item.status === 'draft' && <button title="审核发布" onClick={() => publishQuery?.(item)}><BookOpenCheck size={12}/></button>}<button title="新建研究任务" onClick={() => researchQuery?.(item)}><Play size={12}/></button><button title="删除 Query" onClick={() => deleteQuery?.(item)}><Trash2 size={12}/></button></div></li>)}</ol>
        : <div className="query-generation-task-results-state"><Clock3 size={15}/>{running ? 'Query 正在生成，完成后可在这里查看。' : resultCount ? '生成结果正在同步到 Query 库。' : '这个任务没有保存 Query 结果。'}</div>}
    </section>}
  </article>;
}

function GenerationTaskCard({generation}) {
  const running = ['queued', 'running'].includes(generation.status);
  const completed = generation.status === 'completed';
  return <article className={`query-generation-task ${generation.status}`}>
    <div className="query-generation-task-icon">{running ? <LoaderCircle className="spin" size={15}/> : completed ? <CheckCircle2 size={15}/> : <CircleAlert size={15}/>}</div>
    <div className="query-generation-task-body"><div className="query-generation-task-title"><b>{running ? '正在生成 Query' : completed ? 'Query 生成完成' : 'Query 生成失败'}</b><span>{generation.requested_count} 条</span></div><p title={generation.topic}>{generation.topic}</p><small>{STAGE_LABELS[generation.stage] || generation.stage} · {completed ? `已生成 ${generation.result_query_ids?.length || 0} 条草稿` : generation.status === 'failed' ? generation.error || '请重试任务' : '后台持续执行中'} · 创建于 {formatDateTime(generation.created_at)}</small></div>
  </article>;
}

function QueryCard({item, selected, checked, toggle, choose}) {
  return <article className={`query-library-card ${selected ? 'selected' : ''}`} role="button" tabIndex={0} onClick={choose} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } }} key={item.query_id}>
    <header><label className="query-card-select" onClick={event => event.stopPropagation()}><input type="checkbox" checked={checked} onChange={toggle} aria-label={`选择 ${item.query}`}/><span className={`query-status ${item.status}`}>{STATUS_LABELS[item.status]}</span></label><em>{SOURCE_LABELS[item.source_type]}</em></header>
    <p>{item.query}</p>
    <footer><span><Lightbulb size={12}/>{item.generation_rationale ? '含生成理由' : '理由待补充'}</span><span className="query-card-time" title={item.created_at}><Clock3 size={11}/>{item.source_type === 'agent' ? '生成于 ' : '录入于 '}{formatDateTime(item.created_at)}</span><span>{item.source_references?.length || 0} 个来源</span></footer>
  </article>;
}

function QueryDetail({item, mutating, publish, archiveQuery, deleteQuery, useForResearch}) {
  if (!item) return <aside className="query-detail-panel empty"><Lightbulb/><p>选择一条短 Query，查看它对应的详细研究维度、生成理由和来源依据。</p></aside>;
  return <aside className="query-detail-panel">
    <header><div><span className={`query-status ${item.status}`}>{STATUS_LABELS[item.status]}</span><em>{SOURCE_LABELS[item.source_type]} · v{item.version} · {item.source_type === 'agent' ? '生成于' : '录入于'} {formatDateTime(item.created_at)}</em></div><small>{item.query_id}</small></header>
    <h3>{item.query}</h3>
    <DetailBlock title="研究角度与补充信息" text={item.supplemental_information || '暂无补充信息，可在启动研究前继续编辑。'}/>
    <DetailBlock title="生成理由" text={item.generation_rationale || '该条为人工或资料导入 Query，尚未补充生成理由。'}/>
    <section className="query-source-list"><b>来源依据</b>{item.source_references?.length ? item.source_references.map((source, index) => <article key={`${source.url}-${index}`}><span>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{displaySourceTitle(source.title)}<ExternalLink size={12}/></a> : displaySourceTitle(source.title)}<small>{source.relevance_note || '用于形成 Query 的背景线索'}</small></span></article>) : <p>暂无直接来源，后续研究仍需独立采集与核验正式证据。</p>}<em>{item.source_disclaimer}</em></section>
    <div className="query-detail-actions">{item.status !== 'archived' && <button disabled={mutating} onClick={() => archiveQuery(item)}><Archive size={15}/>归档</button>}<button className="danger" disabled={mutating} onClick={() => deleteQuery(item)}><Trash2 size={15}/>删除</button>{item.status === 'draft' && <button disabled={mutating} onClick={() => publish(item)}><BookOpenCheck size={15}/>审核发布</button>}{item.status !== 'archived' && <button className="primary" disabled={mutating} onClick={() => useForResearch(item)}><Play size={15}/>{item.status === 'draft' ? '发布并新建研究' : '用此 Query 新建研究'}</button>}</div>
  </aside>;
}

function DetailBlock({title, text}) { return <section className="query-detail-block"><b>{title}</b><p>{text}</p></section>; }
function Metric({icon: Icon, label, value}) { return <article><Icon size={18}/><span><small>{label}</small><b>{value}</b></span></article>; }

function ManualQueryForm({request, close, saved}) {
  const [query, setQuery] = useState(''); const [supplement, setSupplement] = useState(''); const [rationale, setRationale] = useState(''); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const submit = async () => { setSaving(true); setError(''); try { saved(await request('/query-library/queries', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({query, supplemental_information: supplement, generation_rationale: rationale})})); } catch (reason) { setError(reason.message || '保存失败'); } finally { setSaving(false); } };
  return <section className="manual-query-form"><header><div><FilePlus2 size={17}/><span><b>人工录入短 Query</b><small>详细研究范围请放在补充信息中</small></span></div><button onClick={close}><X size={15}/></button></header><label>研究选题<textarea value={query} onChange={event => setQuery(event.target.value)} placeholder="例如：卫星拒止条件下多源自主导航精打武器研究"/></label><div><label>详细研究维度与补充信息<textarea value={supplement} onChange={event => setSupplement(event.target.value)}/></label><label>生成/选题理由<textarea value={rationale} onChange={event => setRationale(event.target.value)}/></label></div>{error && <p>{error}</p>}<footer><button onClick={close}>取消</button><button className="primary" disabled={saving || !query.trim()} onClick={submit}>{saving ? '保存中' : '保存草稿'}</button></footer></section>;
}

export default {id: 'query-library', label: '需求 Query', icon: WandSparkles, probePath: '/query-library/health', Component: QueryLibraryPage};
