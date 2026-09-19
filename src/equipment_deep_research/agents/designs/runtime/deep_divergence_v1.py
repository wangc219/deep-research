"""Codex-facing runtime profile for bounded deep-divergence sessions.

Deep divergence is launched as a child workflow from an existing research
run.  It inherits the parent Query, visible result snapshot, and evidence
references, then performs a small number of explicitly budgeted S3/S4
explorations.  The profile intentionally describes only the public contract;
provider reasoning, prompts, and credentials are never part of the runtime
payload.
"""

from __future__ import annotations


MISSION_LENS = (
    "以当前Query和父任务可见结果为锚，围绕能力缺口发散竞争性机制；"
    "只有能改变打击、反制、拒止、抗毁或持续作战效果且具备明确证据边界或待验证声明的方向，"
    "才形成待核验能力画像候选。"
)
QUERY_DOMINANT = True
PROFILE = {
    "scenario": "继承当前Query、结果和证据的深度追问与参考武器定向研究",
    "skills": [
        "Query语义继承",
        "S3竞争性机制发散",
        "S4装备能力映射",
        "证据缺口研究",
        "待核验能力卡生成",
    ],
    "tools": [
        "search_sources",
        "fetch_page",
        "create_evidence_card",
        "write_stage_output",
    ],
    "methodology": [
        "读取父任务的Query、可见结果、候选卡和证据引用",
        "先在不扩大权限的前提下提出竞争性解释与反例",
        "仅针对已声明的参考武器或能力缺口升级公开来源检索",
        "将S3机制映射到S4装备能力、约束、验证路径和失效边界",
        "身份、机理和直接军事效果成立后生成独立的pending_verification能力卡版本；缺少直接证据不单独阻断前瞻方向",
    ],
    "quality_gates": [
        "不得重跑父任务或读取隐藏推理",
        "不得虚构精确指标、成本、TRL或效能比例",
        "候选必须保留来源、假设、反证和未决问题",
        "部分失败只保留草稿/预览，不自动并入正式能力画像",
        "结果必须可追溯到当前Query和声明的研究焦点",
    ],
    "output_focus": [
        "深度追问结论",
        "竞争性机制",
        "参考武器方向",
        "证据缺口与边界",
        "S4能力映射",
        "待核验能力画像卡",
    ],
    "safety_boundary": (
        "仅使用公开来源开展战略、能力、装备市场与防御性需求研究；"
        "不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、"
        "规避防护的方法或武器制造参数。"
    ),
}
