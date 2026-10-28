"""对历史 lint 建立可审阅基线，CI 拒绝新增问题并要求及时缩减已解决条目。"""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "configs/quality/backend-lint-baseline.json"


def fingerprints(issues, root=ROOT):
    """用路径、规则、诊断和源码行识别问题，代码整体移行不会误报。"""
    counts = Counter()
    for issue in issues:
        path = Path(issue["filename"]).resolve()
        source = path.read_text().splitlines()[issue["location"]["row"] - 1].strip()
        key = (
            str(path.relative_to(root)),
            issue["code"],
            issue["message"],
            hashlib.sha256(source.encode()).hexdigest(),
        )
        counts[key] += 1
    return counts


def compare_findings(current, baseline):
    """同时识别新增与已解决问题，不能以减少其他告警抵消新增错误。"""
    return current - baseline, baseline - current


def main():
    """默认只读验收，基线变更必须显式执行并进入代码审阅。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-baseline", action="store_true")
    args = parser.parse_args()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "backend/package",
            "backend/server",
            "--output-format=json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        sys.stderr.write(result.stderr)
        return result.returncode
    current = fingerprints(json.loads(result.stdout))
    if args.refresh_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            dict(zip(("path", "code", "message", "source_sha256"), key), count=count)
            for key, count in sorted(current.items())
        ]
        BASELINE.write_text(
            json.dumps({"version": 1, "findings": rows}, ensure_ascii=False, indent=2)
            + "\n"
        )
        print(f"已更新历史基线：{sum(current.values())} 项；必须审阅基线差异。")
        return 0
    saved = json.loads(BASELINE.read_text())
    baseline = Counter(
        {
            (r["path"], r["code"], r["message"], r["source_sha256"]): r["count"]
            for r in saved["findings"]
        }
    )
    new, resolved = compare_findings(current, baseline)
    if new:
        print("新增 lint 问题（不能以历史基线豁免）：", file=sys.stderr)
        for (path, code, message, _), count in sorted(new.items()):
            print(f"{path}: {code} {message} ({count})", file=sys.stderr)
    if resolved:
        print(
            f"已解决 {sum(resolved.values())} 项历史问题；请显式缩减基线。",
            file=sys.stderr,
        )
    print(
        json.dumps(
            {
                "legacy_findings": sum(current.values()),
                "new_findings": sum(new.values()),
                "resolved_findings": sum(resolved.values()),
            }
        )
    )
    return int(bool(new or resolved))


if __name__ == "__main__":
    raise SystemExit(main())
