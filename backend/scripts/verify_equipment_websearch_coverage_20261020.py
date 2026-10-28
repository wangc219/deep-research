"""验证装备类智能对话与深研对话的公网检索地域及时效覆盖。"""

from __future__ import annotations

import asyncio
import json
import os
import re
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
from platform_core.storage.postgres.models_business import AgentRun, User
from platform_core.utils.auth_utils import AuthUtils


QUERY_ID = "query-30510033-b96d-46e8-8a3a-48ffe2b07e8e"
QUERY = "低空无人集群复杂电磁环境闭环反制装备研究"
PROJECT_ID = "06a3a154-076d-4fab-88a5-add6cd8bacd3"
OUTPUT_DIR = Path("/app/outputs/equipment-websearch-coverage-20261020")
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
TIMEOUT_SECONDS = 600
EXISTING_RUN_IDS = {
    "smart": os.getenv("EXISTING_SMART_RUN_ID", "").strip(),
    "deep": os.getenv("EXISTING_DEEP_RUN_ID", "").strip(),
}
DOMESTIC_HOST_MARKERS = (
    ".cn",
    "81.cn",
    "cas.cn",
    "cetc.com",
    "avic.com",
    "norinco.com",
    "spacechina.com",
)
DOMESTIC_OFFICIAL_SITES = {
    "81.cn",
    "mod.gov.cn",
    "gov.cn",
    "cas.cn",
    "cetc.com.cn",
    "avic.com",
    "norinco.com",
    "spacechina.com",
}
RECENT_MARKERS = (
    "2024",
    "2025",
    "2026",
    "最新",
    "近期",
    "进展",
    "试验",
    "原型",
    "列装",
    "部署",
    "recent",
    "latest",
    "prototype",
    "trial",
    "deployment",
)

PROMPT = f"""项目现有 Query（{QUERY_ID}）：{QUERY}。

本轮只验收 Open Websearch 对装备研究的公开资料覆盖质量，不调用 AMiner、知识库或子智能体，
不创建待办，也不生成新装备候选。
请判断该方向当前公开技术进展、代表性装备/试验、工程成熟度与主要证据缺口。按系统中的装备 Websearch 规则自主设计检索，
实际调用 6—8 次 web_search；每次查询只处理一个明确证据缺口并使用 required_terms 控制主题漂移。
不要把检索计划当成最终答案。

最终用 500—900 字交付核验结论，逐项附可点击原始 URL，注明来源地域与公开年份，
并区分已部署或在役、公开试验、原型样机和论文概念。
若某一地域没有有效公开结果，明确写出证据缺口。只输出完整正文，不创建文件或任务，不追问。"""


def decode(value: Any) -> Any:
    if isinstance(value, dict) and isinstance(value.get("content"), str):
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
    return [item for item in rows or [] if isinstance(item, dict)]


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def is_self_anchored_query(query: str) -> bool:
    """允许极少数未传 required_terms、但自身已有多个装备身份限定词的查询。"""
    generic = {
        "中国",
        "国外",
        "国内",
        "最新",
        "近期",
        "技术",
        "研究",
        "发展",
        "装备",
        "系统",
        "试验",
        "测试",
        "trial",
        "test",
        "latest",
        "recent",
        "system",
        "technology",
    }
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}|[\u3400-\u9fff]{2,}", query)
        if token.casefold() not in generic and not re.fullmatch(r"20[12]\d", token)
    }
    identity_markers = (
        "无人机",
        "反无人机",
        "微波",
        "激光",
        "电磁",
        "干扰",
        "counter-uas",
        "drone",
        "microwave",
        "laser",
        "jamming",
        "electronic warfare",
    )
    lowered = query.casefold()
    return len(tokens) >= 3 and any(marker in lowered for marker in identity_markers)


