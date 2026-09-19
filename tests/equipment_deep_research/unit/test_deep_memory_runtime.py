from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pytest

from equipment_deep_research.agents.workflows.orchestrator import _compact_deep_dialogue_seed_payload
from equipment_deep_research.deep_runtime import tools
from equipment_deep_research.deep_runtime.loop import _run_deep_research_turn
from equipment_deep_research.deep_runtime.provider_runtime import ProviderRuntime
from equipment_deep_research.deep_runtime.workspace import DeepWorkspace


def _append_process_history(arguments):
    root, label = arguments
    workspace = DeepWorkspace.open(root)
    return [workspace.memory.append_history(f"{label}-{index}") for index in range(8)]


def test_workspace_preferences_reach_the_core_with_host_precedence(tmp_path, monkeypatch):
    workspace = DeepWorkspace.open(tmp_path)
    workspace.write_resource("skill", "frontier/SKILL.md", """---
name: frontier
description: Explore alternatives
procedure:
  steps: [List assumptions, Compare alternatives]
  required_artifacts: [AlternativeMap]
  quality_gates: [Distinct mechanisms]
  stop_conditions: [No new assumptions]
---
Keep competing assumptions visible.
""")
    workspace.write_resource("config", "runtime.json", json.dumps({
        "active_skill_ids": ["workspace:frontier"],
        "deep_runtime_budget": {"max_turns": 3, "max_tool_calls": 3},
        "authoring_requested": True,
    }))
    received = []

    async def research(state):
        received.append(state)
        return {"visible_summary": ["result"], "concept_directions": []}

    monkeypatch.setitem(tools.TOOL_HANDLERS, "research_council", research)
    result = asyncio.run(_run_deep_research_turn(object(), {
        "deep_workspace": workspace, "question": "research",
        "deep_runtime_budget": {"max_turns": 1},
    }))
    assert received[0].max_turns == 1
    assert received[0].max_tool_calls == 3
    assert received[0].active_skills[0]["skill_id"] == "workspace:frontier"
    assert "Keep competing assumptions" in received[0].skill_prompt
    assert not received[0].payload["authoring_requested"]
    assert result["workspace"]["capabilities"]["loaded"]
    asyncio.run(_run_deep_research_turn(object(), {
        "deep_workspace": workspace, "question": "research", "active_skill_ids": [],
    }))
    assert "workspace:frontier" not in [item["skill_id"] for item in received[-1].active_skills]


def test_memory_and_dream_form_a_real_multi_turn_loop(tmp_path, monkeypatch):
    workspace = DeepWorkspace.open(tmp_path, identity={"name": "equipment-alpha"})
    received = []
    phases = []

    async def research(state):
        received.append(_compact_deep_dialogue_seed_payload(state.payload))
        return {"visible_summary": ["incremental research"],
                "concept_directions": [{"name": "candidate-alpha", "equipment_form": "concept form"}],
                "research_gaps": ["an assumption remains unverified"]}

    monkeypatch.setitem(tools.TOOL_HANDLERS, "research_council", research)
    monkeypatch.setitem(tools.TOOL_HANDLERS, "deepen", research)

    async def provider(_agent, _prompt, payload, _schema, _tokens, *, phase=""):
        phases.append(phase)
        assert str(tmp_path) not in json.dumps(payload)
        if phase == "deep_research_conduct":
            return {"intent": "deepen", "tools": ["deepen"]}
        assert phase == "deep_memory_dream"
        assert "candidate-alpha" in payload["journal"]
        assert "session=main-session branch=main" in payload["journal"]
        return {"summary": "uncertain research frontier", "facts": [
            {"kind": "assumption", "text": "durable but unverified assumption", "session_id": "main-session", "branch_id": "main"}
        ]}

    async def scenario():
        payload = {"deep_workspace": workspace, "session_id": "main-session",
                   "workspace_record_turn": True, "provider_runtime": ProviderRuntime(json_callback=provider)}
        for index in range(4):
            result = await _run_deep_research_turn(object(), {**payload, "question": f"question-{index}"})
            assert result["workspace"]["recorded"]
            if index == 2:
                assert result["workspace"]["dream"]["status"] == "completed"
                assert result["workspace"]["dream_cursor"] == 6
                assert result["workspace"]["memory_cursor"] == 9
        assert phases.count("deep_memory_dream") == 1
        assert "durable but unverified assumption" in json.dumps(received[-1])
        session = workspace.sessions.load("main-session")
        assert len(session["messages"]) == 8
        assert session["messages"][0]["content"] == "question-0"
        assert session["messages"][-1]["metadata"]["research_result"]["concept_directions"]
        checkpoint = workspace.sessions.load_working_memory("main-session")
        assert checkpoint["source_checkpoint"]["assistant_sequence"] == 8
        assert checkpoint["source_checkpoint"]["assistant_message_id"] == session["messages"][-1]["message_id"]
        await _run_deep_research_turn(object(), {**payload, "question": "side question", "branch_id": "side"})
        assert "durable but unverified assumption" not in json.dumps(received[-1])
        assert "candidate-alpha" not in json.dumps(received[-1]["workspace_context"])
        result = await _run_deep_research_turn(object(), {
            **payload, "question": "explicit reset", "working_memory": {}, "workspace_record_turn": False,
        })
        assert result["workspace"]["context"]["authoritative_memory_preserved"]
        assert result["runtime"]["tools"] == ["research_council"]

    asyncio.run(scenario())


