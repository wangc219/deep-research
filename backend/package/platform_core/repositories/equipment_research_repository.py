"""装备研究 PostgreSQL Repository。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.storage.postgres.models_equipment import (
    EquipmentArtifactRef,
    EquipmentCapabilityVersion,
    EquipmentDeepBranch,
    EquipmentDeepJob,
    EquipmentDeepMessage,
    EquipmentDeepSession,
    EquipmentExpertFeedback,
    EquipmentFavorite,
    EquipmentQuery,
    EquipmentQueryGeneration,
    EquipmentQueryRevision,
    EquipmentResearchEvent,
    EquipmentResearchRun,
)
from platform_core.utils.datetime_utils import utc_now_naive

EQUIPMENT_DEEP_JOB_TERMINAL_STATUSES = (
    "completed",
    "failed",
    "failed_to_queue",
    "cancelled",
    "archived",
    "partial",
    "blocked",
    "rejected",
    "interrupted",
)


def _visible_clause(model, owner_uid: str | None, *, include_legacy: bool = False):
    """管理员读取全部；普通用户读取自己的数据和融合前的只读历史数据。"""
    if owner_uid is None:
        return true()
    owner_clause = model.owner_uid == owner_uid
    if hasattr(model, "import_batch_id"):
        owner_clause = owner_clause & or_(
            model.import_batch_id.is_(None), model.import_batch_id != "workbench-sync"
        )
    if not include_legacy:
        return owner_clause
    legacy_clauses = []
    if hasattr(model, "legacy_source_id"):
        legacy_clauses.append(model.legacy_source_id.is_not(None))
    if hasattr(model, "import_batch_id"):
        legacy_clauses.append(model.import_batch_id == "workbench-sync")
    return or_(owner_clause, *legacy_clauses) if legacy_clauses else owner_clause


class EquipmentResearchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_run(self, run_id: str) -> EquipmentResearchRun | None:
        return await self.session.get(EquipmentResearchRun, run_id)

    async def lock_run(self, run_id: str) -> EquipmentResearchRun | None:
        """串行化任务控制与 Worker 回写，并刷新事务中可能过期的状态。"""
        return await self.session.get(EquipmentResearchRun, run_id, with_for_update=True, populate_existing=True)

    async def add_run(self, run: EquipmentResearchRun) -> EquipmentResearchRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def list_runs_for_user(
        self,
        *,
        owner_uid: str,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_legacy: bool = False,
    ) -> list[EquipmentResearchRun]:
        stmt = select(EquipmentResearchRun).where(
            _visible_clause(EquipmentResearchRun, owner_uid, include_legacy=include_legacy)
        )
        if project_id:
            stmt = stmt.where(EquipmentResearchRun.project_id == project_id)
        if status:
            stmt = stmt.where(EquipmentResearchRun.status == status)
        stmt = stmt.order_by(EquipmentResearchRun.updated_at.desc()).offset(max(offset, 0)).limit(max(limit, 1))
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_by_status(self, owner_uid: str) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(EquipmentResearchRun.status, func.count())
                .where(_visible_clause(EquipmentResearchRun, owner_uid))
                .group_by(EquipmentResearchRun.status)
            )
        ).all()
        return {str(status): int(count) for status, count in rows}

    async def next_event_sequence(self, run_id: str) -> int:
        current = await self.session.scalar(
            select(func.max(EquipmentResearchEvent.sequence)).where(EquipmentResearchEvent.run_id == run_id)
        )
        return int(current or 0) + 1

    async def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> EquipmentResearchEvent:
        event = EquipmentResearchEvent(
            run_id=run_id,
            sequence=await self.next_event_sequence(run_id),
            event_type=event_type,
            payload=payload,
            created_at=utc_now_naive(),
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[EquipmentResearchEvent]:
        stmt = (
            select(EquipmentResearchEvent)
            .where(EquipmentResearchEvent.run_id == run_id, EquipmentResearchEvent.sequence > after_seq)
            .order_by(EquipmentResearchEvent.sequence.asc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_queries(
        self,
        owner_uid: str | None,
        project_id: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
        include_legacy: bool = False,
    ) -> list[EquipmentQuery]:
        stmt = select(EquipmentQuery).where(_visible_clause(EquipmentQuery, owner_uid, include_legacy=include_legacy))
        if project_id:
            stmt = stmt.where(EquipmentQuery.project_id == project_id)
        if status:
            stmt = stmt.where(EquipmentQuery.status == status)
        if source_type:
            stmt = stmt.where(EquipmentQuery.source_type == source_type)
        normalized_search = search.strip()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            stmt = stmt.where(
                or_(
                    EquipmentQuery.query_text.ilike(pattern),
                    EquipmentQuery.supplemental_information.ilike(pattern),
                )
            )
        stmt = (
            stmt.order_by(EquipmentQuery.updated_at.desc())
            .offset(max(offset, 0))
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_queries(
        self,
        owner_uid: str | None,
        *,
        project_id: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        search: str = "",
        include_legacy: bool = False,
    ) -> int:
        stmt = select(func.count(EquipmentQuery.id)).where(
            _visible_clause(EquipmentQuery, owner_uid, include_legacy=include_legacy)
        )
        if project_id:
            stmt = stmt.where(EquipmentQuery.project_id == project_id)
        if status:
            stmt = stmt.where(EquipmentQuery.status == status)
        if source_type:
            stmt = stmt.where(EquipmentQuery.source_type == source_type)
        normalized_search = search.strip()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            stmt = stmt.where(
                or_(
                    EquipmentQuery.query_text.ilike(pattern),
                    EquipmentQuery.supplemental_information.ilike(pattern),
                )
            )
        return int(await self.session.scalar(stmt) or 0)

    async def get_query(self, query_id: str) -> EquipmentQuery | None:
        return await self.session.get(EquipmentQuery, query_id)

    async def lock_query(self, query_id: str) -> EquipmentQuery | None:
        return await self.session.get(EquipmentQuery, query_id, with_for_update=True, populate_existing=True)

    async def add_query(self, query: EquipmentQuery) -> EquipmentQuery:
        self.session.add(query)
        await self.session.flush()
        return query

    async def add_query_revision(self, revision: EquipmentQueryRevision) -> EquipmentQueryRevision:
        self.session.add(revision)
        await self.session.flush()
        return revision

    async def list_query_revisions(self, query_id: str) -> list[EquipmentQueryRevision]:
        stmt = (
            select(EquipmentQueryRevision)
            .where(EquipmentQueryRevision.query_id == query_id)
            .order_by(EquipmentQueryRevision.version.desc(), EquipmentQueryRevision.id.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_query(self, query_id: str) -> None:
        await self.session.execute(delete(EquipmentQuery).where(EquipmentQuery.id == query_id))
        await self.session.flush()

    async def list_capability_versions(
        self, owner_uid: str, limit: int = 50, include_legacy: bool = False
    ) -> list[EquipmentCapabilityVersion]:
        stmt = (
            select(EquipmentCapabilityVersion)
            .where(_visible_clause(EquipmentCapabilityVersion, owner_uid, include_legacy=include_legacy))
            .order_by(EquipmentCapabilityVersion.created_at.desc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_capability_versions_for_run(
        self,
        *,
        owner_uid: str,
        run_id: str,
        limit: int = 50,
    ) -> list[EquipmentCapabilityVersion]:
        stmt = (
            select(EquipmentCapabilityVersion)
            .where(
                EquipmentCapabilityVersion.owner_uid == owner_uid,
                EquipmentCapabilityVersion.run_id == run_id,
            )
            .order_by(EquipmentCapabilityVersion.created_at.desc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_capability_version(self, version: EquipmentCapabilityVersion) -> EquipmentCapabilityVersion:
        self.session.add(version)
        await self.session.flush()
        return version

    async def get_capability_version(self, version_id: str) -> EquipmentCapabilityVersion | None:
        return await self.session.get(EquipmentCapabilityVersion, version_id)

    async def delete_capability_version(self, version_id: str) -> None:
        await self.session.execute(
            delete(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.id == version_id)
        )
        await self.session.flush()

    async def list_expert_feedback(
        self, *, owner_uid: str, run_id: str, limit: int = 100
    ) -> list[EquipmentExpertFeedback]:
        stmt = (
            select(EquipmentExpertFeedback)
            .where(
                EquipmentExpertFeedback.owner_uid == owner_uid,
                EquipmentExpertFeedback.run_id == run_id,
            )
            .order_by(EquipmentExpertFeedback.created_at.desc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_expert_feedback(self, feedback_id: str) -> EquipmentExpertFeedback | None:
        return await self.session.get(EquipmentExpertFeedback, feedback_id)

    async def add_expert_feedback(self, feedback: EquipmentExpertFeedback) -> EquipmentExpertFeedback:
        self.session.add(feedback)
        await self.session.flush()
        return feedback

    async def list_favorites(
        self,
        owner_uid: str | None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EquipmentFavorite]:
        stmt = (
            select(EquipmentFavorite)
            .where(_visible_clause(EquipmentFavorite, owner_uid))
            .order_by(EquipmentFavorite.updated_at.desc())
            .offset(max(offset, 0))
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_favorite(self, favorite_id: str) -> EquipmentFavorite | None:
        return await self.session.get(EquipmentFavorite, favorite_id)

    async def find_favorite(
        self,
        *,
        owner_uid: str,
        run_id: str,
        card_key: str,
    ) -> EquipmentFavorite | None:
        return await self.session.scalar(
            select(EquipmentFavorite)
            .where(
                EquipmentFavorite.owner_uid == owner_uid,
                EquipmentFavorite.run_id == run_id,
                EquipmentFavorite.card_key == card_key,
            )
            .limit(1)
        )

    async def add_favorite(self, favorite: EquipmentFavorite) -> EquipmentFavorite:
        self.session.add(favorite)
        await self.session.flush()
        return favorite

    async def delete_favorite(self, favorite_id: str) -> None:
        await self.session.execute(delete(EquipmentFavorite).where(EquipmentFavorite.id == favorite_id))
        await self.session.flush()

    async def list_deep_sessions(
        self, owner_uid: str | None, limit: int = 200, include_legacy: bool = False
    ) -> list[EquipmentDeepSession]:
        stmt = (
            select(EquipmentDeepSession)
            .where(_visible_clause(EquipmentDeepSession, owner_uid, include_legacy=include_legacy))
            .order_by(EquipmentDeepSession.updated_at.desc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_query_by_fingerprint(self, fingerprint: str) -> EquipmentQuery | None:
        return await self.session.scalar(
            select(EquipmentQuery).where(EquipmentQuery.query_fingerprint == fingerprint).limit(1)
        )

    async def add_generation(self, generation: EquipmentQueryGeneration) -> EquipmentQueryGeneration:
        self.session.add(generation)
        await self.session.flush()
        return generation

    async def get_generation(self, generation_id: str) -> EquipmentQueryGeneration | None:
        return await self.session.get(EquipmentQueryGeneration, generation_id)

    async def lock_generation(self, generation_id: str) -> EquipmentQueryGeneration | None:
        return await self.session.get(
            EquipmentQueryGeneration,
            generation_id,
            with_for_update=True,
            populate_existing=True,
        )

    async def list_generations(
        self,
        owner_uid: str | None,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[EquipmentQueryGeneration]:
        stmt = select(EquipmentQueryGeneration).where(_visible_clause(EquipmentQueryGeneration, owner_uid))
        if project_id:
            stmt = stmt.where(EquipmentQueryGeneration.project_id == project_id)
        if status:
            stmt = stmt.where(EquipmentQueryGeneration.status == status)
        stmt = (
            stmt.order_by(EquipmentQueryGeneration.updated_at.desc())
            .offset(max(offset, 0))
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_generations(
        self,
        owner_uid: str | None,
        *,
        project_id: str | None = None,
        status: str | None = None,
    ) -> int:
        stmt = select(func.count(EquipmentQueryGeneration.id)).where(
            _visible_clause(EquipmentQueryGeneration, owner_uid)
        )
        if project_id:
            stmt = stmt.where(EquipmentQueryGeneration.project_id == project_id)
        if status:
            stmt = stmt.where(EquipmentQueryGeneration.status == status)
        return int(await self.session.scalar(stmt) or 0)

    async def delete_generation(self, generation_id: str) -> None:
        await self.session.execute(
            delete(EquipmentQueryGeneration).where(EquipmentQueryGeneration.id == generation_id)
        )
        await self.session.flush()

    async def add_deep_session(self, session: EquipmentDeepSession) -> EquipmentDeepSession:
        self.session.add(session)
        await self.session.flush()
        return session

    async def get_deep_session(self, session_id: str) -> EquipmentDeepSession | None:
        return await self.session.get(EquipmentDeepSession, session_id)

    async def lock_deep_session(self, session_id: str) -> EquipmentDeepSession | None:
        """Lock one deep session while a cross-table mutation is coordinated."""

        return await self.session.get(
            EquipmentDeepSession,
            session_id,
            with_for_update=True,
            populate_existing=True,
        )

    async def delete_deep_session(self, session_id: str) -> None:
        await self.session.execute(delete(EquipmentDeepSession).where(EquipmentDeepSession.id == session_id))
        await self.session.flush()

    async def add_deep_message(self, message: EquipmentDeepMessage) -> EquipmentDeepMessage:
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_deep_messages(self, session_id: str, limit: int = 80) -> list[EquipmentDeepMessage]:
        stmt = (
            select(EquipmentDeepMessage)
            .where(EquipmentDeepMessage.session_id == session_id)
            .order_by(EquipmentDeepMessage.created_at.asc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_deep_job(self, job: EquipmentDeepJob) -> EquipmentDeepJob:
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_deep_job(self, job_id: str) -> EquipmentDeepJob | None:
        return await self.session.get(EquipmentDeepJob, job_id)

    async def list_deep_jobs(self, session_id: str, limit: int = 20) -> list[EquipmentDeepJob]:
        stmt = (
            select(EquipmentDeepJob)
            .where(EquipmentDeepJob.session_id == session_id)
            .order_by(EquipmentDeepJob.created_at.desc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_nonterminal_deep_jobs(self, session_id: str) -> list[EquipmentDeepJob]:
        """Return every job that could still write to the session."""

        stmt = (
            select(EquipmentDeepJob)
            .where(
                EquipmentDeepJob.session_id == session_id,
                EquipmentDeepJob.status.notin_(EQUIPMENT_DEEP_JOB_TERMINAL_STATUSES),
            )
            .order_by(EquipmentDeepJob.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_deep_branch(self, branch: EquipmentDeepBranch) -> EquipmentDeepBranch:
        self.session.add(branch)
        await self.session.flush()
        return branch

    async def list_deep_branches(self, session_id: str, limit: int = 30) -> list[EquipmentDeepBranch]:
        stmt = (
            select(EquipmentDeepBranch)
            .where(EquipmentDeepBranch.session_id == session_id)
            .order_by(EquipmentDeepBranch.created_at.asc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_artifact_refs(self, run_id: str, limit: int = 80) -> list[EquipmentArtifactRef]:
        stmt = (
            select(EquipmentArtifactRef)
            .where(EquipmentArtifactRef.run_id == run_id)
            .order_by(EquipmentArtifactRef.created_at.desc())
            .limit(max(limit, 1))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def portal_stats(self, owner_uid: str, *, include_legacy: bool = False) -> dict[str, int]:
        visible_runs = _visible_clause(EquipmentResearchRun, owner_uid, include_legacy=include_legacy)
        run_total = int(
            await self.session.scalar(
                select(func.count(EquipmentResearchRun.id)).where(
                    visible_runs, EquipmentResearchRun.status != "archived"
                )
            )
            or 0
        )
        query_total = int(
            await self.session.scalar(
                select(func.count(EquipmentQuery.id)).where(
                    _visible_clause(EquipmentQuery, owner_uid, include_legacy=include_legacy),
                    EquipmentQuery.status != "archived",
                )
            )
            or 0
        )
        capability_total = int(
            await self.session.scalar(
                select(func.count(EquipmentCapabilityVersion.id)).where(
                    _visible_clause(EquipmentCapabilityVersion, owner_uid, include_legacy=include_legacy)
                )
            )
            or 0
        )
        deep_total = int(
            await self.session.scalar(
                select(func.count(EquipmentDeepSession.id)).where(
                    _visible_clause(EquipmentDeepSession, owner_uid, include_legacy=include_legacy)
                )
            )
            or 0
        )
        return {
            "runs": run_total,
            "queries": query_total,
            "capabilities": capability_total,
            "deep_sessions": deep_total,
            "completed_runs": int(
                await self.session.scalar(
                    select(func.count(EquipmentResearchRun.id)).where(
                        visible_runs,
                        EquipmentResearchRun.status == "completed",
                    )
                )
                or 0
            ),
        }
