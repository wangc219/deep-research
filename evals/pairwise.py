from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import random
import re

from .models import EvalQuery, EvalRunResult, PairwiseJudgment, write_jsonl


SYSTEM_MARKERS = {
    "full_method": "参测系统",
    "generic_deep_research": "参测系统",
    "generic_agent": "参测系统",
    "bare_llm": "参测系统",
    "zhipu_llm": "参测系统",
    "no_domain_agents": "参测系统",
    "no_winning_chain": "参测系统",
    "no_feedback_loops": "参测系统",
    "no_multisource_baseline": "参测系统",
    "no_winning_mechanism": "参测系统",
}

MAX_EVIDENCE_ITEMS_PER_ANSWER = 48
MAX_EVIDENCE_CONTEXT_CHARS = 16_000


def build_blind_pairs(
    queries: Iterable[EvalQuery],
    results: Iterable[EvalRunResult],
    output_dir: str | Path,
    *,
    left_system: str,
    right_system: str,
    seed: int = 20260718,
    include_reverse: bool = True,
) -> dict[str, Any]:
    query_map = {item.query_id: item for item in queries}
    result_map = {(item.query_id, item.system_id): item for item in results}
    rng = random.Random(seed)
    public_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    for query_id in sorted(query_map):
        left = result_map.get((query_id, left_system))
        right = result_map.get((query_id, right_system))
        if not left or not right or left.status != "completed" or right.status != "completed":
            continue
        orders = [(left, right, False)]
        if include_reverse:
            orders.append((right, left, True))
        elif rng.random() < 0.5:
            orders = [(right, left, True)]
        for order_index, (answer_a, answer_b, reversed_order) in enumerate(orders, start=1):
            pair_id = "P-" + hashlib.sha256(
                f"{seed}:{query_id}:{left_system}:{right_system}:{order_index}".encode()
            ).hexdigest()[:12]
            public_rows.append(
                {
                    "pair_id": pair_id,
                    "query_id": query_id,
                    "query": query_map[query_id].query,
                    "answer_a": anonymize_answer(answer_a.answer),
                    "answer_b": anonymize_answer(answer_b.answer),
                    "evidence_a": render_evidence_context(answer_a),
                    "evidence_b": render_evidence_context(answer_b),
                }
            )
            mapping_rows.append(
                {
                    "pair_id": pair_id,
                    "query_id": query_id,
                    "system_a": answer_a.system_id,
                    "system_b": answer_b.system_id,
                    "reversed": reversed_order,
                }
            )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "pairs.public.jsonl", public_rows)
    write_jsonl(output / "pairs.admin.jsonl", mapping_rows)
    return {"pair_count": len(public_rows), "query_count": len({row["query_id"] for row in public_rows})}


def anonymize_answer(answer: str) -> str:
    result = str(answer)
    for marker, replacement in SYSTEM_MARKERS.items():
        result = re.sub(re.escape(marker), replacement, result, flags=re.IGNORECASE)
    result = re.sub(r"(?i)equipment[_ -]?deep[_ -]?research", "参测系统", result)
    return result


def render_evidence_context(result: EvalRunResult) -> str:
    """Render compact, anonymous evidence metadata for the blind judge.

    Full-method reports intentionally keep most evidence in the data center
    instead of repeating every source in the prose. Pairwise judging therefore
    needs this bounded companion context to avoid treating compact reporting as
    missing evidence.
    """

    rows: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in result.evidence_context[:MAX_EVIDENCE_ITEMS_PER_ANSWER]:
        if not isinstance(item, dict):
            continue
        url = _clean_evidence_value(item.get("source_url"), 500)
        claim = _clean_evidence_value(item.get("claim"), 420)
        key = (url, claim)
        if not url or not claim or key in seen:
            continue
        seen.add(key)
        rows.append(f"- URL：{url}；摘要：{claim}")

    if not rows:
        return "未提供独立的证据元数据；仅可依据正文中的显式证据进行评判。"
    rendered = "\n".join(rows)
    if len(rendered) > MAX_EVIDENCE_CONTEXT_CHARS:
        rendered = rendered[:MAX_EVIDENCE_CONTEXT_CHARS].rsplit("\n", 1)[0]
        rendered += "\n- （证据上下文已按评测长度上限截断）"
    return rendered


def _clean_evidence_value(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def render_judge_prompt(pair: dict[str, Any], template: str) -> str:
    return (
        template.replace("{{QUERY}}", str(pair["query"]))
        .replace("{{ANSWER_A}}", str(pair["answer_a"]))
        .replace("{{ANSWER_B}}", str(pair["answer_b"]))
        .replace("{{EVIDENCE_A}}", str(pair.get("evidence_a", "")))
        .replace("{{EVIDENCE_B}}", str(pair.get("evidence_b", "")))
        .replace("{{PAIR_ID}}", str(pair["pair_id"]))
    )


def parse_judgment(text: str, *, pair_id: str, judge_id: str) -> PairwiseJudgment:
    value = str(text).strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE | re.DOTALL)
    payload = json.loads(value)
    judgment = PairwiseJudgment(
        pair_id=pair_id,
        judge_id=judge_id,
        winner=str(payload["winner"]),
        confidence=float(payload["confidence"]),
        dimensions={str(key): str(item) for key, item in dict(payload["dimensions"]).items()},
        reason=str(payload.get("reason", "")),
        citation_issues=[str(item) for item in payload.get("citation_issues", [])],
        hard_failures=[str(item) for item in payload.get("hard_failures", [])],
        primary_route=str(payload.get("primary_route", "")),
        secondary_routes=[str(item) for item in payload.get("secondary_routes", [])],
        route_confidence=float(payload.get("route_confidence", 0.0)),
        preference_strength=str(payload.get("preference_strength", "")),
        route_deliverable_check=dict(payload.get("route_deliverable_check", {})),
        adjudication_required=bool(payload.get("adjudication_required", False)),
        adjudication_reasons=[
            str(item) for item in payload.get("adjudication_reasons", [])
        ],
    )
    judgment.validate()
    return judgment
