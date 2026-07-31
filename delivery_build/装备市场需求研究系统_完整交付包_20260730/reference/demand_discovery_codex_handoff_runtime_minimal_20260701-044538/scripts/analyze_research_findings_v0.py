"""Run Phase 4 v0 research queries against the local SQLite graph.

This script is intentionally read-only for the source database. It creates
temporary canonical relation tables inside the current SQLite connection only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
from textwrap import shorten
import time
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_phase4_entity_resolution_v0"
    / "entity_resolution.sqlite"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "docs" / "experiment-artifacts" / "research_findings_v0.md"
)


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        build_temp_canonical_relations(conn)
        report = build_report(conn, db_path)
    finally:
        conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 4 v0 research queries and write a findings report."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def build_temp_canonical_relations(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS temp.canonical_relations;
        CREATE TEMP TABLE canonical_relations AS
        SELECT
            ra.assertion_id,
            ra.relation_type,
            ra.assertion_strength,
            ra.confidence,
            ra.chunk_id,
            c.document_id,
            d.title AS document_title,
            c.content_type,
            src.resolved_entity_id AS source_id,
            src_re.canonical_name AS source_name,
            src_re.canonical_type AS source_type,
            tgt.resolved_entity_id AS target_id,
            tgt_re.canonical_name AS target_name,
            tgt_re.canonical_type AS target_type
        FROM relation_assertions ra
        JOIN chunks c ON ra.chunk_id = c.chunk_id
        JOIN documents d ON c.document_id = d.document_id
        JOIN entity_mentions src ON ra.source_mention_id = src.mention_id
        JOIN resolved_entities src_re
          ON src.resolved_entity_id = src_re.resolved_entity_id
        JOIN entity_mentions tgt ON ra.target_mention_id = tgt.mention_id
        JOIN resolved_entities tgt_re
          ON tgt.resolved_entity_id = tgt_re.resolved_entity_id
        WHERE src.resolution_status = 'resolved'
          AND tgt.resolution_status = 'resolved'
          AND src_re.entity_status = 'active'
          AND tgt_re.entity_status = 'active';

        CREATE INDEX temp.idx_temp_canonrel_source
            ON canonical_relations(source_id);
        CREATE INDEX temp.idx_temp_canonrel_target
            ON canonical_relations(target_id);
        CREATE INDEX temp.idx_temp_canonrel_type
            ON canonical_relations(relation_type);
        CREATE INDEX temp.idx_temp_canonrel_document
            ON canonical_relations(document_id);
        """
    )


def build_report(conn: sqlite3.Connection, db_path: Path) -> str:
    sections: list[str] = [
        "# Research Findings v0",
        "",
        "日期：2026-05-25",
        "",
        "## 范围",
        "",
        f"- 数据库：`{db_path.relative_to(PROJECT_ROOT)}`",
        "- 数据：战术导弹技术 2026 年第 2 期 10 篇公开论文，Phase 4 Entity Resolution v0.5 输出。",
        "- 方法：只读 SQL 查询；脚本仅创建 SQLite 临时表 `canonical_relations`，不写入数据库，不引入 Neo4j，不创建持久 read model。",
        "- 注意：本文是第一版研究发现验证，不是最终领域结论。当前语料小，统计结果容易被单篇论文主题放大。",
        "",
    ]
    sections.extend(dataset_bias_section(conn))
    sections.extend(research_question_sections(conn))
    sections.extend(product_value_section(conn))
    return "\n".join(sections).rstrip() + "\n"


