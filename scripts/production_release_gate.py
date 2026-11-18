#!/usr/bin/env python3
"""执行生产候选镜像与公网发布结果的强制门禁。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

from verify_web_image import verify_image


RELEASE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
HTML_ASSET_PATTERN = re.compile(r'''(?:src|href)=["']([^"']+)["']''')
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 "
    "Chrome/130 Mobile Safari/537.36"
)
API_RUNTIME_SMOKE = (
    "/opt/wechat-mp/bin/python",
    "-c",
    "from app_mp import app; assert app is not None",
)


@dataclass(frozen=True)
class HttpCheck:
    url: str
    status: int
    elapsed_ms: int
    sha256: str


def _docker_inspect(kind: str, target: str) -> dict:
    command = ["docker", kind, "inspect", target]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if len(payload) != 1:
        raise RuntimeError(f"无法唯一识别 Docker 对象：{target}")
    return payload[0]


def _validated_release_value(name: str, value: str) -> str:
    if value in {"development", "unknown"} or not RELEASE_VALUE_PATTERN.fullmatch(value):
        raise RuntimeError(f"{name} 不是可交付的生产值：{value}")
    return value


def _verify_api_runtime(image: str) -> list[str]:
    """在候选镜像内导入可选业务模块，阻止关联文件缺失的半包发布。"""
    command = [
        "docker",
        "run",
        "--rm",
        "--workdir",
        "/app/wechat_mp",
        "--env",
        "WECHAT_MP_DATA_DIR=/tmp/wechat-mp-release-smoke",
        "--env",
        "WECHAT_MP_ACCOUNT_POOL_FILE=/tmp/wechat-mp-release-smoke/account_pool.json",
        "--entrypoint",
        API_RUNTIME_SMOKE[0],
        image,
        *API_RUNTIME_SMOKE[1:],
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise RuntimeError(f"API 候选镜像公众号运行时导入失败：{detail}")
    return ["wechat_mp_import"]


def _verify_api_image_contract(image: str) -> dict:
    script = """
import json
from platform_core.repositories.conversation_repository import (
    INTERNAL_CONVERSATION_CHANNELS,
    INTERNAL_CONVERSATION_TITLE_PREFIXES,
    INVOCATION_CONVERSATION_SOURCES,
)

