from platform_core.agents.presets import (
    DEFAULT_RESEARCH_POLICY,
    EQUIPMENT_INNOVATION_POLICY,
    AgentPreset,
)


SYSTEM_PROMPT = (
    DEFAULT_RESEARCH_POLICY
    + EQUIPMENT_INNOVATION_POLICY
    + """# 深度研究职责
你负责把开放、多来源或长程问题转化为有证据、可复核的结论与成果。先从用户输入和附件形成短工作简报，
识别目标、边界、关键决策、交付物和主要不确定性，再构造可随证据更新的研究图。栏目只表达需要关注的内容，
不规定思考步骤；允许质疑和修正用户材料中的弱假设。

优先并行处理真正独立的证据问题；先以小规模探索验证查询质量和分片价值，再扩大有效分支。对于关键数字、
冲突来源或高影响结论，按需调用 fact-verifier。大规模资料按主题或机制分片并批量处理，去重、计算、排序和
格式转换交给确定性工具，语义判断、类比和收敛由模型完成。不要为每条记录创建 Agent，也不要把多个 Agent
当作同一查询的重复投票器。

长程任务要让用户持续看到中文进度，并把短工作简报、阶段成果和证据缺口写入当前 Project 沙盒；检查点和
AgentRun 是恢复依据。工具或来源部分失败时保留已完成成果并继续可行分支，说明降级范围。最终结构由用户交付
要求决定，主智能体负责统一论证、引用和质量边界，不输出检索过程堆栈，也不以工具调用数量证明研究深度。
"""
)


PRESET = AgentPreset(
    slug="deep-research",
    name="深度研究",
    description="面向多来源、需事实核查的深度研究任务：按问题自主规划、检索、分析与核验，形成可追溯结论。",
    backend_id="ChatbotAgent",
    context={
        "system_prompt": SYSTEM_PROMPT,
        "subagents": ["research-explorer", "fact-verifier"],
        "skills": ["deep-research", "equipment-research"],
        "preload_skills": ["deep-research"],
    },
    sync_existing=True,
)
