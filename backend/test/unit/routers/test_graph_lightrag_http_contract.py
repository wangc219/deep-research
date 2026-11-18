"""验证 LightRAG 路径增强的 HTTP 权限、校验与字段贯通。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.routers import graph_router


def _app(user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(graph_router.graph)
    current_user = user or SimpleNamespace(uid="user-1", id=1, role="user")
    app.dependency_overrides[graph_router.require_knowledge_base_read] = lambda: current_user
    app.dependency_overrides[graph_router.require_knowledge_base_manage] = lambda: current_user
    return app


def test_path_reranking_requires_manage_permission(monkeypatch):
    """只读用户不能通过路径查询间接调用 LLM。"""
    denied = AsyncMock(side_effect=HTTPException(403, "无管理权限"))
    graph_service = AsyncMock()
    monkeypatch.setattr(graph_router, "require_knowledge_base_manage", denied)
    monkeypatch.setattr(graph_router, "_get_graph_service", AsyncMock(return_value=graph_service))

    response = TestClient(_app()).get(
        "/graph/paths",
        params={
            "kb_id": "kb-1",
            "query": "复杂电磁环境感知",
            "path_reranking_enabled": True,
            "path_reranking_model_spec": "local:military-chat",
        },
    )

    assert response.status_code == 403
    denied.assert_awaited_once()
    graph_router._get_graph_service.assert_not_awaited()


def test_path_reranking_missing_model_uses_project_default(monkeypatch):
    """启用增强但未指定模型时复用项目模型设置。"""
    graph_service = SimpleNamespace(discover_paths=AsyncMock(return_value={"paths": [], "summary": {}}))
    lookup = AsyncMock(return_value=graph_service)
    manage = AsyncMock()
    default_model = "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"
    monkeypatch.setattr(graph_router, "_get_graph_service", lookup)
    monkeypatch.setattr(graph_router, "require_knowledge_base_manage", manage)
    monkeypatch.setattr(graph_router, "default_chat_model_spec", AsyncMock(return_value=default_model))

    response = TestClient(_app()).get(
        "/graph/paths",
        params={
            "kb_id": "kb-1",
            "query": "复杂电磁环境感知",
            "path_reranking_enabled": True,
        },
    )

    assert response.status_code == 200, response.text
    graph_router.default_chat_model_spec.assert_awaited_once_with(None)
    manage.assert_awaited_once()
    lookup.assert_awaited_once_with("kb-1")
    assert graph_service.discover_paths.await_args.kwargs["path_reranking"] == {
        "enabled": True,
        "model_spec": default_model,
        "strict": False,
    }


def test_multihop_narrative_uses_project_model_and_explicit_direction(monkeypatch):
    """多跳撰述复用项目模型并保持与创新预测独立的特征契约。"""
    graph_service = SimpleNamespace(
        discover_paths=AsyncMock(
            return_value={"mode": "entity_expansion", "paths": [], "summary": {}, "query_plan": {}}
        )
    )
    default_model = "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"
    monkeypatch.setattr(graph_router, "_get_graph_service", AsyncMock(return_value=graph_service))
    monkeypatch.setattr(graph_router, "require_knowledge_base_manage", AsyncMock())
    monkeypatch.setattr(graph_router, "default_chat_model_spec", AsyncMock(return_value=default_model))

    response = TestClient(_app()).get(
        "/graph/paths",
        params={
            "kb_id": "kb-1",
            "query": "分布式孔径能力扩展",
            "mode": "bottom_up",
            "narrative_enabled": True,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["feature_kind"] == "multi_hop_retrieval"
    assert response.json()["data"]["discovery_mode"] == "bottom_up"
    assert response.json()["data"]["narrative_provenance"]["status"] == "no_evidence"
    graph_router.default_chat_model_spec.assert_awaited_once_with(None)
    assert graph_service.discover_paths.await_args.kwargs["mode"] == "entity_expansion"


def test_path_reranking_strict_and_non_strict_options_reach_graph_service(monkeypatch):
    """严格与降级策略必须原样传到封闭候选重排器。"""
    graph_service = SimpleNamespace(discover_paths=AsyncMock(return_value={"paths": [], "summary": {}}))
    monkeypatch.setattr(graph_router, "_get_graph_service", AsyncMock(return_value=graph_service))
    monkeypatch.setattr(graph_router, "require_knowledge_base_manage", AsyncMock())
    client = TestClient(_app())

    for strict in (False, True):
        response = client.get(
            "/graph/paths",
            params={
                "kb_id": "kb-1",
                "query": "宽带射频抗干扰",
                "path_reranking_enabled": True,
                "path_reranking_model_spec": "local:military-chat",
                "path_reranking_strict": strict,
            },
        )
        assert response.status_code == 200, response.text

    calls = graph_service.discover_paths.await_args_list
    assert calls[0].kwargs["path_reranking"] == {
        "enabled": True,
        "model_spec": "local:military-chat",
        "strict": False,
    }
    assert calls[1].kwargs["path_reranking"] == {
        "enabled": True,
        "model_spec": "local:military-chat",
        "strict": True,
    }


def test_path_reranking_options_reach_innovation_and_solution_services(monkeypatch):
    """创新发现和方案生成共用相同的受约束路径重排配置。"""
    innovation = AsyncMock(return_value={"candidates": []})
    solution = AsyncMock(return_value={"solution": {}})
    monkeypatch.setattr(graph_router, "_get_graph_service", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        graph_router,
        "KnowledgeGraphInnovationService",
        lambda **_kwargs: SimpleNamespace(discover=innovation),
    )
    monkeypatch.setattr(
        graph_router,
        "KnowledgeGraphSolutionService",
        lambda **_kwargs: SimpleNamespace(generate=solution),
    )
    client = TestClient(_app(SimpleNamespace(uid="admin-1", id=1, role="admin")))
    options = {
        "path_reranking_enabled": True,
        "path_reranking_model_spec": "local:military-chat",
        "path_reranking_strict": True,
    }

    discovery_response = client.post(
        "/graph/databases/kb-1/innovation/discover",
        json={"query": "高超声速热防护", "discovery_mode": "top_down", **options},
    )
    solution_response = client.post(
        "/graph/databases/kb-1/innovation/solution",
        json={"query": "高超声速热防护", "discovery_mode": "top_down", **options},
    )

    assert discovery_response.status_code == 200, discovery_response.text
    assert solution_response.status_code == 200, solution_response.text
    expected = {"enabled": True, "model_spec": "local:military-chat", "strict": True}
    assert innovation.await_args.kwargs["path_reranking"] == expected
    assert solution.await_args.kwargs["path_reranking"] == expected


def test_innovation_and_solution_llm_stages_use_project_default(monkeypatch):
    """创新查询、重排、增强与方案生成共享项目默认模型。"""
    innovation = AsyncMock(return_value={"candidates": []})
    solution = AsyncMock(return_value={"solution": {}})
    default_model = "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"
    monkeypatch.setattr(graph_router, "default_chat_model_spec", AsyncMock(return_value=default_model))
    monkeypatch.setattr(graph_router, "_get_graph_service", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        graph_router,
        "KnowledgeGraphInnovationService",
        lambda **_kwargs: SimpleNamespace(discover=innovation),
    )
    monkeypatch.setattr(
        graph_router,
        "KnowledgeGraphSolutionService",
        lambda **_kwargs: SimpleNamespace(generate=solution),
    )
    client = TestClient(_app(SimpleNamespace(uid="admin-1", id=1, role="admin")))

    discovery_response = client.post(
        "/graph/databases/kb-1/innovation/discover",
        json={
            "query": "高超声速热防护",
            "discovery_mode": "top_down",
            "query_enhancement_enabled": True,
            "path_reranking_enabled": True,
            "innovation_llm_enabled": True,
            "innovation_llm_concurrency": 4,
        },
    )
    solution_response = client.post(
        "/graph/databases/kb-1/innovation/solution",
        json={
            "query": "高超声速热防护",
            "discovery_mode": "top_down",
            "llm_enabled": True,
            "query_enhancement_enabled": True,
            "path_reranking_enabled": True,
        },
    )

    assert discovery_response.status_code == 200, discovery_response.text
    assert solution_response.status_code == 200, solution_response.text
    assert graph_router.default_chat_model_spec.await_count == 2
    assert innovation.await_args.kwargs["query_enhancement"]["model_spec"] == default_model
    assert innovation.await_args.kwargs["path_reranking"]["model_spec"] == default_model
    assert innovation.await_args.kwargs["llm_enhancement"]["model_spec"] == default_model
    assert innovation.await_args.kwargs["llm_enhancement"]["concurrency_count"] == 4
    assert solution.await_args.kwargs["model_spec"] == default_model
    assert solution.await_args.kwargs["query_enhancement"]["model_spec"] == default_model
    assert solution.await_args.kwargs["path_reranking"]["model_spec"] == default_model
