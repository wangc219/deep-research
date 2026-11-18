"""逐关系复核审计字段的幂等迁移。"""

RELATION_REVIEW_SCHEMA_STATEMENTS = (
    ("ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS secondary_review JSONB"),
)
