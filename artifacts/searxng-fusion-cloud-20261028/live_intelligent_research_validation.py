"""通过生产 HTTPS 的智能对话并行委派调研探索员，验证三渠道检索质量。"""

from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import delete, select

sys.path.insert(0, "/app/test")

from live_api_cleanup import (  # noqa: E402
    cleanup_test_chat_resources,
    make_test_conversation_metadata,
    make_test_conversation_title,
)
from platform_core.storage.postgres.manager import pg_manager  # noqa: E402
from platform_core.storage.postgres.models_business import (  # noqa: E402
    AcademicRetrievalCall,
    AgentEnv,
    AgentRun,
    Conversation,
    Department,
    Message,
    OperationLog,
    ToolCall,
    User,
    UserConfig,
)
from platform_core.utils.auth_utils import AuthUtils  # noqa: E402
from platform_core.workspace.paths import global_user_data_dir  # noqa: E402


OUT = Path("/app/outputs/searxng-live-intelligent-research-20261029.json")
BASE_URL = "https://www.deepquest.space"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
CASES = [
    {
        "name": "photonic-time-crystal",
        "query": "photonic time crystal nonreciprocal microwave amplification",
        "aliases": ["photonic time crystal", "nonreciprocal", "microwave"],
    },
    {
        "name": "moire-exciton",
        "query": "Moiré excitons in semiconductor heterobilayers",
        "aliases": ["moiré", "moire", "heterobilayer"],
    },
    {
        "name": "altermagnetism",
        "query": "Experimental evidence for altermagnetism and spin splitting",
        "aliases": ["altermagnetism", "spin splitting"],
    },
]


async def api(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.status_code != 200:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def parse_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def text_matches(item: dict, aliases: list[str]) -> bool:
    haystack = " ".join(str(item.get(key) or "") for key in ("title", "content", "url")).casefold()
    return any(alias.casefold() in haystack for alias in aliases)


def summarize_parallel_result(payload: dict, aliases: list[str]) -> dict:
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    provider_counts: Counter[str] = Counter()
    engine_counts: Counter[str] = Counter()
    for item in results:
        if not isinstance(item, dict):
            continue
        for provider in item.get("providers") or []:
            provider_counts[str(provider)] += 1
        for engine in item.get("search_engines") or []:
            engine_counts[str(engine)] += 1
    searxng_results = [
        item
        for item in results
        if isinstance(item, dict) and "searxng" in {str(value) for value in item.get("providers") or []}
    ]
    top = [item for item in results[:10] if isinstance(item, dict)]
    return {
        "status": payload.get("status"),
        "search_mode": payload.get("search_mode"),
        "query_profile": payload.get("query_profile") or {},
        "attempted_providers": payload.get("attempted_providers") or [],
        "completed_providers": payload.get("completed_providers") or [],
        "partial_failures": payload.get("partial_failures") or [],
        "channel_summary": payload.get("channel_summary") or {},
        "result_count": len(results),
        "provider_result_counts": dict(provider_counts),
        "engine_result_counts": dict(engine_counts),
        "searxng_result_count": len(searxng_results),
        "cross_channel_matches": sum(bool(item.get("cross_channel_match")) for item in results if isinstance(item, dict)),
        "top10_alias_matches": sum(text_matches(item, aliases) for item in top),
        "searxng_examples": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "providers": item.get("providers") or [],
                "search_engines": item.get("search_engines") or [],
                "cross_channel_match": bool(item.get("cross_channel_match")),
            }
            for item in searxng_results[:5]
        ],
        "top5": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "providers": item.get("providers") or [],
                "content_level": item.get("content_level"),
                "source_tier": item.get("source_tier"),
            }
            for item in top[:5]
        ],
    }


