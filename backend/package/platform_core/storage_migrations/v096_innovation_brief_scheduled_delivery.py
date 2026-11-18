"""为前沿简报增加提前准备和准点发布状态。"""

INNOVATION_BRIEF_SCHEDULED_DELIVERY_SCHEMA_STATEMENTS = (
    ("ALTER TABLE IF EXISTS innovation_brief_runs ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ"),
    """
    DO $$
    BEGIN
        IF to_regclass('innovation_briefs') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = 'innovation_briefs'
                 AND column_name = 'published_at'
           ) THEN
            ALTER TABLE innovation_briefs ADD COLUMN published_at TIMESTAMPTZ;
            UPDATE innovation_briefs SET published_at = created_at;
        END IF;
    END
    $$
    """,
    ("ALTER TABLE IF EXISTS brief_delivery_outbox ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ"),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_innovation_brief_scheduled_run "
        "ON innovation_brief_runs(subscription_id, brief_type, scheduled_for) "
        "WHERE scheduled_for IS NOT NULL"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_innovation_brief_publish_due "
        "ON innovation_briefs(published_at, created_at) WHERE published_at IS NULL"
    ),
)
