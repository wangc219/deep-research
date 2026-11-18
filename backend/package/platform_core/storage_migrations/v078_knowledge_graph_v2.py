"""知识图谱 v2 的幂等 PostgreSQL 演进语句。"""

KNOWLEDGE_GRAPH_V2_SCHEMA_STATEMENTS = (
    "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions ADD COLUMN IF NOT EXISTS mention_text VARCHAR(512)",
    "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions ADD COLUMN IF NOT EXISTS start_char INTEGER",
    "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions ADD COLUMN IF NOT EXISTS end_char INTEGER",
    "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION",
    "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions ADD COLUMN IF NOT EXISTS model_version VARCHAR(256)",
    "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions ADD COLUMN IF NOT EXISTS ontology_version VARCHAR(128)",
    (
        "ALTER TABLE IF EXISTS knowledge_graph_entity_mentions "
        "ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'pending'"
    ),
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS claim_level VARCHAR(32)",
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION",
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS evidence_quote TEXT",
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS evidence_spans JSONB",
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS reasoning_basis TEXT",
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS uncertainty TEXT",
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions "
        "ADD COLUMN IF NOT EXISTS expert_review_required BOOLEAN NOT NULL DEFAULT TRUE"
    ),
    (
        "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions "
        "ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'pending'"
    ),
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS model_version VARCHAR(256)",
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS ontology_version VARCHAR(128)",
    "ALTER TABLE IF EXISTS knowledge_graph_triple_mentions ADD COLUMN IF NOT EXISTS pipeline_revision VARCHAR(128)",
    """
    CREATE TABLE IF NOT EXISTS ontology_versions (
        version VARCHAR(128) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        definition JSONB NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'draft',
        previous_version VARCHAR(128),
        change_reason TEXT NOT NULL DEFAULT '',
        created_by VARCHAR(64),
        effective_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_entity_types (
        ontology_version VARCHAR(128) NOT NULL REFERENCES ontology_versions(version) ON DELETE CASCADE,
        code VARCHAR(128) NOT NULL,
        name_zh VARCHAR(255) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        definition JSONB NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY (ontology_version, code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_relation_types (
        ontology_version VARCHAR(128) NOT NULL REFERENCES ontology_versions(version) ON DELETE CASCADE,
        code VARCHAR(256) NOT NULL,
        name_zh VARCHAR(255) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        head_types JSONB NOT NULL,
        tail_types JSONB NOT NULL,
        directed BOOLEAN NOT NULL DEFAULT TRUE,
        allow_self BOOLEAN NOT NULL DEFAULT FALSE,
        hypothesis_only BOOLEAN NOT NULL DEFAULT FALSE,
        definition JSONB NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY (ontology_version, code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_entity_aliases (
        id BIGSERIAL PRIMARY KEY,
        entity_id VARCHAR(64) NOT NULL REFERENCES knowledge_graph_entities(entity_id) ON DELETE CASCADE,
        alias VARCHAR(512) NOT NULL,
        normalized_alias VARCHAR(512) NOT NULL,
        language VARCHAR(32) NOT NULL DEFAULT 'unknown',
        source VARCHAR(128) NOT NULL DEFAULT 'extraction',
        confidence DOUBLE PRECISION,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_knowledge_graph_entity_alias UNIQUE (entity_id, normalized_alias, language)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_review_decisions (
        decision_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        target_type VARCHAR(32) NOT NULL,
        target_id VARCHAR(128) NOT NULL,
        decision VARCHAR(32) NOT NULL,
        previous_payload JSONB,
        decided_payload JSONB,
        reason TEXT NOT NULL DEFAULT '',
        reviewer_uid VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_build_runs (
        run_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        pipeline_revision VARCHAR(128) NOT NULL,
        ontology_version VARCHAR(128) NOT NULL,
        model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
        input_hash VARCHAR(128),
        output_hash VARCHAR(128),
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT NOT NULL DEFAULT '',
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_revisions (
        revision_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        parent_revision_id VARCHAR(64),
        ontology_version VARCHAR(128) NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_projection_outbox (
        event_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        chunk_id VARCHAR(128) NOT NULL REFERENCES knowledge_chunks(chunk_id) ON DELETE CASCADE,
        graph_revision VARCHAR(64),
        payload JSONB NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        next_retry_at TIMESTAMPTZ,
        locked_until TIMESTAMPTZ,
        lock_token VARCHAR(32),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_knowledge_graph_projection_chunk_revision UNIQUE (chunk_id, graph_revision)
    )
    """,
    ("ALTER TABLE IF EXISTS knowledge_graph_projection_outbox ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ"),
    ("ALTER TABLE IF EXISTS knowledge_graph_projection_outbox ADD COLUMN IF NOT EXISTS lock_token VARCHAR(32)"),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_triple_mentions_review "
        "ON knowledge_graph_triple_mentions(kb_id, review_status, claim_level)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_mentions_review "
        "ON knowledge_graph_entity_mentions(kb_id, review_status)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_projection_outbox_pending "
        "ON knowledge_graph_projection_outbox(status, next_retry_at, created_at)"
    ),
)
