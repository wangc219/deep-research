"""为前沿简报增加开放发现和调研探索员开关。"""

INNOVATION_BRIEF_DISCOVERY_SCHEMA_STATEMENTS = (
    (
        "ALTER TABLE IF EXISTS innovation_brief_subscriptions "
        "ADD COLUMN IF NOT EXISTS open_discovery_enabled BOOLEAN NOT NULL DEFAULT TRUE"
    ),
    (
        "ALTER TABLE IF EXISTS innovation_brief_subscriptions "
        "ADD COLUMN IF NOT EXISTS research_explorer_enabled BOOLEAN NOT NULL DEFAULT TRUE"
    ),
)
