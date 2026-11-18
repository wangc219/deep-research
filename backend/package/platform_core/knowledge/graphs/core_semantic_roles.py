"""五类军事知识主干角色及细粒度本体兼容映射。

定义取自 ``doc_audit_pack`` 的实体抽取规范，但这里只保存可执行的语义契约；
参考目录不是运行时依赖，也不会被当前项目修改或导入。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

CORE_ROLE_ORDER = ("concept", "principle", "technology", "capability", "application")
RESEARCH_THREAD_TYPES = ("main", "side", "parallel")

CORE_ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "concept": {
        "name_zh": "概念",
        "question": "研究什么问题，面向什么对象、需求、环境或威胁",
        "definition": "定义问题空间的军事需求、作战问题、威胁对象、场景环境或体系概念",
        "include": "可跨文献复用，并能回连原理、技术、能力或应用的主题锚点",
        "exclude": "具体算法、模型、系统、能力收益、论文标题、泛领域标签",
        "suffixes": "概念、问题、环境、场景、对象、任务、需求、威胁、体系",
    },
    "principle": {
        "name_zh": "原理",
        "question": "为什么有效，能力收益从何而来",
        "definition": "解释技术有效性、性能边界和能力收益来源的理论、原理、机制或机理",
        "include": "原文用来解释技术、能力收益、性能边界或约束条件的可复用科学基础",
        "exclude": "具体算法、工程流程、软件系统、实验平台、公式中间变量",
        "suffixes": "理论、原理、机制、机理、效应、定律、基础模型、机理模型",
    },
    "technology": {
        "name_zh": "技术",
        "question": "如何实现",
        "definition": "把科学原理转化为工程能力且可设计、验证、复用、集成或迁移的实现方案",
        "include": "方法、算法、模型、材料、器件、组件、工艺、架构和系统级技术方案",
        "exclude": "科学理论、能力收益、装备对象、应用场景、普通工具、一次性实验配置",
        "suffixes": "方法、算法、模型、技术、系统技术、技术方案、框架技术",
    },
    "capability": {
        "name_zh": "能力",
        "question": "最终形成或提升什么能力、功能或效能",
        "definition": "装备、系统、技术或体系形成的可验证功能性军事能力与效能收益",
        "include": "可由技术、应用、指标或证据支撑的感知、通信、控制、协同、防护或保障能力",
        "exclude": "算法名、模型名、平台名、单个数值指标、任务或装备名称",
        "suffixes": "能力、功能、效能",
    },
    "application": {
        "name_zh": "应用",
        "question": "应用到哪里，服务什么装备、平台、任务、场景或体系环节",
        "definition": "技术或能力落地的具体装备系统、平台、任务、场景、保障体系或训练评估应用",
        "include": "能够承接能力落地并回连证据的具体高层应用去向",
        "exclude": "能力收益、具体算法、空泛的军事应用或工程应用、可操作战术细节",
        "suffixes": "装备、系统、平台、任务、作战场景、保障体系、训练系统、评估平台",
    },
}

# 细粒度类型保留不变；五类角色只用于抽取理解、路径组织、检索和创新发现。
# Domain、Constraint 等扩展类型不能仅凭类型编码伪装成 Concept。
ENTITY_TYPE_CORE_ROLE = {
    "Concept": "concept",
    "Requirement": "concept",
    "Threat": "concept",
    "ScientificPrinciple": "principle",
    "Principle": "principle",
    "KeyTechnology": "technology",
    "AlgorithmModel": "technology",
    "Material": "technology",
    "Component": "technology",
    "Technology": "technology",
    "Capability": "capability",
    "ProductSystem": "application",
    "ApplicationScenario": "application",
    "Application": "application",
}


def core_role_for_entity_type(entity_type: str) -> str:
    """返回细粒度类型对应的五类上位角色；扩展类型返回空字符串。"""
    cleaned = str(entity_type or "").strip()
    direct = ENTITY_TYPE_CORE_ROLE.get(cleaned)
    if direct:
        return direct
    folded = cleaned.casefold()
    for code, role in ENTITY_TYPE_CORE_ROLE.items():
        if folded == code.casefold():
            return role
    return ""


def build_core_role_guidance(entity_types: Iterable[Any]) -> str:
    """生成供项目 LLM 使用的五类定义、边界、命名和当前本体映射。"""
    available: dict[str, list[str]] = {role: [] for role in CORE_ROLE_ORDER}
    supporting: list[str] = []
    for item in entity_types:
        code = str(item.get("code") if isinstance(item, dict) else getattr(item, "code", "")).strip()
        if not code:
            continue
        role = core_role_for_entity_type(code)
        if role:
            available[role].append(code)
        else:
            supporting.append(code)

    lines = ["五类主干语义按上下文角色判定，不得只看词尾："]
    for role in CORE_ROLE_ORDER:
        definition = CORE_ROLE_DEFINITIONS[role]
        codes = "、".join(available[role]) or "当前本体未提供独立编码"
        lines.append(
            f"- {definition['name_zh']}({role})：回答“{definition['question']}”；"
            f"{definition['definition']}。纳入：{definition['include']}；排除：{definition['exclude']}；"
            f"推荐后缀：{definition['suffixes']}；当前可用编码：{codes}。"
        )
    if supporting:
        lines.append(
            "- 扩展类型："
            + "、".join(supporting)
            + "。它们用于补足材料、组件、指标、约束、领域或成果等细节，不能机械替代五类主干角色。"
        )
    lines.extend(
        [
            "Canonical 命名：删除“本文提出/一种/面向/基于实验验证的”等论文表达和非标准的一次性修饰；",
            "保留决定身份的军事领域限定词、型号、材料体系和关键对象，使用中等粒度、跨文献可复用名称；",
            "新术语按“领域限定词 + 核心对象 + 类型后缀”形成候选标准名，英文缩写、译名、长短名进入 aliases；",
            "当前阶段只抽取逐字原文 mention，标准名仍由后续实体对齐治理决定，不得伪造原文或稳定 ID。",
        ]
    )
    return "\n".join(lines)


def build_domain_extraction_guidance(entity_types: Iterable[Any]) -> str:
    """生成贯通主干角色、研究线索和现实落点门的抽取引导。"""
    return "\n".join(
        [
            build_core_role_guidance(entity_types),
            "研究线索分类（research_thread 只表示文献叙事位置，不是新事实或新关系）：",
            "- main：文献的核心问题、关键机理、主要技术贡献、主要能力结果或主要应用落点；",
            "- side：支撑模块、工程约束、验证手段、辅助技术或风险条件；",
            "- parallel：与主方案并列、互补、替代或可组合的同层技术路线；",
            "先识别内容主线，再抽取主线实体；保留有证据价值的辅线和并行路线，但不得为补齐链路凑齐五类。",
            "五类允许缺项；同层并行技术应分别保留，并由原文直接关系连接，不能仅凭并列出现推断互补或替代。",
            "现实场景/战备证据门：仿真、模拟、数字孪生和通用验证平台默认只作为 Evidence/TestSystem 背景，",
            "不能单凭这些词标为核心 Application 或已落地技术；只有邻近原文明示样机、外场实测、系统应用、",
            "装备/任务验证、训练评估或保障落点时，才可作为核心应用/技术候选。不得为了形成完整链路编造实际应用。",
        ]
    )
