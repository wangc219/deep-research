"""真实沙盒、文件 HTTP 接口、预览与打包下载的验收。"""

import io
import os
import zipfile
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from platform_core.agents.backends.sandbox import ProvisionerSandboxBackend
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize("conversation_kind", ["chat", "deep"])
async def test_sandbox_to_workspace_preview_edit_and_zip(test_client, conversation_kind):
    """以已有本机测试身份验证真实读写与 HTTP 授权，不依赖模型猜测路径。"""
    uid = os.getenv("WORKSPACE_E2E_UID")
    if not uid:
        pytest.skip("Set WORKSPACE_E2E_UID to an authorized local test identity")
    with psycopg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", "").replace("+psycopg", "")) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE uid=%s AND is_deleted=0", (uid,))
            user_id = cursor.fetchone()[0]
    headers = {
        "Authorization": "Bearer "
        + AuthUtils.create_access_token({"sub": str(user_id)}, expires_delta=timedelta(minutes=5))
    }
    agent = (await test_client.get("/api/agent/default", headers=headers)).json()["agent"]
    response = await test_client.post(
        "/api/chat/thread",
        headers=headers,
        json={"agent_id": agent.get("slug") or agent["agent_id"], "title": "pytest sandbox workspace delivery"},
    )
    assert response.status_code == 200, response.text
    thread_id = response.json().get("thread_id") or response.json()["id"]
    if conversation_kind == "deep":
        project_id = response.json()["project_id"]
        response = await test_client.post(
            "/api/equipment/deep-thinking",
            headers=headers,
            json={
                "project_id": project_id,
                "title": "pytest deep sandbox workspace delivery",
                "topic": "文件交付验收",
                "knowledge_enabled": False,
                "subagents_enabled": False,
            },
        )
        assert response.status_code == 200, response.text
        deep_session_id = response.json()["session_id"]
        thread_id = response.json()["payload"]["thread_id"]
    from platform_core.services.workdir_service import resolve_authorized_workdir
    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.agents.skills.service import refresh_user_skill_projection_async

    await refresh_user_skill_projection_async(uid)
    async with pg_manager.get_async_session_context() as db:
        access = await resolve_authorized_workdir(thread_id=thread_id, uid=uid, db=db)
    backend = ProvisionerSandboxBackend(
        thread_id=thread_id, uid=uid, workdir_path=access.workdir_path, create_if_missing=True
    )
    runtime_root = f"/home/gem/user-data/{access.workdir_path}"
    name = f"验收-{uuid4().hex[:8]}"
    path = f"/outputs/{name}/report.md"
    content = "# 沙盒工作区验收\n\n读写、预览、编辑与下载。\n"
    result = backend.write(runtime_root + path, content)
    assert result.error is None, result.error
    assert backend.read(runtime_root + path).file_data["content"].startswith("# 沙盒工作区验收")
    assert backend.write("/etc/workspace-probe.txt", "denied").error
    assert backend.write("/home/gem/skills/workspace-probe.txt", "denied").error
    relative_write = backend.execute(
        "python -c \"from pathlib import Path; Path('outputs/relative-write.txt').write_text('persisted')\""
    )
    assert relative_write.exit_code == 0, relative_write.output
    relative_download = await test_client.get(
        "/api/viewer/filesystem/download",
        params={"thread_id": thread_id, "path": "/outputs/relative-write.txt"},
        headers=headers,
    )
    assert relative_download.status_code == 200, relative_download.text
    assert relative_download.content == b"persisted"
    params = {"thread_id": thread_id, "path": path}
    preview = await test_client.get("/api/viewer/filesystem/file", params=params, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["content"] == content
    workspace_path = f"/{access.workdir_path}{path}"
    edited = content + "\n在线编辑保存成功。\n"
    save = await test_client.put(
        "/api/workspace/file", headers=headers, json={"path": workspace_path, "content": edited}
    )
    assert save.status_code == 200, save.text
    assert "在线编辑保存成功" in backend.read(runtime_root + path).file_data["content"]
    archive = await test_client.get(
        "/api/viewer/filesystem/download",
        params={"thread_id": thread_id, "path": f"/outputs/{name}/"},
        headers=headers,
    )
    assert archive.status_code == 200, archive.text
    assert archive.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert bundle.read("report.md").decode() == edited
    if conversation_kind == "deep":
        branch = await test_client.post(
            f"/api/equipment/deep-thinking/{deep_session_id}/branches",
            headers=headers,
            json={"title": "pytest deep workspace branch"},
        )
        assert branch.status_code == 200, branch.text
        branch_payload = branch.json()
        branch_session = branch_payload.get("session", branch_payload)
        branch_download = await test_client.get(
            "/api/viewer/filesystem/download",
            params={"thread_id": branch_session["payload"]["thread_id"], "path": path},
            headers=headers,
        )
        assert branch_download.status_code == 200, branch_download.text
        assert branch_download.content.decode() == edited
    denied = await test_client.get("/api/viewer/filesystem/file", params=params)
    assert denied.status_code == 401
    traversal = await test_client.get(
        "/api/viewer/filesystem/download",
        params={"thread_id": thread_id, "path": "/../other-user"},
        headers=headers,
    )
    assert traversal.status_code == 403
    backend._provider.release(thread_id, uid=uid, workdir_path=access.workdir_path)
    restored_read = backend.execute(
        "python -c \"from pathlib import Path; print(Path('outputs/relative-write.txt').read_text())\""
    )
    assert restored_read.exit_code == 0, restored_read.output
    assert restored_read.output.strip() == "persisted"
    print("Live workspace verified:", thread_id, path)
