"""保留不含研究正文、音频或凭据的验收汇总。"""
import json
import math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

root=Path(__file__).resolve().parent
h=json.loads((root/'heavy-summary.json').read_text())
v=json.loads((root/'video-summary.json').read_text())
l=json.loads((root/'light-summary.json').read_text())
a=json.loads((root/'final-audit.json').read_text())
c=json.loads(next(line for line in (root/'final-cleanup-verification.log').read_text().splitlines() if line.startswith('{')))
b=json.loads((root/'health-benchmark.json').read_text())
assert h['research']['status']=='passed' and v['video']['status']=='passed'
assert l['completed']==20 and len(l['native_deep'])==5 and all(row['status']=='completed' for row in l['native_deep'])
assert all(value==0 for value in c['remaining'].values())
assert all(row['accounts_remaining']==0 and not row['cleanup_errors'] for row in [h,v,l])
assert a['readiness']=='ready' and a['api_5xx_during_acceptance']==0
samples=h['budget_samples']
overlap=[row for row in samples if row.get('interactive_running',0)>0 and row.get('research_running',0)>0 and row.get('asr_processes',0)>0]
assert overlap
def p95(values):
    values=sorted(values)
    return values[math.ceil(len(values)*.95)-1]

times=[row['observed_at'] for row in samples if 'observed_at' in row]
summary={
 'time_zone':'Asia/Shanghai','test_start':datetime.fromtimestamp(min(times),ZoneInfo('Asia/Shanghai')).isoformat(),
 'test_end':datetime.fromtimestamp(max(times),ZoneInfo('Asia/Shanghai')).isoformat(),
 'hardware':'4 vCPU / 16 GB','project_containers':a['project_container_count'],
 'research':{key:h['research'][key] for key in ['seconds','report_characters','capability_versions','model_calls','portfolio_fallback_events']},
 'audio':{'duration_seconds':v['video']['audio_seconds'],'baseline_total_seconds':h['video']['seconds'],
  'mixed_total_seconds':v['video']['seconds'],'fixture':'7.588-second public speech fixture repeated 16 times; only WeChat audio handoff simulated',
  'real_steps':['HTTPS upload','ARQ','SenseVoice','punctuation','DOCX','MinIO','Milvus index']},
 'interactive':{'ordinary_users':16,'chat_completed':20,'deep_short_turns_completed':5,'group_seconds':l['elapsed_seconds'],
  'page_probe_count':len(l['page_probes']),'page_p95_ms':p95([row['ms'] for row in l['page_probes']]),
  'all_page_probes_success':all(row['status']==200 for row in l['page_probes'])},
 'mixed_resources':{'budget_sample_count':len(samples),'three_workloads_overlapping_samples':len(overlap),
  'peak_interactive_runs_during_asr_and_research':max(row['interactive_running'] for row in overlap),
  'asr_thread_budgets_during_run':sorted({row['asr_threads'] for row in samples}),
  'minimum_available_gib':round(min(row.get('available_mib',99999) for row in samples)/1024,2),
  'cpu_busy_peak_percent':max(row.get('cpu_busy_percent',0) for row in samples)},
 'health_check_benchmark':b,'api_5xx_during_acceptance':a['api_5xx_during_acceptance'],
 'candidate_tests':{'passed':14,'real_postgres_capacity_cases':6},'cleanup':c,
 'scope':'One complete research with max_rounds=1 plus real cloud ASR and 16-user short conversation load; not 16 simultaneous full long researches or an all-day soak.',
 'measurement_notes':['P95 uses nearest rank ceil(0.95*n).','Report character count includes Markdown formatting.',
  'Capability API returns run_id and versions keys; the initial harness counted 2 keys. Final verified capability count is 6 PostgreSQL rows before deletion.',
  'Deleting a source research preserves capability versions by design; test-owned versions were explicitly deleted and all residual checks passed.']}