async def main() -> None:
    pg_manager.initialize()
    uid = f"qasearx_{uuid4().hex[:10]}"
    password = secrets.token_urlsafe(24)
    client = httpx.AsyncClient(base_url=BASE_URL, timeout=90, trust_env=False)
    user_id = None
    thread_id = None
    session_id = None
    parent_run_id = None
    report: dict = {
        "scope": "production HTTPS intelligent dialogue; one parent concurrently delegates three research-explorer runs",
        "queries": CASES,
        "started_at_epoch": time.time(),
    }
    try:
        async with pg_manager.get_async_session_context() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            user = User(
                uid=uid,
                username=uid,
                password_hash=AuthUtils.hash_password(password),
                role="user",
                department_id=department_id,
            )
            db.add(user)
            await db.flush()
            user_id = user.id

        login = await api(client, "POST", "/api/auth/token", data={"username": uid, "password": password})
        client.headers["Authorization"] = "Bearer " + login["access_token"]
        default = await api(client, "GET", "/api/agent/default")
        agent_slug = default["agent"]["slug"]
        thread = await api(
            client,
            "POST",
            "/api/chat/thread",
            json={
                "agent_id": agent_slug,
                "title": make_test_conversation_title("searx-live-intelligent-research"),
                "metadata": make_test_conversation_metadata("searx-live-intelligent-research", e2e=True),
            },
        )
        thread_id = thread.get("thread_id") or thread.get("id")
        async with pg_manager.get_async_session_context() as db:
            project_id = await db.scalar(
                select(Conversation.project_id).where(Conversation.thread_id == thread_id, Conversation.uid == uid)
            )

        session = await api(
            client,
            "POST",
            "/api/equipment/deep-thinking",
            json={
                "project_id": project_id,
                "title": make_test_conversation_title("searx-three-explorers"),
                "topic": "罕见技术术语三渠道检索质量验收",
                "focus": "验证 Open WebSearch、SearXNG、AMiner 并行融合和证据分级",
                "knowledge_enabled": False,
                "subagents_enabled": True,
            },
        )
        session_id = session.get("session_id") or session.get("id")
        prompt = """这是生产环境检索验收。请立即并行委派3名调研探索员，分别研究以下三个彼此独立的罕见技术术语；不要由主智能体自己替代检索：
1. photonic time crystal nonreciprocal microwave amplification
2. Moiré excitons in semiconductor heterobilayers
3. Experimental evidence for altermagnetism and spin splitting

每名探索员的第一个检索必须调用 parallel_research_search（count=12，academic_mode=topic），让 Open WebSearch、SearXNG、AMiner 三渠道并行融合；随后仅对1至3篇强相关论文用 academic_get_papers 读取完整摘要。每名探索员交付4至6条高价值发现，明确区分完整摘要、部分摘要、仅元数据，并保留真实 URL。请用 subagent_start 在同一波次启动三名探索员，再统一等待；最终简洁比较三组结果的精准性、渠道互补与证据边界，不创建报告或能力卡。"""
        started = time.monotonic()
        sent = await api(
            client,
            "POST",
            f"/api/equipment/deep-thinking/{session_id}/messages",
            json={"content": prompt},
        )
        parent_run_id = sent["request"]["run_id"]
        report.update({"uid": uid, "session_id": session_id, "parent_run_id": parent_run_id})
        print(json.dumps({"phase": "parent_started", "session_id": session_id, "run_id": parent_run_id}), flush=True)

        while time.monotonic() - started < 720:
            run = (await api(client, "GET", f"/api/agent/runs/{parent_run_id}"))["run"]
            if run["status"] in TERMINAL:
                report["parent_status"] = run["status"]
                report["parent_timing"] = run.get("timing") or {}
                report["parent_elapsed_seconds"] = round(time.monotonic() - started, 3)
                if run["status"] != "completed":
                    raise RuntimeError(f"parent run ended as {run['status']}: {run.get('error_message')}")
                break
            await asyncio.sleep(2)
        else:
            raise TimeoutError("parent intelligent dialogue exceeded 720 seconds")

        parent_result = await api(client, "GET", f"/api/agent/runs/{parent_run_id}/result")
        report["parent_output"] = str(parent_result.get("output") or "")
        await asyncio.sleep(3)

        async with pg_manager.get_async_session_context() as db:
            child_runs = list(
                (
                    await db.scalars(
                        select(AgentRun)
                        .where(
                            AgentRun.created_by_run_id == parent_run_id,
                            AgentRun.agent_slug == "research-explorer",
                        )
                        .order_by(AgentRun.created_at)
                    )
                ).all()
            )
            child_ids = [run.id for run in child_runs]
            tool_rows = (
                await db.execute(
                    select(ToolCall, Message)
                    .join(Message, ToolCall.message_id == Message.id)
                    .where(Message.run_id.in_(child_ids))
                    .order_by(ToolCall.created_at)
                )
            ).all() if child_ids else []
            academic_rows = list(
                (
                    await db.scalars(
                        select(AcademicRetrievalCall).where(AcademicRetrievalCall.run_id.in_(child_ids))
                    )
                ).all()
            ) if child_ids else []

        by_run: dict[str, list[ToolCall]] = {run_id: [] for run_id in child_ids}
        for tool, message in tool_rows:
            by_run.setdefault(str(message.run_id), []).append(tool)

        child_summaries = []
        starts = []
        finishes = []
        for run in child_runs:
            tools = by_run.get(run.id, [])
            parallel = next((tool for tool in tools if tool.tool_name == "parallel_research_search"), None)
            query = str((parallel.tool_input or {}).get("query") or "") if parallel else ""
            case = next(
                (case for case in CASES if case["query"].casefold() == query.casefold()),
                next((case for case in CASES if case["name"].split("-")[0] in query.casefold()), CASES[0]),
            )
            parallel_payload = parse_json(parallel.tool_output) if parallel else {}
            row = {
                "run_id": run.id,
                "status": run.status,
                "query": query,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "tool_order": [tool.tool_name for tool in tools],
                "first_tool": tools[0].tool_name if tools else None,
                "parallel_search": summarize_parallel_result(parallel_payload, case["aliases"]),
                "academic_get_papers_calls": sum(tool.tool_name == "academic_get_papers" for tool in tools),
            }
            child_summaries.append(row)
            if run.started_at:
                starts.append(run.started_at.timestamp())
            if run.finished_at:
                finishes.append(run.finished_at.timestamp())

        overlap_seconds = 0.0
        if len(starts) >= 2 and finishes:
            overlap_seconds = max(0.0, min(finishes) - max(starts))
        report["children"] = child_summaries
        report["concurrency"] = {
            "child_count": len(child_runs),
            "overlap_seconds_all_children": round(overlap_seconds, 3),
            "start_spread_seconds": round(max(starts) - min(starts), 3) if len(starts) >= 2 else None,
        }
        report["academic_ledger"] = {
            "calls": len(academic_rows),
            "succeeded": sum(row.status == "succeeded" for row in academic_rows),
            "failed": sum(row.status == "failed" for row in academic_rows),
        }
        all_parallel = [row["parallel_search"] for row in child_summaries]
        report["acceptance"] = {
            "three_research_explorers_completed": len(child_runs) == 3 and all(row.status == "completed" for row in child_runs),
            "children_overlapped": overlap_seconds > 0,
            "parallel_search_was_first_tool": all(row["first_tool"] == "parallel_research_search" for row in child_summaries),
            "all_three_channels_attempted": all(
                {"open-websearch", "searxng", "aminer"}.issubset(set(row["attempted_providers"]))
                for row in all_parallel
            ),
            "all_classified_academic": all("academic" in (row["query_profile"].get("categories") or []) for row in all_parallel),
            "searxng_contributed_every_case": all(row["searxng_result_count"] > 0 for row in all_parallel),
            "top10_alias_precision": round(
                sum(row["top10_alias_matches"] for row in all_parallel) / max(1, 10 * len(all_parallel)), 3
            ),
            "cross_channel_matches": sum(row["cross_channel_matches"] for row in all_parallel),
            "unique_candidates": sum((row["channel_summary"] or {}).get("unique_candidates", 0) for row in all_parallel),
            "median_parallel_result_count": statistics.median(row["result_count"] for row in all_parallel) if all_parallel else 0,
        }
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(json.dumps({"phase": "validation_complete", "report": str(OUT), "acceptance": report["acceptance"]}, ensure_ascii=False), flush=True)
    finally:
        cleanup_errors = []
        try:
            if parent_run_id:
                current = (await api(client, "GET", f"/api/agent/runs/{parent_run_id}"))["run"]
                if current["status"] not in TERMINAL:
                    await api(client, "POST", f"/api/agent/runs/{parent_run_id}/cancel")
                    for _ in range(90):
                        current = (await api(client, "GET", f"/api/agent/runs/{parent_run_id}"))["run"]
                        if current["status"] in TERMINAL:
                            break
                        await asyncio.sleep(1)
            if session_id:
                for _ in range(30):
                    response = await client.delete(f"/api/equipment/deep-thinking/{session_id}")
                    if response.status_code in {200, 404}:
                        break
                    if response.status_code != 409:
                        raise RuntimeError(f"deep session cleanup failed: {response.status_code}: {response.text[:300]}")
                    await asyncio.sleep(1)
            if user_id is not None:
                async with pg_manager.get_async_session_context() as db:
                    owned_runs = list((await db.scalars(select(AgentRun.id).where(AgentRun.uid == uid))).all())
                await cleanup_test_chat_resources(client, dict(client.headers), owner_uid=uid)
                async with pg_manager.get_async_session_context() as db:
                    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
                    if user is not None:
                        for model, column, value in (
                            (OperationLog, OperationLog.user_id, user_id),
                            (AgentEnv, AgentEnv.uid, uid),
                            (UserConfig, UserConfig.uid, uid),
                        ):
                            await db.execute(delete(model).where(column == value))
                        await db.delete(user)
                directory = global_user_data_dir(uid)
                if directory.exists() and directory.name == uid:
                    shutil.rmtree(directory)
                report["cleanup"] = {"owned_runs": len(owned_runs), "account_removed": True}
        except Exception as error:  # 保留验收报告并显式暴露清理问题
            cleanup_errors.append(f"{type(error).__name__}: {error}")
            report["cleanup"] = {"errors": cleanup_errors}
        finally:
            if report:
                OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            await client.aclose()
            await pg_manager.close()


asyncio.run(main())
