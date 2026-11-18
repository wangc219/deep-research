"""标注工作草稿与一次确认批量提交的持久化结构。"""

ANNOTATION_DRAFT_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_annotation_drafts (
        draft_id VARCHAR(64) PRIMARY KEY,
        assignment_id VARCHAR(64) NOT NULL
            REFERENCES knowledge_graph_annotation_assignments(assignment_id) ON DELETE CASCADE,
        annotator_uid VARCHAR(128) NOT NULL,
        annotation_payload JSONB NOT NULL,
        payload_sha256 VARCHAR(64) NOT NULL,
        source_kind VARCHAR(32) NOT NULL DEFAULT 'manual',
        provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
        last_submitted_draft_sha256 VARCHAR(64),
        last_submitted_revision INTEGER,
        last_submitted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_kg_annotation_draft_assignment_annotator
            UNIQUE (assignment_id, annotator_uid),
        CONSTRAINT ck_kg_annotation_draft_source_kind
            CHECK (source_kind IN ('ai_prelabel', 'manual')),
        CONSTRAINT ck_kg_annotation_draft_last_revision
            CHECK (last_submitted_revision IS NULL OR last_submitted_revision > 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_kg_annotation_draft_annotator_updated
    ON knowledge_graph_annotation_drafts(annotator_uid, updated_at)
    """,
)
