"""知识图谱阶段运行日志与冲突治理表的幂等迁移。"""

KNOWLEDGE_GRAPH_OPERABILITY_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_build_stage_runs (
        stage_run_id VARCHAR(64) PRIMARY KEY,
        run_id VARCHAR(64) NOT NULL
            REFERENCES knowledge_graph_build_runs(run_id) ON DELETE CASCADE,
        kb_id VARCHAR(80) NOT NULL
            REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        stage_code VARCHAR(64) NOT NULL,
        stage_order INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'processing',
        input_hash VARCHAR(64) NOT NULL,
        output_hash VARCHAR(64),
        model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
        ontology_version VARCHAR(128) NOT NULL,
        rule_version VARCHAR(128) NOT NULL,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT NOT NULL DEFAULT '',
        attempt_count INTEGER NOT NULL DEFAULT 1,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        CONSTRAINT uq_kg_build_stage_attempt UNIQUE (run_id, stage_code, attempt_count),
        CONSTRAINT ck_kg_build_stage_order CHECK (stage_order >= 0),
        CONSTRAINT ck_kg_build_stage_attempt CHECK (attempt_count >= 1),
        CONSTRAINT ck_kg_build_stage_status
            CHECK (status IN ('processing', 'completed', 'failed', 'cancelled', 'skipped'))
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_build_stage_run_order "
        "ON knowledge_graph_build_stage_runs(run_id, stage_order, attempt_count)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_build_stage_kb_status "
        "ON knowledge_graph_build_stage_runs(kb_id, status, started_at)"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_conflicts (
        conflict_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL
            REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        fingerprint VARCHAR(64) NOT NULL,
        conflict_type VARCHAR(64) NOT NULL,
        left_target_type VARCHAR(32) NOT NULL,
        left_target_id VARCHAR(128) NOT NULL,
        right_target_type VARCHAR(32),
        right_target_id VARCHAR(128),
        status VARCHAR(32) NOT NULL DEFAULT 'open',
        severity VARCHAR(16) NOT NULL DEFAULT 'medium',
        summary TEXT NOT NULL,
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        detected_by VARCHAR(64) NOT NULL,
        resolution TEXT NOT NULL DEFAULT '',
        resolved_by VARCHAR(64),
        resolved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_kg_conflict_fingerprint UNIQUE (kb_id, fingerprint),
        CONSTRAINT ck_kg_conflict_status
            CHECK (status IN ('open', 'resolved', 'dismissed', 'superseded')),
        CONSTRAINT ck_kg_conflict_severity
            CHECK (severity IN ('low', 'medium', 'high', 'critical')),
        CONSTRAINT ck_kg_conflict_left_target
            CHECK (left_target_type IN ('entity_mention', 'relation_mention', 'entity', 'relation')),
        CONSTRAINT ck_kg_conflict_right_target CHECK (
            right_target_type IS NULL
            OR right_target_type IN ('entity_mention', 'relation_mention', 'entity', 'relation')
        ),
        CONSTRAINT ck_kg_conflict_right_pair CHECK (
            (right_target_type IS NULL AND right_target_id IS NULL)
            OR (right_target_type IS NOT NULL AND right_target_id IS NOT NULL)
        )
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_conflict_queue "
        "ON knowledge_graph_conflicts(kb_id, status, severity, created_at)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_conflict_left_target "
        "ON knowledge_graph_conflicts(kb_id, left_target_type, left_target_id, status)"
    ),
)
