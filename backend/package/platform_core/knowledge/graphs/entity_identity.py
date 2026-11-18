"""实体与关系主数据的稳定标识规则。"""

from __future__ import annotations

from uuid import UUID, uuid4, uuid5

RELATION_NAMESPACE = UUID("ac85855a-66ed-42a4-aad7-5d0d78450156")


def new_entity_uuid(kb_id: str, normalized_name: str, entity_type: str) -> str:
    """生成不编码名称、语言或类型的候选 UUID；并发幂等由 PostgreSQL 原子分配。"""
    del kb_id, normalized_name, entity_type
    return str(uuid4())


def relation_uuid(kb_id: str, source_entity_id: str, relation_type: str, target_entity_id: str) -> str:
    """按稳定端点 UUID 与有向关系类型生成关系 UUID。"""
    return str(
        uuid5(
            RELATION_NAMESPACE,
            f"{kb_id}\x1f{source_entity_id}\x1f{relation_type}\x1f{target_entity_id}",
        )
    )
