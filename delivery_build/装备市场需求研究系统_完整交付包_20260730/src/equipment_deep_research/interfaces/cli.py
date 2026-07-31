from __future__ import annotations

import argparse
from pathlib import Path

from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.harness.optimizations import (
    apply_quick_optimizations,
    print_performance_report,
)
from equipment_deep_research.providers.codex_optimizations import (
    apply_codex_optimizations,
    print_codex_performance_report,
)


def main(argv: list[str] | None = None) -> int:
    # 应用所有性能优化
    apply_quick_optimizations()
    apply_codex_optimizations()
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Run equipment capability image Deep Research.")
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument(
        "--provider",
        choices=["fake", "codex", "responses", "smoke"],
        default=None,
        help=(
            "Execution backend. Codex uses isolated codex exec sessions; "
            "Responses requires API credentials; smoke must be selected explicitly."
        ),
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument(
        "--research-route",
        choices=["auto", "new_winning_mechanism", "traditional_gap", "war_case_learning"],
        default="auto",
    )
    parser.add_argument("--agents", default="", help="Comma-separated agent ids. Empty means default preset.")
    parser.add_argument("--run-id", default="deep-research-run")
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--output-root", default=str(project_root / "outputs" / "runs"))
    parser.add_argument(
        "--agent-config",
        default=str(project_root / "configs" / "equipment_deep_research" / "agents.yaml"),
    )
    parser.add_argument(
        "--preset-config",
        default=str(project_root / "configs" / "equipment_deep_research" / "presets.yaml"),
    )
    parser.add_argument(
        "--provider-config",
        default=str(project_root / "configs" / "equipment_deep_research" / "providers.yaml"),
    )
    parser.add_argument(
        "--evidence-config",
        default=str(project_root / "configs" / "equipment_deep_research" / "evidence.yaml"),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--analyst-confirmed", action="store_true")
    parser.add_argument("--as-of-date", default="", help="Research evidence cutoff date (YYYY-MM-DD).")
    parser.add_argument("--interaction-mode", choices=["expert", "autonomous"], default="expert")
    parser.add_argument("--discovery-branch", choices=["auto", "A", "B", "C", "D", "E", "F", "G", "H"], default="auto")
    parser.add_argument(
        "--execution-profile-id",
        choices=["legacy_v1", "optimized_v2"],
        default="optimized_v2",
        help="Select the harness implementation. Optimized v2 is the default; legacy remains available for rollback.",
    )
    parser.add_argument(
        "--stage-policy-id",
        choices=["full_method", "no_multisource_baseline", "no_winning_mechanism"],
        default="full_method",
        help="Evaluation-only stage policy. Ordinary runs must keep full_method.",
    )
    args = parser.parse_args(argv)
    agent_ids = [item.strip() for item in args.agents.split(",") if item.strip()]
    runner = DeepResearchRunner(
        project_root=project_root,
        output_root=Path(args.output_root),
        agent_config_path=Path(args.agent_config),
        preset_config_path=Path(args.preset_config),
        provider_config_path=Path(args.provider_config),
        evidence_config_path=Path(args.evidence_config),
    )
    result = runner.run(
        mode=args.mode,
        topic=args.topic,
        research_route=args.research_route,
        run_id=args.run_id,
        agent_ids=agent_ids or None,
        max_rounds=args.max_rounds or None,
        provider_name=args.provider,
        resume=args.resume,
        analyst_confirmed=args.analyst_confirmed,
        as_of_date=args.as_of_date,
        interaction_mode=args.interaction_mode,
        discovery_branch=args.discovery_branch,
        execution_profile_id=args.execution_profile_id,
        stage_policy_id=args.stage_policy_id,
    )
    print(f"Run dir: {result['run_dir']}")
    print(f"Status: {result.get('status', 'completed')}")
    print(f"Route: {result['route']}")
    print(f"Audit status: {result['audit_status']}")
    print(f"Report: {result['report_path']}")
    print(f"Capability images: {result['capability_images_path']}")
    print(f"Summary: {result['summary_path']}")

    # 打印性能报告（如果启用了监控）
    print_performance_report()
    print_codex_performance_report()

    return 0