@pytest.mark.parametrize("response", [
    {}, {"_provider_error": "unavailable"}, {"summary": "invalid", "facts": "not a list"},
    {"summary": "wrong scope", "facts": [{"text": "foreign", "session_id": "other", "branch_id": "other"}]},
    {"summary": "invalid epistemics", "facts": [{"kind": "finding", "stance": "consensus",
        "text": "unsupported", "session_id": "session", "branch_id": "main"}]},
])
def test_invalid_dream_never_advances_cursor(tmp_path, monkeypatch, response):
    workspace = DeepWorkspace.open(tmp_path)
    for index in range(6):
        workspace.memory.append_history(f"journal-{index}", session_id="session")

    async def research(_state):
        return {"visible_summary": ["visible result"], "concept_directions": []}

    async def provider(*_args, **_kwargs):
        return response

    monkeypatch.setitem(tools.TOOL_HANDLERS, "research_council", research)
    result = asyncio.run(_run_deep_research_turn(object(), {
        "deep_workspace": workspace, "session_id": "session", "question": "continue",
        "workspace_record_turn": True, "provider_runtime": ProviderRuntime(json_callback=provider),
    }))
    assert result["workspace"]["dream"]["status"] == "deferred"
    assert result["workspace"]["recorded"]
    assert workspace.memory.last_dream_cursor() == 0


def test_dream_commits_only_the_snapshot_seen_by_model(tmp_path):
    workspace = DeepWorkspace.open(tmp_path)
    workspace.memory.append_history("seen by model", session_id="session")
    batch = workspace.memory.build_dream_prompt()
    workspace.memory.append_history("arrived during model call", session_id="session")
    result = workspace.memory.consolidate_dream(facts=[{"text": "durable"}], batch=batch)
    assert result.through_cursor == 1
    assert workspace.memory.last_dream_cursor() == 1
    assert "arrived during model call" in workspace.memory.build_dream_prompt().prompt
    with pytest.raises(ValueError, match="stale Dream batch"):
        workspace.memory.consolidate_dream(facts=["obsolete"], batch=batch)
    assert "obsolete" not in workspace.memory.read_memory()


