"""前沿技术创意简报订阅、证据挖掘、评分和投递。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_int_env
from platform_core.knowledge.graphs.innovation_discovery import discover_innovation_hypotheses
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.runtime import knowledge_base
from platform_core.services.knowledge_source_connectors import collect_source_items
from platform_core.services.scheduled_agent_service import next_run_at, validate_schedule
from platform_core.services.task_service import Task, TaskContext, tasker
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge_governance import (
    BriefDeliveryOutbox,
    InnovationBrief,
    InnovationBriefRun,
    InnovationBriefSubscription,
    KnowledgeSource,
    KnowledgeSourceItem,
)
from platform_core.utils.datetime_utils import format_utc_datetime, utc_now

BRIEF_TASK_TYPE = "innovation_brief_generate"
ACTIVE_BRIEF_RUN_STATUSES = {"pending", "running"}
BRIEF_MAX_ITEMS = 10
BRIEF_HYPOTHESIS_RESERVED_SLOTS = 2
BRIEF_KNOWLEDGE_CONCURRENCY = 4
BRIEF_QUERY_PLANNING_TIMEOUT_SECONDS = 45
BRIEF_PREPARE_AHEAD_MINUTES = get_int_env("INNOVATION_BRIEF_PREPARE_AHEAD_MINUTES", 180, minimum=5)
BRIEF_RESEARCH_EXPLORER_MAX_WAIT_MINUTES = get_int_env(
    "INNOVATION_BRIEF_RESEARCH_MAX_WAIT_MINUTES",
    90,
    minimum=5,
)
BRIEF_RESEARCH_EXPLORER_CUTOFF_MINUTES = get_int_env(
    "INNOVATION_BRIEF_RESEARCH_CUTOFF_MINUTES",
    15,
    minimum=0,
)
BRIEF_RESEARCH_EXPLORER_RECHECK_SECONDS = get_int_env(
    "INNOVATION_BRIEF_RESEARCH_RECHECK_SECONDS",
    5,
    minimum=1,
)
BRIEF_RESEARCH_FINDING_LIMIT = 8
BRIEF_RESEARCH_HYPOTHESIS_LIMIT = 2
BRIEF_CONVERGENCE_TIMEOUT_SECONDS = get_int_env(
    "INNOVATION_BRIEF_CONVERGENCE_TIMEOUT_SECONDS",
    90,
    minimum=15,
)
BRIEF_CONVERGENCE_MAX_ATTEMPTS = 2
BRIEF_QUALITY_MIN_FINDINGS = 3
BRIEF_QUALITY_MIN_FACTS = 1
BRIEF_QUALITY_MIN_INFERENCES = 1
BRIEF_QUALITY_MIN_HYPOTHESES = 1
TERMINAL_AGENT_RUN_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
PRIORITY_TECHNOLOGY_TAXONOMY = (
    ("无人作战系统", "无人机、无人车、无人艇、无人潜航器、无人集群", "自主感知、智能决策、协同控制"),
    ("导弹武器系统", "防空导弹、反舰导弹、巡航导弹、弹道导弹", "制导导航、目标识别、飞行控制"),
    ("远程精确打击装备", "远程火箭炮、精确制导弹药、远程巡航打击平台", "精确定位、导航制导、体系协同"),
    ("反无人系统", "反无人机雷达、光电探测系统、电子干扰装备、拦截系统", "低慢小目标探测、多传感器融合"),
    ("高超声速武器装备", "高超声速滑翔飞行器、高超声速巡航飞行器", "高温材料、高速飞行、热防护"),
    ("定向能武器装备", "激光武器、高功率微波装备", "高能激光、微波技术、能源管理"),
    ("智能弹药与巡飞装备", "智能炮弹、巡飞弹、末制导弹药", "智能感知、自主导航、精确控制"),
    ("智能化空中作战平台", "新一代战斗机、无人僚机、智能空战平台", "人机协同、态势感知、任务规划"),
    ("新型陆战装备", "无人战车、机器人作战平台、智能装甲车辆", "自主驾驶、战场感知、平台协同"),
    ("新型海上作战装备", "无人水面舰艇、无人潜航器、新型水下探测平台", "水下通信、自主航行、海洋感知"),
    ("空天攻防装备", "军用卫星、空间态势感知系统、反卫星装备", "空间探测、轨道监测、卫星防护"),
    ("电子战与电磁攻防装备", "电子侦察、通信干扰、雷达对抗系统", "频谱感知、电磁环境认知"),
    ("网络空间作战装备", "网络防护平台、网络靶场、网络态势感知系统", "网络安全、威胁检测、自动化防御"),
    ("智能防空反导装备", "综合防空系统、反导预警系统、多层拦截体系", "多源探测、目标跟踪、指挥控制"),
    ("新型水下作战装备", "水下机器人、智能水雷探测与处置系统", "水声感知、水下自主控制"),
    ("智能指挥与作战支援装备", "智能指挥系统、战场信息融合平台、辅助决策系统", "多模态融合、知识推理、智能决策"),
    ("新型侦察监视装备", "高分辨率侦察卫星、合成孔径雷达、分布式传感器", "多源遥感、目标识别、信息融合"),
    ("新型通信与导航装备", "抗干扰通信终端、战术数据链、组合导航系统", "安全通信、导航增强、组网协同"),
    ("新概念作战装备", "仿生机器人、可变构型平台、跨域无人系统", "仿生控制、新材料、跨域自主协同"),
)
DEFAULT_TOPICS = [row[0] for row in PRIORITY_TECHNOLOGY_TAXONOMY]
DEFAULT_KEYWORDS = [
    "自主",
    "集群",
    "制导",
    "探测",
    "电子对抗",
    "定向能",
    "先进推进",
    "低成本精确打击",
    "高超声速",
    "高能激光",
    "高功率微波",
    "巡飞弹",
    "人机协同",
    "空天攻防",
    "水下自主",
    "频谱感知",
    "抗干扰通信",
    "多模态融合",
    "仿生控制",
]
DEFAULT_LANGUAGES = ["zh-CN", "en"]
OPEN_DISCOVERY_THEMES = (
    (
        "军事人工智能、认知域与网络攻防",
        "军事人工智能 认知域 网络攻防 人机协同 弱信号 新原理",
        "military AI cognitive warfare cyber operations human machine teaming weak signals new principles",
    ),
    (
        "量子感知、通信与先进传感",
        "量子感知 量子通信 先进传感 无源探测 导航定位 军事应用",
        "quantum sensing communication advanced sensors passive detection PNT military applications",
    ),
    (
        "空天、临近空间与海底作战",
        "空天 临近空间 海底作战 跨域载荷 新型武器 技术突破",
        "space near-space undersea warfare cross-domain payload novel weapons technology breakthrough",
    ),
    (
        "新材料、新能源、仿生、增材制造与先进推进",
        "新材料 新能源 仿生 增材制造 先进推进 军事颠覆技术 工程验证",
        "advanced materials energy biomimetics additive manufacturing propulsion disruptive defense technology",
    ),
)
OPEN_DISCOVERY_RELEVANCE_TERMS = {
    "军事人工智能",
    "认知域",
    "网络攻防",
    "量子感知",
    "量子通信",
    "先进传感",
    "临近空间",
    "海底作战",
    "新材料",
    "新能源",
    "仿生",
    "增材制造",
    "先进推进",
    "military ai",
    "cognitive warfare",
    "cyber operations",
    "quantum sensing",
    "quantum communication",
    "near-space",
    "undersea warfare",
    "advanced materials",
    "additive manufacturing",
    "advanced propulsion",
}
TRUSTED_FIRST_PARTY_SUFFIXES = (".gov", ".gov.cn", ".mil", ".mil.cn", ".int")
DISRUPTION_TERMS = {
    "自主",
    "集群",
    "协同",
    "智能",
    "高超声速",
    "定向能",
    "量子",
    "低成本",
    "颠覆",
    "autonomous",
    "swarm",
    "hypersonic",
    "directed energy",
    "cognitive warfare",
    "quantum sensing",
    "advanced materials",
    "additive manufacturing",
    "advanced propulsion",
    "breakthrough",
}
INNOVATION_EXPANSION_TERMS = {
    "新概念",
    "新原理",
    "跨域",
    "异构",
    "组合",
    "融合",
    "仿生",
    "可变构型",
    "分布式",
    "无源",
    "自组织",
    "自适应",
    "认知",
    "涌现",
    "novel concept",
    "new principle",
    "cross-domain",
    "multi-domain",
    "heterogeneous",
    "convergence",
    "biomimetic",
    "morphing",
    "distributed",
    "passive",
    "self-organizing",
    "adaptive",
    "emergent",
}


class BriefDeliveryProvider(Protocol):
    """投递 Provider 统一契约。"""

    name: str

    async def enqueue(self, db: AsyncSession, brief: InnovationBrief) -> BriefDeliveryOutbox: ...


class InAppBriefDeliveryProvider:
    name = "in_app"

    async def enqueue(self, db: AsyncSession, brief: InnovationBrief) -> BriefDeliveryOutbox:
        existing = await db.scalar(
            select(BriefDeliveryOutbox).where(
                BriefDeliveryOutbox.brief_id == brief.id,
                BriefDeliveryOutbox.provider == self.name,
            )
        )
        if existing is not None:
            return existing
        scheduled_for = await db.scalar(
            select(InnovationBriefRun.scheduled_for).where(InnovationBriefRun.id == brief.run_id)
        )
        record = BriefDeliveryOutbox(
            id=uuid.uuid4().hex,
            brief_id=brief.id,
            owner_uid=brief.owner_uid,
            provider=self.name,
            status="delivered",
            payload={"brief_id": brief.id, "title": brief.title},
            scheduled_for=scheduled_for or brief.published_at,
            delivered_at=utc_now(),
        )
        db.add(record)
        return record


class DisabledWeComBriefDeliveryProvider:
    """企业微信预留 Provider；首版不保存凭据且不外发。"""

    name = "wecom"

    async def enqueue(self, db: AsyncSession, brief: InnovationBrief) -> BriefDeliveryOutbox:
        existing = await db.scalar(
            select(BriefDeliveryOutbox).where(
                BriefDeliveryOutbox.brief_id == brief.id,
                BriefDeliveryOutbox.provider == self.name,
            )
        )
        if existing is not None:
            return existing
        scheduled_for = await db.scalar(
            select(InnovationBriefRun.scheduled_for).where(InnovationBriefRun.id == brief.run_id)
        )
        record = BriefDeliveryOutbox(
            id=uuid.uuid4().hex,
            brief_id=brief.id,
            owner_uid=brief.owner_uid,
            provider=self.name,
            status="disabled",
            payload={"brief_id": brief.id, "enabled": False},
            scheduled_for=scheduled_for or brief.published_at,
        )
        db.add(record)
        return record


async def list_subscriptions(db: AsyncSession, *, tenant_id: str, owner_uid: str) -> dict:
    """读取当前用户订阅；首次访问时创建可编辑的默认订阅。"""
    rows = list(
        (
            await db.scalars(
                select(InnovationBriefSubscription)
                .where(
                    InnovationBriefSubscription.tenant_id == tenant_id,
                    InnovationBriefSubscription.owner_uid == owner_uid,
                )
                .order_by(InnovationBriefSubscription.created_at)
            )
        ).all()
    )
    if not rows:
        rows = [await _create_default_subscription(db, tenant_id=tenant_id, owner_uid=owner_uid)]
    return {"items": [_subscription_dict(row) for row in rows]}


async def create_subscription(
    db: AsyncSession,
    *,
    tenant_id: str,
    owner_uid: str,
    data: dict,
) -> dict:
    values = _subscription_values(data)
    await _validate_subscription_sources(db, tenant_id, values["source_ids"])
    row = InnovationBriefSubscription(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        owner_uid=owner_uid,
        **values,
    )
    db.add(row)
    await db.commit()
    return _subscription_dict(row)


async def update_subscription(
    db: AsyncSession,
    *,
    tenant_id: str,
    owner_uid: str,
    subscription_id: str,
    data: dict,
) -> dict:
    row = await _owned_subscription(db, tenant_id, owner_uid, subscription_id, lock=True)
    merged = {
        "name": row.name,
        "topics": row.topics,
        "keywords": row.keywords,
        "knowledge_ids": row.knowledge_ids,
        "source_ids": row.source_ids,
        "languages": row.languages,
        "timezone": row.timezone,
        "daily_enabled": row.daily_enabled,
        "weekly_enabled": row.weekly_enabled,
        "daily_cron": row.daily_cron,
        "weekly_cron": row.weekly_cron,
        "reminder_sensitivity": row.reminder_sensitivity,
        "significance_threshold": row.significance_threshold,
        "open_discovery_enabled": row.open_discovery_enabled,
        "research_explorer_enabled": row.research_explorer_enabled,
        "enabled": row.enabled,
        **data,
    }
    values = _subscription_values(merged)
    await _validate_subscription_sources(db, tenant_id, values["source_ids"])
    for key, value in values.items():
        setattr(row, key, value)
    scheduled_runs = list(
        (
            await db.scalars(
                select(InnovationBriefRun).where(
                    InnovationBriefRun.subscription_id == row.id,
                    InnovationBriefRun.scheduled_for.is_not(None),
                    InnovationBriefRun.status.in_({"pending", "running", "prepared"}),
                )
            )
        ).all()
    )
    for run in scheduled_runs:
        run.status = "cancelled"
        run.completed_at = run.completed_at or utc_now()
        run.stats = {**(run.stats or {}), "delivery_status": "cancelled_by_subscription_update"}
        prepared = await db.scalar(
            select(InnovationBrief).where(
                InnovationBrief.run_id == run.id,
                InnovationBrief.published_at.is_(None),
            )
        )
        if prepared is not None:
            await db.delete(prepared)
    await db.commit()
    return _subscription_dict(row)


async def delete_subscription(
    db: AsyncSession,
    *,
    tenant_id: str,
    owner_uid: str,
    subscription_id: str,
) -> None:
    row = await _owned_subscription(db, tenant_id, owner_uid, subscription_id, lock=True)
    await db.delete(row)
    await db.commit()


async def create_brief_run(
    db: AsyncSession,
    *,
    tenant_id: str,
    owner_uid: str,
    subscription_id: str,
    brief_type: str,
    trigger: str = "manual",
) -> dict:
    if brief_type not in {"daily", "weekly"}:
        raise HTTPException(status_code=422, detail="brief_type 必须是 daily 或 weekly")
    subscription = await _owned_subscription(db, tenant_id, owner_uid, subscription_id, lock=True)
    active = await db.scalar(
        select(InnovationBriefRun.id)
        .where(
            InnovationBriefRun.subscription_id == subscription.id,
            InnovationBriefRun.status.in_(ACTIVE_BRIEF_RUN_STATUSES),
            InnovationBriefRun.scheduled_for.is_(None),
        )
        .limit(1)
    )
    if active:
        raise HTTPException(status_code=409, detail="该订阅已有正在运行的简报任务")
    run = InnovationBriefRun(
        id=uuid.uuid4().hex,
        subscription_id=subscription.id,
        owner_uid=owner_uid,
        brief_type=brief_type,
        status="pending",
        stats={"trigger": trigger},
    )
    task = await tasker.create_in_session(
        db,
        name=f"生成{_brief_type_label(brief_type)}：{subscription.name}",
        task_type=BRIEF_TASK_TYPE,
        payload={"brief_run_id": run.id, "operator_id": owner_uid},
        payload_match={"subscription_id": subscription.id},
    )
    run.task_id = task.id
    db.add(run)
    await db.commit()
    await tasker.publish(task)
    return _run_dict(run)


async def list_brief_runs(
    db: AsyncSession,
    *,
    tenant_id: str,
    owner_uid: str,
    subscription_id: str | None = None,
) -> dict:
    statement = (
        select(InnovationBriefRun)
        .join(InnovationBriefSubscription)
        .where(
            InnovationBriefSubscription.tenant_id == tenant_id,
            InnovationBriefRun.owner_uid == owner_uid,
        )
    )
    if subscription_id:
        statement = statement.where(InnovationBriefRun.subscription_id == subscription_id)
    rows = list((await db.scalars(statement.order_by(InnovationBriefRun.created_at.desc()).limit(100))).all())
    return {"items": [_run_dict(row) for row in rows]}


async def list_briefs(
    db: AsyncSession,
    *,
    owner_uid: str,
    brief_type: str | None,
    unread: bool | None,
    page: int,
    page_size: int,
) -> dict:
    now = utc_now()
    published = InnovationBrief.published_at.is_not(None) & (InnovationBrief.published_at <= now)
    statement = select(InnovationBrief).where(InnovationBrief.owner_uid == owner_uid, published)
    count_statement = select(func.count(InnovationBrief.id)).where(InnovationBrief.owner_uid == owner_uid, published)
    if brief_type:
        statement = statement.where(InnovationBrief.brief_type == brief_type)
        count_statement = count_statement.where(InnovationBrief.brief_type == brief_type)
    if unread is not None:
        statement = statement.where(InnovationBrief.unread.is_(unread))
        count_statement = count_statement.where(InnovationBrief.unread.is_(unread))
    total = int(await db.scalar(count_statement) or 0)
    rows = list(
        (
            await db.scalars(
                statement.order_by(InnovationBrief.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    unread_count = int(
        await db.scalar(
            select(func.count(InnovationBrief.id)).where(
                InnovationBrief.owner_uid == owner_uid,
                InnovationBrief.unread.is_(True),
                published,
            )
        )
        or 0
    )
    return {
        "items": [_brief_dict(row, detail=False) for row in rows],
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "page_size": page_size,
    }


async def get_brief(db: AsyncSession, *, owner_uid: str, brief_id: str) -> dict:
    row = await db.scalar(
        select(InnovationBrief).where(
            InnovationBrief.id == brief_id,
            InnovationBrief.owner_uid == owner_uid,
            InnovationBrief.published_at.is_not(None),
            InnovationBrief.published_at <= utc_now(),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="简报不存在")
    return _brief_dict(row, detail=True)


async def mark_brief_read(db: AsyncSession, *, owner_uid: str, brief_id: str, read: bool) -> dict:
    row = await db.scalar(
        select(InnovationBrief)
        .where(
            InnovationBrief.id == brief_id,
            InnovationBrief.owner_uid == owner_uid,
            InnovationBrief.published_at.is_not(None),
            InnovationBrief.published_at <= utc_now(),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="简报不存在")
    row.unread = not read
    row.read_at = utc_now() if read else None
    await db.commit()
    return {"id": row.id, "unread": bool(row.unread), "read_at": format_utc_datetime(row.read_at)}


async def run_innovation_brief(context: TaskContext) -> dict:
    """执行查询扩展、多源取证、证据分层、创新发现和简报持久化。"""
    run_started = monotonic()
    run_id = str(context.payload["brief_run_id"])
    cancelled_result: dict | None = None
    async with pg_manager.get_async_session_context() as db:
        run = await db.get(InnovationBriefRun, run_id)
        if run is None:
            raise ValueError("简报运行不存在")
        subscription = await db.get(InnovationBriefSubscription, run.subscription_id)
        if subscription is None:
            raise ValueError("简报订阅已删除")
        if run.status == "cancelled" or not _scheduled_run_delivery_enabled(subscription, run):
            run.status = "cancelled"
            run.completed_at = run.completed_at or utc_now()
            run.stats = {**(run.stats or {}), "delivery_status": "cancelled_before_generation"}
            cancelled_result = {"brief_run_id": run_id, "cancelled": True}
        else:
            run.status = "running"
            run.started_at = utc_now()
            snapshot = _subscription_dict(subscription)
            brief_type = run.brief_type
            snapshot["brief_type"] = brief_type
            scheduled_for = run.scheduled_for
            model_spec = await _resolve_brief_model_spec(db)
        await db.commit()

    if cancelled_result is not None:
        await context.set_result(cancelled_result)
        await context.set_progress(100, "订阅已变更，本次定时简报不再推送")
        return cancelled_result

    await context.set_progress(8, "正在扩展多语言、多角度查询")
    planning_started = monotonic()
    plan, planning_warnings = await _expand_query_plan_with_agent(
        snapshot,
        model_spec=model_spec,
        run_id=run_id,
    )
    planning_ms = round((monotonic() - planning_started) * 1000)
    async with pg_manager.get_async_session_context() as db:
        run = await db.get(InnovationBriefRun, run_id)
        run.query_plan = plan
        await db.commit()

    collection_started = monotonic()
    (evidence, warnings), history_context = await asyncio.gather(
        _collect_evidence(snapshot, plan, context),
        _load_historical_brief_context(snapshot["id"]),
    )
    collection_ms = round((monotonic() - collection_started) * 1000)
    warnings = [*planning_warnings, *warnings]
    candidate_ranked = _score_and_classify(evidence, snapshot, history_context["evidence"])
    effective_threshold = _effective_significance_threshold(
        float(snapshot["significance_threshold"]),
        str(snapshot["reminder_sensitivity"]),
    )
    research_required = _should_run_research_explorer(
        brief_type=brief_type,
        enabled=bool(snapshot["research_explorer_enabled"]),
        ranked=candidate_ranked,
        significance_threshold=effective_threshold,
    )

    analysis_started = monotonic()
    research_digest: dict[str, Any] = {}
    convergence_attempts = 0
    await context.set_progress(58, "正在并行研判证据与创新组合")
    hypothesis_task = _discover_hypotheses(snapshot, plan, context)
    if research_required:
        (research_digest, explorer_warnings), (graph_hypotheses, graph_warnings) = await asyncio.gather(
            _collect_research_explorer_digest(
                {
                    **snapshot,
                    "recent_brief_titles": history_context["recent_titles"],
                    "candidate_signals": _research_candidate_signals(candidate_ranked),
                },
                plan,
                run_id=run_id,
                scheduled_for=scheduled_for,
            ),
            hypothesis_task,
        )
        research_digest["findings"] = _select_research_findings(
            research_digest.get("findings") or [],
            historical_titles=history_context["research_finding_titles"],
        )
        warnings.extend(explorer_warnings)
    else:
        graph_hypotheses, graph_warnings = await hypothesis_task
    await context.raise_if_cancelled()
    await context.set_progress(62, "正在比对历史简报并进行证据分层")

    warnings.extend(graph_warnings)
    candidate_hypotheses = _merge_hypothesis_candidates(research_digest, graph_hypotheses)
    novel_hypotheses = _select_novel_hypotheses(
        candidate_hypotheses,
        historical_keys=history_context["hypothesis_keys"],
        limit=BRIEF_MAX_ITEMS,
    )
    hypothesis_quota = min(BRIEF_HYPOTHESIS_RESERVED_SLOTS, len(novel_hypotheses))
    ranked = _select_high_value_evidence(
        candidate_ranked,
        limit=BRIEF_MAX_ITEMS - hypothesis_quota,
    )
    hypotheses = novel_hypotheses[: BRIEF_MAX_ITEMS - len(ranked)]
    sections = _build_sections(ranked, hypotheses, warnings, research_digest=research_digest)
    quality = _assess_brief_quality(sections)

    while not quality["passed"] and convergence_attempts < BRIEF_CONVERGENCE_MAX_ATTEMPTS:
        convergence_attempts += 1
        await context.set_progress(
            70 + convergence_attempts * 5,
            f"质量门未通过，正在执行第 {convergence_attempts} 次证据收敛",
        )
        converged_digest, convergence_warnings = await _converge_research_digest_with_agent(
            snapshot,
            candidate_ranked,
            research_digest,
            model_spec=model_spec,
            run_id=run_id,
            attempt=convergence_attempts,
            quality_failures=quality["failures"],
        )
        warnings.extend(convergence_warnings)
        if not converged_digest:
            continue
        research_digest = _merge_research_digests(research_digest, converged_digest)
        research_digest["findings"] = _select_research_findings(
            research_digest.get("findings") or [],
            historical_titles=history_context["research_finding_titles"],
        )
        candidate_hypotheses = _merge_hypothesis_candidates(research_digest, graph_hypotheses)
        novel_hypotheses = _select_novel_hypotheses(
            candidate_hypotheses,
            historical_keys=history_context["hypothesis_keys"],
            limit=BRIEF_MAX_ITEMS,
        )
        hypothesis_quota = min(BRIEF_HYPOTHESIS_RESERVED_SLOTS, len(novel_hypotheses))
        ranked = _select_high_value_evidence(
            candidate_ranked,
            limit=BRIEF_MAX_ITEMS - hypothesis_quota,
        )
        hypotheses = novel_hypotheses[: BRIEF_MAX_ITEMS - len(ranked)]
        sections = _build_sections(ranked, hypotheses, warnings, research_digest=research_digest)
        quality = _assess_brief_quality(sections)

    if not quality["passed"]:
        warnings.append("生成质量门未通过，本轮不创建、不发布简报。")
        sections = _build_sections(ranked, hypotheses, warnings, research_digest=research_digest)
    max_score = max((item["score"] for item in ranked), default=0.0)
    significant = max_score >= effective_threshold
    weekly = brief_type == "weekly"
    unread = scheduled_for is not None or weekly or significant
    summary = _build_summary(run.brief_type, sections, warnings)
    analysis_ms = round((monotonic() - analysis_started) * 1000)

    await context.set_progress(88, "正在执行发布前质量门并写入简报")
    prepared_at = utc_now()
    quality_blocked_result: dict | None = None
    async with pg_manager.get_async_session_context() as db:
        run = await db.get(InnovationBriefRun, run_id)
        subscription = await db.get(InnovationBriefSubscription, run.subscription_id)
        if run.status == "cancelled" or not _scheduled_run_delivery_enabled(subscription, run):
            run.status = "cancelled"
            run.completed_at = prepared_at
            run.stats = {
                **(run.stats or {}),
                "delivery_status": "cancelled_during_generation",
                "total_ms": round((monotonic() - run_started) * 1000),
            }
            await db.commit()
            cancelled_result = {"brief_run_id": run_id, "cancelled": True}
        elif not quality["passed"]:
            failure_text = "；".join(quality["failures"])
            run.status = "failed"
            run.error = f"生成质量门未通过：{failure_text}"[:4000]
            run.completed_at = prepared_at
            run.stats = {
                **(run.stats or {}),
                "candidate_evidence_count": len(candidate_ranked),
                "candidate_hypothesis_count": len(candidate_hypotheses),
                "research_explorer_run_id": research_digest.get("agent_run_id"),
                "research_explorer_finding_count": len(research_digest.get("findings") or []),
                "research_explorer_quality": "blocked",
                "convergence_agent_used": convergence_attempts > 0,
                "convergence_attempts": convergence_attempts,
                "grounded_source_count": int(research_digest.get("grounded_source_count") or 0),
                "untrusted_source_rejected_count": int(research_digest.get("untrusted_source_rejected_count") or 0),
                "quality_gate_passed": False,
                "quality_gate_failures": quality["failures"],
                "qualified_finding_count": quality["qualified_finding_count"],
                "section_fact_count": quality["fact_count"],
                "section_inference_count": quality["inference_count"],
                "section_hypothesis_count": quality["qualified_hypothesis_count"],
                "planning_ms": planning_ms,
                "collection_ms": collection_ms,
                "analysis_ms": analysis_ms,
                "total_ms": round((monotonic() - run_started) * 1000),
                "delivery_status": "quality_blocked",
                "publish_blocked_reason": failure_text,
            }
            await db.commit()
            quality_blocked_result = {
                "brief_run_id": run_id,
                "quality_blocked": True,
                "quality_failures": quality["failures"],
                "published": False,
            }
        else:
            scheduled_for = run.scheduled_for
            publish_immediately = scheduled_for is None or _datetime_due(scheduled_for, prepared_at)
            prepared_before_schedule_ms = (
                max(0, round((scheduled_for - prepared_at).total_seconds() * 1000)) if scheduled_for else 0
            )
            delivery_lag_ms = (
                max(0, round((prepared_at - scheduled_for).total_seconds() * 1000)) if scheduled_for else 0
            )
            published_at = prepared_at if publish_immediately else None
            run.status = "completed" if publish_immediately else "prepared"
            run.completed_at = prepared_at
            run.stats = {
                **(run.stats or {}),
                "evidence_count": len(ranked),
                "hypothesis_count": len(hypotheses),
                "selected_item_count": len(ranked) + len(hypotheses),
                "candidate_evidence_count": len(candidate_ranked),
                "candidate_hypothesis_count": len(candidate_hypotheses),
                "max_items": BRIEF_MAX_ITEMS,
                "max_score": max_score,
                "effective_significance_threshold": effective_threshold,
                "reminder_sensitivity": snapshot["reminder_sensitivity"],
                "significant": significant,
                "warning_count": len(warnings),
                "open_discovery_enabled": snapshot["open_discovery_enabled"],
                "research_explorer_enabled": snapshot["research_explorer_enabled"],
                "research_explorer_required": research_required,
                "research_explorer_run_id": research_digest.get("agent_run_id"),
                "research_explorer_finding_count": len(research_digest.get("findings") or []),
                "research_explorer_quality": ("complete" if quality["passed"] else "blocked"),
                "section_fact_count": len(sections.get("confirmed_facts") or []),
                "section_inference_count": len(sections.get("cross_validated_inferences") or []),
                "section_hypothesis_count": len(sections.get("innovation_hypotheses") or []),
                "convergence_agent_used": convergence_attempts > 0,
                "convergence_attempts": convergence_attempts,
                "grounded_source_count": int(research_digest.get("grounded_source_count") or 0),
                "untrusted_source_rejected_count": int(research_digest.get("untrusted_source_rejected_count") or 0),
                "quality_gate_passed": True,
                "quality_gate_failures": [],
                "planning_ms": planning_ms,
                "collection_ms": collection_ms,
                "analysis_ms": analysis_ms,
                "total_ms": round((monotonic() - run_started) * 1000),
                "prepared_before_schedule_ms": prepared_before_schedule_ms,
                "delivery_lag_ms": delivery_lag_ms,
                "delivery_status": "published" if publish_immediately else "prepared",
            }
            brief = InnovationBrief(
                id=uuid.uuid4().hex,
                run_id=run.id,
                subscription_id=run.subscription_id,
                owner_uid=run.owner_uid,
                brief_type=run.brief_type,
                title=f"{snapshot['name']} · {_brief_type_label(run.brief_type)}",
                summary=summary,
                sections=sections,
                evidence=ranked,
                max_score=max_score,
                significant=significant,
                unread=unread,
                published_at=published_at,
            )
            db.add(brief)
            await db.flush()
            if publish_immediately:
                await InAppBriefDeliveryProvider().enqueue(db, brief)
                await DisabledWeComBriefDeliveryProvider().enqueue(db, brief)
            await db.commit()

    if cancelled_result is not None:
        await context.set_result(cancelled_result)
        await context.set_progress(100, "订阅已变更，本次定时简报不再推送")
        return cancelled_result

    if quality_blocked_result is not None:
        await context.set_result(quality_blocked_result)
        await context.set_progress(100, "生成质量未达标，本轮已阻止发布")
        return quality_blocked_result

    result = {
        "brief_run_id": run_id,
        "brief_id": brief.id,
        "significant": significant,
        "unread": unread,
        "max_score": max_score,
        "published": brief.published_at is not None,
        "scheduled_for": format_utc_datetime(run.scheduled_for),
    }
    await context.set_result(result)
    await context.set_progress(100, "简报生成完成")
    return result


async def create_collection_update_briefs(
    db: AsyncSession,
    *,
    source: KnowledgeSource,
    source_run_id: str,
    items: list[KnowledgeSourceItem],
) -> int:
    """为订阅了来源的用户生成待审核采集更新和站内投递。"""
    if not source.notify_on_new or not items:
        return 0

    subscriptions = list(
        (
            await db.scalars(
                select(InnovationBriefSubscription).where(
                    InnovationBriefSubscription.tenant_id == source.tenant_id,
                    InnovationBriefSubscription.enabled.is_(True),
                )
            )
        ).all()
    )
    subscriptions = [row for row in subscriptions if source.id in set(row.source_ids or [])]
    if not subscriptions:
        return 0

    evidence = [_collection_update_evidence(source, item) for item in items]
    now = utc_now()
    for subscription in subscriptions:
        run = InnovationBriefRun(
            id=uuid.uuid4().hex,
            subscription_id=subscription.id,
            owner_uid=subscription.owner_uid,
            brief_type="collection_update",
            status="completed",
            query_plan=[],
            stats={
                "trigger": "source_collection",
                "source_id": source.id,
                "source_run_id": source_run_id,
                "evidence_count": len(evidence),
                "pending_review_count": len(evidence),
            },
            started_at=now,
            completed_at=now,
        )
        brief = InnovationBrief(
            id=uuid.uuid4().hex,
            run_id=run.id,
            subscription_id=subscription.id,
            owner_uid=subscription.owner_uid,
            brief_type="collection_update",
            title=f"{source.name} · 发现 {len(evidence)} 条待审核更新",
            summary=(
                f"来源“{source.name}”发现 {len(evidence)} 条新内容，均已进入暂存区；"
                "审核通过前不会进入正式检索区或事实图谱。"
            ),
            sections={
                "confirmed_facts": [],
                "cross_validated_inferences": [],
                "innovation_hypotheses": [],
                "evidence_gaps": evidence,
                "warnings": ["本批证据均为待审核暂存内容，不代表正式知识事实。"],
            },
            evidence=evidence,
            max_score=0.0,
            significant=False,
            unread=True,
            published_at=now,
        )
        db.add(run)
        await db.flush()
        db.add(brief)
        await db.flush()
        await InAppBriefDeliveryProvider().enqueue(db, brief)
        await DisabledWeComBriefDeliveryProvider().enqueue(db, brief)
    return len(subscriptions)


async def fail_innovation_brief(session, task_record, error: str) -> None:
    run_id = str((task_record.payload or {}).get("brief_run_id") or "")
    if not run_id:
        return
    run = await session.get(InnovationBriefRun, run_id)
    if run is not None and run.status in ACTIVE_BRIEF_RUN_STATUSES:
        run.status = "failed"
        run.error = error[:4000]
        run.completed_at = utc_now()


async def claim_due_brief_runs(*, limit: int = 10) -> int:
    """在真实推送时间前领取日简报和周报的耗时准备任务。"""
    created = 0
    now = utc_now()
    preparation_horizon = now + timedelta(minutes=BRIEF_PREPARE_AHEAD_MINUTES)
    claimed_daily_subscriptions: set[str] = set()
    claimed_weekly_subscriptions: set[str] = set()
    for _ in range(limit):
        task: Task | None = None
        async with pg_manager.get_async_session_context() as db:
            future_daily_run_exists = (
                select(InnovationBriefRun.id)
                .where(
                    InnovationBriefRun.subscription_id == InnovationBriefSubscription.id,
                    InnovationBriefRun.brief_type == "daily",
                    InnovationBriefRun.scheduled_for > now,
                    InnovationBriefRun.status.in_({"pending", "running", "prepared"}),
                )
                .exists()
            )
            future_weekly_run_exists = (
                select(InnovationBriefRun.id)
                .where(
                    InnovationBriefRun.subscription_id == InnovationBriefSubscription.id,
                    InnovationBriefRun.brief_type == "weekly",
                    InnovationBriefRun.scheduled_for > now,
                    InnovationBriefRun.status.in_({"pending", "running", "prepared"}),
                )
                .exists()
            )
            daily_due_clause = (
                InnovationBriefSubscription.daily_enabled.is_(True)
                & (InnovationBriefSubscription.next_daily_at <= preparation_horizon)
                & ~future_daily_run_exists
            )
            weekly_due_clause = (
                InnovationBriefSubscription.weekly_enabled.is_(True)
                & (InnovationBriefSubscription.next_weekly_at <= preparation_horizon)
                & ~future_weekly_run_exists
            )
            if claimed_daily_subscriptions:
                daily_due_clause &= InnovationBriefSubscription.id.not_in(claimed_daily_subscriptions)
            if claimed_weekly_subscriptions:
                weekly_due_clause &= InnovationBriefSubscription.id.not_in(claimed_weekly_subscriptions)
            subscription = await db.scalar(
                select(InnovationBriefSubscription)
                .where(
                    InnovationBriefSubscription.enabled.is_(True),
                    or_(daily_due_clause, weekly_due_clause),
                )
                .order_by(
                    func.least(
                        InnovationBriefSubscription.next_daily_at,
                        InnovationBriefSubscription.next_weekly_at,
                    )
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if subscription is None:
                break
            future_daily_run_id = await db.scalar(
                select(InnovationBriefRun.id)
                .where(
                    InnovationBriefRun.subscription_id == subscription.id,
                    InnovationBriefRun.brief_type == "daily",
                    InnovationBriefRun.scheduled_for > now,
                    InnovationBriefRun.status.in_({"pending", "running", "prepared"}),
                )
                .limit(1)
            )
            daily_due = bool(
                subscription.daily_enabled
                and subscription.next_daily_at
                and _datetime_due(subscription.next_daily_at, preparation_horizon)
                and subscription.id not in claimed_daily_subscriptions
                and not future_daily_run_id
            )
            brief_type = "daily" if daily_due else "weekly"
            if brief_type == "daily":
                claimed_daily_subscriptions.add(subscription.id)
            else:
                claimed_weekly_subscriptions.add(subscription.id)
            scheduled_for = subscription.next_daily_at if daily_due else subscription.next_weekly_at
            existing_scheduled_run_id = await db.scalar(
                select(InnovationBriefRun.id)
                .where(
                    InnovationBriefRun.subscription_id == subscription.id,
                    InnovationBriefRun.brief_type == brief_type,
                    InnovationBriefRun.scheduled_for == scheduled_for,
                )
                .limit(1)
            )
            _advance_subscription_schedule(subscription, brief_type, scheduled_for=scheduled_for)
            if existing_scheduled_run_id:
                await db.commit()
                continue
            run = InnovationBriefRun(
                id=uuid.uuid4().hex,
                subscription_id=subscription.id,
                owner_uid=subscription.owner_uid,
                brief_type=brief_type,
                status="pending",
                scheduled_for=scheduled_for,
                stats={
                    "trigger": "scheduled",
                    "prepare_ahead_minutes": BRIEF_PREPARE_AHEAD_MINUTES,
                    "delivery_status": "preparing",
                },
            )
            task = await tasker.create_in_session(
                db,
                name=f"提前准备{_brief_type_label(brief_type)}：{subscription.name}",
                task_type=BRIEF_TASK_TYPE,
                payload={"brief_run_id": run.id, "operator_id": subscription.owner_uid},
                payload_match={
                    "subscription_id": subscription.id,
                    "brief_type": brief_type,
                    "scheduled_for": format_utc_datetime(scheduled_for),
                },
            )
            run.task_id = task.id
            db.add(run)
            await db.commit()
        if task is not None:
            await tasker.publish(task)
            created += 1
    return created


async def publish_due_briefs(*, limit: int = 100) -> int:
    """原子发布已准备简报；重复扫描、并发 worker 和重启均不会重复投递。"""
    published = 0
    processed = 0
    while processed < limit:
        now = utc_now()
        async with pg_manager.get_async_session_context() as db:
            candidate = (
                await db.execute(
                    select(InnovationBrief, InnovationBriefRun, InnovationBriefSubscription)
                    .join(InnovationBriefRun, InnovationBriefRun.id == InnovationBrief.run_id)
                    .join(
                        InnovationBriefSubscription,
                        InnovationBriefSubscription.id == InnovationBrief.subscription_id,
                    )
                    .where(
                        InnovationBrief.published_at.is_(None),
                        InnovationBriefRun.scheduled_for.is_not(None),
                        InnovationBriefRun.scheduled_for <= now,
                    )
                    .order_by(InnovationBriefRun.scheduled_for, InnovationBrief.created_at)
                    .with_for_update(of=InnovationBrief, skip_locked=True)
                    .limit(1)
                )
            ).first()
            if candidate is None:
                break
            brief, run, subscription = candidate
            processed += 1
            if run.status == "cancelled" or not _scheduled_run_delivery_enabled(subscription, run):
                run.status = "cancelled"
                run.stats = {**(run.stats or {}), "delivery_status": "cancelled_before_publish"}
                await db.delete(brief)
                await db.commit()
                continue

            brief.published_at = now
            brief.unread = True
            run.status = "completed"
            lag_ms = max(0, round((now - run.scheduled_for).total_seconds() * 1000))
            run.stats = {
                **(run.stats or {}),
                "delivery_lag_ms": lag_ms,
                "delivery_status": "published",
                "published_at": format_utc_datetime(now),
            }
            await InAppBriefDeliveryProvider().enqueue(db, brief)
            await DisabledWeComBriefDeliveryProvider().enqueue(db, brief)
            await db.commit()
            published += 1
    return published


async def _create_default_subscription(
    db: AsyncSession,
    *,
    tenant_id: str,
    owner_uid: str,
) -> InnovationBriefSubscription:
    values = _subscription_values(
        {
            "name": "新质创新军事前沿技术观察",
            "topics": DEFAULT_TOPICS,
            "keywords": DEFAULT_KEYWORDS,
            "open_discovery_enabled": True,
            "research_explorer_enabled": True,
        }
    )
    row = InnovationBriefSubscription(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        owner_uid=owner_uid,
        **values,
    )
    db.add(row)
    await db.commit()
    return row


def _subscription_values(data: dict) -> dict:
    timezone = str(data.get("timezone") or "Asia/Shanghai")
    daily_cron, timezone = validate_schedule(str(data.get("daily_cron") or "0 8 * * *"), timezone)
    weekly_cron, timezone = validate_schedule(str(data.get("weekly_cron") or "0 9 * * 1"), timezone)
    threshold = float(data.get("significance_threshold", 70))
    if not 0 <= threshold <= 100:
        raise HTTPException(status_code=422, detail="significance_threshold 必须在 0 到 100 之间")
    sensitivity = str(data.get("reminder_sensitivity") or "standard")
    if sensitivity not in {"conservative", "standard", "sensitive"}:
        raise HTTPException(status_code=422, detail="提醒敏感度不受支持")
    return {
        "name": _required_text(data.get("name"), "订阅名称", 255),
        "topics": _text_list(data.get("topics")) or list(DEFAULT_TOPICS),
        "keywords": _text_list(data.get("keywords")),
        "knowledge_ids": _text_list(data.get("knowledge_ids")),
        "source_ids": _text_list(data.get("source_ids")),
        "languages": _text_list(data.get("languages")) or list(DEFAULT_LANGUAGES),
        "timezone": timezone,
        "daily_enabled": bool(data.get("daily_enabled", True)),
        "weekly_enabled": bool(data.get("weekly_enabled", True)),
        "daily_cron": daily_cron,
        "weekly_cron": weekly_cron,
        "reminder_sensitivity": sensitivity,
        "significance_threshold": threshold,
        "open_discovery_enabled": bool(data.get("open_discovery_enabled", True)),
        "research_explorer_enabled": bool(data.get("research_explorer_enabled", True)),
        "next_daily_at": _next_run_at_aware(daily_cron, timezone),
        "next_weekly_at": _next_run_at_aware(weekly_cron, timezone),
        "enabled": bool(data.get("enabled", True)),
    }


async def _validate_subscription_sources(db: AsyncSession, tenant_id: str, source_ids: list[str]) -> None:
    if not source_ids:
        return
    count = int(
        await db.scalar(
            select(func.count(KnowledgeSource.id)).where(
                KnowledgeSource.tenant_id == tenant_id,
                KnowledgeSource.id.in_(source_ids),
            )
        )
        or 0
    )
    if count != len(set(source_ids)):
        raise HTTPException(status_code=404, detail="部分知识来源不存在或不属于当前组织")


async def _owned_subscription(
    db: AsyncSession,
    tenant_id: str,
    owner_uid: str,
    subscription_id: str,
    *,
    lock: bool = False,
) -> InnovationBriefSubscription:
    statement = select(InnovationBriefSubscription).where(
        InnovationBriefSubscription.id == subscription_id,
        InnovationBriefSubscription.tenant_id == tenant_id,
        InnovationBriefSubscription.owner_uid == owner_uid,
    )
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="简报订阅不存在")
    return row


def _expand_query_plan(subscription: InnovationBriefSubscription) -> list[dict]:
    as_of = utc_now()
    year = as_of.year
    month = as_of.strftime("%Y-%m")
    brief_type = str(getattr(subscription, "brief_type", "daily") or "daily")
    freshness_zh = "近30天 最新进展" if brief_type == "weekly" else "近7天 最新进展"
    freshness_en = "past 30 days latest update" if brief_type == "weekly" else "past 7 days latest update"
    languages = list(subscription.languages or DEFAULT_LANGUAGES)[:4]
    topics = list(subscription.topics or DEFAULT_TOPICS)[:20]
    midpoint = max(1, (len(topics) + 1) // 2)
    deployment_topics = topics[:midpoint]
    principle_topics = topics[midpoint:] or deployment_topics
    angles = (
        (
            deployment_topics,
            "种子方向·重点谱系新概念与关键进展",
            "新概念 新原理 技术突破 跨域组合 工程进展",
            "novel concept new principle technology breakthrough cross-domain integration engineering progress",
        ),
        (
            principle_topics,
            "种子方向·原理反制与证据缺口",
            "关键原理 作用机理 反制 弱点 证据",
            "principle mechanism countermeasure vulnerability evidence",
        ),
    )
    rows = []
    for language in languages:
        language_hint = "" if language in {"zh-CN", "zh", "en"} else f" {language}"
        for topic_group, angle, zh_terms, en_terms in angles:
            terms = zh_terms if language.casefold().startswith("zh") else en_terms
            freshness = freshness_zh if language.casefold().startswith("zh") else freshness_en
            topic_label = " / ".join(topic_group)
            topic_query = " OR ".join(f'"{topic}"' for topic in topic_group)
            rows.append(
                {
                    "topic": topic_label,
                    "language": language,
                    "angle": angle,
                    "query": f"({topic_query}) {terms} {freshness} {month} {year}{language_hint}",
                }
            )

    if getattr(subscription, "open_discovery_enabled", True):
        for theme, zh_terms, en_terms in OPEN_DISCOVERY_THEMES:
            for language in languages:
                terms = zh_terms if language.casefold().startswith("zh") else en_terms
                freshness = freshness_zh if language.casefold().startswith("zh") else freshness_en
                language_hint = "" if language in {"zh-CN", "zh", "en"} else f" {language}"
                rows.append(
                    {
                        "topic": theme,
                        "language": language,
                        "angle": "开放发现·跨域扫描与弱信号",
                        "query": f"{terms} {freshness} {month} {year}{language_hint}",
                    }
                )
    return rows[:12]


async def _expand_query_plan_with_agent(
    subscription: InnovationBriefSubscription | dict,
    *,
    model_spec: str,
    run_id: str,
) -> tuple[list[dict], list[str]]:
    """复用平台聊天模型进行智能体式查询扩展，失败时保留确定性查询基线。"""
    baseline = _expand_query_plan(_subscription_view(subscription))
    if not str(model_spec or "").strip():
        return baseline, ["未配置平台默认智能体模型，本次使用确定性多语言查询基线。"]

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from platform_core.models.chat import load_chat_model

        model = load_chat_model(model_spec, session_id=f"innovation-brief:{run_id}")
        payload = {
            "as_of": utc_now().date().isoformat(),
            "brief_type": str(_subscription_value(subscription, "brief_type") or "daily"),
            "freshness_window": (
                "优先近30天，必要时回溯近90天"
                if _subscription_value(subscription, "brief_type") == "weekly"
                else "优先近7天，必要时回溯近30天"
            ),
            "topics": list(_subscription_value(subscription, "topics") or DEFAULT_TOPICS),
            "keywords": list(_subscription_value(subscription, "keywords") or []),
            "priority_taxonomy": [
                {"category": category, "equipment": equipment, "technologies": technologies}
                for category, equipment, technologies in PRIORITY_TECHNOLOGY_TAXONOMY
            ],
            "languages": list(_subscription_value(subscription, "languages") or DEFAULT_LANGUAGES),
            "open_discovery_enabled": bool(_subscription_value(subscription, "open_discovery_enabled") is not False),
            "open_discovery_themes": [row[0] for row in OPEN_DISCOVERY_THEMES],
            "baseline": baseline,
        }
        async with asyncio.timeout(BRIEF_QUERY_PLANNING_TIMEOUT_SECONDS):
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是新质创新军事前沿技术情报查询规划智能体。只扩展公开检索查询，不形成事实结论。"
                            "用户主题是高优先级种子而非范围边界；开放发现启用时，必须加入种子之外的跨领域扫描、"
                            "弱信号和新原理发现。覆盖技术突破、试验部署、作用机理、反制关系、薄弱点和证据缺口；"
                            "以 priority_taxonomy 的 19 类谱系为持续关注面，同时必须扫描谱系外的新概念、跨域组合、"
                            "关键部件迁移和弱信号；查询必须带入 as_of 与 freshness_window。官方试验、样机、采购、"
                            "交付和部署只用于判断证据成熟度，不得成为检索范围、准入条件或唯一优先方向；"
                            "旧论文可以支撑新机理与新组合，但不得冒充本期最新进展。"
                            "严格输出 JSON 数组，每项只有 topic、language、angle、query 四个字符串字段，最多 12 项。"
                        )
                    ),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                ],
                config={"tags": ["innovation-brief", "query-planning"], "run_name": "innovation_brief_query_plan"},
            )
        agent_rows = _parse_agent_query_plan(getattr(response, "content", response))
        focus_rows = [row for row in baseline if not row["angle"].startswith("开放发现")]
        discovery_rows = [row for row in baseline if row["angle"].startswith("开放发现")]
        candidates = [*agent_rows[:3], *focus_rows[:2], *discovery_rows, *focus_rows[2:]]
        merged = []
        seen = set()
        for row in candidates:
            key = (row["language"].casefold(), row["query"].casefold())
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
            if len(merged) >= 12:
                break
        return merged, []
    except Exception as exc:
        return baseline, [f"查询规划智能体不可用，已回退确定性查询基线：{str(exc)[:240]}"]


async def _resolve_brief_model_spec(db: AsyncSession) -> str:
    """复用平台默认智能体模型配置。"""
    from platform_core.services.equipment_model_adapter import default_chat_model_spec

    return await default_chat_model_spec(db)


def _parse_agent_query_plan(content: Any) -> list[dict]:
    """解析并收紧智能体 JSON 输出，兼容说明文字和尾部截断。"""
    required = {"topic", "language", "angle", "query"}
    if (
        isinstance(content, list)
        and content
        and all(isinstance(item, dict) and required.issubset(item) for item in content)
    ):
        raw = content
    else:
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text") or item.get("content") or "") for item in content if isinstance(item, dict)
            ).strip()
        else:
            text = str(content or "").strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        raw = _extract_query_plan_json(fenced.group(1) if fenced else text)
    if isinstance(raw, dict):
        raw = raw.get("queries") or raw.get("items") or raw.get("plan")
    if not isinstance(raw, list):
        raise ValueError("查询规划智能体未返回 JSON 数组")
    rows = []
    for item in raw[:24]:
        if not isinstance(item, dict):
            continue
        row = {key: str(item.get(key) or "").strip()[:500] for key in ("topic", "language", "angle", "query")}
        if all(row.values()):
            rows.append(row)
    if not rows:
        raise ValueError("查询规划智能体未返回有效查询")
    return rows


def _extract_query_plan_json(text: str) -> Any:
    """从模型说明文字或截断输出中恢复完整的查询规划条目。"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    decoder = json.JSONDecoder()
    recovered_rows = []
    for match in re.finditer(r"[\[{]", text):
        try:
            candidate, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict) and any(key in candidate for key in ("queries", "items", "plan")):
            return candidate
        if isinstance(candidate, dict) and all(
            str(candidate.get(key) or "").strip() for key in ("topic", "language", "angle", "query")
        ):
            recovered_rows.append(candidate)
    if recovered_rows:
        return recovered_rows
    raise ValueError("查询规划智能体未返回可恢复的 JSON")


