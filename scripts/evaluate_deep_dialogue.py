#!/usr/bin/env python3
"""Score captured deep-dialogue JSONL results without invoking a model."""

from __future__ import annotations

import argparse
import json

from evals.deep_dialogue import evaluate_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate identity, divergence, closure, adversarial depth and S6 gating."
    )
    parser.add_argument("input", help="JSONL file containing captured deep-dialogue cases")
    parser.add_argument("--output", help="Optional report JSON path")
    args = parser.parse_args()
    report = evaluate_jsonl(args.input)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
