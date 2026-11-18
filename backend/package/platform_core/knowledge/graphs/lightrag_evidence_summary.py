"""用 LLM 选择已审核证据行，生成不改写事实的检索摘要。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

from platform_core.knowledge.graphs.extractors.llm import LLMGraphExtractor

EVIDENCE_SUMMARY_VERSION = "defense-lightrag-extractive-evidence-summary-v1"
MAX_EVIDENCE_ROWS = 64
MAX_EVIDENCE_TEXT_CHARS = 800
MAX_SUMMARY_CONTEXT_CHARS = 24000
DEFAULT_MAX_SELECTED = 12

Completion = Callable[[str], Awaitable[dict[str, Any]]]


class LightRAGEvidenceSummarySelector:
    """只选择 accepted evidence ID，平台负责原样渲染对应证据。"""

    def __init__(self, options: dict[str, Any] | None = None, *, completion: Completion | None = None):
        self.options = dict(options or {})
        self._completion = completion
        self._extractor: LLMGraphExtractor | None = None

    async def enhance_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """为实体向量追加抽取式证据摘要，失败时按 strict 策略处理。"""
        candidates = [deepcopy(record) for record in records]
        if not self.options.get("enabled"):
            return candidates
        model_spec = str(self.options.get("model_spec") or "").strip()
        if not model_spec:
            raise ValueError("启用已审核证据摘要时必须配置 model_spec")
        _validate_source_text_policy(self.options, model_spec=model_spec)
        strict = self.options.get("strict", False)
        if not isinstance(strict, bool):
            raise ValueError("已审核证据摘要 strict 必须是布尔值")

        semaphore = asyncio.Semaphore(self._concurrency)

        async def enhance(record: dict[str, Any]) -> dict[str, Any] | Exception:
            async with semaphore:
                try:
                    return await self._enhance_record(record)
                except Exception as exc:  # noqa: BLE001
                    if strict:
                        return exc
                    record["evidence_summary"] = self._provenance(
                        status="degraded",
                        selected_count=0,
                        failure_type=type(exc).__name__,
                    )
                    return record

        results = await asyncio.gather(*(enhance(record) for record in candidates))
        for result in results:
            if isinstance(result, Exception):
                raise result
        return results

    async def aclose(self) -> None:
        """释放选择器独占的模型连接。"""
        if self._extractor is not None:
            await self._extractor.aclose()
            self._extractor = None

    async def _enhance_record(self, record: dict[str, Any]) -> dict[str, Any]:
        evidence_rows = _normalize_evidence_rows(record.get("evidence_rows") or [])
        if not evidence_rows:
            record["evidence_summary"] = self._provenance(status="empty", selected_count=0)
            return record
        prompt = _selection_prompt(
            entity_profile=str(record.get("content") or ""),
            evidence_rows=evidence_rows,
            max_selected=self._max_selected,
        )
        payload = await self._complete(prompt)
        selected = _selected_rows(payload, evidence_rows, max_selected=self._max_selected)
        if selected:
            exact_lines = [f"- [{item['evidence_id']}] {item['text']}" for item in selected]
            record["content"] = f"{record.get('content') or ''}\n检索证据摘录：\n" + "\n".join(exact_lines)
        record["evidence_summary"] = self._provenance(
            status="completed",
            selected_count=len(selected),
            selected_evidence_ids=[item["evidence_id"] for item in selected],
        )
        return record

    async def _complete(self, prompt: str) -> dict[str, Any]:
        if self._completion is not None:
            return await self._completion(prompt)
        if self._extractor is None:
            self._extractor = LLMGraphExtractor(
                {
                    "model_spec": str(self.options["model_spec"]),
                    "timeout_seconds": self.options.get("timeout_seconds", 90),
                    "max_output_tokens": self.options.get("max_output_tokens", 2048),
                    "enable_thinking": self.options.get("enable_thinking", False),
                    "model_params": dict(self.options.get("model_params") or {}),
                    "enable_hypothesis_extraction": False,
                    "max_hypotheses_per_chunk": 0,
                }
            )
        return await self._extractor.complete_json(prompt, required_keys=("selected_evidence_ids",))

    @property
    def _concurrency(self) -> int:
        return max(1, min(int(self.options.get("concurrency") or 4), 8))

    @property
    def _max_selected(self) -> int:
        return max(1, min(int(self.options.get("max_selected") or DEFAULT_MAX_SELECTED), 24))

    def _provenance(
        self,
        *,
        status: str,
        selected_count: int,
        selected_evidence_ids: list[str] | None = None,
        failure_type: str | None = None,
    ) -> dict[str, Any]:
        value = {
            "summary_version": EVIDENCE_SUMMARY_VERSION,
            "status": status,
            "model_spec": str(self.options.get("model_spec") or "").strip() or None,
            "selected_count": selected_count,
            "extractive_only": True,
            "authoritative_write": False,
        }
        if selected_evidence_ids is not None:
            value["selected_evidence_ids"] = selected_evidence_ids
        if failure_type:
            value["failure_type"] = failure_type
        return value


def _normalize_evidence_rows(values: list[Any]) -> list[dict[str, str]]:
    rows = []
    seen = set()
    for value in values[:MAX_EVIDENCE_ROWS]:
        if not isinstance(value, dict):
            continue
        evidence_id = str(value.get("evidence_id") or "").strip()
        text = " ".join(str(value.get("text") or "").split()).strip()[:MAX_EVIDENCE_TEXT_CHARS]
        kind = str(value.get("kind") or "evidence").strip()[:40]
        if not evidence_id or not text or evidence_id in seen:
            continue
        seen.add(evidence_id)
        rows.append({"evidence_id": evidence_id, "kind": kind, "text": text})
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_SUMMARY_CONTEXT_CHARS:
        raise ValueError("已审核证据摘要候选超过上下文硬上限")
    return rows


def _validate_source_text_policy(options: dict[str, Any], *, model_spec: str) -> None:
    policy = str(options.get("source_text_policy") or "").strip()
    if policy not in {"local_only", "approved_external"}:
        raise ValueError("已审核证据摘要必须声明 local_only 或 approved_external")
    if policy != "local_only":
        return
    configured = options.get("local_provider_ids") or []
    if not isinstance(configured, list):
        raise ValueError("已审核证据摘要 local_provider_ids 必须是数组")
    local_provider_ids = {
        "local",
        "local-provider",
        "local-llm",
        "ollama",
        "lmstudio",
        *(str(value).strip().casefold() for value in configured if str(value).strip()),
    }
    if model_spec.split(":", 1)[0].casefold() not in local_provider_ids:
        raise ValueError("local_only 策略拒绝未登记的模型提供方")


def _selected_rows(
    payload: dict[str, Any],
    evidence_rows: list[dict[str, str]],
    *,
    max_selected: int,
) -> list[dict[str, str]]:
    requested = payload.get("selected_evidence_ids")
    if not isinstance(requested, list):
        raise ValueError("已审核证据摘要模型必须返回 selected_evidence_ids 数组")
    by_id = {item["evidence_id"]: item for item in evidence_rows}
    selected = []
    seen = set()
    for value in requested:
        evidence_id = str(value or "").strip()
        if evidence_id in by_id and evidence_id not in seen:
            seen.add(evidence_id)
            selected.append(by_id[evidence_id])
        if len(selected) >= max_selected:
            break
    return selected


def _selection_prompt(*, entity_profile: str, evidence_rows: list[dict[str, str]], max_selected: int) -> str:
    return f"""你是军事武器装备技术原理知识图谱的检索证据选择器。
你只能从给定 evidence_id 中选择最有助于实体检索、机理检索和关系检索的证据行。

硬约束：
- 只返回 evidence_id，不得生成、概括或改写任何事实；
- 不得返回候选外的 ID；
- 最多选择 {max_selected} 条，优先保留作用机理、技术实现、能力作用和适用条件；
- OCR 噪声、重复行和只有名称而无技术信息的行应降权；
- 不输出解释、Markdown、关键词或自然语言摘要。

实体画像：{entity_profile[:4000]}
已审核证据：{json.dumps(evidence_rows, ensure_ascii=False, separators=(",", ":"))}

严格返回：{{"selected_evidence_ids":["候选 evidence_id"]}}
"""
