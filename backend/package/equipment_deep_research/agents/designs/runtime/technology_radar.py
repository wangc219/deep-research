from __future__ import annotations

MISSION_LENS = '判断技术能否带来探测、决策、火力、毁伤、反制、抗扰、机动或保障环节的任务级跃迁。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '前沿技术信号、成熟度、能力潜力和颠覆场景',
 'skills': ['技术雷达', 'technology_readiness_analysis', '技术潜力评估', '场景反推'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'assess_technology_readiness',
           'compare_equipment_capability',
           'test_competing_hypothesis'],
 'methodology': ['扫描论文专利项目与试验', '评估TRL和工程节点', '识别工业与成本约束', '反向构造颠覆场景', '设计阶段验证'],
 'quality_gates': ['技术信号多源核验', '成熟度和能力潜力分开', '限制条件完整'],
 'output_focus': ['技术信号', '成熟度', '能力潜力', '限制条件', '颠覆场景', '验证路线'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
