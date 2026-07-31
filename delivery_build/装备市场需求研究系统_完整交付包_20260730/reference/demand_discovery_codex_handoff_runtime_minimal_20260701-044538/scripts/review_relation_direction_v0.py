"""Create a deterministic relation-direction spot check report.

The script samples high-confidence enables/supports/applies_to assertions from
the Phase 4 SQLite database, applies the current manual review labels embedded
below, and writes a Markdown report. It does not modify the database.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from textwrap import shorten
from typing import Any


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
    PROJECT_ROOT / "docs" / "manual-review" / "relation_direction_spotcheck_v0.md"
)

RELATION_TARGETS = {
    "enables": 20,
    "supports": 15,
    "applies_to": 15,
}

# Labels are intentionally stored in code so the same sampled assertions can be
# re-scored after prompt/schema changes. Values:
# correct, reversed, ambiguous, wrong_relation
MANUAL_LABELS: dict[str, tuple[str, str]] = {
    "doc-2025-a2a57bf570-chunk-0002::relation::r3": (
        "correct",
        "Evidence explicitly says cross-domain coordination is enabled by swarm intelligence.",
    ),
    "doc-2025-93ed1296d0-chunk-0003::relation::r1": (
        "correct",
        "Evidence states multi-domain technology development improves operational effectiveness.",
    ),
    "doc-2025-aea7d802cb-chunk-0002::relation::r3": (
        "wrong_relation",
        "Direction is not reversed, but evidence says requirements drive adoption; 'drives' is a better relation than enables.",
    ),
    "doc-2025-ae008ab3d1-chunk-0002::relation::r5": (
        "correct",
        "Evidence says space-based detection/interception capabilities play a role in deterrence.",
    ),
    "doc-2025-48e136bc24-chunk-0006::relation::r4": (
        "correct",
        "Evidence says the system effectively improves awareness and decision capability.",
    ),
    "doc-2025-910b69851e-chunk-0002::relation::r2": (
        "correct",
        "Evidence says new air and missile defense systems promote low-cost efficient defense means.",
    ),
    "doc-2025-91686cf0be-chunk-0001::relation::r8": (
        "correct",
        "Evidence says commercial forces are used to develop orbital transfer equipment.",
    ),
    "doc-2025-2b25f10056-chunk-0002::relation::r1": (
        "wrong_relation",
        "Evidence says USSF is transitioning to operational deployment; this is not an enables relation.",
    ),
    "doc--08d321eede-chunk-0001::relation::r3": (
        "correct",
        "Evidence says the code can capture flow-field evolution features.",
    ),
    "doc-GA-BP-1483d11819-chunk-0001::relation::r5": (
        "correct",
        "Evidence says the method can satisfy engine price estimation.",
    ),
    "doc-2025-a2a57bf570-chunk-0004::relation::r1": (
        "correct",
        "Evidence says AI gives rise to a new operational paradigm.",
    ),
    "doc-2025-93ed1296d0-chunk-0005::relation::r4": (
        "ambiguous",
        "Evidence says CCA development focuses on improving autonomy; not enough to assert CCA enables the capability.",
    ),
    "doc-2025-aea7d802cb-chunk-0002::relation::r4": (
        "wrong_relation",
        "Direction is not reversed, but evidence says requirements accelerate technology verification; 'drives' is a better relation.",
    ),
    "doc-2025-ae008ab3d1-chunk-0002::relation::r6": (
        "correct",
        "Evidence says the capability will play a role in future operational effectiveness.",
    ),
    "doc-2025-48e136bc24-chunk-0006::relation::r5": (
        "correct",
        "Evidence says TOC-L has agile deployment capability.",
    ),
    "doc-2025-910b69851e-chunk-0002::relation::r5": (
        "correct",
        "Evidence says new air and missile defense systems build space advantages.",
    ),
    "doc-2025-91686cf0be-chunk-0001::relation::r9": (
        "correct",
        "Evidence says commercial forces are used to develop in-orbit refueling equipment.",
    ),
    "doc-2025-2b25f10056-chunk-0005::relation::r1": (
        "correct",
        "Evidence says the plan aims to improve the ability to maintain space superiority.",
    ),
    "doc--08d321eede-chunk-0003::relation::r3": (
        "correct",
        "Evidence says the in-house code can simulate flow feature evolutions.",
    ),
    "doc-GA-BP-1483d11819-chunk-0021::relation::r3": (
        "ambiguous",
        "Evidence says GA-BP incorporates global search ability; it is closer to has_capability than enables.",
    ),
    "doc-2025-a2a57bf570-chunk-0004::relation::r6": (
        "correct",
        "Evidence says major countries promote military intelligence development.",
    ),
    "doc-2025-93ed1296d0-chunk-0003::relation::r4": (
        "correct",
        "Evidence says major military powers support UAV technology development.",
    ),
    "doc-2025-aea7d802cb-chunk-0002::relation::r5": (
        "correct",
        "Evidence says resilient space communication architectures are a strategic direction for TT&C capabilities.",
    ),
    "doc-2025-ae008ab3d1-chunk-0001::relation::r2": (
        "correct",
        "Evidence says space-based detection/interception capabilities are key support for deterrence/effectiveness.",
    ),
    "doc-2025-48e136bc24-chunk-0002::relation::r1": (
        "correct",
        "Evidence says 5G is used to support command and control systems.",
    ),
    "doc-2025-910b69851e-chunk-0004::relation::r1": (
        "correct",
        "Evidence says countries improve operational capabilities through system upgrades and deployment.",
    ),
    "doc-2025-91686cf0be-chunk-0001::relation::r1": (
        "correct",
        "Evidence says top-level strategy guides future space operations system planning.",
    ),
    "doc-2025-2b25f10056-chunk-0002::relation::r2": (
        "correct",
        "Evidence says space capabilities have a prominent central role in national security framework.",
    ),
    "doc--08d321eede-chunk-0001::relation::r2": (
        "correct",
        "Evidence says classic experiments verify computational code reliability.",
    ),
    "doc-GA-BP-1483d11819-chunk-0001::relation::r2": (
        "correct",
        "Evidence names GA-BP as the basis of the proposed price prediction method.",
    ),
    "doc-2025-a2a57bf570-chunk-0005::relation::r6": (
        "correct",
        "Evidence says AI applications are placed first in the critical technology list.",
    ),
    "doc-2025-93ed1296d0-chunk-0005::relation::r1": (
        "correct",
        "Evidence says CCA operates under command/control/collaboration of manned aircraft.",
    ),
    "doc-2025-aea7d802cb-chunk-0002::relation::r6": (
        "correct",
        "Evidence says software-defined TT&C technologies are a strategic direction for TT&C capabilities.",
    ),
    "doc-2025-ae008ab3d1-chunk-0002::relation::r2": (
        "correct",
        "Evidence says technological autonomy is a component of national security strategies.",
    ),
    "doc-2025-48e136bc24-chunk-0002::relation::r2": (
        "correct",
        "Evidence says cloud computing is used to support command and control systems.",
    ),
    "doc-2025-a2a57bf570-chunk-0002::relation::r1": (
        "correct",
        "Evidence says machine intelligence is deeply integrated into operational tasks.",
    ),
    "doc-2025-93ed1296d0-chunk-0003::relation::r5": (
        "correct",
        "Evidence says UAV equipment has been applied to ground strikes.",
    ),
    "doc-2025-aea7d802cb-chunk-0006::relation::r5": (
        "wrong_relation",
        "Evidence says the center is handled by the task force; relation should be responsible_for, not applies_to.",
    ),
    "doc-2025-ae008ab3d1-chunk-0002::relation::r4": (
        "correct",
        "Evidence says space is emerging as a critical domain in missile defense.",
    ),
    "doc-2025-48e136bc24-chunk-0003::relation::r2": (
        "correct",
        "Evidence says disruptive technologies are applied and demonstrated in exercises/tests.",
    ),
    "doc-2025-910b69851e-chunk-0006::relation::r1": (
        "correct",
        "Evidence says the regiment is equipped with S-500 and enters deployment; source-to-target application is acceptable.",
    ),
    "doc-2025-91686cf0be-chunk-0010::relation::r2": (
        "reversed",
        "Evidence says USSF optimizes the commercial procurement strategy; extracted direction is strategy -> USSF.",
    ),
    "doc-2025-2b25f10056-chunk-0014::relation::r2": (
        "correct",
        "Evidence says mission-centered standards optimize guardian fitness/readiness.",
    ),
    "doc--08d321eede-chunk-0003::relation::r8": (
        "wrong_relation",
        "Evidence says reflection shock re-enters the propellant channel; relation should be enters/located_in, not applies_to.",
    ),
    "doc-GA-BP-1483d11819-chunk-0003::relation::r4": (
        "correct",
        "Evidence says the parameter method is mainly used in the demonstration/design phase.",
    ),
    "doc-2025-a2a57bf570-chunk-0002::relation::r5": (
        "correct",
        "Evidence says AI is established as a central instrument in great-power military competition.",
    ),
    "doc-2025-93ed1296d0-chunk-0003::relation::r6": (
        "correct",
        "Evidence says UAV equipment has been applied to special operations.",
    ),
    "doc-2025-aea7d802cb-chunk-0006::relation::r6": (
        "wrong_relation",
        "Evidence says the center is handled by the 8th Space Delta; relation should be responsible_for, not applies_to.",
    ),
    "doc-2025-ae008ab3d1-chunk-0003::relation::r1": (
        "correct",
        "Evidence says missile offense-defense confrontation escalates in the Ukraine battlefield.",
    ),
    "doc-2025-48e136bc24-chunk-0004::relation::r2": (
        "correct",
        "Evidence says the AI-driven C2 capability is expected at theater/corps/division command institutions.",
    ),
}


@dataclass(frozen=True)
class SampleRow:
    assertion_id: str
    relation_type: str
    source: str
    source_type: str
    target: str
    target_type: str
    confidence: float
    strength: str
    document_title: str
    chunk_id: str
    claim_text: str
    evidence_quote: str
    chunk_text: str


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        samples = sample_relations(conn)
        report = build_report(samples, db_path)
    finally:
        conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample high-confidence relation directions for spot checking."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def sample_relations(conn: sqlite3.Connection) -> list[SampleRow]:
    candidates = fetch_candidates(conn)
    samples: list[SampleRow] = []
    for relation_type, target_count in RELATION_TARGETS.items():
        rel_candidates = [row for row in candidates if row.relation_type == relation_type]
        samples.extend(stratified_pick(rel_candidates, target_count))
    return samples


def fetch_candidates(conn: sqlite3.Connection) -> list[SampleRow]:
    rows = conn.execute(
        """
        SELECT
            ra.assertion_id,
            ra.relation_type,
            src_re.canonical_name AS source,
            src_re.canonical_type AS source_type,
            tgt_re.canonical_name AS target,
            tgt_re.canonical_type AS target_type,
            ra.confidence,
            ra.assertion_strength AS strength,
            d.title AS document_title,
            c.chunk_id,
            c.text AS chunk_text,
            GROUP_CONCAT(DISTINCT sc.text) AS claim_text,
            GROUP_CONCAT(DISTINCT es.quote) AS evidence_quote
        FROM relation_assertions ra
        JOIN chunks c ON ra.chunk_id = c.chunk_id
        JOIN documents d ON c.document_id = d.document_id
        JOIN entity_mentions src ON ra.source_mention_id = src.mention_id
        JOIN resolved_entities src_re
          ON src.resolved_entity_id = src_re.resolved_entity_id
        JOIN entity_mentions tgt ON ra.target_mention_id = tgt.mention_id
        JOIN resolved_entities tgt_re
          ON tgt.resolved_entity_id = tgt_re.resolved_entity_id
        LEFT JOIN relation_claim_links rcl ON ra.assertion_id = rcl.assertion_id
        LEFT JOIN source_claims sc ON rcl.claim_id = sc.claim_id
        LEFT JOIN evidence_claim_links ecl ON sc.claim_id = ecl.claim_id
        LEFT JOIN evidence_spans es ON ecl.evidence_span_id = es.evidence_span_id
        WHERE ra.relation_type IN ('enables', 'supports', 'applies_to')
          AND ra.confidence >= 0.9
          AND src.resolution_status = 'resolved'
          AND tgt.resolution_status = 'resolved'
          AND src_re.entity_status = 'active'
          AND tgt_re.entity_status = 'active'
        GROUP BY ra.assertion_id
        ORDER BY ra.relation_type, d.title, c.chunk_id, ra.assertion_id
        """
    ).fetchall()
    return [
        SampleRow(
            assertion_id=row["assertion_id"],
            relation_type=row["relation_type"],
            source=row["source"],
            source_type=row["source_type"],
            target=row["target"],
            target_type=row["target_type"],
            confidence=float(row["confidence"]),
            strength=row["strength"],
            document_title=row["document_title"],
            chunk_id=row["chunk_id"],
            claim_text=row["claim_text"] or "",
            evidence_quote=row["evidence_quote"] or "",
            chunk_text=row["chunk_text"] or "",
        )
        for row in rows
    ]


def stratified_pick(rows: list[SampleRow], target_count: int) -> list[SampleRow]:
    if len(rows) <= target_count:
        return rows
    by_doc: dict[str, list[SampleRow]] = {}
    for row in rows:
        by_doc.setdefault(row.document_title, []).append(row)

    picked: list[SampleRow] = []
    doc_names = sorted(by_doc)
    cursor = 0
    while len(picked) < target_count:
        made_progress = False
        for doc_name in doc_names:
            doc_rows = by_doc[doc_name]
            if cursor < len(doc_rows):
                picked.append(doc_rows[cursor])
                made_progress = True
                if len(picked) >= target_count:
                    break
        if not made_progress:
            break
        cursor += 1
    return picked


def build_report(samples: list[SampleRow], db_path: Path) -> str:
    label_counts = Counter(label_for(row.assertion_id)[0] for row in samples)
    reviewed = sum(label_counts.values())
    reversed_count = label_counts["reversed"]
    error_like = label_counts["reversed"] + label_counts["wrong_relation"]
    path_unsafe = error_like + label_counts["ambiguous"]
    resolved_reviewed = reviewed - label_counts["unlabeled"]

    lines = [
        "# Relation Direction Spot Check v0",
        "",
        "日期：2026-05-25",
        "",
        "## 范围",
        "",
        f"- 数据库：`{db_path.relative_to(PROJECT_ROOT)}`",
        "- 抽样对象：`confidence >= 0.9` 的 `enables / supports / applies_to` 关系。",
        "- 抽样方法：按关系类型定额抽样，目标 `enables=20`、`supports=15`、`applies_to=15`，并按文档轮转，避免单篇文档垄断样本。",
        "- 判定依据：优先看 `SourceClaim` 和 exact evidence；证据不足时看同一 chunk 原文片段。",
        "",
        "## 结果",
        "",
        f"- 样本数：`{reviewed}`",
        f"- 已标注：`{resolved_reviewed}`",
        f"- correct：`{label_counts['correct']}`",
        f"- reversed：`{reversed_count}`",
        f"- wrong_relation：`{label_counts['wrong_relation']}`",
        f"- ambiguous：`{label_counts['ambiguous']}`",
        f"- unlabeled：`{label_counts['unlabeled']}`",
        "",
    ]
    if resolved_reviewed:
        lines.extend(
            [
                f"- 方向抽反率：`{reversed_count / resolved_reviewed:.1%}`",
                f"- 严格错误率（reversed + wrong_relation）：`{error_like / resolved_reviewed:.1%}`",
                f"- 路径推断不安全率（reversed + wrong_relation + ambiguous）：`{path_unsafe / resolved_reviewed:.1%}`",
                "",
            ]
        )
    lines.extend(
        [
            "解释：`ambiguous` 不计入严格错误，但表示证据或关系语义不足以支撑后续自动多跳推断。",
            "",
            "## 分类型统计",
            "",
            table(
                ["relation", "samples", "correct", "reversed", "wrong_relation", "ambiguous", "unlabeled"],
                relation_summary(samples),
            ),
            "",
            "## 样本明细",
            "",
        ]
    )
    for index, row in enumerate(samples, start=1):
        label, note = label_for(row.assertion_id)
        lines.extend(
            [
                f"### {index}. {row.relation_type}: {row.source} -> {row.target}",
                "",
                f"- assertion_id：`{row.assertion_id}`",
                f"- label：`{label}`",
                f"- note：{note}",
                f"- source_type / target_type：`{row.source_type}` / `{row.target_type}`",
                f"- confidence / strength：`{row.confidence}` / `{row.strength}`",
                f"- document：{row.document_title}",
                f"- chunk：`{row.chunk_id}`",
                f"- claim：{compact(row.claim_text, 180)}",
                f"- evidence：{compact(row.evidence_quote, 220)}",
                f"- chunk_excerpt：{compact(row.chunk_text, 260)}",
                "",
            ]
        )
    lines.extend(
        [
            "## 判定阈值",
            "",
            "- `< 5%`：方向错误率可接受，作为 known issue 文档化。",
            "- `5-20%`：需要修改抽取 prompt，并对关键关系部分重抽。",
            "- `> 20%`：抽取层需要返工，不应进入 HypothesisLink。",
            "",
            "## 当前判断",
            "",
            "当前样本的方向抽反率低于 5%，没有证据表明存在大规模方向反转。但严格错误率落入 5-20% 区间，主要来自 `enables/applies_to` 被用于表达 `drives / responsible_for / has_capability / enters` 等关系。进入 HypothesisLink 前应修改抽取 prompt，并对高价值关系做部分重抽或人工审核。",
            "",
        ]
    )
    return "\n".join(lines)


def relation_summary(samples: list[SampleRow]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relation_type in RELATION_TARGETS:
        rel_samples = [row for row in samples if row.relation_type == relation_type]
        counts = Counter(label_for(row.assertion_id)[0] for row in rel_samples)
        rows.append(
            {
                "relation": relation_type,
                "samples": len(rel_samples),
                "correct": counts["correct"],
                "reversed": counts["reversed"],
                "wrong_relation": counts["wrong_relation"],
                "ambiguous": counts["ambiguous"],
                "unlabeled": counts["unlabeled"],
            }
        )
    return rows


def label_for(assertion_id: str) -> tuple[str, str]:
    return MANUAL_LABELS.get(assertion_id, ("unlabeled", "pending manual review"))


def table(headers: list[str], rows: list[dict[str, Any]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    return "\n".join(output)


def compact(value: str, width: int) -> str:
    text = " ".join((value or "").replace("\r", " ").replace("\n", " ").split())
    return shorten(text, width=width, placeholder="...")


if __name__ == "__main__":
    raise SystemExit(main())