def dataset_bias_section(conn: sqlite3.Connection) -> list[str]:
    raw_enables = fetchall(
        conn,
        """
        SELECT source_name AS source, source_type AS type,
               COUNT(*) AS raw_relations,
               COUNT(DISTINCT chunk_id) AS chunks,
               COUNT(DISTINCT document_id) AS docs,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE relation_type = 'enables'
        GROUP BY source_id, source_name
        ORDER BY raw_relations DESC, chunks DESC, docs DESC, source_name
        LIMIT 10
        """,
    )
    doc_enables = fetchall(
        conn,
        """
        SELECT source_name AS source, source_type AS type,
               COUNT(*) AS raw_relations,
               COUNT(DISTINCT chunk_id) AS chunks,
               COUNT(DISTINCT document_id) AS docs,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE relation_type = 'enables'
        GROUP BY source_id, source_name
        ORDER BY docs DESC, chunks DESC, raw_relations DESC, source_name
        LIMIT 10
        """,
    )
    gabp = fetchall(
        conn,
        """
        SELECT source_name AS source, source_type AS type,
               COUNT(*) AS raw_relations,
               COUNT(DISTINCT chunk_id) AS chunks,
               COUNT(DISTINCT document_id) AS docs,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE relation_type = 'enables'
          AND source_name = 'GA-BP算法'
        GROUP BY source_id, source_name
        """,
    )
    raw_entities = fetchall(
        conn,
        """
        SELECT re.canonical_name AS canonical, re.canonical_type AS type,
               COUNT(*) AS raw_mentions,
               COUNT(DISTINCT em.chunk_id) AS chunks,
               COUNT(DISTINCT c.document_id) AS docs
        FROM entity_mentions em
        JOIN resolved_entities re ON em.resolved_entity_id = re.resolved_entity_id
        JOIN chunks c ON em.chunk_id = c.chunk_id
        WHERE em.resolution_status = 'resolved'
          AND re.entity_status = 'active'
        GROUP BY re.resolved_entity_id
        ORDER BY raw_mentions DESC, chunks DESC, docs DESC, re.canonical_name
        LIMIT 10
        """,
    )
    doc_entities = fetchall(
        conn,
        """
        SELECT re.canonical_name AS canonical, re.canonical_type AS type,
               COUNT(*) AS raw_mentions,
               COUNT(DISTINCT em.chunk_id) AS chunks,
               COUNT(DISTINCT c.document_id) AS docs
        FROM entity_mentions em
        JOIN resolved_entities re ON em.resolved_entity_id = re.resolved_entity_id
        JOIN chunks c ON em.chunk_id = c.chunk_id
        WHERE em.resolution_status = 'resolved'
          AND re.entity_status = 'active'
        GROUP BY re.resolved_entity_id
        ORDER BY docs DESC, chunks DESC, raw_mentions DESC, re.canonical_name
        LIMIT 10
        """,
    )

    lines = [
        "## 0. 统计口径校准：mention 高频不等于领域共识",
        "",
        "### Q2 原口径：按 enables 原始关系数排序",
        "",
        table(["source", "type", "raw_relations", "chunks", "docs"], raw_enables),
        "",
        "### Q2 修正口径：按 document 去重排序",
        "",
        table(["source", "type", "raw_relations", "chunks", "docs"], doc_enables),
        "",
        "### GA-BP 算法偏置验证",
        "",
        table(["source", "type", "raw_relations", "chunks", "docs", "titles"], gabp),
        "",
        "结论：`GA-BP算法` 的 `8` 条 enables 全部来自同一篇论文的 `4` 个 chunks。它是单篇技术论文主题被重复抽取造成的局部高频，不应按 raw count 解释为领域共识。",
        "",
        "### Q4 原口径：按 mention 数排序",
        "",
        table(["canonical", "type", "raw_mentions", "chunks", "docs"], raw_entities),
        "",
        "### Q4 修正口径：按 document 去重排序",
        "",
        table(["canonical", "type", "raw_mentions", "chunks", "docs"], doc_entities),
        "",
        "结论：后续所有“高频实体 / 高频关系”报告必须同时给出 `raw_mentions/raw_relations`、`chunks` 和 `docs`。默认排序应优先使用 `docs DESC, chunks DESC`，否则单篇论文会放大局部主题。",
        "",
    ]
    return lines


