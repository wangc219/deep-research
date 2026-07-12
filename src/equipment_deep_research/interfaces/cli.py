from __future__ import annotations

import argparse
from pathlib import Path

from equipment_deep_research.orchestration.runner import DeepResearchRunner


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Run equipment capability image Deep Research.")
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument(
        "--provider",
        choices=["fake", "responses", "smoke"],
        default=None,
        help="Execution backend. real mode defaults to responses when credentials exist, otherwise smoke.",
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
    )
    print(f"Run dir: {result['run_dir']}")
    print(f"Status: {result.get('status', 'completed')}")
    print(f"Route: {result['route']}")
    print(f"Audit status: {result['audit_status']}")
    print(f"Report: {result['report_path']}")
    print(f"Capability images: {result['capability_images_path']}")
    print(f"Summary: {result['summary_path']}")
    return 0
