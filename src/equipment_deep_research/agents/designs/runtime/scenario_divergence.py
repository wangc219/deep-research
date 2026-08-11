from __future__ import annotations

MISSION_LENS = '候选方向只有在能够改变未来战争中的打击、反制、拒止、威慑或体系生存机制时才进入下游。'
QUERY_DOMINANT = False
PROFILE = {'scenario': '智能模式下的开放式需求与场景发散',
 'skills': ['问题重构', '竞争假设', '场景发散', '分支推荐'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'build_scenario_graph',
           'branch_scenario',
           'test_competing_hypothesis'],
 'methodology': ['扫描弱信号', '重构候选问题', '形成竞争假设', '生成候选场景', '推荐A-H分支'],
 'quality_gates': ['候选方向彼此有区分度', '边界假设显式', '不得把想象当事实'],
 'output_focus': ['候选主题', '候选场景', '竞争假设', '推荐分支', '边界假设'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