def research_question_sections(conn: sqlite3.Connection) -> list[str]:
    sections: list[str] = []
    sections.extend(space_force_dependencies(conn))
    sections.extend(gabp_applications(conn))
    sections.extend(dual_role_technologies(conn))
    sections.extend(cca_chain(conn))
    sections.extend(abstract_body_overlap(conn))
    sections.extend(sources_with_critical_issues(conn))
    sections.extend(golden_dome_trace(conn))
    sections.extend(enables_pairs(conn))
    return sections


def space_force_dependencies(conn: sqlite3.Connection) -> list[str]:
    rows = fetchall(
        conn,
        """
        SELECT target_name AS object, target_type AS type,
               relation_type AS relation, COUNT(*) AS raw,
               COUNT(DISTINCT chunk_id) AS chunks,
               COUNT(DISTINCT document_id) AS docs,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE source_name = '美国太空军'
          AND relation_type IN ('implements', 'supports', 'applies_to', 'enables')
        GROUP BY target_id, target_name, target_type, relation_type
        ORDER BY docs DESC, chunks DESC, raw DESC, object
        LIMIT 12
        """,
    )
    provider_rows = fetchall(
        conn,
        """
        SELECT p.source_name AS provider, p.target_name AS object,
               p.relation_type AS relation, COUNT(*) AS raw,
               COUNT(DISTINCT p.document_id) AS docs
        FROM canonical_relations sf
        JOIN canonical_relations p ON sf.target_id = p.target_id
        WHERE sf.source_name = '美国太空军'
          AND p.source_name != '美国太空军'
          AND p.source_type = 'Source'
          AND p.relation_type IN ('implements', 'supports', 'enables')
        GROUP BY p.source_id, p.target_id, p.relation_type
        ORDER BY docs DESC, raw DESC, provider, object
        LIMIT 10
        """,
    )
    return [
        "## 1. 美国太空军依赖哪些技术对象？提供方是谁？",
        "",
        table(["object", "type", "relation", "raw", "chunks", "docs", "titles"], rows),
        "",
        "同一批目标对象上的其他 Source 提供方/实施方：",
        "",
        table(["provider", "object", "relation", "raw", "docs"], provider_rows),
        "",
        "发现：当前语料中，美国太空军最清晰的链路不是“依赖某单一底层技术”，而是围绕轨道应用、太空域感知、项目和组织计划形成关系。提供方信息较稀疏，说明现有 schema 更擅长抽实体关系，不足以直接回答供应链或承包商问题。",
        "下一个问题：需要把 `Source` 细分为国家、军种、机构、公司、项目办公室，才能稳定分析提供方。",
        "",
    ]


def gabp_applications(conn: sqlite3.Connection) -> list[str]:
    rows = fetchall(
        conn,
        """
        SELECT relation_type AS relation, source_name AS source, target_name AS target,
               COUNT(*) AS raw,
               COUNT(DISTINCT chunk_id) AS chunks,
               COUNT(DISTINCT document_id) AS docs,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE source_name = 'GA-BP算法'
           OR target_name = 'GA-BP算法'
        GROUP BY relation_type, source_id, target_id
        ORDER BY docs DESC, chunks DESC, raw DESC, relation_type
        LIMIT 15
        """,
    )
    return [
        "## 2. GA-BP 算法在哪些应用场景被提及？涉及几篇论文？",
        "",
        table(["relation", "source", "target", "raw", "chunks", "docs", "titles"], rows),
        "",
        "发现：`GA-BP算法` 当前只出现在 `1` 篇论文中，主要围绕弹用涡喷/涡扇发动机订购价格预测模型。它可以作为“算法应用样例”，但不能作为当前语料中的领域趋势。",
        "下一个问题：如果要判断算法迁移潜力，需要补充更多算法应用论文，而不是从单篇高频里外推。",
        "",
    ]


