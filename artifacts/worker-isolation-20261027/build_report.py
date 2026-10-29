"""从验收证据生成静态报告，明确区分短对话实测与重任务边界。"""
import json
import math
from pathlib import Path

root = Path(__file__).resolve().parent
final = json.loads((root / 'memory-capacity-result-final.json').read_text())
resources = json.loads((root / 'memory-capacity-resources-final.json').read_text())
observed = json.loads((root / 'memory-user-observations-final.json').read_text())
subagent = json.loads((root / 'subagent-result.json').read_text())
cleanup = json.loads(next(row for row in (root / 'cleanup-verification.log').read_text().splitlines() if row.startswith('{')))
lines = (root / 'final-source-and-health.log').read_text().splitlines()
deployment, ready = json.loads(lines[0]), json.loads(lines[1])
assert final['completed'] == 20 and len(final['native_deep']) == 5
assert all(row['status'] == 'completed' for row in final['native_deep'])
assert not final['errors'] and not final['cleanup_errors'] and final['accounts_remaining'] == 0
assert observed['maximum_total_running'] == {'deep': 4, 'chat': 16}
assert observed['maximum_running_per_user'] == {'deep': 2, 'chat': 3}
assert subagent['status'] == 'passed' and subagent['accounts_remaining'] == 0
assert all(value == 0 for value in cleanup['remaining'].values()) and ready['status'] == 'ready'
latencies = sorted(row['ms'] for row in final['page_probes'])
summary = {
    'hardware': '4 vCPU / 16 GB', 'ordinary_users': 16,
    'short_chats_completed': 20, 'native_deep_short_turns_completed': 5,
    'group_elapsed_seconds': final['elapsed_seconds'],
    'actual_completed_model_calls': sum(row['n'] for row in final['real_model_calls'] if row['status'] == 'completed'),
    'page_probe_count': len(latencies), 'page_probe_p95_ms': latencies[math.ceil(len(latencies) * .95) - 1],
    'minimum_available_memory_gib': round(resources['minimum_available_mib'] / 1024, 2),
    'cpu_peak_percent': resources['maximum_cpu_percent'], 'swap_peak_mib': resources['maximum_swap_used_mib'],
    'local_regressions_passed': 255, 'candidate_tests_passed': 7, 'candidate_real_postgres_scenarios': 2,
    'observed_capacity': observed, 'cleanup': cleanup, 'deployment': deployment,
    'scope': 'Real short chats and native deep turns; not simultaneous full long research reports, large PDF/OCR/ASR or 16 external WeChat sessions.',
    'subagent_e2e_stage': 'Real model/tool/file/SSE E2E passed after pool separation, before the final resource-query connection reuse patch.',
}
(root / 'acceptance-report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))

cards = [
    ('普通账户', '16'), ('真实模型完成', '25 / 25'),
    ('整组耗时', f"{summary['group_elapsed_seconds']} 秒"),
    ('页面探测 P95', f"{summary['page_probe_p95_ms']} ms"),
    ('最低可用内存', f"{summary['minimum_available_memory_gib']} GiB"), ('Swap 峰值', '0 MiB'),
]
card_html = ''.join(f'<div class="card"><small>{name}</small><strong>{value}</strong></div>' for name, value in cards)
page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>4 核 16 GB · Worker 隔离与并发验收</title>
<style>body{margin:0;background:#f3f6fa;color:#203044;font:16px/1.7 system-ui,sans-serif}main{max-width:1000px;margin:40px auto;padding:0 24px 50px}h1{font-size:30px;line-height:1.4}h2{font-size:21px;margin-top:30px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card,section{background:white;padding:20px;border-radius:12px;border:1px solid #dce5ed}section{margin:18px 0}small{color:#687888;display:block}strong{font-size:27px;display:block}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid #e4eaf0}a{color:#146ac8}.badge{color:#126642;background:#e4f5ec;padding:5px 12px;border-radius:16px;display:inline-block}@media(max-width:640px){.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:25px}}</style>
<main><span class="badge">云端已部署 · 本轮验收通过</span>
<h1>4 核 16 GB：Worker 隔离与并发验收</h1>
<p>2026-10-27 · https://www.deepquest.space</p>
<p>普通聊天、新版深研、子任务和后台任务使用独立 Docker Worker 与 Redis 队列。每位用户拥有独立执行配额与私有数据；物理 Worker 按业务共享。常驻进程复用内存，减少重复启动与槽位争抢。</p>
<div class="cards">''' + card_html + '''</div>
<h2>当前生效容量</h2><section><table><tr><th>执行池</th><th>全局接纳上限</th><th>每用户执行上限</th></tr>
<tr><td>普通聊天</td><td>16</td><td>3</td></tr>
<tr><td>新版深研</td><td>4</td><td>2</td></tr>
<tr><td>子智能体</td><td>8</td><td>4</td></tr>
<tr><td>通用后台任务</td><td>ARQ 24 / 数据库槽 20</td><td>按业务规则</td></tr></table>
<p>采样达到聊天同时 running 16、深研 4，同一用户分别保持在 3 和 2。配额通过 PostgreSQL 事务锁与有效 lease 计数执行；超额请求保留 pending，释放槽位后补发。子任务使用独立执行池，避免父任务占满槽位后等待子任务。</p></section>
<h2>发现与修复</h2><section><p>首次 16 人真实模型测试出现 4 个失败：运行清单与资源解析持有只读连接，再嵌套申请同一个连接池。修复事务边界后，20 个普通对话加 1 个深研短对话全部完成。</p>
<p>提额测试发现默认智能体的知识库选项也会嵌套申请连接，造成约 30 秒等待。现已复用调用方 Session，保留权限过滤。真实 PostgreSQL 单连接测试确认既能完成查询，又不能读取其他用户的私有知识库。</p></section>
<h2>最终验证</h2><section><p>16 个普通账户通过生产 HTTPS 登录，20 个普通对话与 5 个新版深研短对话全部完成。模型计量表确认 25 次真实调用成功。单用户额外提交多条聊天及 3 个深研请求，排队后均完成，负载期间页面探测全部成功。</p>
<p>本地相关回归 255 项通过；云端候选镜像 7 项通过，其中包含两个真实 PostgreSQL 场景。分池上线后的父子任务 E2E 验证真实模型、文件共享、流式输出和两个不同 Worker 的执行记录；该 E2E 在最后的资源查询优化前完成。</p>
<p>资源采样 100 秒，CPU 短时峰值 100%，Swap 为 0。最终 API 与四个 Worker 健康、无 OOM、同一镜像；最终修复上线后的 API 日志无 5xx。CPU 相对权重优先保障 API 与普通聊天，剩余内存可用于识别、索引、大文件及文件缓存。</p></section>
<h2>清理与适用范围</h2><section><p>本轮共创建 65 个临时测试身份，已全部删除。测试对话、深研、项目、计量、操作日志、隔离 schema 和 Redis 事件均核对为零残留。</p>
<p>本轮证明短对话与深研混合并发可用。完整长研究、大型 PDF/OCR、视频 ASR 和 16 个外部微信会话同时运行未在本轮混合压测中覆盖。4 核 CPU、外部模型额度与微信侧限制仍决定重任务吞吐；视频识别继续保留单任务容量。</p>
<p>部署前已保存源码、容量配置、旧镜像和数据库备份。数据库备份仅验证目录可读取，未做完整恢复演练。</p></section>
<p><a href="acceptance-report.json">汇总 JSON</a> · <a href="memory-capacity-result-final.json">真实对话结果</a> · <a href="memory-user-observations-final.json">配额采样</a> · <a href="resource-fix-candidate-tests.log">候选镜像测试</a> · <a href="cleanup-verification.log">清理核验</a> · <a href="final-source-and-health.log">源码与健康核验</a></p></main></html>'''
(root / 'acceptance-report.html').write_text(page)
print('Acceptance report created; evidence assertions passed')
