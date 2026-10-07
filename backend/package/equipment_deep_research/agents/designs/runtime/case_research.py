from __future__ import annotations

MISSION_LENS = '从战例中提炼改变打击链、成本交换、反制窗口、体系抗毁和持续作战的因果规律及迁移边界。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '多语言战例检索、事实还原、因果链和跨案例迁移',
 'skills': ['多语言深度搜索', '时序事件重建', '因果链分析', '类比与反事实推理'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'register_event_timeline',
           'transfer_case_lesson',
           'test_competing_hypothesis'],
 'methodology': ['界定案例', '重建事实时间线', '标记关键决策点', '构建因果链', '跨案例比较', '映射未来场景'],
 'quality_gates': ['事实与事后推断分离', '关键因果至少有证据链', '迁移边界完整'],
 'output_focus': ['事实时间线', '参与方与装备', '关键决策', '因果链', '跨案例模式', '未来映射'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