(root/'acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
cells=[('完整研究','397.88 秒'),('报告 / 画像','16,292 字符 / 6 份'),('模型调用','86 次成功'),
 ('121 秒测试音频','重叠负载下 52.49 秒'),('16 用户对话','20 普通 + 5 深研全部成功'),('页面探测 P95',f"{summary['interactive']['page_p95_ms']} ms")]
cards=''.join(f'<div><small>{key}</small><b>{value}</b></div>' for key,value in cells)
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>4 核 16 GB · 动态资源与数据清理验收</title><style>body{background:#f3f6fa;color:#203044;font:16px/1.7 system-ui,sans-serif;margin:0}main{max-width:1040px;margin:36px auto;padding:0 24px 50px}h1{font-size:29px;line-height:1.4}h2{font-size:21px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.cards div,section{background:#fff;border:1px solid #dce5ed;border-radius:12px;padding:20px}section{margin:20px 0}small{color:#687888;display:block}b{font-size:22px}table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #e3e9ef;padding:10px;text-align:left}a{color:#146ac8}.ok{color:#176a43}@media(max-width:640px){.cards{grid-template-columns:1fr 1fr}}</style><main>
<p class="ok">2026-10-27 · 已部署 · 本轮云端验收数据已清理</p><h1>4 核 16 GB：动态资源与重任务混合验收</h1>
<p>18 个运行容器均属于该项目。项目可共享主机可用 CPU、内存；业务池以相对 CPU 权重保障交互。后台每 2 秒评估主机余量、交互及研究状态，调整新重任务接纳与 ASR 音频块的线程预算，正在执行的任务持续运行。</p><div class="cards">'''+cards+'''</div>
<h2>测试范围和口径</h2><section><p>一项完整研究（max_rounds=1）真实生成报告，86 次模型调用均完成，组合降级事件为 0。121.403 秒音频经过真实 SenseVoice、标点、Word、MinIO 与 Milvus 索引。音频由 7.588 秒公开语音夹具重复 16 次，微信端音频交接使用夹具；本轮没有替用户登录真实微信。</p>
<p>第一次转录全流程 48.88 秒；第二次在完整研究与 16 用户对话负载重叠时用 52.49 秒。20 个普通对话、5 个新版深研短对话全部完成，整组 19.838 秒。页面 P95 为压力窗口的独立探测结果，采用 nearest-rank，样本量见 JSON。</p>
<p>预算采样记录到三个负载同时存在的 6 个样本，最高同时有 20 个交互 Run、1 个完整研究和 1 个识别进程。ASR 预算在负载中为 1–3 线程；空闲策略可使用 4 线程。主机 CPU 忙碌率峰值 99.9%，最低可用内存约 8.33 GiB；补充主机采样 Swap 为 0。</p></section>
<h2>资源策略与检查</h2><section><p>当资源充足时按已配置上限接纳；其他计算竞争和交互增加时降低新重任务接纳。内存低于 4 GiB 时进一步收敛，低于 2.5 GiB 时暂缓新增研究和通用任务。预算过期采用保守档。CPU 与内存压力边界有自动化测试，未在生产人为制造 OOM。</p>
<p>候选镜像 14 项通过，包含 6 项真实 PostgreSQL 容量测试。Worker 检查直接验证 Redis 租约，替代反复加载完整后端；图数据库执行认证 HTTP 查询，替代 Java 命令行。单次测量：旧 Worker 检查 5.749 秒，新检查连同容器启动 0.776 秒；图检查 2.437 秒降到 0.829 秒。最终站点 ready，验收期间 API 日志 5xx 为 0。</p></section>
<h2>验收数据清除</h2><section><p>本轮 20 个临时账户已全部删除。对账户、操作日志、普通与深研会话、研究、画像、项目、视频设备、任务、知识库、文件、向量集合、MinIO 对象、Redis 事件、计量及本地 outbox 均做残留检查，全部为 0。云端 Word、报告、音频、临时验收目录已移除；另清理 5 组明确带 pytest-video 标记的历史验收产物。</p>
<p>源研究删除后画像按产品设计保留，已额外删除测试用户的 6 份画像。初始脚本把接口的两个字段误当成画像数量；最终按 PostgreSQL 记录确认 6 份，修正计数后再删除。这里只保留不含研究正文、转录正文、音频或凭据的汇总。</p></section>
<h2>适用范围</h2><section><p>本轮验证了一项完整研究、云端长音频处理与多用户短对话的代表性混合负载。未把结果外推成 16 项完整长研究同时无排队交付，未做全天持续压力或复杂噪声语音识别精度评测。外部模型与微信侧能力也影响实际耗时。</p></section>
<p><a href="acceptance-summary.json">汇总与指标口径</a> · <a href="final-cleanup-verification.log">独立清理核验</a> · <a href="final-audit.json">部署和资源核查</a> · <a href="candidate-tests-and-health-benchmark.log">候选镜像测试</a></p></main></html>'''
(root/'acceptance-report.html').write_text(page)
print('Aggregate acceptance summary generated; cleanup assertions passed')