def dual_role_technologies(conn: sqlite3.Connection) -> list[str]:
    rows = fetchall(
        conn,
        """
        WITH entity_relation AS (
            SELECT source_id AS entity_id, source_name AS entity, source_type AS type,
                   relation_type, document_id, chunk_id
            FROM canonical_relations
            WHERE source_type IN ('Technology', 'EngineeringObject', 'Capability')
            UNION ALL
            SELECT target_id, target_name, target_type,
                   relation_type, document_id, chunk_id
            FROM canonical_relations
            WHERE target_type IN ('Technology', 'EngineeringObject', 'Capability')
        )
        SELECT entity, type,
               SUM(CASE WHEN relation_type = 'enables' THEN 1 ELSE 0 END) AS enables_hits,
               SUM(CASE WHEN relation_type = 'constrains' THEN 1 ELSE 0 END) AS constrains_hits,
               COUNT(DISTINCT document_id) AS docs,
               COUNT(DISTINCT chunk_id) AS chunks
        FROM entity_relation
        GROUP BY entity_id, entity, type
        HAVING enables_hits > 0 AND constrains_hits > 0
        ORDER BY docs DESC, chunks DESC, enables_hits DESC, constrains_hits DESC, entity
        LIMIT 12
        """,
    )
    return [
        "## 3. 哪些技术对象同时出现在 enables 和 constrains 中？",
        "",
        table(["entity", "type", "enables_hits", "constrains_hits", "docs", "chunks"], rows),
        "",
        "发现：这类实体数量很少，当前结果更像是“同一对象在不同上下文中既作为能力来源又作为约束对象”的线索。它们适合进入人工复核，但还不足以直接形成隐边推断。",
        "下一个问题：需要引入证据级复核，区分技术本身的约束、应用场景的约束和供应/组织约束。",
        "",
    ]


def cca_chain(conn: sqlite3.Connection) -> list[str]:
    incoming = fetchall(
        conn,
        """
        SELECT source_name AS source, source_type AS type, relation_type AS relation,
               COUNT(*) AS raw,
               COUNT(DISTINCT document_id) AS docs,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE target_name = '协同作战飞机'
        GROUP BY source_id, source_name, source_type, relation_type
        ORDER BY docs DESC, raw DESC, source_name
        LIMIT 12
        """,
    )
    outgoing = fetchall(
        conn,
        """
        SELECT relation_type AS relation, target_name AS target, target_type AS type,
               COUNT(*) AS raw,
               COUNT(DISTINCT document_id) AS docs,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE source_name = '协同作战飞机'
        GROUP BY relation_type, target_id, target_name, target_type
        ORDER BY docs DESC, raw DESC, target_name
        LIMIT 12
        """,
    )
    return [
        "## 4. 协同作战飞机能力链路：谁指向它？它又指向谁？",
        "",
        "指向 `协同作战飞机`：",
        "",
        table(["source", "type", "relation", "raw", "docs", "titles"], incoming),
        "",
        "`协同作战飞机` 指向的对象：",
        "",
        table(["relation", "target", "type", "raw", "docs", "titles"], outgoing),
        "",
        "发现：CCA 相关链路能回答“项目/平台/概念之间如何互相支撑”，但当前关系方向还需要人工审查。例如某些 `enables` 可能表达“CCA 支撑六代机”，也可能是模型把上下文因果方向抽反。",
        "下一个问题：对候选隐边前，必须把高价值链路的 SourceClaim 和 EvidenceSpan 拉出来做方向校验。",
        "",
    ]


