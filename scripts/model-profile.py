#!/usr/bin/env python3
"""Inspect and switch the unified model profile registry."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from equipment_deep_research.model_profiles import (  # noqa: E402
    activate_profile,
    activate_swarm_overrides,
    active_profile_id,
    doctor_profile,
    get_profile,
    profile_environment,
    public_profiles,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="统一模型档案管理")
    parser.add_argument("command", choices=["list", "show", "use", "doctor", "env", "use-swarm"])
    parser.add_argument("profile", nargs="?")
    parser.add_argument("--env-file", default="", help="use 写入的 env file（默认 .env.local）")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.command == "list":
        payload = public_profiles()
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"当前档案: {payload['active_profile'] or '(未选择)'}")
            for item in payload["profiles"]:
                marker = " *" if item["id"] == payload["active_profile"] else ""
                fallback = ",".join(item["fallback_profiles"]) or "无"
                credential = "已配置" if item["credential_configured"] else "未配置"
                print(f"{item['id']}{marker}\t{item['provider']}\t{item['model']}\t{item['protocol']}\t凭据:{credential}\tfallback:{fallback}")
        return 0
    if not args.profile:
        parser.error(f"{args.command} 需要 profile 参数")
    if args.command == "show":
        selected, profile = get_profile(args.profile)
        payload = {"id": selected, **profile}
        payload.pop("api_key", None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "env":
        for name, value in profile_environment(args.profile).items():
            if value:
                print(f"{name}={value}")
        return 0
    if args.command == "use":
        result = activate_profile(args.profile, env_file=args.env_file or None)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "use-swarm":
        try:
            overrides = json.loads(args.profile)
        except json.JSONDecodeError as exc:
            parser.error(f"use-swarm 需要 JSON 对象: {exc}")
        if not isinstance(overrides, dict):
            parser.error("use-swarm 需要 JSON 对象")
        result = activate_swarm_overrides(overrides, env_file=args.env_file or None)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    result = doctor_profile(args.profile)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
