"""Schema constants for the extraction experiment."""

SCHEMA_VERSION = "extraction-experiment-v2"
RELATION_QUALITY_RULE_VERSION = "relation-quality-rules-v2"

ENTITY_TYPES = {
    "Principle",
    "Technology",
    "EngineeringObject",
    "Capability",
    "Metric",
    "RequirementGap",
    "Scenario",
    "Constraint",
    "Source",
}

RELATION_TYPES = {
    "supports",
    "implements",
    "enables",
    "drives",
    "responsible_for",
    "has_capability",
    "constrains",
    "applies_to",
    "measured_by",
    "indicates",
    "addresses",
    "evolves_to",
    "impacts",
    "similar_to",
    "contrasts_with",
}

SEVEN_RELATION_TYPES = {
    "enables",
    "drives",
    "implements",
    "has_capability",
    "applies_to",
    "constrains",
    "responsible_for",
}

RELATION_INFERENCE_ELIGIBILITY = {
    "true",
    "false",
    "needs_review",
}

PATH_SAFE_RELATION_TYPES = {
    "enables",
    "supports",
    "implements",
    "applies_to",
    "drives",
    "has_capability",
}

CONTEXT_ONLY_RELATION_TYPES = {
    "responsible_for",
    "contrasts_with",
    "similar_to",
    "measured_by",
}

NEEDS_REVIEW_RELATION_TYPES = {
    "evolves_to",
    "addresses",
    "impacts",
    "constrains",
    "indicates",
}

CLAIM_TYPES = {
    "fact_statement",
    "proposal",
    "prediction",
    "opinion",
    "weak_signal",
    "contradiction",
}

MODALITIES = {
    "asserted",
    "proposed",
    "possible",
    "expected",
    "uncertain",
    "negated",
}

ASSERTION_STRENGTHS = {
    "strong",
    "weak",
    "speculative",
    "negated",
}

WEAK_MODALITY_TERMS = {
    "可能",
    "有望",
    "预期",
    "预计",
    "未来",
    "发展方向",
    "或将",
    "可用于",
    "潜在",
    "提出",
    "建议",
    "探索",
    "认为",
    "may",
    "might",
    "could",
    "potential",
    "proposed",
    "expected",
}

NEGATION_TERMS = {
    "不能",
    "无法",
    "未能",
    "不足",
    "缺乏",
    "限制",
    "困难",
    "不可",
    "not",
    "cannot",
    "unable",
    "lack",
    "limited",
}

ENTITY_KEYWORDS = {
    "Technology": [
        "技术",
        "算法",
        "模型",
        "系统",
        "方法",
        "架构",
        "感知",
        "识别",
        "测控",
        "通信",
        "防御",
    ],
    "EngineeringObject": [
        "装备",
        "平台",
        "无人机",
        "发动机",
        "体系",
        "载荷",
        "导弹",
        "卫星",
    ],
    "Capability": [
        "能力",
        "探测",
        "跟踪",
        "识别",
        "通信",
        "控制",
        "预警",
        "拦截",
    ],
    "Metric": [
        "精度",
        "距离",
        "速度",
        "成本",
        "价格",
        "性能",
        "效率",
        "可靠性",
    ],
    "Constraint": [
        "约束",
        "限制",
        "困难",
        "风险",
        "不足",
        "瓶颈",
        "问题",
    ],
}
