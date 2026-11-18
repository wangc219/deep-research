"""知识来源版本、构建运行和验收报告的幂等 PostgreSQL 演进。"""

KNOWLEDGE_GRAPH_ACCEPTANCE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS knowledge_source_documents (
        document_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        file_id VARCHAR(64) NOT NULL REFERENCES knowledge_files(file_id) ON DELETE CASCADE,
        source_type VARCHAR(32) NOT NULL DEFAULT 'unknown',
        language VARCHAR(32) NOT NULL DEFAULT 'unknown',
        domain VARCHAR(256) NOT NULL DEFAULT '',
        content_hash VARCHAR(128),
        current_version INTEGER NOT NULL DEFAULT 1,
        source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_knowledge_source_document_file UNIQUE (kb_id, file_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_document_versions (
        document_id VARCHAR(64) NOT NULL REFERENCES knowledge_source_documents(document_id) ON DELETE CASCADE,
        version INTEGER NOT NULL,
        content_hash VARCHAR(128) NOT NULL,
        parser_name VARCHAR(128),
        parser_version VARCHAR(128),
        input_hash VARCHAR(128) NOT NULL,
        source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (document_id, version)
    )
    """,
    (
        "ALTER TABLE IF EXISTS knowledge_graph_build_runs "
        "ADD COLUMN IF NOT EXISTS scope VARCHAR(32) NOT NULL DEFAULT 'pending'"
    ),
    (
        "ALTER TABLE IF EXISTS knowledge_graph_build_runs "
        "ADD COLUMN IF NOT EXISTS document_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
    ),
    "ALTER TABLE IF EXISTS knowledge_graph_build_runs ADD COLUMN IF NOT EXISTS rule_version VARCHAR(128)",
    "ALTER TABLE IF EXISTS knowledge_graph_build_runs ADD COLUMN IF NOT EXISTS started_by VARCHAR(64)",
    (
        "ALTER TABLE IF EXISTS knowledge_graph_build_runs "
        "ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 1"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_evaluation_runs (
        evaluation_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        pipeline_revision VARCHAR(128) NOT NULL,
        gold_manifest_sha256 VARCHAR(64) NOT NULL,
        prediction_sha256 VARCHAR(64) NOT NULL,
        report JSONB NOT NULL,
        status VARCHAR(32) NOT NULL,
        created_by VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_knowledge_source_documents_kb ON knowledge_source_documents(kb_id, source_type)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_document_versions_hash ON knowledge_document_versions(content_hash)",
    "CREATE INDEX IF NOT EXISTS ix_kg_build_runs_kb_status ON knowledge_graph_build_runs(kb_id, status, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_kg_evaluation_kb_created ON knowledge_graph_evaluation_runs(kb_id, created_at DESC)",
)
