"""将最终源码核验、真实验收与未验收边界合并成可审阅报告。"""

import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
evidence=out/'cloud-evidence'
runtime=evidence/'runtime-outputs'
def read(path):
    return json.loads(path.read_text())
def suite(path):
    cases=list(ET.parse(path).getroot().iter('testcase'))
    result={'passed':0,'failed':0,'errors':0,'skipped':0}
    for row in cases:
        key='failed' if row.find('failure') is not None else 'errors' if row.find('error') is not None else 'skipped' if row.find('skipped') is not None else 'passed'
        result[key]+=1
    return result
manifest=read(out/'source-manifest-final.json')
assert len(manifest)==3443
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
integrity=read(evidence/'latest-release-integrity.json')
before=read(runtime/'migration-20261026-persistence-before.json')
after=read(runtime/'migration-20261026-persistence-after.json')
assert before==after
container_before=dict(row.split() for row in (evidence/'cold-containers-before.txt').read_text().splitlines())
container_after=dict(row.split() for row in (evidence/'cold-containers-after.txt').read_text().splitlines())
assert set(container_before)==set(container_after) and all(container_before[name]!=container_after[name] for name in container_before)
assert len(container_before)==15
unit=suite(runtime/'migration-20261026-latest-unit.xml')
api=suite(runtime/'migration-20261026-feedback-http.xml')
rest=suite(runtime/'migration-20261026-feedback-integration-rest.xml')
integration=suite(runtime/'migration-20261026-latest-integration.xml')
assert unit['passed']==2948 and integration['passed']>=407 and integration['failed']==integration['errors']==0 and integration['skipped']==21
tests={'latest_backend_unit':unit,'latest_http_integration':integration,
       'migration_domain_before_final_query_changes':suite(evidence/'domain-s5-final.xml'),
       'migration_real_flows_before_feedback':suite(runtime/'migration-20261026-real.xml'),
       'migration_multimodal_before_feedback':suite(runtime/'migration-20261026-multimodal.xml'),
       'latest_post_cold_real_flows':suite(runtime/'migration-20261026-post-cold-real.xml')}
assert 'ℹ pass 591' in (out/'feedback-web-unit-final.log').read_text()
research=read(runtime/'migration-20261026-research-result.json')
business=read(runtime/'migration-20261026-business-verification.json')
s5=read(runtime/'migration-20261026-s5-delivery.json')
default_probe=read(runtime/'migration-20261026-final-default-project-probe.json')
assert default_probe['real_query_completed'] and default_probe['cleanup']=='passed'
assert all(row['s5_selected']==row['formal_cards']==6 for row in s5)
audit=read(runtime/'migration-20261026-runtime-audit.json')
assert all(value==0 for value in audit['active'].values())
time=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
report={'generated_at':time,'site':'https://www.deepquest.space',
    'status':'latest_release_deployed_acceptance_passed_with_explicit_deferred_scope',
    'data_source':'local','old_cloud_data_and_backups_permanently_removed':True,
    'latest_source':{'files':len(manifest),'sha256':(out/'source-final.sha256').read_text().split()[0],
                     'runtime_python_files':integrity['runtime_python_files'],'api_image_id':integrity['api_image_id'],
                     'local_content_changes_since_packaging':0,'all_workers_same_new_image':True},
    's5':s5,'tests':tests,'web_unit_passed':591,'web_lint':'passed','web_build':'passed',
    'cold_recreated_containers':15,'final_application_containers_recreated':5,'persistent_tables_compared':8,'persistent_tables_unchanged':True,
    'feedback_persistence':{'records_before_cleanup':4,'rolled_back_records':2,'synthetic_fixture_cleaned':True},
    'feedback_features':['server_confirmed_immediate_display','five_second_visible_page_polling','latest_first','per_card_version_history','five_dimension_scores_and_deltas','candidate_status_not_effective_claim','rollback_audit_retained','server_derived_reviewer_and_utc'],
    'business':business,'final_default_project_probe':default_probe,'real_research':research,'runtime_audit':audit,
    'remaining_ui_check':None, 'feedback_in_page_confirmation':read(out/'feedback-confirmation-verification.json'),
    'deferred':['协议','阿里云模型','MiniMax-M2.5开通','Dify','Notion','智谱外部知识库'],
    'quality':{'legacy_lint':241,'new_lint':0},
    'limitations':['未验证反馈仅为记忆候选；不宣称已训练或自动改写生产评分。','完整研究有一次辅助来源请求20秒超时；最终交付成功，超时不计成功。','21项集成跳过与用户暂缓项不计通过。','测试通过不构成所有潜在漏洞均已排除的保证。']}
