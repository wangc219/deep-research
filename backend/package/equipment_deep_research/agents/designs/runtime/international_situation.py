from __future__ import annotations

MISSION_LENS = '把联盟、部署、采购和安全态势变化转换为预警窗口、任务压力及拒止/威慑可信度影响。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '国际安全态势、威胁预警、联盟与力量建设研判',
 'skills': ['strategic_osint', 'threat_forecasting', 'force_posture_tracking'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'register_event_timeline',
           'compare_actor_positions',
           'register_warning_indicator',
           'test_competing_hypothesis'],
 'methodology': ['建立事件时间线', '执行行为体-意图-能力三角验证', '识别预警指标', '比较竞争假设'],
 'quality_gates': ['主要判断双源支撑', '时间尺度明确', '高影响低置信判断进入开放问题'],
 'output_focus': ['态势判断', '威胁评估', '战略格局', '对手动向', '场景驱动因素'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
