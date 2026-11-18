"""为历史采集成果导入记录补齐知识分类字段。"""

COLLECTION_ARTIFACT_CATEGORY_SCHEMA_STATEMENTS = (
    ("ALTER TABLE IF EXISTS collection_artifact_ingestions ADD COLUMN IF NOT EXISTS category_id VARCHAR(64)"),
    (
        "CREATE INDEX IF NOT EXISTS ix_collection_artifact_ingestions_category_id "
        "ON collection_artifact_ingestions(category_id)"
    ),
    """
    DO $$ BEGIN
        IF to_regclass('collection_artifact_ingestions') IS NOT NULL THEN
            ALTER TABLE collection_artifact_ingestions
                ADD CONSTRAINT fk_collection_artifact_ingestions_category
                FOREIGN KEY (category_id) REFERENCES knowledge_categories(id) ON DELETE RESTRICT;
        END IF;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """,
)
