"""知识库结构化 Block 元数据的幂等 PostgreSQL 演进。"""

PARSED_BLOCK_SCHEMA_STATEMENTS = (
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS document_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS page_number INTEGER",
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS block_type VARCHAR(64)",
    ("ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS heading_path JSONB NOT NULL DEFAULT '[]'::jsonb"),
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS bbox JSONB",
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS parser_name VARCHAR(128)",
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS parser_version VARCHAR(128)",
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS source_metadata JSONB",
    ("CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_file_page ON knowledge_chunks(file_id, page_number, chunk_index)"),
)
