"""记录标注活动显式验收语种范围。"""

PILOT_ACCEPTANCE_SCOPE_SCHEMA_STATEMENTS = (
    (
        "ALTER TABLE IF EXISTS knowledge_graph_annotation_campaigns "
        'ADD COLUMN IF NOT EXISTS acceptance_languages JSONB NOT NULL DEFAULT \'["en", "zh"]\'::jsonb'
    ),
)
