"""云端候选/正式镜像的真实三渠道长尾检索验收。"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit

from platform_core.agents.toolkits.buildin.academic import _merge_parallel_research_results
from platform_core.agents.toolkits.buildin.tools import execute_public_web_search
from platform_core.config.options import aminer_api_opts
from platform_core.services.academic_retrieval_service import DirectAcademicRetrievalService
from platform_core.storage.postgres.manager import pg_manager


CASES = [
    {
        "name": "rare-altermagnetism",
        "query": "Experimental evidence for altermagnetism and spin splitting",
        "aliases": ["altermagnetism", "spin splitting"],
    },
    {
        "name": "rare-moire-exciton",
        "query": "Moiré excitons in semiconductor heterobilayers",
        "aliases": ["moiré", "moire", "heterobilayer"],
    },
    {
        "name": "cross-hydrodynamic-graphene",
        "query": "Hydrodynamic electron flow in graphene",
        "aliases": ["hydrodynamic", "viscous", "graphene"],
    },
    {
        "name": "rare-photonic-time-crystal",
        "query": "photonic time crystal nonreciprocal microwave amplification",
        "aliases": ["photonic time crystal", "nonreciprocal", "microwave"],
    },
    {
        "name": "mixed-language-altermagnetism",
        "query": "交错磁性 altermagnetism 自旋劈裂 实验证据",
        "aliases": ["altermagnetism", "交错磁性", "自旋劈裂"],
    },
]


def _matches(item: dict, aliases: list[str]) -> bool:
    haystack = " ".join(str(item.get(key) or "") for key in ("title", "content", "url")).casefold()
    return any(alias.casefold() in haystack for alias in aliases)


def _summary(case: dict, web: dict, academic: dict, merged: dict, elapsed: float) -> dict:
    results = merged.get("results") or []
    domains = {
        (urlsplit(str(item.get("url") or "")).hostname or "").removeprefix("www.")
        for item in results
        if item.get("url")
    }
    domains.discard("")
    top = results[:10]
    return {
        "case": case["name"],
        "query": case["query"],
        "seconds": round(elapsed, 3),
        "status": merged.get("status"),
        "search_mode": merged.get("search_mode"),
        "completed_providers": merged.get("completed_providers") or [],
        "attempted_providers": merged.get("attempted_providers") or [],
        "partial_failures": merged.get("partial_failures") or [],
        "query_profile": merged.get("query_profile") or {},
        "channel_summary": merged.get("channel_summary") or {},
        "web_status": web.get("status"),
        "aminer_status": academic.get("aminer_status") or academic.get("status"),
        "distinct_domains": len(domains),
        "authoritative_sources": sum(item.get("source_tier") == "authoritative" for item in results),
        "abstract_level_papers": sum(item.get("content_level") == "abstract" for item in results),
        "top10_alias_matches": sum(_matches(item, case["aliases"]) for item in top),
        "top10": [
            {
                key: item.get(key)
                for key in (
                    "title",
                    "url",
                    "providers",
                    "search_engines",
                    "source_tier",
                    "content_level",
                    "cross_channel_match",
                )
            }
            for item in top
        ],
    }


async def _run_case(case: dict, academic_service: DirectAcademicRetrievalService) -> dict:
    started = time.monotonic()
    web_task = asyncio.to_thread(
        execute_public_web_search,
        case["query"],
        count=10,
        required_term_groups=[case["aliases"]],
        fusion_strategy="parallel",
    )
    academic_task = academic_service.search(
        case["query"],
        mode="semantic",
        limit=10,
        any_terms=case["aliases"],
    )
    web, academic = await asyncio.gather(web_task, academic_task)
    merged = _merge_parallel_research_results(case["query"], web, academic, count=10)
    return _summary(case, web, academic, merged, time.monotonic() - started)


async def _hard_constraint_probe() -> dict:
    result = await asyncio.to_thread(
        execute_public_web_search,
        "altermagnetism experimental evidence",
        count=10,
        sites=["nature.com"],
        block_hosts=["arxiv.org"],
        required_terms=["altermagnetism"],
        fusion_strategy="parallel",
    )
    rows = result.get("results") or []
    leaks = []
    for item in rows:
        host = (urlsplit(str(item.get("url") or "")).hostname or "").casefold()
        text = " ".join(str(item.get(key) or "") for key in ("title", "content", "url")).casefold()
        if not (host == "nature.com" or host.endswith(".nature.com")) or host == "arxiv.org" or host.endswith(
            ".arxiv.org"
        ) or "altermagnetism" not in text:
            leaks.append(item.get("url"))
    return {
        "status": result.get("status"),
        "returned": len(rows),
        "leaks": leaks,
        "attempted_providers": result.get("attempted_providers") or [],
        "partial_failures": result.get("partial_failures") or [],
    }


async def main() -> None:
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            config = await aminer_api_opts.get(db)
        credentials = {"user_id": config.get("user_id", ""), "api_key": config.get("api_key", "")}
        academic_service = DirectAcademicRetrievalService(credentials)
        rows = []
        for case in CASES:
            row = await _run_case(case, academic_service)
            rows.append(row)
            print(json.dumps({"case_result": row}, ensure_ascii=False), flush=True)
        constraint = await _hard_constraint_probe()
        report = {
            "cases": rows,
            "hard_constraint_probe": constraint,
            "summary": {
                "cases": len(rows),
                "all_three_attempted": all(
                    {"open-websearch", "searxng", "aminer"}.issubset(set(row["attempted_providers"])) for row in rows
                ),
                "cases_with_three_completed": sum(
                    {"open-websearch", "searxng", "aminer"}.issubset(set(row["completed_providers"])) for row in rows
                ),
                "total_unique_candidates": sum(row["channel_summary"].get("unique_candidates", 0) for row in rows),
                "total_cross_channel_matches": sum(
                    row["channel_summary"].get("cross_channel_matches", 0) for row in rows
                ),
                "top10_alias_precision": round(
                    sum(row["top10_alias_matches"] for row in rows)
                    / max(1, sum(min(10, row["channel_summary"].get("unique_candidates", 0)) for row in rows)),
                    3,
                ),
                "hard_constraint_leaks": len(constraint["leaks"]),
            },
        }
        print(json.dumps({"final_report": report}, ensure_ascii=False), flush=True)
    finally:
        await pg_manager.close()


asyncio.run(main())
