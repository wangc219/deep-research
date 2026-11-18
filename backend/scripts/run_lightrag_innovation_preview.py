#!/usr/bin/env python3
"""对现有本地知识库运行项目模型驱动的双向创新预览。"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from run_lightrag_fusion_pilot import local_operator_headers


async def run(args: argparse.Namespace) -> dict[str, Any]:
    headers, operator_uid = await local_operator_headers(args.api_base, expires_minutes=60)
    timeout = httpx.Timeout(connect=30, read=args.timeout_seconds, write=30, pool=30)
    started = time.monotonic()
    results = []
    async with httpx.AsyncClient(
        base_url=args.api_base.rstrip("/"),
        headers=headers,
        timeout=timeout,
    ) as client:
        system_response = await client.get("/system/config")
        system_response.raise_for_status()
        project_model = str(system_response.json().get("default_model") or "").strip()
        provider_id = project_model.partition(":")[0].casefold()
        if not project_model or provider_id.startswith("local"):
            raise ValueError("创新预览必须使用项目模型设置中的非本地通用模型")

        for query in args.query:
            modes = {}
            for mode in ("top_down", "bottom_up"):
                response = await client.post(
                    f"/graph/databases/{args.kb_id}/innovation/discover",
                    json={
                        "query": query,
                        "discovery_mode": mode,
                        "max_hops": args.max_hops,
                        "max_candidates": args.max_candidates,
                        "persist": False,
                        "retrieval_mode": "mix",
                        "evidence_scope": args.evidence_scope,
                        "query_enhancement_enabled": True,
                        "path_reranking_enabled": True,
                        "innovation_llm_enabled": True,
                    },
                )
                response.raise_for_status()
                modes[mode] = response.json().get("data") or {}
            results.append({"query": query, "modes": modes})

    report = {
        "contract": "defense-lightrag-innovation-preview-v1",
        "scope": "local_development_only",
        "operator_uid": operator_uid,
        "kb_id": args.kb_id,
        "project_model": project_model,
        "local_llm_used": False,
        "retrieval_mode": "mix",
        "persisted": False,
        "review_status": "pending",
        "expert_review_required": True,
        "results": results,
        "duration_seconds": round(time.monotonic() - started, 2),
        "quality_claim_allowed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:5050/api")
    parser.add_argument("--max-hops", type=int, default=5)
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--evidence-scope", choices=("any", "cross_document"), default="any")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    report = asyncio.run(run(build_parser().parse_args()))
    summary = {
        "kb_id": report["kb_id"],
        "project_model": report["project_model"],
        "queries": [
            {
                "query": item["query"],
                "top_down_hypotheses": len(item["modes"]["top_down"].get("hypotheses") or []),
                "bottom_up_hypotheses": len(item["modes"]["bottom_up"].get("hypotheses") or []),
            }
            for item in report["results"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
