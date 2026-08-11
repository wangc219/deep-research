from __future__ import annotations

MISSION_LENS = '以保护关键任务和基础设施、限制威胁扩散、恢复行动能力及实施可控反制为军事价值边界。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '非传统安全威胁、新型场景、跨部门协同和韧性需求',
 'skills': ['新威胁扫描', '非传统场景工程', '跨部门边界分析', '法律伦理审查'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'build_scenario_graph',
           'map_environment_constraint',
           'test_competing_hypothesis'],
 'methodology': ['扫描威胁与触发条件', '构造新场景', '识别跨部门责任和资源', '优先形成非致命与韧性能力', '审查法律伦理边界'],
 'quality_gates': ['民用影响和法律边界明确', '跨部门接口完整', '场景不过度军事化'],
 'output_focus': ['威胁画像', '触发条件', '跨部门边界', '韧性能力', '法律伦理限制'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
