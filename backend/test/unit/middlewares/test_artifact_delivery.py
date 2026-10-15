from types import SimpleNamespace

import pytest

from platform_core.agents.middlewares.artifacts import ArtifactDeliveryMiddleware
from platform_core.agents.toolkits.service import resolve_configured_runtime_tools
from platform_core.workspace.workdir import Workdir


@pytest.mark.asyncio
async def test_delivers_only_created_or_modified_real_output_files(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEP_RESEARCH_USER_DATA_DIR", str(tmp_path))
    root = tmp_path / "shared/user-1/workspace/projects/test"
    outputs = root / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "unchanged.md").write_text("old")
    (outputs / "edited.md").write_text("old")
    runtime = SimpleNamespace(context=SimpleNamespace(uid="user-1", workdir_relative_path="projects/test"))
    middleware = ArtifactDeliveryMiddleware()
    await middleware.abefore_agent({}, runtime)
    (outputs / "report.md").write_text("new")
    (outputs / "edited.md").write_text("edited report")
    (outputs / "hidden.md").symlink_to(tmp_path / "secret")
    (outputs / "large_tool_results").mkdir()
    (outputs / "large_tool_results/tool.txt").write_text("internal")
    (outputs / ".temporary.txt").write_text("incomplete")
    update = await middleware.aafter_agent({}, runtime)
    assert set(update["artifacts"]) == {
        "/home/gem/user-data/projects/test/outputs/report.md",
        "/home/gem/user-data/projects/test/outputs/edited.md",
    }
    assert Workdir.open_existing("user-1", "projects/test").read_file("/outputs/report.md", 100) == b"new"


@pytest.mark.asyncio
async def test_no_outputs_does_not_claim_delivery(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEP_RESEARCH_USER_DATA_DIR", str(tmp_path))
    (tmp_path / "shared/user-1/workspace/projects/test").mkdir(parents=True)
    runtime = SimpleNamespace(context=SimpleNamespace(uid="user-1", workdir_relative_path="projects/test"))
    middleware = ArtifactDeliveryMiddleware()
    await middleware.abefore_agent({}, runtime)
    assert await middleware.aafter_agent({}, runtime) is None


@pytest.mark.asyncio
async def test_delivery_tool_available_without_selected_tools_or_skills():
    context = SimpleNamespace(tools=[], mcps=[], _skill_runtime_snapshot={})
    tools = await resolve_configured_runtime_tools(context)
    assert "present_artifacts" in {tool.name for tool in tools}


@pytest.mark.asyncio
async def test_graph_final_state_contains_files_without_model_delivery_call(monkeypatch, tmp_path):
    """真实 Agent graph 应将终态输出快照传入 artifacts reducer。"""
    from langchain.agents import create_agent
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from platform_core.agents.state import BaseState

    monkeypatch.setenv("DEEP_RESEARCH_USER_DATA_DIR", str(tmp_path))
    root = tmp_path / "shared/user-1/workspace/projects/test"
    root.mkdir(parents=True)

    class WriteReportMiddleware(AgentMiddleware):
        def before_model(self, state, runtime):
            (root / "outputs").mkdir(exist_ok=True)
            (root / "outputs/report.md").write_text("# Report")

    graph = create_agent(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="Saved")])),
        middleware=[ArtifactDeliveryMiddleware(), WriteReportMiddleware()],
        state_schema=BaseState,
    )
    state = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Create report"}]},
        context=SimpleNamespace(uid="user-1", workdir_relative_path="projects/test"),
    )
    assert state["artifacts"] == ["/home/gem/user-data/projects/test/outputs/report.md"]
