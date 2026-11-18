"""知识图谱 Pilot 规模与质量门禁的版本化统一口径。"""

from __future__ import annotations

PILOT_REQUIREMENTS_VERSION = "defense-kg-pilot-requirements-v3"

# 用户于 2026-10-31 将本地 Pilot 调整为 papers/ 中的 1000 篇中文论文。
# 保留 patent_documents 字段，确保未来引入专利时无需改变契约结构。
PILOT_QUOTAS = {
    "source_documents": 1000,
    "paper_documents": 1000,
    "patent_documents": 0,
    "gold_documents": 300,
}

PILOT_GRAPH_QUOTAS = {
    "accepted_entities": 5000,
    "accepted_relations": 20000,
}


def pilot_requirement_payload() -> dict[str, int | str]:
    """返回可由 API 与界面直接展示的稳定验收阈值。"""
    return {
        "requirements_version": PILOT_REQUIREMENTS_VERSION,
        **PILOT_QUOTAS,
        **PILOT_GRAPH_QUOTAS,
    }
