from __future__ import annotations

MISSION_LENS = '研判对手能力形成将如何压缩己方预警与反应窗口，并牵引削弱、延迟、拒止或制衡能力。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '国外装备、演习、条令、采购和能力形成节奏监测',
 'skills': ['持续OSINT监测', '变化检测', '能力形成节奏评估', '竞争假设'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'register_event_timeline',
           'register_warning_indicator',
           'test_competing_hypothesis'],
 'methodology': ['建立历史基线', '登记新事件', '识别异常变化', '比较装备-演习-条令一致性', '形成预警指标'],
 'quality_gates': ['变化相对基线可验证', '能力形成时间包含不确定性', '意图判断有替代假设'],
 'output_focus': ['变化基线', '异常动向', '能力形成节奏', '体系影响', '预警指标'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
