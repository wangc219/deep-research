from __future__ import annotations

MISSION_LENS = '用任务阶段、对手体系和失败条件检验发现—决策—协同—打击—评估—再组织链能否闭合。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '现代多域作战场景、敌方行动方案和环境压力建模',
 'skills': ['scenario_engineering', 'modern_battlespace_analysis', 'adversary_coa_analysis'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'build_scenario_graph',
           'branch_scenario',
           'map_critical_window',
           'map_environment_constraint',
           'stress_test_scenario'],
 'methodology': ['构建背景-力量-目标-阶段-触发器', '生成最可能/最危险/替代COA', '执行环境压力测试', '映射能力压力点'],
 'quality_gates': ['至少两个场景分支', '关键节点有证据或显式假设', '环境约束映射到装备功能'],
 'output_focus': ['场景框架', '敌方COA', '关键时间窗', '环境约束', '能力压力点'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
