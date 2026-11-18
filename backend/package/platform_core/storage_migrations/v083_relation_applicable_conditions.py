"""关系适用条件字段的幂等迁移。"""

RELATION_APPLICABLE_CONDITIONS_SCHEMA_STATEMENTS = (
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions "
        "ADD COLUMN IF NOT EXISTS applicable_conditions JSONB NOT NULL DEFAULT '[]'::jsonb"
    ),
    (
        "ALTER TABLE IF EXISTS knowledge_graph_hypotheses "
        "ADD COLUMN IF NOT EXISTS applicable_conditions JSONB NOT NULL DEFAULT '[]'::jsonb"
    ),
    (
        "UPDATE knowledge_graph_triple_mentions SET applicable_conditions = '[]'::jsonb "
        "WHERE applicable_conditions IS NULL"
    ),
    ("UPDATE knowledge_graph_hypotheses SET applicable_conditions = '[]'::jsonb WHERE applicable_conditions IS NULL"),
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions "
        "ALTER COLUMN applicable_conditions SET DEFAULT '[]'::jsonb, "
        "ALTER COLUMN applicable_conditions SET NOT NULL"
    ),
    (
        "ALTER TABLE IF EXISTS knowledge_graph_hypotheses "
        "ALTER COLUMN applicable_conditions SET DEFAULT '[]'::jsonb, "
        "ALTER COLUMN applicable_conditions SET NOT NULL"
    ),
)
