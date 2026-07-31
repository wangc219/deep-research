from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import json

from .models import EvalQuery, EvalRunResult


BASELINE_REPORT_SYSTEMS = frozenset({"generic_agent", "bare_llm", "zhipu_llm"})


def query_fingerprint(query: str) -> str:
    return sha256(str(query).strip().encode("utf-8")).hexdigest()


class BaselineReportLibrary:
    """Immutable report storage shared by benchmark execution and later judging."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def save_completed(
        self,
        *,
        dataset_id: str,
        queries: Iterable[EvalQuery],
        results: Iterable[EvalRunResult],
        source_eval_id: str,
        mode: str,
    ) -> list[dict[str, Any]]:
        query_map = {item.query_id: item for item in queries}
        saved: list[dict[str, Any]] = []
        for result in results:
            if (
                result.system_id not in BASELINE_REPORT_SYSTEMS
                or result.status != "completed"
                or not result.answer.strip()
                or any(str(ref).startswith("baseline_report:") for ref in result.artifact_refs)
            ):
                continue
            query = query_map.get(result.query_id)
            if query is None:
                continue
            answer_hash = sha256(result.answer.encode("utf-8")).hexdigest()
            report_id = "BR-" + sha256(
                f"{source_eval_id}\0{result.query_id}\0{result.system_id}\0{answer_hash}".encode(
                    "utf-8"
                )
            ).hexdigest()[:24]
            report_dir = self.root / report_id
            report_path = report_dir / "report.md"
            metadata_path = report_dir / "report.json"
            if metadata_path.is_file() and report_path.is_file():
                continue
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text(result.answer, encoding="utf-8")
            metadata = {
                "schema_version": "1.0",
                "report_id": report_id,
                "dataset_id": dataset_id,
                "query_id": query.query_id,
                "query": query.query,
                "query_sha256": query_fingerprint(query.query),
                "system_id": result.system_id,
                "status": result.status,
                "citations": list(result.citations),
                "sources": list(result.sources),
                "evidence_context": list(result.evidence_context),
                "duration_seconds": float(result.duration_seconds),
                "usage": dict(result.usage),
                "model_snapshot": dict(result.model_snapshot),
                "estimated_cost": float(result.estimated_cost),
                "artifact_refs": list(result.artifact_refs),
                "answer_sha256": answer_hash,
                "answer_chars": len(result.answer),
                "report_path": str(report_path),
                "source_eval_id": source_eval_id,
                "mode": mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            temporary = metadata_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(metadata_path)
            saved.append(metadata)
        return saved

    def list(
        self,
        *,
        dataset_id: str | None = None,
        query_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.root.is_dir():
            return rows
        for report_dir in self.root.iterdir():
            metadata_path = report_dir / "report.json"
            report_path = report_dir / "report.md"
            if not report_dir.is_dir() or not metadata_path.is_file() or not report_path.is_file():
                continue
            try:
                row = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if dataset_id is not None and row.get("dataset_id") != dataset_id:
                continue
            if query_ids is not None and str(row.get("query_id")) not in query_ids:
                continue
            rows.append(row)
        return sorted(rows, key=lambda row: str(row.get("created_at", "")), reverse=True)

    def load(self, report_id: str) -> dict[str, Any]:
        report_dir = self.root / report_id
        if report_dir.parent.resolve() != self.root:
            raise ValueError("baseline report path escapes report library")
        metadata_path = report_dir / "report.json"
        report_path = report_dir / "report.md"
        if not metadata_path.is_file() or not report_path.is_file():
            raise FileNotFoundError(report_id)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        answer = report_path.read_text(encoding="utf-8")
        if sha256(answer.encode("utf-8")).hexdigest() != metadata.get("answer_sha256"):
            raise ValueError(f"baseline report content hash mismatch: {report_id}")
        return {**metadata, "answer": answer}

    def as_eval_result(self, report_id: str, *, eval_id: str) -> EvalRunResult:
        row = self.load(report_id)
        return EvalRunResult(
            eval_id=eval_id,
            query_id=str(row["query_id"]),
            system_id=str(row["system_id"]),
            status="completed",
            answer=str(row["answer"]),
            citations=[str(item) for item in row.get("citations", [])],
            sources=[str(item) for item in row.get("sources", [])],
            evidence_context=[
                dict(item)
                for item in row.get("evidence_context", [])
                if isinstance(item, dict)
            ],
            duration_seconds=float(row.get("duration_seconds", 0.0) or 0.0),
            usage=dict(row.get("usage", {})),
            model_snapshot={
                **dict(row.get("model_snapshot", {})),
                "reused_baseline_report_id": report_id,
                "source_eval_id": row.get("source_eval_id", ""),
            },
            estimated_cost=float(row.get("estimated_cost", 0.0) or 0.0),
            artifact_refs=[
                *[str(item) for item in row.get("artifact_refs", [])],
                f"baseline_report:{report_id}",
                str(row.get("report_path", "")),
            ],
        )
