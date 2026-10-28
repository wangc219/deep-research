"""用一个项目军事 Query 验证智能对话与深研对话的三类真实检索。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select

from platform_core.config.options import system_options
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import AcademicRetrievalCall, AgentRun, User
from platform_core.utils.auth_utils import AuthUtils


QUERY_ID = "query-30510033-b96d-46e8-8a3a-48ffe2b07e8e"
QUERY = "低空无人集群复杂电磁环境闭环反制装备研究"
PROJECT_ID = "06a3a154-076d-4fab-88a5-add6cd8bacd3"
KB_ID = "kb_zcfj9omke9"
OUTPUT_DIR = Path("/app/outputs/retrieval-quality-20261020")
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
TIMEOUT_SECONDS = 900
EXISTING_RUN_IDS = tuple(
    run_id.strip() for run_id in os.getenv("EXISTING_RUN_IDS", "").split(",") if run_id.strip()
)

PROMPT = f"""项目现有 Query（{QUERY_ID}）：{QUERY}。

本轮只验收检索通道和证据融合质量，不生成或发散新装备候选，不启动子智能体，不创建待办。

请围绕“复杂电磁环境下，如何形成对低空无人集群的探测—识别—决策—软硬反制—效果评估闭环”做一次可核验的研究回答。
本次是检索质量验收，必须在形成结论前实际完成三类检索：
1. 调用 Open Websearch，至少用两个精确检索词，并用 required_terms 控制主题漂移；优先政府、军队、标准组织、论文出版页或厂商一手资料。
2. 调用 AMiner academic_search 发现相关论文，筛选后调用 academic_get_papers 获取 1—2 篇强相关论文的完整摘要。不要把题录或摘要声称为全文。
3. 本轮显式启用 @知识库；调用知识库 query_kb 或 query_kbs，知识库 ID 为 {KB_ID}；优先检索“无人机蜂群反制、探干通一体化、雷达抗干扰、协同态势感知”，引用返回的文件名与具体内容。

