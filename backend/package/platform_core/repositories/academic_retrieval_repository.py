"""论文检索账本与缓存；预占事务不包含外部 HTTP 请求。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config.options import aminer_api_opts
from platform_core.services.aminer_client import ENDPOINTS, aminer_credential_scope
from platform_core.storage.postgres.models_business import AcademicRetrievalCall, AgentRun, ConfigOption
from platform_core.utils.datetime_utils import utc_now_naive


@dataclass(frozen=True)
class AcademicReservation:
    """预占结果：命中缓存或已执行请求时无需再次请求供应商。"""

    call_id: str | None
    credentials: dict[str, Any]
    result: dict[str, Any] | None
    cached: bool = False


class AcademicRetrievalRepository:
    """串行化同一研究轮次的父子调用预算与幂等请求。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_root(self, *, run_id: str, uid: str, worker_id: str | None = None) -> AgentRun:
        """只沿服务端父运行关系解析预算归属，恢复运行沿用原轮次。"""
        run = await self.db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.uid == uid))
        if (
            run is None
            or run.status != "running"
            or (
                worker_id
                and (run.worker_id != worker_id or not run.lease_expires_at or run.lease_expires_at <= utc_now_naive())
            )
        ):
            raise ValueError("当前运行未持有学术检索执行权")
        visited: set[str] = set()
        while run.run_type in {"subagent", "resume"}:
            if run.id in visited or not run.created_by_run_id:
                raise ValueError("学术检索父运行关系无效")
            visited.add(run.id)
            run = await self.db.scalar(
                select(AgentRun).where(AgentRun.id == run.created_by_run_id, AgentRun.uid == uid)
            )
            if run is None:
                raise ValueError("学术检索父运行不存在")
        return run

    async def reserve(
        self,
        *,
        root_run_id: str,
        run_id: str,
        uid: str,
        endpoint: str,
        request_key: str,
        attempt_no: int,
        credential_scope: str,
        adaptive_long_running: bool = False,
    ) -> AcademicReservation:
        """锁定配置与父 Run 后预占预算；调用方提交后才能发送 HTTP。"""
        await self.db.scalar(select(ConfigOption).where(ConfigOption.key == aminer_api_opts.key).with_for_update())
        config = await aminer_api_opts.get(self.db)
        if not config["enabled"]:
            return AcademicReservation(None, {}, {"status": "disabled", "message": "AMiner 学术检索已停用"})
        if credential_scope != aminer_credential_scope(config):
            return AcademicReservation(None, {}, {"status": "configuration_changed", "message": "AMiner 配置已更新"})
        root = await self.db.scalar(
            select(AgentRun).where(AgentRun.id == root_run_id, AgentRun.uid == uid).with_for_update()
        )
        if root is None:
            raise ValueError("学术检索父运行不存在")

        ttl = 3600 if endpoint in {"search", "question_search", "title_search", "semantic_search"} else 86400
        cached = await self.db.scalar(
            select(AcademicRetrievalCall)
            .where(
                AcademicRetrievalCall.request_key == request_key,
                AcademicRetrievalCall.status == "succeeded",
                AcademicRetrievalCall.finished_at > utc_now_naive() - timedelta(seconds=ttl),
            )
            .order_by(AcademicRetrievalCall.finished_at.desc())
            .limit(1)
        )
        if cached:
            return AcademicReservation(None, {}, dict(cached.result), cached=True)

        previous = await self.db.scalar(
            select(AcademicRetrievalCall).where(
                AcademicRetrievalCall.root_run_id == root_run_id,
                AcademicRetrievalCall.request_key == request_key,
                AcademicRetrievalCall.attempt_no == attempt_no,
            )
        )
        if previous:
            result = previous.result or {
                "status": "in_progress",
                "message": "相同检索已预占或执行中，请使用其他已有证据",
            }
            return AcademicReservation(None, {}, dict(result), cached=previous.status == "succeeded")

        prefix = "deep" if root.source == "equipment_deep_research" or root.agent_slug == "deep-research" else "chat"
        costs = await self.db.execute(
            select(AcademicRetrievalCall.endpoint, func.count(), func.sum(AcademicRetrievalCall.cost_cents))
            .where(AcademicRetrievalCall.root_run_id == root_run_id)
            .group_by(AcademicRetrievalCall.endpoint)
        )
        used = list(costs.all())
        _method, _path, cost, kind = ENDPOINTS[endpoint]
        spent = sum(int(row[2]) for row in used)
        budget_cents = int(config[f"{prefix}_budget_cents"])
        if budget_cents > 0 and spent + cost > budget_cents:
            return AcademicReservation(
                None, {}, {"status": "budget_exhausted", "message": "本轮 AMiner 费用预算已用尽"}
            )
        # 0 表示不设置应用侧额度；供应商限流、重复查询保护和 Agent
        # 总工具预算仍负责阻止失控请求。免费接口无需另设隐藏硬上限。
        limit = 0 if kind == "free" or adaptive_long_running else int(config[f"{prefix}_{kind}_limit"])
        count = sum(int(row[1]) for row in used if ENDPOINTS[row[0]][3] == kind)
        if limit > 0 and count >= limit:
            return AcademicReservation(
                None, {}, {"status": "limit_reached", "message": f"本轮 AMiner {kind} 调用次数已达上限"}
            )
        call = AcademicRetrievalCall(
            id=str(uuid4()),
            root_run_id=root_run_id,
            run_id=run_id,
            request_key=request_key,
            endpoint=endpoint,
            attempt_no=attempt_no,
            cost_cents=cost,
            status="pending",
        )
        self.db.add(call)
        await self.db.flush()
        return AcademicReservation(call.id, config, None)

    async def finish(self, call_id: str, result: dict[str, Any]) -> None:
        """写回供应商结果；失败及未知结果仍保留已预占费用。"""
        call = await self.db.get(AcademicRetrievalCall, call_id)
        if call is None:
            raise ValueError("学术检索预占记录不存在")
        call.status = "succeeded" if result["status"] == "ok" else "failed"
        call.result = result
        call.finished_at = utc_now_naive()
        await self.db.flush()
