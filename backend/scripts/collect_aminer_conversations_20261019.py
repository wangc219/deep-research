"""Read back persisted run/audit/ledger evidence for this verification only."""

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import AcademicRetrievalCall, AgentRun, User
from platform_core.utils.auth_utils import AuthUtils

ROOT = Path("/app/outputs/aminer-conversations-20261019")


def decoded(value):
    if isinstance(value, dict) and "content" in value:
        value = value["content"]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {"text": value}
    return value if isinstance(value, dict) else {}


async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            u = await db.scalar(
                select(User).where(User.role == "superadmin", User.is_deleted == 0).order_by(User.id).limit(1)
            )
            token = AuthUtils.create_access_token({"sub": str(u.id)}, expires_delta=timedelta(minutes=10))
        summary = []
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:5050", headers={"Authorization": "Bearer " + token}, timeout=120
        ) as client:
            for manifest_path in sorted(ROOT.rglob("manifest.json")):
                manifest = json.loads(manifest_path.read_text())
                for item in manifest["cases"]:
                    path = manifest_path.parent / (item["name"] + ".json")
                    record = json.loads(path.read_text()) if path.exists() else dict(item)
                    rid, tid = item["run_id"], item["thread_id"]
                    response = await client.get(f"/api/agent/runs/{rid}/result")
                    response.raise_for_status()
                    record["result"] = response.json()
                    response = await client.get(f"/api/chat/thread/{tid}/audits")
                    response.raise_for_status()
                    record["tools"] = [
                        {
                            k: a.get(k)
                            for k in ("run_id", "tool_name", "tool_input", "tool_output", "error_message", "status")
                        }
                        for a in response.json()["audits"]
                        if a.get("type") == "tool"
                    ]
                    if rid == "110d6bad-fb99-46c8-852e-1d551221d1b6":
                        record["watchdog"] = (
                            "Manually cancelled after 331 seconds without any tool call; "
                            "verification-only runner was stopped before starting another topic."
                        )
                    async with pg_manager.get_async_session_context() as db:
                        calls = (
                            await db.scalars(
                                select(AcademicRetrievalCall)
                                .where(AcademicRetrievalCall.root_run_id == rid)
                                .order_by(AcademicRetrievalCall.created_at)
                            )
                        ).all()
                        record["aminer_ledger"] = [
                            {
                                "endpoint": x.endpoint,
                                "status": x.status,
                                "cost_cents": x.cost_cents,
                                "attempt": x.attempt_no,
                                "created_at": str(x.created_at),
                                "finished_at": str(x.finished_at),
                                "provider_log_id": (x.result or {}).get("log_id"),
                                "result_status": (x.result or {}).get("status"),
                                "returned": len((x.result or {}).get("data") or []),
                            }
                            for x in calls
                        ]
                        children, frontier = [], [rid]
                        while frontier:
                            found = (
                                await db.scalars(select(AgentRun).where(AgentRun.created_by_run_id.in_(frontier)))
                            ).all()
                            children.extend(found)
                            frontier = [x.id for x in found]
                        record["child_runs"] = [
                            {"run_id": x.id, "thread_id": x.conversation_thread_id, "status": x.status}
                            for x in children
                        ]
                    record["child_tools"] = []
                    for child in record["child_runs"]:
                        response = await client.get(f"/api/chat/thread/{child['thread_id']}/audits")
                        response.raise_for_status()
                        record["child_tools"].extend(
                            {
                                k: a.get(k)
                                for k in ("run_id", "tool_name", "tool_input", "tool_output", "error_message", "status")
                            }
                            for a in response.json()["audits"]
                            if a.get("type") == "tool"
                        )
                    record["academic_evidence"] = []
                    for tool in [*record["tools"], *record["child_tools"]]:
                        if not str(tool["tool_name"]).startswith("academic_"):
                            continue
                        payload = decoded(tool["tool_output"])
                        record["academic_evidence"].append(
                            {
                                "tool": tool["tool_name"],
                                "run_id": tool.get("run_id"),
                                "input": tool["tool_input"],
                                "status": payload.get("status"),
                                "aminer_status": payload.get("aminer_status"),
                                "cached": payload.get("cached"),
                                "query_coverage": payload.get("query_coverage"),
                                "missing_paper_ids": payload.get("missing_paper_ids"),
                                "papers": [
                                    {
                                        k: p.get(k)
                                        for k in (
                                            "id",
                                            "doi",
                                            "title",
                                            "authors",
                                            "year",
                                            "venue",
                                            "url",
                                            "content_level",
                                            "content",
                                        )
                                    }
                                    for p in payload.get("results", [])
                                ],
                            }
                        )
                    full = {
                        p["id"]
                        for e in record["academic_evidence"]
                        for p in e["papers"]
                        if p["content_level"] == "abstract"
                    }
                    partial = {
                        p["id"]
                        for e in record["academic_evidence"]
                        for p in e["papers"]
                        if p["content_level"] == "partial_abstract"
                    }
                    record["academic_tool_calls"] = len(record["academic_evidence"])
                    record["web_tool_calls"] = sum(
                        t["tool_name"] == "web_search" for t in [*record["tools"], *record["child_tools"]]
                    )
                    record["estimated_aminer_cost_cents"] = sum(c["cost_cents"] for c in record["aminer_ledger"])
                    record["answer_urls"] = sorted(
                        set(re.findall(r"https?://[^\s<>\]\)\"]+", record["result"].get("output") or ""))
                    )
                    record["full_abstract_unique_count"] = len(full)
                    record["partial_abstract_unique_count"] = len(partial - full)
                    record["collected_at"] = datetime.now(UTC).isoformat()
                    path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
                    summary.append(
                        {
                            "file": str(path.relative_to(ROOT)),
                            "name": item["name"],
                            "kind": item["kind"],
                            "variant": item["variant"],
                            "run_id": rid,
                            "thread_id": tid,
                            "session_id": item.get("session_id"),
                            "status": record["result"]["status"],
                            "error": record["result"].get("error"),
                            "total_latency_ms": record["result"].get("timing", {}).get("total_latency_ms"),
                            "academic_tools": record["academic_tool_calls"],
                            "web_tools": record["web_tool_calls"],
                            "ledger_requests": len(record["aminer_ledger"]),
                            "estimated_aminer_cost_cents": record["estimated_aminer_cost_cents"],
                            "full_abstract_unique_count": len(full),
                            "partial_abstract_unique_count": len(partial - full),
                            "empty_search_terms": sum(
                                q.get("returned") == 0 and q.get("status") == "ok"
                                for e in record["academic_evidence"]
                                for q in e.get("query_coverage") or []
                            ),
                        }
                    )
        (ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