def _subscription_view(subscription: InnovationBriefSubscription | dict):
    """把持久模型或运行快照投影成查询规划所需属性。"""
    if not isinstance(subscription, dict):
        return subscription

    class SubscriptionView:
        topics = subscription.get("topics") or DEFAULT_TOPICS
        languages = subscription.get("languages") or DEFAULT_LANGUAGES
        open_discovery_enabled = subscription.get("open_discovery_enabled", True)
        brief_type = subscription.get("brief_type") or "daily"

    return SubscriptionView()


def _subscription_value(subscription: InnovationBriefSubscription | dict, key: str):
    return subscription.get(key) if isinstance(subscription, dict) else getattr(subscription, key, None)


async def _collect_evidence(snapshot: dict, plan: list[dict], context: TaskContext) -> tuple[list[dict], list[str]]:
    evidence: list[dict] = []
    warnings: list[str] = []
    queries = [row["query"] for row in plan[:8]]
    try:
        web_items = await collect_source_items(
            "web_search",
            {
                "queries": queries,
                "count": 8,
                "time_range": "month" if snapshot.get("brief_type") == "weekly" else "week",
            },
            None,
        )
        for item in web_items:
            evidence.append(_candidate_to_evidence(item, evidence_type="web_search", review_status="external"))
    except Exception as exc:
        warnings.append(f"WebSearch 取证失败：{exc}")

    await context.set_progress(35, f"WebSearch 已取得 {len(evidence)} 条，正在读取来源暂存区")
    if snapshot["source_ids"] or snapshot["knowledge_ids"]:
        async with pg_manager.get_async_session_context() as db:
            statement = (
                select(KnowledgeSourceItem, KnowledgeSource)
                .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceItem.source_id)
                .where(
                    KnowledgeSource.tenant_id == snapshot["tenant_id"],
                    KnowledgeSourceItem.review_status.in_(("pending", "approved")),
                )
            )
            if snapshot["source_ids"]:
                statement = statement.where(KnowledgeSource.id.in_(snapshot["source_ids"]))
            if snapshot["knowledge_ids"]:
                statement = statement.where(KnowledgeSourceItem.kb_id.in_(snapshot["knowledge_ids"]))
            rows = (await db.execute(statement.order_by(KnowledgeSourceItem.discovered_at.desc()).limit(100))).all()
            for item, source in rows:
                evidence.append(
                    {
                        "id": item.id,
                        "title": item.title,
                        "excerpt": item.markdown[:3000],
                        "url": item.canonical_url,
                        "source": source.name,
                        "source_type": source.source_type,
                        "review_status": item.review_status,
                        "pending_review": item.review_status == "pending",
                        "published_at": (item.metadata_json or {}).get("published_at"),
                        "discovered_at": format_utc_datetime(item.discovered_at),
                        "kb_id": item.kb_id,
                        "source_item_id": item.id,
                    }
                )

    await context.set_progress(48, "正在联合正式知识库检索")
    knowledge_evidence, knowledge_warnings = await _collect_knowledge_evidence(
        snapshot["knowledge_ids"][:8],
        queries[:2],
    )
    evidence.extend(knowledge_evidence)
    warnings.extend(knowledge_warnings)
    return _dedupe_evidence(evidence), warnings