最终用 800—1600 字形成一份检索质量核验正文：分别列出三类检索最有价值的证据及其相关性，再用这些证据简要判断闭环装备构型、关键技术链、性能/适用边界、主要失效条件和最小验证试验。逐项区分网页公开事实、AMiner 论文摘要结论、知识库内部文献结论以及尚待验证的工程推断；网页给出可点击 URL，论文给出题名/年份/DOI 或出版链接，知识库给出文件名。只输出完整正文，不创建文件或任务，不追问。"""


def decode(value: Any) -> Any:
    if (
        isinstance(value, dict)
        and isinstance(value.get("content"), str)
        and (value.get("type") == "tool" or not any(key in value for key in ("results", "status", "metadata", "query")))
    ):
        value = value["content"]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {"text": value}
    return value


def result_rows(payload: Any) -> list[dict[str, Any]]:
    payload = decode(payload)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    rows = payload.get("results")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    nested: list[dict[str, Any]] = []
    for retrieval in payload.get("retrievals") or []:
        if isinstance(retrieval, dict):
            nested.extend(result_rows(retrieval.get("result")))
    return nested


async def descendants(root_run_id: str) -> list[AgentRun]:
    found: list[AgentRun] = []
    frontier = [root_run_id]
    async with pg_manager.get_async_session_context() as db:
        while frontier:
            rows = (await db.scalars(select(AgentRun).where(AgentRun.created_by_run_id.in_(frontier)))).all()
            found.extend(rows)
            frontier = [row.id for row in rows]
    return found


async def main() -> None:
    pg_manager.initialize()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        async with pg_manager.get_async_session_context() as db:
            user = await db.scalar(
                select(User).where(User.role == "superadmin", User.is_deleted == 0).order_by(User.id).limit(1)
            )
            assert user is not None
            token = AuthUtils.create_access_token({"sub": str(user.id)}, expires_delta=timedelta(hours=2))
            model = (await system_options.get(db))["default_model"]

        headers = {"Authorization": "Bearer " + token}
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:5050", headers=headers, timeout=httpx.Timeout(120)
        ) as client:

            async def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            query_payload = await request("GET", f"/api/equipment/queries/{QUERY_ID}")
            selected_query = query_payload.get("item") or query_payload
            assert selected_query.get("query_id") == QUERY_ID
            assert selected_query.get("query") == QUERY

            kb_preflight = await request(
                "POST",
                f"/api/knowledge/databases/{KB_ID}/query",
                json={"query": "低空无人集群 雷达探测 电磁干扰 反制 闭环", "meta": {}},
            )
            preflight_rows = result_rows(kb_preflight.get("result"))
            assert preflight_rows, "知识库预检未召回内容"

            default_agent = (await request("GET", "/api/agent/default"))["agent"]
            default_slug = default_agent.get("slug") or default_agent["agent_id"]
            runs: list[dict[str, Any]] = []

            for index, entry in enumerate(("smart", "deep")):
                title = f"三类检索质量验收-{entry}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
                started = time.monotonic()
                if index < len(EXISTING_RUN_IDS):
                    run_id = EXISTING_RUN_IDS[index]
                    async with pg_manager.get_async_session_context() as db:
                        existing = await db.scalar(select(AgentRun).where(AgentRun.id == run_id))
                    assert existing is not None, f"找不到既有 Run: {run_id}"
                    result = await request("GET", f"/api/agent/runs/{run_id}/result")
                    timing = result.get("timing") or {}
                    runs.append(
                        {
                            "entry": entry,
                            "agent_slug": existing.agent_slug,
                            "run_id": run_id,
                            "thread_id": existing.conversation_thread_id,
                            "session_id": None,
                            "elapsed_seconds": round(float(timing.get("total_latency_ms") or 0) / 1000, 1),
                            "result": result,
                        }
                    )
                    print(
                        json.dumps(
                            {"reused": entry, "run_id": run_id, "status": result.get("status")},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    continue
                if entry == "smart":
                    thread = await request(
                        "POST",
                        "/api/chat/thread",
                        json={"agent_id": default_slug, "title": title, "project_id": PROJECT_ID},
                    )
                    thread_id = thread.get("thread_id") or thread["id"]
                    submitted = await request(
                        "POST",
                        "/api/agent/runs",
                        json={
                            "agent_slug": default_slug,
                            "thread_id": thread_id,
                            "query": PROMPT,
                            "model_spec": model,
                            "tool_approval_mode": "always_trust",
                            "knowledge_ids": [KB_ID],
                            "meta": {"request_id": f"retrieval-quality-smart-{uuid4().hex[:10]}"},
                        },
                    )
                    session_id = None
                    run_id = submitted["run_id"]
                    agent_slug = default_slug
                else:
                    session = await request(
                        "POST",
                        "/api/equipment/deep-thinking",
                        json={
                            "project_id": PROJECT_ID,
                            "title": title,
                            "topic": QUERY,
                            "focus": "三类检索证据融合质量验收",
                            "model_spec": model,
                            "knowledge_enabled": True,
                            "knowledge_ids": [KB_ID],
                            "subagents_enabled": False,
                        },
                    )
                    session_id = session["session_id"]
                    thread_id = session["payload"]["thread_id"]
                    submitted = await request(
                        "POST",
                        f"/api/equipment/deep-thinking/{session_id}/messages",
                        json={"content": PROMPT, "model_spec": model},
                    )
                    run_id = submitted["request"]["run_id"]
                    agent_slug = "deep-research"

                print(json.dumps({"submitted": entry, "run_id": run_id}, ensure_ascii=False), flush=True)
                last_status = None
                while time.monotonic() - started < TIMEOUT_SECONDS:
                    result = await request("GET", f"/api/agent/runs/{run_id}/result")
                    if result.get("status") != last_status:
                        last_status = result.get("status")
                        print(
                            json.dumps(
                                {
                                    "entry": entry,
                                    "status": last_status,
                                    "elapsed_seconds": round(time.monotonic() - started, 1),
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                    if result.get("status") in TERMINAL:
                        break
                    await asyncio.sleep(8)
                else:
                    raise TimeoutError(f"{entry} run {run_id} 超过 {TIMEOUT_SECONDS} 秒")

                runs.append(
                    {
                        "entry": entry,
                        "agent_slug": agent_slug,
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                        "result": result,
                    }
                )
                print(
                    json.dumps(
                        {
                            "finished": entry,
                            "status": result.get("status"),
                            "elapsed_seconds": runs[-1]["elapsed_seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

            for run in runs:
                children = await descendants(run["run_id"])
                audit_threads = [run["thread_id"], *(child.conversation_thread_id for child in children)]
                tools: list[dict[str, Any]] = []
                for thread_id in dict.fromkeys(audit_threads):
                    audits = await request("GET", f"/api/chat/thread/{thread_id}/audits")
                    tools.extend(item for item in audits.get("audits") or [] if item.get("type") == "tool")

                web_tools = [item for item in tools if item.get("tool_name") == "web_search"]
                web_rows = [row for item in web_tools for row in result_rows(item.get("tool_output"))]
                web_urls = {
                    str(row.get("url") or "").split("#", 1)[0].rstrip("/")
                    for row in web_rows
                    if str(row.get("url") or "").startswith(("http://", "https://"))
                }
                relevant_web = [
                    row
                    for row in web_rows
                    if any(
                        marker in (str(row.get("title") or "") + " " + str(row.get("snippet") or row.get("content") or "")).casefold()
                        for marker in ("uav", "drone", "无人", "反无人", "radar", "雷达", "electromagnetic", "电磁")
                    )
                ]
                authoritative_web = [row for row in web_rows if row.get("source_tier") == "authoritative"]

                academic_search_tools = [item for item in tools if item.get("tool_name") == "academic_search"]
                academic_get_tools = [item for item in tools if item.get("tool_name") == "academic_get_papers"]
                academic_candidates = [
                    row for item in academic_search_tools for row in result_rows(item.get("tool_output"))
                ]
                academic_details = [row for item in academic_get_tools for row in result_rows(item.get("tool_output"))]
                full_abstracts = [
                    {
                        "id": row.get("id"),
                        "title": row.get("title"),
                        "year": row.get("year"),
                        "doi": row.get("doi"),
                    }
                    for row in academic_details
                    if row.get("content_level") == "abstract"
                ]

                kb_tools = [item for item in tools if item.get("tool_name") in {"query_kb", "query_kbs"}]
                kb_rows = [row for item in kb_tools for row in result_rows(item.get("tool_output"))]
                kb_sources = sorted(
                    {
                        str((row.get("metadata") or {}).get("source") or "")
                        for row in kb_rows
                        if str((row.get("metadata") or {}).get("source") or "")
                    }
                )
                kb_scores = sorted(
                    [
                        float((row.get("metadata") or {}).get("score") or row.get("score") or 0)
                        for row in kb_rows
                    ],
                    reverse=True,
                )

                async with pg_manager.get_async_session_context() as db:
                    ledger = (
                        await db.scalars(
                            select(AcademicRetrievalCall)
                            .where(AcademicRetrievalCall.root_run_id == run["run_id"])
                            .order_by(AcademicRetrievalCall.created_at)
                        )
                    ).all()

                output = str(run["result"].get("output") or "")
                run["children"] = [
                    {"run_id": child.id, "agent_slug": child.agent_slug, "status": child.status}
                    for child in children
                ]
                run["audit"] = {
                    "web_search_calls": len(web_tools),
                    "web_result_count": len(web_rows),
                    "web_distinct_urls": len(web_urls),
                    "web_relevant_results": len(relevant_web),
                    "web_relevance_ratio": round(len(relevant_web) / len(web_rows), 3) if web_rows else 0,
                    "web_authoritative_results": len(authoritative_web),
                    "web_urls": sorted(web_urls),
                    "academic_search_calls": len(academic_search_tools),
                    "academic_candidate_count": len(academic_candidates),
                    "academic_get_papers_calls": len(academic_get_tools),
                    "full_abstracts": full_abstracts,
                    "aminer_ledger_calls": len(ledger),
                    "aminer_failed_calls": sum(call.status != "succeeded" for call in ledger),
                    "knowledge_calls": len(kb_tools),
                    "knowledge_result_count": len(kb_rows),
                    "knowledge_sources": kb_sources,
                    "knowledge_top_scores": kb_scores[:5],
                }
                audit = run["audit"]
                run["quality_checks"] = {
                    "completed": run["result"].get("status") == "completed",
                    "open_websearch_effective": audit["web_search_calls"] >= 2
                    and audit["web_distinct_urls"] >= 3
                    and audit["web_relevance_ratio"] >= 0.6,
                    "open_websearch_high_quality": audit["web_authoritative_results"] >= 1,
                    "aminer_effective": audit["academic_search_calls"] >= 1
                    and audit["academic_candidate_count"] >= 1
                    and len(audit["full_abstracts"]) >= 1
                    and audit["aminer_failed_calls"] == 0,
                    "knowledge_effective": audit["knowledge_calls"] >= 1
                    and audit["knowledge_result_count"] >= 1
                    and len(audit["knowledge_sources"]) >= 1
                    and max(audit["knowledge_top_scores"], default=0) >= 0.6,
                    "standalone_synthesis": len(output) >= 800,
                    "source_boundaries_explicit": all(marker in output for marker in ("知识库", "AMiner"))
                    and ("http://" in output or "https://" in output),
                    "no_tool_protocol_leak": not any(
                        marker in output.casefold() for marker in ("dsml", "tool_calls", "invoke name=", "<｜")
                    ),
                }
                run["quality_passed"] = all(run["quality_checks"].values())

            report = {
                "validated_at": datetime.now(UTC).isoformat(),
                "query_id": QUERY_ID,
                "query": QUERY,
                "project_id": PROJECT_ID,
                "knowledge_base_id": KB_ID,
                "model": model,
                "real_services": {"open_websearch": True, "aminer": True, "knowledge_base": True},
                "knowledge_preflight": {
                    "result_count": len(preflight_rows),
                    "top_sources": [
                        {
                            "source": (row.get("metadata") or {}).get("source"),
                            "file_id": (row.get("metadata") or {}).get("file_id"),
                            "score": row.get("score"),
                        }
                        for row in preflight_rows[:5]
                    ],
                },
                "runs": runs,
                "passed": all(run["quality_passed"] for run in runs),
            }
            output_path = OUTPUT_DIR / "validation.json"
            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print("VALIDATION_PATH=" + str(output_path), flush=True)
            print(
                "VALIDATION_SUMMARY="
                + json.dumps(
                    {
                        "passed": report["passed"],
                        "runs": [
                            {
                                "entry": run["entry"],
                                "run_id": run["run_id"],
                                "elapsed_seconds": run["elapsed_seconds"],
                                "audit": run["audit"],
                                "quality_checks": run["quality_checks"],
                            }
                            for run in runs
                        ],
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )
            if not report["passed"]:
                raise AssertionError("智能对话与深研对话未同时通过三类检索质量门槛")
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
