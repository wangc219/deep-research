from __future__ import annotations

MISSION_LENS = '检验跨域数据、权限、时序和接口是否真正缩短火力闭环并提高拒止、反制与抗毁能力。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '多域能力矩阵、接口依赖、协同缝隙与融合效果链',
 'skills': ['跨域矩阵', '接口分析', '协同缝隙识别', '融合效果链'],
 'tools': ['build_scenario_graph',
           'map_task_capability',
           'build_coordination_dependency',
           'stress_test_scenario'],
 'methodology': ['建立域-任务-能力矩阵', '分析数据/指挥/时序/保障接口', '定位协同缝隙', '比较融合收益和耦合风险'],
 'quality_gates': ['覆盖相关作战域', '接口条件可验证', '融合建议包含降级运行方式'],
 'output_focus': ['跨域矩阵', '域间接口', '协同缝隙', '融合效果链', '融合能力需求'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