async def _collect_knowledge_evidence(kb_ids: list[str], queries: list[str]) -> tuple[list[dict], list[str]]:
    """跨知识库受控并发检索，同一知识库内保持顺序以避免后端突发压力。"""
    semaphore = asyncio.Semaphore(BRIEF_KNOWLEDGE_CONCURRENCY)

    async def collect_one(kb_id: str) -> tuple[list[dict], list[str]]:
        rows = []
        warnings = []
        async with semaphore:
            for query in queries:
                try:
                    results = await knowledge_base.aquery(query, kb_id=kb_id)
                except Exception as exc:
                    warnings.append(f"知识库 {kb_id} 检索失败：{exc}")
                    break
                for index, row in enumerate(results if isinstance(results, list) else [results]):
                    rows.append(_knowledge_result_to_evidence(kb_id, query, row, index))
        return rows, warnings

    if not kb_ids or not queries:
        return [], []
    results = await asyncio.gather(*(collect_one(kb_id) for kb_id in kb_ids))
    return (
        [row for rows, _warnings in results for row in rows],
        [warning for _rows, warnings in results for warning in warnings],
    )


async def _collect_research_explorer_digest(
    snapshot: dict,
    plan: list[dict],
    *,
    run_id: str,
    scheduled_for: datetime | None = None,
) -> tuple[dict, list[str]]:
    """调用既有深度研究智能体，并要求其委派调研探索员形成原理型证据摘要。"""
    from platform_core.services.agent_request_service import (
        AgentRequestInput,
        RunOrigin,
        submit_agent_request,
    )
    from platform_core.services.agent_run_service import AgentRunWaitTimeout
    from platform_core.services.input_message_service import build_chat_input_message
    from platform_core.storage.postgres.models_business import User
    from platform_core.utils.hash_utils import hash_id

    prompt = _research_explorer_prompt(snapshot, plan)
    request_id = hash_id("brief-research:", run_id, length=64)
    thread_id = hash_id("brief_thread_", f"{snapshot['owner_uid']}:{run_id}", length=64)
    agent_run_id = ""
    try:
        async with pg_manager.get_async_session_context() as db:
            user = await db.scalar(
                select(User).where(
                    User.uid == snapshot["owner_uid"],
                    User.is_deleted == 0,
                )
            )
            if user is None or bool(user.is_deleted):
                return {}, ["调研探索员未运行：订阅用户不存在或已停用。"]
            response = await submit_agent_request(
                request_input=AgentRequestInput(
                    agent_slug="deep-research",
                    thread_id=thread_id,
                    request_id=request_id,
                    input_message=build_chat_input_message(prompt),
                    origin=RunOrigin(
                        source="innovation_brief",
                        channel="internal",
                        external_id=run_id,
                        metadata={"brief_run_id": run_id},
                    ),
                    request_metadata={"brief_run_id": run_id, "research_explorer_required": True},
                    tool_approval_mode="always_trust",
                    runtime_context_overrides={"context": {"knowledges": list(snapshot["knowledge_ids"])}}
                    if snapshot["knowledge_ids"]
                    else {},
                    queue_policy="enqueue",
                    create_conversation=True,
                    conversation_title=f"简报调研探索 · {snapshot['name']}",
                ),
                current_user=user,
                db=db,
            )
        agent_run_id = str(response.get("run_id") or "")
        if not agent_run_id:
            return {}, ["调研探索员请求已排队但尚未生成运行记录，本次简报先使用常规证据链。"]
        result = await _await_research_explorer_result(
            run_id=agent_run_id,
            current_uid=snapshot["owner_uid"],
            scheduled_for=scheduled_for,
        )
    except TimeoutError:
        return {}, [f"调研探索员运行 {agent_run_id or ''} 超过简报质量等待窗口，本期暂不合并其结果。"]
    except AgentRunWaitTimeout as exc:
        return {}, [f"调研探索员运行 {exc.result.get('agent_run_id') or ''} 等待超时，本期暂不合并其结果。"]
    except Exception as exc:
        return {}, [f"调研探索员不可用，本次保留常规检索结果：{str(exc)[:240]}"]

    if result.get("status") != "completed":
        error = result.get("error") or {}
        return {}, [f"调研探索员运行未完成：{error.get('message') or result.get('status') or '未知状态'}"]
    digest = _parse_research_explorer_digest(result.get("output"))
    digest["agent_run_id"] = agent_run_id
    digest["agent_slug"] = str(result.get("agent_slug") or "deep-research")
    return digest, []


