"""Command-line interface for the developer handoff package."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .commands import MODULES, build_module_command, resolve_data_root
from .doctor import collect_checks


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Developer launcher for the data crawling handoff package."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="check local runtime readiness")
    doctor_parser.add_argument("--data-root")
    doctor_parser.add_argument("--runtime-root")

    run_parser = subparsers.add_parser("run", help="run one collector module")
    run_parser.add_argument("module", choices=sorted(MODULES))
    run_parser.add_argument("--data-root")
    run_parser.add_argument("passthrough", nargs=argparse.REMAINDER)

    package_parser = subparsers.add_parser("package", help="build the developer handoff ZIP")
    package_parser.add_argument("--output-root", default="outputs/packages")
    package_parser.add_argument("--version", default="v1.0.0")
    package_parser.add_argument("--live-report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = default_project_root()

    if args.command == "doctor":
        data_root = resolve_data_root(args.data_root)
        runtime_root = Path(args.runtime_root or project_root / "runtime").resolve()
        checks = collect_checks(
            project_root=project_root,
            data_root=data_root,
            runtime_root=runtime_root,
        )
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if all(bool(item.get("ok")) for item in checks) else 1

    if args.command == "run":
        data_root = resolve_data_root(args.data_root)
        passthrough = list(args.passthrough)
        if passthrough[:1] == ["--"]:
            passthrough = passthrough[1:]
        command = build_module_command(
            args.module,
            project_root,
            data_root,
            passthrough,
        )
        environment = dict(os.environ)
        environment["CRAWLER_DATA_ROOT"] = str(data_root)
        completed = subprocess.run(
            command,
            cwd=project_root,
            env=environment,
            check=False,
        )
        return int(completed.returncode)

    from .package_builder import build_package

    result = build_package(
        project_root=project_root,
        output_root=Path(args.output_root),
        version=args.version,
        live_report=Path(args.live_report) if args.live_report else None,
    )
    print(f"Package directory: {result.package_root}")
    print(f"ZIP path: {result.zip_path}")
    print(f"Files: {result.file_count}")
    print(f"Checksums: {result.checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

