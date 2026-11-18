"""知识图谱构建谱系与验收登记的应用服务。"""

from __future__ import annotations

import re
from typing import Any

from platform_core.knowledge.training.graph_acceptance import (
    AUTHORITATIVE_ACCEPTANCE_SNAPSHOT_CONTRACT,
    PILOT_ACCEPTANCE_CONTRACT,
    PILOT_ACCEPTANCE_CRITERIA,
    validate_pilot_acceptance_report,
    validate_pilot_build_stats_consistency,
)
from platform_core.knowledge.training.pilot_requirements import pilot_requirement_payload
from platform_core.repositories.knowledge_graph_acceptance_repository import (
    KnowledgeGraphAcceptanceRepository,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ACCEPTANCE_CRITERIA = PILOT_ACCEPTANCE_CRITERIA


class KnowledgeGraphAcceptanceService:
    """组合权威规模统计、构建运行和不可变评测报告。"""

    def __init__(self, repository: KnowledgeGraphAcceptanceRepository | None = None):
        self.repository = repository or KnowledgeGraphAcceptanceRepository()

    async def get_status(self, kb_id: str) -> dict[str, Any]:
        """返回后端判定的 Pilot 验收状态，前端只负责展示。"""
        stats = await self.repository.collect_pilot_stats(kb_id)
        build_runs = await self.repository.get_build_run_summary(kb_id)
        evaluation = await self.repository.get_latest_evaluation(kb_id)
        common = {
            "snapshot_contract": AUTHORITATIVE_ACCEPTANCE_SNAPSHOT_CONTRACT,
            "kb_id": kb_id,
            "requirements": pilot_requirement_payload(),
            "stats": stats,
            "build_runs": build_runs,
        }
        if evaluation is None:
            return {
                **common,
                "passed": False,
                "failed_criteria": ["evaluation_missing"],
                "latest_evaluation": None,
            }

        report = evaluation["report"]
        if report.get("acceptance_contract") != PILOT_ACCEPTANCE_CONTRACT:
            return {
                **common,
                "passed": False,
                "failed_criteria": ["evaluation_contract_outdated"],
                "latest_evaluation": evaluation,
            }
        try:
            self._validate_report(report)
            self._validate_build_stats(report, stats)
        except ValueError:
            return {
                **common,
                "passed": False,
                "failed_criteria": ["authoritative_state_drift"],
                "latest_evaluation": evaluation,
            }
        return {
            **common,
            "passed": evaluation["status"] == "passed" and report.get("passed") is True,
            "failed_criteria": list(report.get("failed_criteria") or []),
            "latest_evaluation": evaluation,
        }

    async def list_build_runs(self, *, kb_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """读取构建运行摘要。"""
        return await self.repository.list_build_runs(kb_id=kb_id, limit=limit, offset=offset)

    async def get_build_run(self, *, kb_id: str, run_id: str) -> dict[str, Any]:
        """读取构建运行及阶段日志。"""
        result = await self.repository.get_build_run_with_stages(kb_id=kb_id, run_id=run_id)
        if result is None:
            raise LookupError("图谱构建运行不存在")
        return result

    async def record_evaluation(
        self,
        *,
        kb_id: str,
        pipeline_revision: str,
        gold_manifest_sha256: str,
        prediction_sha256: str,
        report: dict[str, Any],
        created_by: str | None,
    ) -> dict[str, Any]:
        """校验 CLI 验收契约并幂等写入权威记录。"""
        self._validate_sha256(gold_manifest_sha256, "gold_manifest_sha256")
        self._validate_sha256(prediction_sha256, "prediction_sha256")
        self._validate_report(report)
        current_stats = await self.repository.collect_pilot_stats(kb_id)
        self._validate_build_stats(report, current_stats)
        evaluation_id = await self.repository.record_evaluation(
            kb_id=kb_id,
            pipeline_revision=pipeline_revision,
            gold_manifest_sha256=gold_manifest_sha256,
            prediction_sha256=prediction_sha256,
            report=report,
            created_by=created_by,
        )
        return {"evaluation_id": evaluation_id, "status": "passed" if report["passed"] else "failed"}

    @staticmethod
    def _validate_sha256(value: str, field: str) -> None:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError(f"{field} 必须是 64 位小写 SHA-256")

    @staticmethod
    def _validate_report(report: dict[str, Any]) -> None:
        validate_pilot_acceptance_report(report)

    @staticmethod
    def _validate_build_stats(report: dict[str, Any], stats: dict[str, Any]) -> None:
        validate_pilot_build_stats_consistency(report, stats)
