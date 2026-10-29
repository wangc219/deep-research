"""汇总可复核的验收证据，不把跳过项或重复复测计为新增通过。"""
import json,html,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone,timedelta
root=Path(__file__).resolve().parent
source_sha=(root/'source-final.sha256').read_text().split()[0]

def read(name):return json.loads((root/name).read_text())
def suite(name):
 p=root/name
 if not p.exists():return {'evidence':name,'status':'pending'}
 cases=list(ET.parse(p).iter('testcase'))
 failures=sum(c.find('failure') is not None for c in cases)
 errors=sum(c.find('error') is not None for c in cases)
 skipped=sum(c.find('skipped') is not None for c in cases)
 return {'evidence':name,'cases':len(cases),'passed':len(cases)-failures-errors-skipped,'failed':failures,'errors':errors,'skipped':skipped}
models=read('enabled-model-verification.json')
for m in models:
 if m['model']=='Pro/MiniMaxAI/MiniMax-M2.5':
  m['observed_status']=m['status'];m['status']='deferred_by_user_after_real_403'
rows=[]
def row(feature,method,result,evidence,status='passed'):rows.append(dict(feature=feature,method=method,result=result,evidence=evidence,status=status))
row('登录、HTTPS 与资源加载','正式公网 HTTPS 真实密码登录；SSE、worker、PG 因果链','证书校验、301、静态资源、ready、未登录管理接口401通过','public-https-verification.json; cloud-logs/https-final.log')
row('企业、用户、项目与权限隔离','真实HTTP、PG与隔离测试身份的自动化契约；浏览器页面巡检','当前原生入口、普通用户/管理员可见性、资源授权与撤销通过','cloud-xml/full-acceptance-20261025-cloud-integration.xml; cloud-logs/system-final.log')
row('智能对话、Steer 与多智能体','真实供应商、真实worker、SSE与持久化','异步执行、Steer checkpoint、子智能体并行、共享成果和历史回读通过','cloud-logs/real.log; cloud-logs/deterministic-final.log')
row('上下文压缩','实际3轮对话→模型摘要→文件和PG checkpoint→下一轮复述','唯一标记在压缩后准确保留；复测通过','cloud-logs/summary-final.log')
row('Query→研究→能力画像→报告','临时普通用户，真实模型与后台worker完整执行','387秒完成；7032字报告；2个画像版本；66次成功调用；S5降级0次','cloud-logs/research-complete.log; cloud-real-research-report.md')
row('原生深研对话、计量与报告接口','真实模型；真实HTTP与PG','原生深研、模型计量、终态投影与下载通过','cloud-logs/real.log; cloud-logs/final-image-smoke.log')
row('图片、PDF OCR、推理流','真实看图、PDF OCR、非视觉OCR回退','3项通过；思考内容SSE/历史/PG一致','cloud-logs/multimodal.log')
row('已开通模型逐项连通','运行时真实模型工厂；重排直接校验供应商结果，排除中性分数回退','3对话、3嵌入、2重排共8项通过','enabled-model-verification.json')
row('已开通对话模型工具往返','逐个真实调用 DeepSeek、硅基DeepSeek、GLM；流式工具→结果→续答','3项通过；显式thinking；续答正文和工具协议通过','cloud-logs/provider-reasoning.log')
row('学术工具选路与引用','真实模型、隔离PG；AMiner与Web响应使用测试替身','10类选路、完整摘要、规范引用、鉴权失败恢复和共享预算已复测；另有真实外部检索E2E','cloud-logs/academic-citation-final.log; cloud-logs/citation-public-final.log')
row('知识库完整闭环','真实上传、OCR、嵌入、MinIO、Milvus、Neo4j、重排、模型评估','入库、向量召回、图谱、评估集生成、回答与裁判通过','cloud-logs/real.log; real-knowledge-evaluation.log')
row('原有知识与原文','浏览器真实召回原技术库；实际PDF预览','原库10个相关片段与PDF可读，重启后数据计数保留','cloud-original-retrieval.png; cloud-original-pdf-preview.png; final-state-verification.json')
row('公众号扫码与账号池','用户亲自微信扫码；实际账号验证、公众号搜索与列表','1个可用账号；实际搜索、收藏、21篇列表通过；重启后授权保留','cloud-real-wechat-batch-download.png; final-state-verification.json')
row('公众号下载、成果与入库','真实公开URL下载、正文预览、2篇多选批量下载、新建私有库和索引','批量2成功0失败；入库3片段；全服务重启后再次召回3片段','cloud-real-wechat-download.png; cloud-real-wechat-sandbox.png; cloud-real-wechat-restart-retrieval.png')
row('微信视频→ASR→Word/ZIP→知识库','本机真实微信视频→个人采集器→云端CPU ASR','实际新闻视频转录553字；Word、ZIP、入库与向量召回通过','cloud-real-video-delivery-final.log; cloud-real-wechat-video.docx')
row('独立文档研究','真实资料库与模型；问答、研究报告、追问、编辑、下载、撤销','逐字引文、ZIP、SHA冲突409、撤销后403通过；重启后3任务仍completed','cloud-logs/document-answer.log; cloud-logs/document-report.log; final-state-verification.json')
row('个人空间、技能与MCP','真实沙盒成果→工作区预览、编辑与ZIP；真实模型技能/MCP调用；安全拒绝契约','chat/deep成果链、个人技能、动态MCP及stdio安全拒绝通过','cloud-logs/real.log; cloud-xml/full-acceptance-20261025-cloud-integration.xml')
row('任务、取消、审计与仪表盘','真实PG/Redis与HTTP契约；确定性provider用于可重复的故障/取消测试','终态竞争、因果一致性、取消、工具审计、统计契约通过；不将确定性provider算真实模型','cloud-logs/deterministic.log; cloud-logs/deterministic-final.log; cloud-logs/real.log')
row('源码与运行镜像一致性','3434个源码文件hash；716运行Python文件hash；API及3worker镜像核对','源码、运行代码、沙盒控制器一致；内部发布端口仅loopback','release-integrity-final.json; source-manifest-final.json')
row('迁移与全服务重启持久化','备份；隔离PG schema幂等演练；停启全部应用和存储容器','schema14/6；PG、JWT、MinIO原文、Milvus召回通过；原数据计数一致','cloud-schema-rehearsal.log; cloud-logs/restart-final.log; cloud-logs/persistence-verify.log; final-state-verification.json')
row('清理旧版与临时权限','活动目录替换；旧容器退出；删除临时staging；禁用验收账号和采集设备','新版单一活动目录/镜像；临时凭据清理；受保护回滚备份保留','final-state-verification.json; release-integrity-final.json')
row('阿里云模型','用户明确暂不验证','不计通过','用户本轮授权','deferred')
row('MiniMax-M2.5','实际调用返回403 Model disabled；用户决定后续自行开通','本轮暂缓，不计通过','enabled-model-verification.json; 用户本轮授权','deferred')
row('Dify / Notion / 智谱云知识库','缺少真实凭据或资料库授权；用户要求先迁移','外部服务连接暂缓，不计通过','用户本轮授权','deferred')
row('协议与隐私页面内容','页面仍为现有模板','组织名与生效日占位符待用户替换；未代拟法务内容','现有登录页协议模板','limitation')
row('后端全仓lint','修改的运行文件检查通过；全仓遗留告警未全部清理','全仓1081条既有告警，不宣称全仓lint通过','backend-lint.json; backend-lint.log','limitation')
checks={
 'cloud_unit':suite('cloud-xml/full-acceptance-20261025-cloud-unit.xml'),
 'cloud_integration_initial':suite('cloud-xml/full-acceptance-20261025-cloud-integration.xml'),
 'cloud_integration_system_retest':suite('cloud-xml/full-acceptance-20261025-cloud-system-final.xml'),
 'cloud_real_e2e':suite('cloud-xml/full-acceptance-20261025-cloud-real.xml'),
 'cloud_multimodal':suite('cloud-xml/full-acceptance-20261025-real-multimodal-final.xml'),
 'cloud_deterministic_initial':suite('cloud-xml/full-acceptance-20261025-cloud-deterministic.xml'),
 'cloud_deterministic_retest':suite('cloud-xml/full-acceptance-20261025-cloud-deterministic-final.xml'),
 'cloud_summary':suite('cloud-xml/full-acceptance-20261025-cloud-summary.xml'),
 'cloud_final_image_smoke':suite('cloud-xml/full-acceptance-20261025-cloud-final-image-smoke.xml'),
 'cloud_async_image_smoke':suite('cloud-xml/full-acceptance-20261025-cloud-async-image-smoke.xml'),
 'cloud_public_https':suite('cloud-xml/full-acceptance-20261025-cloud-https-final.xml'),
 'cloud_provider_reasoning':suite('cloud-xml/full-acceptance-20261025-cloud-provider-reasoning.xml'),
 'cloud_academic_routing_initial':suite('cloud-xml/full-acceptance-20261025-cloud-academic-routing.xml'),
 'cloud_academic_citation_before_notice':suite('cloud-xml/full-acceptance-20261025-cloud-academic-citation-before-notice.xml'),
 'cloud_academic_citation_final':suite('cloud-xml/full-acceptance-20261025-cloud-academic-citation-final.xml'),
 'cloud_academic_citation_resolved':suite('cloud-xml/full-acceptance-20261025-cloud-academic-citation-resolved.xml'),
 'cloud_citation_public_final':suite('cloud-xml/full-acceptance-20261025-cloud-citation-public-final.xml'),
 'domain_final_initial':suite('full-acceptance-20261025-domain-s5-final.xml'),
 'domain_final_retest':suite('full-acceptance-20261025-domain-gate-resolved.xml'),
 'document_offline':suite('document-research.xml'),
}
limitations=[
 '学术选路初跑8通过2引用失败；首个候选70通过2失败，其中1项未取完整摘要、1项测试错误假设首批工具必须为学术工具。后续修正完整摘要提示和测试批次定位后71通过，余1项因查询被既有规则缩短而断言失败；对照query_coverage修正测试后定向1通过，72唯一用例已验证，未把复测重复相加。保留各次失败证据。',
 '按用户要求在初步验收后先迁移；云端继续发现、修复并复验问题。未将迁移前状态包装成零缺陷。',
 'HTTP集成初跑405通过、1失败、21跳过；日志测试harness只读路径修正后14项复测通过，唯一已通过用例共406，不能直接相加为419。21个跳过原样保留，部分能力另有显式真实测试。',
 '领域最终全量2249通过、1测试替身失败；将测试替身适配新acquire_async后5项定向复测通过，2250唯一用例已验证；初次全量XML仍保留失败记录。',
 '确定性provider初跑10通过、1未配置Langfuse的断言失败；按实际启用状态检查后1项复测通过，唯一用例11，不等于真实供应商11项。',
 '单元XML汇总tests属性为2933，与实际2926个testcase及pytest日志不一致；报告按实际用例与日志统计2926。',
 '学术选路探针使用真实模型、真实隔离PG，但AMiner/Web响应由测试替身提供，仅证明选路、预算、鉴权失败恢复和引用约束；外部检索真实性另见real E2E。',
 '知识评估中的1.0仅代表本轮合成小样本，不代表平台整体准确率100%。',
 '完整研究最终成功，辅助source_anchor曾有20秒超时并恢复，未宣称所有模型请求零失败。',
 '本轮验证为全服务/容器重启，未重启服务器操作系统；没有以破坏生产环境的方式做无限并发或全面渗透测试，不能保证绝对无漏洞。',
]
fixes=[
 {'problem':'学术回答将来源链接自行改写、遗漏引用标签或仅凭部分摘要写技术比较','change':'工具返回可直接使用的citation标签；明确逐字使用来源URL、技术结论前读取完整摘要；修正鉴权恢复测试对首个非学术工具批次的错误假设','proof':'最初引用失败与部分摘要问题已复验；72项中71通过、1查询规范化测试假设失败，修正后定向1通过；正式公网检索复验见日志'},
 {'problem':'S3/S5精简输入丢失run/agent/mission/batch身份与phase','change':'精简后保留阶段身份；运行时phase直接读stream_options','proof':'完整研究66次成功模型调用、2画像、S5降级0；阶段计量正确'},
 {'problem':'S6 fan-out等待gate占满线程池，完成调用又等待同一线程池写计量','change':'新增异步等待acquire_async，保留优先级、取消清理与lease语义','proof':'单线程池12调用完成；取消测试与51项回归；真实研究387秒完成'},
 {'problem':'云端CPU ASR权重加载峰值内存过高','change':'torch mmap与assign低内存加载','proof':'x86预检、真实微信新闻视频转录及最终镜像ASR复验通过'},
 {'problem':'新写入Milvus数据被一致性延迟误判未就绪','change':'关键count/query采用Strong一致性','proof':'真实入库、原文/向量召回与全服务重启后唯一标记召回通过'},
 {'problem':'非视觉OCR回退生命周期、空正文与Steer交接','change':'修正BaseChatModel生命周期与审计；拒绝空正文并保留Steer安全点','proof':'真实多模态3项与Steer回归通过'},
 {'problem':'部署、迁移脚本与旧CI契约不一致','change':'受控停写迁移入口、退出沙盒、证明令牌；修正init拉镜像与质量门禁','proof':'101项配置契约、脚本语法和真实schema幂等演练通过'},
]
skipped=[]
for c in ET.parse(root/'cloud-xml/full-acceptance-20261025-cloud-integration.xml').iter('testcase'):
 s=c.find('skipped')
 if s is not None:skipped.append({'test':c.attrib.get('classname','')+'.'+c.attrib['name'],'reason':s.attrib.get('message','')})
