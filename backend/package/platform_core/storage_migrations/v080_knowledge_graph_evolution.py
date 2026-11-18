"""知识图谱治理、创新候选与技术演化的幂等 PostgreSQL 演进。"""

KNOWLEDGE_GRAPH_EVOLUTION_SCHEMA_STATEMENTS = (
    (
        "ALTER TABLE IF EXISTS knowledge_graph_entities "
        "ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active'"
    ),
    ("ALTER TABLE IF EXISTS knowledge_graph_entities ADD COLUMN IF NOT EXISTS superseded_by_entity_id VARCHAR(64)"),
    "ALTER TABLE IF EXISTS knowledge_graph_entities ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ",
    "ALTER TABLE IF EXISTS knowledge_graph_entities ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ",
    "ALTER TABLE IF EXISTS knowledge_graph_entities ADD COLUMN IF NOT EXISTS entity_version INTEGER NOT NULL DEFAULT 1",
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_entity_redirects (
        redirect_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        source_entity_id VARCHAR(64) NOT NULL REFERENCES knowledge_graph_entities(entity_id) ON DELETE CASCADE,
        target_entity_id VARCHAR(64) NOT NULL REFERENCES knowledge_graph_entities(entity_id) ON DELETE CASCADE,
        operation VARCHAR(32) NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_kg_entity_redirect_source UNIQUE (kb_id, source_entity_id),
        CONSTRAINT ck_kg_entity_redirect_distinct CHECK (source_entity_id <> target_entity_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_change_events (
        event_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        graph_revision VARCHAR(64) NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        target_type VARCHAR(32) NOT NULL,
        target_id VARCHAR(128) NOT NULL,
        before_payload JSONB,
        after_payload JSONB,
        reason TEXT NOT NULL DEFAULT '',
        source_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_hypotheses (
        hypothesis_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        source_entity_id VARCHAR(64) NOT NULL REFERENCES knowledge_graph_entities(entity_id) ON DELETE CASCADE,
        target_entity_id VARCHAR(64) NOT NULL REFERENCES knowledge_graph_entities(entity_id) ON DELETE CASCADE,
        relation_type VARCHAR(256) NOT NULL,
        discovery_mode VARCHAR(32) NOT NULL,
        claim_level VARCHAR(32) NOT NULL DEFAULT 'Hypothesis',
        score DOUBLE PRECISION NOT NULL,
        evidence_path JSONB NOT NULL,
        mechanism_hypothesis TEXT NOT NULL DEFAULT '',
        feasibility_basis JSONB NOT NULL DEFAULT '[]'::jsonb,
        expected_effects JSONB NOT NULL DEFAULT '[]'::jsonb,
        uncertainties JSONB NOT NULL DEFAULT '[]'::jsonb,
        algorithm_version VARCHAR(128) NOT NULL,
        review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        reviewed_by VARCHAR(64),
        reviewed_at TIMESTAMPTZ,
        review_reason TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_kg_hypothesis_identity UNIQUE (
            kb_id, source_entity_id, target_entity_id, relation_type, algorithm_version
        ),
        CONSTRAINT ck_kg_hypothesis_claim CHECK (claim_level = 'Hypothesis')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_trend_snapshots (
        snapshot_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        entity_id VARCHAR(64) NOT NULL REFERENCES knowledge_graph_entities(entity_id) ON DELETE CASCADE,
        as_of TIMESTAMPTZ NOT NULL,
        algorithm_version VARCHAR(128) NOT NULL,
        frontier_score DOUBLE PRECISION NOT NULL,
        maturity_stage VARCHAR(32) NOT NULL,
        burst_level VARCHAR(32) NOT NULL,
        component_scores JSONB NOT NULL,
        time_series JSONB NOT NULL,
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_kg_trend_snapshot UNIQUE (kb_id, entity_id, as_of, algorithm_version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_kg_redirect_target ON knowledge_graph_entity_redirects(kb_id, target_entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_kg_change_target ON knowledge_graph_change_events(kb_id, target_type, target_id)",
    "CREATE INDEX IF NOT EXISTS ix_kg_change_revision ON knowledge_graph_change_events(kb_id, graph_revision)",
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_hypothesis_review "
        "ON knowledge_graph_hypotheses(kb_id, review_status, score DESC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_trend_entity_time "
        "ON knowledge_graph_trend_snapshots(kb_id, entity_id, as_of DESC)"
    ),
)
