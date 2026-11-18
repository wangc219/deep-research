"""双人独立标注与专家仲裁表的幂等迁移。"""

ANNOTATION_CAMPAIGN_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_annotation_campaigns (
        campaign_id VARCHAR(64) PRIMARY KEY,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        guideline_version VARCHAR(128) NOT NULL,
        ontology_version VARCHAR(128) NOT NULL,
        pilot_mode BOOLEAN NOT NULL DEFAULT TRUE,
        acceptance_languages JSONB NOT NULL DEFAULT '["en", "zh"]'::jsonb,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        created_by VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_kg_annotation_campaign_status
            CHECK (status IN ('draft', 'active', 'adjudicating', 'completed', 'sealed'))
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_annotation_campaign_kb_status "
        "ON knowledge_graph_annotation_campaigns(kb_id, status, created_at)"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_annotation_assignments (
        assignment_id VARCHAR(64) PRIMARY KEY,
        campaign_id VARCHAR(64) NOT NULL
            REFERENCES knowledge_graph_annotation_campaigns(campaign_id) ON DELETE CASCADE,
        document_id VARCHAR(64) NOT NULL,
        document_version INTEGER NOT NULL,
        split VARCHAR(16) NOT NULL,
        annotator_a_uid VARCHAR(128) NOT NULL,
        annotator_b_uid VARCHAR(128) NOT NULL,
        arbitrator_uid VARCHAR(128) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'assigned',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_kg_annotation_campaign_document UNIQUE (campaign_id, document_id),
        CONSTRAINT fk_kg_annotation_assignment_document_version
            FOREIGN KEY (document_id, document_version)
            REFERENCES knowledge_document_versions(document_id, version) ON DELETE CASCADE,
        CONSTRAINT ck_kg_annotation_assignment_document_version CHECK (document_version > 0),
        CONSTRAINT ck_kg_annotation_assignment_split CHECK (split IN ('train', 'dev', 'test')),
        CONSTRAINT ck_kg_annotation_assignment_status
            CHECK (status IN ('assigned', 'annotating', 'awaiting_adjudication', 'adjudicating', 'completed')),
        CONSTRAINT ck_kg_annotation_assignment_distinct_roles CHECK (
            annotator_a_uid <> annotator_b_uid
            AND annotator_a_uid <> arbitrator_uid
            AND annotator_b_uid <> arbitrator_uid
        )
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_annotation_assignment_campaign_status "
        "ON knowledge_graph_annotation_assignments(campaign_id, status)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_annotation_assignment_annotator_a "
        "ON knowledge_graph_annotation_assignments(annotator_a_uid, status)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_annotation_assignment_annotator_b "
        "ON knowledge_graph_annotation_assignments(annotator_b_uid, status)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_annotation_assignment_arbitrator "
        "ON knowledge_graph_annotation_assignments(arbitrator_uid, status)"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_annotation_submissions (
        submission_id VARCHAR(64) PRIMARY KEY,
        assignment_id VARCHAR(64) NOT NULL
            REFERENCES knowledge_graph_annotation_assignments(assignment_id) ON DELETE CASCADE,
        annotator_uid VARCHAR(128) NOT NULL,
        revision INTEGER NOT NULL,
        annotation_payload JSONB NOT NULL,
        payload_sha256 VARCHAR(64) NOT NULL,
        submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_kg_annotation_submission_revision CHECK (revision > 0),
        CONSTRAINT uq_kg_annotation_submission_revision
            UNIQUE (assignment_id, annotator_uid, revision)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_kg_annotation_submission_latest "
        "ON knowledge_graph_annotation_submissions(assignment_id, annotator_uid, revision)"
    ),
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_annotation_adjudications (
        adjudication_id VARCHAR(64) PRIMARY KEY,
        assignment_id VARCHAR(64) NOT NULL
            REFERENCES knowledge_graph_annotation_assignments(assignment_id) ON DELETE CASCADE,
        arbitrator_uid VARCHAR(128) NOT NULL,
        final_payload JSONB NOT NULL,
        payload_sha256 VARCHAR(64) NOT NULL,
        disagreement_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        adjudicated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_kg_annotation_adjudication_assignment UNIQUE (assignment_id)
    )
    """,
)
