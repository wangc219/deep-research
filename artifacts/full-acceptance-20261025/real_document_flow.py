"""使用合成测试资料通过实际服务、模型和交付下载完成独立文档研究验收。"""
import io
import json
from pathlib import Path
import time
from uuid import uuid4
import zipfile

import httpx

config = json.loads(Path("/var/lib/document-research/config.json").read_text())
owner = config.get("settings_admins", ["local"])[0]
headers = {"Authorization": "Bearer " + config["tokens"][owner]}
base = "http://127.0.0.1:4198/document-research-api"
with httpx.Client(base_url=base, headers=headers, timeout=120) as client:
    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    library = request("POST", "/libraries", json={"name": "真实验收_" + uuid4().hex[:8]}).json()
    try:
        text = "测试资料关注跨页表头。跨页表格解析应保留原始行列关系。此资料仅用于软件引用验收，未测量任何解析器性能。"
        document = request("POST", f"/libraries/{library['id']}/documents", files={"file": ("acceptance.txt", text.encode(), "text/plain")}).json()
        preview = request("POST", "/retrieve", json={"problem": "跨页表格解析应保留什么关系？", "library_ids": [library["id"]]}).json()
        assert preview.get("sources"), preview
        task = request("POST", "/tasks", json={"mode": "answer", "problem": "根据测试资料，跨页表格解析应保留什么关系？",
                         "library_ids": [library["id"]], "allow_external_model": True}).json()
        request("POST", f"/tasks/{task['id']}/run")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = request("GET", f"/tasks/{task['id']}").json()
            if result["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(1)
        assert result["status"] == "completed", result
        report = result["report"]
        assert report["answer"], report
        for claim in report["answer"]:
            assert claim["quote"] in text, claim
        archive = request("GET", f"/tasks/{task['id']}/delivery.zip")
        with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
            assert package.namelist()
        print(json.dumps({"library_id": library["id"], "task_id": task["id"], "retrieval": "passed", "real_model": "passed",
                          "verbatim_citations": "passed", "download_zip": "passed", "answer_count": len(report["answer"])}, ensure_ascii=False))
    finally:
        request("DELETE", f"/libraries/{library['id']}")