(out/'acceptance-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
stats=[('最新镜像后端单元',unit,'runtime-outputs/migration-20261026-latest-unit.xml'),
       ('最新镜像 HTTP 集成（API 与其余集成两组）',integration,'runtime-outputs/migration-20261026-latest-integration.xml'),
       ('领域迁移时全量（后续Query改动另测38项）',tests['migration_domain_before_final_query_changes'],'domain-s5-final.xml'),
       ('迁移真实端到端（反馈改动前）',tests['migration_real_flows_before_feedback'],'runtime-outputs/migration-20261026-real.xml'),
       ('真实视觉 / OCR / 推理（反馈改动前）',tests['migration_multimodal_before_feedback'],'runtime-outputs/migration-20261026-multimodal.xml'),
       ('最新镜像冷重建后真实模型 / Worker / 检索',tests['latest_post_cold_real_flows'],'runtime-outputs/migration-20261026-post-cold-real.xml')]
rows=''.join(f'<tr><td>{name}</td><td>{value["passed"]}</td><td>{value["failed"]+value["errors"]}</td><td>{value["skipped"]}</td><td><a href="cloud-evidence/{link}">证据</a></td></tr>' for name,value,link in stats)
doc=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>本地整体迁移与能力画像反馈验收</title>
<style>body{{margin:0;background:#f3f5fa;color:#1b2e41;font:15px/1.75 system-ui,-apple-system,"PingFang SC",sans-serif}}main{{max-width:1120px;margin:auto;padding:28px}}section{{background:white;border:1px solid #dfe5ee;border-radius:12px;padding:22px;margin:18px 0}}h1{{font-size:28px}}h2{{font-size:21px}}.good{{background:#e6f6ed;padding:16px;border-radius:8px}}.pending{{background:#fff2d5;padding:16px;border-radius:8px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #e0e6ef;vertical-align:top}}th{{background:#f1f4fa}}code,a{{overflow-wrap:anywhere}}a{{color:#1759ad}}img{{width:100%;border:1px solid #dfe5ee;border-radius:8px}}li{{margin:7px 0}}small{{color:#586b80}}</style>
<main><h1>本地整体迁移与能力画像反馈验收</h1><p>{html.escape(time)} · <a href="https://www.deepquest.space">打开云站</a> · <a href="acceptance-report.json">结构化报告</a></p>
<p class="good">最新本地代码已部署云端并完成服务器复验。数据以本地为准；原云端业务数据与备份已永久删除。后续反馈更新仅升级代码，没有再次覆盖云端新产生的数据。</p>
<p class="good">反馈回滚确认已改为站内对话框，避免原生确认框阻塞。云端已真实验证取消不改变状态，确认后显示“已回滚”并保留审计记录。用户暂缓项见下文。</p>
<section><h2>“2个版本”的计数更正</h2><p>此前脚本误把接口对象的 <code>run_id</code>、<code>versions</code> 两个字段数当成画像数。已修正脚本并核实两次真实研究：各 <b>6张独立正式画像，每张v1</b>；S5入选6个候选，与6张画像的 hypothesis_id、冻结五维评分一一匹配，S5回退0次。动态蜂群v2默认入选下限、上限均为6，满足5–6张要求，未修改算法凑数。</p><p><a href="cloud-evidence/runtime-outputs/migration-20261026-s5-delivery.json">S5逐项交付核验</a> · <a href="s5-delivery-final.log">计数更正证据</a>。原始失败日志及原统计输出保留，历史优化报告已注明更正原因。</p></section>
<section><h2>反馈即时可查与自进化候选</h2><ul><li>提交成功后先显示服务器确认记录，后台每5秒自动同步；隐藏页暂停同步，读取失败可手动刷新。</li><li>修正“最新三条显示成最旧三条”；可展开记录、按当前画像版本查看，切换任务时立即清空旧数据并隔离迟到响应。</li><li>列表与卡片统一版本标识，修复卡片反馈数错误为0；保存画像版本、反馈人、UTC时间、五维评分、差值与细则建议。</li><li>服务端读取本任务真实S5基准，按45/15/10/25/5计算专家综合分，拒绝跨任务版本与非法评分，忽略客户端伪造的基准与综合分。</li><li>反馈保存时实际提炼为有界记忆候选，显示“已提炼，待验证”；回滚保留原因、时间、操作者与历史。候选没有被宣称为已训练或已验证有效。</li></ul><p>本地及云端均真实提交合成反馈，并核实第二终端新增记录自动出现。合成数据明确标注，不作为专家评价，验收后已清理。</p><img src="feedback-cloud-rollback-verified.png" alt="云端真实反馈记录：自动同步与候选状态"><p><small>合成验收截图；测试后项目与反馈已清理。</small></p><img src="feedback-local-real-ui.png" alt="本地实际提交反馈后展开五维评分与差值"></section>
<section><h2>最新代码与运行镜像一致</h2><p><b>3443个源码文件、717个运行Python文件逐文件校验通过</b>；4个应用进程使用同一份新构建的amd64镜像，前端与沙盒控制器也已核验。最后本地扫描确认打包后无源码变动。</p><p>源码包 SHA256：<code>{report['latest_source']['sha256']}</code><br>API运行镜像：<code>{integrity['api_image_id']}</code></p><p><a href="source-manifest-final.json">逐文件清单</a> · <a href="source-final.sha256">包校验值</a> · <a href="cloud-evidence/feedback-source-update.json">迁移后的画像反馈改动</a> · <a href="cloud-evidence/latest-release-integrity.json">最终运行与镜像核验</a></p></section>
<section><h2>本地数据迁移及冷重建</h2><p>迁移时核验63张PostgreSQL业务表、202个应用对象、5个向量集合共35069行向量、图谱20080节点与35102关系。两套向量命名空间分别恢复，图谱保留全部属性。</p><p>迁移后15个容器冷重建通过；合并最终工作台改动后再重建5个应用容器，8张关键业务表逐行指纹完全一致，4条合成反馈（含2条回滚）完整保留。原技术库93文档、2384分块，原PDF下载及预览通过；真实检索返回10块。15169字旧报告与19932字云端新报告均可读取，各有6张正式画像。</p><p><a href="cloud-evidence/runtime-outputs/migration-20261026-persistence-before.json">重建前指纹</a> · <a href="cloud-evidence/runtime-outputs/migration-20261026-persistence-after.json">重建后指纹</a> · <a href="post-cold-business-complete.log">原文件、检索与两份报告</a> · <a href="cloud-evidence/cold-feedback.log">反馈持久化</a> · <a href="old-cloud-data-removal.log">原云端数据删除</a></p><img src="cloud-technical-library.png" alt="迁移后的技术库93文档与2384分块"></section>
<section><h2>验收结果</h2><p>各套件范围有重叠，不相加；内部模拟测试、HTTP回归与真实供应商调用分开列明。通过数按实际testcase及pytest终态核对。</p><table><thead><tr><th>范围</th><th>通过</th><th>失败</th><th>跳过</th><th>证据</th></tr></thead><tbody>{rows}<tr><td>最新前端单元</td><td>591</td><td>0</td><td>0</td><td><a href="feedback-web-unit-final.log">日志</a></td></tr></tbody></table><p>前端lint、构建通过；后端新增lint为0、历史遗留241。最新完整集成证据见 <a href="cloud-evidence/runtime-outputs/migration-20261026-latest-integration.xml">最终全量集成复验</a>。</p></section>
<section><h2>合并的默认工作台与 Query 改动</h2><p>已一并迁移用户确认完成的 Query 生成器、默认工作台及首次对话目录修复。Query、研究任务、深研对话与智能对话默认归入本人工作台，按用户串行复用，手动改名保留身份；不随意选取其他账号项目。最新真实接口并发验收与实际模型 Query 生成单独留证。</p><p><a href="concurrent-query-regression-resolved.log">Query领域38项</a> · <a href="concurrent-project-local-http-resolved.log">本地真实接口12项</a> · <a href="cloud-evidence/runtime-outputs/migration-20261026-final-default-project-probe.json">云端真实模型与默认项目归属</a> · <a href="feedback-confirmation-verification.json">站内回滚确认实测</a></p></section><section><h2>真实功能交付</h2><p>完整研究416秒完成，19932字报告；89次模型调用成功，1次辅助来源请求20秒超时，S5回退0。超时未算成功，也不据此宣称所有长请求超时均已消除。原Query真实生成并发布；最终工作台探针另有1次真实模型调用并成功生成能力需求Query。照明维护题目最初被能力需求规则拒绝，未计通过，随后使用明确设备能力需求题目实测。独立文档模型问答、原文引文和ZIP交付通过。</p><p>真实页面验证技术库检索、技能目录、公众号账号池、公开账号检索、102篇文章列表、单篇下载及个人空间正文预览。微信公开文章下载1成功、0失败，正常采集成果保留。</p><p>冷重建后又真实执行原生深研、异步Agent与持久化、网页及学术检索3项，全部通过。</p><p><a href="cloud-evidence/runtime-outputs/migration-20261026-research-result.json">完整研究结果（已更正6张）</a> · <a href="cloud-evidence/runtime-outputs/migration-20261026-post-cold-real.xml">重建后真实调用</a> · <a href="cloud-wechat-real-download-completed.png">公众号实际下载</a></p></section>
<section><h2>清理与未验收边界</h2><p>合成反馈项目已清理，临时验收账号均停用，仅隐藏本轮专用账号的测试对话；真实客户对话和研究报告保留。当前活动研究、Agent、任务与临时验收账号均为0。HTTPS就绪、内部端口仅监听回环地址、凭据权限0600。</p><p>用户暂缓：协议主体与正式文本、阿里云模型、MiniMax-M2.5开通、Dify、Notion、智谱外部知识库。它们不计为本轮通过项。原生确认框问题已通过站内确认框优化并完成页面实测。</p><p>保留初次夹具缺失、旧目录相对路径及旧计数错误的原始输出，修复后复测另存。测试通过不等于已排除所有潜在漏洞。</p><p><a href="final-cleanup-and-release.log">最终清理与运行核验</a> · <a href="cloud-evidence/runtime-outputs/migration-20261026-runtime-audit.json">活动任务及辅助超时审计</a></p></section></main></html>'''
(out/'acceptance-report.html').write_text(doc)
progress=read(out/'progress.json')
progress.update(stage='latest_code_deployed_cold_rebuild_verified_report_delivered',status=report['status'],cloud_integration_passed=integration['passed'],cloud_post_cold_real_passed=3,latest_application_containers_recreated=5,source_sha256=report['latest_source']['sha256'],cold_recreated_containers=15,persistence_tables_verified=8,remaining=[],report='acceptance-report.html')
(out/'progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'report':str(out/'acceptance-report.html'),'tests':tests,'status':report['status']},ensure_ascii=False))