report={'generated_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'decision':'新版已上线；已开通核心功能与真实闭环通过；已授权暂缓项单列。','deployment':read('deployment-final.json'),'url':'https://www.deepquest.space','source_sha256':source_sha,'production_root':'/opt/deep-research','backup_root':'/var/backups/deepquest/full-acceptance-20261025','api_image':'deepquest-api:acceptance-20261025','api_image_id_prefix':read('deployment-final.json')['api_image_id'].removeprefix('sha256:')[:12],'schema':{'business':14,'knowledge':6},'frontend':{'passed':586,'failed':0,'lint':'passed','build':'passed'},'checks':checks,'models':models,'matrix':rows,'fixes':fixes,'limitations':limitations,'integration_initial_skips':skipped,'final_state':read('final-state-verification.json'),'release_integrity':read('release-integrity-final.json'),'public_https':read('public-https-verification.json')}
(root/'acceptance-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
esc=lambda x:html.escape(str(x))
def links(value):
 return '<br>'.join('<a href="'+esc(p.strip())+'">'+esc(p.strip())+'</a>' if '.' in p and '用户' not in p else esc(p) for p in value.split(';'))
body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeepQuest 云端真实验收报告</title><style>body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;background:#f2f5f8;color:#172739;margin:0;line-height:1.6}main{max-width:1280px;margin:auto;padding:32px}h1{font-size:28px}h2{margin-top:36px}section,.card{background:white;padding:20px;border-radius:12px;margin:16px 0;box-shadow:0 3px 16px #162d4010}table{width:100%;border-collapse:collapse;background:white;font-size:14px}th,td{padding:12px;text-align:left;border-bottom:1px solid #e4eaf0;vertical-align:top}th{background:#eaf0f5}a{color:#165fba;overflow-wrap:anywhere}code{overflow-wrap:anywhere}.badge{display:inline-block;border-radius:5px;padding:2px 8px;font-weight:600}.passed{background:#dff3e9;color:#165b39}.deferred,.limitation{background:#fff0ce;color:#805506}.failed{background:#ffe2e2;color:#a51d1d}button{padding:8px 16px;margin:4px;border:1px solid #b9c9d9;border-radius:6px;background:#fff;cursor:pointer}.note{color:#536779}img{max-width:100%;border:1px solid #d5dfe9;border-radius:8px}li{margin:8px 0}pre{white-space:pre-wrap}summary{cursor:pointer;font-weight:600}</style><main>'''
body+='<h1>DeepQuest 云端真实验收报告</h1><p>'+esc(report['decision'])+'</p><p><a href="https://www.deepquest.space">打开正式网站</a> · <a href="acceptance-report.json">结构化报告 JSON</a> · '+esc(report['generated_at'])+'</p>'
body+='<section><b>活动目录：</b><code>/opt/deep-research</code><br><b>源码SHA256：</b><code>'+report['source_sha256']+'</code><br><b>API与3个Worker：</b><code>'+report['api_image_id_prefix']+'</code> · schema 14/6<br><b>维护：</b>已解除 · readiness ready / degraded false<br><b>旧版：</b>已退出活动运行；受保护回滚备份保留于 <code>'+report['backup_root']+'</code></section>'
body+='<h2>验收矩阵</h2><p class="note">“通过”指下列明确步骤及证据通过；授权暂缓和既有限制不计通过。</p><div><button onclick="filterRows(\'all\')">全部</button><button onclick="filterRows(\'passed\')">通过</button><button onclick="filterRows(\'deferred\')">授权暂缓</button><button onclick="filterRows(\'limitation\')">限制</button></div><table id="matrix"><thead><tr><th>功能</th><th>方式</th><th>结果</th><th>证据</th></tr></thead><tbody>'
labels={'passed':'通过','deferred':'授权暂缓','limitation':'已知限制','failed':'未通过'}
for r in rows:body+='<tr data-status="'+r['status']+'"><td><span class="badge '+r['status']+'">'+labels[r['status']]+'</span><br>'+esc(r['feature'])+'</td><td>'+esc(r['method'])+'</td><td>'+esc(r['result'])+'</td><td>'+links(r['evidence'])+'</td></tr>'
body+='</tbody></table><h2>自动化结果与复测</h2><p class="note">表格保留初次失败和跳过；复测有重叠，不应把各行相加作为唯一用例总数。前端586项通过，lint/build通过；配置契约101项通过。</p><table><tr><th>套件</th><th>通过</th><th>失败/错误</th><th>跳过</th><th>原始证据</th></tr>'
for name,c in checks.items():body+='<tr><td>'+esc(name)+'</td><td>'+esc(c.get('passed','待完成'))+'</td><td>'+esc(str(c.get('failed','—'))+'/'+str(c.get('errors','—')))+'</td><td>'+esc(c.get('skipped','—'))+'</td><td>'+links(c['evidence'])+'</td></tr>'
body+='</table><h2>模型实际调用</h2><table><tr><th>供应商 / 模型</th><th>类型</th><th>结果</th></tr>'
for m in models:body+='<tr><td>'+esc(m['provider']+' / '+m['model'])+'</td><td>'+esc(m['type'])+'</td><td>'+esc('通过' if m['status']=='passed' else ('用户授权暂缓；实际返回403 Model disabled' if m.get('upstream_model_disabled') else '用户授权暂缓'))+'</td></tr>'
body+='</table><h2>本轮发现并修复</h2>'
for f in fixes:body+='<section><b>'+esc(f['problem'])+'</b><p>'+esc(f['change'])+'</p><p class="note">复验：'+esc(f['proof'])+'</p></section>'
body+='<h2>重启与原数据保留</h2><p>全部应用及存储容器已停启；原用户6、对话82、消息2142、AgentRun77、任务10、知识库1、文件6、片段91，与停写备份一致。全服务重启后原知识PDF与召回、新公众号授权/入库召回、独立文档任务均保留。没有重启服务器操作系统。</p><figure><img src="cloud-real-wechat-restart-retrieval.png" alt="公众号入库资料在全服务重启后真实召回3片段"><figcaption>用户微信扫码后，实际公众号文章下载并入库；重启后再次召回3个相关片段。</figcaption></figure>'
body+='<h2>统计口径与限制</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in limitations)+'</ul><details><summary>集成初跑21个跳过项原始清单</summary><ul>'+''.join('<li><code>'+esc(x['test'])+'</code><br>'+esc(x['reason'])+'</li>' for x in skipped)+'</ul></details>'
body+='<p class="note">验收账号与采集器临时设备已撤销，临时staging与本地私有状态已清理；用户原账号、微信授权和保留的验收样本未撤销。报告和日志含内部路径与审计标识，供项目内部复核。</p><script>function filterRows(s){document.querySelectorAll("#matrix tbody tr").forEach(r=>r.hidden=s!=="all"&&r.dataset.status!==s)}</script></main></html>'
(root/'acceptance-report.html').write_text(body)
print(json.dumps({'report':'acceptance-report.html','matrix_rows':len(rows),'pending_suites':[n for n,c in checks.items() if c.get('status')=='pending']},ensure_ascii=False))