def test_scoped_facts_and_missing_branch_memory_remain_isolated(tmp_path):
    workspace = DeepWorkspace.open(tmp_path)
    workspace.memory.append_history("two branches")
    workspace.memory.consolidate_dream(facts=[
        {"kind": "assumption", "text": "shared wording", "session_id": "session", "branch_id": "main"},
        {"kind": "assumption", "text": "shared wording", "session_id": "session", "branch_id": "side"},
        {"text": "side only", "session_id": "session", "branch_id": "side"},
    ])
    assert "side only" not in workspace.memory.read_context(session_id="session", branch_id="main")
    assert "side only" in workspace.memory.read_context(session_id="session", branch_id="side")
    assert "shared wording" not in workspace.memory.read_context(session_id="another")
    assert len(workspace.memory._read_facts()) == 3
    workspace.sessions.save_working_memory("session", {"current_objective": "side only"}, branch_id="side")
    assert workspace.sessions.load_working_memory("session", branch_id="main") == {}
    assert workspace.sessions.load_working_memory("session", branch_id="missing") == {}
    result = asyncio.run(_run_deep_research_turn(object(), {
        "question": "/memory", "session_id": "session", "branch_id": "main", "deep_workspace": workspace,
    }))
    assert "side only" not in json.dumps(result["visible_summary"])


def test_dream_preserves_opposing_stances_for_the_same_research_subject(tmp_path):
    workspace = DeepWorkspace.open(tmp_path)
    workspace.memory.consolidate_dream(
        facts=[
            {
                "kind": "assumption",
                "stance": "supports",
                "subject_key": "末段自主复核收益",
                "text": "链路受扰时仍可压缩交战窗口",
                "session_id": "session",
                "branch_id": "main",
            },
            {
                "kind": "assumption",
                "stance": "challenges",
                "subject_key": "末段自主复核收益",
                "text": "诱骗会放大错误复核造成的窗口损失",
                "session_id": "session",
                "branch_id": "main",
            },
        ],
        summary="同一机理仍有相反判断",
    )

    facts = workspace.memory._read_facts()
    assert {
        (item["stance"], item["subject_key"])
        for item in facts
        if item.get("kind") == "assumption"
    } == {
        ("supports", "末段自主复核收益"),
        ("challenges", "末段自主复核收益"),
    }
    context = workspace.memory.read_context(session_id="session", branch_id="main")
    assert "assumption/supports/subject=末段自主复核收益" in context
    assert "assumption/challenges/subject=末段自主复核收益" in context
    rendered = workspace.memory.read_memory()
    assert "### assumption / supports" in rendered
    assert "### assumption / challenges" in rendered


def test_run_can_host_multiple_locked_equipment_workspaces(tmp_path):
    first = DeepWorkspace.open_equipment(tmp_path, workspace_id="run:test", identity={"name": "first"})
    second = DeepWorkspace.open_equipment(tmp_path, workspace_id="run:test", identity={"name": "second"})
    first.memory.write_memory("first analyst notes")
    assert first.state_dir != second.state_dir
    assert first.workspace_id != second.workspace_id
    assert second.memory.read_memory() == ""
    reopened = DeepWorkspace.open_equipment(tmp_path, workspace_id="run:test", identity={"name": "first"})
    assert reopened.memory.read_memory() == "first analyst notes"
    with pytest.raises(ValueError, match="identity mismatch"):
        second.assert_identity({"name": "first"})


def test_matching_legacy_workspace_is_preserved_when_scoping_equipment(tmp_path):
    legacy = DeepWorkspace.open(tmp_path, workspace_id="run:test", identity={"name": "first"})
    legacy.memory.write_memory("existing analyst notes")
    legacy.sessions.append_message("existing-session", role="user", content="existing transcript")
    first = DeepWorkspace.open_equipment(tmp_path, workspace_id="run:test", identity={"name": "first"})
    second = DeepWorkspace.open_equipment(tmp_path, workspace_id="run:test", identity={"name": "second"})
    assert first.state_dir == legacy.state_dir
    assert first.memory.read_memory() == "existing analyst notes"
    assert first.sessions.load("existing-session")["messages"][0]["content"] == "existing transcript"
    assert second.sessions.load("existing-session") is None


