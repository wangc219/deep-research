from __future__ import annotations

from typing import Any

CORE_ONTOLOGY = {
    "Concept": "需要解释、解决或约束研发方向的概念、需求、问题或环境条件",
    "Principle": "可说明技术为何有效的物理、数学、材料、信息或控制机理",
    "Technology": "可实现、验证或集成的算法、材料、器件、工艺、架构或技术方案",
    "Capability": "由技术带来的可测量、可验证能力、性能或效能收益",
    "Application": "明确的装备、系统环节、任务支撑、保障流程或使用场景",
}

MILITARY_VALUE_DIMENSIONS = (
    "信息获取与认知决策",
    "复杂对抗环境适应性",
    "生存性与防护韧性",
    "任务效能与精确性",
    "自主智能与人机协同",
    "体系集成与互操作性",
    "战备保障与全寿命可靠性",
    "成本能耗与供应链可控性",
)

RELATION_METADATA_FIELDS = (
    "claim_level",
    "confidence",
    "evidence_quote",
    "reasoning_basis",
    "military_value_dimensions",
    "expected_capability_gain",
    "application_direction",
    "uncertainty",
    "expert_review_required",
)

CLAIM_LEVELS = {"Fact", "Inference", "Hypothesis"}
MAX_HYPOTHESES_PER_CHUNK = 3
DEFAULT_MAX_HYPOTHESES_PER_CHUNK = 2


def build_defense_quality_contract(*, enable_hypotheses: bool, max_hypotheses: int) -> str:
    """生成面向武器装备研发的紧凑抽取质量契约。"""
    ontology = "\n".join(f"  - {label}: {description}" for label, description in CORE_ONTOLOGY.items())
    dimensions = "、".join(MILITARY_VALUE_DIMENSIONS)
    hypothesis_instruction = (
        f"允许在同一文本证据范围内提出最多 {max_hypotheses} 条高价值探索关系"
        if enable_hypotheses and max_hypotheses > 0
        else "不要输出任何探索性或假设关系"
    )
    return f"""武器装备研发知识抽取质量契约：
1. 核心本体：
{ontology}
   可使用 Requirement、Threat、Constraint、Metric、Material、Component 等扩展类型，
   但扩展实体必须直接服务核心研发链。不要把宽泛主题、宣传性表述、作者、机构、论文、章节、
   参考文献或证据片段建成实体；过滤只有背景意义、没有研发作用的名称。
2. 抽取前在内部完成以下检查，但不要输出思考过程：
   a) 识别文本主贡献及其与武器装备研发的实质关联；
   b) 从证据恢复“概念/需求 → 原理 → 技术 → 能力 → 应用”主线，允许证据不足时缺项；
   c) 识别有独立证据的作用原理/机理、关键模块、约束、指标、验证结果和并行技术路线；
   d) 评估技术新颖性、工程可行性、成熟度、转化条件和潜在军事价值；
   e) 执行实体边界、同义名称、关系方向、证据和事实/推断/假设分层自检。
3. 军事价值只能从以下高层维度评价：{dimensions}。
   价值判断必须说明原文依据和适用条件；不得从局部实验效果直接外推为工程化、列装或实战能力。
   优先保留能够形成“机理依据—技术实现—可验证能力收益—装备/系统环节”闭环的知识，
   以及决定转化可行性的关键指标、接口、材料/器件、工程约束、成熟度和验证结果。
   high 仅用于证据较强且能明确支撑重要能力或系统价值的贡献；medium 用于技术实质明确但验证或转化条件不完整的贡献；
   宽泛背景、口号式潜力和无法落到研发决策的 low 内容应放入 discarded_noise，不要扩展成图谱节点。
4. 关系分层：
   - Fact：当前文本有直接、明确陈述，evidence_quote 必须是原文短句。
   - Inference：可由当前文本中的机理、指标或上下文直接推出，必须给出 reasoning_basis 和 uncertainty。
   - Hypothesis：{hypothesis_instruction}；只能连接文本中已经存在且有证据的实体，
     优先表达并列技术互补、原理迁移或技术到能力/应用的潜在桥接。
     label 使用 COMBINES_WITH、PREDICTED_LINK、TRANSFERABLE_TO 或 POTENTIAL_FOR，
     必须给出 reasoning_basis、expected_capability_gain、uncertainty，且 expert_review_required=true。
5. 深度发散边界：不强制补齐五类实体，不为追求数量创造空泛节点；证据弱时宁缺勿滥。
   不得把可能性写成既成事实，不得把实验室局部效果外推成系统能力；
   不生成制造参数、部署流程、目标选择、攻击步骤、战术运用或原文没有的可操作细节。
6. 去重与命名：同一实体统一使用最完整稳定名称和同一 label；同义简称合并，
   不因型号修饰、大小写、空格、代词或句式差异拆成重复实体。
7. Technology 实体的 attributes 优先记录有原文依据的“技术实质”“作用机理”“技术指标”
   “适用条件”“工程约束”“成熟度”“验证状态”“转化潜力”“潜在军事价值维度”；不得猜测属性。
8. 每条关系补充字段：claim_level、confidence(0~1)、evidence_quote、reasoning_basis、
   military_value_dimensions(数组)、expected_capability_gain、application_direction、uncertainty、
   expert_review_required。无内容时使用空字符串或空数组，不得省略字段。
"""


def normalize_relation_metadata(relation: dict[str, Any]) -> dict[str, Any]:
    """校验并收敛模型输出的关系分层与研发价值元数据。"""
    claim_level = str(relation.get("claim_level") or "Inference").strip().title()
    if claim_level not in CLAIM_LEVELS:
        claim_level = "Inference"

    try:
        confidence = float(relation.get("confidence", 0.5))
    except (TypeError, ValueError, OverflowError):
        confidence = 0.5
    confidence = max(0.0, min(confidence, 1.0))

    dimensions = relation.get("military_value_dimensions") or []
    if not isinstance(dimensions, list):
        dimensions = []
    allowed_dimensions = set(MILITARY_VALUE_DIMENSIONS)
    dimensions = list(
        dict.fromkeys(str(value).strip() for value in dimensions if str(value).strip() in allowed_dimensions)
    )

    expert_review_required = relation.get("expert_review_required")
    if not isinstance(expert_review_required, bool):
        expert_review_required = claim_level == "Hypothesis"
    if claim_level == "Hypothesis":
        expert_review_required = True

    return {
        "claim_level": claim_level,
        "confidence": confidence,
        "evidence_quote": _clean_text(relation.get("evidence_quote"), 1000),
        "reasoning_basis": _clean_text(relation.get("reasoning_basis"), 2000),
        "military_value_dimensions": dimensions,
        "expected_capability_gain": _clean_text(relation.get("expected_capability_gain"), 1000),
        "application_direction": _clean_text(relation.get("application_direction"), 1000),
        "uncertainty": _clean_text(relation.get("uncertainty"), 1000),
        "expert_review_required": expert_review_required,
    }


def _clean_text(value: Any, max_length: int) -> str:
    return str(value or "").strip()[:max_length]
