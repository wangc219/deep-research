from pathlib import Path
import threading
import time

from evals.cli import run_systems
from evals.models import EvalQuery, EvalRunResult, read_jsonl, write_jsonl


def _queries(path: Path, count: int) -> Path:
    write_jsonl(
        path,
        [
            {
                "query_id": f"Q-{index:04d}",
                "query": f"问题 {index}",
                "region": "台海",
                "domain": "低空",
                "difficulty": "medium",
                "split": "pilot",
            }
            for index in range(1, count + 1)
        ],
    )
    return path


class _StubAdapter:
    def __init__(self, system_id: str, tracker: dict, lock: threading.Lock) -> None:
        self.system_id = system_id
        self._tracker = tracker
        self._lock = lock

    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        with self._lock:
            self._tracker["active"] += 1
            self._tracker["peak"] = max(self._tracker["peak"], self._tracker["active"])
        time.sleep(0.03)
        try:
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=f"{self.system_id}:{query.query_id}",
            )
        finally:
            with self._lock:
                self._tracker["active"] -= 1


def _install_stub(monkeypatch, tracker: dict, lock: threading.Lock) -> None:
    monkeypatch.setattr(
        "evals.cli._build_adapter",
        lambda project_root, eval_root, system_id, **kwargs: _StubAdapter(system_id, tracker, lock),
    )


def test_run_systems_parallel_overlaps_and_reports_workers(tmp_path: Path, monkeypatch) -> None:
    queries = _queries(tmp_path / "queries.jsonl", 2)
    tracker = {"active": 0, "peak": 0}
    _install_stub(monkeypatch, tracker, threading.Lock())
    result = run_systems(
        project_root=tmp_path,
        queries_path=queries,
        eval_id="parallel-run",
        systems=["full_method", "generic_agent", "bare_llm"],
        split="pilot",
        output_root=tmp_path / "out",
        limit=None,
        fake=True,
        resume=False,
        config={},
        max_workers=6,
    )
    assert result["result_count"] == 6
    assert result["completed"] == 6
    assert result["parallel_workers"] == 6
    assert tracker["peak"] >= 2  # tasks actually ran concurrently


def test_run_systems_injects_existing_full_method_without_building_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    queries = _queries(tmp_path / "queries.jsonl", 1)
    built: list[str] = []

    def build(project_root, eval_root, system_id, **kwargs):
        built.append(system_id)
        return _StubAdapter(system_id, {"active": 0, "peak": 0}, threading.Lock())

    monkeypatch.setattr("evals.cli._build_adapter", build)
    result = run_systems(
        project_root=tmp_path,
        queries_path=queries,
        eval_id="injected",
        systems=["generic_agent"],
        split="pilot",
        output_root=tmp_path / "out",
        limit=1,
        fake=True,
        resume=False,
        config={},
        injected_results=[
            EvalRunResult(
                eval_id="injected",
                query_id="Q-0001",
                system_id="full_method",
                status="completed",
                answer="existing project report",
            )
        ],
    )

    assert built == ["generic_agent"]
    assert result["system_count"] == 2
    rows = read_jsonl(tmp_path / "out" / "injected" / "results.jsonl")
    assert {row["system_id"] for row in rows} == {"full_method", "generic_agent"}


def test_run_systems_reuses_injected_baseline_without_building_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    queries = _queries(tmp_path / "queries.jsonl", 1)

    def unexpected_build(*args, **kwargs):
        raise AssertionError("cached baseline should not build an adapter")

    monkeypatch.setattr("evals.cli._build_adapter", unexpected_build)
    result = run_systems(
        project_root=tmp_path,
        queries_path=queries,
        eval_id="cached-baseline",
        systems=["generic_agent"],
        split="pilot",
        output_root=tmp_path / "out",
        limit=1,
        fake=False,
        resume=False,
        config={},
        injected_results=[
            EvalRunResult(
                eval_id="cached-baseline",
                query_id="Q-0001",
                system_id="generic_agent",
                status="completed",
                answer="saved generic Codex report",
                artifact_refs=["baseline_report:BR-example"],
            )
        ],
    )

    assert result["scheduled_tasks"] == 0
    assert result["completed"] == 1
    rows = read_jsonl(tmp_path / "out" / "cached-baseline" / "results.jsonl")
    assert rows[0]["answer"] == "saved generic Codex report"


