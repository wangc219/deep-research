"""预检 Pilot 选择清单，显式登记权威版本并生成标注 campaign spec。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from platform_core.knowledge.training.annotation_workflow import DEFAULT_GUIDELINE_VERSION
from platform_core.knowledge.training.pilot_campaign import (
    build_annotation_campaign_spec,
    load_pilot_selection_manifest,
)
from platform_core.repositories.knowledge_graph_annotation_preparation_repository import (
    KnowledgeGraphAnnotationPreparationRepository,
)
from platform_core.repositories.user_repository import UserRepository


async def run(args: argparse.Namespace) -> int:
    """执行默认只读预检；写数据库和生成任务清单均需显式参数。"""
    manifest = load_pilot_selection_manifest(args.manifest)
    repository = KnowledgeGraphAnnotationPreparationRepository()
    result = await repository.preflight(manifest, kb_id=args.kb_id)
    registered_count = 0
    if args.register_authoritative:
        if not args.kb_id:
            raise ValueError("--register-authoritative 必须同时提供 --kb-id")
        registered_count = await repository.register_authoritative_documents(
            kb_id=args.kb_id,
            result=result,
        )
        result = await repository.preflight(manifest, kb_id=args.kb_id)

    report = dict(result.report)
    report["registration"] = {
        "requested": bool(args.register_authoritative),
        "registered_document_count": registered_count,
    }
    if args.output_report:
        _write_json(args.output_report, report)

    if args.output_spec:
        if not args.kb_id:
            raise ValueError("--output-spec 必须同时提供 --kb-id")
        role_values = [args.annotator_a_uid, args.annotator_b_uid, args.arbitrator_uid]
        if not all(role_values):
            raise ValueError("生成 campaign spec 必须提供两名标注员 UID 和一名独立仲裁专家 UID")
        if not report["campaign_spec_ready"]:
            raise ValueError("权威文档映射预检未通过，不能生成 campaign spec")
        requested_uids = [args.annotator_a_uid, args.annotator_b_uid, args.arbitrator_uid]
        users = await UserRepository().list_active_by_uids(requested_uids)
        active_uids = {str(user.uid) for user in users}
        missing_uids = sorted(set(requested_uids) - active_uids)
        if missing_uids:
            raise ValueError(f"以下标注参与者不存在或已删除: {missing_uids}")
        spec = build_annotation_campaign_spec(
            manifest=manifest,
            bindings=result.bindings,
            name=args.name,
            ontology_version=args.ontology_version,
            guideline_version=args.guideline_version,
            annotator_ids=[args.annotator_a_uid, args.annotator_b_uid],
            arbitrator_id=args.arbitrator_uid,
        )
        _write_json(
            args.output_spec,
            {
                "contract_version": "defense-kg-annotation-campaign-spec-v1",
                "manifest_sha256": manifest.manifest_sha256,
                "kb_id": args.kb_id,
                "spec": spec.model_dump(mode="json"),
            },
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_ready and not report["campaign_spec_ready"]:
        return 2
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="300 篇 gold-selection-manifest.jsonl")
    parser.add_argument("--kb-id", help="目标本地知识库；省略时只检查能否唯一解析")
    parser.add_argument("--output-report", help="脱敏预检报告 JSON")
    parser.add_argument("--register-authoritative", action="store_true", help="显式登记已匹配文件的权威来源版本")
    parser.add_argument("--output-spec", help="预检通过后输出 campaign spec JSON")
    parser.add_argument("--name", default="Defense KG Pilot Gold 300")
    parser.add_argument("--ontology-version", default="defense-kg-1.0")
    parser.add_argument("--guideline-version", default=DEFAULT_GUIDELINE_VERSION)
    parser.add_argument("--annotator-a-uid")
    parser.add_argument("--annotator-b-uid")
    parser.add_argument("--arbitrator-uid")
    parser.add_argument("--require-ready", action="store_true", help="映射未全部就绪时返回非零状态")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


def _write_json(path: str, payload: dict) -> None:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
