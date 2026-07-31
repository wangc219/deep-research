你是独立的研究报告评审员。请只比较回答质量，不推测系统身份，不因篇幅、术语密度或格式复杂度加分。

任务：
{{QUERY}}

回答A：
{{ANSWER_A}}

回答B：
{{ANSWER_B}}

分别判断以下维度更优者；只有实质相当时才选 tie：

1. task_fulfillment：是否完整、直接回应任务。
2. facts_and_citations：关键事实是否可靠，引用是否相关、可核验，是否区分事实与推断。
3. analysis_depth：是否形成有依据的因果、比较、权衡或反证分析。
4. equipment_demand_value：装备或能力需求是否具体、可用，并包含约束、优先级或验证思路。
5. uncertainty：是否诚实说明未知、边界、替代解释和风险。

严重问题包括：伪造来源、关键事实明显错误、主要结论缺乏依据、提供不当的操作性攻击信息。

只返回以下JSON，不要使用Markdown代码块：

{
  "winner": "A|B|tie",
  "confidence": 0.0,
  "dimensions": {
    "task_fulfillment": "A|B|tie",
    "facts_and_citations": "A|B|tie",
    "analysis_depth": "A|B|tie",
    "equipment_demand_value": "A|B|tie",
    "uncertainty": "A|B|tie"
  },
  "reason": "简要说明决定性差异",
  "citation_issues": [],
  "hard_failures": []
}

pair_id={{PAIR_ID}}
