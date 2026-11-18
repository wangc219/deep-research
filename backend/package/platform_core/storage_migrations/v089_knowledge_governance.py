"""知识分类、统一来源、前沿简报和采集成果状态。"""

KNOWLEDGE_GOVERNANCE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS knowledge_categories (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        parent_id VARCHAR(64) REFERENCES knowledge_categories(id) ON DELETE RESTRICT,
        name VARCHAR(255) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_by VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_category_sibling_normalized "
        "ON knowledge_categories(tenant_id, COALESCE(parent_id, ''), name)"
    ),
    ("CREATE INDEX IF NOT EXISTS ix_knowledge_category_tree ON knowledge_categories(tenant_id, parent_id, sort_order)"),
    """
    CREATE TABLE IF NOT EXISTS knowledge_source_credentials (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL,
        encrypted_secret TEXT NOT NULL,
        created_by VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_sources (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        category_id VARCHAR(64) REFERENCES knowledge_categories(id) ON DELETE RESTRICT,
        name VARCHAR(255) NOT NULL,
        source_type VARCHAR(32) NOT NULL,
        config JSONB NOT NULL DEFAULT '{}'::jsonb,
        credential_id VARCHAR(64) REFERENCES knowledge_source_credentials(id) ON DELETE SET NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        notify_on_new BOOLEAN NOT NULL DEFAULT FALSE,
        cron_expression VARCHAR(100),
        timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
        cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
        last_status VARCHAR(32) NOT NULL DEFAULT 'idle',
        last_error TEXT NOT NULL DEFAULT '',
        last_run_at TIMESTAMPTZ,
        next_run_at TIMESTAMPTZ,
        created_by VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_knowledge_source_type CHECK (
            source_type IN ('upload', 'postgresql', 'mysql', 'website', 'web_search')
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_knowledge_source_owner ON knowledge_sources(tenant_id, kb_id, enabled)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_source_next_run ON knowledge_sources(enabled, next_run_at)",
    """
    CREATE TABLE IF NOT EXISTS knowledge_source_runs (
        id VARCHAR(64) PRIMARY KEY,
        source_id VARCHAR(64) NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
        owner_uid VARCHAR(64) NOT NULL,
        task_id VARCHAR(64),
        trigger VARCHAR(32) NOT NULL DEFAULT 'manual',
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        stats JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT NOT NULL DEFAULT '',
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_knowledge_source_run_status CHECK (
            status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_knowledge_source_run_recent ON knowledge_source_runs(source_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS knowledge_source_items (
        id VARCHAR(64) PRIMARY KEY,
        source_id VARCHAR(64) NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
        run_id VARCHAR(64) REFERENCES knowledge_source_runs(id) ON DELETE SET NULL,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        category_id VARCHAR(64) REFERENCES knowledge_categories(id) ON DELETE RESTRICT,
        external_key VARCHAR(1024) NOT NULL,
        canonical_url VARCHAR(2048) NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        markdown TEXT NOT NULL,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        content_hash VARCHAR(64) NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        previous_item_id VARCHAR(64) REFERENCES knowledge_source_items(id) ON DELETE SET NULL,
        review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        review_note TEXT NOT NULL DEFAULT '',
        reviewed_by VARCHAR(64),
        reviewed_at TIMESTAMPTZ,
        minio_url VARCHAR(1024),
        knowledge_file_id VARCHAR(64) REFERENCES knowledge_files(file_id) ON DELETE SET NULL,
        ingest_task_id VARCHAR(64),
        discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_knowledge_source_item_version UNIQUE (source_id, external_key, version),
        CONSTRAINT uq_knowledge_source_item_hash UNIQUE (source_id, content_hash),
        CONSTRAINT ck_knowledge_source_item_review CHECK (
            review_status IN ('pending', 'approved', 'rejected', 'duplicate', 'failed')
        )
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_knowledge_source_item_queue "
        "ON knowledge_source_items(kb_id, review_status, discovered_at DESC)"
    ),
    """
    CREATE TABLE IF NOT EXISTS innovation_brief_subscriptions (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL,
        owner_uid VARCHAR(64) NOT NULL,
        name VARCHAR(255) NOT NULL,
        topics JSONB NOT NULL DEFAULT '[]'::jsonb,
        keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
        knowledge_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        languages JSONB NOT NULL DEFAULT '["zh-CN", "en"]'::jsonb,
        timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
        daily_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        weekly_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        daily_cron VARCHAR(100) NOT NULL DEFAULT '0 8 * * *',
        weekly_cron VARCHAR(100) NOT NULL DEFAULT '0 9 * * 1',
        reminder_sensitivity VARCHAR(16) NOT NULL DEFAULT 'standard',
        significance_threshold DOUBLE PRECISION NOT NULL DEFAULT 70,
        next_daily_at TIMESTAMPTZ,
        next_weekly_at TIMESTAMPTZ,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_innovation_subscription_owner "
        "ON innovation_brief_subscriptions(owner_uid, enabled)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_innovation_subscription_daily_due "
        "ON innovation_brief_subscriptions(enabled, next_daily_at)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_innovation_subscription_weekly_due "
        "ON innovation_brief_subscriptions(enabled, next_weekly_at)"
    ),
    """
    CREATE TABLE IF NOT EXISTS innovation_brief_runs (
        id VARCHAR(64) PRIMARY KEY,
        subscription_id VARCHAR(64) NOT NULL REFERENCES innovation_brief_subscriptions(id) ON DELETE CASCADE,
        owner_uid VARCHAR(64) NOT NULL,
        task_id VARCHAR(64),
        brief_type VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        query_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
        stats JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT NOT NULL DEFAULT '',
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_innovation_brief_run_recent "
        "ON innovation_brief_runs(subscription_id, created_at DESC)"
    ),
    """
    CREATE TABLE IF NOT EXISTS innovation_briefs (
        id VARCHAR(64) PRIMARY KEY,
        run_id VARCHAR(64) NOT NULL REFERENCES innovation_brief_runs(id) ON DELETE CASCADE,
        subscription_id VARCHAR(64) NOT NULL REFERENCES innovation_brief_subscriptions(id) ON DELETE CASCADE,
        owner_uid VARCHAR(64) NOT NULL,
        brief_type VARCHAR(32) NOT NULL,
        title VARCHAR(512) NOT NULL,
        summary TEXT NOT NULL,
        sections JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        max_score DOUBLE PRECISION NOT NULL DEFAULT 0,
        significant BOOLEAN NOT NULL DEFAULT FALSE,
        unread BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        read_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_innovation_brief_feed ON innovation_briefs(owner_uid, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_innovation_brief_unread ON innovation_briefs(owner_uid, unread)",
    """
    CREATE TABLE IF NOT EXISTS brief_delivery_outbox (
        id VARCHAR(64) PRIMARY KEY,
        brief_id VARCHAR(64) NOT NULL REFERENCES innovation_briefs(id) ON DELETE CASCADE,
        owner_uid VARCHAR(64) NOT NULL,
        provider VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        delivered_at TIMESTAMPTZ,
        CONSTRAINT uq_brief_delivery_provider UNIQUE (brief_id, provider),
        CONSTRAINT ck_brief_delivery_provider CHECK (provider IN ('in_app', 'wecom'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_brief_delivery_pending ON brief_delivery_outbox(status, created_at)",
    """
    CREATE TABLE IF NOT EXISTS collection_artifact_records (
        id VARCHAR(64) PRIMARY KEY,
        owner_uid VARCHAR(64) NOT NULL,
        source VARCHAR(32) NOT NULL,
        artifact_key VARCHAR(64) NOT NULL,
        title TEXT NOT NULL,
        account VARCHAR(255) NOT NULL DEFAULT '',
        canonical_url VARCHAR(2048) NOT NULL DEFAULT '',
        content_hash VARCHAR(64),
        primary_path VARCHAR(1024) NOT NULL,
        import_path VARCHAR(1024) NOT NULL,
        files JSONB NOT NULL DEFAULT '[]'::jsonb,
        status VARCHAR(32) NOT NULL DEFAULT 'downloaded',
        failure_stage VARCHAR(32),
        error TEXT NOT NULL DEFAULT '',
        downloaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_collection_artifact_owner_key UNIQUE (owner_uid, source, artifact_key),
        CONSTRAINT ck_collection_artifact_status CHECK (
            status IN ('downloaded', 'importing', 'imported', 'failed')
        )
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_collection_artifact_owner_status "
        "ON collection_artifact_records(owner_uid, source, status)"
    ),
    """
    CREATE TABLE IF NOT EXISTS collection_artifact_ingestions (
        id VARCHAR(64) PRIMARY KEY,
        artifact_id VARCHAR(64) NOT NULL REFERENCES collection_artifact_records(id) ON DELETE CASCADE,
        kb_id VARCHAR(80) NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
        category_id VARCHAR(64) REFERENCES knowledge_categories(id) ON DELETE RESTRICT,
        content_hash VARCHAR(64) NOT NULL,
        task_id VARCHAR(64) NOT NULL,
        knowledge_file_id VARCHAR(64) REFERENCES knowledge_files(file_id) ON DELETE SET NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'importing',
        error TEXT NOT NULL DEFAULT '',
        created_by VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_collection_artifact_ingestion_content UNIQUE (artifact_id, kb_id, content_hash),
        CONSTRAINT ck_collection_artifact_ingestion_status CHECK (
            status IN ('importing', 'imported', 'failed')
        )
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_collection_artifact_ingestion_task "
        "ON collection_artifact_ingestions(task_id, status)"
    ),
    "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS category_id VARCHAR(64)",
    (
        "ALTER TABLE IF EXISTS innovation_brief_subscriptions "
        "ADD COLUMN IF NOT EXISTS reminder_sensitivity VARCHAR(16) NOT NULL DEFAULT 'standard'"
    ),
    ("ALTER TABLE IF EXISTS innovation_brief_subscriptions ADD COLUMN IF NOT EXISTS next_daily_at TIMESTAMPTZ"),
    ("ALTER TABLE IF EXISTS innovation_brief_subscriptions ADD COLUMN IF NOT EXISTS next_weekly_at TIMESTAMPTZ"),
    "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS category_id VARCHAR(64)",
    "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS source_id VARCHAR(64)",
    "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS source_item_id VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_bases_category_id ON knowledge_bases(category_id)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_files_category_id ON knowledge_files(category_id)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_files_source_id ON knowledge_files(source_id)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_files_source_item_id ON knowledge_files(source_item_id)",
    """
    DO $$ BEGIN
        ALTER TABLE knowledge_bases
            ADD CONSTRAINT fk_knowledge_bases_category
            FOREIGN KEY (category_id) REFERENCES knowledge_categories(id) ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """,
    """
    DO $$ BEGIN
        ALTER TABLE knowledge_files
            ADD CONSTRAINT fk_knowledge_files_category
            FOREIGN KEY (category_id) REFERENCES knowledge_categories(id) ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """,
    """
    DO $$ BEGIN
        ALTER TABLE knowledge_files
            ADD CONSTRAINT fk_knowledge_files_source
            FOREIGN KEY (source_id) REFERENCES knowledge_sources(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """,
    """
    DO $$ BEGIN
        ALTER TABLE knowledge_files
            ADD CONSTRAINT fk_knowledge_files_source_item
            FOREIGN KEY (source_item_id) REFERENCES knowledge_source_items(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """,
)
