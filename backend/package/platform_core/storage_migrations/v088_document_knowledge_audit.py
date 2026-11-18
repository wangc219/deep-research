"""增加文档分流、研究链与知识卡的幂等 Schema。"""

DOCUMENT_KNOWLEDGE_AUDIT_SCHEMA_STATEMENTS = (
    ("ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS graph_excluded BOOLEAN NOT NULL DEFAULT FALSE"),
    "ALTER TABLE IF EXISTS knowledge_chunks ADD COLUMN IF NOT EXISTS graph_exclusion_reason TEXT",
    (
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_graph_eligible "
        "ON knowledge_chunks(kb_id, graph_excluded, graph_indexed, id)"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_document_triage (
        document_id VARCHAR(64) NOT NULL REFERENCES knowledge_source_documents(document_id) ON DELETE CASCADE,
        document_version INTEGER NOT NULL,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        document_kind VARCHAR(32) NOT NULL,
        triage_level VARCHAR(32) NOT NULL,
        eligible_for_extraction BOOLEAN NOT NULL DEFAULT TRUE,
        reason TEXT NOT NULL DEFAULT '',
        signals JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        rule_version VARCHAR(128) NOT NULL,
        input_hash VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (document_id, document_version)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_knowledge_document_triage_eligibility "
        "ON knowledge_document_triage(kb_id, eligible_for_extraction, triage_level)"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_research_threads (
        thread_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        document_id VARCHAR(64) NOT NULL REFERENCES knowledge_source_documents(document_id) ON DELETE CASCADE,
        document_version INTEGER NOT NULL,
        thread_key VARCHAR(512) NOT NULL,
        thread_type VARCHAR(16) NOT NULL,
        title TEXT NOT NULL,
        technical_line JSONB NOT NULL DEFAULT '[]'::jsonb,
        capability_direction JSONB NOT NULL DEFAULT '[]'::jsonb,
        application_direction JSONB NOT NULL DEFAULT '[]'::jsonb,
        military_value JSONB NOT NULL DEFAULT '{}'::jsonb,
        innovation_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
        entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        relation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
        uncertainty TEXT NOT NULL DEFAULT '',
        confidence DOUBLE PRECISION NOT NULL,
        pipeline_revision VARCHAR(128) NOT NULL,
        governance_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_knowledge_research_thread_revision
            UNIQUE (document_id, document_version, thread_key, pipeline_revision)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_knowledge_research_thread_document "
        "ON knowledge_research_threads(kb_id, document_id, document_version)"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_document_cards (
        card_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        document_id VARCHAR(64) NOT NULL REFERENCES knowledge_source_documents(document_id) ON DELETE CASCADE,
        document_version INTEGER NOT NULL,
        title TEXT NOT NULL,
        source_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        triage JSONB NOT NULL DEFAULT '{}'::jsonb,
        content_overview TEXT NOT NULL DEFAULT '',
        main_thread_id VARCHAR(64),
        sub_thread_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        core_entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        core_relation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        technology_families JSONB NOT NULL DEFAULT '[]'::jsonb,
        capability_gains JSONB NOT NULL DEFAULT '[]'::jsonb,
        application_directions JSONB NOT NULL DEFAULT '[]'::jsonb,
        evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
        maturity JSONB NOT NULL DEFAULT '{}'::jsonb,
        heat_signals JSONB NOT NULL DEFAULT '{}'::jsonb,
        innovation_potential JSONB NOT NULL DEFAULT '{}'::jsonb,
        uncertainty TEXT NOT NULL DEFAULT '',
        pipeline_revision VARCHAR(128) NOT NULL,
        ontology_version VARCHAR(128) NOT NULL,
        governance_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_knowledge_document_card_revision
            UNIQUE (document_id, document_version, pipeline_revision)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_knowledge_document_card_status "
        "ON knowledge_document_cards(kb_id, governance_status, updated_at)"
    ),
)