async def _await_research_explorer_result(
    *,
    run_id: str,
    current_uid: str,
    scheduled_for: datetime | None,
) -> dict:
    """在通用 SSE 窗口结束后继续回收简报探索结果，最长不越过质量截止时间。"""
    from platform_core.services.agent_run_service import (
        AgentRunWaitTimeout,
        await_agent_run_result,
        load_agent_run_result,
    )

    deadline = monotonic() + _research_explorer_wait_budget_seconds(scheduled_for)
    last_result: dict[str, Any] = {"agent_run_id": run_id, "status": "running"}
    try:
        async with asyncio.timeout(max(1.0, deadline - monotonic())):
            return await await_agent_run_result(run_id=run_id, current_uid=current_uid)
    except AgentRunWaitTimeout as exc:
        last_result = exc.result
    except TimeoutError:
        pass

    while monotonic() < deadline:
        await asyncio.sleep(min(BRIEF_RESEARCH_EXPLORER_RECHECK_SECONDS, max(0.0, deadline - monotonic())))
        last_result = await load_agent_run_result(run_id=run_id, current_uid=current_uid)
        if str(last_result.get("status") or "") in TERMINAL_AGENT_RUN_STATUSES:
            return last_result
    raise AgentRunWaitTimeout(last_result)


def _research_explorer_wait_budget_seconds(scheduled_for: datetime | None) -> float:
    """给收敛与发布预留硬截止时间，不让深研排队拖过推送时刻。"""
    maximum = float(BRIEF_RESEARCH_EXPLORER_MAX_WAIT_MINUTES * 60)
    if scheduled_for is None:
        return maximum
    now = utc_now()
    if scheduled_for.tzinfo is None:
        now = now.replace(tzinfo=None)
    convergence_deadline = scheduled_for - timedelta(minutes=BRIEF_RESEARCH_EXPLORER_CUTOFF_MINUTES)
    until_cutoff = (convergence_deadline - now).total_seconds()
    return max(1.0, min(maximum, until_cutoff))


