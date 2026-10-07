"""以平台模型凭据适配器启动旧研究队列，保留既有任务执行协议。"""

import sys

from equipment_deep_research.providers.platform_access import (
    configure_model_resolver,
    configure_research_knowledge_tool_factory,
)
from platform_core.services.equipment_model_adapter import equipment_model_profiles, resolve_managed_equipment_model
from platform_core.services.equipment_research_knowledge import PlatformResearchKnowledgeResolver


def main():
    """按队列类型启动工作进程。"""
    configure_model_resolver(resolve_managed_equipment_model, equipment_model_profiles)
    kind, *args = sys.argv[1:]
    if kind == "research":
        from equipment_deep_research.interfaces.worker import main as worker_main
        knowledge_tool_factory = PlatformResearchKnowledgeResolver()
        configure_research_knowledge_tool_factory(knowledge_tool_factory)
        try:
            return worker_main(args)
        finally:
            configure_research_knowledge_tool_factory(None)
            knowledge_tool_factory.close()
    elif kind == "query":
        from equipment_deep_research.query_library.cli import main as worker_main
    else:
        raise ValueError("未知装备研究队列")
    return worker_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
