"""随代码发布的固定远程 MCP 连接定义。"""

BUILTIN_MCP_SERVERS = {
    "aminer-official": {
        "name": "AMiner 学术数据",
        "transport": "streamable_http",
        "url": "https://mcp.aminer.cn/mcp",
        "description": (
            "AMiner 官方学者、专利、机构和期刊查询；复用模型设置中的 AMiner 凭证。"
            "论文搜索、完整摘要和参考文献优先使用内置论文工具，默认停用重复 MCP 工具。"
        ),
        "icon": "🎓",
        "tags": ["内置", "学术", "专利", "学者"],
        "timeout": 20,
        "sse_read_timeout": 60,
        "disabled_tools": [
            "search_paper",
            "search_paper_by_title",
            "get_paper_detail",
            "get_papers_info",
            "get_paper_citations",
        ],
    },
    "deepwiki-official": {
        "name": "DeepWiki",
        "transport": "streamable_http",
        "url": "https://mcp.deepwiki.com/mcp",
        "description": "查询公开 GitHub 仓库的文档、架构与代码，支持针对仓库提问。",
        "icon": "📚",
        "tags": ["内置", "代码", "文档"],
    },
}
