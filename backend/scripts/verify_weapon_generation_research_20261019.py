"""以真实模型验证智能对话与深研对话的证据塑形装备生成链。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select

from platform_core.config.options import system_options
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import (
    AcademicRetrievalCall,
    AgentRun,
    PlatformModelCall,
    User,
)
from platform_core.utils.auth_utils import AuthUtils


QUERY_ID = "query-30510033-b96d-46e8-8a3a-48ffe2b07e8e"
QUERY = "低空无人集群复杂电磁环境闭环反制装备研究"
PROMPT = f"""项目 Query（{QUERY_ID}）：{QUERY}。
请先进行深度、高效的 Websearch 与 AMiner 论文调研；围绕“面向未来作战需求，形成制衡对手并赢得制胜优势的具体装备”自主形成
研究议程。作战矛盾、能够颠覆或重写的作战方式、前瞻创新制胜机理、针对国外具体装备或体系的制衡路径都是开放入口，不要求逐项覆盖；
调研也可解决候选实现所需的关键技术问题。把发现前置塑造成创作输入，并用实现证据与不可跨越边界约束，
再直接提出 2 个具体、面向作战的新质创新武器装备。不要先自由堆概念再用 S3/S4 字段或检查表事后修补，也不要输出固定检查表。
候选应从生成起点就是可独立研制、部署和试验、能够直接反制具体对象的物理装备；说明关键发现如何塑造构想、直接战果、主要工程边界与最小验证动作。
公开事实与论文结论给出可点击来源，装备级外推和待验证假设明确降级。仅在正文作答，不创建文件或正式平台研究任务，不要追问。"""
PROMPT += "\n最终返回必须是可独立阅读的完整正文，不得只写总结，也不得说‘已在上方给出’或引用未包含在最终返回中的内容。"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
RUN_TIMEOUT_SECONDS = 2700
AGENT_SLUGS = tuple(
    slug.strip()
    for slug in os.getenv("ACCEPTANCE_AGENT_SLUGS", "default-chatbot,deep-research").split(",")
    if slug.strip()
)
EXISTING_RUN_IDS = tuple(
    run_id.strip()
    for run_id in os.getenv("ACCEPTANCE_EXISTING_RUN_IDS", "").split(",")
    if run_id.strip()
)


def decoded(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and "content" in value:
        value = value["content"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {"text": value}
    return value if isinstance(value, dict) else {}


def authoritative_web_result(result: dict[str, Any]) -> bool:
    if result.get("source_tier") == "authoritative":
        return True
    path = urlparse(str(result.get("url") or "")).path.casefold()
    return any(marker in path for marker in ("/press-releases/", "/press_release/", "/newsroom/releases/"))


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
    try:
        async with pg_manager.get_async_session_context() as db:
            user = await db.scalar(
                select(User).where(User.role == "superadmin", User.is_deleted == 0).order_by(User.id).limit(1)
            )
            assert user is not None
            token = AuthUtils.create_access_token({"sub": str(user.id)}, expires_delta=timedelta(hours=2))
            model = (await system_options.get(db))["default_model"]

        headers = {"Authorization": "Bearer " + token}
        async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", headers=headers, timeout=120) as client:

            async def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            runs: list[dict[str, Any]] = []
            validation_started = time.monotonic()
            for index, slug in enumerate(AGENT_SLUGS):
                # 两个入口串行验收，避免 2 个主智能体和多名探索员同时挤压同一模型供应商，
                # 使测得耗时更接近真实单会话体验。
                if index < len(EXISTING_RUN_IDS):
                    async with pg_manager.get_async_session_context() as db:
                        existing = await db.scalar(
                            select(AgentRun).where(AgentRun.id == EXISTING_RUN_IDS[index])
                        )
                    assert existing is not None and existing.agent_slug == slug
                    result = await request("GET", f"/api/agent/runs/{existing.id}/result")
                    timing = result.get("timing") or {}
                    elapsed_seconds = round(float(timing.get("total_latency_ms") or 0) / 1000, 1)
                    run = {
                        "agent_slug": slug,
                        "run_id": existing.id,
                        "thread_id": existing.conversation_thread_id,
                        "request_id": "existing-run-audit",
                        "result": result,
                        "elapsed_seconds": elapsed_seconds,
                    }
                    runs.append(run)
                    print(
                        json.dumps(
                            {
                                "reused": slug,
                                "run_id": existing.id,
                                "status": result["status"],
                                "elapsed_seconds": elapsed_seconds,
                            }
                        ),
                        flush=True,
                    )
                    continue
                request_id = f"weapon-generation-{slug}-{uuid4().hex[:12]}"
                run_started = time.monotonic()
                created = await request(
                    "POST",
                    "/api/agent-invocation/agent-call/runs",
                    json={
                        "agent_slug": slug,
                        "messages": [{"role": "user", "content": PROMPT}],
                        "stream": False,
                        "request_id": request_id,
                        "model_spec": model,
                        "async_mode": True,
                        "tool_approval_mode": "always_trust",
                    },
                )
                run = {
                    "agent_slug": slug,
                    "run_id": created["run_id"],
                    "thread_id": created["thread_id"],
                    "request_id": request_id,
                }
                runs.append(run)
                print(json.dumps({"submitted": slug, "run_id": created["run_id"]}), flush=True)

                while time.monotonic() - run_started < RUN_TIMEOUT_SECONDS:
                    result = await request("GET", f"/api/agent/runs/{run['run_id']}/result")
                    if result["status"] in TERMINAL:
                        run["result"] = result
                        run["elapsed_seconds"] = round(time.monotonic() - run_started, 1)
                        print(
                            json.dumps(
                                {
                                    "finished": run["agent_slug"],
                                    "run_id": run["run_id"],
                                    "status": result["status"],
                                    "elapsed_seconds": run["elapsed_seconds"],
                                }
                            ),
                            flush=True,
                        )
                        break
                    await asyncio.sleep(10)
                else:
                    raise TimeoutError(
                        f"{slug} run {run['run_id']} did not finish within {RUN_TIMEOUT_SECONDS} seconds"
                    )

            for run in runs:
                if "result" not in run:
                    run["result"] = await request("GET", f"/api/agent/runs/{run['run_id']}/result")

                children = await descendants(run["run_id"])
                run["children"] = [
                    {
                        "run_id": child.id,
                        "thread_id": child.conversation_thread_id,
                        "agent_slug": child.agent_slug,
                        "status": child.status,
                    }
                    for child in children
                ]
                audit_threads = [run["thread_id"], *(child.conversation_thread_id for child in children)]
                tools: list[dict[str, Any]] = []
                for thread_id in audit_threads:
                    audits = await request("GET", f"/api/chat/thread/{thread_id}/audits")
                    tools.extend(item for item in audits["audits"] if item.get("type") == "tool")

                async with pg_manager.get_async_session_context() as db:
                    calls = (
                        await db.scalars(
                            select(AcademicRetrievalCall)
                            .where(AcademicRetrievalCall.root_run_id == run["run_id"])
                            .order_by(AcademicRetrievalCall.created_at)
                        )
                    ).all()
                    child_by_id = {child.id: child.agent_slug for child in children}
                    model_calls = (
                        await db.scalars(
                            select(PlatformModelCall)
                            .where(PlatformModelCall.run_id.in_([run["run_id"], *child_by_id]))
                            .order_by(PlatformModelCall.created_at)
                        )
                    ).all()

                web_records = [
                    (decoded(item.get("tool_input")), decoded(item.get("tool_output")))
                    for item in tools
                    if item.get("tool_name") == "web_search"
                ]
                web_rejected_statuses = {
                    "delivery_required",
                    "duplicate_query",
                    "missing_required_terms",
                    "tool_batch_limit",
                    "tool_budget_reached",
                }
                executed_web_records = [
                    (tool_input, tool_output)
                    for tool_input, tool_output in web_records
                    if tool_output.get("status") not in web_rejected_statuses
                ]
                web_inputs = [tool_input for tool_input, _tool_output in executed_web_records]
                web_outputs = [tool_output for _tool_input, tool_output in executed_web_records]
                web_results = [
                    result
                    for output in web_outputs
                    for result in output.get("results", [])
                    if isinstance(result, dict)
                ]
                web_urls = {
                    str(result.get("url") or "").split("#", 1)[0].rstrip("/")
                    for result in web_results
                    if str(result.get("url") or "").startswith(("https://", "http://"))
                }
                authoritative_web_urls = {
                    str(result.get("url") or "").split("#", 1)[0].rstrip("/")
                    for result in web_results
                    if authoritative_web_result(result)
                    and str(result.get("url") or "").startswith(("https://", "http://"))
                }
                academic_search_records = [
                    (decoded(item.get("tool_input")), decoded(item.get("tool_output")))
                    for item in tools
                    if item.get("tool_name") == "academic_search"
                ]
                academic_title_hits = sum(
                    str(tool_input.get("mode") or "topic") == "title" and bool(tool_output.get("results"))
                    for tool_input, tool_output in academic_search_records
                )
                academic_topic_hits = sum(
                    str(tool_input.get("mode") or "topic") != "title" and bool(tool_output.get("results"))
                    for tool_input, tool_output in academic_search_records
                )
                academic_get_outputs = [
                    decoded(item.get("tool_output"))
                    for item in tools
                    if item.get("tool_name") == "academic_get_papers"
                ]
                full_abstracts = [
                    {
                        "id": paper.get("id"),
                        "title": paper.get("title"),
                        "doi": paper.get("doi"),
                    }
                    for output in academic_get_outputs
                    for paper in output.get("results", [])
                    if paper.get("content_level") == "abstract"
                ]
                run["audit"] = {
                    "subagent_start": sum(item.get("tool_name") == "subagent_start" for item in tools),
                    "subagent_await": sum(item.get("tool_name") == "subagent_await" for item in tools),
                    "web_search": len(web_inputs),
                    "web_with_required_terms": sum(bool(item.get("required_terms")) for item in web_inputs),
                    "web_anchor_rejections": sum(
                        tool_output.get("status") == "missing_required_terms"
                        for _tool_input, tool_output in web_records
                    ),
                    "web_distinct_sources": len(web_urls),
                    "web_authoritative_sources": len(authoritative_web_urls),
                    "web_authoritative_urls": sorted(authoritative_web_urls),
                    "academic_search": sum(item.get("tool_name") == "academic_search" for item in tools),
                    "academic_topic_hits": academic_topic_hits,
                    "academic_title_hits": academic_title_hits,
                    "academic_get_papers": len(academic_get_outputs),
                    "full_abstracts": full_abstracts,
                    "aminer_calls": len(calls),
                    "aminer_failed_calls": sum(call.status != "succeeded" for call in calls),
                    "aminer_cost_cents": sum(call.cost_cents for call in calls),
                    "aminer_endpoints": [call.endpoint for call in calls],
                    "model_calls": len(model_calls),
                    "model_duration_ms": round(sum(call.duration_ms for call in model_calls), 1),
                    "model_input_tokens": sum(call.input_tokens or 0 for call in model_calls),
                    "model_output_tokens": sum(call.output_tokens or 0 for call in model_calls),
                    "model_by_agent": {
                        agent_slug: {
                            "calls": len(agent_calls),
                            "duration_ms": round(sum(call.duration_ms for call in agent_calls), 1),
                            "max_duration_ms": round(max((call.duration_ms for call in agent_calls), default=0), 1),
                            "input_tokens": sum(call.input_tokens or 0 for call in agent_calls),
                            "output_tokens": sum(call.output_tokens or 0 for call in agent_calls),
                        }
                        for agent_slug in {run["agent_slug"], *child_by_id.values()}
                        if (
                            agent_calls := [
                                call
                                for call in model_calls
                                if (
                                    run["agent_slug"]
                                    if call.run_id == run["run_id"]
                                    else child_by_id.get(call.run_id)
                                )
                                == agent_slug
                            ]
                        )
                    },
                }

                output = str(run["result"].get("output") or "")
                audit = run["audit"]
                run["quality_checks"] = {
                    "completed": run["result"]["status"] == "completed",
                    "efficient_single_entry": float(run.get("elapsed_seconds") or 999999) <= 600,
                    "two_focused_explorers": len(children) == 2,
                    "web_evidence_volume": audit["web_search"] >= 5,
                    "web_source_breadth": audit["web_distinct_sources"] >= 6,
                    "authoritative_web_evidence": audit["web_authoritative_sources"] >= 2,
                    "required_terms_precision": (
                        audit["web_search"] > 0
                        and audit["web_with_required_terms"] / audit["web_search"] >= 0.75
                    ),
                    "aminer_used": audit["academic_search"] >= 2 and audit["aminer_failed_calls"] == 0,
                    "aminer_precise_discovery": (
                        audit["academic_topic_hits"] >= 1 or audit["academic_title_hits"] >= 1
                    ),
                    "full_abstract_chain": 1 <= len(audit["full_abstracts"]) <= 3,
                    "full_abstract_relevance": bool(audit["full_abstracts"])
                    and all(
                        any(
                            marker in str(paper.get("title") or "").casefold()
                            for marker in (
                                "uav",
                                "drone",
                                "unmanned",
                                "gnss",
                                "gps",
                                "microwave",
                                "spoof",
                                "radar jamming",
                                "jamming effect",
                            )
                        )
                        for paper in audit["full_abstracts"]
                    ),
                    "standalone_final_body": len(output) >= 2000
                    and "以上正文" not in output
                    and "已在上方" not in output,
                    "no_visible_tool_protocol": not any(
                        marker in output.casefold()
                        for marker in ("dsml", "tool_calls", "invoke name=", "<｜")
                    ),
                    "concrete_equipment_and_validation": (
                        any(marker in output for marker in ("候选装备", "候选一", "候选1", "装备 1", "装备1"))
                        and any(marker in output for marker in ("最小验证", "验证动作", "验证试验"))
                    ),
                    "evidence_shapes_generation": any(
                        marker in output
                        for marker in (
                            "调研发现如何塑造",
                            "调研如何塑造",
                            "证据如何塑造",
                            "证据塑造",
                            "塑形性发现",
                            "制胜判断",
                            "证据驱动的判断",
                            "如何塑造候选",
                            "制胜关系与候选生成",
                            "关键发现如何塑造构想",
                            "塑造结论",
                        )
                    ),
                }
                run["quality_passed"] = all(run["quality_checks"].values())

            public = {
                "query_id": QUERY_ID,
                "query": QUERY,
                "model": model,
                "runs": [
                    {
                        "agent_slug": run["agent_slug"],
                        "run_id": run["run_id"],
                        "thread_id": run["thread_id"],
                        "status": run["result"]["status"],
                        "elapsed_seconds": run.get("elapsed_seconds"),
                        "timing": run["result"].get("timing"),
                        "children": run["children"],
                        "audit": run["audit"],
                        "quality_checks": run["quality_checks"],
                        "quality_passed": run["quality_passed"],
                        "output": run["result"].get("output"),
                        "error": run["result"].get("error"),
                    }
                    for run in runs
                ],
                "total_elapsed_seconds": (
                    round(sum(float(run.get("elapsed_seconds") or 0) for run in runs), 1)
                    if EXISTING_RUN_IDS
                    else round(time.monotonic() - validation_started, 1)
                ),
            }
            print("VALIDATION_JSON=" + json.dumps(public, ensure_ascii=False, default=str), flush=True)
            if not all(run["quality_passed"] for run in runs):
                raise AssertionError("真实模型验收未同时满足效率与质量门槛")
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