def abstract_body_overlap(conn: sqlite3.Connection) -> list[str]:
    summary = fetchall(
        conn,
        """
        WITH abstract_tech AS (
            SELECT DISTINCT re.resolved_entity_id
            FROM entity_mentions em
            JOIN resolved_entities re ON em.resolved_entity_id = re.resolved_entity_id
            JOIN chunks c ON em.chunk_id = c.chunk_id
            WHERE re.canonical_type = 'Technology'
              AND re.entity_status = 'active'
              AND c.content_type = 'abstract_or_metadata'
        ),
        body_tech AS (
            SELECT DISTINCT re.resolved_entity_id
            FROM entity_mentions em
            JOIN resolved_entities re ON em.resolved_entity_id = re.resolved_entity_id
            JOIN chunks c ON em.chunk_id = c.chunk_id
            WHERE re.canonical_type = 'Technology'
              AND re.entity_status = 'active'
              AND c.content_type IN ('chinese_body', 'mixed_language_body', 'table_or_parameter_dense')
        )
        SELECT
            (SELECT COUNT(*) FROM abstract_tech) AS abstract_technologies,
            (SELECT COUNT(*) FROM body_tech) AS body_technologies,
            (SELECT COUNT(*) FROM abstract_tech JOIN body_tech USING(resolved_entity_id)) AS overlap
        """,
    )
    examples = fetchall(
        conn,
        """
        WITH typed AS (
            SELECT re.resolved_entity_id, re.canonical_name, c.content_type
            FROM entity_mentions em
            JOIN resolved_entities re ON em.resolved_entity_id = re.resolved_entity_id
            JOIN chunks c ON em.chunk_id = c.chunk_id
            WHERE re.canonical_type = 'Technology'
              AND re.entity_status = 'active'
        )
        SELECT canonical_name AS technology,
               MAX(CASE WHEN content_type = 'abstract_or_metadata' THEN 1 ELSE 0 END) AS in_abstract,
               MAX(CASE WHEN content_type IN ('chinese_body', 'mixed_language_body', 'table_or_parameter_dense') THEN 1 ELSE 0 END) AS in_body
        FROM typed
        GROUP BY resolved_entity_id, canonical_name
        HAVING in_abstract = 1 AND in_body = 1
        ORDER BY canonical_name
        LIMIT 20
        """,
    )
    return [
        "## 5. 摘要/元数据中的技术对象与正文有多少重叠？",
        "",
        table(["abstract_technologies", "body_technologies", "overlap"], summary),
        "",
        "重叠样例：",
        "",
        table(["technology", "in_abstract", "in_body"], examples),
        "",
        "发现：摘要技术对象与正文技术对象存在重叠，但数量不高。摘要适合做主题入口，正文仍是关系和证据的主要来源。",
        "下一个问题：报告生成时可以先用摘要召回主题，再用正文 relation/evidence 支撑具体判断。",
        "",
    ]


def sources_with_critical_issues(conn: sqlite3.Connection) -> list[str]:
    rows = fetchall(
        conn,
        """
        SELECT re.canonical_name AS source,
               COUNT(*) AS mentions,
               COUNT(DISTINCT c.chunk_id) AS chunks,
               COUNT(DISTINCT c.document_id) AS docs,
               GROUP_CONCAT(DISTINCT d.title) AS titles
        FROM entity_mentions em
        JOIN resolved_entities re ON em.resolved_entity_id = re.resolved_entity_id
        JOIN chunks c ON em.chunk_id = c.chunk_id
        JOIN documents d ON c.document_id = d.document_id
        JOIN issues i ON em.chunk_id = i.chunk_id
        WHERE re.canonical_type = 'Source'
          AND re.entity_status = 'active'
          AND i.severity = 'critical'
        GROUP BY re.resolved_entity_id, re.canonical_name
        HAVING docs >= 3
        ORDER BY docs DESC, chunks DESC, mentions DESC, source
        LIMIT 20
        """,
    )
    fallback = fetchall(
        conn,
        """
        SELECT re.canonical_name AS source,
               COUNT(*) AS mentions,
               COUNT(DISTINCT c.chunk_id) AS chunks,
               COUNT(DISTINCT c.document_id) AS docs,
               GROUP_CONCAT(DISTINCT d.title) AS titles
        FROM entity_mentions em
        JOIN resolved_entities re ON em.resolved_entity_id = re.resolved_entity_id
        JOIN chunks c ON em.chunk_id = c.chunk_id
        JOIN documents d ON c.document_id = d.document_id
        JOIN issues i ON em.chunk_id = i.chunk_id
        WHERE re.canonical_type = 'Source'
          AND re.entity_status = 'active'
          AND i.severity = 'critical'
        GROUP BY re.resolved_entity_id, re.canonical_name
        ORDER BY docs DESC, chunks DESC, mentions DESC, source
        LIMIT 10
        """,
    )
    return [
        "## 6. 哪些 Source 横跨多个 document 且关联 critical issue？",
        "",
        "筛选条件：`docs >= 3`。",
        "",
        table(["source", "mentions", "chunks", "docs", "titles"], rows),
        "",
        "放宽后 top 10：",
        "",
        table(["source", "mentions", "chunks", "docs", "titles"], fallback),
        "",
        "发现：严格 `docs >= 3` 下只有 `美国` 命中，且它是粒度很粗的国家 actor。critical issue 更像局部抽取结构问题，不宜直接归因到某个具体 source。",
        "下一个问题：数据质量看板应优先按 chunk/doc 定位，而不是按 source 归因。",
        "",
    ]


