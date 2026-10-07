from __future__ import annotations

MISSION_LENS = '检查S1–S6是否形成连续打击/反制军事因果链，避免技术名词、流程完整或证据数量替代真实作战价值。'
QUERY_DOMINANT = False
PROFILE = {'scenario': 'S1-S6中循环因果连续性、覆盖和回溯点批判',
 'skills': ['跨步骤一致性', '因果链审查', '分支覆盖审查', '回溯决策'],
 'tools': ['create_recall_request'],
 'methodology': ['检查S1至S6输入输出连接', '核对A-H分支侧重', '识别最早失败节点', '给出后续重跑范围'],
 'quality_gates': ['回溯到最早不完整步骤', '不隐藏剩余不确定性', '达到循环上限时明确限制'],
 'output_focus': ['是否通过', '最早回溯步骤', '跨步问题', '重跑指引'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