def _research_explorer_prompt(snapshot: dict, plan: list[dict]) -> str:
    """构造简报专用的调研探索员委派任务。"""
    weekly = snapshot.get("brief_type") == "weekly"
    parallel_rule = (
        "周报在正交轴中动态选择 2 至 3 个并行分片，最多 3 个。"
        if weekly
        else "日报在正交轴中动态选择 1 至 2 个并行分片，最多 2 个。"
    )
    scope_rule = (
        "订阅主题只是高优先级种子，必须同时扫描种子之外的跨域弱信号。"
        if snapshot["open_discovery_enabled"]
        else "只围绕订阅主题检索，不做主题外扩展。"
    )
    payload = {
        "as_of": utc_now().date().isoformat(),
        "subscription": snapshot["name"],
        "brief_type": snapshot.get("brief_type") or "daily",
        "freshness_window": "近30天优先、必要时回溯近90天" if weekly else "近7天优先、必要时回溯近30天",
        "priority_seed_topics": snapshot["topics"],
        "priority_taxonomy": [
            {"category": category, "equipment": equipment, "technologies": technologies}
            for category, equipment, technologies in PRIORITY_TECHNOLOGY_TAXONOMY
        ],
        "keywords": snapshot["keywords"],
        "languages": snapshot["languages"],
        "query_plan": plan[:12],
        "candidate_signals": list(snapshot.get("candidate_signals") or [])[:12],
        "avoid_recent_titles": list(snapshot.get("recent_brief_titles") or [])[:80],
    }
    return (
        "你是本次新质创新军事前沿技术简报的总控研究智能体。必须调用 research-explorer 调研探索员，"
        f"{parallel_rule} 候选正交轴包括："
        "19 类重点谱系的新进展与关键缺口、谱系外的新概念/新原理/弱信号、跨域组合与反制/失效边界。"
        "使用 subagent_start 并行启动 research-explorer，research_budget_mode 使用 standard；"
        "若实际只有一个独立缺口可只启动 1 个，不按渠道或地区机械拆分。"
        "总控只负责去重、交叉核验与综合，不再重复探索员已经完成的同义检索；"
        "只有关键数字或来源冲突会改变结论时，才追加 1 个 fact-verifier 做定向核查。"
        "这是无人值守的内部简报任务，不得向用户请求工具审批或补充回答；"
        "使用公开网页、学术证据和已授权知识库，检索并整理最近出现的新技术、新原理、试验与工程信号。"
        "最新性以任务上下文 as_of 为准：优先 freshness_window 内首次公开或发生实质变化的信号；"
        "更早资料只能作为原理、基线或演进脉络，除非本期出现新的复现、试验、采办、部署或反制变化。"
        "高价值信号应至少改变以下一项：装备作用机理、总体构型、接敌几何、任务链位置、对手应对或成本交换；"
        "任务上下文中的 19 类新质武器装备技术谱系、典型装备和重点技术是持续关注面，但不是范围边界；"
        "必须持续扫描谱系外的新概念、跨域迁移、民用技术军事化组合与尚未形成固定装备名称的能力信号。"
        "官方试验/采办/部署、论文实验和工程里程碑用于判断证据强度与成熟度，不得成为发现范围、准入门槛或唯一优先方向；"
        "不得因信号仍处论文、仿真或概念阶段而过滤它。弱化营销稿、转载和没有具体机理的泛化 AI/无人化表述。"
        f"{scope_rule} 优先核验 candidate_signals 中的高分新信号，再补充真正遗漏的跨域发现；"
        "不要重复执行 query_plan 中语义等价的查询。重点解释作用原理、可能改变的作战关系、工程成熟度、反制与失效边界；"
        "严格区分 Fact、Inference、Hypothesis，不得把模型知识当作已检索事实。"
        "在 findings 基础上先形成 innovation_outlook：说明哪些新原理、跨域迁移或技术组合值得进一步想象，"
        "以及为何可能形成新质能力；"
        "再提出 1 至 2 条创新假设：必须进行跨技术或跨原理组合，形成明确的新质装备形态或技术设想，"
        "说明可能改变的作战关系，并给出最小可验证试验与反制、风险、失效边界；"
        "每条创新假设必须引用本次 findings 中至少一个"
        "真实标题作为 source_titles，只能标记为 Hypothesis，不能把设想写成已实现事实。"
        "最终只输出一个紧凑 JSON 对象，不要 Markdown 围栏、前后说明、重复引文或校验过程；"
        "summary 不超过 600 个中文字符，innovation_outlook 不超过 500 个中文字符，"
        "findings 最多 8 条，每个文本字段不超过 600 个中文字符，"
        "innovation_hypotheses 最多 2 条，每个文本字段不超过 500 个中文字符，完整 JSON 控制在 12000 字符以内。"
        "格式为："
        '{"summary":"总体判断","innovation_outlook":"基于本期调研形成的新质技术思考与可探索组合",'
        '"findings":[{"title":"技术名称","principle":"作用原理",'
        '"why_it_matters":"军事价值与变化","equipment_implication":"牵引的具体装备身份或构型变化",'
        '"maturity":"论文|仿真|样机|地面试验|飞行/海试|部署/采办",'
        '"published_at":"YYYY-MM-DD或unknown","claim_level":"Fact|Inference|Hypothesis",'
        '"evidence":"证据摘要","boundaries":"反制、风险或失效边界","sources":'
        '[{"title":"来源名","url":"https://..."}]}],"innovation_hypotheses":['
        '{"title":"新质装备或技术设想名称","mechanism_hypothesis":"跨技术组合及待验证作用机理",'
        '"equipment_concept":"潜在装备形态与任务应用","operational_value":"可能改变的作战关系",'
        '"feasibility_basis":"由调研发现支持的可行性依据","verification_path":"最小可验证试验路径",'
        '"countermeasures_and_risks":"反制、风险与失效边界","source_titles":["对应 finding 标题"]}],'
        '"gaps":["待验证证据缺口"]}。'
        "findings 精选最多 8 条高价值发现，每条至少保留一个真实来源；"
        "不得重复 avoid_recent_titles 中已出现且没有实质变化的主题，无法核实的内容放入 gaps。任务上下文："
        + json.dumps(payload, ensure_ascii=False)
    )


def _research_candidate_signals(ranked: list[dict]) -> list[dict]:
    """给调研探索员提供紧凑候选面，减少重复发现式搜索。"""
    return [
        {
            "title": str(item.get("title") or "")[:500],
            "url": str(item.get("url") or "")[:2048],
            "excerpt": str(item.get("excerpt") or "")[:1200],
            "score": item.get("score"),
            "claim_level": item.get("claim_level"),
            "change_signal": item.get("change_signal"),
            "published_at": item.get("published_at"),
            "recency_bucket": item.get("recency_bucket"),
            "innovation_expansion_score": (item.get("score_breakdown") or {}).get("innovation_expansion"),
        }
        for item in ranked[:12]
    ]


def _parse_research_explorer_digest(content: Any) -> dict:
    """解析调研探索员结构化交付，并恢复被输出上限截断的完整条目。"""
    text = _model_content_text(content)
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    raw = _extract_research_digest_json(fenced.group(1) if fenced else text)
    if raw is None:
        return {
            "summary": text[:2000],
            "innovation_outlook": "",
            "findings": [],
            "innovation_hypotheses": [],
            "gaps": ["调研探索员未返回结构化 JSON，已保留原文。"],
        }

    findings = []
    quality_gaps = []
    for item in (raw.get("findings") or [])[:BRIEF_RESEARCH_FINDING_LIMIT]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        principle = str(item.get("principle") or "").strip()
        if not title or not principle:
            continue
        claim_level = str(item.get("claim_level") or "Hypothesis").strip().title()
        if claim_level not in {"Fact", "Inference", "Hypothesis"}:
            claim_level = "Hypothesis"
        sources = [
            {
                "title": str(source.get("title") or source.get("url") or "原始来源").strip()[:500],
                "url": str(source.get("url") or "").strip()[:2048],
            }
            for source in (item.get("sources") or [])[:8]
            if isinstance(source, dict) and str(source.get("url") or "").startswith(("http://", "https://"))
        ]
        sources = list(
            {_normalized_url(source["url"]): source for source in sources if _normalized_url(source["url"])}.values()
        )
        if not sources:
            quality_gaps.append(f"{title}：未提供可核验来源，未纳入本期高价值发现。")
            continue
        independent_sources = {_source_identity({"url": source["url"]}) for source in sources}
        official = any(_is_first_party({"url": source["url"]}) for source in sources)
        primary_research = any(_is_primary_research_source({"url": source["url"]}) for source in sources)
        if claim_level == "Fact" and not official and not primary_research and len(independent_sources) < 2:
            claim_level = "Inference"
        findings.append(
            {
                "title": title[:1000],
                "principle": principle[:5000],
                "why_it_matters": str(item.get("why_it_matters") or "").strip()[:5000],
                "equipment_implication": str(item.get("equipment_implication") or "").strip()[:5000],
                "maturity": str(item.get("maturity") or "").strip()[:500],
                "published_at": str(item.get("published_at") or "").strip()[:100],
                "claim_level": claim_level,
                "evidence": str(item.get("evidence") or "").strip()[:5000],
                "boundaries": str(item.get("boundaries") or "").strip()[:5000],
                "sources": sources,
            }
        )
    finding_by_title = {_normalized_title(item["title"]): item for item in findings}
    hypotheses = []
    for item in (raw.get("innovation_hypotheses") or [])[:BRIEF_RESEARCH_HYPOTHESIS_LIMIT]:
        if not isinstance(item, dict):
            continue
        fields = {
            key: str(item.get(key) or "").strip()
            for key in (
                "title",
                "mechanism_hypothesis",
                "equipment_concept",
                "operational_value",
                "feasibility_basis",
                "verification_path",
                "countermeasures_and_risks",
            )
        }
        missing = [key for key, value in fields.items() if not value]
        source_titles = list(
            dict.fromkeys(
                str(value).strip()[:1000] for value in (item.get("source_titles") or [])[:8] if str(value).strip()
            )
        )
        matched_findings = [
            finding_by_title[key]
            for key in (_normalized_title(title) for title in source_titles)
            if key in finding_by_title
        ]
        if missing or not matched_findings:
            title = fields["title"] or "未命名创新假设"
            reason = f"缺少字段：{'、'.join(missing)}" if missing else "未引用本次已核验的调研发现标题"
            quality_gaps.append(f"{title}：{reason}，未纳入创新假设。")
            continue
        stable_material = f"{fields['title']}\n{fields['mechanism_hypothesis']}".strip().casefold()
        hypotheses.append(
            {
                "hypothesis_id": "research-" + hashlib.sha256(stable_material.encode()).hexdigest()[:24],
                "title": fields["title"][:1000],
                "mechanism_hypothesis": fields["mechanism_hypothesis"][:5000],
                "equipment_concept": fields["equipment_concept"][:5000],
                "operational_value": fields["operational_value"][:5000],
                "feasibility_basis": [fields["feasibility_basis"][:5000]],
                "verification_path": fields["verification_path"][:5000],
                "countermeasures_and_risks": fields["countermeasures_and_risks"][:5000],
                "source_titles": [finding["title"] for finding in matched_findings],
                "source_findings": matched_findings,
                "expected_effects": [fields["equipment_concept"][:5000], fields["operational_value"][:5000]],
                "validation_requirements": [
                    fields["verification_path"][:5000],
                    fields["countermeasures_and_risks"][:5000],
                ],
                "uncertainties": [fields["countermeasures_and_risks"][:5000]],
                "claim_level": "Hypothesis",
                "review_status": "pending",
                "expert_review_required": True,
                "discovery_mode": "research_explorer",
            }
        )
    return {
        "summary": str(raw.get("summary") or "").strip()[:20000],
        "innovation_outlook": str(raw.get("innovation_outlook") or "").strip()[:5000],
        "findings": findings,
        "innovation_hypotheses": hypotheses,
        "gaps": [
            *[str(item).strip()[:2000] for item in (raw.get("gaps") or [])[:20] if str(item).strip()],
            *(
                ["调研探索员 JSON 在输出末尾被截断，系统已恢复其中完整的发现与创新假设。"]
                if raw.get("_recovered_from_truncation")
                else []
            ),
            *quality_gaps,
        ][:20],
    }


