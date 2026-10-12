"""智能对话与研究子智能体共用的论文检索工具。"""

from typing import Annotated, Literal

from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field

from platform_core.agents.toolkits.registry import tool
from platform_core.services.academic_retrieval_service import AcademicRetrievalService


class AcademicSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="简短公开科研关键词；禁止发送完整会话或内部文档")
    mode: Literal["topic", "title"] = Field(default="topic", description="主题发现或已知论文标题定位")
    limit: int = Field(default=10, ge=1, le=20)
    page: int = Field(default=1, ge=1, le=10, description="从 1 开始的结果页码；标题搜索最多 10 页")
    order: Literal["relevance", "recent", "cited"] = Field(
        default="relevance", description="相关性优先，或按年份/被引数量排序"
    )


class AcademicPapersInput(BaseModel):
    paper_ids: list[Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S+$")]] = Field(
        min_length=1, max_length=10, description="实际检索或用户提供的 AMiner 论文 ID"
    )
    full_abstract: bool = Field(default=True, description="仅对拟引用论文读取完整摘要；false 使用免费部分摘要")


class AcademicReferencesInput(BaseModel):
    paper_id: str = Field(min_length=1, max_length=128, description="需要追溯的核心论文 ID")
    limit: int = Field(default=20, ge=1, le=50)


@tool(
    category="buildin",
    tags=["搜索", "论文"],
    display_name="论文搜索",
    description=(
        "通过 AMiner 发现论文并返回题录、DOI、来源和部分摘要。科研技术问题优先使用；"
        "仅发送公开科研关键词，不发送会话或内部文档。"
    ),
    args_schema=AcademicSearchInput,
)
async def academic_search(
    query: str, runtime: ToolRuntime, mode: str = "topic", limit: int = 10, order: str = "relevance", page: int = 1
) -> dict:
    """按主题或已知标题检索公开论文。"""
    return await AcademicRetrievalService(runtime.context).search(query, mode=mode, limit=limit, order=order, page=page)


@tool(
    category="buildin",
    tags=["搜索", "论文"],
    display_name="论文摘要与详情",
    description="批量补齐选定论文题录，按需获取完整摘要。请先筛选拟引用论文再调用；摘要不是全文，不能声称已阅读全文。",
    args_schema=AcademicPapersInput,
)
async def academic_get_papers(paper_ids: list[str], runtime: ToolRuntime, full_abstract: bool = True) -> dict:
    """为选定论文补充可追溯摘要证据。"""
    return await AcademicRetrievalService(runtime.context).get_papers(paper_ids, full_abstract=full_abstract)


@tool(
    category="buildin",
    tags=["搜索", "论文"],
    display_name="论文参考文献",
    description="获取核心论文引用的参考文献，按需扩展一层。不是后续引用者列表，不递归抓取文献树；与其他论文工具共享本轮预算。",
    args_schema=AcademicReferencesInput,
)
async def academic_get_references(paper_id: str, runtime: ToolRuntime, limit: int = 20) -> dict:
    """追溯核心论文的原始参考文献。"""
    return await AcademicRetrievalService(runtime.context).get_references(paper_id, limit=limit)
