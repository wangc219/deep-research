"""在独立文档服务内通过管理接口配置真实模型，不输出任何凭据。"""
import json
import os
from pathlib import Path
import shutil
import sys

import httpx

values = json.load(sys.stdin)
root = Path("/var/lib/document-research")
source = root / "config.json"
backup = root / "config.before-full-acceptance-20261025.json"
if not backup.exists():
    shutil.copyfile(source, backup)
    os.chmod(backup, 0o600)
config = json.loads(source.read_text())
owner = config.get("settings_admins", ["local"])[0]
token = config["tokens"][owner]
response = httpx.put("http://127.0.0.1:4198/document-research-api/settings/model",
                     headers={"Authorization": "Bearer " + token},
                     json={**values, "clear_api_key": False, "reasoning_effort": ""}, timeout=30)
assert response.status_code == 200, response.status_code
assert response.json()["model_configured"]
print(json.dumps({"model_configured": True, "credentials_redacted": True, "backup_saved": True}))
