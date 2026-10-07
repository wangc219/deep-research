"""企业组织与功能权限的幂等增量迁移。"""

ENTERPRISE_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS tenants (
        id VARCHAR(64) PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
    "INSERT INTO tenants(id, name) VALUES ('default', '默认租户') ON CONFLICT (id) DO NOTHING",
    "ALTER TABLE departments ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) "
    "NOT NULL DEFAULT 'default' REFERENCES tenants(id)",
    "ALTER TABLE departments ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES departments(id)",
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
            WHERE conrelid='departments'::regclass AND contype='f'
            AND confrelid='tenants'::regclass) THEN
            ALTER TABLE departments ADD CONSTRAINT departments_tenant_id_fkey
                FOREIGN KEY (tenant_id) REFERENCES tenants(id);
        END IF;
    END $$""",
    "CREATE INDEX IF NOT EXISTS ix_departments_tenant_id ON departments(tenant_id)",
    """CREATE TABLE IF NOT EXISTS feature_permissions (
        id SERIAL PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id),
        subject_type VARCHAR(20) NOT NULL CHECK (subject_type IN ('tenant','department','user')),
        subject_id VARCHAR(128) NOT NULL, feature VARCHAR(64) NOT NULL,
        can_read BOOLEAN NOT NULL DEFAULT TRUE, can_write BOOLEAN NOT NULL DEFAULT TRUE,
        CHECK (NOT can_write OR can_read),
        UNIQUE (tenant_id, subject_type, subject_id, feature))""",
    """CREATE TABLE IF NOT EXISTS platform_request_metrics (
        id BIGSERIAL PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, uid VARCHAR(128) NOT NULL,
        feature VARCHAR(64) NOT NULL, method VARCHAR(10) NOT NULL, status_code INTEGER NOT NULL,
        duration_ms FLOAT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
    "CREATE INDEX IF NOT EXISTS ix_platform_metrics_created ON platform_request_metrics(created_at)",
)
