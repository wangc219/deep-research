"""真实 HTTP 验证公众号复刻的鉴权、隔离、文件、RSS 与旧接口退役。"""

import asyncio
import io
import json
import re
import xml.etree.ElementTree as ET
import os
import shutil
import signal
import zipfile
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.services.wechat_mp_service import data_root, owner_key
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
BASE = "/api/wechat-mp"
APP = BASE + "/app"


async def test_replica_http_isolation_files_rss_and_legacy_removal():
    """创建两个临时测试用户，通过真实 API 和独立原版进程验证端到端边界。"""
    users = []
    async with pg_manager.get_async_session_context() as db:
        department = await db.scalar(select(Department).limit(1))
        for _ in range(2):
            uid = "pytest_mp_" + uuid4().hex
            user = User(
                uid=uid, username=uid, password_hash="test-only-no-login", role="user", department_id=department.id
            )
            db.add(user)
            users.append(user)
        await db.commit()
        identities = [(u.id, u.uid, AuthUtils.create_access_token({"sub": str(u.id)})) for u in users]
    clients = [
        httpx.AsyncClient(base_url=os.getenv("API_BASE_URL", "http://127.0.0.1:5050"), timeout=30) for _ in users
    ]
    try:
        assert (await clients[0].get(APP + "/")).status_code == 401
        for client, (_, _, token) in zip(clients, identities):
            response = await client.post(BASE + "/session", headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200, response.text
            cookie = response.headers["set-cookie"].lower()
            assert "httponly" in cookie and "samesite=strict" in cookie
            assert "path=/api/wechat-mp" in cookie
            assert "nav-accounts" in response.json()["document"]
            versioned = re.search(r'src="(/api/wechat-mp/app/js/[^"?]+\?v=[a-f0-9]+)"', response.json()["document"])[1]
            asset = await client.get(versioned)
            assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
            cached = await client.get(versioned, headers={"If-None-Match": asset.headers["etag"]})
            assert cached.status_code == 304 and not cached.content
            response = await client.get(APP + "/")
            assert response.status_code == 200
            for name in ("账号池", "公众号管理", "文章下载", "网址下载", "下载历史", "代理设置", "系统设置"):
                assert name in response.text
            assert "nav-transcode" not in response.text and "nav-channels" not in response.text
            assert (await client.get(APP + "/api/douyin/history")).status_code == 404
            for endpoint in (
                "auth/status",
                "accounts",
                "account-pool",
                "articles/history",
                "articles/content-filter",
                "proxy/config",
                "settings",
            ):
                response = await client.get(APP + "/api/" + endpoint)
                assert response.status_code == 200, (endpoint, response.text)
        first, second = clients
        headers = {"X-Requested-With": "WechatMP"}
        assert (await first.post(APP + "/api/settings", json={"max_articles": 17})).status_code == 403
        assert (await first.post(APP + "/api/settings", headers=headers, json={"max_articles": 17})).status_code == 200
        assert (await first.get(APP + "/api/settings")).json()["max_articles"] == 17
        assert (await second.get(APP + "/api/settings")).json()["max_articles"] == 50
        assert (
            await first.post(APP + "/api/settings", headers=headers, json={"download_dir": "/etc"})
        ).status_code == 400
        directories = [data_root() / owner_key(uid) for _, uid, _ in identities]
        output = directories[0] / "articles_full" / "验收公众号" / "验收文章"
        output.mkdir(parents=True)
        (output / "验收文章.md").write_text("# 公众号文章\n\n原版导出内容", encoding="utf-8")
        (output / "验收文章.html").write_text(
            '<div id="js_content"><h1>公众号文章</h1><img src="image.png"></div><script>alert(1)</script>',
            encoding="utf-8",
        )
        (output / "image.png").write_bytes(b"image-fixture")
        (directories[0] / "download_history.json").write_text(
            json.dumps(
                [
                    {
                        "success": True,
                        "account": "验收公众号",
                        "title": "验收文章",
                        "url": "https://mp.weixin.qq.com/s/fixture",
                        "path": str(output),
                        "publish_time": 1792800000,
                    }
                ]
            )
        )
        response = await first.get(APP + "/api/articles/serve-file", params={"path": str(output / "验收文章.md")})
        assert response.status_code == 200 and "原版导出内容" in response.text
        assert (
            await second.get(APP + "/api/articles/serve-file", params={"path": str(output / "验收文章.md")})
        ).status_code == 404
        assert (
            await first.get(
                APP + "/api/articles/serve-file", params={"path": str(directories[0] / "app_settings.json")}
            )
        ).status_code == 404
        response = await first.get(APP + "/api/articles/serve-file", params={"path": str(output / "验收文章.html")})
        assert "sandbox allow-same-origin" in response.headers["content-security-policy"]
        response = await first.get(APP + "/api/platform/files", params={"path": str(output), "zip": 1})
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == {"验收文章.md", "验收文章.html", "image.png"}
        assert (
            await second.get(APP + "/api/platform/files", params={"path": str(output), "zip": 1})
        ).status_code == 403
        link = (await first.get(APP + "/api/platform/rss-link", headers={"Origin": "http://127.0.0.1:5050"})).json()[
            "url"
        ]
        async with httpx.AsyncClient() as anonymous:
            response = await anonymous.get(link)
            assert response.status_code == 200 and "<rss" in response.text
            xml = ET.fromstring(response.content)
            article_link = xml.findtext("./channel/item/link")
            assert "/api/wechat-mp/resources/" in article_link
            assert (await anonymous.get(article_link)).status_code == 200
            content = xml.findtext("./channel/item/{http://purl.org/rss/1.0/modules/content/}encoded")
            assert "image.png?token=" in content
            assert (await anonymous.get(article_link.split("?")[0])).status_code == 401
            etag = response.headers["etag"]
            assert (await anonymous.get(link, headers={"If-None-Match": etag})).status_code == 304
            assert (await anonymous.get(link.split("?")[0])).status_code == 401
        assert (await first.delete(BASE + "/session")).status_code == 200
        assert (await first.get(APP + "/")).status_code == 401
        assert (await first.get(versioned, headers={"If-None-Match": asset.headers["etag"]})).status_code == 401
        # 旧业务接口与数据表不因复刻重新激活。
        async with pg_manager.get_async_session_context() as db:
            tables = (
                await db.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE tablename IN "
                        "('wechat_article_archives','wechat_article_destinations','wechat_subscriptions')"
                    )
                )
            ).all()
            assert not tables
        # 多个并发请求应复用一个用户进程。
        before = (directories[1] / "worker.pid").read_text()
        responses = await asyncio.gather(*[second.get(APP + "/healthz") for _ in range(8)])
        assert all(r.status_code == 200 for r in responses)
        assert (directories[1] / "worker.pid").read_text() == before
    finally:
        for client in clients:
            await client.aclose()
        for _, uid, _ in identities:
            directory = data_root() / owner_key(uid)
            pid_file = directory / "worker.pid"
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            shutil.rmtree(directory, ignore_errors=True)
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(User).where(User.id.in_([item[0] for item in identities])))
            await db.commit()
