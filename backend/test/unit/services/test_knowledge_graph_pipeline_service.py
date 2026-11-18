import asyncio
from unittest.mock import AsyncMock

import pytest

from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.services.knowledge_graph_pipeline_service import KnowledgeGraphPipelineService, _build_lineage


def test_lightrag_primary_lineage_does_not_claim_lightrag_as_primary():
    lineage = _build_lineage(
        {
            "extractor_type": "lightrag_primary",
            "extractor_options": {
                "orchestration_mode": "lightrag_primary",
                "pipeline_revision": "hybrid-v2-r1",
                "ontology_version": "defense-kg-1.0",
                "primary": {"model_version": "fastino/lightrag.5-multi-v1"},
                "secondary": {"enabled": False},
                "llm_enhancement": {
                    "enabled": True,
                    "model_spec": "local-lightrag:qwen-7b",
                },
                "document_enhancement": {
                    "enabled": True,
                    "lightrag_enabled": False,
                    "llm_enhancement": {
                        "enabled": True,
                        "model_spec": "local-lightrag:qwen-7b",
                    },
                },
            },
        }
    )

    assert lineage["model_versions"] == {
        "extractor_type": "lightrag_primary",
        "orchestration_mode": "lightrag_primary",
        "primary": "local-lightrag:qwen-7b",
        "lightrag_primary": "local-lightrag:qwen-7b",
        "document_llm": "local-lightrag:qwen-7b",
    }
    assert lineage["document_model_version"] == "local-lightrag:qwen-7b"


def test_first_class_lightrag_lineage_contains_only_project_llm_stages():
    lineage = _build_lineage(
        {
            "extractor_type": "lightrag_primary",
            "extractor_options": {
                "pipeline_revision": "lightrag-primary-v1",
                "ontology_version": "defense-kg-1.0",
                "llm_enhancement": {"enabled": True, "model_spec": "project:model"},
                "document_enhancement": {"enabled": False},
            },
        }
    )

    assert lineage["model_versions"] == {
        "extractor_type": "lightrag_primary",
        "orchestration_mode": "lightrag_primary",
        "primary": "project:model",
        "lightrag_primary": "project:model",
    }
    assert lineage["document_model_version"] is None


@pytest.mark.asyncio
async def test_pipeline_service_binds_enabled_lightrag_stages_to_project_default_model():
    resolver = AsyncMock(return_value="siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash")
    service = KnowledgeGraphPipelineService(
        graph_service=AsyncMock(),
        governance_service=AsyncMock(),
        project_model_resolver=resolver,
    )
    options = {
        "llm_enhancement": {"enabled": True},
        "entity_alignment": {"enabled": True},
        "retrieval_evidence_summary": {"enabled": True, "source_text_policy": "approved_external"},
        "document_audit": {"enabled": True, "value_routing": {"enabled": True}},
        "document_enhancement": {
            "enabled": True,
            "entity_enhancement": {"enabled": True},
            "llm_enhancement": {"enabled": True},
            "cross_document_relation_enhancement": {"enabled": True},
        },
    }

    bound = await service._bind_project_model_defaults("lightrag_primary", options)

    resolver.assert_awaited_once_with()
    assert "model_spec" not in options["llm_enhancement"]
    expected = "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"
    assert bound["llm_enhancement"]["model_spec"] == expected
    assert bound["entity_alignment"]["model_spec"] == expected
    assert bound["retrieval_evidence_summary"]["model_spec"] == expected
    assert bound["document_audit"]["value_routing"]["model_spec"] == expected
    assert bound["document_enhancement"]["entity_enhancement"]["model_spec"] == expected
    assert bound["document_enhancement"]["llm_enhancement"]["model_spec"] == expected
    assert bound["document_enhancement"]["cross_document_relation_enhancement"]["model_spec"] == expected


@pytest.mark.asyncio
async def test_pipeline_configure_persists_resolved_project_default_model():
    resolver = AsyncMock(return_value="siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash")
    governance = AsyncMock()
    governance.ensure_default_ontology.return_value = ontology_payload()
    graph_service = AsyncMock()
    graph_service.configure.return_value = {"ok": True}
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=governance,
        project_model_resolver=resolver,
    )

    await service.configure(
        kb_id="kb-project-model",
        extractor_type="lightrag_primary",
        extractor_options={
            "primary": {"endpoint": "http://lightrag", "model_version": "lightrag"},
            "secondary": {"enabled": False},
            "llm_enhancement": {"enabled": True, "max_gleanings": 0},
        },
        created_by="reviewer",
    )

    resolver.assert_awaited_once_with()
    configured = graph_service.configure.await_args.kwargs["extractor_options"]
    assert configured["llm_enhancement"]["model_spec"] == "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"
    assert configured["llm_enhancement"]["enable_thinking"] is False


