"""真实 HTTP 验证公众号/视频成果共享工作区、下载及选择入库。"""

import asyncio
import io
import json
import shutil
import time
import zipfile
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from platform_core.services import collection_artifact_service as artifacts
from platform_core.services import wechat_mp_service as mp
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.storage.postgres.models_knowledge import KnowledgeBase
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import user_workspace_dir
from platform_core.knowledge.video_transcriber.utils.docx_exporter import write_video_docx

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
BASE = "/api/knowledge/collection-artifacts"


async def test_real_http_collection_workspace_and_import(tmp_path):
    """只构造微信下载后的源文件；文件边界、数据库、知识库和队列都走真实服务。"""
    identities = []
    kb_id = None
    task_ids = []
    async with pg_manager.get_async_session_context() as db:
        department = await db.scalar(select(Department).limit(1))
        spec = await db.scalar(
            select(KnowledgeBase.embedding_model_spec).where(KnowledgeBase.embedding_model_spec.is_not(None)).limit(1)
        )
        for _ in range(2):
            uid = "pytest_collection_" + uuid4().hex
            user = User(uid=uid, username=uid, password_hash="no-login", role="user", department_id=department.id)
            db.add(user)
            await db.flush()
            identities.append(
                (user.id, uid, {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})})
            )
    uid, headers = identities[0][1:]
    directory = mp.owner_directory(mp.register_owner(uid))
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", timeout=60) as client:
        try:
            assert (await client.get(BASE + "/wechat-articles")).status_code == 401
            article = directory / "articles_full" / "验收公众号" / "验收文章"
            article.mkdir(parents=True)
            (article / "正文.md").write_text(
                "# 沙盒采集验收\n\n这篇文章用于验证公众号下载结果能够由用户选择入知识库。\n"
            )
            (article / "图片.png").write_bytes(b"fixture image")
            (directory / "download_history.json").write_text(
                json.dumps(
                    [
                        {
                            "title": "验收文章",
                            "success": True,
                            "path": str(article),
                            "link": "https://mp.weixin.qq.com/s/test",
                            "time": time.time(),
                        }
                    ]
                )
            )
            # 不打开页面，验证下载后的后台发布。
            for _ in range(30):
                response = await client.get(BASE + "/wechat-articles", headers=headers)
                assert response.status_code == 200, response.text
                if response.json()["items"]:
                    break
                await asyncio.sleep(0.5)
            records = response.json()["items"]
            assert len(records) == 1
            item = records[0]
            assert item["available"]
            response = await client.get(
                "/api/workspace/download", params={"path": item["primary_path"]}, headers=headers
            )
            assert response.status_code == 200 and "沙盒采集验收" in response.text
            response = await client.post(BASE + "/wechat-articles/archive", json={"ids": [item["id"]]}, headers=headers)
            assert response.status_code == 200, response.text
            assert len(zipfile.ZipFile(io.BytesIO(response.content)).namelist()) == 2
            other_headers = identities[1][2]
            assert (await client.get(BASE + "/wechat-articles", headers=other_headers)).json()["items"] == []
            assert (
                await client.post(BASE + "/wechat-articles/archive", json={"ids": [item["id"]]}, headers=other_headers)
            ).status_code == 409
            assert (
                await client.post(BASE + "/wechat-articles/archive", json={"ids": []}, headers=headers)
            ).status_code == 422
            # 真实 DOCX 成果与 Markdown 同时发布，作为另一来源独立展示。
            document = write_video_docx(tmp_path / "video.docx", "验收视频", "这是一段用于验收的视频文字稿。")
            artifacts.publish_video(
                uid, "test-oid", "验收视频", "这是一段用于验收的视频文字稿。", document.read_bytes(), "验收视频号"
            )
            response = await client.get(BASE + "/wxchannels", headers=headers)
            video = response.json()["items"][0]
            assert video["primary_path"].endswith(".docx") and video["import_path"].endswith(".md")
            assert video["folder"] != item["folder"]
            # 目标知识库由当前测试用户创建；另一用户不可向它导入。
            response = await client.post(
                "/api/knowledge/databases",
                headers=headers,
                json={
                    "database_name": "pytest_collection_" + uuid4().hex,
                    "description": "采集成果验收",
                    "embedding_model_spec": spec or "siliconflow-cn:Pro/BAAI/bge-m3",
                    "kb_type": "milvus",
                    "additional_params": {},
                },
            )
            assert response.status_code == 200, response.text
            kb_id = response.json()["kb_id"]
            own_libraries = (await client.get("/api/knowledge/databases", headers=headers)).json()["databases"]
            other_libraries = (await client.get("/api/knowledge/databases", headers=other_headers)).json()["databases"]
            assert any(database["kb_id"] == kb_id for database in own_libraries)
            assert all(database["kb_id"] != kb_id for database in other_libraries)
            assert (await client.get(f"/api/knowledge/databases/{kb_id}", headers=other_headers)).status_code in {
                403,
                404,
            }
            response = await client.post(
                "/api/knowledge/files/import-workspace",
                headers=other_headers,
                json={"kb_id": kb_id, "paths": [item["import_path"]]},
            )
            assert response.status_code in {403, 404}, response.text
            for record in (item, video):
                response = await client.post(
                    "/api/knowledge/files/import-workspace",
                    headers=headers,
                    json={"kb_id": kb_id, "paths": [record["import_path"]]},
                )
                assert response.status_code == 200, response.text
                staged = response.json()["items"][0]
                response = await client.post(
                    f"/api/knowledge/databases/{kb_id}/documents",
                    headers=headers,
                    json={
                        "items": [staged["file_path"]],
                        "params": {
                            "content_type": "file",
                            "auto_index": True,
                            "content_hashes": {staged["file_path"]: staged["content_hash"]},
                            "file_sizes": {staged["file_path"]: staged["size"]},
                        },
                    },
                )
                assert response.status_code == 200, response.text
                assert response.json().get("task_id"), response.text
                task_ids.append(response.json()["task_id"])
            # 实际等待解析与向量索引终态，不能把队列接收当作入库完成。
            for task_id in task_ids:
                for _ in range(120):
                    response = await client.get(f"/api/tasks/{task_id}", headers=headers)
                    assert response.status_code == 200, response.text
                    task = response.json()["task"]
                    if task["status"] in {"success", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(0.5)
                assert task["status"] == "success", task
        finally:
            for task_id in task_ids:
                task_response = await client.get(f"/api/tasks/{task_id}", headers=headers)
                if task_response.status_code == 200 and task_response.json()["task"]["status"] in {
                    "pending",
                    "running",
                }:
                    await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
            if kb_id:
                await client.delete(f"/api/knowledge/databases/{kb_id}", headers=headers)
            for _, owner, _ in identities:
                shutil.rmtree(mp.data_root() / mp.owner_key(owner), ignore_errors=True)
                shutil.rmtree(artifacts.manifest_directory(owner), ignore_errors=True)
                shutil.rmtree(user_workspace_dir(owner).parent, ignore_errors=True)
            async with pg_manager.get_async_session_context() as db:
                await db.execute(update(User).where(User.id.in_([item[0] for item in identities])).values(is_deleted=1))
