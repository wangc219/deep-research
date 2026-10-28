"""对比真实 AMiner REST 与官方 MCP 的相同论文请求。"""

import asyncio
import json
import statistics
import time
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from platform_core.config.options import aminer_api_opts
from platform_core.services.aminer_client import AMinerClient, normalize_paper
from platform_core.storage.postgres.manager import pg_manager


def unwrap(result):
    """读取 MCP TextContent 中的供应商 JSON。"""
    if isinstance(result, list):
        text = next(x["text"] for x in result if isinstance(x, dict) and x.get("type") == "text")
        return json.loads(text)
    if isinstance(result, str):
        return json.loads(result)
    return result


async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            config = await aminer_api_opts.get(db)
        token = config["api_key"].strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        rest = AMinerClient(config)
        client = MultiServerMCPClient(
            {
                "aminer": {
                    "transport": "streamable_http",
                    "url": "https://mcp.aminer.cn/mcp",
                    "headers": {"Authorization": "Bearer " + token},
                    "timeout": 20,
                    "sse_read_timeout": 60,
                }
            }
        )
        tools = {t.name: t for t in await client.get_tools()}
        rag_title = "Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach"
        cases = [
            (
                "topic",
                "search",
                {"keyword": "FlashAttention", "page": 0, "size": 5},
                "search_paper",
                {"title": "", "keyword": "FlashAttention", "page": 0, "size": 5},
            ),
            (
                "title",
                "title_search",
                {
                    "title": rag_title,
                    "page": 1,
                    "size": 3,
                },
                "search_paper_by_title",
                {
                    "title": rag_title,
                    "page": 1,
                    "size": 3,
                },
            ),
            (
                "abstract",
                "detail",
                {"id": "629435a25aee126c0f2fecb3"},
                "get_paper_detail",
                {"id": "629435a25aee126c0f2fecb3"},
            ),
        ]
        records = []
        for name, endpoint, rest_payload, tool_name, mcp_payload in cases:
            for repetition in range(3):
                for mode in ("rest", "mcp") if repetition % 2 == 0 else ("mcp", "rest"):
                    started = time.monotonic()
                    if mode == "rest":
                        result = await rest.request(endpoint, rest_payload)
                    else:
                        result = unwrap(await tools[tool_name].ainvoke(mcp_payload))
                    record = {
                        "case": name,
                        "transport": mode,
                        "repetition": repetition + 1,
                        "seconds": round(time.monotonic() - started, 4),
                        "code": result.get("code"),
                        "success": result.get("success"),
                        "total": result.get("total"),
                        "provider_log_id": result.get("log_id"),
                        "papers": [normalize_paper(p) for p in result.get("data") or [] if isinstance(p, dict)],
                    }
                    records.append(record)
                    print(
                        json.dumps(
                            {k: v for k, v in record.items() if k != "papers"}
                            | {
                                "returned": len(record["papers"]),
                                "abstract_characters": [len(x["content"]) for x in record["papers"]],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
        extras = []
        for name, arguments in [
            ("search_person", {"name": "Tri Dao", "size": 3}),
            ("search_patent", {"query": "lithium battery", "size": 3}),
            ("search_organization", {"orgs": ["清华大学"]}),
        ]:
            started = time.monotonic()
            result = unwrap(await tools[name].ainvoke(arguments))
            extras.append(
                {
                    "tool": name,
                    "arguments": arguments,
                    "seconds": round(time.monotonic() - started, 4),
                    "result": result,
                }
            )
            print(
                json.dumps(
                    {
                        "extra_tool": name,
                        "code": result.get("code"),
                        "success": result.get("success"),
                        "returned": len(result.get("data") or []),
                    }
                ),
                flush=True,
            )
        summaries = []
        for name, *_ in cases:
            r = [x for x in records if x["case"] == name and x["transport"] == "rest"]
            m = [x for x in records if x["case"] == name and x["transport"] == "mcp"]
            summaries.append(
                {
                    "case": name,
                    "rest_median_seconds": statistics.median(x["seconds"] for x in r),
                    "mcp_median_seconds": statistics.median(x["seconds"] for x in m),
                    "identical_paper_ids": [[p["id"] for p in x["papers"]] for x in r]
                    == [[p["id"] for p in x["papers"]] for x in m],
                    "identical_abstracts": [[p["content"] for p in x["papers"]] for x in r]
                    == [[p["content"] for p in x["papers"]] for x in m],
                }
            )
        out = Path("/app/outputs/aminer-mcp-20261019")
        out.mkdir(parents=True, exist_ok=True)
        (out / "transport-comparison.json").write_text(
            json.dumps(
                {
                    "mock": False,
                    "repetitions": 3,
                    "summary": summaries,
                    "requests": records,
                    "additional_mcp_capabilities": extras,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(json.dumps({"summary": summaries}, ensure_ascii=False))
    finally:
        await pg_manager.close()


asyncio.run(main())
