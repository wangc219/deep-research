from __future__ import annotations

from pathlib import Path
import asyncio

import pytest

import equipment_deep_research.deep_runtime.workspace as workspace_module
from equipment_deep_research.deep_runtime.workspace import DeepWorkspace, WorkspaceResourceConflict
from equipment_deep_research.deep_runtime.loop import _run_deep_research_turn


def _identity() -> dict[str, object]:
    return {
        "canonical_candidate": True,
        "hypothesis_id": "hypothesis-1",
        "card_binding_id": "card-1",
        "primary_equipment_identity": "equipment-alpha",
    }


def test_workspace_layout_manifest_and_external_resources(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(
        tmp_path,
        workspace_id="equipment:alpha",
        identity=_identity(),
    )

    assert workspace.workspace_id == "equipment:alpha"
    assert workspace.identity_fingerprint
    for directory in (
        workspace.config_dir,
        workspace.skills_dir,
        workspace.plugins_dir,
        workspace.sessions_dir,
        workspace.memory_dir,
        workspace.checkpoints_dir,
        workspace.artifacts_dir,
    ):
        assert directory.is_dir()

    workspace.write_resource("skills", "effect_chain/SKILL.md", "procedural steps")
    workspace.write_resource("config", "runtime.json", '{"max_turns": 4}')
    workspace.write_artifact("research/trace.json", '{"ok": true}')
    assert workspace.list_resources("skills") == ["effect_chain/SKILL.md"]
    assert workspace.read_resource("config", "runtime.json") == b'{"max_turns": 4}'
    assert workspace.read_artifact("research/trace.json") == b'{"ok": true}'

    reopened = DeepWorkspace.open(
        tmp_path,
        workspace_id="equipment:alpha",
        identity=_identity(),
    )
    assert reopened.manifest.to_dict() == workspace.manifest.to_dict()
    with pytest.raises(ValueError, match="identity mismatch"):
        DeepWorkspace.open(
            tmp_path,
            workspace_id="equipment:alpha",
            identity={**_identity(), "hypothesis_id": "other"},
        )


def test_workspace_resource_history_and_optimistic_conflict(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, workspace_id="equipment:history", identity=_identity())
    workspace.write_resource("skill", "frontier/SKILL.md", "version one")
    first = workspace.read_resource("skill", "frontier/SKILL.md")
    first_hash = __import__("hashlib").sha256(first).hexdigest()
    workspace.write_resource(
        "skill", "frontier/SKILL.md", "version two", expected_sha256=first_hash
    )
    second_hash = __import__("hashlib").sha256(b"version two").hexdigest()
    with pytest.raises(WorkspaceResourceConflict):
        workspace.write_resource(
            "skill", "frontier/SKILL.md", "stale writer", expected_sha256=first_hash
        )
    versions = workspace.list_resource_versions("skill", "frontier/SKILL.md")
    assert len(versions) == 2
    assert versions[0]["sha256"] != versions[1]["sha256"]
    first_version = next(item for item in versions if item["sha256"] == first_hash)
    restored = workspace.read_resource_version(
        "skill", "frontier/SKILL.md", first_version["version_id"]
    )
    assert restored == b"version one"
    workspace.restore_resource_version(
        "skill",
        "frontier/SKILL.md",
        first_version["version_id"],
        expected_sha256=second_hash,
    )
    assert workspace.read_resource("skill", "frontier/SKILL.md") == b"version one"


def test_workspace_resource_three_way_merge_is_preview_only(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, workspace_id="equipment:merge", identity=_identity())
    workspace.write_resource("skill", "frontier/SKILL.md", "title\nbase\nend\n")
    base_version = workspace.list_resource_versions("skill", "frontier/SKILL.md")[0]["version_id"]
    workspace.write_resource(
        "skill", "frontier/SKILL.md", "title\nbase\nours\n"
    )
    merged = workspace.merge_resource_version(
        "skill",
        "frontier/SKILL.md",
        base_version,
        "title\ntheirs\nend\n",
    )
    assert merged["conflicted"] is False
    assert "ours" in merged["content"]
    assert "theirs" in merged["content"]
    assert workspace.read_resource("skill", "frontier/SKILL.md") == b"title\nbase\nours\n"

    conflict = workspace.merge_resource_version(
        "skill",
        "frontier/SKILL.md",
        base_version,
        "title\nbase\ntheirs\n",
    )
    assert conflict["conflicted"] is True
    assert "<<<<<<< ours" in conflict["content"]
    assert conflict["conflicts"]


def test_workspace_plugin_package_merge_keeps_files_atomic_ready(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, workspace_id="equipment:package-merge", identity=_identity())
    workspace.write_resource("plugin", "method/plugin.json", '{"name":"method","description":"base"}\n')
    workspace.write_resource("plugin", "method/mcp.json", '{"mcpServers":{}}\n')
    workspace.write_resource("plugin", "method/skills/frontier/SKILL.md", "base skill\n")
    base_versions = {
        name: workspace.list_resource_versions("plugin", name)[0]["version_id"]
        for name in workspace.list_resources("plugin")
    }
    workspace.write_resource(
        "plugin", "method/plugin.json", '{"name":"method","description":"server edit"}\n',
        expected_sha256=__import__("hashlib").sha256(
            b'{"name":"method","description":"base"}\n'
        ).hexdigest(),
    )
    preview = workspace.merge_plugin_package(
        "method",
        base_versions=base_versions,
        incoming_files={
            "method/plugin.json": '{"name":"method","description":"base"}\n',
            "method/skills/frontier/SKILL.md": "incoming skill\n",
            "method/skills/new/SKILL.md": "new skill\n",
        },
    )
    assert preview["atomic_ready"] is True
    actions = {item["name"]: item["action"] for item in preview["files"]}
    assert actions["method/mcp.json"] == "delete"
    assert actions["method/skills/new/SKILL.md"] == "upsert"
    applied = workspace.apply_plugin_package_merge(
        "method",
        base_versions=base_versions,
        incoming_files={
            "method/plugin.json": '{"name":"method","description":"base"}\n',
            "method/skills/frontier/SKILL.md": "incoming skill\n",
            "method/skills/new/SKILL.md": "new skill\n",
        },
    )
    assert applied["applied"] is True
    assert workspace.read_resource("plugin", "method/plugin.json") == b'{"name":"method","description":"server edit"}\n'
    assert workspace.read_resource("plugin", "method/skills/new/SKILL.md") == b"new skill\n"
    with pytest.raises(FileNotFoundError):
        workspace.read_resource("plugin", "method/mcp.json")

    conflict = workspace.merge_plugin_package(
        "method",
        base_versions=base_versions,
        incoming_files={
            "method/plugin.json": '{"name":"method","description":"incoming edit"}\n',
        },
    )
    assert conflict["atomic_ready"] is False
    assert conflict["conflicted"] is True


def test_workspace_plugin_package_apply_rolls_back_history_on_late_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = DeepWorkspace.open(
        tmp_path, workspace_id="equipment:package-rollback", identity=_identity()
    )
    workspace.write_resource("plugin", "method/plugin.json", '{"version":1}\n')
    workspace.write_resource("plugin", "method/mcp.json", '{"mcpServers":{}}\n')
    base_versions = {
        name: workspace.list_resource_versions("plugin", name)[0]["version_id"]
        for name in workspace.list_resources("plugin")
    }
    before_files = {
        name: workspace.read_resource("plugin", name)
        for name in workspace.list_resources("plugin")
    }
    before_history = {
        name: [item["version_id"] for item in workspace.list_resource_versions("plugin", name)]
        for name in before_files
    }

    original_record = workspace._record_resource_version
    calls = 0

    def fail_on_second_record(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated package journal failure")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(workspace, "_record_resource_version", fail_on_second_record)
    with pytest.raises(OSError, match="simulated package journal failure"):
        workspace.apply_plugin_package_merge(
            "method",
            base_versions=base_versions,
            incoming_files={
                "method/plugin.json": '{"version":2}\n',
                "method/mcp.json": '{"mcpServers":{"probe":{}}}\n',
            },
        )

    assert {
        name: workspace.read_resource("plugin", name) for name in before_files
    } == before_files
    assert {
        name: [item["version_id"] for item in workspace.list_resource_versions("plugin", name)]
        for name in before_files
    } == before_history


def test_session_transcript_is_complete_while_context_is_bounded(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    workspace.sessions.create("session-1", metadata={"kind": "deep-thinking"})
    for index in range(4):
        workspace.sessions.append_message(
            "session-1",
            role="user",
            content=f"question-{index}",
        )
        workspace.sessions.append_message(
            "session-1",
            role="assistant",
            content=f"answer-{index}",
        )
    workspace.sessions.save_working_memory(
        "session-1",
        {
            "branch_id": "main",
            "current_objective": "close the effect chain",
            "candidate_directions": [{"name": "latent node", "stable": True}],
            "research_gaps": ["countermeasure boundary"],
        },
    )

    session = workspace.sessions.load("session-1")
    assert session is not None
    assert len(session["messages"]) == 8
    context = workspace.sessions.build_context(
        "session-1",
        current_question="continue",
        turn_limit=2,
    )
    assert len(context["living_transcript"]) == 4
    assert context["transcript_count"] == 8
    assert context["working_memory"]["candidate_directions"][0]["name"] == "latent node"
    assert context["context_usage"]["archived_turns"] == 2


def test_branch_context_does_not_mix_sibling_explorations(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    workspace.sessions.create("session-branches")
    workspace.sessions.append_message(
        "session-branches", role="user", content="main question", branch_id="main"
    )
    workspace.sessions.append_message(
        "session-branches", role="assistant", content="main answer", branch_id="main"
    )
    workspace.sessions.append_message(
        "session-branches", role="user", content="branch A question", branch_id="branch-a"
    )
    workspace.sessions.append_message(
        "session-branches", role="assistant", content="branch A answer", branch_id="branch-a"
    )
    workspace.sessions.append_message(
        "session-branches", role="user", content="branch B question", branch_id="branch-b"
    )
    workspace.sessions.append_message(
        "session-branches", role="assistant", content="branch B answer", branch_id="branch-b"
    )

    branch_a = workspace.sessions.build_context(
        "session-branches", branch_id="branch-a", turn_limit=2
    )
    branch_a_text = "\n".join(item["content"] for item in branch_a["living_transcript"])
    assert "branch A" in branch_a_text
    assert "branch B" not in branch_a_text
    assert 0 < branch_a["transcript_count"] < 6

    main = workspace.sessions.build_context(
        "session-branches", branch_id="main", turn_limit=2
    )
    main_text = "\n".join(item["content"] for item in main["living_transcript"])
    assert "main answer" in main_text
    assert "branch A" not in main_text
    assert "branch B" not in main_text
    assert main["transcript_count"] == 2


def test_dream_consolidation_is_incremental_and_preserves_manual_memory(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    workspace.memory.write_memory("# Analyst notes\n\nKeep uncertainty explicit.\n")
    workspace.memory.append_history(
        "candidate: latent node",
        session_id="session-1",
        role="assistant",
    )
    first = workspace.memory.consolidate_dream(
        facts=[{"kind": "frontier", "text": "latent node"}],
        summary="retain the direction",
    )
    assert first.changed is True
    assert first.processed_entries == 1
    assert first.through_cursor == 1
    assert "Analyst notes" in workspace.memory.read_memory()
    assert "latent node" in workspace.memory.read_memory()
    assert workspace.memory.last_dream_cursor() == 1

    # A second run with no new journal input is a no-op and does not duplicate
    # the fact.  New input advances the cursor only after consolidation.
    second = workspace.memory.consolidate_dream(
        facts=[{"kind": "frontier", "text": "latent node"}],
    )
    assert second.processed_entries == 0
    assert second.added_facts == 0
    workspace.memory.append_history("open frontier: low-cost countermeasure", role="user")
    third = workspace.memory.consolidate_dream(
        working_memory={"research_gaps": ["low-cost countermeasure"]},
    )
    assert third.processed_entries == 1
    assert third.through_cursor == 2
    assert workspace.memory.last_dream_cursor() == 2
    assert workspace.memory.read_memory().count("low-cost countermeasure") >= 1


def test_dream_cursor_advances_only_after_audit_log_is_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    workspace.memory.append_history(
        "candidate: resilient decoy node",
        session_id="session-1",
        role="assistant",
    )
    original_append_line = workspace_module._append_line

    def fail_dream_log(path: Path, record: dict[str, object]) -> None:
        if path == workspace.memory.dream_log_file:
            raise OSError("injected Dream audit failure")
        original_append_line(path, record)

    monkeypatch.setattr(workspace_module, "_append_line", fail_dream_log)
    with pytest.raises(OSError, match="audit failure"):
        workspace.memory.consolidate_dream(
            facts=[{"kind": "frontier", "text": "resilient decoy node"}],
            summary="retain for adversarial review",
        )
    assert workspace.memory.last_dream_cursor() == 0

    # Retrying the same batch is safe: facts are content-addressed, the audit
    # row is now durable, and only then does the cursor commit the batch.
    monkeypatch.setattr(workspace_module, "_append_line", original_append_line)
    retried = workspace.memory.consolidate_dream(
        facts=[{"kind": "frontier", "text": "resilient decoy node"}],
        summary="retain for adversarial review",
    )
    assert retried.processed_entries == 1
    assert retried.through_cursor == 1
    assert workspace.memory.last_dream_cursor() == 1


def test_empty_dream_result_preserves_existing_facts_and_deduplicates_checkpoint(
    tmp_path: Path,
) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    workspace.memory.append_history("first research turn")
    workspace.memory.consolidate_dream(facts=[{"kind": "fact", "text": "durable finding"}])
    workspace.memory.append_history("new unresolved frontier")

    fallback = workspace.memory.consolidate_dream()
    assert fallback.processed_entries == 1
    assert fallback.added_facts == 1
    assert fallback.total_facts == 2
    assert "durable finding" in workspace.memory.read_memory()
    assert "new unresolved frontier" in workspace.memory.read_memory()

    workspace.memory.append_history("new unresolved frontier")
    repeated = workspace.memory.consolidate_dream()
    assert repeated.added_facts == 0
    assert repeated.total_facts == 2
    assert workspace.memory.last_dream_cursor() == 3


def test_history_cursor_recovers_when_sidecar_write_fails_after_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    assert workspace.memory.append_history("first") == 1
    original_atomic_write = workspace_module._atomic_write
    failed = False

    def fail_cursor(path: Path, data: str | bytes, **kwargs: object) -> None:
        nonlocal failed
        if path == workspace.memory.cursor_file and not failed:
            failed = True
            raise OSError("injected cursor sidecar failure")
        original_atomic_write(path, data, **kwargs)

    monkeypatch.setattr(workspace_module, "_atomic_write", fail_cursor)
    with pytest.raises(OSError, match="cursor sidecar failure"):
        workspace.memory.append_history("second")
    monkeypatch.setattr(workspace_module, "_atomic_write", original_atomic_write)

    # The JSONL append was durable, so the next allocation must continue at 3
    # even though the sidecar still contains cursor 1.
    assert workspace.memory.append_history("third") == 3
    rows = list(workspace_module._read_jsonl(workspace.memory.history_file))
    assert [row["cursor"] for row in rows] == [1, 2, 3]


def test_dream_memory_cap_preserves_managed_markers(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    workspace.memory.append_history("large Dream batch")
    facts = [
        {"kind": "frontier", "text": f"frontier-{index}-" + ("x" * 1_180)}
        for index in range(240)
    ]
    workspace.memory.consolidate_dream(facts=facts, summary="latest frontier")
    rendered = workspace.memory.read_memory()
    assert len(rendered) <= workspace_module.MAX_MEMORY_CHARS
    assert workspace_module._MANAGED_MEMORY_START in rendered
    assert workspace_module._MANAGED_MEMORY_END in rendered
    assert "frontier-239" in rendered


def test_empty_dream_result_keeps_checkpoint_when_prior_facts_exist(
    tmp_path: Path,
) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    workspace.memory.append_history("initial durable finding")
    workspace.memory.consolidate_dream(facts=[{"kind": "fact", "text": "known"}])
    workspace.memory.append_history("new finding with no structured response")

    result = workspace.memory.consolidate_dream()

    assert result.processed_entries == 1
    assert workspace.memory.last_dream_cursor() == 2
    facts_rows = list(workspace_module._read_jsonl(workspace.memory.facts_file))
    assert any(row.get("kind") == "checkpoint" for row in facts_rows)


def test_workspace_rejects_path_escape_and_symlink_resources(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(tmp_path, identity=_identity())
    with pytest.raises(ValueError, match="stay within"):
        workspace.write_artifact("../outside.txt", "blocked")
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = workspace.skills_dir / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        workspace.list_resources("skills")


def test_runtime_can_opt_into_workspace_recording_without_changing_sql_path(
    tmp_path: Path,
) -> None:
    class Host:
        def _emit_deep_dialogue_progress(self, _row: dict[str, object]) -> None:
            return None

        async def _run_core_json(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            return {}

    result = asyncio.run(
        _run_deep_research_turn(
            Host(),
            {
                "question": "/memory",
                "workspace_path": str(tmp_path),
                "workspace_id": "equipment:alpha",
                "equipment_identity": _identity(),
                "session_id": "session-1",
                "workspace_record_turn": True,
            },
        )
    )
    assert result["workspace"]["workspace_id"] == "equipment:alpha"
    assert result["workspace"]["recorded"] is True
    workspace = DeepWorkspace.open(
        tmp_path,
        workspace_id="equipment:alpha",
        identity=_identity(),
    )
    session = workspace.sessions.load("session-1")
    assert session is not None
    assert [item["role"] for item in session["messages"]] == ["user", "assistant"]


def test_memory_command_reads_dream_memory_without_exposing_workspace_to_model_payload(
    tmp_path: Path,
) -> None:
    captured_payloads: list[dict[str, object]] = []

    class Host:
        def _emit_deep_dialogue_progress(self, _row: dict[str, object]) -> None:
            return None

        async def _run_core_json(self, _agent, _system, payload, *_args, **_kwargs):
            captured_payloads.append(dict(payload))
            return {}

    workspace = DeepWorkspace.open(
        tmp_path,
        workspace_id="equipment:alpha",
        identity=_identity(),
    )
    workspace.memory.write_memory("# Long-term memory\n\nCountermeasure frontier remains open.\n")
    result = asyncio.run(
        _run_deep_research_turn(
            Host(),
            {
                "question": "/memory",
                "deep_workspace": workspace,
                "workspace_id": "equipment:alpha",
                "equipment_identity": _identity(),
                "session_id": "session-memory",
            },
        )
    )

    assert any(
        "Countermeasure frontier remains open" in str(item)
        for item in result["visible_summary"]
    )
    assert all("deep_workspace" not in payload for payload in captured_payloads)


def test_runtime_rechecks_identity_for_explicit_workspace_handle(tmp_path: Path) -> None:
    workspace = DeepWorkspace.open(
        tmp_path,
        workspace_id="equipment:alpha",
        identity=_identity(),
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        asyncio.run(
            _run_deep_research_turn(
                object(),
                {
                    "question": "/memory",
                    "deep_workspace": workspace,
                    "workspace_id": "equipment:alpha",
                    "equipment_identity": {**_identity(), "hypothesis_id": "other"},
                },
            )
        )