async def _converge_research_digest_with_agent(
    snapshot: dict,
    ranked: list[dict],
    existing_digest: dict,
    *,
    model_spec: str,
    run_id: str,
    attempt: int,
    quality_failures: list[str],
) -> tuple[dict, list[str]]:
    """用现有证据启动快速收敛 Agent，避免深研排队导致空简报。"""
    if not str(model_spec or "").strip():
        return {}, ["未配置平台智能体模型，无法执行简报质量收敛。"]

    allowed_evidence = [
        {
            "title": str(item.get("title") or "").strip()[:500],
            "url": str(item.get("url") or "").strip()[:2048],
            "source": str(item.get("source") or "").strip()[:300],
            "published_at": str(item.get("published_at") or "unknown")[:100],
            "excerpt": str(item.get("excerpt") or "").strip()[:1600],
            "initial_claim_level": str(item.get("claim_level") or "Inference"),
        }
        for item in ranked[:20]
        if _normalized_url(item.get("url"))
    ]
    for finding in (existing_digest.get("findings") or [])[:BRIEF_RESEARCH_FINDING_LIMIT]:
        if not isinstance(finding, dict):
            continue
        excerpt = "\n".join(
            str(finding.get(field) or "").strip()
            for field in ("evidence", "principle", "maturity")
            if str(finding.get(field) or "").strip()
        )[:1600]
        for source in (finding.get("sources") or [])[:8]:
            if not isinstance(source, dict) or not _normalized_url(source.get("url")):
                continue
            allowed_evidence.append(
                {
                    "title": str(source.get("title") or finding.get("title") or "深研来源").strip()[:500],
                    "url": str(source.get("url") or "").strip()[:2048],
                    "source": "deep-research",
                    "published_at": str(finding.get("published_at") or "unknown")[:100],
                    "excerpt": excerpt,
                    "initial_claim_level": str(finding.get("claim_level") or "Inference"),
                }
            )
    allowed_evidence = list(
        {
            _normalized_url(item.get("url")): item for item in allowed_evidence if _normalized_url(item.get("url"))
        }.values()
    )[:40]
    if not allowed_evidence:
        return {}, ["候选证据与深研成果均没有可核验 URL，快速收敛 Agent 未运行。"]

    payload = {
        "as_of": utc_now().date().isoformat(),
        "subscription": snapshot["name"],
        "brief_type": snapshot.get("brief_type") or "daily",
        "topics": snapshot.get("topics") or [],
        "keywords": snapshot.get("keywords") or [],
        "quality_failures": quality_failures,
        "existing_findings": list(existing_digest.get("findings") or [])[:8],
        "allowed_evidence": allowed_evidence,
    }
    system_prompt = (
        "你是前沿军事技术简报的证据收敛智能体。你的任务不是重新联网搜索，而是仅依据输入的"
        "allowed_evidence 形成可发布的结构化研究成果。不得补写、猜测、改造或拼接任何 URL；"
        "sources.url 必须逐字符复制 allowed_evidence 中的 URL。目标是形成至少 3 条高价值调研发现，"
        "其中至少 1 条 Fact、1 条 Inference，并形成至少 1 条 Hypothesis。Fact 只能来自官方一手来源，"
        "同一结论的至少两个独立来源，或带 DOI 的原始技术论文对其自身方法、试验和结果的直接报告；"
        "单篇论文不得支撑列装状态、跨场景有效性或作战效能等外推结论，证据不足时必须标为 Inference。"
        "每条发现必须写清技术原理、"
        "证据所支持的变化、具体装备构型影响、成熟度及反制/失效边界。创新假设必须从本次发现中"
        "收敛为单一具体的新质武器装备，写清跨技术机理、装备形态、作战关系、最小验证试验和反制风险，"
        "并用 source_titles 精确引用本次 finding 标题。若证据无法支撑某项要求，不得虚构，在 gaps 说明。"
        "最终只输出一个 JSON 对象，不要 Markdown、说明或校验过程。JSON 结构与字段为："
        '{"summary":"总体判断","innovation_outlook":"可探索组合",'
        '"findings":[{"title":"技术发现","principle":"作用原理",'
        '"why_it_matters":"变化与军事价值","equipment_implication":"具体装备构型影响",'
        '"maturity":"论文|仿真|样机|地面试验|飞行/海试|部署/采办",'
        '"published_at":"YYYY-MM-DD或unknown","claim_level":"Fact|Inference",'
        '"evidence":"证据摘要","boundaries":"反制、风险与失效边界",'
        '"sources":[{"title":"来源名","url":"输入中的精确URL"}]}],'
        '"innovation_hypotheses":[{"title":"单一具体装备名称",'
        '"mechanism_hypothesis":"跨技术组合与待验证机理","equipment_concept":"具体装备形态",'
        '"operational_value":"可能改变的作战关系","feasibility_basis":"由发现支持的依据",'
        '"verification_path":"最小可验证试验","countermeasures_and_risks":"反制与失效边界",'
        '"source_titles":["对应 finding 精确标题"]}],"gaps":["证据缺口"]}。'
    )
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from platform_core.models.chat import load_chat_model

        model = load_chat_model(model_spec, session_id=f"innovation-brief-convergence:{run_id}")
        async with asyncio.timeout(BRIEF_CONVERGENCE_TIMEOUT_SECONDS):
            response = await model.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                ],
                config={
                    "tags": ["innovation-brief", "quality-convergence"],
                    "run_name": f"innovation_brief_convergence_{attempt}",
                },
            )
    except Exception as exc:
        return {}, [f"简报质量收敛 Agent 第 {attempt} 次运行失败：{str(exc)[:240]}"]

    parsed = _parse_research_explorer_digest(getattr(response, "content", response))
    grounded = _ground_research_digest(parsed, allowed_evidence)
    grounded["convergence_attempt"] = attempt
    return grounded, []


def _ground_research_digest(digest: dict, allowed_evidence: list[dict]) -> dict:
    """只保留输入证据白名单内的来源，并重新判定事实层级与假设锚点。"""
    allowed_by_url = {
        _normalized_url(item.get("url")): item for item in allowed_evidence if _normalized_url(item.get("url"))
    }
    rejected_source_count = 0
    findings = []
    for item in digest.get("findings") or []:
        accepted_sources = []
        for source in item.get("sources") or []:
            key = _normalized_url(source.get("url"))
            allowed = allowed_by_url.get(key)
            if allowed is None:
                rejected_source_count += 1
                continue
            accepted_sources.append(
                {
                    "title": str(allowed.get("title") or allowed.get("source") or source.get("title") or "原始来源")[
                        :500
                    ],
                    "url": str(allowed.get("url") or "")[:2048],
                }
            )
        accepted_sources = list({_normalized_url(source["url"]): source for source in accepted_sources}.values())
        if not accepted_sources:
            continue
        independent_sources = {_source_identity({"url": source["url"]}) for source in accepted_sources}
        official = any(_is_first_party({"url": source["url"]}) for source in accepted_sources)
        primary_research = any(_is_primary_research_source({"url": source["url"]}) for source in accepted_sources)
        claim_level = str(item.get("claim_level") or "Inference")
        if claim_level != "Fact" or (not official and not primary_research and len(independent_sources) < 2):
            claim_level = "Inference"
        findings.append({**item, "claim_level": claim_level, "sources": accepted_sources})

    valid_titles = {_normalized_title(item.get("title")): item.get("title") for item in findings}
    hypotheses = []
    for item in digest.get("innovation_hypotheses") or []:
        matched_titles = [
            valid_titles[key]
            for key in (_normalized_title(title) for title in (item.get("source_titles") or []))
            if key in valid_titles
        ]
        if not matched_titles:
            continue
        hypotheses.append({**item, "source_titles": list(dict.fromkeys(matched_titles))})

    return {
        **digest,
        "findings": findings,
        "innovation_hypotheses": hypotheses,
        "grounded_source_count": sum(len(item.get("sources") or []) for item in findings),
        "untrusted_source_rejected_count": rejected_source_count,
    }


def _merge_research_digests(primary: dict, supplement: dict) -> dict:
    """合并深研与快速收敛结果，保留深研运行身份并按标题去重。"""
    findings = []
    seen_findings = set()
    for item in [*(supplement.get("findings") or []), *(primary.get("findings") or [])]:
        key = _normalized_title(item.get("title"))
        if not key or key in seen_findings:
            continue
        seen_findings.add(key)
        findings.append(item)

    hypotheses = []
    seen_hypotheses = set()
    for item in [
        *(supplement.get("innovation_hypotheses") or []),
        *(primary.get("innovation_hypotheses") or []),
    ]:
        key = _hypothesis_identity(item)
        if key in seen_hypotheses:
            continue
        seen_hypotheses.add(key)
        hypotheses.append(item)

    return {
        **primary,
        "summary": str(primary.get("summary") or supplement.get("summary") or ""),
        "innovation_outlook": str(primary.get("innovation_outlook") or supplement.get("innovation_outlook") or ""),
        "findings": findings[:BRIEF_RESEARCH_FINDING_LIMIT],
        "innovation_hypotheses": hypotheses[:BRIEF_RESEARCH_HYPOTHESIS_LIMIT],
        "gaps": list(dict.fromkeys([*(primary.get("gaps") or []), *(supplement.get("gaps") or [])]))[:20],
        "grounded_source_count": int(primary.get("grounded_source_count") or 0)
        + int(supplement.get("grounded_source_count") or 0),
        "untrusted_source_rejected_count": int(primary.get("untrusted_source_rejected_count") or 0)
        + int(supplement.get("untrusted_source_rejected_count") or 0),
        "convergence_attempt": supplement.get("convergence_attempt") or primary.get("convergence_attempt"),
    }


def _merge_hypothesis_candidates(research_digest: dict, graph_hypotheses: list[dict]) -> list[dict]:
    """优先合并调研驱动设想，再由统一历史去重和总量配额筛选。"""
    return [
        *[item for item in (research_digest.get("innovation_hypotheses") or []) if isinstance(item, dict)],
        *graph_hypotheses,
    ]


def _extract_research_digest_json(text: str) -> dict | None:
    """兼容前后说明，并从被截断的 JSON 中恢复已经完整输出的条目。"""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        value = None
    if isinstance(value, dict):
        return value

    decoder = json.JSONDecoder()
    findings = []
    hypotheses = []
    for match in re.finditer(r"\{", text):
        try:
            candidate, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and any(key in candidate for key in ("summary", "findings", "gaps")):
            return candidate
        if not isinstance(candidate, dict):
            continue
        if candidate.get("title") and candidate.get("principle") and isinstance(candidate.get("sources"), list):
            findings.append(candidate)
        elif candidate.get("title") and candidate.get("mechanism_hypothesis"):
            hypotheses.append(candidate)
    if not findings and not hypotheses:
        return None
    return {
        "summary": _extract_json_string_field(text, "summary")
        or "调研探索员输出在末尾被截断，以下为系统恢复的完整高价值条目。",
        "innovation_outlook": _extract_json_string_field(text, "innovation_outlook"),
        "findings": findings,
        "innovation_hypotheses": hypotheses,
        "gaps": [],
        "_recovered_from_truncation": True,
    }


def _extract_json_string_field(text: str, field: str) -> str:
    """从不完整 JSON 中安全读取一个已闭合的字符串字段。"""
    match = re.search(rf'"{re.escape(field)}"\s*:\s*', text)
    if match is None:
        return ""
    try:
        value, _ = json.JSONDecoder().raw_decode(text, match.end())
    except json.JSONDecodeError:
        return ""
    return str(value).strip() if isinstance(value, str) else ""


def _model_content_text(content: Any) -> str:
    """统一模型字符串与 content blocks，避免列表字符串化破坏 JSON。"""
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text") or item.get("content") or "") for item in content if isinstance(item, dict)
        ).strip()
    return str(content or "").strip()


