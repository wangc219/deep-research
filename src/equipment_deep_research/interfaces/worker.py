from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
from threading import Event, Thread
import time

from equipment_deep_research.application.factory import build_application_service
from equipment_deep_research.harness.event_bus import sanitize_runtime_payload
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.queue.worker import ResearchWorker


def runtime_status_for_event(event_type: str) -> str:
    """Map durable orchestration milestones to the user-facing run phase."""

    if event_type in {
        "baseline_agents_summarized",
        "discovery_convergence_completed",
        "winning_model_call_started",
        "winning_swarm_started",
    }:
        return "synthesizing"
    if event_type == "audit_completed":
        return "reviewing"
    if event_type == "report_model_call_started":
        return "reporting"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one queued Deep Research task.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--output-root", default="outputs/runs")
    parser.add_argument("--mode", choices=("fake", "real"), default=os.environ.get("EQUIPMENT_DR_MODE", "fake"))
    parser.add_argument("--provider", default=os.environ.get("EQUIPMENT_DR_PROVIDER"))
    parser.add_argument(
        "--worker-id",
        default=os.environ.get(
            "EQUIPMENT_DR_WORKER_ID",
            f"research-worker-{socket.gethostname()}",
        ),
    )
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument(
        "--max-idle-poll-interval",
        type=float,
        default=float(os.environ.get("EQUIPMENT_DR_MAX_IDLE_POLL_INTERVAL", "5")),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--disable-orphan-recovery",
        action="store_true",
        help="Leave stale-run recovery to another Worker in the same pool.",
    )
    args = parser.parse_args(argv)
    root = Path(args.project_root)
    output_root = Path(args.output_root)
    service = build_application_service(args.database_url)

    def execute(run_id: str) -> dict:
        view = service.get_run(run_id)
        execution = dict(view.execution)
        run_dir = output_root / view.run_id

        def publish_event(event_type: str, payload: dict) -> None:
            service.publish_runtime_event(
                run_id,
                event_type,
                sanitize_runtime_payload(payload),
            )
            next_status = runtime_status_for_event(event_type)
            if next_status:
                current = service.get_run(run_id)
                if current.status != next_status:
                    service.set_status(run_id, next_status)

        return DeepResearchRunner(
            project_root=root,
            output_root=output_root,
            agent_config_path=root / "configs/equipment_deep_research/agents.yaml",
            preset_config_path=root / "configs/equipment_deep_research/presets.yaml",
            provider_config_path=root / "configs/equipment_deep_research/providers.yaml",
            evidence_config_path=root / "configs/equipment_deep_research/evidence.yaml",
            event_sink=publish_event,
        ).run(
            mode=str(execution.get("mode") or args.mode),
            topic=view.topic,
            supplemental_information=getattr(
                view, "supplemental_information", ""
            ),
            research_route=view.research_route,
            run_id=view.run_id,
            agent_ids=view.selected_agent_ids or None,
            max_rounds=view.max_rounds,
            provider_name=str(execution.get("provider") or args.provider or "") or None,
            provider_model=str(execution.get("model") or "") or None,
            provider_base_url=str(execution.get("base_url") or "") or None,
            provider_api_key_env=str(execution.get("api_key_env") or "") or None,
            agent_model_profiles=(
                dict(execution.get("agent_models", {}))
                if isinstance(execution.get("agent_models", {}), dict)
                else None
            ),
            resume=run_dir.exists(),
            analyst_confirmed=view.analyst_confirmed,
            interaction_mode=getattr(view, "interaction_mode", "expert"),
            discovery_branch=getattr(view, "discovery_branch", "auto"),
            execution_profile_id=getattr(view, "execution_profile_id", "") or "legacy_v1",
            report_template_mode=getattr(
                view, "report_template_mode", "three_layer_nine_item"
            ),
            allow_resume_config_mismatch=run_dir.exists(),
        )

    worker = ResearchWorker(service=service, execute=execute, worker_id=args.worker_id)
    # Replace a stale heartbeat from a previous process before deciding whether
    # an active run has become orphaned, then resume it from its checkpoint.
    touch_worker = getattr(service, "touch_worker", None)
    if callable(touch_worker):
        touch_worker(args.worker_id, status="idle")
    recover_orphaned_runs = getattr(service, "recover_orphaned_runs", None)
    recovery_enabled = callable(recover_orphaned_runs) and not args.disable_orphan_recovery
    if recovery_enabled:
        recover_orphaned_runs()
    if args.once:
        outcome = worker.run_once()
        return 0 if outcome is None or outcome.status == "completed" else 1
    recovery_stop = Event()
    if recovery_enabled:
        recovery_interval = max(
            5.0,
            float(os.environ.get("EQUIPMENT_DR_ORPHAN_RECOVERY_INTERVAL", "10")),
        )

        def recover_in_background() -> None:
            while not recovery_stop.wait(recovery_interval):
                try:
                    recover_orphaned_runs()
                except Exception:
                    # A transient SQLite lock or concurrent state transition
                    # must not stop future reconciliation attempts.
                    continue

        Thread(
            target=recover_in_background,
            name=f"{args.worker_id}-orphan-recovery",
            daemon=True,
        ).start()
    base_delay = max(args.poll_interval, 0.1)
    maximum_delay = max(args.max_idle_poll_interval, base_delay)
    idle_delay = base_delay
    while True:
        outcome = worker.run_once()
        if outcome is None:
            time.sleep(idle_delay)
            idle_delay = min(maximum_delay, idle_delay * 1.5)
        else:
            idle_delay = base_delay


if __name__ == "__main__":
    raise SystemExit(main())
