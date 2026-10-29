"""生产环境交付前真实验收；所有写入限定到一次性测试账号。"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import shutil
import time
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import (
    AgentEnv,
    AgentRun,
    Department,
    OperationLog,
    User,
    UserConfig,
)
from platform_core.storage.postgres.models_equipment import EquipmentQuery
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir


BASE_URL = "https://www.deepquest.space"
ROOT = Path("/app/outputs/final-delivery-acceptance-20261029")
STATE_PATH = ROOT / "state.private.json"
REPORT_PATH = ROOT / "acceptance-report.json"
PREFIX = "DEEP_RESEARCH_TEST_FINAL_DELIVERY_20261029_"
TERMINAL = {"completed", "failed", "cancelled", "interrupted", "rejected"}


def load(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return fallback


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def state() -> dict:
    return load(STATE_PATH, {})


def report() -> dict:
    return load(REPORT_PATH, {"suite": "final-delivery-acceptance-20261029", "phases": {}})


async def ensure_user() -> dict:
    current = state()
    if current.get("uid"):
        return current
    uid = "qa_final_" + uuid4().hex[:12]
    async with pg_manager.get_async_session_context() as db:
        department_id = await db.scalar(select(Department.id).limit(1))
        user = User(
            uid=uid,
            username=uid,
            password_hash=AuthUtils.hash_password(secrets.token_urlsafe(24)),
            role="user",
            department_id=department_id,
        )
        db.add(user)
        await db.flush()
        current = {
            "uid": uid,
            "user_id": user.id,
            "created_at": time.time(),
            "thread_ids": [],
            "deep_session_ids": [],
            "task_ids": [],
            "kb_ids": [],
        }
    save(STATE_PATH, current)
    return current


async def token_for(current: dict) -> str:
    async with pg_manager.get_async_session_context() as db:
        user = await db.scalar(select(User).where(User.uid == current["uid"], User.is_deleted == 0))
        if user is None:
            raise RuntimeError("验收账号不存在")
        return AuthUtils.create_access_token({"sub": str(user.id)})


async def client_for(current: dict) -> httpx.AsyncClient:
    token = await token_for(current)
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": "Bearer " + token},
        timeout=httpx.Timeout(120, connect=20),
        trust_env=False,
    )


async def api(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.status_code not in {200, 201, 202}:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:1200]}")
    if not response.content:
        return {}
    content_type = response.headers.get("content-type", "")
    return response.json() if "json" in content_type else response.text


def update_state(**changes) -> dict:
    current = state()
    for key, value in changes.items():
        if key.endswith("_append"):
            target = key.removesuffix("_append")
            current.setdefault(target, []).append(value)
        else:
            current[key] = value
    save(STATE_PATH, current)
    return current


async def wait_agent_run(client: httpx.AsyncClient, request_id: str, run_id: str | None, timeout: float) -> dict:
    started = time.monotonic()
    last_status = ""
    while time.monotonic() - started < timeout:
        if not run_id:
            request = (await api(client, "GET", f"/api/agent/requests/{request_id}"))["request"]
            run_id = request.get("run_id") or request.get("dispatched_run_id")
            last_status = str(request.get("status") or last_status)
        if run_id:
            payload = await api(client, "GET", f"/api/agent/runs/{run_id}")
            row = payload.get("run") if isinstance(payload, dict) and isinstance(payload.get("run"), dict) else payload
            status = str(row.get("status") or "")
            last_status = status or last_status
            if status in TERMINAL:
                result = await api(client, "GET", f"/api/agent/runs/{run_id}/result")
                return {
                    "request_id": request_id,
                    "run_id": run_id,
                    "status": status,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "result": result,
                }
        await asyncio.sleep(2)
    raise TimeoutError(f"Agent Run 超时: request={request_id}, run={run_id}, last={last_status}")


def output_text(result: dict) -> str:
    value = result.get("result", result)
    for _ in range(6):
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return ""
        for key in ("output", "answer", "content", "final_output"):
            if isinstance(value.get(key), str):
                return value[key]
        value = value.get("result")
    return ""


async def run_chat_case(client: httpx.AsyncClient, agent_slug: str, name: str, prompt: str) -> dict:
    title = f"DEEP_RESEARCH_TEST_CONVERSATION_final-{name}-{uuid4().hex[:10]}"
    thread = await api(
        client,
        "POST",
        "/api/chat/thread",
        json={
            "agent_id": agent_slug,
            "title": title,
            "metadata": {"_deep_research_test": True, "_deep_research_e2e": True, "test": f"final-{name}"},
        },
    )
    thread_id = str(thread.get("thread_id") or thread.get("id"))
    update_state(thread_ids_append=thread_id)
    submitted = await api(
        client,
        "POST",
        "/api/agent/runs",
        json={
            "query": prompt,
            "agent_slug": agent_slug,
            "thread_id": thread_id,
            # messages.request_id is VARCHAR(64); keep the live acceptance ID
            # recognizable while leaving room for a collision-resistant suffix.
            "meta": {"request_id": f"qa-final-{name[:20]}-{uuid4().hex[:16]}"},
            "tool_approval_mode": "always_trust",
            "queue_policy": "enqueue",
        },
    )
    completed = await wait_agent_run(
        client,
        str(submitted["request_id"]),
        submitted.get("run_id"),
        timeout=1200,
    )
    text_output = output_text(completed["result"])
    return {
        "name": name,
        "thread_id": thread_id,
        "run_id": completed["run_id"],
        "status": completed["status"],
        "elapsed_seconds": completed["elapsed_seconds"],
        "output_characters": len(text_output),
        "has_citation": "<cite" in text_output or "http" in text_output,
        "output_excerpt": text_output[:1800],
    }


async def phase_chat() -> None:
    current = await ensure_user()
    taskbook = Path("/tmp/final-taskbook.md").read_text(errors="replace")[:10000]
    async with await client_for(current) as client:
        ready = await api(client, "GET", "/api/system/ready")
        default = await api(client, "GET", "/api/agent/default")
        agent_slug = str(default["agent"]["slug"])
        cases = [
            (
                "general",
                "用不超过500字解释为什么海水通常呈蓝色，并区分瑞利散射、选择性吸收和天空反射的作用；不需要检索时不要为了形式调用工具。",
            ),
            (
                "rare-equipment",
                """请委派1名调研探索员研究罕见技术术语“magneto-ionic protonation control of exchange bias”。探索员首个检索必须调用 parallel_research_search，要求 Open WebSearch、SearXNG、AMiner 三渠道并行；随后只读取最相关论文摘要。请给出可验证的物理机制、可用于新质装备的工程实现边界、TRL/实验缺口，并逐条保留真实来源。不要把仅元数据当作完整论文结论。""",
            ),
            (
                "long-taskbook",
                """下面是一份长任务书正文。请把它转化为可执行的90天研究推进方案：列出目标树、工作包、前后依赖、动态蜂群角色、每阶段输入输出、质量门、证据门、风险与停止条件；不得启动真实研究任务，只做规划。任务书正文如下：\n\n"""
                + taskbook,
            ),
        ]
        rows = await asyncio.gather(*(run_chat_case(client, agent_slug, name, prompt) for name, prompt in cases))
    gate = {
        "public_ready": ready.get("status") == "ready" and not ready.get("degraded"),
        "all_completed": all(row["status"] == "completed" for row in rows),
        "all_substantive": all(row["output_characters"] >= 300 for row in rows),
        "rare_case_has_citation": next(row for row in rows if row["name"] == "rare-equipment")["has_citation"],
    }
    result = {"status": "passed" if all(gate.values()) else "failed", "gate": gate, "cases": rows}
    current_report = report()
    current_report["phases"]["intelligent_dialogue"] = result
    save(REPORT_PATH, current_report)
    print(json.dumps(result, ensure_ascii=False), flush=True)


async def phase_research() -> None:
    current = await ensure_user()
    resume_existing = bool(current.get("run_id") and current.get("query_id") and current.get("source_query"))
    if resume_existing:
        source_snapshot = dict(current["source_query"])
        query_id = str(current["query_id"])
        query_version = int(current.get("query_version") or 1)
        project_id = str(current.get("project_id") or "")
        run_id = str(current["run_id"])
    else:
        async with pg_manager.get_async_session_context() as db:
            source = await db.scalar(
                select(EquipmentQuery)
                .where(EquipmentQuery.status == "published", EquipmentQuery.owner_uid != current["uid"])
                .order_by(func.random())
                .limit(1)
            )
            if source is None:
                source = await db.scalar(
                    select(EquipmentQuery).where(EquipmentQuery.owner_uid != current["uid"]).order_by(func.random()).limit(1)
                )
            if source is None:
                raise RuntimeError("Query 库中没有可用于随机验收的 Query")
            source_snapshot = {
                "id": source.id,
                "query": source.query_text,
                "supplemental_information": source.supplemental_information or "",
                "status": source.status,
            }
    async with await client_for(current) as client:
        if not resume_existing:
            clone = await api(
                client,
                "POST",
                "/api/equipment/queries",
                json={
                    "project_id": None,
                    "query": source_snapshot["query"],
                    "supplemental_information": (
                        source_snapshot["supplemental_information"]
                        + "\n\n交付前真实验收：动态蜂群模式，必须区分公开证据、推断和待验证假设。"
                    )[:8000],
                    "generation_rationale": f"随机抽取既有 Query {source_snapshot['id']} 的隔离验收副本",
                    "source_references": [],
                    "status": "published",
                    "knowledge_enabled": False,
                    "knowledge_ids": [],
                },
            )
            query_id = str(clone.get("query_id") or clone.get("id"))
            query_version = int(clone.get("version") or 1)
            project_id = str(clone.get("project_id") or "")
            update_state(query_id=query_id, query_version=query_version, project_id=project_id, source_query=source_snapshot)
            created = await api(
                client,
                "POST",
                "/api/equipment/runs",
                headers={"Idempotency-Key": PREFIX + "research_" + uuid4().hex},
                json={
                    "project_id": None,
                    "topic": source_snapshot["query"],
                    "source_query_id": query_id,
                    "source_query_version": query_version,
                    "knowledge_enabled": False,
                    "knowledge_ids": [],
                    "supplemental_information": (
                        source_snapshot["supplemental_information"]
                        + "\n\n执行生产环境交付验收；使用真实公开检索，最终结论必须带证据边界。"
                    )[:8000],
                    "interaction_mode": "autonomous",
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                    "report_template_mode": "three_layer_nine_item",
                    "selected_agent_ids": [],
                    "max_rounds": 1,
                    "payload": {"analyst_confirmed": True, "acceptance_marker": PREFIX},
                },
            )
            run_id = str(created["run_id"])
            update_state(run_id=run_id, project_id=str(created.get("project_id") or project_id))
            await api(client, "POST", f"/api/equipment/runs/{run_id}/start")
        started = time.monotonic()
        statuses = ["resumed"] if resume_existing else []
        final = {}
        while time.monotonic() - started < 3600:
            final = await api(client, "GET", f"/api/equipment/runs/{run_id}")
            status = str(final.get("status") or "")
            if not statuses or statuses[-1] != status:
                statuses.append(status)
                print(json.dumps({"phase": "research", "status": status, "elapsed": round(time.monotonic() - started)}, ensure_ascii=False), flush=True)
            if status in {"completed", "failed", "cancelled", "paused", "archived"}:
                break
            await asyncio.sleep(5)
        report_text = await api(client, "GET", f"/api/equipment/runs/{run_id}/report") if final.get("status") == "completed" else ""
        versions_payload = await api(client, "GET", f"/api/equipment/runs/{run_id}/capability-versions")
        versions = versions_payload.get("versions", versions_payload) if isinstance(versions_payload, dict) else versions_payload
        events = await api(client, "GET", f"/api/equipment/runs/{run_id}/events")
        event_types = [str(row.get("event_type") or row.get("type") or "") for row in events if isinstance(row, dict)]
        dynamic_events = [value for value in event_types if "dynamic" in value or "agent_" in value]
        async with pg_manager.get_async_session_context() as db:
            model_calls = (
                await db.execute(
                    text("SELECT status,count(*) AS n FROM platform_model_calls WHERE run_id=:run GROUP BY status"),
                    {"run": run_id},
                )
            ).mappings().all()
        completed_model_calls = sum(int(row["n"]) for row in model_calls if row["status"] == "completed")
    gate = {
        "completed": final.get("status") == "completed",
        "real_model_calls": completed_model_calls > 0,
        "report_substantive": isinstance(report_text, str) and len(report_text) >= 2000,
        "capability_portraits": isinstance(versions, list) and len(versions) > 0,
        "dynamic_swarm_events": len(dynamic_events) > 0,
        "source_query_lineage": str(final.get("source_query_id") or "") == query_id
        or str((final.get("payload") or {}).get("source_query_id") or "") == query_id,
        "projectless_creation": bool(current.get("project_id") or state().get("project_id")),
    }
    result = {
        "status": "passed" if all(gate.values()) else "failed",
        "gate": gate,
        "source_query": source_snapshot,
        "test_query_id": query_id,
        "run_id": run_id,
        "run_statuses": statuses,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "report_characters": len(report_text) if isinstance(report_text, str) else 0,
        "capability_version_count": len(versions) if isinstance(versions, list) else 0,
        "dynamic_event_count": len(dynamic_events),
        "completed_model_calls": completed_model_calls,
    }
    current_report = report()
    current_report["phases"]["dynamic_swarm_research"] = result
    save(REPORT_PATH, current_report)
    print(json.dumps(result, ensure_ascii=False), flush=True)


async def phase_deep_feedback() -> None:
    current = state()
    if not current.get("run_id"):
        raise RuntimeError("请先完成 research 阶段")
    run_id = current["run_id"]
    async with await client_for(current) as client:
        versions_payload = await api(client, "GET", f"/api/equipment/runs/{run_id}/capability-versions")
        versions = versions_payload.get("versions", versions_payload) if isinstance(versions_payload, dict) else versions_payload
        if not isinstance(versions, list) or not versions:
            raise RuntimeError("研究任务没有能力画像版本")
        card = versions[0]
        version_id = str(card.get("version_id") or card.get("id"))
        card_snapshot = card.get("snapshot") if isinstance(card.get("snapshot"), dict) else card
        capability_id = str(card_snapshot.get("capability_id") or card_snapshot.get("id") or "")
        # Formal S6 baseline versions are already immutable/verified.  The API
        # correctly rejects attempts to mutate them, but they remain valid
        # targets for expert feedback and evolution learning.
        if not version_id.startswith("baseline-"):
            await api(
                client,
                "POST",
                f"/api/equipment/runs/{run_id}/capability-versions/{version_id}/verify",
                json={"status": "verified"},
            )
        feedback_response = await api(
            client,
            "POST",
            f"/api/equipment/runs/{run_id}/expert-feedback",
            json={
                "capability_id": capability_id,
                "capability_version_id": version_id,
                "capability_name": str(card_snapshot.get("name") or "验收能力画像"),
                "comment": "审批通过，但技术实现必须补充接口时序、闭环控制、失效安全和分阶段实物验证指标，禁止把论文概念直接写成已工程化能力。",
                "verdict": "approved",
                "rating": 5,
                "dimensions": ["technology_implementation", "evidence_boundary"],
                "target_agent_ids": ["S4", "S6"],
                "stage_scope": ["S4", "S6"],
                "reviewer_role": "expert",
            },
        )
        feedback = feedback_response["feedback"]
        feedback_id = str(feedback["feedback_id"])
        update_state(feedback_id=feedback_id, capability_version_id=version_id)
        sections = []
        modules = card_snapshot.get("capability_portrait_modules") or card_snapshot.get("modules") or {}
        if isinstance(modules, dict):
            labels = {
                "overview": "概述",
                "technology_implementation": "装备与技术实现",
                "operational_process": "关键作战流程",
                "capability_effects": "形成能力与作战效果",
                "winning_logic": "制胜逻辑机理",
            }
            for key, label in labels.items():
                value = modules.get(key)
                if isinstance(value, str) and value.strip():
                    sections.append({"label": label, "text": value[:4000]})
        deep = await api(
            client,
            "POST",
            "/api/equipment/deep-thinking",
            json={
                "project_id": None,
                "title": "DEEP_RESEARCH_TEST_CONVERSATION_final-deep-tech-" + uuid4().hex[:8],
                "topic": str(card_snapshot.get("name") or state().get("source_query", {}).get("query") or "装备技术实现"),
                "focus": "把能力画像的装备与技术实现深化为可执行技术方案",
                "run_id": run_id,
                "knowledge_enabled": False,
                "knowledge_ids": [],
                "subagents_enabled": True,
                "research_mode": "section_deepen",
                "research_section": "装备与技术实现",
                "source_feedback_id": feedback_id,
                "capability_card_key": capability_id,
                "capability_name": str(card_snapshot.get("name") or "验收能力画像"),
                "capability_sections": sections,
            },
        )
        session_id = str(deep.get("session_id") or deep.get("id"))
        update_state(deep_session_ids_append=session_id)
        sent = await api(
            client,
            "POST",
            f"/api/equipment/deep-thinking/{session_id}/messages",
            json={
                "content": "基于已审批画像和专家反馈，深化一个可实施技术方案。必须给出系统组成、接口与数据流、关键算法/控制环、硬件选型边界、试验件分级、验证指标、故障与降级策略、12个月里程碑；调用调研探索员核验罕见术语或关键论文，不得虚构参数。",
                "create_artifact": False,
            },
        )
        request = sent.get("request", sent)
        completed = await wait_agent_run(
            client,
            str(request["request_id"]),
            request.get("run_id"),
            timeout=1800,
        )
        text_output = output_text(completed["result"])
        session = await api(client, "GET", f"/api/equipment/deep-thinking/{session_id}")
        payload = session.get("payload", session)
        snapshot = payload.get("source_feedback_snapshot") or {}
    gate = {
        "feedback_processed": feedback.get("learning_status") in {"processed", "deduplicated"},
        "approval_bound_to_session": str(snapshot.get("feedback_id") or "") == feedback_id,
        "deep_completed": completed["status"] == "completed",
        "deep_substantive": len(text_output) >= 1200,
        "implementation_specific": sum(term in text_output for term in ("接口", "验证", "故障", "里程碑")) >= 3,
        "projectless_deep_session": bool(session_id),
    }
    result = {
        "status": "passed" if all(gate.values()) else "failed",
        "gate": gate,
        "feedback_id": feedback_id,
        "feedback_learning_status": feedback.get("learning_status"),
        "feedback_memory_status": feedback.get("memory_status"),
        "feedback_effect_status": feedback.get("effect_status"),
        "session_id": session_id,
        "deep_run_id": completed["run_id"],
        "elapsed_seconds": completed["elapsed_seconds"],
        "output_characters": len(text_output),
        "output_excerpt": text_output[:2200],
    }
    current_report = report()
    current_report["phases"]["capability_feedback_and_deep_research"] = result
    save(REPORT_PATH, current_report)
    print(json.dumps(result, ensure_ascii=False), flush=True)


async def phase_cleanup() -> None:
    current = state()
    if not current.get("uid"):
        print(json.dumps({"status": "already_clean"}, ensure_ascii=False))
        return
    from live_api_cleanup import cleanup_test_chat_resources
    from platform_core.services import collection_artifact_service, wechat_mp_service

    errors = []
    before = {}
    async with pg_manager.get_async_session_context() as db:
        for table in (
            "users",
            "projects",
            "conversations",
            "agent_runs",
            "equipment_research_runs",
            "equipment_queries",
            "equipment_deep_sessions",
            "equipment_expert_feedback",
            "tasks",
        ):
            try:
                before[table] = int(
                    await db.scalar(text(f"SELECT count(*) FROM {table} WHERE " + (
                        "uid=:uid" if table in {"users", "conversations", "agent_runs"}
                        else "owner_uid=:uid" if table.startswith("equipment_")
                        else "payload->>'operator_id'=:uid" if table == "tasks"
                        else "uid=:uid"
                    )), {"uid": current["uid"]})
                    or 0
                )
            except Exception:
                await db.rollback()
    async with await client_for(current) as client:
        for session_id in reversed(current.get("deep_session_ids", [])):
            response = await client.delete(f"/api/equipment/deep-thinking/{session_id}")
            if response.status_code not in {200, 404}:
                errors.append(f"deep_session:{session_id}:{response.status_code}")
        if current.get("feedback_id") and current.get("run_id"):
            response = await client.post(
                f"/api/equipment/runs/{current['run_id']}/expert-feedback/{current['feedback_id']}/rollback",
                json={"reason": "交付前验收数据清理"},
            )
            if response.status_code not in {200, 404}:
                errors.append(f"feedback:{response.status_code}")
        if current.get("run_id"):
            run_response = await client.get(f"/api/equipment/runs/{current['run_id']}")
            if run_response.status_code == 200:
                status = str(run_response.json().get("status") or "")
                if status not in {"completed", "failed", "cancelled", "archived", "paused"}:
                    await client.post(f"/api/equipment/runs/{current['run_id']}/cancel")
                    for _ in range(60):
                        row = await client.get(f"/api/equipment/runs/{current['run_id']}")
                        if row.status_code != 200 or row.json().get("status") in {"completed", "failed", "cancelled", "archived", "paused"}:
                            break
                        await asyncio.sleep(1)
                delete_response = await client.delete(f"/api/equipment/runs/{current['run_id']}")
                if delete_response.status_code not in {200, 404}:
                    errors.append(f"run:{delete_response.status_code}:{delete_response.text[:200]}")
        if current.get("query_id"):
            query_response = await client.get(f"/api/equipment/queries/{current['query_id']}")
            if query_response.status_code == 200:
                version = int(query_response.json().get("version") or current.get("query_version") or 1)
                delete_response = await client.delete(
                    f"/api/equipment/queries/{current['query_id']}", params={"expected_version": version}
                )
                if delete_response.status_code not in {200, 404}:
                    errors.append(f"query:{delete_response.status_code}:{delete_response.text[:200]}")
        for task_id in current.get("task_ids", []):
            for prefix in ("/api/knowledge/wxchannels/tasks/", "/api/tasks/"):
                response = await client.delete(prefix + task_id)
                if response.status_code in {200, 404}:
                    break
        for kb_id in current.get("kb_ids", []):
            response = await client.delete(f"/api/knowledge/databases/{kb_id}")
            if response.status_code not in {200, 404}:
                errors.append(f"kb:{kb_id}:{response.status_code}")
        try:
            await cleanup_test_chat_resources(client, dict(client.headers), owner_uid=current["uid"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"chat_cleanup:{type(exc).__name__}:{exc}")
        if current.get("project_id"):
            response = await client.delete(f"/api/projects/{current['project_id']}")
            if response.status_code not in {200, 404}:
                errors.append(f"project:{response.status_code}")
    async with pg_manager.get_async_session_context() as db:
        user = await db.scalar(select(User).where(User.uid == current["uid"]).with_for_update())
        if user is not None:
            for model, column, value in (
                (OperationLog, OperationLog.user_id, user.id),
                (AgentEnv, AgentEnv.uid, current["uid"]),
                (UserConfig, UserConfig.uid, current["uid"]),
            ):
                await db.execute(delete(model).where(column == value))
            await db.delete(user)
    shutil.rmtree(wechat_mp_service.data_root() / wechat_mp_service.owner_key(current["uid"]), ignore_errors=True)
    shutil.rmtree(collection_artifact_service.manifest_directory(current["uid"]), ignore_errors=True)
    directory = global_user_data_dir(current["uid"])
    if directory.exists() and directory.name == current["uid"]:
        shutil.rmtree(directory)
    async with pg_manager.get_async_session_context() as db:
        remaining = {
            "users": int(await db.scalar(text("SELECT count(*) FROM users WHERE uid=:uid"), {"uid": current["uid"]}) or 0),
            "projects": int(await db.scalar(text("SELECT count(*) FROM projects WHERE uid=:uid"), {"uid": current["uid"]}) or 0),
            "conversations": int(await db.scalar(text("SELECT count(*) FROM conversations WHERE uid=:uid"), {"uid": current["uid"]}) or 0),
            "agent_runs": int(await db.scalar(text("SELECT count(*) FROM agent_runs WHERE uid=:uid"), {"uid": current["uid"]}) or 0),
            "research_runs": int(await db.scalar(text("SELECT count(*) FROM equipment_research_runs WHERE owner_uid=:uid"), {"uid": current["uid"]}) or 0),
            "queries": int(await db.scalar(text("SELECT count(*) FROM equipment_queries WHERE owner_uid=:uid"), {"uid": current["uid"]}) or 0),
            "deep_sessions": int(await db.scalar(text("SELECT count(*) FROM equipment_deep_sessions WHERE owner_uid=:uid"), {"uid": current["uid"]}) or 0),
            "feedback": int(await db.scalar(text("SELECT count(*) FROM equipment_expert_feedback WHERE owner_uid=:uid"), {"uid": current["uid"]}) or 0),
        }
    result = {"status": "passed" if not errors and not any(remaining.values()) else "failed", "before": before, "remaining": remaining, "errors": errors}
    current_report = report()
    current_report["cleanup"] = result
    current_report["finished_at"] = time.time()
    phase_statuses = [value.get("status") for value in current_report.get("phases", {}).values() if isinstance(value, dict)]
    current_report["overall_status"] = "passed" if result["status"] == "passed" and phase_statuses and all(value == "passed" for value in phase_statuses) else "failed"
    save(REPORT_PATH, current_report)
    STATE_PATH.unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False), flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["chat", "research", "deep-feedback", "cleanup"])
    args = parser.parse_args()
    pg_manager.initialize()
    try:
        await {
            "chat": phase_chat,
            "research": phase_research,
            "deep-feedback": phase_deep_feedback,
            "cleanup": phase_cleanup,
        }[args.phase]()
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