async def _discover_hypotheses(
    snapshot: dict,
    plan: list[dict],
    context: TaskContext,
) -> tuple[list[dict], list[str]]:
    hypotheses = []
    warnings = []
    query = "；".join(row["query"] for row in plan[:3])
    service = MilvusGraphService()
    for kb_id in snapshot["knowledge_ids"][:5]:
        await context.raise_if_cancelled()
        try:
            path_result = await service.discover_paths(
                kb_id,
                query=query,
                mode="requirement_driven",
                max_hops=4,
                max_paths=5,
                include_combinations=False,
            )
            candidates = discover_innovation_hypotheses(
                kb_id=kb_id,
                path_result=path_result,
                discovery_mode="top_down",
                max_candidates=5,
            )
            for item in candidates:
                hypotheses.append({**item, "claim_level": "Hypothesis", "kb_id": kb_id})
        except Exception as exc:
            warnings.append(f"知识图谱 {kb_id} 创新发现失败：{str(exc)[:240]}")
    return hypotheses, warnings


async def _historical_brief_context(db: AsyncSession, subscription_id: str) -> dict:
    """读取有限历史简报，为证据、假设和探索发现提供跨日报周报避重基线。"""
    rows = (
        await db.execute(
            select(InnovationBrief.evidence, InnovationBrief.sections)
            .where(
                InnovationBrief.subscription_id == subscription_id,
                InnovationBrief.published_at.is_not(None),
                InnovationBrief.published_at <= utc_now(),
            )
            .order_by(InnovationBrief.created_at.desc())
            .limit(30)
        )
    ).all()
    evidence = [item for row in rows for item in (row.evidence or []) if isinstance(item, dict)][:3000]
    hypotheses = [
        item
        for row in rows
        for item in ((row.sections or {}).get("innovation_hypotheses") or [])
        if isinstance(item, dict)
    ]
    findings = [
        item
        for row in rows
        for item in ((row.sections or {}).get("research_explorer_findings") or [])
        if isinstance(item, dict)
    ]
    recent_titles = list(
        dict.fromkeys(
            str(item.get("title") or item.get("mechanism_hypothesis") or "").strip()
            for item in [*evidence, *hypotheses, *findings]
            if str(item.get("title") or item.get("mechanism_hypothesis") or "").strip()
        )
    )[:80]
    return {
        "evidence": evidence,
        "hypothesis_keys": {_hypothesis_identity(item) for item in hypotheses},
        "research_finding_titles": {_normalized_title(item.get("title")) for item in findings},
        "recent_titles": recent_titles,
    }


async def _load_historical_brief_context(subscription_id: str) -> dict:
    """使用独立短会话读取历史基线，允许与外部取证并行。"""
    async with pg_manager.get_async_session_context() as db:
        return await _historical_brief_context(db, subscription_id)


def _score_and_classify(
    evidence: list[dict],
    snapshot: dict,
    history: set[str] | list[dict],
) -> list[dict]:
    focus_terms = {value.casefold() for value in [*snapshot["topics"], *snapshot["keywords"]] if value}
    discovery_terms = (
        {term.casefold() for term in OPEN_DISCOVERY_RELEVANCE_TERMS}
        if snapshot.get("open_discovery_enabled", True)
        else set()
    )
    signature_terms = focus_terms | discovery_terms
    historical_rows = history if isinstance(history, list) else []
    historical_fingerprints = (
        {str(item.get("fingerprint")) for item in historical_rows if item.get("fingerprint")}
        if historical_rows
        else set(history)
    )
    sources_by_signature: dict[str, set[str]] = {}
    for item in evidence:
        signature = _topic_signature(item, signature_terms)
        sources_by_signature.setdefault(signature, set()).add(_source_identity(item))

    rows = []
    for item in evidence:
        text = f"{item.get('title', '')} {item.get('excerpt', '')}".casefold()
        focus_matched = sum(1 for term in focus_terms if term in text)
        discovery_matched = sum(1 for term in discovery_terms if term in text)
        relevance = min(100.0, 35.0 + 20.0 * focus_matched) if focus_terms else 60.0
        if discovery_matched:
            relevance = max(relevance, min(85.0, 45.0 + 10.0 * discovery_matched))
        fingerprint = _evidence_fingerprint(item)
        change_signal, historical_match = _change_signal(
            item,
            fingerprint,
            historical_rows,
            signature_terms,
        )
        if fingerprint in historical_fingerprints:
            novelty = 20.0
            change_signal = "known"
        elif change_signal == "conflict":
            novelty = 100.0
        elif change_signal == "changed":
            novelty = 80.0
        else:
            novelty = 90.0
        credibility = _credibility_score(item)
        independent_sources = len(sources_by_signature.get(_topic_signature(item, signature_terms), set()))
        corroboration = min(100.0, 25.0 + max(0, independent_sources - 1) * 40.0)
        disruption = min(100.0, 30.0 + 14.0 * sum(term in text for term in DISRUPTION_TERMS))
        recency, recency_bucket, recency_days, published_datetime = _recency_score(item.get("published_at"))
        innovation_expansion = _innovation_expansion_score(text)
        score = round(
            relevance * 0.18
            + novelty * 0.17
            + credibility * 0.16
            + corroboration * 0.11
            + disruption * 0.14
            + recency * 0.14
            + innovation_expansion * 0.10,
            1,
        )
        official = _is_first_party(item)
        if item.get("pending_review"):
            claim_level = "Inference"
            claim_reason = "证据仍在暂存区等待审核，尚不能正式化为事实"
        elif official or independent_sources >= 2:
            claim_level = "Fact"
            claim_reason = "官方一手来源" if official else f"{independent_sources} 个独立来源交叉印证"
        else:
            claim_level = "Inference"
            claim_reason = "单一来源或证据链尚未完成交叉验证"
        rows.append(
            {
                **item,
                "fingerprint": fingerprint,
                "change_signal": change_signal,
                "historical_fingerprint": (historical_match.get("fingerprint") if historical_match else None),
                "claim_level": claim_level,
                "claim_reason": claim_reason,
                "score": score,
                "recency_bucket": recency_bucket,
                "recency_days": recency_days,
                "score_breakdown": {
                    "relevance": relevance,
                    "novelty": novelty,
                    "credibility": credibility,
                    "corroboration": corroboration,
                    "disruption_potential": disruption,
                    "recency": recency,
                    "innovation_expansion": innovation_expansion,
                },
                "_published_sort_value": published_datetime.timestamp() if published_datetime else 0.0,
                "independent_source_count": independent_sources,
                "risk": (
                    "待审核证据不得进入正式检索区或事实图谱"
                    if item.get("pending_review")
                    else "需核验原始上下文与发布时间"
                ),
                "verification_next": (
                    "补充独立来源并核对原始发布材料" if not official else "跟踪后续试验、部署或正式采购信息"
                ),
            }
        )
    ranked = sorted(
        rows,
        key=lambda item: (
            item["score"],
            item["score_breakdown"]["recency"],
            item["score_breakdown"]["innovation_expansion"],
            item["_published_sort_value"],
        ),
        reverse=True,
    )[:100]
    for item in ranked:
        item.pop("_published_sort_value", None)
    return ranked


def _select_high_value_evidence(ranked: list[dict], *, limit: int = BRIEF_MAX_ITEMS) -> list[dict]:
    """按评分选择新证据，优先保持来源多样性，不足时再按原排名补齐。"""
    if limit <= 0:
        return []
    candidates = []
    seen_titles = set()
    seen_urls = set()
    for item in ranked:
        if item.get("change_signal") == "known":
            continue
        title_key = _normalized_title(item.get("title"))
        url_key = _normalized_url(item.get("url"))
        if (title_key and title_key in seen_titles) or (url_key and url_key in seen_urls):
            continue
        if title_key:
            seen_titles.add(title_key)
        if url_key:
            seen_urls.add(url_key)
        candidates.append(item)
        if len(candidates) >= max(limit * 4, limit):
            break

    selected = []
    deferred = []
    source_counts: dict[str, int] = {}
    for item in candidates:
        source_key = _source_identity(item)
        if source_counts.get(source_key, 0) >= 2:
            deferred.append(item)
            continue
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        selected.append(item)
        if len(selected) >= limit:
            return selected
    for item in deferred:
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _select_novel_hypotheses(
    hypotheses: list[dict],
    *,
    historical_keys: set[str],
    limit: int = BRIEF_MAX_ITEMS,
) -> list[dict]:
    """选择未在近期日报或周报中出现的创新假设。"""
    if limit <= 0:
        return []
    selected = []
    seen = set(historical_keys)
    for item in hypotheses:
        key = _hypothesis_identity(item)
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= max(0, limit):
            break
    return selected


def _select_research_findings(
    findings: list[dict],
    *,
    historical_titles: set[str],
) -> list[dict]:
    """过滤近期已展示的调研探索员发现，并限制单期阅读密度。"""
    selected = []
    seen = set(historical_titles)
    for item in findings:
        title_key = _normalized_title(item.get("title"))
        if not title_key or title_key in seen:
            continue
        seen.add(title_key)
        selected.append(item)
        if len(selected) >= BRIEF_RESEARCH_FINDING_LIMIT:
            break
    return selected


def _change_signal(
    item: dict,
    fingerprint: str,
    history: list[dict],
    terms: set[str],
) -> tuple[str, dict | None]:
    """按同 URL/同主题历史识别新增、内容变化和否定性冲突。"""
    if not history:
        return "new", None
    url = str(item.get("url") or "").strip()
    signature = _topic_signature(item, terms)
    match = next(
        (
            row
            for row in history
            if (url and str(row.get("url") or "").strip() == url) or _topic_signature(row, terms) == signature
        ),
        None,
    )
    if match is None:
        return "new", None
    if str(match.get("fingerprint") or _evidence_fingerprint(match)) == fingerprint:
        return "known", match
    current_polarity = _claim_polarity(item)
    historical_polarity = _claim_polarity(match)
    if current_polarity and historical_polarity and current_polarity != historical_polarity:
        return "conflict", match
    return "changed", match


def _claim_polarity(item: dict) -> str:
    text = f"{item.get('title', '')} {item.get('excerpt', '')}".casefold()
    negative_terms = ("未", "不再", "否认", "失败", "取消", "推迟", "without", "denied", "failed", "cancelled")
    positive_terms = ("完成", "成功", "确认", "部署", "通过", "completed", "confirmed", "deployed", "successful")
    negative = any(term in text for term in negative_terms)
    positive = any(term in text for term in positive_terms)
    if negative:
        return "negative"
    if positive:
        return "positive"
    return ""


def _build_sections(
    ranked: list[dict],
    hypotheses: list[dict],
    warnings: list[str],
    *,
    research_digest: dict | None = None,
) -> dict:
    research_digest = research_digest or {}
    research_items = [
        _research_finding_to_evidence(item)
        for item in (research_digest.get("findings") or [])
        if isinstance(item, dict)
    ]
    confirmed_facts = _merge_section_evidence(
        [item for item in ranked if item["claim_level"] == "Fact"],
        [item for item in research_items if item["claim_level"] == "Fact"],
    )
    cross_validated_inferences = _merge_section_evidence(
        [item for item in ranked if item["claim_level"] == "Inference"],
        [item for item in research_items if item["claim_level"] == "Inference"],
    )
    return {
        "research_explorer_summary": research_digest.get("summary") or "",
        "research_explorer_outlook": research_digest.get("innovation_outlook") or "",
        "research_explorer_findings": research_digest.get("findings") or [],
        "research_explorer_gaps": research_digest.get("gaps") or [],
        "research_explorer_run_id": research_digest.get("agent_run_id"),
        "confirmed_facts": confirmed_facts,
        "cross_validated_inferences": cross_validated_inferences,
        "innovation_hypotheses": hypotheses,
        "evidence_gaps": [
            {
                "title": item.get("title"),
                "gap": item.get("claim_reason"),
                "next": item.get("verification_next"),
            }
            for item in ranked
            if item["claim_level"] != "Fact"
        ],
        "warnings": warnings,
    }


def _assess_brief_quality(sections: dict) -> dict:
    """在持久化前验证四层产物及其来源、机理和验证路径。"""
    findings = [item for item in (sections.get("research_explorer_findings") or []) if isinstance(item, dict)]
    qualified_findings = [
        item
        for item in findings
        if all(
            str(item.get(field) or "").strip()
            for field in ("title", "principle", "evidence", "equipment_implication", "boundaries")
        )
        and any(_normalized_url(source.get("url")) for source in (item.get("sources") or []))
    ]
    facts = [item for item in (sections.get("confirmed_facts") or []) if isinstance(item, dict)]
    inferences = [item for item in (sections.get("cross_validated_inferences") or []) if isinstance(item, dict)]
    hypotheses = [item for item in (sections.get("innovation_hypotheses") or []) if isinstance(item, dict)]
    qualified_hypotheses = [
        item
        for item in hypotheses
        if all(
            item.get(field)
            for field in (
                "mechanism_hypothesis",
                "equipment_concept",
                "operational_value",
                "verification_path",
                "countermeasures_and_risks",
                "source_titles",
            )
        )
    ]
    failures = []
    checks = (
        (len(qualified_findings), BRIEF_QUALITY_MIN_FINDINGS, "合格调研发现"),
        (len(facts), BRIEF_QUALITY_MIN_FACTS, "已证实事实"),
        (len(inferences), BRIEF_QUALITY_MIN_INFERENCES, "研判推断"),
        (len(qualified_hypotheses), BRIEF_QUALITY_MIN_HYPOTHESES, "证据锚定创新假设"),
    )
    for actual, minimum, label in checks:
        if actual < minimum:
            failures.append(f"{label}不足：{actual}/{minimum}")
    return {
        "passed": not failures,
        "failures": failures,
        "qualified_finding_count": len(qualified_findings),
        "fact_count": len(facts),
        "inference_count": len(inferences),
        "qualified_hypothesis_count": len(qualified_hypotheses),
    }


def _research_finding_to_evidence(item: dict) -> dict:
    """把探索员发现投影到事实/推断阅读层，同时保留多来源和原理信息。"""
    sources = [source for source in (item.get("sources") or []) if isinstance(source, dict)]
    primary = sources[0] if sources else {}
    title = str(item.get("title") or "未命名调研发现").strip()
    excerpt_parts = [
        str(item.get("evidence") or "").strip(),
        str(item.get("principle") or "").strip(),
        str(item.get("why_it_matters") or "").strip(),
        str(item.get("equipment_implication") or "").strip(),
        str(item.get("maturity") or "").strip(),
    ]
    claim_level = str(item.get("claim_level") or "Inference")
    if claim_level not in {"Fact", "Inference", "Hypothesis"}:
        claim_level = "Inference"
    source_count = len({_normalized_url(source.get("url")) for source in sources if source.get("url")})
    return {
        "id": "research-" + hashlib.sha256(title.casefold().encode()).hexdigest()[:24],
        "title": title,
        "excerpt": "\n".join(value for value in excerpt_parts if value)[:5000],
        "url": str(primary.get("url") or ""),
        "source": str(primary.get("title") or "调研探索员"),
        "sources": sources,
        "source_type": "research_explorer",
        "claim_level": claim_level,
        "claim_reason": (
            "调研探索员取得官方一手来源或至少两个独立来源并完成证据分层"
            if claim_level == "Fact"
            else "调研探索员已取得可追溯来源，但结论仍包含机理或作战关系推演"
        ),
        "verification_next": str(item.get("boundaries") or "继续核验工程试验、部署状态与反制边界"),
        "independent_source_count": source_count,
        "published_at": str(item.get("published_at") or "").strip(),
        "maturity": str(item.get("maturity") or "").strip(),
        "equipment_implication": str(item.get("equipment_implication") or "").strip(),
        "research_explorer": True,
    }