def test_cancelling_dream_does_not_record_current_turn(tmp_path, monkeypatch):
    workspace = DeepWorkspace.open(tmp_path)
    for index in range(6):
        workspace.memory.append_history(f"journal-{index}", session_id="session")

    async def scenario():
        entered = asyncio.Event()

        async def research(_state):
            return {"visible_summary": ["visible result"], "concept_directions": []}

        async def provider(*_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setitem(tools.TOOL_HANDLERS, "research_council", research)
        task = asyncio.create_task(_run_deep_research_turn(object(), {
            "deep_workspace": workspace, "session_id": "session", "question": "continue",
            "workspace_record_turn": True, "provider_runtime": ProviderRuntime(json_callback=provider),
        }))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert workspace.memory.last_dream_cursor() == 0
        assert workspace.memory.latest_cursor() == 6
        assert workspace.sessions.load("session") is None

    asyncio.run(scenario())


def test_separate_workspace_instances_serialize_journal_cursors(tmp_path):
    first = DeepWorkspace.open(tmp_path)
    second = DeepWorkspace.open(tmp_path)

    def append(workspace, label):
        return [workspace.memory.append_history(f"{label}-{index}") for index in range(12)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append, first, "first"), pool.submit(append, second, "second")]
        cursors = [cursor for future in futures for cursor in future.result()]
    assert sorted(cursors) == list(range(1, 25))
    assert first.memory.latest_cursor() == second.memory.latest_cursor() == 24
    assert len(first.memory.read_history(limit=32)) == 24


@pytest.mark.skipif(os.name != "posix", reason="POSIX file-lock contract")
def test_separate_worker_processes_serialize_journal_cursors(tmp_path):
    workspace = DeepWorkspace.open(tmp_path)
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        batches = list(pool.map(_append_process_history, [(str(tmp_path), "first"), (str(tmp_path), "second")]))
    assert sorted(cursor for batch in batches for cursor in batch) == list(range(1, 17))
    assert workspace.memory.latest_cursor() == 16
    assert len(workspace.memory.read_history(limit=32)) == 16


def test_optional_context_failure_cannot_abort_visible_research(tmp_path, monkeypatch):
    workspace = DeepWorkspace.open(tmp_path)

    def unavailable(*_args, **_kwargs):
        raise OSError("private local path")

    async def research(_state):
        return {"visible_summary": ["visible research"], "concept_directions": []}

    monkeypatch.setattr(workspace.sessions, "build_context", unavailable)
    monkeypatch.setitem(tools.TOOL_HANDLERS, "research_council", research)
    result = asyncio.run(_run_deep_research_turn(object(), {
        "deep_workspace": workspace, "session_id": "session", "question": "continue",
    }))
    assert result["visible_summary"] == ["visible research"]
    assert result["workspace"]["context"]["error"] == "workspace context unavailable"
    assert "private local path" not in json.dumps(result)
    with pytest.raises(OSError):
        asyncio.run(_run_deep_research_turn(object(), {
            "deep_workspace": workspace, "session_id": "session", "question": "continue", "workspace_required": True,
        }))


def test_stop_arriving_during_dream_does_not_advance_current_turn_memory(tmp_path, monkeypatch):
    workspace = DeepWorkspace.open(tmp_path)
    for index in range(6):
        workspace.memory.append_history(f"committed-{index}", session_id="session")
    stopped = False

    async def research(_state):
        return {"visible_summary": ["visible research"], "concept_directions": []}

    async def provider(*_args, **_kwargs):
        nonlocal stopped
        stopped = True
        return {"summary": "old committed records only", "facts": []}

    monkeypatch.setitem(tools.TOOL_HANDLERS, "research_council", research)
    result = asyncio.run(_run_deep_research_turn(object(), {
        "deep_workspace": workspace, "session_id": "session", "question": "continue", "workspace_record_turn": True,
        "should_stop": lambda *_args: stopped, "provider_runtime": ProviderRuntime(json_callback=provider),
    }))
    assert result["workspace"]["recorded"] is False
    assert result["runtime"]["status"] == "stopped"
    assert result["finalization_status"] == "partial"
    assert workspace.sessions.load("session") is None