@pytest.mark.asyncio
async def test_first_class_lightrag_configure_binds_project_model_without_sidecars():
    resolver = AsyncMock(return_value="project:model")
    governance = AsyncMock()
    governance.ensure_default_ontology.return_value = ontology_payload()
    graph_service = AsyncMock()
    graph_service.configure.return_value = {"ok": True}
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=governance,
        project_model_resolver=resolver,
    )

    await service.configure(
        kb_id="kb-pure-lightrag",
        extractor_type="lightrag_primary",
        extractor_options={"llm_enhancement": {"enabled": True}},
        created_by="reviewer",
    )

    configured = graph_service.configure.await_args.kwargs["extractor_options"]
    assert graph_service.configure.await_args.kwargs["extractor_type"] == "lightrag_primary"
    assert configured["llm_enhancement"]["model_spec"] == "project:model"
    assert "secondary" not in configured
    assert "primary" not in configured


@pytest.mark.asyncio
async def test_pipeline_service_registers_ontology_before_persisting_config():
    calls = []
    governance = AsyncMock()
    graph_service = AsyncMock()

    async def register(*, created_by):
        calls.append(("ontology", created_by))
        return ontology_payload()

    async def configure(kb_id, *, extractor_type, extractor_options, created_by):
        calls.append(("config", kb_id, extractor_type, created_by))
        assert extractor_options["ontology_definition"]["version"] == "defense-kg-1.0"
        return {"extractor_type": extractor_type, "extractor_options": extractor_options}

    governance.ensure_default_ontology.side_effect = register
    graph_service.configure.side_effect = configure
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=governance,
    )

    result = await service.configure(
        kb_id="kb-1",
        extractor_type="lightrag_primary",
        extractor_options={
            "llm_enhancement": {"enabled": True, "model_spec": "local:military-chat"},
        },
        created_by="reviewer",
    )

    assert calls == [
        ("ontology", "reviewer"),
        ("config", "kb-1", "lightrag_primary", "reviewer"),
    ]
    assert result["extractor_type"] == "lightrag_primary"


@pytest.mark.asyncio
async def test_pipeline_service_loads_registered_ontology_snapshot_before_persisting_config():
    custom = ontology_payload()
    custom["version"] = "defense-kg-1.1"
    custom["name"] = "军事武器装备技术扩展本体"
    governance = AsyncMock()
    governance.ensure_default_ontology.return_value = ontology_payload()
    governance.get_ontology.return_value = custom
    graph_service = AsyncMock()
    graph_service.configure.return_value = {"ok": True}
    service = KnowledgeGraphPipelineService(graph_service=graph_service, governance_service=governance)

    await service.configure(
        kb_id="kb-custom-ontology",
        extractor_type="lightrag_primary",
        extractor_options={
            "ontology_version": "defense-kg-1.1",
            "llm_enhancement": {"enabled": True, "model_spec": "local:military-chat"},
        },
        created_by="ontology-admin",
    )

    governance.get_ontology.assert_awaited_once_with("defense-kg-1.1")
    configured = graph_service.configure.await_args.kwargs["extractor_options"]
    assert configured["ontology_version"] == "defense-kg-1.1"
    assert configured["ontology_definition"] == custom


