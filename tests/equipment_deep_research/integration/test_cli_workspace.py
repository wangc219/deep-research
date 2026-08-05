from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

import pytest

from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.domain import workspace as workspace_module
from equipment_deep_research.domain.proposals import TraceProposal
from equipment_deep_research.domain.store import SqliteRunStore
from equipment_deep_research.domain import store as store_module
from equipment_deep_research.harness.recovery import RecoveryError
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.interfaces import cli
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.orchestration import runner as runner_module
from equipment_deep_research.agents.provider import FakeAgentProvider
from equipment_deep_research.tools.artifacts import SecureArtifactStore


ROOT = Path(__file__).resolve().parents[3]


def _runner(tmp_path: Path, **overrides: Any) -> DeepResearchRunner:
    kwargs = {
        "project_root": ROOT,
        "output_root": tmp_path,
        "agent_config_path": ROOT
        / "configs"
        / "equipment_deep_research"
        / "agents.yaml",
        "preset_config_path": ROOT
        / "configs"
        / "equipment_deep_research"
        / "presets.yaml",
    }
    kwargs.update(overrides)
    return DeepResearchRunner(**kwargs)


class _ConcurrencyProbeProvider(FakeAgentProvider):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run_baseline_agent(self, request):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.03)
            return super().run_baseline_agent(request)
        finally:
            with self._lock:
                self.active -= 1


class _PipelinePrefetchProbeProvider(FakeAgentProvider):
    provider_kind = "codex_cli"

    def __init__(self) -> None:
        self.prefetched: list[str] = []
        self._lock = threading.Lock()
        self._progress = None

    def set_baseline_progress_callback(self, callback) -> None:
        self._progress = callback

    def prefetch_baseline_agent(self, request):
        with self._lock:
            self.prefetched.append(request.agent.agent_id)
        if self._progress is not None:
            self._progress(
                {
                    "event_type": "baseline_discovery_completed",
                    "run_id": request.run_id,
                    "agent_id": request.agent.agent_id,
                    "round_index": request.round_index,
                    "source_count": 1,
                }
            )
        return {"agent_id": request.agent.agent_id, "source_count": 1}

    def draft_report(self, payload):
        assert payload["topic"]
        return """## 第一层：需求挖掘层——场景·战法/技术·装备能力特征

### ① 典型作战场景

本测试仅验证六个业务 Agent 在假设对手、地域、烈度、时间窗和约束条件下的并行预取。

### ② 新战法或新概念技术及制胜机理

现有范式串行处理存在不足；并行预取后仍按依赖关系完成结构化分析，因此可形成测试意义上的制胜优势。

### ③ 装备能力特征清单

能力域及射程、响应时间、自主等级、成本量级、规模量级仅作为测试字段，不形成真实结论。

## 第二层：技术攻关层——能力实现途径与核心技术

### ④ 能力实现途径

测试链路按沿用改进验证接口，不判断集成创新或原理突破。

### ⑤ 核心技术清单与攻关优先级

测试技术点、成熟度、瓶颈和P0优先级均为夹具语义。

### ⑥ 技术耦合与短板风险

接口依赖与耦合只用于验证卡脖子短板不会拖垮测试流程。

## 第三层：能力图像与效能贡献层

### ⑦ 装备能力图像

能力域、指标画像和谱系位置仅用于测试三层九项格式。

### ⑧ 效能贡献评估

仅验证补链、强链、开链字段及突防率、交换比、决策周期量级方向。

### ⑨ 发展优先级与近期抓手

P0演示验证项目只检查验收指标、通过条件和失败条件，不形成真实研究结论。
"""