contract = {
    "sources": list(INVOCATION_CONVERSATION_SOURCES),
    "channels": list(INTERNAL_CONVERSATION_CHANNELS),
    "title_prefixes": list(INTERNAL_CONVERSATION_TITLE_PREFIXES),
}
assert "innovation_brief" in contract["sources"]
assert "internal" in contract["channels"]
assert "简报调研探索 ·" in contract["title_prefixes"]
print(json.dumps(contract, ensure_ascii=False))
"""
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python", image, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip())


def _write_evidence(path: Path | None, payload: dict) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
    print(f"发布门禁通过，证据已写入：{path}")


def verify_candidate(args: argparse.Namespace) -> None:
    release_id = _validated_release_value("release_id", args.release_id)
    source_revision = _validated_release_value("source_revision", args.source_revision)
    candidate = _docker_inspect("image", args.candidate_image)
    current = _docker_inspect("container", args.current_container)
    labels = candidate.get("Config", {}).get("Labels") or {}
    expected_labels = {
        "com.deepquest.release.id": release_id,
        "com.deepquest.release.component": args.component,
        "org.opencontainers.image.revision": source_revision,
    }
    mismatched = {
        key: {"expected": value, "actual": labels.get(key)}
        for key, value in expected_labels.items()
        if labels.get(key) != value
    }
    if mismatched:
        raise RuntimeError(f"候选镜像版本标签不匹配：{json.dumps(mismatched, ensure_ascii=False)}")

    current_image_id = current.get("Image", "")
    current_image_name = current.get("Config", {}).get("Image", "")
    candidate_image_id = candidate.get("Id", "")
    if candidate_image_id == current_image_id:
        raise RuntimeError("候选镜像与当前运行镜像 ID 相同，本次发布没有实质变更")
    if args.candidate_image == current_image_name:
        raise RuntimeError("候选镜像复用了当前运行标签，禁止不可追溯的原地覆盖")

    checked_assets = verify_image(args.candidate_image) if args.component == "web" else None
    api_contract = _verify_api_image_contract(args.candidate_image) if args.component == "api" else None
    runtime_checks = _verify_api_runtime(args.candidate_image) if args.component == "api" else None
    _write_evidence(
        args.output,
        {
            "gate": "candidate",
            "status": "passed",
            "release_id": release_id,
            "source_revision": source_revision,
            "component": args.component,
            "candidate_image": args.candidate_image,
            "candidate_image_id": candidate_image_id,
            "current_image": current_image_name,
            "current_image_id": current_image_id,
            "checked_asset_references": checked_assets,
            "api_conversation_visibility_contract": api_contract,
            "runtime_checks": runtime_checks,
        },
    )


def _fetch(url: str, *, user_agent: str | None = None) -> tuple[bytes, HttpCheck]:
    headers = {"User-Agent": user_agent} if user_agent else {}
    request = urllib.request.Request(url, headers=headers)
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read()
        status = response.status
    elapsed_ms = round((time.monotonic() - started) * 1000)
    if status != 200:
        raise RuntimeError(f"公网检查失败：{url} 返回 HTTP {status}")
    return body, HttpCheck(
        url=url,
        status=status,
        elapsed_ms=elapsed_ms,
        sha256=hashlib.sha256(body).hexdigest(),
    )


def _fetch_html_assets(base_url: str, body: bytes) -> list[HttpCheck]:
    html = body.decode("utf-8")
    checks: list[HttpCheck] = []
    for reference in sorted(set(HTML_ASSET_PATTERN.findall(html))):
        if not reference.startswith("/assets/"):
            continue
        _, check = _fetch(urljoin(base_url, reference))
        checks.append(check)
    if not checks:
        raise RuntimeError("公网 HTML 没有可验证的内容哈希静态资源")
    return checks


def verify_public(args: argparse.Namespace) -> None:
    release_id = _validated_release_value("release_id", args.release_id)
    public_url = args.public_url.rstrip("/") + "/"
    checks: list[HttpCheck] = []

    release_body, release_check = _fetch(urljoin(public_url, "release.json"))
    checks.append(release_check)
    release = json.loads(release_body)
    if release.get("release_id") != release_id:
        raise RuntimeError(
            f"公网版本不是本次候选：期望 {release_id}，实际 {release.get('release_id')}"
        )

    ready_body, ready_check = _fetch(args.readiness_url)
    checks.append(ready_check)
    readiness = json.loads(ready_body)
    if readiness.get("status") != "ready":
        raise RuntimeError(f"readiness 未通过：{readiness.get('status')}")

    index_body, index_check = _fetch(public_url)
    checks.append(index_check)
    checks.extend(_fetch_html_assets(public_url, index_body))

    mobile_body, mobile_check = _fetch(urljoin(public_url, "login"), user_agent=MOBILE_USER_AGENT)
    checks.append(mobile_check)
    if b"/assets/" not in mobile_body:
        raise RuntimeError("手机端入口没有返回有效 Web 应用资源")

    _write_evidence(
        args.output,
        {
            "gate": "public",
            "status": "passed",
            "release_id": release_id,
            "public_url": public_url,
            "readiness_url": args.readiness_url,
            "checks": [asdict(check) for check in checks],
        },
    )


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    candidate = commands.add_parser("candidate")
    candidate.add_argument("--candidate-image", required=True)
    candidate.add_argument("--current-container", required=True)
    candidate.add_argument("--component", choices=("api", "web"), required=True)
    candidate.add_argument("--release-id", required=True)
    candidate.add_argument("--source-revision", required=True)
    candidate.add_argument("--output", type=Path)
    candidate.set_defaults(handler=verify_candidate)

    public = commands.add_parser("public")
    public.add_argument("--public-url", required=True)
    public.add_argument("--readiness-url", required=True)
    public.add_argument("--release-id", required=True)
    public.add_argument("--output", type=Path)
    public.set_defaults(handler=verify_public)
    return parser


def main() -> None:
    """执行指定的生产发布门禁。"""
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
