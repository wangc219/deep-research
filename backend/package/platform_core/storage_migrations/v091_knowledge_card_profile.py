"""补齐 KnowledgeCard 的指标、迁移、GraphRAG 与叙事画像。"""

KNOWLEDGE_CARD_PROFILE_SCHEMA_STATEMENTS = (
    (
        "ALTER TABLE IF EXISTS knowledge_document_cards "
        "ADD COLUMN IF NOT EXISTS key_metrics JSONB NOT NULL DEFAULT '[]'::jsonb"
    ),
    (
        "ALTER TABLE IF EXISTS knowledge_document_cards "
        "ADD COLUMN IF NOT EXISTS transfer_potential JSONB NOT NULL DEFAULT '{}'::jsonb"
    ),
    (
        "ALTER TABLE IF EXISTS knowledge_document_cards "
        "ADD COLUMN IF NOT EXISTS graph_rag_hints JSONB NOT NULL DEFAULT '{}'::jsonb"
    ),
    (
        "ALTER TABLE IF EXISTS knowledge_document_cards "
        "ADD COLUMN IF NOT EXISTS narrative_report JSONB NOT NULL DEFAULT '{}'::jsonb"
    ),
)
