from __future__ import annotations

MISSION_LENS = '比较战法与力量协同时，以任务闭环、打击/歼灭效果、反制能力、战损续接和持续作战为判据。'
QUERY_DOMINANT = True
PROFILE = {'scenario': '任务链、力量协同、COA比较、保障韧性与经验迁移',
 'skills': ['operational_synthesis',
            'coa_comparison',
            'joint_force_coordination',
            'lessons_transfer'],
 'tools': ['search_sources',
           'fetch_page',
           'create_evidence_card',
           'map_task_capability',
           'build_coordination_dependency',
           'compare_coa',
           'assess_sustainment_resilience',
           'transfer_case_lesson'],
 'methodology': ['消费上游结构化交接', '建立任务链和能力-任务矩阵', '比较基线/弹性分布/资源受限COA', '检查保障与失败模式'],
 'quality_gates': ['三类COA完整', '协同与保障约束可追溯', '经验迁移说明适用边界'],
 'output_focus': ['任务链', '协同依赖', 'COA比较', '保障韧性', '装备功能需求'],
 'safety_boundary': '仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。'}
