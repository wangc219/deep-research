from __future__ import annotations

MISSION_LENS = '围绕体系节点失效、替代链路和级联效应，评估打击/反制闭环与战损后任务续接能力。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '红蓝体系模型、任务依赖、级联脆弱性与替代链路',
 'skills': ['体系建模', '依赖图分析', '脆弱性分析', '简化推演'],
 'tools': ['build_scenario_graph',
           'map_task_capability',
           'build_coordination_dependency',
           'stress_test_scenario',
           'test_competing_hypothesis'],
 'methodology': ['定义体系边界', '绘制感知-决策-行动-保障链', '识别单点与级联失效', '压力测试替代链路', '形成补链强链需求'],
 'quality_gates': ['脆弱点有依赖路径依据', '区分模型假设与事实', '建议保持防御性和任务级'],
 'output_focus': ['体系边界', '任务依赖', '关键脆弱点', '替代链路', '补链强链需求'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
