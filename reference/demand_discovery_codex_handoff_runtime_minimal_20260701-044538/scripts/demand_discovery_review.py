from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.demand_discovery.domain.models import HumanReviewRecord  # noqa: E402
from knowledgegraph.demand_discovery.domain.report import render_demand_report  # noqa: E402
from knowledgegraph.demand_discovery.domain.review import (  # noqa: E402
    PushPlan,
    generate_push_lists,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review demand discovery reports.")
    parser.add_argument(
        "--store",
        required=True,
        help="Append-only domain JSONL path.",
    )
    parser.add_argument(
        "--push-dir",
        default=str(PROJECT_ROOT / "outputs" / "push"),
        help="Directory for local push inbox/watchlist markdown.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("report_id")
    decide = sub.add_parser("decide")
    decide.add_argument("report_id")
    decide.add_argument(
        "--decision",
        required=True,
        choices=[
            "approved",
            "approved_with_changes",
            "needs_revision",
            "rejected",
            "watchlist",
        ],
    )
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--accepted-claims", action="append", default=[])
    decide.add_argument("--rejected-claims", action="append", default=[])
    decide.add_argument("--requested-changes", action="append", default=[])
    decide.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    store_path = Path(args.store)
    store = DomainStore.load_jsonl(store_path)
    store.bind_jsonl(store_path)

    if args.command == "list":
        for report in store.demand_reports.values():
            if report.review_status == "review_ready":
                sensitive = " sensitive" if report.sensitive_review_required else ""
                print(f"{report.report_id}\t{report.title}\t{report.review_status}{sensitive}")
        return 0

    if args.command == "show":
        report = store.demand_reports[args.report_id]
        print(render_demand_report(store, report))
        return 0

    record = HumanReviewRecord(
        review_id=f"review-{uuid4().hex}",
        report_id=args.report_id,
        reviewer=args.reviewer,
        review_time=datetime.now(timezone.utc),
        decision=args.decision,
        decision_reason=args.reason,
        accepted_claims=list(args.accepted_claims),
        rejected_claims=list(args.rejected_claims),
        requested_changes=list(args.requested_changes),
        notes=args.notes,
    )
    store.append_human_review(record)
    push_dir = Path(args.push_dir)
    generate_push_lists(
        store,
        PushPlan(push_dir / "inbox.md", push_dir / "watchlist.md"),
    )
    print(f"recorded {record.review_id} for {record.report_id}: {record.decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
