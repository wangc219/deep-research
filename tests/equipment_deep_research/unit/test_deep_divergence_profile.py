import asyncio
from hashlib import sha256

from equipment_deep_research.agents.workflows.winning import (
    _analyze_deep_divergence_subagents,
)
from equipment_deep_research.orchestration.execution_contracts import (
    apply_execution_profile_to_blueprint,
    deep_divergence_v1_profile,
)


class _DeepHost:
    def __init__(self, *, fail_s4: bool = False) -> None:
        self.events = []
        self.fail_s4 = fail_s4

    def _emit_winning_progress(self, row):
        self.events.append(dict(row))

    async def _run_core_json(self, agent_id, _prompt, payload, _schema, _tokens, *, phase):
        if phase == "deep_s3_divergence":
            slot = int(payload["divergence_slot"])
            return {
                "hypothesis_id": f"h-{slot}",
                "direction_name": f"方向{slot}",
                "breakthrough_directions": [f"S3-{slot}"],
                "effect_chain": ["压力→断点→效果"],
                "equipment_form": "拦截器",
                "operational_mechanism": "压缩交战窗口",
                "military_value": "形成直接拦截效果",
                "target_and_direct_effect": "拦截目标",
                "failure_boundary": "极端环境需验证",
                "direct_evidence_refs": ["ev-parent"],
                "confidence": 0.7,
                "open_questions": [],
            }
        if phase == "deep_s4_mapping":
            if self.fail_s4 and int(payload["mapping_slot"]) == 2:
                raise RuntimeError("synthetic S4 failure")
            slot = int(payload["mapping_slot"])
            return {
                "hypothesis_id": f"h-{slot}",
                "capability_mapping": [f"能力映射{slot}"],
                "concept_directions": [
                    {
                        "name": f"方向{slot}",
                        "type": "new_capability",
                        "function": "拦截",
                        "equipment_form": "拦截器",
                        "primary_equipment_identity": f"拦截器{slot}",
                        "operational_mechanism": "压缩交战窗口",
                        "target_scenario": "当前Query",
                        "military_value": "直接拦截",
                        "direct_evidence_refs": ["ev-parent"],
                        "capability_gap": "现有能力不足",
                        "baseline_system": "现役基线",
                        "failure_boundary": "需验证",
                        "validation_plan": ["仿真验证"],
                        "confidence": 0.65,
                    }
                ],
                "confidence": 0.65,
                "open_questions": [],
            }
        if phase == "deep_s6_authoring":
            directions = payload["candidate_directions"]
            return {
                "concept_directions": directions[:2],
                "confidence": 0.65,
                "open_questions": [],
                "evidence_validation": {"all_ids_valid": True, "invalid_ids": []},
            }
        raise AssertionError((agent_id, phase))


def test_deep_divergence_runs_only_s3_s4_s6_and_caps_slots():
    host = _DeepHost()
    result = asyncio.run(_analyze_deep_divergence_subagents(
        host,
        {
            "run_id": "child-1",
            "topic": "当前Query",
            "research_route": "traditional_gap",
            "execution_profile_id": "deep_divergence_v1",
            "evidence_index": [],
            "deep_parent_context": {
                "parent_run_id": "parent-1",
                "hypothesis_id": "h-parent",
                "candidate": {"name": "参考武器", "evidence_ids": ["ev-parent"]},
                "focus": "补齐直接作战效果",
            },
        },
    ))
    assert result["deep_stage_scope"] == ["S3", "S4", "S6"]
    assert result["deep_stage_plan"]["S3"]["completed"] == 3
    assert result["deep_stage_plan"]["S4"]["completed"] == 3
    assert len(result["concept_directions"]) == 2
    assert not any("S1" in str(event) or "S2" in str(event) or "S5" in str(event) for event in host.events)


def test_deep_profile_persists_search_and_concurrency_budgets():
    profile = deep_divergence_v1_profile()
    blueprint = apply_execution_profile_to_blueprint(
        {"primary_branch": "A", "runtime_route": "traditional_gap"},
        profile,
    )
    budgets = blueprint["runtime_budgets"]
    assert budgets["maximum_searches"] == 6
    assert budgets["max_searches"] == 6
    assert budgets["codex_concurrency"] == 6
    assert budgets["max_concurrency"] == 6


