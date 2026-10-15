"""把本轮实际生成的 outputs 文件登记为对话交付物。"""

import asyncio

from langchain.agents.middleware.types import AgentMiddleware
from platform_core.agents.backends.paths import runtime_user_data_path
from platform_core.workspace.workdir import Workdir


class ArtifactDeliveryMiddleware(AgentMiddleware):
    """比较运行前后文件快照，补齐模型遗漏的交付登记。"""

    def __init__(self):
        self._before: dict[str, tuple] = {}

    def _snapshot(self, context) -> dict[str, tuple]:
        """仅扫描当前用户当前 Project 的最终成果目录，不跟随符号链接。"""
        workdir = Workdir.open_existing(context.uid, context.workdir_relative_path)
        output_root = workdir.resolve_path("/outputs")
        try:
            entries = workdir.workspace.search_authorized_tree(
                output_root,
                "",
                include_directories=False,
                exclude_directories=frozenset({"large_tool_results", "conversation_history"}),
                exclude_hidden=True,
                max_results=500,
                max_directories=100,
            )
        except FileNotFoundError:
            return {}
        return {
            runtime_user_data_path(item["path"]): (item["size"], item["modified_at"])
            for item in entries
            if not item["name"].startswith(".")
        }

    async def abefore_agent(self, state, runtime):
        """记录本次运行开始前已有成果。"""
        self._before = await asyncio.to_thread(self._snapshot, runtime.context)

    async def aafter_agent(self, state, runtime):
        """只交付真实新增或修改的成果，保留显式交付的文件。"""
        after = await asyncio.to_thread(self._snapshot, runtime.context)
        artifacts = [path for path, metadata in after.items() if self._before.get(path) != metadata]
        return {"artifacts": artifacts} if artifacts else None
