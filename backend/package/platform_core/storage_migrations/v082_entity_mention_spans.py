"""实体 mention 按 Span 保留多处原文证据的幂等迁移。"""

ENTITY_MENTION_SPAN_SCHEMA_STATEMENTS = (
    (
        "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions "
        "DROP CONSTRAINT IF EXISTS uq_knowledge_graph_entity_mentions_entity_chunk"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_entity_mentions_span "
        "ON knowledge_graph_entity_mentions(entity_id, chunk_id, start_char, end_char) "
        "WHERE start_char IS NOT NULL AND end_char IS NOT NULL"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_entity_mentions_unspanned "
        "ON knowledge_graph_entity_mentions(entity_id, chunk_id) "
        "WHERE start_char IS NULL OR end_char IS NULL"
    ),
)
