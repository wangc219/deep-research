"""宿主注入的平台访问端口；领域运行时不反向依赖宿主实现。"""

from collections.abc import Callable, Sequence
from typing import Any

from equipment_deep_research.application.dto import RunView
from equipment_deep_research.application.ports import ResearchKnowledgeToolFactory
from equipment_deep_research.contracts.tools import ToolDefinition

_resolver: Callable[[str], dict[str, Any]] | None = None
_catalog: Callable[[], dict[str, Any]] | None = None
_research_knowledge_tool_factory: ResearchKnowledgeToolFactory | None = None


def configure_model_resolver(
    resolver: Callable[[str], dict[str, Any]],
    catalog: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """由平台组合根安装凭据解析器。"""
    global _resolver, _catalog
    _resolver = resolver
    _catalog = catalog


def platform_model_profiles() -> dict[str, Any] | None:
    """只返回平台公开模型目录，不暴露凭据。"""
    return _catalog() if _catalog is not None else None


def resolve_platform_model(spec: str) -> dict[str, Any]:
    """解析失败时明确终止，不回退到环境中的其他账户。"""
    if _resolver is None:
        raise ValueError("平台模型解析器未初始化")
    try:
        return _resolver(spec)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc


def resolve_platform_execution(execution: dict[str, Any]) -> dict[str, Any] | None:
    """平台宿主接管真实任务，历史任务使用平台默认模型；独立运行保持原行为。"""
    if execution.get("mode") == "fake":
        return None
    spec = str(execution.get("model_spec") or "")
    if not spec and _resolver is None:
        return None
    return resolve_platform_model(spec)


def configure_research_knowledge_tool_factory(
    factory: ResearchKnowledgeToolFactory | None,
) -> None:
    """由平台组合根安装按 owner 绑定、调用时鉴权的知识工具工厂。"""
    global _research_knowledge_tool_factory
    _research_knowledge_tool_factory = factory


def platform_research_knowledge_tools(
    run: RunView,
    event_sink: Callable[[str, dict], None] | None = None,
) -> tuple[ToolDefinition, ...]:
    """独立运行未安装宿主端口时不暴露平台知识工具。"""
    if _research_knowledge_tool_factory is None:
        return ()
    tools: Sequence[ToolDefinition] = _research_knowledge_tool_factory(
        run,
        event_sink,
    )
    return tuple(tools)


_observer_factory: Callable[..., Any] | None = None


def configure_model_observer(factory: Callable[..., Any]) -> None:
    """宿主注入用量持久化端口，领域不依赖统计数据库。"""
    global _observer_factory
    _observer_factory = factory


def model_call_observer(**identity: Any) -> Any:
    """创建绑定当前模型身份的调用观察器；独立运行无需统计宿主。"""
    return _observer_factory(**identity) if _observer_factory else None