def test_run_systems_parallel_output_matches_sequential(tmp_path: Path, monkeypatch) -> None:
    queries = _queries(tmp_path / "queries.jsonl", 3)
    systems = ["full_method", "generic_agent", "bare_llm"]

    _install_stub(monkeypatch, {"active": 0, "peak": 0}, threading.Lock())
    sequential = run_systems(
        project_root=tmp_path, queries_path=queries, eval_id="seq",
        systems=systems, split="pilot", output_root=tmp_path / "out",
        limit=None, fake=True, resume=False, config={}, max_workers=1,
    )
    assert sequential["parallel_workers"] == 1
    sequential_rows = read_jsonl(tmp_path / "out" / "seq" / "results.jsonl")

    _install_stub(monkeypatch, {"active": 0, "peak": 0}, threading.Lock())
    run_systems(
        project_root=tmp_path, queries_path=queries, eval_id="par",
        systems=systems, split="pilot", output_root=tmp_path / "out",
        limit=None, fake=True, resume=False, config={}, max_workers=4,
    )
    parallel_rows = read_jsonl(tmp_path / "out" / "par" / "results.jsonl")

    def strip(rows: list[dict]) -> list[dict]:
        return [{**row, "eval_id": ""} for row in rows]

    assert strip(parallel_rows) == strip(sequential_rows)


def test_run_systems_parallel_resume_skips_completed(tmp_path: Path, monkeypatch) -> None:
    queries = _queries(tmp_path / "queries.jsonl", 2)
    _install_stub(monkeypatch, {"active": 0, "peak": 0}, threading.Lock())
    first = run_systems(
        project_root=tmp_path, queries_path=queries, eval_id="resume",
        systems=["full_method", "generic_agent"], split="pilot",
        output_root=tmp_path / "out", limit=None, fake=True, resume=False,
        config={}, max_workers=4,
    )
    assert first["completed"] == 4

    ran: list[str] = []
    lock = threading.Lock()

    class _RecordingAdapter(_StubAdapter):
        def run(self, query, *, eval_id, output_dir):
            with lock:
                ran.append(f"{self.system_id}:{query.query_id}")
            return super().run(query, eval_id=eval_id, output_dir=output_dir)

    monkeypatch.setattr(
        "evals.cli._build_adapter",
        lambda project_root, eval_root, system_id, **kwargs: _RecordingAdapter(
            system_id, {"active": 0, "peak": 0}, lock
        ),
    )
    run_systems(
        project_root=tmp_path, queries_path=queries, eval_id="resume",
        systems=["full_method", "generic_agent"], split="pilot",
        output_root=tmp_path / "out", limit=None, fake=True, resume=True,
        config={}, max_workers=4,
    )
    assert ran == []  # everything already completed, nothing re-run


def test_run_systems_honors_cancellation_before_scheduling_work(tmp_path: Path, monkeypatch) -> None:
    queries = _queries(tmp_path / "queries.jsonl", 3)
    tracker = {"active": 0, "peak": 0}
    _install_stub(monkeypatch, tracker, threading.Lock())
    cancelled = threading.Event()
    cancelled.set()
    progress: list[tuple[int, int]] = []

    result = run_systems(
        project_root=tmp_path,
        queries_path=queries,
        eval_id="cancelled-before-start",
        systems=["generic_agent", "bare_llm"],
        split="pilot",
        output_root=tmp_path / "out",
        limit=None,
        fake=True,
        resume=False,
        config={},
        max_workers=4,
        cancel_requested=cancelled.is_set,
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert result["cancelled"] is True
    assert result["completed"] == 0
    assert result["scheduled_tasks"] == 6
    assert tracker["peak"] == 0
    assert progress == []
