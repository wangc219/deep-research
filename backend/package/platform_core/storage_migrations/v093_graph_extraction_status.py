"""修复知识 Chunk 抽取状态对 JSON null 的兼容误判。"""

GRAPH_EXTRACTION_STATUS_SCHEMA_STATEMENTS = (
    (
        "UPDATE knowledge_chunks SET graph_extraction_details = "
        "jsonb_build_object('status', 'pending', 'attempt_count', 0) "
        "WHERE graph_extraction_details->>'status' = 'succeeded' "
        "AND graph_structure_indexed IS NOT TRUE "
        "AND graph_indexed IS NOT TRUE "
        "AND (extraction_result IS NULL OR extraction_result = 'null'::jsonb)"
    ),
    (
        "UPDATE knowledge_chunks SET graph_extraction_details = jsonb_build_object('status', 'succeeded') "
        "WHERE (graph_extraction_details IS NULL "
        "OR graph_extraction_details->>'status' = 'pending') "
        "AND ((extraction_result IS NOT NULL AND extraction_result <> 'null'::jsonb) "
        "OR graph_structure_indexed IS TRUE OR graph_indexed IS TRUE)"
    ),
    (
        "UPDATE knowledge_chunks SET graph_extraction_details = "
        "jsonb_build_object('status', 'pending', 'attempt_count', 0) "
        "WHERE graph_extraction_details IS NULL"
    ),
)
