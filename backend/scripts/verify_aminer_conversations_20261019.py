"""Real HTTP conversations, model, AMiner and ledger; no credential/config writes."""

import asyncio
import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select

from platform_core.config.options import aminer_api_opts, system_options
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import AcademicRetrievalCall, User
from platform_core.utils.auth_utils import AuthUtils

OUT = Path("/app/outputs/aminer-conversations-20261019")
KINDS = ("smart", "deep")
VARIANTS = ("web", "aminer")
TOPICS = {
    "attention": (
        "针对长序列大模型的显存瓶颈，比较 FlashAttention 与稀疏注意力：各自改变什么、计算与显存开销、"
        "速度结论适用条件、是否能保证任意硬件推理提速两倍。请检索公开技术资料，给出3篇左右可追溯论文和链接，"
        "把每项关键结论对应到实际取得的证据，明确摘要与全文边界。中文600字左右，仅在正文作答，"
        "无需文件或平台任务，不要追问。"
    ),
    "rag": (
        "比较检索增强生成 RAG 与长上下文模型在知识密集型问答中的取舍，重点解释准确性、成本、信息遗漏和何时结合使用。"
        "请检索公开技术资料，给出3篇左右可追溯论文和链接，把每项关键结论对应到实际取得的证据，"
        "明确摘要与全文边界。中文600字左右，仅在正文作答，无需文件或平台任务，不要追问。"
    ),
}


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            user = await db.scalar(
                select(User).where(User.role == "superadmin", User.is_deleted == 0).order_by(User.id).limit(1)
            )
            assert user is not None, "Missing existing administrative verification identity"
            token = AuthUtils.create_access_token({"sub": str(user.id)}, expires_delta=timedelta(hours=2))
            config = await aminer_api_opts.get(db)
            model = (await system_options.get(db))["default_model"]
        headers = {"Authorization": "Bearer " + token}
        async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", headers=headers, timeout=120) as client:

            async def req(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            agent = (await req("GET", "/api/agent/default"))["agent"]
            slug = agent.get("slug") or agent["agent_id"]
            project = await req("POST", "/api/projects/defaults/equipment", json={})
            project_id = project.get("project_id") or project["id"]
            manifest = {
                "date": "2026-10-19",
                "timezone": "Asia/Shanghai",
                "environment": "local production HTTP API and worker",
                "model": model,
                "aminer_enabled": bool(config.get("enabled")),
                "real_model": True,
                "real_aminer": True,
                "mock_transport": False,
                "configuration_modified": False,
                "baseline_method": (
                    "same prompt plus user constraint to use web only; "
                    "tools remain available; verify zero academic calls"
                ),
                "cases": [],
            }
            save("manifest.json", manifest)

            async def case(topic, kind, variant):
                name = f"{topic}-{kind}-{variant}"
                prompt = TOPICS[topic]
                if variant == "web":
                    prompt += (
                        "\n本轮作为网页检索对照实验，仅使用网页检索与网页阅读，不使用 AMiner 或 academic 学术工具。"
                    )
                title = f"AMiner真实验证 {name} 20261019"
                if kind == "smart":
                    thread = await req(
                        "POST", "/api/chat/thread", json={"agent_id": slug, "title": title, "project_id": project_id}
                    )
                    thread_id = thread.get("thread_id") or thread["id"]
                    submitted = await req(
                        "POST",
                        "/api/agent/runs",
                        json={
                            "agent_slug": slug,
                            "thread_id": thread_id,
                            "model_spec": model,
                            "query": prompt,
                            "knowledge_ids": [],
                        },
                    )
                    run_id = submitted["run_id"]
                    session_id = None
                else:
                    session = await req(
                        "POST",
                        "/api/equipment/deep-thinking",
                        json={
                            "project_id": project_id,
                            "title": title,
                            "topic": TOPICS[topic],
                            "model_spec": model,
                            "knowledge_enabled": False,
                            "subagents_enabled": False,
                        },
                    )
                    session_id = session["session_id"]
                    thread_id = session["payload"]["thread_id"]
                    submitted = await req(
                        "POST",
                        f"/api/equipment/deep-thinking/{session_id}/messages",
                        json={"content": prompt, "model_spec": model},
                    )
                    run_id = submitted["request"]["run_id"]
                record = {
                    "name": name,
                    "topic": topic,
                    "kind": kind,
                    "variant": variant,
                    "thread_id": thread_id,
                    "session_id": session_id,
                    "run_id": run_id,
                    "prompt": prompt,
                    "submitted_at_utc": datetime.now(UTC).isoformat(),
                }
                manifest["cases"].append(record)
                save("manifest.json", manifest)
                save(f"{name}.json", record)
                print(json.dumps({"submitted": name, "run_id": run_id}), flush=True)
                started = time.monotonic()
                last_status = None
                while time.monotonic() - started < 300:
                    result = await req("GET", f"/api/agent/runs/{run_id}/result")
                    status = result["status"]
                    if status != last_status:
                        print(
                            json.dumps(
                                {"case": name, "status": status, "elapsed": round(time.monotonic() - started, 1)}
                            ),
                            flush=True,
                        )
                        last_status = status
                    if status in {"completed", "failed", "cancelled", "interrupted"}:
                        break
                    await asyncio.sleep(8)
                if result["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
                    await req("POST", f"/api/agent/runs/{run_id}/cancel", json={})
                    record["watchdog"] = "Verification exceeded 300 seconds; cancellation requested"
                    result = await req("GET", f"/api/agent/runs/{run_id}/result")
                record["elapsed_seconds"] = round(time.monotonic() - started, 2)
                record["result"] = result
                audits = await req("GET", f"/api/chat/thread/{thread_id}/audits")
                record["tools"] = [
                    {
                        k: item.get(k)
                        for k in ("run_id", "tool_name", "tool_input", "tool_output", "error_message", "status")
                    }
                    for item in audits["audits"]
                    if item.get("type") == "tool"
                ]
                async with pg_manager.get_async_session_context() as db:
                    calls = (
                        await db.scalars(
                            select(AcademicRetrievalCall)
                            .where(AcademicRetrievalCall.root_run_id == run_id)
                            .order_by(AcademicRetrievalCall.created_at)
                        )
                    ).all()
                    record["aminer_ledger"] = [
                        {
                            "endpoint": x.endpoint,
                            "status": x.status,
                            "cost_cents": x.cost_cents,
                            "attempt": x.attempt_no,
                            "created_at": x.created_at,
                            "finished_at": x.finished_at,
                        }
                        for x in calls
                    ]
                record["estimated_aminer_cost_cents"] = sum(x["cost_cents"] for x in record["aminer_ledger"])
                record["academic_tool_calls"] = sum(
                    str(x.get("tool_name", "")).startswith("academic_") for x in record["tools"]
                )
                record["web_tool_calls"] = sum(x.get("tool_name") == "web_search" for x in record["tools"])
                record["answer_urls"] = sorted(set(re.findall(r"https?://[^\s<>\]\)]+", result.get("output") or "")))
                save(f"{name}.json", record)
                print(
                    json.dumps(
                        {
                            "finished": name,
                            "status": result["status"],
                            "seconds": record["elapsed_seconds"],
                            "academic_tools": record["academic_tool_calls"],
                            "web_tools": record["web_tool_calls"],
                            "ledger_calls": len(record["aminer_ledger"]),
                            "cost_cents": record["estimated_aminer_cost_cents"],
                        }
                    ),
                    flush=True,
                )
                return record

            # Four independent conversations at a time; no child agent delegation.
            for topic in TOPICS:
                results = await asyncio.gather(
                    *(case(topic, kind, variant) for kind in KINDS for variant in VARIANTS),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        print(json.dumps({"error": type(result).__name__, "message": str(result)}), flush=True)
            manifest["finished_at_utc"] = datetime.now(UTC).isoformat()
            save("manifest.json", manifest)
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
