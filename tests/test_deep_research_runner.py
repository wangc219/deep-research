from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import socket
import ssl
from typing import Any

import pytest

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.tools.materialization import EvidenceMaterializer
from equipment_deep_research.tools.permissions import ToolPermissionRegistry


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class _FakeHTTPResponse:
    content: bytes = b"public source content"
    headers: dict[str, str] = field(default_factory=dict)
    status_code: int = 200
    reason: str = "OK"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}: {self.reason}")


class _RecordingTransport:
    def __init__(self, *responses: _FakeHTTPResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> _FakeHTTPResponse:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected transport request")
        return self.responses.pop(0)


def _evidence(source_url: str, *, evidence_id: str = "ev-test") -> EvidenceCard:
    return EvidenceCard(
        evidence_id=evidence_id,
        source_title="test source",
        source_url=source_url,
        source_tier="A",
        claim="test claim",
        excerpt="test excerpt",
        source_location="test:1",
        quality_assessment="test_quality",
        created_by="test_agent",
    )


def _runner(tmp_path: Path) -> DeepResearchRunner:
    return DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        preset_config_path=ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
    )


def test_fake_default_full_loop_outputs_files(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="fake-full",
    )
    run_dir = Path(result["run_dir"])
    assert (run_dir / "report.md").exists()
    assert (run_dir / "capability_images.json").exists()
    assert (run_dir / "round_summary.json").exists()
    assert (run_dir / "domain.jsonl").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "artifacts").exists()
    images = json.loads((run_dir / "capability_images.json").read_text(encoding="utf-8"))
    assert {item["capability_type"] for item in images} == {"new_capability", "upgrade"}
    assert "需要发展具备" not in (run_dir / "report.md").read_text(encoding="utf-8")
    assert result["stage_count"] == 3
    summary = json.loads((run_dir / "round_summary.json").read_text(encoding="utf-8"))
    assert summary["store_summary"]["materialized_evidence_count"] == 4
    assert len(summary["source_materials"]) == 4