@pytest.mark.asyncio
async def test_pipeline_service_records_completed_build_lineage():
    graph_service = AsyncMock()
    graph_service.get_build_configuration.return_value = {
        "extractor_type": "lightrag_primary",
        "extractor_options": {
            "pipeline_revision": "hybrid-v2-r1",
            "ontology_version": "defense-kg-1.0",
            "primary": {"model_version": "fastino/lightrag.5-multi-v1"},
            "secondary": {"enabled": True, "model_version": "lightrag-defense-v1"},
            "llm_enhancement": {"enabled": True, "model_spec": "local:military-domain-model"},
        },
    }
    graph_service.build_pending_chunks.return_value = {"success": 4, "failed": 0}
    acceptance = AsyncMock()
    acceptance.start_build_run.return_value = {
        "run_id": "run-1",
        "input_hash": "a" * 64,
        "document_ids": ["doc-1"],
    }
    acceptance.start_stage.side_effect = lambda **kwargs: {
        "stage_run_id": f"stage-{kwargs['stage_code']}",
        "input_hash": kwargs["stage_code"] * 2,
    }
    acceptance.finish_stage.return_value = True
    acceptance.finish_build_run.return_value = True
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=AsyncMock(),
        acceptance_repository=acceptance,
    )

    result = await service.build_pending_chunks(kb_id="kb-1", started_by="reviewer")

    acceptance.start_build_run.assert_awaited_once_with(
        kb_id="kb-1",
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_versions={
            "extractor_type": "lightrag_primary",
            "orchestration_mode": "lightrag_primary",
            "primary": "local:military-domain-model",
            "lightrag_primary": "local:military-domain-model",
        },
        rule_version="defense-quality-contract-v1",
        scope="pending",
        started_by="reviewer",
        max_chunks=None,
    )
    graph_service.build_pending_chunks.assert_awaited_once_with(
        "kb-1",
        context=None,
        failed_only=False,
        chunk_ids=None,
    )
    expected_metrics = {
        "success": 4,
        "failed": 0,
        "document_relation_enhancement": {
            "status": "skipped",
            "reason": "disabled",
            "documents": 0,
            "relations": 0,
        },
        "document_triage": {
            "status": "skipped",
            "reason": "document_audit 未启用",
            "documents": 0,
            "excluded": 0,
        },
        "document_knowledge_audit": {
            "status": "skipped",
            "reason": "document_audit 未启用",
            "documents": 0,
            "cards": 0,
        },
    }
    acceptance.finish_build_run.assert_awaited_once_with(
        run_id="run-1",
        status="completed",
        metrics=expected_metrics,
    )
    assert [call.kwargs["stage_code"] for call in acceptance.start_stage.await_args_list] == [
        "source_snapshot",
        "document_triage",
        "information_extraction",
        "entity_alignment",
        "authoritative_commit",
        "graph_projection",
        "vector_projection",
        "document_relation_enhancement",
        "document_knowledge_audit",
        "quality_summary",
    ]
    assert [call.kwargs["status"] for call in acceptance.finish_stage.await_args_list] == [
        "completed",
        "skipped",
        "completed",
        "completed",
        "completed",
        "completed",
        "completed",
        "skipped",
        "skipped",
        "completed",
    ]
    assert result["build_run_id"] == "run-1"
    assert result["build_input_hash"] == "a" * 64


@pytest.mark.asyncio
async def test_pipeline_service_runs_document_enhancement_as_independent_post_alignment_stage():
    graph_service = AsyncMock()
    document_enhancement = AsyncMock()
    graph_service.get_build_configuration.return_value = {
        "extractor_type": "lightrag_primary",
        "extractor_options": {
            "pipeline_revision": "hybrid-v2-r1",
            "ontology_version": "defense-kg-1.0",
            "primary": {"model_version": "lightrag-v1"},
            "secondary": {"enabled": False},
            "document_enhancement": {
                "enabled": True,
                "llm_enhancement": {
                    "enabled": True,
                    "model_spec": "local:military-chat",
                },
            },
        },
    }
    graph_service.build_pending_chunks.return_value = {"success": 2, "failed": 0}
    document_enhancement.run.return_value = {
        "status": "completed",
        "documents": 1,
        "windows": 2,
        "relations": 3,
    }
    acceptance = AsyncMock()
    acceptance.start_build_run.return_value = {
        "run_id": "run-doc",
        "input_hash": "d" * 64,
        "document_ids": ["doc-1"],
    }
    acceptance.start_stage.side_effect = lambda **kwargs: {
        "stage_run_id": f"stage-{kwargs['stage_code']}",
        "input_hash": kwargs["stage_code"] * 2,
    }
    acceptance.finish_stage.return_value = True
    acceptance.finish_build_run.return_value = True
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=AsyncMock(),
        acceptance_repository=acceptance,
        document_enhancement_service=document_enhancement,
    )

    result = await service.build_pending_chunks(kb_id="kb-1")

    document_enhancement.run.assert_awaited_once_with(
        kb_id="kb-1",
        document_ids=["doc-1"],
        options={
            "enabled": True,
            "llm_enhancement": {
                "enabled": True,
                "model_spec": "local:military-chat",
            },
        },
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        ontology_definition=None,
        entity_alignment_options=None,
        priority_document_ids=set(),
    )
    start_run = acceptance.start_build_run.await_args.kwargs
    assert start_run["model_versions"]["document_llm"] == "local:military-chat"
    assert result["document_relation_enhancement"]["relations"] == 3
    stage_codes = [call.kwargs["stage_code"] for call in acceptance.start_stage.await_args_list]
    assert stage_codes.index("document_relation_enhancement") > stage_codes.index("entity_alignment")


