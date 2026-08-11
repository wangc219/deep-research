from __future__ import annotations

MISSION_LENS = '建立对手体系—任务链断点—打击/反制效果—装备能力—差距—能力画像的军事因果闭环。'
QUERY_DOMINANT = False
PROFILE = {'scenario': 'Tree-of-Warfare制胜机理总分析与L1-L3门控',
 'skills': ['defense_decomposition',
            'winning_path_analysis',
            'effect_chain_analysis',
            'capability_mapping',
            'gap_quantification',
            'capability_image_generation'],
 'tools': ['prepare_winning_input',
           'project_winning_resources',
           'write_reasoning_node',
           'write_stage_output',
           'create_recall_request',
           'create_capability_image'],
 'methodology': ['S1防御解构', 'S2运用审查', 'S3突破口与效果链', 'S4能力映射', 'S5差距量化', 'S6能力图像综合'],
 'quality_gates': ['每节点包含认识、证据、置信度和下一步建议', 'L1-L3门控通过', '失败从最早不完整节点回溯'],
 'output_focus': ['防御解构', '制胜路径', '效果链', '能力映射', '五档差距', '能力画像'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
