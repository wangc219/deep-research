from __future__ import annotations

MISSION_LENS = '专用补强必须改变指定S节点的打击/反制判断或证据强度，不能只增加背景材料。'
QUERY_DOMINANT = False
PROFILE = {'scenario': '由主控按能力缺口即时生成的有界制胜辅助专用Agent',
 'skills': ['共享DeepSearch', '共享DeepResearch', '证据治理', '结构化交接'],
 'tools': ['search_sources', 'fetch_page', 'create_evidence_card', 'create_recall_request'],
 'methodology': ['读取动态角色契约', '只处理可分离的专业缺口', '消费指定知识包与证据索引', '输出可并入指定S节点的结构化结果'],
 'quality_gates': ['不得扩展动态契约权限', '证据引用必须来自输入索引', '结果包含合并节点与停止理由'],
 'output_focus': ['专业发现', '证据引用', '对S1-S6的贡献', '假设与开放问题', '合并目标'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