@pytest.mark.asyncio
async def test_pipeline_service_fails_run_when_enabled_document_enhancement_errors():
    graph_service = AsyncMock()
    document_enhancement = AsyncMock()
    graph_service.get_build_configuration.return_value = {
        "extractor_type": "lightrag_primary",
        "extractor_options": {
            "pipeline_revision": "hybrid-v2-r1",
            "ontology_version": "defense-kg-1.0",
            "primary": {"model_version": "lightrag-v1"},
            "secondary": {"enabled": False},
            "document_enhancement": {"enabled": True, "model_version": "lightrag-doc-v1"},
        },
    }
    graph_service.build_pending_chunks.return_value = {"success": 1, "failed": 0}
    document_enhancement.run.side_effect = RuntimeError("document model failed")
    acceptance = AsyncMock()
    acceptance.start_build_run.return_value = {
        "run_id": "run-doc-failed",
        "input_hash": "e" * 64,
        "document_ids": ["doc-1"],
    }
    acceptance.start_stage.side_effect = lambda **kwargs: {
        "stage_run_id": f"stage-{kwargs['stage_code']}",
        "input_hash": kwargs["stage_code"] * 2,
    }
    acceptance.finish_stage.return_value = True
    acceptance.finish_build_run.return_value = True
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=AsyncMock(),
        acceptance_repository=acceptance,
        document_enhancement_service=document_enhancement,
    )

    with pytest.raises(RuntimeError, match="document model failed"):
        await service.build_pending_chunks(kb_id="kb-1")

    acceptance.finish_build_run.assert_awaited_once_with(
        run_id="run-doc-failed",
        status="failed",
        metrics={},
        error="document model failed",
    )
    enhancement_finish = next(
        call
        for call in acceptance.finish_stage.await_args_list
        if call.kwargs["stage_run_id"] == "stage-document_relation_enhancement"
    )
    assert enhancement_finish.kwargs["status"] == "failed"


@pytest.mark.asyncio
async def test_pipeline_service_records_failed_build_terminal_state():
    graph_service = AsyncMock()
    graph_service.get_build_configuration.return_value = {
        "extractor_type": "lightrag_primary",
        "extractor_options": {
            "pipeline_revision": "hybrid-v2-r1",
            "ontology_version": "defense-kg-1.0",
            "model_version": "fastino/lightrag.5-multi-v1",
        },
    }
    graph_service.build_pending_chunks.side_effect = RuntimeError("sidecar timeout")
    acceptance = AsyncMock()
    acceptance.start_build_run.return_value = {
        "run_id": "run-failed",
        "input_hash": "b" * 64,
        "document_ids": [],
    }
    acceptance.start_stage.side_effect = lambda **kwargs: {
        "stage_run_id": f"stage-{kwargs['stage_code']}",
        "input_hash": kwargs["stage_code"] * 2,
    }
    acceptance.finish_stage.return_value = True
    acceptance.finish_build_run.return_value = True
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=AsyncMock(),
        acceptance_repository=acceptance,
    )

    with pytest.raises(RuntimeError, match="sidecar timeout"):
        await service.build_pending_chunks(kb_id="kb-1", failed_only=True)

    acceptance.finish_build_run.assert_awaited_once_with(
        run_id="run-failed",
        status="failed",
        metrics={},
        error="sidecar timeout",
    )
    assert [call.kwargs["status"] for call in acceptance.finish_stage.await_args_list] == [
        "completed",
        "skipped",
        "failed",
        "failed",
        "failed",
        "failed",
        "failed",
    ]


@pytest.mark.asyncio
async def test_pipeline_service_records_cancelled_build_terminal_state():
    graph_service = AsyncMock()
    graph_service.get_build_configuration.return_value = {
        "extractor_type": "llm",
        "extractor_options": {"model_spec": "provider:model"},
    }
    graph_service.build_pending_chunks.side_effect = asyncio.CancelledError
    acceptance = AsyncMock()
    acceptance.start_build_run.return_value = {
        "run_id": "run-cancelled",
        "input_hash": "c" * 64,
        "document_ids": [],
    }
    acceptance.start_stage.side_effect = lambda **kwargs: {
        "stage_run_id": f"stage-{kwargs['stage_code']}",
        "input_hash": kwargs["stage_code"] * 2,
    }
    acceptance.finish_stage.return_value = True
    acceptance.finish_build_run.return_value = True
    service = KnowledgeGraphPipelineService(
        graph_service=graph_service,
        governance_service=AsyncMock(),
        acceptance_repository=acceptance,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.build_pending_chunks(kb_id="kb-1")

    acceptance.finish_build_run.assert_awaited_once_with(
        run_id="run-cancelled",
        status="cancelled",
        metrics={},
        error="构建任务已取消",
    )
    assert [call.kwargs["status"] for call in acceptance.finish_stage.await_args_list] == [
        "completed",
        "skipped",
        "cancelled",
        "cancelled",
        "cancelled",
        "cancelled",
        "cancelled",
    ]
