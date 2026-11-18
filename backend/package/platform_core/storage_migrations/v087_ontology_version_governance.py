"""补齐本体版本生效时间和生命周期约束的幂等迁移。"""

ONTOLOGY_VERSION_GOVERNANCE_SCHEMA_STATEMENTS = (
    (
        "UPDATE ontology_versions SET effective_at = COALESCE(effective_at, created_at, NOW()) "
        "WHERE status = 'active' AND effective_at IS NULL"
    ),
    "ALTER TABLE IF EXISTS ontology_versions DROP CONSTRAINT IF EXISTS ck_ontology_version_status",
    (
        "ALTER TABLE IF EXISTS ontology_versions ADD CONSTRAINT ck_ontology_version_status "
        "CHECK (status IN ('draft', 'active', 'deprecated'))"
    ),
    "ALTER TABLE IF EXISTS ontology_versions DROP CONSTRAINT IF EXISTS ck_ontology_version_effective_at",
    (
        "ALTER TABLE IF EXISTS ontology_versions ADD CONSTRAINT ck_ontology_version_effective_at "
        "CHECK (status <> 'active' OR effective_at IS NOT NULL)"
    ),
    "ALTER TABLE IF EXISTS ontology_versions DROP CONSTRAINT IF EXISTS ck_ontology_version_previous",
    (
        "ALTER TABLE IF EXISTS ontology_versions ADD CONSTRAINT ck_ontology_version_previous "
        "CHECK (previous_version IS NULL OR previous_version <> version)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_ontology_versions_effective "
        "ON ontology_versions(status, effective_at DESC, created_at DESC)"
    ),
)
