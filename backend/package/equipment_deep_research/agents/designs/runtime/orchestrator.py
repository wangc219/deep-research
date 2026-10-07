from __future__ import annotations

MISSION_LENS = '所有蓝图和Agent选择都要落到可验证的打击、歼灭、反制、拒止、威慑、抗毁或持续作战效果，避免只优化流程覆盖。'
QUERY_DOMINANT = False
PROFILE = {'scenario': '资深JS专家人格下的需求语义解析、A-H/OTHER驱动识别、S1-S6蓝图、Agent DAG和四级循环控制',
 'skills': ['requirement_semantics_analysis',
            'discovery_driver_recognition',
            'discovery_blueprint_generation',
            'dag_loop_orchestration'],
 'tools': ['analyze_research_request',
           'classify_discovery_drivers',
           'build_discovery_blueprint',
           'plan_execution_waves',
           'evaluate_loop_transition'],
 'methodology': ['形成任务语义卡和问题树',
                 '逐项评估A-H并记录OTHER未覆盖驱动源',
                 '组合S1-S6强度与回溯点',
                 '按能力覆盖选择最小充分Agent集合',
                 '构建DAG波次并设置内中外L4循环预算'],
 'quality_gates': ['专家显式边界不被覆盖', '主次驱动源有任务依据', '能力标签无关键遗漏', '并发与结构化交接关系明确', '无信息增益循环停止'],
 'output_focus': ['任务语义卡', '驱动源评分', '发现蓝图', '能力覆盖矩阵', 'Agent DAG与执行波次', '循环预算回溯点与停止条件'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
