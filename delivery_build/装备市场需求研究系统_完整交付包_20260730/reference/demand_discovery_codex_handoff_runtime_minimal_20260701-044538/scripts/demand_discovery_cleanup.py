from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.retention import (  # noqa: E402
    RetentionConfig,
    cleanup_outputs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean demand discovery run artifacts.")
    parser.add_argument(
        "--root",
        default=str(PROJECT_ROOT / "outputs"),
        help="Output root to clean.",
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "configs" / "demand_discovery" / "retention.yaml"),
    )
    parser.add_argument(
        "--domain-store",
        action="append",
        default=[],
        help=(
            "Domain JSONL path used to protect referenced artifacts. "
            "May be passed multiple times; defaults to auto-discovering "
            "domain.jsonl under the output root."
        ),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    config = _load_config(Path(args.config))
    domain_store = _load_domain_store_for_cleanup(
        Path(args.root),
        [Path(item) for item in args.domain_store],
    )
    result = cleanup_outputs(
        Path(args.root),
        config,
        apply=bool(args.apply),
        domain_store=domain_store,
    )
    action = "deleted" if args.apply else "would delete"
    for item in result.to_delete:
        print(f"{action}: {item.path} ({item.layer}, {item.size_bytes} bytes)")
    print(f"reclaimable_bytes: {result.reclaimable_bytes}")
    print(f"protected_refs: {len(result.protected_refs)}")
    return 0


def _load_config(path: Path) -> RetentionConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RetentionConfig(
        mid_term_keep_days=int(data.get("mid_term", {}).get("keep_days", 90)),
        short_term_keep_days=int(data.get("short_term", {}).get("keep_days", 14)),
        runtime_log_keep_days=int(data.get("runtime_log", {}).get("keep_days", 7)),
    )


def _load_domain_store_for_cleanup(
    root: Path,
    explicit_paths: list[Path],
) -> DomainStore | None:
    paths = explicit_paths or _discover_domain_jsonl(root)
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    combined = DomainStore()
    for path in existing:
        _merge_domain_store(combined, DomainStore.load_jsonl(path))
    return combined


def _discover_domain_jsonl(root: Path) -> list[Path]:
    patterns = [
        "runs/*/domain.jsonl",
        "scheduled/runs/*/domain.jsonl",
        "scheduled/*/domain.jsonl",
    ]
    discovered: set[Path] = set()
    for pattern in patterns:
        discovered.update(root.glob(pattern))
    return sorted(discovered)


def _merge_domain_store(target: DomainStore, source: DomainStore) -> None:
    target.sources.update(source.sources)
    target.evidence.update(source.evidence)
    target.candidates.update(source.candidates)
    target.audit_reports.update(source.audit_reports)
    target.demand_reports.update(source.demand_reports)
    target.human_reviews.update(source.human_reviews)
    target.trace_events.extend(source.trace_events)


if __name__ == "__main__":
    raise SystemExit(main())
