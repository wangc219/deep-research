"""幂等创建论文检索账本，不修改现有 Run、消息或模型配置。"""

ACADEMIC_RETRIEVAL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS academic_retrieval_calls (
        id VARCHAR(64) PRIMARY KEY,
        root_run_id VARCHAR(64) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
        run_id VARCHAR(64) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
        request_key VARCHAR(64) NOT NULL,
        endpoint VARCHAR(32) NOT NULL,
        attempt_no INTEGER NOT NULL,
        cost_cents INTEGER NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        result JSONB,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
        finished_at TIMESTAMP WITHOUT TIME ZONE,
        CONSTRAINT uq_academic_call_attempt UNIQUE (root_run_id, request_key, attempt_no),
        CONSTRAINT ck_academic_call_cost CHECK (cost_cents >= 0),
        CONSTRAINT ck_academic_call_status CHECK (status IN ('pending', 'succeeded', 'failed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_academic_retrieval_calls_root_run_id ON academic_retrieval_calls(root_run_id)",
    "CREATE INDEX IF NOT EXISTS ix_academic_call_cache ON academic_retrieval_calls(request_key, status, finished_at)",
)