def golden_dome_trace(conn: sqlite3.Connection) -> list[str]:
    entity_rows = fetchall(
        conn,
        """
        SELECT re.canonical_name AS canonical, re.canonical_type AS type,
               re.mention_count AS mentions, re.chunk_count AS chunks,
               re.document_count AS docs, re.alias_json AS aliases
        FROM resolved_entities re
        WHERE re.canonical_name LIKE '%金穹%'
        ORDER BY re.mention_count DESC
        """,
    )
    relation_rows = fetchall(
        conn,
        """
        SELECT relation_type AS relation, source_name AS source, target_name AS target,
               assertion_strength AS strength, confidence,
               document_title AS document, chunk_id AS chunk
        FROM canonical_relations
        WHERE source_name LIKE '%金穹%'
           OR target_name LIKE '%金穹%'
        ORDER BY document_title, relation_type, source_name, target_name
        LIMIT 20
        """,
    )
    claim_rows = fetchall(
        conn,
        """
        SELECT cr.relation_type AS relation, cr.source_name AS source, cr.target_name AS target,
               sc.claim_type, sc.modality, sc.confidence,
               sc.text AS claim_text,
               es.quote AS evidence_quote,
               es.match_status AS match,
               cr.document_title AS document
        FROM canonical_relations cr
        JOIN relation_claim_links rcl ON cr.assertion_id = rcl.assertion_id
        JOIN source_claims sc ON rcl.claim_id = sc.claim_id
        LEFT JOIN evidence_claim_links ecl ON sc.claim_id = ecl.claim_id
        LEFT JOIN evidence_spans es ON ecl.evidence_span_id = es.evidence_span_id
        WHERE cr.source_name LIKE '%金穹%'
           OR cr.target_name LIKE '%金穹%'
           OR sc.text LIKE '%金穹%'
           OR es.quote LIKE '%金穹%'
        ORDER BY cr.document_title, cr.relation_type, cr.source_name, cr.target_name
        LIMIT 12
        """,
    )
    claim_rows = [
        {
            **dict(row),
            "claim_text": compact_text(row["claim_text"], width=50),
            "evidence_quote": compact_text(row["evidence_quote"], width=50),
        }
        for row in claim_rows
    ]
    return [
        "## 7. “金穹”项目的关联实体、声明和证据",
        "",
        "实体：",
        "",
        table(["canonical", "type", "mentions", "chunks", "docs", "aliases"], entity_rows),
        "",
        "关系：",
        "",
        table(["relation", "source", "target", "strength", "confidence", "document", "chunk"], relation_rows),
        "",
        "声明与证据摘录：",
        "",
        table(["relation", "source", "target", "claim_type", "modality", "confidence", "claim_text", "evidence_quote", "match", "document"], claim_rows),
        "",
        "发现：`金穹` 在当前语料中可完整追到关系、claim 和 evidence，但关系数量有限，更适合作为溯源链路验证样例，而不是趋势统计样本。",
        "下一个问题：如果要让用户信任隐边报告，产品界面必须能像本查询一样从关系回到 claim/evidence。",
        "",
    ]