def test_runner_model_fallback_selects_task_agents_and_executes_parallel_wave(
    tmp_path: Path,
) -> None:
    provider = _ConcurrencyProbeProvider()
    result = _runner(tmp_path, provider=provider).run(
        mode="fake",
        topic="传统装备能力缺口与作战运用升级",
        research_route="traditional_gap",
        run_id="dynamic-parallel-wave",
        analyst_confirmed=True,
    )
    trace = [
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    started = next(item for item in trace if item["event_type"] == "run_started")
    assert "international_situation" not in started["payload"]["agent_ids"]
    assert set(started["payload"]["agent_ids"]) == {
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    }
    assert any(
        item["event_type"] == "baseline_wave_started"
        and item["payload"]["concurrent"] is True
        for item in trace
    )
    assert provider.max_active >= 2


def test_runner_enforces_configured_baseline_wave_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_BASELINE_WAVE_CONCURRENCY", "2")
    provider = _ConcurrencyProbeProvider()
    result = _runner(tmp_path, provider=provider).run(
        mode="fake",
        topic="多 Agent 有界并发治理验证",
        research_route="traditional_gap",
        run_id="bounded-parallel-wave",
        agent_ids=[
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        analyst_confirmed=True,
    )

    trace = [
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    starts = [item for item in trace if item["event_type"] == "baseline_wave_started"]
    assert provider.max_active == 2
    assert starts
    assert all(item["payload"]["bounded"] is True for item in starts)
    assert max(item["payload"]["max_concurrency"] for item in starts) == 2
    assert all(item["payload"]["max_concurrency"] <= 2 for item in starts)


def test_real_codex_runner_prefetches_all_six_business_agents(tmp_path: Path) -> None:
    provider = _PipelinePrefetchProbeProvider()
    agent_ids = [
        "international_situation",
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
        "opponent_monitoring",
        "system_confrontation",
    ]

    result = _runner(tmp_path, provider=provider).run(
        mode="real",
        topic="六业务 Agent 流水线验证",
        research_route="traditional_gap",
        run_id="codex-prefetch-six",
        agent_ids=agent_ids,
        analyst_confirmed=True,
    )

    trace = [
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert set(provider.prefetched) == set(agent_ids)
    assert any(item["event_type"] == "baseline_pipeline_started" for item in trace)
    assert {
        item["actor"]
        for item in trace
        if item["event_type"] == "baseline_discovery_completed"
    } == set(agent_ids)


def test_workspace_creates_required_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")

    assert workspace.run_dir == tmp_path / "run-1"
    assert workspace.sessions_dir.is_dir()
    assert workspace.artifacts_dir.is_dir()
    assert workspace.checkpoints_dir.is_dir()
    assert workspace.database_path == workspace.run_dir / "run.db"
    workspace.close()


def test_workspace_create_never_binds_an_ordinary_race_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "runs"
    output_root.mkdir()
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "marker.txt").write_text("untouched", encoding="utf-8")
    real_publish = workspace_module._rename_noreplace_at

    def race_publish(parent_fd: int, source: str, destination: str) -> None:
        os.rename(attacker, destination, dst_dir_fd=parent_fd)
        real_publish(parent_fd, source, destination)

    monkeypatch.setattr(workspace_module, "_rename_noreplace_at", race_publish)

    with pytest.raises(FileExistsError):
        RunWorkspace.create(output_root, "run-1")

    assert (output_root / "run-1" / "marker.txt").read_text(
        encoding="utf-8"
    ) == "untouched"
    assert not any(path.name.endswith(".creating") for path in output_root.iterdir())


def test_missing_output_root_component_uses_noreplace_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "runs"
    attacker = tmp_path / "attacker-output"
    attacker.mkdir()
    (attacker / "marker.txt").write_text("untouched", encoding="utf-8")
    real_publish = workspace_module._rename_noreplace_at

    def race_publish(parent_fd: int, source: str, destination: str) -> None:
        if destination == "runs":
            os.rename(attacker, destination, dst_dir_fd=parent_fd)
        real_publish(parent_fd, source, destination)

    monkeypatch.setattr(workspace_module, "_rename_noreplace_at", race_publish)

    with pytest.raises(FileExistsError):
        RunWorkspace.create(output_root, "run-1")

    assert (output_root / "marker.txt").read_text(encoding="utf-8") == "untouched"
    assert not (output_root / "run-1").exists()


def test_workspace_rejects_shared_writable_output_root(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    output_root.mkdir()
    output_root.chmod(0o770)

    with pytest.raises(PermissionError, match="group/world writable"):
        RunWorkspace.create(output_root, "run-1")

    assert list(output_root.iterdir()) == []


def test_workspace_create_fails_closed_without_atomic_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "runs"

    def unavailable(*args: object, **kwargs: object) -> None:
        raise RuntimeError("atomic no-replace directory publication is unavailable")

    monkeypatch.setattr(workspace_module, "_rename_noreplace_at", unavailable)

    with pytest.raises(RuntimeError, match="atomic no-replace"):
        RunWorkspace.create(output_root, "run-1")

    assert not (output_root / "run-1").exists()
    assert not output_root.exists()


def test_bound_sqlite_rejects_aba_path_replacement_before_attacker_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "runs"
    workspace = RunWorkspace.create(output_root, "run-1")
    database_fd = workspace.dup_database_fd()
    database_dir_fd = workspace.dup_run_fd()
    attacker_root = tmp_path / "attacker-root"
    attacker_run = attacker_root / "run-1"
    attacker_run.mkdir(parents=True)
    attacker_db = attacker_run / "run.db"
    connection = sqlite3.connect(attacker_db)
    connection.execute("CREATE TABLE attacker_marker(value TEXT)")
    connection.execute("INSERT INTO attacker_marker VALUES ('untouched')")
    connection.commit()
    connection.close()
    original_bytes = attacker_db.read_bytes()
    real_connect = store_module.sqlite3.connect

    def aba_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        bound_root = tmp_path / "bound-root"
        output_root.rename(bound_root)
        attacker_root.rename(output_root)
        opened = real_connect(*args, **kwargs)
        output_root.rename(attacker_root)
        bound_root.rename(output_root)
        return opened

    monkeypatch.setattr(store_module.sqlite3, "connect", aba_connect)
    try:
        with pytest.raises(RuntimeError, match="bound inode|bound database file"):
            SqliteRunStore(
                workspace.database_path,
                run_id="run-1",
                database_fd=database_fd,
                database_dir_fd=database_dir_fd,
            )
    finally:
        os.close(database_fd)
        os.close(database_dir_fd)
        workspace.close()

    assert attacker_db.read_bytes() == original_bytes
    assert not (attacker_run / "run.db-wal").exists()
    assert not (attacker_run / "run.db-shm").exists()


def test_bound_sqlite_fails_closed_without_descriptor_auditing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "run-1")
    database_fd = workspace.dup_database_fd()
    database_dir_fd = workspace.dup_run_fd()

    def unavailable() -> Path:
        raise RuntimeError("SQLite descriptor auditing is unavailable")

    monkeypatch.setattr(store_module, "_descriptor_directory", unavailable)
    try:
        with pytest.raises(RuntimeError, match="descriptor auditing"):
            SqliteRunStore(
                workspace.database_path,
                run_id="run-1",
                database_fd=database_fd,
                database_dir_fd=database_dir_fd,
            )
    finally:
        os.close(database_fd)
        os.close(database_dir_fd)
        workspace.close()


def test_bound_sqlite_rechecks_database_name_before_subsequent_operations(
    tmp_path: Path,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "run-1")
    store = SqliteRunStore.for_workspace(workspace, run_id="run-1")
    bound_database = workspace.run_dir / "bound-run.db"
    workspace.database_path.rename(bound_database)
    attacker_database = workspace.database_path
    connection = sqlite3.connect(attacker_database)
    connection.execute("CREATE TABLE attacker_marker(value TEXT)")
    connection.execute("INSERT INTO attacker_marker VALUES ('untouched')")
    connection.commit()
    connection.close()
    attacker_bytes = attacker_database.read_bytes()

    try:
        with pytest.raises(RuntimeError, match="database name changed"):
            store.recover()
    finally:
        store.close()
        workspace.close()

    assert attacker_database.read_bytes() == attacker_bytes
    assert not Path(f"{attacker_database}-wal").exists()
    assert not Path(f"{attacker_database}-shm").exists()


def test_bound_sqlite_rejects_legacy_wal_before_secure_connect(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "run-1")
    connection = sqlite3.connect(workspace.database_path)
    assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    connection.execute("CREATE TABLE legacy(value TEXT)")
    connection.commit()
    connection.close()
    database_bytes = workspace.database_path.read_bytes()

    try:
        with pytest.raises(RuntimeError, match="offline trusted migration"):
            SqliteRunStore.for_workspace(workspace, run_id="run-1")
    finally:
        workspace.close()

    assert workspace.database_path.read_bytes() == database_bytes


def test_runner_closes_workspace_when_sqlite_constructor_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[RunWorkspace] = []
    real_create = RunWorkspace.create

    def capture_create(
        cls: type[RunWorkspace], output_root: Path, run_id: str
    ) -> RunWorkspace:
        workspace = real_create(output_root, run_id)
        captured.append(workspace)
        return workspace

    class FailingStore:
        @classmethod
        def for_workspace(cls, *args: object, **kwargs: object) -> None:
            raise RuntimeError("injected store construction failure")

    monkeypatch.setattr(
        runner_module.RunWorkspace, "create", classmethod(capture_create)
    )
    monkeypatch.setattr(runner_module, "SqliteRunStore", FailingStore)

    with pytest.raises(RuntimeError, match="injected store construction failure"):
        _runner(tmp_path).run(
            mode="fake",
            topic="cleanup",
            research_route="new_winning_mechanism",
            run_id="cleanup-run",
        )

    with pytest.raises(RuntimeError, match="workspace is closed"):
        captured[0].dup_run_fd()


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_workspace_handles_bind_original_run_and_subdirectories(
    tmp_path: Path,
    replacement: str,
) -> None:
    output_root = tmp_path / "runs"
    workspace = RunWorkspace.create(output_root, "run-1")
    original_run = output_root / "bound-run-1"
    workspace.run_dir.rename(original_run)
    attacker_root = tmp_path / "attacker-run"
    attacker_root.mkdir()
    if replacement == "symlink":
        workspace.run_dir.symlink_to(attacker_root, target_is_directory=True)
        replacement_run = attacker_root
    else:
        workspace.run_dir.mkdir()
        replacement_run = workspace.run_dir
    attack_location = replacement_run
    for name in ("agent_sessions", "artifacts", "checkpoints"):
        (replacement_run / name).mkdir()

    run_fd = workspace.dup_run_fd()
    sessions_fd = workspace.dup_sessions_fd()
    database_fd = workspace.dup_database_fd()
    try:
        assert (
            os.fstat(run_fd).st_dev,
            os.fstat(run_fd).st_ino,
        ) == workspace.run_identity
        workspace.write_run_text("report.md", "bound\n")
        workspace.write_checkpoint_text("latest.json", "{}")
        artifacts = SecureArtifactStore.for_workspace(workspace)
        artifacts.put("artifact", kind="text", meta={"content_type": "text/plain"})
        session = JsonlSessionStore("agent.jsonl", root_fd=sessions_fd)
        session.append({"event_type": "bound"})
        session.close()
        database = SqliteRunStore(
            workspace.database_path,
            run_id="run-1",
            database_fd=database_fd,
        )
        database.commit(
            (),
            (
                TraceProposal(
                    proposal_id="bound-trace",
                    event_type="bound",
                    actor="test",
                    payload={"bound": True},
                ),
            ),
        )
        database.close()
    finally:
        os.close(run_fd)
        os.close(sessions_fd)
        os.close(database_fd)
        workspace.close()

    assert (original_run / "report.md").read_text(encoding="utf-8") == "bound\n"
    assert (original_run / "checkpoints" / "latest.json").is_file()
    assert list((original_run / "artifacts").glob("*.meta.json"))
    assert (original_run / "agent_sessions" / "agent.jsonl").is_file()
    assert (original_run / "run.db").is_file()
    assert [path for path in attack_location.rglob("*") if path.is_file()] == []


def test_workspace_close_invalidates_handle_duplication(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    run_fd = workspace.dup_run_fd()

    workspace.close()

    with pytest.raises(RuntimeError, match="closed"):
        workspace.dup_run_fd()
    os.fstat(run_fd)
    os.close(run_fd)


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_workspace_subdirectory_handles_ignore_replacement_paths(
    tmp_path: Path,
    replacement: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "run-1")
    bound_directories: dict[str, Path] = {}
    attacker_directories: dict[str, Path] = {}
    for name in ("agent_sessions", "artifacts", "checkpoints"):
        current = workspace.run_dir / name
        bound = workspace.run_dir / f"bound-{name}"
        current.rename(bound)
        attacker = tmp_path / f"attacker-{name}"
        attacker.mkdir()
        if replacement == "symlink":
            current.symlink_to(attacker, target_is_directory=True)
        else:
            current.mkdir()
            attacker = current
        bound_directories[name] = bound
        attacker_directories[name] = attacker

    workspace.write_checkpoint_text("latest.json", "{}")
    SecureArtifactStore.for_workspace(workspace).put(
        "artifact",
        kind="text",
        meta={"content_type": "text/plain"},
    )
    sessions_fd = workspace.dup_sessions_fd()
    try:
        session = JsonlSessionStore("agent.jsonl", root_fd=sessions_fd)
    finally:
        os.close(sessions_fd)
    session.append({"event_type": "bound"})
    session.close()
    workspace.close()

    assert (bound_directories["checkpoints"] / "latest.json").is_file()
    assert list(bound_directories["artifacts"].glob("*.meta.json"))
    assert (bound_directories["agent_sessions"] / "agent.jsonl").is_file()
    for attacker in attacker_directories.values():
        assert [path for path in attacker.rglob("*") if path.is_file()] == []


def test_runner_closes_workspace_handles_when_hook_raises(tmp_path: Path) -> None:
    captured: list[RunWorkspace] = []

    def fail_after_create(event: str, workspace: RunWorkspace) -> None:
        if event == "after_workspace_created":
            captured.append(workspace)
            raise RuntimeError("stop after create")

    with pytest.raises(RuntimeError, match="stop after create"):
        _runner(tmp_path, run_hook=fail_after_create).run(
            mode="fake",
            topic="handle cleanup",
            research_route="auto",
            run_id="cleanup-run",
        )

    assert len(captured) == 1
    with pytest.raises(RuntimeError, match="closed"):
        captured[0].dup_run_fd()


@pytest.mark.parametrize(
    ("root_name", "leaf"),
    [
        ("run", "report.md"),
        ("run", "domain.jsonl"),
        ("checkpoints", "latest.json"),
    ],
)
def test_workspace_atomic_writer_rejects_leaf_symlink_without_touching_external(
    tmp_path: Path,
    root_name: str,
    leaf: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    external = tmp_path / f"external-{leaf}"
    external.write_text("external\n", encoding="utf-8")
    root = workspace.run_dir if root_name == "run" else workspace.checkpoints_dir
    (root / leaf).symlink_to(external)

    with pytest.raises(ValueError, match="symlink"):
        if root_name == "run":
            workspace.write_run_text(leaf, "replacement\n")
        else:
            workspace.write_checkpoint_text(leaf, "replacement\n")

    assert external.read_text(encoding="utf-8") == "external\n"


@pytest.mark.parametrize(
    ("root_name", "leaf"),
    [
        ("run", "report.md"),
        ("run", "domain.jsonl"),
        ("checkpoints", "latest.json"),
    ],
)
def test_workspace_atomic_writer_replaces_checked_leaf_without_following_race_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_name: str,
    leaf: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    external = tmp_path / f"external-race-{leaf}"
    external.write_text("external\n", encoding="utf-8")
    root = workspace.run_dir if root_name == "run" else workspace.checkpoints_dir
    target = root / leaf
    target.write_text("old\n", encoding="utf-8")
    real_rename = os.rename

    def racing_rename(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        assert dst == leaf
        target.unlink()
        target.symlink_to(external)
        real_rename(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(workspace_module.os, "rename", racing_rename)
    if root_name == "run":
        workspace.write_run_text(leaf, "replacement\n")
    else:
        workspace.write_checkpoint_text(leaf, "replacement\n")

    assert external.read_text(encoding="utf-8") == "external\n"
    assert target.read_text(encoding="utf-8") == "replacement\n"


def test_workspace_writer_fails_closed_without_secure_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    monkeypatch.setattr(workspace_module.os, "supports_dir_fd", set())

    with pytest.raises(RuntimeError, match="secure workspace path operations"):
        workspace.write_run_text("report.md", "blocked\n")

    assert not (workspace.run_dir / "report.md").exists()


def test_workspace_create_fails_closed_before_creating_root_without_dirfd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "blocked-runs"
    monkeypatch.setattr(workspace_module.os, "supports_dir_fd", set())

    with pytest.raises(RuntimeError, match="secure workspace path operations"):
        RunWorkspace.create(output_root, "run-1")

    assert not output_root.exists()


def test_workspace_safe_stat_rejects_leaf_replaced_after_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    target = workspace.run_dir / "report.md"
    target.write_text("report\n", encoding="utf-8")
    external = tmp_path / "external-stat-report.md"
    external.write_text("external\n", encoding="utf-8")
    real_open_at = workspace_module._open_at

    def racing_open_at(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int,
    ) -> int:
        if path == "report.md":
            target.unlink()
            target.symlink_to(external)
        return real_open_at(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(workspace_module, "_open_at", racing_open_at)

    with pytest.raises(ValueError, match="symlink"):
        workspace.run_file_is_regular("report.md")

    assert external.read_text(encoding="utf-8") == "external\n"


@pytest.mark.parametrize(
    "run_id",
    [
        "/tmp/equipment-dr-absolute-escape",
        ".",
        "..",
        "../equipment-dr-parent-escape",
        "nested/run",
        r"nested\run",
    ],
)
def test_workspace_rejects_run_id_path_escape(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="run_id"):
        RunWorkspace.create(tmp_path, run_id)


def test_workspace_allows_double_dot_inside_run_id(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path, "release..1")

    assert workspace.run_dir == tmp_path / "release..1"
    assert workspace.run_dir.is_dir()


def test_workspace_rejects_preexisting_empty_run_directory(tmp_path: Path) -> None:
    (tmp_path / "existing-empty").mkdir()

    with pytest.raises(FileExistsError):
        RunWorkspace.create(tmp_path, "existing-empty")


def test_workspace_rejects_symlink_escape_without_modifying_target(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "runs"
    output_root.mkdir()
    external_target = tmp_path / "external-target"
    external_target.mkdir()
    marker = external_target / "marker.txt"
    marker.write_text("unchanged\n", encoding="utf-8")
    (output_root / "escape").symlink_to(external_target, target_is_directory=True)

    with pytest.raises(FileExistsError):
        RunWorkspace.create(output_root, "escape")

    assert marker.read_text(encoding="utf-8") == "unchanged\n"
    assert {path.name for path in external_target.iterdir()} == {"marker.txt"}


def test_runner_rejects_reused_run_id_before_writing(tmp_path: Path) -> None:
    run_id = "reused-run"
    first = _runner(tmp_path).run(
        mode="fake",
        topic="first run",
        research_route="auto",
        run_id=run_id,
    )
    run_dir = Path(first["run_dir"])
    original_files = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    original_directories = {
        path.relative_to(run_dir) for path in run_dir.rglob("*") if path.is_dir()
    }

    with pytest.raises(FileExistsError):
        _runner(tmp_path).run(
            mode="fake",
            topic="second run",
            research_route="auto",
            run_id=run_id,
            agent_ids=["weapon_equipment"],
        )

    assert {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    } == original_files
    assert {
        path.relative_to(run_dir) for path in run_dir.rglob("*") if path.is_dir()
    } == original_directories
    assert {
        "report.md",
        "capability_images.json",
        "round_summary.json",
        "domain.jsonl",
        "trace.jsonl",
        "agent_sessions",
        "artifacts",
    } <= {path.name for path in run_dir.iterdir()}


def test_runner_uses_default_provider_and_evidence_configs(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    assert (
        runner.provider_config_path
        == ROOT / "configs" / "equipment_deep_research" / "providers.yaml"
    )
    assert (
        runner.evidence_config_path
        == ROOT / "configs" / "equipment_deep_research" / "evidence.yaml"
    )


def test_runner_allows_omitted_new_configs_for_custom_project_root(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "minimal-project"
    project_root.mkdir()

    runner = DeepResearchRunner(
        project_root=project_root,
        output_root=tmp_path / "runs",
        agent_config_path=ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        preset_config_path=ROOT
        / "configs"
        / "equipment_deep_research"
        / "presets.yaml",
    )

    assert runner.provider_config_path == (
        project_root / "configs" / "equipment_deep_research" / "providers.yaml"
    )
    assert runner.evidence_config_path == (
        project_root / "configs" / "equipment_deep_research" / "evidence.yaml"
    )
    absent_fingerprint = runner._config_fingerprint(
        mode="fake",
        max_rounds=5,
        analyst_confirmed=False,
    )
    assert absent_fingerprint == runner._config_fingerprint(
        mode="fake",
        max_rounds=5,
        analyst_confirmed=False,
    )
    assert absent_fingerprint != runner._config_fingerprint(
        mode="fake",
        max_rounds=5,
        analyst_confirmed=False,
        stage_policy_id="no_winning_mechanism",
    )
    result = runner.run(
        mode="fake",
        topic="minimal custom project",
        research_route="auto",
        run_id="minimal-custom-root",
        agent_ids=["weapon_equipment"],
    )
    assert result["status"] == "completed"


def test_optional_config_appearance_changes_resume_fingerprint(tmp_path: Path) -> None:
    project_root = tmp_path / "minimal-project"
    project_root.mkdir()
    runner = DeepResearchRunner(
        project_root=project_root,
        output_root=tmp_path / "runs",
        agent_config_path=ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        preset_config_path=ROOT
        / "configs"
        / "equipment_deep_research"
        / "presets.yaml",
    )
    runner.run(
        mode="fake",
        topic="optional config fingerprint",
        research_route="auto",
        run_id="optional-config",
        agent_ids=["weapon_equipment"],
    )
    config_dir = project_root / "configs" / "equipment_deep_research"
    config_dir.mkdir(parents=True)
    (config_dir / "providers.yaml").write_text("providers: {}\n", encoding="utf-8")

    with pytest.raises(RecoveryError, match="configuration"):
        runner.run(
            mode="fake",
            topic="optional config fingerprint",
            research_route="auto",
            run_id="optional-config",
            agent_ids=["weapon_equipment"],
            resume=True,
        )


@pytest.mark.parametrize(
    "config_name", ["provider_config_path", "evidence_config_path"]
)
def test_runner_rejects_missing_new_config_paths(
    tmp_path: Path, config_name: str
) -> None:
    missing_path = tmp_path / f"missing-{config_name}.yaml"

    with pytest.raises(FileNotFoundError, match=str(missing_path)):
        _runner(tmp_path, **{config_name: missing_path})


def test_runner_resume_requires_an_existing_run(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run directory does not exist"):
        _runner(tmp_path).run(
            mode="fake",
            topic="resume test",
            research_route="auto",
            run_id="resume-test",
            resume=True,
        )

    assert not (tmp_path / "resume-test").exists()


def test_analyst_confirmation_is_recorded_in_trace_and_summary(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="analyst confirmation test",
        research_route="auto",
        run_id="analyst-confirmed",
        analyst_confirmed=True,
    )

    run_dir = Path(result["run_dir"])
    trace_rows = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    run_started = next(
        row["payload"]
        for row in trace_rows
        if row["payload"]["event_type"] == "run_started"
    )
    summary = json.loads((run_dir / "round_summary.json").read_text(encoding="utf-8"))
    assert run_started["payload"]["analyst_confirmed"] is True
    assert summary["analyst_confirmed"] is True


def test_runner_keeps_seven_artifact_names_and_adds_checkpoints(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="workspace artifact test",
        research_route="auto",
        run_id="artifact-contract",
    )

    run_dir = Path(result["run_dir"])
    expected = {
        "report.md",
        "capability_images.json",
        "round_summary.json",
        "domain.jsonl",
        "trace.jsonl",
        "agent_sessions",
        "artifacts",
        "checkpoints",
    }
    assert expected <= {path.name for path in run_dir.iterdir()}


def test_cli_passes_new_configuration_and_run_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_config = tmp_path / "providers.yaml"
    evidence_config = tmp_path / "evidence.yaml"
    provider_config.write_text("providers: {}\n", encoding="utf-8")
    evidence_config.write_text("acceptance: {}\n", encoding="utf-8")
    calls: dict[str, dict[str, Any]] = {}

    class RecordingRunner:
        def __init__(self, **kwargs: Any) -> None:
            calls["init"] = kwargs

        def run(self, **kwargs: Any) -> dict[str, Any]:
            calls["run"] = kwargs
            return {
                "run_dir": str(tmp_path / "cli-run"),
                "route": "traditional_gap",
                "audit_status": "passed",
                "report_path": str(tmp_path / "cli-run" / "report.md"),
                "capability_images_path": str(
                    tmp_path / "cli-run" / "capability_images.json"
                ),
                "summary_path": str(tmp_path / "cli-run" / "round_summary.json"),
            }

    monkeypatch.setattr(cli, "DeepResearchRunner", RecordingRunner)

    exit_code = cli.main(
        [
            "--mode",
            "fake",
            "--topic",
            "CLI test",
            "--supplemental-information",
            "Operational constraints and concrete equipment deliverables.",
            "--provider-config",
            str(provider_config),
            "--evidence-config",
            str(evidence_config),
            "--resume",
            "--allow-resume-config-mismatch",
            "--analyst-confirmed",
        ]
    )

    assert exit_code == 0
    assert calls["init"]["provider_config_path"] == provider_config
    assert calls["init"]["evidence_config_path"] == evidence_config
    assert calls["run"]["resume"] is True
    assert calls["run"]["supplemental_information"] == (
        "Operational constraints and concrete equipment deliverables."
    )
    assert calls["run"]["allow_resume_config_mismatch"] is True
    assert calls["run"]["analyst_confirmed"] is True


def test_cli_exposes_provider_and_evidence_controls_without_domain_gate() -> None:
    parser_text = (
        ROOT / "src" / "equipment_deep_research" / "interfaces" / "cli.py"
    ).read_text(encoding="utf-8")

    assert "--source-whitelist" not in parser_text
    assert "--provider-config" in parser_text
    assert "--evidence-config" in parser_text
    assert "--supplemental-information" in parser_text
    assert "--resume" in parser_text
    assert "--allow-resume-config-mismatch" in parser_text
    assert "--analyst-confirmed" in parser_text