def is_domestic_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    return any(marker in host for marker in DOMESTIC_HOST_MARKERS)


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

            selected = await request("GET", f"/api/equipment/queries/{QUERY_ID}")
            selected = selected.get("item") or selected
            assert selected.get("query") == QUERY

            default_agent = (await request("GET", "/api/agent/default"))["agent"]
            default_slug = default_agent.get("slug") or default_agent["agent_id"]
            runs: list[dict[str, Any]] = []

            for entry in ("smart", "deep"):
                title = f"装备公网覆盖验收-{entry}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
                started = time.monotonic()
                existing_run_id = EXISTING_RUN_IDS[entry]
                if existing_run_id:
                    async with pg_manager.get_async_session_context() as db:
                        existing = await db.scalar(select(AgentRun).where(AgentRun.id == existing_run_id))
                    assert existing is not None, f"找不到既有 Run: {existing_run_id}"
                    result = await request("GET", f"/api/agent/runs/{existing_run_id}/result")
                    runs.append(
                        {
                            "entry": entry,
                            "agent_slug": existing.agent_slug,
                            "run_id": existing_run_id,
                            "thread_id": existing.conversation_thread_id,
                            "session_id": None,
                            "elapsed_seconds": round(
                                float((result.get("timing") or {}).get("total_latency_ms") or 0) / 1000,
                                1,
                            ),
                            "result": result,
                        }
                    )
                    print(json.dumps({"reused": entry, "run_id": existing_run_id}, ensure_ascii=False), flush=True)
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
                            "meta": {"request_id": f"equipment-websearch-{entry}-{uuid4().hex[:10]}"},
                        },
                    )
                    run_id = submitted["run_id"]
                    agent_slug = default_slug
                    session_id = None
                else:
                    session = await request(
                        "POST",
                        "/api/equipment/deep-thinking",
                        json={
                            "project_id": PROJECT_ID,
                            "title": title,
                            "topic": QUERY,
                            "focus": "装备公网检索国内外及前沿覆盖验收",
                            "model_spec": model,
                            "knowledge_enabled": False,
                            "knowledge_ids": [],
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
                while time.monotonic() - started < TIMEOUT_SECONDS:
                    result = await request("GET", f"/api/agent/runs/{run_id}/result")
                    if result.get("status") in TERMINAL:
                        break
                    await asyncio.sleep(8)
                else:
                    raise TimeoutError(f"{entry} run {run_id} exceeded {TIMEOUT_SECONDS}s")

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

            for run in runs:
                children = await descendants(run["run_id"])
                thread_ids = [run["thread_id"], *(child.conversation_thread_id for child in children)]
                tools: list[dict[str, Any]] = []
                for thread_id in dict.fromkeys(thread_ids):
                    audits = await request("GET", f"/api/chat/thread/{thread_id}/audits")
                    tools.extend(item for item in audits.get("audits") or [] if item.get("type") == "tool")

                web_tools = [item for item in tools if item.get("tool_name") == "web_search"]
                queries = [str((item.get("tool_input") or {}).get("query") or "") for item in web_tools]
                required_terms = [(item.get("tool_input") or {}).get("required_terms") for item in web_tools]
                sites = [(item.get("tool_input") or {}).get("sites") or [] for item in web_tools]
                call_rows = [result_rows(item.get("tool_output")) for item in web_tools]
                rows = [row for current_rows in call_rows for row in current_rows]
                urls = sorted(
                    {
                        str(row.get("url") or "").split("#", 1)[0].rstrip("/")
                        for row in rows
                        if str(row.get("url") or "").startswith(("http://", "https://"))
                    }
                )
                domestic_urls = [url for url in urls if is_domestic_url(url)]
                foreign_urls = [url for url in urls if not is_domestic_url(url)]
                domestic_query_urls = sorted(
                    {
                        str(row.get("url") or "").split("#", 1)[0].rstrip("/")
                        for query, current_rows in zip(queries, call_rows, strict=True)
                        if has_cjk(query)
                        for row in current_rows
                        if str(row.get("url") or "").startswith(("http://", "https://"))
                    }
                )
                foreign_query_urls = sorted(
                    {
                        str(row.get("url") or "").split("#", 1)[0].rstrip("/")
                        for query, current_rows in zip(queries, call_rows, strict=True)
                        if not has_cjk(query)
                        for row in current_rows
                        if str(row.get("url") or "").startswith(("http://", "https://"))
                    }
                )
                authoritative = [row for row in rows if row.get("source_tier") == "authoritative"]
                output = str(run["result"].get("output") or "")
                explicit_anchor_count = sum(bool(terms) for terms in required_terms)
                audit = {
                    "web_search_calls": len(web_tools),
                    "queries": queries,
                    "required_terms": required_terms,
                    "explicit_anchor_calls": explicit_anchor_count,
                    "sites": sites,
                    "result_count": len(rows),
                    "distinct_urls": len(urls),
                    "domestic_urls": domestic_urls,
                    "foreign_urls": foreign_urls,
                    "domestic_query_urls": domestic_query_urls,
                    "foreign_query_urls": foreign_query_urls,
                    "authoritative_results": len(authoritative),
                }
                domestic_official_attempted = any(
                    DOMESTIC_OFFICIAL_SITES.intersection(str(site).casefold() for site in call_sites)
                    for call_sites in sites
                ) or any("site:" in query.casefold() and has_cjk(query) for query in queries)
                domestic_gap_disclosed = "国内" in output and "缺口" in output
                deployment_boundary = any(marker in output for marker in ("部署", "在役", "列装"))
                trial_boundary = any(marker in output for marker in ("公开试验", "试验", "测试", "演示"))
                checks = {
                    "completed": run["result"].get("status") == "completed",
                    "six_to_eight_calls": 6 <= len(web_tools) <= 8,
                    "domestic_query": any(has_cjk(query) for query in queries),
                    "foreign_query": any(not has_cjk(query) and re.search(r"[A-Za-z]", query) for query in queries),
                    "recent_progress_query": any(
                        marker in query.casefold() for query in queries for marker in RECENT_MARKERS
                    ),
                    "query_anchor_coverage": explicit_anchor_count >= max(1, len(web_tools) - 1)
                    and all(
                        bool(terms) or is_self_anchored_query(query)
                        for query, terms in zip(queries, required_terms, strict=True)
                    ),
                    "domestic_official_search_attempted": domestic_official_attempted,
                    "domestic_coverage_handled": bool(domestic_urls)
                    or (domestic_official_attempted and domestic_gap_disclosed),
                    "foreign_source_found": bool(foreign_query_urls),
                    "source_quality": len(urls) >= 4 and bool(authoritative),
                    "maturity_boundaries": deployment_boundary
                    and trial_boundary
                    and "原型" in output
                    and "论文" in output,
                    "region_and_time_labeled": (
                        "国内" in output and "国外" in output and bool(re.search(r"20[12]\d", output))
                    ),
                }
                run["children"] = [
                    {"run_id": child.id, "agent_slug": child.agent_slug, "status": child.status} for child in children
                ]
                run["audit"] = audit
                run["quality_checks"] = checks
                run["quality_passed"] = all(checks.values())

            report = {
                "validated_at": datetime.now(UTC).isoformat(),
                "query_id": QUERY_ID,
                "query": QUERY,
                "project_id": PROJECT_ID,
                "model": model,
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
                ),
                flush=True,
            )
            if not report["passed"]:
                raise AssertionError("智能对话与深研对话未同时通过装备 Open Websearch 覆盖门槛")
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
