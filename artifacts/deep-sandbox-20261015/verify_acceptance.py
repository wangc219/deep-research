"""通过真实 HTTP 验证深研智能体的文件、交付状态及 ZIP。"""

import hashlib
import io
import json
import os
import zipfile
from datetime import timedelta
from pathlib import Path

import httpx
import psycopg

from platform_core.utils.auth_utils import AuthUtils

submission = json.loads(Path("/tmp/deep-sandbox-submission.json").read_text())
with psycopg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", "").replace("+psycopg", "")) as conn:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE uid=%s AND is_deleted=0", ("Hitsz504",))
        user_id = cursor.fetchone()[0]
headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user_id)}, expires_delta=timedelta(minutes=5))}
with httpx.Client(base_url="http://localhost:5050", headers=headers, timeout=60) as client:
    run_id = submission["request"]["run_id"]
    result = client.get(f"/api/agent/runs/{run_id}/result")
    result.raise_for_status()
    state = client.get(f"/api/chat/thread/{submission['thread_id']}/state")
    state.raise_for_status()
    root = "/outputs/深研沙盒验收-20261015/"
    files = {}
    for name in ("深研验收.md", "样例数据.csv", "交互图表.html"):
        params = {"thread_id": submission["thread_id"], "path": root + name}
        response = client.get("/api/viewer/filesystem/download", params=params)
        response.raise_for_status()
        assert response.content
        files[name] = {"bytes": len(response.content), "sha256": hashlib.sha256(response.content).hexdigest()}
    archive = client.get("/api/viewer/filesystem/download", params={"thread_id": submission["thread_id"], "path": root})
    archive.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        for name in files:
            assert hashlib.sha256(bundle.read(name)).hexdigest() == files[name]["sha256"]
    print(json.dumps({**submission, "run_status": result.json()["status"], "output": result.json().get("output"),
        "files": files, "zip_bytes": len(archive.content), "state": state.json()}, ensure_ascii=False))