def test_subset_agents_runs_with_coverage_limits(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="fake-subset",
        agent_ids=["combat_scenario", "weapon_equipment"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["selected_agent_ids"] == ["combat_scenario", "weapon_equipment"]
    assert summary["coverage"]["missing_required_tags"]
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "缺失关键能力标签" in report


def test_three_research_routes_have_e2e(tmp_path: Path) -> None:
    for route in ["new_winning_mechanism", "traditional_gap", "war_case_learning"]:
        result = _runner(tmp_path).run(
            mode="fake",
            topic=f"{route} 测试主题",
            research_route=route,
            run_id=f"run-{route}",
        )
        summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
        assert summary["resolved_route"] == route
        assert result["capability_count"] == 2


def test_real_smoke_materializes_public_source_diagnostics(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="real",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="real-smoke",
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["mode"] == "real"
    assert len(summary["source_materials"]) == 4
    assert all(row["artifact_refs"] for row in summary["source_materials"])


def test_public_source_is_not_blocked_by_domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from equipment_deep_research.agents import provider
    from equipment_deep_research.tools import materialization

    monkeypatch.setattr(provider, "_public_smoke_url_for_agent", lambda agent_id: "https://example.com/public")
    monkeypatch.setattr(
        materialization.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        materialization.PinnedHTTPTransport,
        "get",
        lambda *args, **kwargs: _FakeHTTPResponse(headers={"content-type": "text/plain"}),
    )
    result = _runner(tmp_path).run(
        mode="real",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="public-source",
        agent_ids=["international_situation"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["source_materials"][0]["status"] == "fetched"
    assert summary["store_summary"]["evidence_count"] == 1
    domain_rows = [
        json.loads(line)
        for line in (Path(result["run_dir"]) / "domain.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    packets = [row["payload"] for row in domain_rows if row["type"] == "BaselineFindingPacket"]
    assert packets[0]["evidence_ids"]


def test_failed_public_fetch_is_not_formal_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from equipment_deep_research.agents import provider
    from equipment_deep_research.tools import materialization

    monkeypatch.setattr(provider, "_public_smoke_url_for_agent", lambda agent_id: "https://example.com/unavailable")
    monkeypatch.setattr(
        materialization.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        materialization.PinnedHTTPTransport,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    result = _runner(tmp_path).run(
        mode="real",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="failed-source",
        agent_ids=["international_situation"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["source_materials"][0]["status"] == "fetch_failed"
    assert summary["store_summary"]["evidence_count"] == 0
    domain_rows = [
        json.loads(line)
        for line in (Path(result["run_dir"]) / "domain.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    packets = [row["payload"] for row in domain_rows if row["type"] == "BaselineFindingPacket"]
    assert packets[0]["evidence_ids"] == []
    assert result["audit_status"] == "limited"


def test_private_network_source_is_rejected_before_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from equipment_deep_research.agents import provider
    from equipment_deep_research.tools import materialization

    requested = False

    def unexpected_get(*args: object, **kwargs: object) -> object:
        nonlocal requested
        requested = True
        raise AssertionError("private network URL must not be fetched")

    monkeypatch.setattr(provider, "_public_smoke_url_for_agent", lambda agent_id: "http://internal.example/private")
    monkeypatch.setattr(
        materialization.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 80))],
    )
    monkeypatch.setattr(materialization.PinnedHTTPTransport, "get", unexpected_get)
    result = _runner(tmp_path).run(
        mode="real",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="private-source",
        agent_ids=["international_situation"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert requested is False
    assert summary["source_materials"][0]["status"] == "network_safety_rejected"
    assert summary["store_summary"]["evidence_count"] == 0


def test_malformed_ipv6_source_does_not_skip_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from equipment_deep_research.agents import provider

    monkeypatch.setattr(
        provider,
        "_public_smoke_url_for_agent",
        lambda agent_id: "http://[2001:db8::1/",
    )
    result = _runner(tmp_path).run(
        mode="real",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="malformed-ipv6-source",
        agent_ids=["international_situation"],
    )

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert len(summary["source_materials"]) == 1
    assert summary["source_materials"][0]["status"] == "network_safety_rejected"
    assert summary["store_summary"]["evidence_count"] == 0


def test_private_ip_source_is_rejected_before_transport(tmp_path: Path) -> None:
    transport = _RecordingTransport()
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    result = materializer.materialize(_evidence("http://10.0.0.7/private"), mode="real")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "private_network_denied"
    assert transport.calls == []


def test_public_dns_result_is_the_ip_used_by_transport(tmp_path: Path) -> None:
    resolver_calls: list[tuple[str, int]] = []

    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        resolver_calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = _RecordingTransport(_FakeHTTPResponse(headers={"content-type": "text/plain"}))
    materializer = EvidenceMaterializer(tmp_path, resolver=resolver, transport=transport)

    result = materializer.materialize(_evidence("https://example.com/public"), mode="real")

    assert result.material["status"] == "fetched"
    assert resolver_calls == [("example.com", 443)]
    assert transport.calls[0]["connect_ip"] == "93.184.216.34"
    assert transport.calls[0]["hostname"] == "example.com"


def test_redirect_to_private_network_is_rejected_before_second_transport_request(tmp_path: Path) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        address = "93.184.216.34" if host == "public.example" else "10.0.0.7"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    transport = _RecordingTransport(
        _FakeHTTPResponse(
            content=b"",
            headers={"location": "http://internal.example/private"},
            status_code=302,
            reason="Found",
        )
    )
    materializer = EvidenceMaterializer(tmp_path, resolver=resolver, transport=transport)

    result = materializer.materialize(_evidence("https://public.example/start"), mode="real")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "private_network_denied"
    assert [call["connect_ip"] for call in transport.calls] == ["93.184.216.34"]


def test_redirect_hops_are_limited(tmp_path: Path) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = _RecordingTransport(
        _FakeHTTPResponse(content=b"", headers={"location": "/second"}, status_code=302),
        _FakeHTTPResponse(content=b"", headers={"location": "/third"}, status_code=302),
    )
    materializer = EvidenceMaterializer(
        tmp_path,
        max_redirects=1,
        resolver=resolver,
        transport=transport,
    )

    result = materializer.materialize(_evidence("https://public.example/first"), mode="real")

    assert result.material["status"] == "fetch_failed"
    assert "redirect limit exceeded: 1" in result.material["error"]
    assert len(transport.calls) == 2


def test_pinned_https_uses_validated_ip_with_original_hostname_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from equipment_deep_research.tools import http_transport

    opened: list[tuple[str, int, object]] = []
    wrapped: list[tuple[object, str]] = []
    raw_socket = object()
    tls_socket = object()

    class RecordingTLSContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, sock: object, *, server_hostname: str) -> object:
            wrapped.append((sock, server_hostname))
            return tls_socket

    def open_numeric_ip(connect_ip: str, *, port: int, timeout_seconds: object) -> object:
        opened.append((connect_ip, port, timeout_seconds))
        return raw_socket

    monkeypatch.setattr(http_transport, "_connect_numeric_ip", open_numeric_ip)
    connection = http_transport._PinnedHTTPConnection(
        connect_ip="93.184.216.34",
        port=443,
        timeout_seconds=8,
        tls_hostname="example.com",
        ssl_context=RecordingTLSContext(),
    )

    connection.connect()

    assert opened == [("93.184.216.34", 443, 8)]
    assert wrapped == [(raw_socket, "example.com")]
    assert connection.sock is tls_socket


def test_pinned_https_rejects_unverified_tls_context() -> None:
    from equipment_deep_research.tools.http_transport import PinnedHTTPTransport

    with pytest.raises(ValueError, match="verify certificate hostnames"):
        PinnedHTTPTransport(ssl_context=ssl._create_unverified_context())


def test_fake_fixture_requires_exact_hostname(tmp_path: Path) -> None:
    transport = _RecordingTransport(_FakeHTTPResponse(headers={"content-type": "text/plain"}))

    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        assert host == "attacker.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    materializer = EvidenceMaterializer(tmp_path, resolver=resolver, transport=transport)

    result = materializer.materialize(
        _evidence("https://fixture.local@attacker.com/"),
        mode="fake",
    )

    assert result.material["status"] == "fetched"
    assert transport.calls[0]["hostname"] == "attacker.com"


def test_fake_fixture_exact_hostname_materializes_without_transport(tmp_path: Path) -> None:
    transport = _RecordingTransport()
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    result = materializer.materialize(_evidence("https://fixture.local/source"), mode="fake")

    assert result.material["status"] == "fixture_materialized"
    assert transport.calls == []


def test_fake_fixture_does_not_bypass_allowed_schemes(tmp_path: Path) -> None:
    transport = _RecordingTransport()
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    result = materializer.materialize(_evidence("ftp://fixture.local/source"), mode="fake")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "scheme_not_allowed"
    assert transport.calls == []


def test_real_mode_rejects_fixture_hostname_without_transport(tmp_path: Path) -> None:
    transport = _RecordingTransport()
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    result = materializer.materialize(_evidence("https://fixture.local/source"), mode="real")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "fixture_only_allowed_in_fake_mode"
    assert transport.calls == []


def test_recall_requests_are_traceable_for_missing_coverage(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="低空无人机探测预警能力缺口",
        research_route="new_winning_mechanism",
        run_id="recall-trace",
        agent_ids=["combat_scenario", "weapon_equipment"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["recall_requests"]
    trace_rows = [
        json.loads(line)
        for line in (Path(result["run_dir"]) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    recall_events = [row["payload"] for row in trace_rows if row["payload"]["event_type"] == "recall_requested"]
    assert {event["payload"]["target_capability_tag"] for event in recall_events} >= {"operation", "threat"}


def test_custom_agent_config_is_selected_without_explicit_agent_ids(tmp_path: Path) -> None:
    custom_agents = tmp_path / "agents.yaml"
    custom_agents.write_text(
        """
default_model: gpt-5.5
agents:
  - agent_id: integrated_research
    display_name: 综合研判
    description: 覆盖首版新制胜机理路线所需标签的替换agent。
    capability_tags: [situation, threat, scenario, equipment, operation]
    tools: [search_sources, fetch_page, create_evidence_card]
    context_policy:
      visible_sections: [task, evidence_policy, own_checkpoint, recall_request]
    enabled: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=custom_agents,
        preset_config_path=ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
    ).run(
        mode="fake",
        topic="新型协同防空能力方向",
        research_route="new_winning_mechanism",
        run_id="custom-agent",
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["selected_agent_ids"] == ["integrated_research"]
    assert summary["coverage"]["coverage_passed"] is True


def test_tool_permission_denial_is_enforced() -> None:
    agent = AgentDef(
        agent_id="limited_agent",
        display_name="受限智能体",
        description="只允许写证据卡。",
        capability_tags=["scenario"],
        tools=["create_evidence_card"],
        context_policy={},
    )
    with pytest.raises(PermissionError):
        ToolPermissionRegistry.default().enforce_active_tool(agent, "fetch_page")
