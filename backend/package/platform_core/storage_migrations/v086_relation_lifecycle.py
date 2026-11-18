"""为权威关系增加生命周期、失效时间和版本的幂等迁移。"""

RELATION_LIFECYCLE_SCHEMA_STATEMENTS = (
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triples "
        "ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active'"
    ),
    ("ALTER TABLE IF EXISTS knowledge_graph_triples ADD COLUMN IF NOT EXISTS superseded_by_triple_id VARCHAR(64)"),
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triples "
        "ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    ),
    "ALTER TABLE IF EXISTS knowledge_graph_triples ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ",
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triples "
        "ADD COLUMN IF NOT EXISTS relation_version INTEGER NOT NULL DEFAULT 1"
    ),
    "UPDATE knowledge_graph_triples SET lifecycle_status = 'active' WHERE lifecycle_status IS NULL",
    "UPDATE knowledge_graph_triples SET valid_from = COALESCE(valid_from, created_at, NOW())",
    "UPDATE knowledge_graph_triples SET relation_version = 1 WHERE relation_version IS NULL",
    "ALTER TABLE IF EXISTS knowledge_graph_triples ALTER COLUMN lifecycle_status SET DEFAULT 'active'",
    "ALTER TABLE IF EXISTS knowledge_graph_triples ALTER COLUMN lifecycle_status SET NOT NULL",
    "ALTER TABLE IF EXISTS knowledge_graph_triples ALTER COLUMN valid_from SET DEFAULT NOW()",
    "ALTER TABLE IF EXISTS knowledge_graph_triples ALTER COLUMN valid_from SET NOT NULL",
    "ALTER TABLE IF EXISTS knowledge_graph_triples ALTER COLUMN relation_version SET DEFAULT 1",
    "ALTER TABLE IF EXISTS knowledge_graph_triples ALTER COLUMN relation_version SET NOT NULL",
    "ALTER TABLE IF EXISTS knowledge_graph_triples DROP CONSTRAINT IF EXISTS ck_kg_triple_lifecycle_status",
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triples ADD CONSTRAINT ck_kg_triple_lifecycle_status "
        "CHECK (lifecycle_status IN ('active', 'invalid', 'superseded'))"
    ),
    "ALTER TABLE IF EXISTS knowledge_graph_triples DROP CONSTRAINT IF EXISTS ck_kg_triple_relation_version",
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triples ADD CONSTRAINT ck_kg_triple_relation_version "
        "CHECK (relation_version >= 1)"
    ),
    "ALTER TABLE IF EXISTS knowledge_graph_triples DROP CONSTRAINT IF EXISTS ck_kg_triple_supersession",
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triples ADD CONSTRAINT ck_kg_triple_supersession CHECK ("
        "(lifecycle_status = 'superseded' AND superseded_by_triple_id IS NOT NULL AND valid_to IS NOT NULL) "
        "OR (lifecycle_status = 'invalid' AND superseded_by_triple_id IS NULL AND valid_to IS NOT NULL) "
        "OR (lifecycle_status = 'active' AND superseded_by_triple_id IS NULL AND valid_to IS NULL)"
        ")"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_triple_lifecycle "
        "ON knowledge_graph_triples(kb_id, lifecycle_status, updated_at)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_triple_superseded_by "
        "ON knowledge_graph_triples(kb_id, superseded_by_triple_id) "
        "WHERE superseded_by_triple_id IS NOT NULL"
    ),
)
