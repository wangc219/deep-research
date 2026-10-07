"""融合运行时的逐次模型调用账本；重复执行安全。"""

MODEL_CALL_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS platform_model_calls (
        id VARCHAR(64) PRIMARY KEY,
        model_spec VARCHAR(512) NOT NULL,
        surface VARCHAR(64) NOT NULL,
        run_id VARCHAR(256) NOT NULL DEFAULT '',
        phase VARCHAR(256) NOT NULL DEFAULT '',
        status VARCHAR(24) NOT NULL,
        duration_ms DOUBLE PRECISION NOT NULL,
        input_tokens BIGINT,
        output_tokens BIGINT,
        total_tokens BIGINT,
        error_type VARCHAR(128) NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))""",
    "ALTER TABLE platform_model_calls ALTER COLUMN created_at SET DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')",
    "CREATE INDEX IF NOT EXISTS ix_model_calls_created ON platform_model_calls(created_at)",
    "CREATE INDEX IF NOT EXISTS ix_model_calls_run ON platform_model_calls(run_id)",
)
