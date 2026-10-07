from __future__ import annotations

MISSION_LENS = '按军事任务后果和增量价值聚合结论，优先保留能改变打击、反制、拒止、威慑或持续作战机制的Claim。'
QUERY_DOMINANT = False
PROFILE = {'scenario': '跨Agent、跨背景、跨场景和跨分支的发现收敛',
 'skills': ['语义聚类', '冲突保留', '优先级排序', '跨分支关联'],
 'tools': ['prepare_winning_input', 'project_winning_resources'],
 'methodology': ['按共同任务需求聚类', '去重但保留冲突', '建立跨分支因果关联', '形成优先级与回传问题'],
 'quality_gates': ['不得用多数意见覆盖冲突', '每个优先项可追溯到输入Packet', '开放问题被保留'],
 'output_focus': ['需求簇', '冲突', '优先序', '跨分支关联', '开放问题'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
