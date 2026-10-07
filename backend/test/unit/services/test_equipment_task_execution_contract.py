"""平台任务传入领域执行器的配置契约，避免适配过程丢失用户选择。"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from platform_core.services import equipment_research_task as task


@pytest.mark.asyncio
async def test_platform_research_cancellation_reaps_processes_before_thread_release(
    monkeypatch,
):
    """取消 Durable Task 时必须先终止本 Run 子进程，再等待领域线程退出。"""

    started = threading.Event()
    released = threading.Event()
    thread_finished = threading.Event()
    cleanup_calls: list[tuple[str, float]] = []

    def run_domain(_run, *, resume=False):
        assert resume is True
        started.set()
        assert released.wait(2)
        thread_finished.set()
        return {"result": {}}

    def terminate(run_id: str, *, grace_seconds: float):
        cleanup_calls.append((run_id, grace_seconds))
        released.set()
        return SimpleNamespace(
            orphan_count=2,
            terminated_count=2,
            forced_count=0,
        )

    monkeypatch.setattr(task, "_run_domain", run_domain)
    monkeypatch.setattr(
        "equipment_deep_research.runtime_process_registry.terminate_run_process_groups",
        terminate,
    )
    execution = asyncio.create_task(
        task._run_domain_cancellable(SimpleNamespace(id="run-cancel"), resume=True)
    )
    assert await asyncio.to_thread(started.wait, 1)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    assert cleanup_calls == [("run-cancel", 3.0)]
    assert thread_finished.is_set()


def test_platform_research_runs_overlap_without_process_environment_lock(monkeypatch, tmp_path):
    """两个平台 Run 应在同一 Worker 进程内并行，且显式模型参数不串线。"""

    active = 0
    max_active = 0
    observed: dict[str, str] = {}
    guard = threading.Lock()
    monkeypatch.setattr(task, "user_workdir_host_dir", lambda _uid, _workdir: tmp_path)
    monkeypatch.setattr(
        "equipment_deep_research.application.factory.build_application_service",
        lambda *_: SimpleNamespace(repository=SimpleNamespace(save=lambda _view: None)),
    )

    class Runner:
        def __init__(self, **_kwargs):
            pass

        def run(self, *, run_id, provider_model=None, **_kwargs):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
                observed[run_id] = provider_model
            time.sleep(0.08)
            with guard:
                active -= 1
            return {"run_id": run_id, "model": provider_model}

    class KnowledgeToolFactory:
        def __call__(self, _view, _event_sink):
            return ()

        def close(self):
            pass

    monkeypatch.setattr("equipment_deep_research.orchestration.runner.DeepResearchRunner", Runner)
    monkeypatch.setattr(
        "platform_core.services.equipment_research_knowledge.PlatformResearchKnowledgeResolver",
        KnowledgeToolFactory,
    )
    monkeypatch.setattr(
        "platform_core.services.equipment_model_adapter.bind_equipment_execution",
        lambda payload: {
            "model_spec": payload["model_spec"],
            "execution": {"mode": "real", "model_spec": payload["model_spec"]},
            "overlay": {"EQUIPMENT_DR_MODEL": payload["model_spec"]},
            "runner": {
                "mode": "real",
                "provider_name": "platform",
                "provider_model": payload["model_spec"],
                "provider_base_url": f"https://{payload['model_spec']}.example/v1",
                "provider_api_key_env": "EQUIPMENT_DR_API_KEY",
                "provider_api_key": f"secret-{payload['model_spec']}",
            },
        },
    )

    def make_run(run_id: str, model_spec: str):
        return SimpleNamespace(
            id=run_id,
            owner_uid="owner",
            project_id="project",
            topic=run_id,
            research_route="auto",
            payload={
                "workdir_path": "projects/shared",
                "directory_mode": "linked",
                "model_spec": model_spec,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda run: task._run_domain(run)["result"],
                [make_run("run-a", "model-a"), make_run("run-b", "model-b")],
            )
        )

    assert max_active == 2
    assert observed == {"run-a": "model-a", "run-b": "model-b"}
    assert {item["model"] for item in results} == {"model-a", "model-b"}


def test_platform_task_preserves_selected_execution_contract(monkeypatch, tmp_path):
    """显式配置与知识工具范围必须抵达 Runner，正文不得注入。"""
    saved = []
    factory_lifecycle = []
    monkeypatch.setattr(task, "user_workdir_host_dir", lambda uid, workdir: tmp_path)
    monkeypatch.setattr(
        "equipment_deep_research.application.factory.build_application_service",
        lambda *_: SimpleNamespace(repository=SimpleNamespace(save=saved.append)),
    )

    class Runner:
        def __init__(self, **kwargs):
            pass

        def run(
            self,
            *,
            resume=False,
            execution_profile_id="legacy_v1",
            interaction_mode="expert",
            discovery_branch="auto",
            report_template_mode="three_layer_nine_item",
            analyst_confirmed=False,
            project_id="",
            supplemental_information="",
            research_knowledge_tools=(),
            **kwargs,
        ):
            return {
                "profile": execution_profile_id,
                "interaction": interaction_mode,
                "branch": discovery_branch,
                "template": report_template_mode,
                "confirmed": analyst_confirmed,
                "project": project_id,
                "supplemental": supplemental_information,
                "research_knowledge_tools": research_knowledge_tools,
                "resume": resume,
            }

    class KnowledgeToolFactory:
        def __call__(self, view, event_sink):
            factory_lifecycle.append(("bound", view, event_sink))
            return ("query-kb-tool",)

        def close(self):
            factory_lifecycle.append(("closed",))

    monkeypatch.setattr("equipment_deep_research.orchestration.runner.DeepResearchRunner", Runner)
    monkeypatch.setattr(
        "platform_core.services.equipment_research_knowledge.PlatformResearchKnowledgeResolver",
        KnowledgeToolFactory,
    )
    run = SimpleNamespace(
        id="contract-run",
        owner_uid="contract-user",
        project_id="contract-project",
        topic="通用软件契约测试",
        research_route="auto",
        payload={
            "workdir_path": "projects/contract",
            "directory_mode": "linked",
            "execution": {"mode": "fake"},
            "execution_profile_id": "winning_swarm_dynamic_v2",
            "interaction_mode": "autonomous",
            "discovery_branch": "A",
            "report_template_mode": "project_argument_v1",
            "analyst_confirmed": True,
            "supplemental_information": "既有企业研究约束。",
            "knowledge_enabled": True,
            "knowledge_ids": ["kb-technology", "kb-technology"],
        },
    )
    result = task._run_domain(run)["result"]
    assert result == {
        "profile": "winning_swarm_dynamic_v2",
        "interaction": "autonomous",
        "branch": "A",
        "template": "project_argument_v1",
        "confirmed": True,
        "project": "contract-project",
        "supplemental": "既有企业研究约束。",
        "research_knowledge_tools": ("query-kb-tool",),
        "resume": False,
    }
    assert saved[0].execution_profile_id == result["profile"]
    assert saved[0].report_template_mode == result["template"]
    assert saved[0].supplemental_information == "既有企业研究约束。"
    assert saved[0].owner_uid == "contract-user"
    assert saved[0].knowledge_enabled is True
    assert saved[0].knowledge_ids == ["kb-technology"]
    assert factory_lifecycle[0][0] == "bound"
    assert factory_lifecycle[-1] == ("closed",)


def test_platform_failed_run_resume_reaches_domain_runner(monkeypatch, tmp_path):
    """平台恢复动作必须真正启用领域检查点恢复，而不是从头运行。"""
    observed = []
    (tmp_path / "outputs" / "equipment-research" / "resume-run").mkdir(parents=True)
    monkeypatch.setattr(task, "user_workdir_host_dir", lambda uid, workdir: tmp_path)
    monkeypatch.setattr(
        "equipment_deep_research.application.factory.build_application_service",
        lambda *_: SimpleNamespace(repository=SimpleNamespace(save=lambda _view: None)),
    )

    class Runner:
        def __init__(self, **_kwargs):
            pass

        def run(self, *, resume=False, **_kwargs):
            observed.append(resume)
            return {"resumed": resume}

    class KnowledgeToolFactory:
        def __call__(self, _view, _event_sink):
            return ()

        def close(self):
            pass

    monkeypatch.setattr("equipment_deep_research.orchestration.runner.DeepResearchRunner", Runner)
    monkeypatch.setattr(
        "platform_core.services.equipment_research_knowledge.PlatformResearchKnowledgeResolver",
        KnowledgeToolFactory,
    )
    run = SimpleNamespace(
        id="resume-run",
        owner_uid="owner",
        project_id="project",
        topic="恢复任务",
        research_route="auto",
        payload={
            "workdir_path": "projects/resume",
            "directory_mode": "linked",
            "execution": {"mode": "fake"},
        },
    )

    assert task._run_domain(run, resume=True)["result"] == {"resumed": True}
    assert observed == [True]


def test_platform_resume_without_checkpoint_starts_fresh(monkeypatch, tmp_path):
    """启动前失败的 Run 没有检查点，恢复操作应自动转为全新执行。"""
    observed = []
    monkeypatch.setattr(task, "user_workdir_host_dir", lambda uid, workdir: tmp_path)
    monkeypatch.setattr(
        "equipment_deep_research.application.factory.build_application_service",
        lambda *_: SimpleNamespace(repository=SimpleNamespace(save=lambda _view: None)),
    )

    class Runner:
        def __init__(self, **_kwargs):
            pass

        def run(self, *, resume=False, **_kwargs):
            observed.append(resume)
            return {"resumed": resume}

    class KnowledgeToolFactory:
        def __call__(self, _view, _event_sink):
            return ()

        def close(self):
            pass

    monkeypatch.setattr("equipment_deep_research.orchestration.runner.DeepResearchRunner", Runner)
    monkeypatch.setattr(
        "platform_core.services.equipment_research_knowledge.PlatformResearchKnowledgeResolver",
        KnowledgeToolFactory,
    )
    run = SimpleNamespace(
        id="fresh-run",
        owner_uid="owner",
        project_id="project",
        topic="启动前失败任务",
        research_route="auto",
        payload={
            "workdir_path": "projects/fresh",
            "directory_mode": "linked",
            "execution": {"mode": "fake"},
        },
    )

    assert task._run_domain(run, resume=True)["result"] == {"resumed": False}
    assert observed == [False]


def test_managed_research_workdir_is_materialized_when_missing(monkeypatch, tmp_path):
    """受平台管理的 Project 目录缺失时，研究任务应安全恢复目录。"""
    from platform_core.workspace import paths

    monkeypatch.setattr(paths, "get_user_data_dir", lambda: tmp_path)
    run = SimpleNamespace(
        owner_uid="owner",
        payload={
            "workdir_path": "projects/2026-09-22_20-50-41_06a3a154",
            "directory_mode": "managed",
        },
    )

    resolved = task.resolve_research_workdir(run)

    assert resolved.is_dir()


def test_linked_research_workdir_missing_is_not_created(monkeypatch, tmp_path):
    """外部关联目录缺失时必须明确失败，不能伪造一个空目录。"""
    from platform_core.workspace import paths

    monkeypatch.setattr(paths, "get_user_data_dir", lambda: tmp_path)
    paths.ensure_user_workspace("owner")
    run = SimpleNamespace(
        owner_uid="owner",
        payload={"workdir_path": "linked/external", "directory_mode": "linked"},
    )

    with pytest.raises(RuntimeError, match="linked Project Workdir 不存在"):
        task.resolve_research_workdir(run)

    assert not (paths.user_workspace_dir("owner") / "linked" / "external").exists()


def test_managed_research_workdir_rejects_symlink(monkeypatch, tmp_path):
    """managed 路径即使格式合法，也不能穿过符号链接。"""
    from platform_core.workspace import paths

    monkeypatch.setattr(paths, "get_user_data_dir", lambda: tmp_path)
    paths.ensure_user_workspace("owner")
    projects = paths.user_workspace_dir("owner") / "projects"
    projects.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    workdir_name = "2026-09-22_20-50-41_06a3a154"
    (projects / workdir_name).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="符号链接或非目录组件"):
        task.resolve_research_workdir(
            SimpleNamespace(
                owner_uid="owner",
                payload={
                    "workdir_path": f"projects/{workdir_name}",
                    "directory_mode": "managed",
                },
            )
        )
