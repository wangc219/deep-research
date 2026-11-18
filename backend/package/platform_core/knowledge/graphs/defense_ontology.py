"""军事武器装备知识图谱的版本化核心本体。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class EntityTypeDefinition:
    code: str
    name_zh: str
    description: str


@dataclass(frozen=True, slots=True)
class RelationTypeDefinition:
    code: str
    name_zh: str
    description: str
    head_types: tuple[str, ...]
    tail_types: tuple[str, ...]
    directed: bool = True
    allow_self: bool = False
    hypothesis_only: bool = False


@dataclass(frozen=True, slots=True)
class OntologyDefinition:
    version: str
    name: str
    entity_types: tuple[EntityTypeDefinition, ...]
    relation_types: tuple[RelationTypeDefinition, ...]

    @property
    def entity_type_by_code(self) -> dict[str, EntityTypeDefinition]:
        return {item.code: item for item in self.entity_types}

    @property
    def relation_type_by_code(self) -> dict[str, RelationTypeDefinition]:
        return {item.code: item for item in self.relation_types}


ENTITY_TYPES: Final = (
    EntityTypeDefinition("ScientificPrinciple", "科学原理", "物理、数学、材料、信息或控制等作用机理"),
    EntityTypeDefinition("KeyTechnology", "关键技术", "可实现、验证或集成的技术方案"),
    EntityTypeDefinition("AlgorithmModel", "算法模型", "算法、模型、控制方法和软件方法"),
    EntityTypeDefinition("Material", "材料", "功能材料、结构材料和复合材料"),
    EntityTypeDefinition("Component", "技术组件", "芯片、传感器、模块、器件和子系统"),
    EntityTypeDefinition("ProductSystem", "产品系统", "装备、平台、系统和产品概念"),
    EntityTypeDefinition("Capability", "产品能力", "可测量的性能、效能或任务能力"),
    EntityTypeDefinition("ApplicationScenario", "应用场景", "装备环节、任务场景和保障流程"),
    EntityTypeDefinition("Domain", "技术领域", "技术分类和跨领域归属"),
    EntityTypeDefinition("Achievement", "技术成果", "论文、专利、样机、试验和工程成果"),
    EntityTypeDefinition("Metric", "技术指标", "数值、单位、测试条件和性能指标"),
    EntityTypeDefinition("Constraint", "约束条件", "环境、接口、成本、工程和供应链约束"),
)

P = "ScientificPrinciple"
T = "KeyTechnology"
A = "AlgorithmModel"
M = "Material"
C = "Component"
S = "ProductSystem"
K = "Capability"
U = "ApplicationScenario"
D = "Domain"
H = "Achievement"
METRIC = "Metric"
X = "Constraint"

RELATION_TYPES: Final = (
    RelationTypeDefinition("BASED_ON", "基于", "技术实现所依据的科学原理", (T, A, C, S), (P,)),
    RelationTypeDefinition("USES_TECHNOLOGY", "使用技术", "技术或系统使用另一项技术资源", (T, S), (T, A, M, C)),
    RelationTypeDefinition("IMPLEMENTS", "实现", "算法或组件实现技术或原理", (A, C), (T, P)),
    RelationTypeDefinition("COMPOSED_OF", "组成", "技术或系统由组件、材料或算法构成", (T, S), (C, M, A)),
    RelationTypeDefinition("ENABLES_CAPABILITY", "形成能力", "原理或技术形成可验证能力", (P, T, A, C), (K,)),
    RelationTypeDefinition("SUPPORTS_APPLICATION", "支撑应用", "能力或系统支撑应用场景", (K, S), (U,)),
    RelationTypeDefinition("APPLIED_TO", "应用于", "技术、算法或组件应用于系统或场景", (T, A, C), (S, U)),
    RelationTypeDefinition("PRODUCES_ACHIEVEMENT", "产生成果", "技术或算法产出论文、专利、样机或试验", (T, A), (H,)),
    RelationTypeDefinition("BELONGS_TO_DOMAIN", "属于领域", "核心知识对象归属技术领域", (P, T, K, U), (D,)),
    RelationTypeDefinition("MEASURED_BY", "由指标度量", "技术、能力或系统由指标度量", (T, K, S), (METRIC,)),
    RelationTypeDefinition("CONSTRAINED_BY", "受约束", "技术、能力或系统受条件限制", (T, K, S), (X,)),
    RelationTypeDefinition("IMPROVES", "提升", "技术或组件提升技术或能力", (T, C), (T, K)),
    RelationTypeDefinition("VALIDATED_BY", "由成果验证", "技术或能力由成果、试验或样机验证", (T, K), (H,)),
    RelationTypeDefinition("EVOLVES_FROM", "演化自", "新技术或系统由历史方案演化", (T, S), (T, S)),
    RelationTypeDefinition("REPLACES", "替代", "新技术、组件或系统替代旧对象", (T, C, S), (T, C, S)),
    RelationTypeDefinition(
        "POTENTIAL_FOR", "潜在用于", "证据不足的潜在应用关系", (P, T, A, C, K), (K, S, U), hypothesis_only=True
    ),
    RelationTypeDefinition(
        "TRANSFERABLE_TO", "可迁移至", "有待验证的跨领域技术迁移", (P, T, A), (T, S, U), hypothesis_only=True
    ),
    RelationTypeDefinition(
        "COMBINES_WITH", "可组合", "有待验证的技术互补组合", (T, A, C), (T, A, C), hypothesis_only=True
    ),
    RelationTypeDefinition(
        "PREDICTED_LINK",
        "预测关联",
        "模型发现但尚未验证的关联",
        tuple(item.code for item in ENTITY_TYPES),
        tuple(item.code for item in ENTITY_TYPES),
        hypothesis_only=True,
    ),
)

DEFENSE_ONTOLOGY_V1: Final = OntologyDefinition(
    version="defense-kg-1.0",
    name="军事武器装备技术核心本体",
    entity_types=ENTITY_TYPES,
    relation_types=RELATION_TYPES,
)

ENTITY_TYPE_ALIASES: Final = {
    "principle": P,
    "原理": P,
    "科学原理": P,
    "technology": T,
    "技术": T,
    "关键技术": T,
    "algorithm": A,
    "model": A,
    "算法": A,
    "算法模型": A,
    "material": M,
    "材料": M,
    "component": C,
    "组件": C,
    "器件": C,
    "技术组件": C,
    "product": S,
    "system": S,
    "产品": S,
    "系统": S,
    "产品系统": S,
    "capability": K,
    "能力": K,
    "产品能力": K,
    "application": U,
    "scenario": U,
    "应用": U,
    "应用场景": U,
    "domain": D,
    "领域": D,
    "achievement": H,
    "成果": H,
    "技术成果": H,
    "metric": METRIC,
    "指标": METRIC,
    "技术指标": METRIC,
    "constraint": X,
    "约束": X,
    "约束条件": X,
}


def canonical_entity_type(value: str) -> str:
    """将中英文旧标签收敛到本体稳定编码。"""
    cleaned = str(value or "").strip()
    if cleaned in DEFENSE_ONTOLOGY_V1.entity_type_by_code:
        return cleaned
    return ENTITY_TYPE_ALIASES.get(cleaned.casefold(), cleaned)


def validate_relation_types(head_type: str, relation_type: str, tail_type: str) -> bool:
    """检查关系端点是否符合本体声明。"""
    relation = DEFENSE_ONTOLOGY_V1.relation_type_by_code.get(relation_type)
    if relation is None:
        return False
    canonical_head = canonical_entity_type(head_type)
    canonical_tail = canonical_entity_type(tail_type)
    return canonical_head in relation.head_types and canonical_tail in relation.tail_types


def ontology_payload() -> dict:
    """生成 sidecar 和管理 API 共用的可序列化本体。"""
    return {
        "version": DEFENSE_ONTOLOGY_V1.version,
        "name": DEFENSE_ONTOLOGY_V1.name,
        "entity_types": [
            {"code": item.code, "name_zh": item.name_zh, "description": item.description}
            for item in DEFENSE_ONTOLOGY_V1.entity_types
        ],
        "relation_types": [
            {
                "code": item.code,
                "name_zh": item.name_zh,
                "description": item.description,
                "head_types": list(item.head_types),
                "tail_types": list(item.tail_types),
                "directed": item.directed,
                "allow_self": item.allow_self,
                "hypothesis_only": item.hypothesis_only,
            }
            for item in DEFENSE_ONTOLOGY_V1.relation_types
        ],
    }