def _merge_section_evidence(primary: list[dict], research: list[dict]) -> list[dict]:
    """合并常规证据与探索发现，按标题和链接去重并限制单层阅读密度。"""
    result = []
    seen = set()
    for item in [*primary, *research]:
        key = _normalized_url(item.get("url")) or _normalized_title(item.get("title"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= BRIEF_MAX_ITEMS:
            break
    return result


def _build_summary(brief_type: str, sections: dict, warnings: list[str]) -> str:
    research_count = len(sections.get("research_explorer_findings") or [])
    facts = len(sections.get("confirmed_facts") or [])
    inferences = len(sections.get("cross_validated_inferences") or [])
    hypotheses = len(sections.get("innovation_hypotheses") or [])
    if research_count + facts + inferences + hypotheses == 0:
        lead = f"本次{_brief_type_label(brief_type)}未发现需要重复推送的新高价值信号。"
    else:
        lead = (
            f"本次{_brief_type_label(brief_type)}形成 {research_count} 条调研发现，"
            f"分层保留 {facts} 条已证实事实、{inferences} 条研判推断，"
            f"并提出 {hypotheses} 条始终保持 Hypothesis 的创新假设。"
        )
    return lead + (f" {len(warnings)} 个来源未完成取证，详见运行告警。" if warnings else "")


def _candidate_to_evidence(item: dict, *, evidence_type: str, review_status: str) -> dict:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "id": hashlib.sha256(str(item.get("external_key") or item.get("title")).encode()).hexdigest()[:24],
        "title": str(item.get("title") or "未命名证据"),
        "excerpt": str(item.get("markdown") or "")[:3000],
        "url": str(item.get("canonical_url") or ""),
        "source": str(metadata.get("source") or "WebSearch"),
        "source_type": evidence_type,
        "review_status": review_status,
        "pending_review": False,
        "published_at": metadata.get("published_at"),
        "discovered_at": format_utc_datetime(utc_now()),
        "search_snapshot": metadata.get("search_snapshot") or {},
    }


def _collection_update_evidence(source: KnowledgeSource, item: KnowledgeSourceItem) -> dict:
    """把来源暂存项投影为明确标注待审核的简报证据。"""
    return {
        "id": item.id,
        "title": item.title,
        "excerpt": item.markdown[:3000],
        "url": item.canonical_url,
        "source": source.name,
        "source_type": source.source_type,
        "review_status": item.review_status,
        "pending_review": True,
        "published_at": (item.metadata_json or {}).get("published_at"),
        "discovered_at": format_utc_datetime(item.discovered_at),
        "kb_id": item.kb_id,
        "source_item_id": item.id,
        "claim_level": "EvidenceGap",
        "claim_reason": "新采集内容尚未经过知识库管理者审核",
        "risk": "待审核证据不得进入正式检索区或事实图谱",
        "verification_next": "审核来源、正文与发布时间后决定是否正式入库",
    }


def _effective_significance_threshold(threshold: float, sensitivity: str) -> float:
    """按提醒敏感度调整显著性阈值并限制在 0–100。"""
    offset = {"conservative": 10.0, "standard": 0.0, "sensitive": -10.0}.get(sensitivity, 0.0)
    return min(100.0, max(0.0, threshold + offset))


def _should_run_research_explorer(
    *,
    brief_type: str,
    enabled: bool,
    ranked: list[dict],
    significance_threshold: float,
) -> bool:
    """启用探索后，日报与周报都执行深挖，避免低分弱信号导致 01/04 长期为空。"""
    return bool(enabled and brief_type in {"daily", "weekly"})


def _knowledge_result_to_evidence(kb_id: str, query: str, row: Any, index: int) -> dict:
    data = row if isinstance(row, dict) else {"content": str(row)}
    excerpt = str(data.get("content") or data.get("text") or data.get("page_content") or data)[:3000]
    title = str(data.get("filename") or data.get("title") or f"知识库证据 {index + 1}")
    fallback_id = f"{kb_id}:{index}:{hashlib.sha1(excerpt.encode()).hexdigest()[:12]}"
    return {
        "id": str(data.get("chunk_id") or data.get("id") or fallback_id),
        "title": title,
        "excerpt": excerpt,
        "url": "",
        "source": f"知识库 {kb_id}",
        "source_type": "knowledge_base",
        "review_status": "approved",
        "pending_review": False,
        "published_at": data.get("published_at"),
        "discovered_at": format_utc_datetime(utc_now()),
        "kb_id": kb_id,
        "file_id": data.get("file_id"),
        "chunk_id": data.get("chunk_id"),
        "query": query,
    }


def _dedupe_evidence(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for row in rows:
        key = row.get("url") or f"{row.get('source')}:{row.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _topic_signature(item: dict, terms: set[str] | None = None) -> str:
    text = f"{item.get('title', '')} {item.get('excerpt', '')}".casefold()
    matched_terms = sorted(term for term in (terms or set()) if term and term in text)
    if matched_terms:
        return "topic:" + "|".join(matched_terms[:5])
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(item.get("title") or "").casefold())
    tokens = [token for token in value.split() if len(token) > 1]
    return " ".join(tokens[:5]) or str(item.get("id") or "unknown")


def _normalized_title(value: Any) -> str:
    """把标题规范化为稳定避重键。"""
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())[:500]


def _normalized_url(value: Any) -> str:
    """忽略链接片段与常见跟踪参数，生成单期避重键。"""
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}{parsed.path.rstrip('/')}"


def _hypothesis_identity(item: dict) -> str:
    """优先使用稳定假设 ID，兼容旧数据和测试中的文本假设。"""
    stable_id = str(item.get("hypothesis_id") or "").strip()
    if stable_id:
        return f"id:{stable_id}"
    text = item.get("mechanism_hypothesis") or item.get("title") or item.get("feasibility_basis") or ""
    return "text:" + hashlib.sha256(str(text).strip().casefold().encode()).hexdigest()


def _source_identity(item: dict) -> str:
    parsed = urlparse(str(item.get("url") or ""))
    host = parsed.hostname
    if (host or "").casefold() in {"doi.org", "dx.doi.org"}:
        doi_prefix = parsed.path.strip("/").casefold().split("/", 1)[0]
        if doi_prefix.startswith("10."):
            return f"doi-registrant:{doi_prefix}"
    return (host or str(item.get("source") or "unknown")).casefold()


def _is_first_party(item: dict) -> bool:
    host = (urlparse(str(item.get("url") or "")).hostname or "").casefold()
    return any(host.endswith(suffix) for suffix in TRUSTED_FIRST_PARTY_SUFFIXES)


def _is_primary_research_source(item: dict) -> bool:
    """识别可直接证明论文自身方法与试验结果的注册 DOI 原始来源。"""
    parsed = urlparse(str(item.get("url") or "").strip())
    host = (parsed.hostname or "").casefold()
    return host in {"doi.org", "dx.doi.org"} and parsed.path.strip("/").casefold().startswith("10.")


def _credibility_score(item: dict) -> float:
    if _is_first_party(item):
        return 95.0
    if item.get("source_type") == "knowledge_base" or item.get("review_status") == "approved":
        return 78.0
    if item.get("pending_review"):
        return 52.0
    return 62.0


def _recency_score(value: Any) -> tuple[float, str, int | None, datetime | None]:
    """按真实发布时间提供软时效分；缺失或异常日期保留中性分。"""
    published_at = _parse_evidence_datetime(value)
    now = utc_now()
    if published_at is None or published_at > now + timedelta(days=1):
        return 45.0, "unknown", None, None

    age_days = max(0, (now - published_at).days)
    if age_days <= 7:
        return 100.0, "within_7_days", age_days, published_at
    if age_days <= 30:
        return 90.0, "within_30_days", age_days, published_at
    if age_days <= 90:
        return 75.0, "within_90_days", age_days, published_at
    if age_days <= 180:
        return 60.0, "within_180_days", age_days, published_at
    if age_days <= 365:
        return 45.0, "within_365_days", age_days, published_at
    if age_days <= 730:
        return 25.0, "within_2_years", age_days, published_at
    return 15.0, "older", age_days, published_at


def _parse_evidence_datetime(value: Any) -> datetime | None:
    """兼容来源中的 ISO 日期与时间戳，不用抓取时间伪装发布时间。"""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text or text.casefold() in {"unknown", "none", "null", "n/a"}:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _innovation_expansion_score(text: str) -> float:
    """对新概念与跨域组合提供软加权，不把词表变成准入门槛。"""
    matched = sum(term in text for term in INNOVATION_EXPANSION_TERMS)
    if matched == 0:
        return 30.0
    return min(100.0, 55.0 + matched * 15.0)


def _evidence_fingerprint(item: dict) -> str:
    payload = "|".join(
        [
            str(item.get("url") or ""),
            str(item.get("title") or "").casefold(),
            str(item.get("excerpt") or "")[:500],
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _advance_subscription_schedule(
    subscription: InnovationBriefSubscription,
    brief_type: str,
    *,
    scheduled_for: datetime,
) -> None:
    """从本次计划时刻之后推进游标，避免提前准备时再次得到同一时刻。"""
    if brief_type == "daily":
        subscription.next_daily_at = _next_run_at_aware(
            subscription.daily_cron,
            subscription.timezone,
            after=scheduled_for,
        )
    else:
        subscription.next_weekly_at = _next_run_at_aware(
            subscription.weekly_cron,
            subscription.timezone,
            after=scheduled_for,
        )


def _scheduled_run_delivery_enabled(
    subscription: InnovationBriefSubscription | None,
    run: InnovationBriefRun,
) -> bool:
    """判断定时运行在订阅变更后是否仍允许发布；手动运行不受调度开关影响。"""
    if run.scheduled_for is None:
        return True
    if subscription is None or not subscription.enabled:
        return False
    if run.brief_type == "daily":
        return bool(subscription.daily_enabled)
    if run.brief_type == "weekly":
        return bool(subscription.weekly_enabled)
    return False


def _next_run_at_aware(expression: str, timezone: str, *, after: datetime | None = None) -> datetime:
    """把旧调度器的 naive UTC 结果标记为 TIMESTAMPTZ 所需的 aware UTC。"""
    reference = after or utc_now()
    if reference.tzinfo is not None:
        reference = reference.astimezone(UTC).replace(tzinfo=None)
    return next_run_at(expression, timezone, reference).replace(tzinfo=UTC)


def _datetime_due(value: datetime, now: datetime) -> bool:
    if value.tzinfo is None:
        return value <= now.replace(tzinfo=None)
    return value <= now


def _subscription_dict(row: InnovationBriefSubscription) -> dict:
    prepare_delta = timedelta(minutes=BRIEF_PREPARE_AHEAD_MINUTES)
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "owner_uid": row.owner_uid,
        "name": row.name,
        "topics": list(row.topics or []),
        "keywords": list(row.keywords or []),
        "knowledge_ids": list(row.knowledge_ids or []),
        "source_ids": list(row.source_ids or []),
        "languages": list(row.languages or []),
        "timezone": row.timezone,
        "daily_enabled": bool(row.daily_enabled),
        "weekly_enabled": bool(row.weekly_enabled),
        "daily_cron": row.daily_cron,
        "weekly_cron": row.weekly_cron,
        "reminder_sensitivity": row.reminder_sensitivity,
        "significance_threshold": float(row.significance_threshold),
        "open_discovery_enabled": bool(row.open_discovery_enabled),
        "research_explorer_enabled": bool(row.research_explorer_enabled),
        "next_daily_at": format_utc_datetime(row.next_daily_at),
        "next_weekly_at": format_utc_datetime(row.next_weekly_at),
        "next_daily_prepare_at": format_utc_datetime(row.next_daily_at - prepare_delta if row.next_daily_at else None),
        "next_weekly_prepare_at": format_utc_datetime(
            row.next_weekly_at - prepare_delta if row.next_weekly_at else None
        ),
        "prepare_ahead_minutes": BRIEF_PREPARE_AHEAD_MINUTES,
        "enabled": bool(row.enabled),
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _run_dict(row: InnovationBriefRun) -> dict:
    return {
        "id": row.id,
        "subscription_id": row.subscription_id,
        "task_id": row.task_id,
        "brief_type": row.brief_type,
        "status": row.status,
        "query_plan": row.query_plan or [],
        "stats": row.stats or {},
        "error": row.error,
        "scheduled_for": format_utc_datetime(row.scheduled_for),
        "started_at": format_utc_datetime(row.started_at),
        "completed_at": format_utc_datetime(row.completed_at),
        "created_at": format_utc_datetime(row.created_at),
    }


def _brief_dict(row: InnovationBrief, *, detail: bool) -> dict:
    data = {
        "id": row.id,
        "run_id": row.run_id,
        "subscription_id": row.subscription_id,
        "brief_type": row.brief_type,
        "title": row.title,
        "summary": row.summary,
        "max_score": float(row.max_score),
        "significant": bool(row.significant),
        "unread": bool(row.unread),
        "created_at": format_utc_datetime(row.created_at),
        "published_at": format_utc_datetime(row.published_at),
        "read_at": format_utc_datetime(row.read_at),
    }
    if detail:
        data.update({"sections": row.sections or {}, "evidence": row.evidence or []})
    return data


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))[:100]


def _required_text(value: Any, label: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{label}不能为空")
    if len(normalized) > maximum:
        raise HTTPException(status_code=422, detail=f"{label}不能超过 {maximum} 个字符")
    return normalized


def _brief_type_label(value: str) -> str:
    return {
        "daily": "每日前沿技术简报",
        "weekly": "每周前沿技术汇总",
        "collection_update": "采集更新",
    }.get(value, value)
