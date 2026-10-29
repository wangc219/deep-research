"""汇总本轮原始证据，生成可离线查看的优化与下线报告。"""

import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read_json(name):
    return json.loads((HERE / name).read_text())


def suite(name, label, note=""):
    """按实际 testcase 统计，跳过和失败独立列出。"""
    cases = ElementTree.parse(HERE / name).getroot().findall(".//testcase")
    failed = sum(case.find("failure") is not None or case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    return dict(label=label, passed=len(cases) - failed - skipped, failed=failed, skipped=skipped,
                evidence=name, note=note)


parent = json.loads((ROOT / "artifacts/full-acceptance-20261025/source-manifest-final.json").read_text())
current = read_json("source-manifest-final.json")
source_sha = hashlib.sha256((HERE / "source-final.tar.gz").read_bytes()).hexdigest()
delta = dict(parent_source_sha256="6fbaf01e49af8fb4d2896b3ab873e29aef7b2448037dee9ff558ed94388bbeb3",
             source_sha256=source_sha,
             changed=sorted(p for p in parent.keys() & current.keys() if parent[p] != current[p]),
             added=sorted(current.keys() - parent.keys()), removed=sorted(parent.keys() - current.keys()))
(HERE / "source-delta.json").write_text(json.dumps(delta, ensure_ascii=False, indent=2) + "\n")

tests = [
    suite("unit-release.xml", "平台后端完整单元", "最后阶段参数修复另由领域全量和真实探针覆盖。"),
    suite("domain-release.xml", "最终研究领域完整回归", "使用历史测试要求的临时目录布局；未跳过断言。"),
    suite("deep-optimization-20261025-integration-final.xml", "真实 HTTP 集成", "21项跳过未计为通过；范围见原始XML。"),
    suite("deep-optimization-20261025-academic-final.xml", "学术选路与证据探针", "模型真实调用；AMiner/Web传输使用受控响应，外部真实性另见E2E。"),
    suite("deep-optimization-20261025-real.xml", "真实外部服务与业务链路", "含模型、检索、知识入库、OCR、嵌入、重排、图谱及评估等。"),
    suite("deep-optimization-20261025-real-final.xml", "前次服务重启后关键链路", "5项，含真实知识链路和采集。"),
    suite("real-release.xml", "最终服务重启后真实复验", "真实对话、Web、AMiner和论文摘要。"),
    suite("phase-and-gate-resolved.xml", "最终阶段、预算与并发定向回归", "与领域全量存在重叠，不累计为独立总量。"),
]
assert all(t["failed"] == 0 for t in tests), tests
assert next(t for t in tests if t["label"] == "最终研究领域完整回归")["skipped"] == 0

report = dict(
    generated_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    local_status="optimized_and_retested", cloud_status="deployments_removed_not_redeployed",
    migration_blocker="待用户确认业务数据以本地、原云端或合并结果为准；两边资料数量不同，不默认覆盖。",
    cloud_removal=read_json("cloud-removal-result.json"),
    cloud_final_verification="cloud-offline-release.log",
    improvements=[
        "并发调用由20毫秒轮询改为跨线程与事件循环通知；释放、取消和扩容都会唤醒等待者。",
        "学术回答仅接受当前轮次、匹配实际工具调用的真实来源；缺引用或摘要不足最多两轮纠正，仍不满足则失败。",
        "明确要求公开技术证据时必须检索；遵循用户明确排除论文等渠道的限制。",
        "重排失败保留原召回排序并显式提示降级，不再伪造0.5分；状态沿来源元数据传递到前端。",
        "来源整理阶段进入供应商调用及计量；短阶段关闭隐藏推理，保留20秒上限。实际预算由返回元数据传递，原参数不再被污染。",
        "后端历史lint从本轮1079项减至241项，新增问题门禁为零；前端CI增加只读lint。",
    ],
    tests=tests, frontend=dict(passed=586, failed=0, skipped=0, lint="passed", build="passed",
                             evidence=["web-unit.log", "web-lint-final.log", "web-build-final.log"]),
    quality=dict(legacy_findings=241, new_findings=0, architecture="passed", evidence="quality-release.log"),
    real_research=read_json("research-result.json"),
    final_source_anchor_probe=read_json("anchor-phase-release-result.json"),
    deferred=["协议主体与正式协议文本", "阿里云模型", "MiniMax-M2.5开通", "Dify", "Notion", "智谱外部知识库"],
    source=dict(sha256=source_sha, files=len(current), changed=len(delta["changed"]),
                added=len(delta["added"]), removed=len(delta["removed"]), archive="source-final.tar.gz"),
    limitations=[
        "云端当前没有项目运行，因此本报告不将历史云端验收计为当前新版云端复验。",
        "完整研究耗时594秒，产生15169字报告和2个画像版本：98次模型调用成功、3次辅助来源请求超时，S5回退0次。",
        "针对上述超时与阶段缺失的最终短探针3次成功，输入不同于原长请求，不能据此宣称所有长请求均已消除超时。",
        "原并行维护规程Query被领域规则拒绝，未计通过；另一个明确设备能力Query真实生成并发布。",
        "保留初次学术选路失败、旧重排断言失败、历史目录布局失败与原wrapper失败日志；修复及复测独立归档。",
        "剩余241项历史lint和21项集成跳过项不计为已消除问题；测试通过不等于不存在任何漏洞。",
        "源码包不含私有部署凭据和运行数据；迁移需另行迁移所选业务数据和受保护配置，PostgreSQL跨架构使用逻辑恢复。",
    ],
)
(HERE / "optimization-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

esc = html.escape
def link(name):
    return f'<a href="{esc(name, quote=True)}">{esc(name)}</a>'

rows = "".join(f'<tr><td>{esc(t["label"])}</td><td>{t["passed"]}</td><td>{t["failed"]}</td>'
               f'<td>{t["skipped"]}</td><td>{esc(t["note"])}<br>{link(t["evidence"])}</td></tr>' for t in tests)
items = lambda values: "<ul>" + "".join("<li>" + esc(v) + "</li>" for v in values) + "</ul>"
body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>本地深度优化与云端撤除复核</title>
<style>body{{font:15px/1.7 system-ui,-apple-system,"PingFang SC",sans-serif;background:#f2f5f8;color:#182b3b;margin:0}}
main{{max-width:1150px;margin:auto;padding:28px}}section{{background:white;padding:24px;margin:18px 0;border-radius:12px}}
h1{{font-size:28px}}h2{{font-size:21px}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;border-bottom:1px solid #dbe3eb;padding:10px;vertical-align:top}}
th{{background:#eaf0f6}}a{{color:#155da8;overflow-wrap:anywhere}}code{{overflow-wrap:anywhere}}img{{width:100%;border:1px solid #dbe3eb}}.status{{background:#fff0ce;padding:16px;border-radius:8px}}li{{margin:8px 0}}</style>
<main><h1>本地深度优化与云端撤除复核</h1><p>{esc(report["generated_at"])}</p>
<p class="status">本地优化已复测；云端所有项目已撤除，尚未重新部署。迁移前等待业务数据来源选择。</p>
<section><h2>当前云端状态</h2><p>49.232.128.56：0容器、0 Compose项目，Nginx停止并禁用，活动部署目录已移除，项目端口关闭。
最新复查见 {link("cloud-offline-release.log")}。</p><p>完整部署、业务数据、最新逻辑导出与独立文档数据保存在受保护目录
<code>/var/backups/deepquest/offline-before-local-optimization-20261025</code>。备份已校验，未删除历史备份。</p>
<p>{esc(report["migration_blocker"])}</p>{link("cloud-removal-result.json")}</section>
<section><h2>完成的优化</h2>{items(report["improvements"])}</section>
<section><h2>验证结果</h2><p>各套件存在范围重叠，不相加。跳过项单列，模拟传输与真实外部调用明确区分。</p>
<table><thead><tr><th>范围</th><th>通过</th><th>失败</th><th>跳过</th><th>证据与说明</th></tr></thead><tbody>{rows}</tbody></table>
<p>前端586项通过、0跳过，lint与构建通过：{link("web-unit.log")} / {link("web-lint-final.log")} / {link("web-build-final.log")}。</p>
<p>架构边界通过，质量门禁新增0项、遗留241项：{link("architecture-release.log")} / {link("quality-release.log")}。</p></section>
<section><h2>真实研究交付与最终定向复验</h2><p>完整研究594秒完成，交付15169字报告、2个能力画像版本。
98次模型调用成功，3次辅助来源调用超时，S5回退0次。{link("research-result.json")} / {link("research-non-success.json")}。</p>
<p>最终来源阶段真实探针3次成功，阶段计量正确，原20秒上限保留；仅证明该短探针。
{link("anchor-phase-release-result.json")}。明确设备能力Query另测8秒生成并发布，{link("valid-query-result.json")}。</p></section>
<section><h2>真实页面故障与恢复</h2><p>独立测试资料库触发重排服务失败，页面显示降级提示且保留召回结果：</p>
<img src="local-rerank-degraded-ui.png" alt="重排服务降级提示"><p>恢复已开通重排模型后，真实分数显示，降级提示消失：</p>
<img src="local-rerank-recovered-ui.png" alt="重排恢复真实分数"><p>本轮临时故障资料库与验收身份已清理或禁用，见 {link("ui-cleanup.log")}。</p></section>
<section><h2>暂缓项和结论边界</h2>{items(report["deferred"])}{items(report["limitations"])}</section>
<section><h2>交付物</h2><p>源码{len(current)}文件，相对上一轮快照修改{len(delta["changed"])}、新增{len(delta["added"])}、删除{len(delta["removed"])}。
其中包含针对遗留告警文件的安全修复与格式整理，不将整仓既有改动认领为本轮工作。</p>
<p>SHA256：<code>{source_sha}</code></p><p>{link("source-final.tar.gz")} / {link("source-final.sha256")} / {link("source-manifest-final.json")} / {link("source-delta.json")} / {link("optimization-report.json")}</p></section></main></html>'''
(HERE / "optimization-report.html").write_text(body)
progress = read_json("progress.json")
progress.update(stage="local_optimization_completed_awaiting_migration_data_choice", local_changes_unverified=False,
                cloud_currently_deployed=False, source_sha256=source_sha,
                migration_data_choice="awaiting_user", report="optimization-report.html")
(HERE / "progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"report": str(HERE / "optimization-report.html"), "source_sha256": source_sha,
                  "cloud_deployed": False, "migration_data_choice": "awaiting_user"}, ensure_ascii=False))
