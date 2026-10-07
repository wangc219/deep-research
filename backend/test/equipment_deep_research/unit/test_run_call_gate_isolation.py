from __future__ import annotations

import asyncio

from equipment_deep_research.agents.provider import ResponsesAgentProvider
from equipment_deep_research.providers.fake import ScriptedFakeProvider


def test_run_call_gates_are_isolated_and_inherit_codex_concurrency(monkeypatch) -> None:
    """Each run gets its own configured gate while retaining its per-run cap."""

    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "0")

    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget({"codex_concurrency": 2})

    first = provider.call_gate_for_run("run-a")
    second = provider.call_gate_for_run("run-b")

    assert first is not second
    assert provider.call_gate_for_run("run-a") is first
    assert first.snapshot()["limit"] == 2
    assert second.snapshot()["limit"] == 2

    first_leases = [first.try_acquire(priority="critical") for _ in range(2)]
    second_leases = [second.try_acquire(priority="critical") for _ in range(2)]
    try:
        # A single run remains capped at codex_concurrency.
        assert all(first_leases)
        assert first.try_acquire(priority="critical") is None
        assert all(second_leases)
        assert second.try_acquire(priority="critical") is None
    finally:
        for lease in first_leases:
            if lease is not None:
                # The elapsed value is irrelevant to this isolation assertion;
                # use a successful zero-duration release to keep the gate tidy.
                first.release(0.0, success=True)
        for lease in second_leases:
            if lease is not None:
                second.release(0.0, success=True)


def test_run_core_text_routes_nested_run_id_to_internal_options(monkeypatch) -> None:
    """The run identity selects the gate without becoming model-visible input."""

    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    captured_options: dict[str, object] = {}

    async def fake_collect_stream(
        selected_provider,
        messages,
        options,
        **kwargs,
    ):
        del selected_provider, messages, kwargs
        captured_options.update(options)
        return "ok", {}

    monkeypatch.setattr(provider, "_collect_stream", fake_collect_stream)

    payload = {"input": {"run_id": "run-nested", "mission_node": "S3"}}
    asyncio.run(
        provider._run_core_text(
            "winning_swarm_frontier_equipment_miner",
            "system",
            payload,
            128,
            phase="winning_swarm_dynamic_s3",
        )
    )

    assert captured_options["_run_id"] == "run-nested"
    assert payload == {
        "input": {"run_id": "run-nested", "mission_node": "S3"}
    }
