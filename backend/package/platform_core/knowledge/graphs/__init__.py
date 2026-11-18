"""知识图谱领域包；具体基础设施适配器按需加载。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .milvus_graph_service import MilvusGraphService

__all__ = ["MilvusGraphService"]


def __getattr__(name: str):
    if name == "MilvusGraphService":
        from .milvus_graph_service import MilvusGraphService

        return MilvusGraphService
    raise AttributeError(name)
