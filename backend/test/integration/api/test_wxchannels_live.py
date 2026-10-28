"""个人视频采集协议的真实 HTTP、ARQ、SenseVoice 和 MinIO 验收。"""

import asyncio
import io
import os
import secrets
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_VIDEO_LIVE") != "1", reason="显式启用 CPU 语音识别验收"),
]
BASE = "/api/knowledge/wxchannels"
DEVICE_BASE = BASE + "/collector"


async def test_personal_audio_to_docx_download_and_import(
    test_client, admin_headers, standard_user, knowledge_database
):
    """只模拟微信端音频交接，其余组件全部走运行中的真实平台。"""
    device_id = "wxd_" + uuid4().hex
    token = secrets.token_hex(32)
    device_headers = {"Authorization": "Bearer " + token, "X-Collector-Device": device_id}
    task_ids = []
    latest = None
    stop = asyncio.Event()
    state = {"channels_ready": True, "mcp_available": True, "wechat_available": True, "ffmpeg_available": True}
    response = await test_client.post(
        DEVICE_BASE + "/devices",
        headers=admin_headers,
        json={"device_id": device_id, "token": token, "name": "pytest video PC", "platform": "macos"},
    )
    assert response.status_code == 200

    async def heartbeat():
        """在识别期间维持设备在线，读取当前 Worker 的真实执行 ID。"""
        nonlocal latest
        while not stop.is_set():
            response = await test_client.post(BASE + "/collector/heartbeat", headers=device_headers, json=state)
            assert response.status_code == 200
            latest = response.json().get("job")
            try:
                await asyncio.wait_for(stop.wait(), 2)
            except TimeoutError:
                pass

    async def wait_job(task_id):
        """等待 ARQ 领取并获得有效租约。"""
        for _ in range(90):
            if latest and latest["task_id"] == task_id:
                return latest
            await asyncio.sleep(1)
        pytest.fail("Worker 未领取测试任务")

    async def wait_task(task_id):
        """从独立 HTTP 请求验证刷新后的持久化终态。"""
        for _ in range(180):
            response = await test_client.get(BASE + "/tasks/" + task_id, headers=admin_headers)
            assert response.status_code == 200
            task = response.json()
            if task["status"] in {"success", "failed", "cancelled"}:
                return task
            await asyncio.sleep(1)
        pytest.fail("转换任务未在预期时间内结束")

    response = await test_client.post(BASE + "/collector/heartbeat", headers=device_headers, json=state)
    assert response.status_code == 200
    pulse = asyncio.create_task(heartbeat())
    try:
        account = "pytest公开音频账号"
        source = {"account": account, "max_pages": 1, "collection_mode": "personal", "device_id": device_id}
        response = await test_client.post(BASE + "/videos", headers=admin_headers, json=source)
        assert response.status_code == 200
        discovery_id = response.json()["task_id"]
        task_ids.append(discovery_id)
        job = await wait_job(discovery_id)
        oid = "pytest-video-" + uuid4().hex
        response = await test_client.post(
            BASE + "/collector/event",
            headers=device_headers,
            json={
                "task_id": discovery_id,
                "execution_id": job["execution_id"],
                "sequence": 1,
                "kind": "video_list",
                "username": "fixture@finder",
                "videos": [{"oid": oid, "title": "视频转文字环境测试"}],
            },
        )
        assert response.status_code == 200
        discovery = await wait_task(discovery_id)
        assert discovery["status"] == "success" and discovery["result"]["videos"][0]["oid"] == oid
        response = await test_client.post(
            BASE + "/transcribe",
            headers=admin_headers,
            json={
                **source,
                "max_videos": 1,
                "video_oids": [oid],
                "timeout_seconds": 300,
            },
        )
        assert response.status_code == 202 and response.json()["submitted"]
        task_id = response.json()["task_id"]
        task_ids.append(task_id)
        job = await wait_job(task_id)
        audio = Path("test/fixtures/video_transcriber/speech.wav").read_bytes()
        response = await test_client.post(
            BASE + "/collector/audio",
            headers=device_headers,
            data={
                "task_id": task_id,
                "execution_id": job["execution_id"],
                "sequence": "1",
                "oid": oid,
                "title": "视频转文字环境测试",
            },
            files={"file": ("speech.wav", audio, "audio/wav")},
        )
        assert response.status_code == 200
        response = await test_client.post(
            BASE + "/collector/event",
            headers=device_headers,
            json={
                "task_id": task_id,
                "execution_id": job["execution_id"],
                "sequence": 2,
                "kind": "complete",
            },
        )
        assert response.status_code == 200
        task = await wait_task(task_id)
        assert task["status"] == "success", task
        assert task["result"]["completed_count"] == 1
        assert "语音识别" in task["result"]["items"][0]["text"]
        assert "object_key" not in task["result"]["items"][0]
        download_path = BASE + f"/tasks/{task_id}/items/0/docx"
        denied = await test_client.get(download_path, headers=standard_user["headers"])
        assert denied.status_code == 404
        denied = await test_client.post(BASE + f"/tasks/{task_id}/cancel", headers=standard_user["headers"])
        assert denied.status_code == 404
        response = await test_client.get(download_path, headers=admin_headers)
        assert response.status_code == 200
        word = Document(io.BytesIO(response.content))
        assert any("语音识别" in paragraph.text for paragraph in word.paragraphs)
        output = Path("/app/outputs/wxchannels-acceptance")
        output.mkdir(parents=True, exist_ok=True)
        (output / "migration-qa.docx").write_bytes(response.content)
        response = await test_client.get(BASE + f"/tasks/{task_id}/archive", headers=admin_headers)
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 1
            assert archive.namelist()[0].endswith(".docx")
        response = await test_client.post(
            BASE + f"/databases/{knowledge_database['kb_id']}/import",
            headers=admin_headers,
            json={"task_id": task_id, "indexes": [0]},
        )
        assert response.status_code == 200
        index_id = response.json()["task_id"]
        file_ids = response.json()["file_ids"]
        response = await test_client.post(
            BASE + f"/databases/{knowledge_database['kb_id']}/import",
            headers=admin_headers,
            json={"task_id": task_id, "indexes": [0]},
        )
        assert response.status_code == 200 and response.json()["file_ids"] == file_ids
        for _ in range(90):
            indexed = (await test_client.get("/api/tasks/" + index_id, headers=admin_headers)).json()["task"]
            if indexed["status"] in {"success", "failed"}:
                break
            await asyncio.sleep(1)
        assert indexed["status"] == "success", indexed.get("error")
    finally:
        stop.set()
        await pulse
        for task_id in task_ids:
            await test_client.post(BASE + f"/tasks/{task_id}/cancel", headers=admin_headers)
        await test_client.delete(DEVICE_BASE + "/devices/" + device_id, headers=admin_headers)


async def test_oneclick_packages_include_pairing_and_platform_programs(test_client, admin_headers):
    """真实接口返回可双击的 Mac/Windows 连接包，设备令牌不会成为平台登录凭据。"""
    for platform, launcher in [("macos", "连接我的微信.command"), ("windows", "连接我的微信.cmd")]:
        config = {
            "device_id": "wxd_" + uuid4().hex,
            "token": secrets.token_hex(32),
            "name": "pytest oneclick",
            "platform": platform,
            "platform_url": "http://localhost:5050",
        }
        try:
            response = await test_client.post(BASE + "/collector/package", headers=admin_headers, json=config)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store, private"
            with zipfile.ZipFile(io.BytesIO(response.content)) as package:
                import json

                assert json.loads(package.read("video-collector.json")) == config
                assert launcher in package.namelist()
                assert len([name for name in package.namelist() if name.startswith("bin/")]) == 2
                assert package.getinfo(launcher).external_attr >> 16 & 0o100
            response = await test_client.get(
                "/api/knowledge/databases", headers={"Authorization": "Bearer " + config["token"]}
            )
            assert response.status_code == 401
        finally:
            await test_client.delete(DEVICE_BASE + "/devices/" + config["device_id"], headers=admin_headers)
