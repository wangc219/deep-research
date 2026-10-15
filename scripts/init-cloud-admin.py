#!/usr/bin/env python3
"""在网站开放前通过回环 API 初始化管理员，登录信息仅写入私有文件。"""

import json
import os
from pathlib import Path
import secrets
from urllib.request import Request, urlopen


def main():
    root = Path(__file__).resolve().parent.parent
    base = "http://127.0.0.1:6050/api/auth"
    with urlopen(base + "/check-first-run", timeout=15) as response:
        if not json.load(response)["first_run"]:
            print("管理员已初始化；不修改现有账号。")
            return

    path = root / ".env.admin"
    if path.exists():
        credentials = json.loads(path.read_text())
    else:
        credentials = {
            "url": "https://www.deepquest.space",
            "uid": "dqadmin",
            "password": secrets.token_urlsafe(24),
        }
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(credentials, output, ensure_ascii=False, indent=2)
            output.write("\n")

    payload = {key: credentials[key] for key in ("uid", "password")}
    request = Request(
        base + "/initialize",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        identity = json.load(response)
    if identity["uid"] != credentials["uid"] or identity["role"] != "superadmin":
        raise RuntimeError("管理员初始化响应不符合预期")
    print(f"管理员初始化完成；登录信息保存于 {path}（0600）。")


if __name__ == "__main__":
    main()
