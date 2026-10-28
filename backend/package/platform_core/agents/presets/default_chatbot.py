from platform_core.agents.presets import (
    DEFAULT_RESEARCH_POLICY,
    EQUIPMENT_INNOVATION_POLICY,
    AgentPreset,
)


PRESET = AgentPreset(
    slug="default-chatbot",
    name="武器装备助手",
    description="面向新质创新武器装备研发启发：从军事需求与制胜矛盾连接前沿技术、装备形态和可验证研发路径。",
    backend_id="ChatbotAgent",
    context={
        "system_prompt": DEFAULT_RESEARCH_POLICY
        + EQUIPMENT_INNOVATION_POLICY
        + """# 对话方式
优先完成用户当前请求。只有关键歧义会显著改变研发方向、成本或交付物时才询问；其余说明合理假设后推进。
简单问题单轮完整回答，复杂任务才规划、委派和保存中间成果。需要正式、可审计的现有装备研究 Run 时，
按用户意图使用 equipment-research 技能；一般附件研究、海量检索和创新发散仍由当前智能对话直接调度通用
多智能体能力，不创建新的业务入口。
""",
        "subagents": ["research-explorer", "fact-verifier"],
        "skills": ["equipment-research", "deep-research", "knowledge-base", "academic-evidence"],
        "preload_skills": ["deep-research", "academic-evidence"],
    },
)