def enables_pairs(conn: sqlite3.Connection) -> list[str]:
    rows = fetchall(
        conn,
        """
        SELECT source_name AS source, target_name AS target,
               COUNT(*) AS raw,
               COUNT(DISTINCT chunk_id) AS chunks,
               COUNT(DISTINCT document_id) AS docs,
               ROUND(AVG(confidence), 3) AS avg_conf,
               GROUP_CONCAT(DISTINCT document_title) AS titles
        FROM canonical_relations
        WHERE relation_type = 'enables'
        GROUP BY source_id, target_id
        ORDER BY docs DESC, chunks DESC, raw DESC, avg_conf DESC,
                 source_name, target_name
        LIMIT 20
        """,
    )
    return [
        "## 8. enables 高频 source-target 配对前 20",
        "",
        table(["source", "target", "raw", "chunks", "docs", "avg_conf", "titles"], rows),
        "",
        "发现：按 document 去重后，多数 enables 配对仍只来自 1 篇论文。这说明当前语料还不足以稳定抽出跨文档“技术使能模式”。",
        "下一个问题：扩充语料前，不宜把单个 enables 配对直接上升为创新方向；更适合把它们作为候选线索交给人工复核。",
        "",
    ]


def product_value_section(conn: sqlite3.Connection) -> list[str]:
    stats = fetchone(
        conn,
        """
        SELECT
            (SELECT COUNT(*) FROM canonical_relations) AS canonical_relations,
            (SELECT COUNT(DISTINCT document_id) FROM canonical_relations) AS documents_with_relations,
            (SELECT COUNT(*) FROM resolved_entities WHERE entity_status = 'active') AS active_entities
        """,
    )
    return [
        "## 当前产品价值判断",
        "",
        table(["canonical_relations", "documents_with_relations", "active_entities"], [stats]),
        "",
        "Case 判断：当前更接近 **Case A/B 之间**。",
        "",
        "- 能产出有用发现：GA-BP 高频偏置、美国太空军口径收窄、CCA 链路需要方向校验、金穹可溯源。",
        "- 价值不足之处：10 篇论文太少，多数关系配对只来自 1 篇文档，跨文档共识信号还弱。",
        "- 工程痛点：查询可以写出来，性能不是主要障碍；主要障碍是统计口径和 SQL 认知成本。",
        "",
        "下一步建议：先扩充语料并建立文档去重统计规范；如继续做基础设施，只做最朴素的临时或物化 `canonical_relations` 查询表，不引入复杂 projection 框架，也不直接上 Neo4j。",
        "",
    ]


def fetchall(conn: sqlite3.Connection, query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    start = time.perf_counter()
    rows = [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
    elapsed_ms = (time.perf_counter() - start) * 1000
    for row in rows:
        row.setdefault("_elapsed_ms", round(elapsed_ms, 3))
    return rows


def fetchone(conn: sqlite3.Connection, query: str, params: Iterable[Any] = ()) -> dict[str, Any]:
    rows = fetchall(conn, query, params)
    return rows[0] if rows else {}


def table(headers: list[str], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_无结果_"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = []
        for header in headers:
            value = row.get(header, "")
            values.append(escape_markdown(compact_text(value)))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def compact_text(value: Any, width: int = 80) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    return shorten(text, width=width, placeholder="...")


def escape_markdown(value: str) -> str:
    return value.replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