def test_deep_divergence_preserves_partial_s4_failure():
    host = _DeepHost(fail_s4=True)
    result = asyncio.run(_analyze_deep_divergence_subagents(
        host,
        {
            "run_id": "child-2",
            "topic": "当前Query",
            "research_route": "traditional_gap",
            "execution_profile_id": "deep_divergence_v1",
            "evidence_index": [],
            "deep_parent_context": {
                "parent_run_id": "parent-1",
                "hypothesis_id": "h-parent",
                "candidate": {"name": "参考武器", "evidence_ids": ["ev-parent"]},
            },
        },
    ))
    assert result["deep_divergence_status"] == "partial"
    assert any(item["stage"] == "S4" for item in result["deep_failures"])
    assert result["deep_stage_plan"]["S4"]["failed"] == 1


class _RetrievalHost(_DeepHost):
    def __init__(self) -> None:
        super().__init__()
        self.retrieval_calls = 0
        self.prompts = []

    def _discovery_provider_for(self, _agent_id):
        return object()

    def _runtime_messages(self, *_args, **_kwargs):
        return []

    def _harness_for(self, _agent):
        return None

    async def _collect_stream(self, *_args, **_kwargs):
        self.retrieval_calls += 1
        return "ignored", {
            "web_sources": [
                {
                    "url": f"https://example.com/source-{self.retrieval_calls}",
                    "title": "公开来源",
                    "snippet": "可供后续材料化核验的来源线索",
                }
            ]
        }

    def _reserve_search_batches(self, requested):
        return min(6, requested)

    async def _run_core_json(self, agent_id, _prompt, payload, _schema, _tokens, *, phase):
        self.prompts.append((phase, payload))
        if phase == "deep_s3_divergence":
            slot = int(payload["divergence_slot"])
            return {
                "hypothesis_id": f"h-{slot}",
                "direction_name": f"方向{slot}",
                "breakthrough_directions": [f"S3-{slot}"],
                "effect_chain": ["压力→断点→效果"],
                "equipment_form": "拦截器",
                "operational_mechanism": "压缩交战窗口",
                "military_value": "形成直接拦截效果",
                "target_and_direct_effect": "拦截目标",
                "failure_boundary": "需公开资料核验",
                "evidence_gap": ["缺少公开型号和效果依据"],
                "direct_evidence_refs": [],
                "confidence": 0.5,
                "open_questions": [],
            }
        if phase == "deep_s4_mapping":
            slot = int(payload["mapping_slot"])
            return {
                "hypothesis_id": f"h-{slot}",
                "capability_mapping": [f"能力映射{slot}"],
                "concept_directions": [{
                    "name": f"方向{slot}",
                    "type": "new_capability",
                    "function": "拦截",
                    "equipment_form": "拦截器",
                    "primary_equipment_identity": f"拦截器{slot}",
                    "operational_mechanism": "压缩交战窗口",
                    "target_scenario": "当前Query",
                    "military_value": "直接拦截",
                    "direct_evidence_refs": [
                        f"ev-deep-{sha256(f'https://example.com/source-{slot}'.encode()).hexdigest()[:12]}"
                    ],
                    "capability_gap": "现有能力不足",
                    "baseline_system": "现役基线",
                    "failure_boundary": "需验证",
                    "validation_plan": ["仿真验证"],
                    "confidence": 0.4,
                }],
                "confidence": 0.4,
                "open_questions": [],
            }
        if phase == "deep_s6_authoring":
            raise AssertionError("unmaterialized retrieval leads must not reach S6")
        raise AssertionError((agent_id, phase))


def test_deep_divergence_retrieval_is_bounded_and_stays_before_evidence_gate():
    host = _RetrievalHost()
    result = asyncio.run(_analyze_deep_divergence_subagents(
        host,
        {
            "run_id": "child-retrieval",
            "topic": "当前Query",
            "research_route": "traditional_gap",
            "execution_profile_id": "deep_divergence_v1",
            "evidence_index": [],
            "deep_parent_context": {
                "parent_run_id": "parent-1",
                "candidate": {"name": "参考武器", "api_key": "must-not-leak"},
            },
        },
    ))
    assert host.retrieval_calls == 6
    assert len(result["retrieved_evidence"]) == 6
    assert result["deep_stage_plan"]["retrieval"]["requested"] == 6
    assert result["deep_stage_plan"]["S6"]["failed"] is True
    assert any(item["stage"] == "S6" and "证据门" in item["error"] for item in result["deep_failures"])
    assert all("api_key" not in str(payload) for _phase, payload in host.prompts)
