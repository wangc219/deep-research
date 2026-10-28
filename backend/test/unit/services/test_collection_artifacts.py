"""采集成果的并发发布、可编辑副本及文件边界。"""

from concurrent.futures import ThreadPoolExecutor
import io
import json
import zipfile

import pytest

from platform_core.services import collection_artifact_service as service
from platform_core.services import wechat_mp_service
from platform_core.workspace.filesystem import Workspace


@pytest.fixture
def article_source(monkeypatch, tmp_path):
    """建立独立下载源和个人工作区。"""
    monkeypatch.setenv("DEEP_RESEARCH_USER_DATA_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("COLLECTION_ARTIFACT_DATA_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("WECHAT_MP_DATA_ROOT", str(tmp_path / "mp"))
    uid = "collection-test"
    directory = wechat_mp_service.owner_directory(wechat_mp_service.owner_key(uid))
    article = directory / "articles_full" / "示例公众号" / "示例文章"
    article.mkdir(parents=True)
    (article / "正文.md").write_text("# 示例文章\n\n![图片](image.png)")
    (article / "image.png").write_bytes(b"image")
    (directory / "download_history.json").write_text(
        json.dumps(
            [
                {
                    "title": "示例文章",
                    "success": True,
                    "path": str(article),
                    "link": "https://mp.weixin.qq.com/s/example",
                    "time": 1,
                }
            ]
        )
    )
    return uid, directory, article


def test_concurrent_publication_preserves_edits_and_selected_resources(article_source, tmp_path):
    """并发同步只生成一份成果，刷新不覆盖用户编辑，ZIP 包含文章相对资源。"""
    uid, _, _ = article_source
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.sync_articles(uid), range(4)))
    assert all(len(result["items"]) == 1 and not result["errors"] for result in results)
    item = results[0]["items"][0]
    workspace = Workspace(uid)
    workspace.replace_authorized_file(item["primary_path"], b"# User edited")
    service.sync_articles(uid)
    assert workspace.read_authorized_file(item["primary_path"], 100) == b"# User edited"
    output = tmp_path / "selected.zip"
    service.archive_artifacts(uid, "wechat-articles", [item["id"]], str(output))
    with zipfile.ZipFile(io.BytesIO(output.read_bytes())) as archive:
        assert len(archive.namelist()) == 2
        assert any(name.endswith("image.png") for name in archive.namelist())
    assert not service.list_artifacts("someone-else", "wechat-articles")["items"]
    with pytest.raises(ValueError):
        service.archive_artifacts("someone-else", "wechat-articles", [item["id"]], str(output))


def test_source_symlink_never_leaves_private_download_root(article_source, tmp_path):
    """即使源历史包含成功标记，也不能复制软链接指向的外部内容。"""
    uid, _, article = article_source
    secret = tmp_path / "secret.md"
    secret.write_text("private")
    (article / "escape.md").symlink_to(secret)
    result = service.sync_articles(uid)
    assert result["errors"] and not result["items"]


def test_workspace_symlink_cannot_redirect_publication(article_source, tmp_path):
    """目标工作区被用户替换为软链接时拒绝写入。"""
    uid, _, _ = article_source
    item = service.sync_articles(uid)["items"][0]
    from platform_core.workspace.paths import user_workspace_dir

    path = user_workspace_dir(uid) / item["primary_path"].lstrip("/")
    secret = tmp_path / "secret.md"
    secret.write_text("untouched")
    path.unlink()
    path.symlink_to(secret)
    result = service.sync_articles(uid)
    assert result["errors"]
    assert secret.read_text() == "untouched"
    assert not result["items"][0]["available"]


@pytest.mark.asyncio
async def test_missing_old_video_does_not_block_other_artifacts(article_source, monkeypatch):
    """一条历史源文件丢失时继续恢复其他成果，并保留可见错误。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from platform_core.services import wxchannels_service
    from platform_core.storage.minio import client

    uid, _, _ = article_source
    task = {
        "payload": {"account": "视频号"},
        "result": {
            "items": [
                {
                    "oid": "missing",
                    "title": "丢失文字稿",
                    "status": "completed",
                    "text": "text",
                    "object_key": "missing",
                },
                {"oid": "good", "title": "可用文字稿", "status": "completed", "text": "text", "object_key": "good"},
            ]
        },
    }
    monkeypatch.setattr(wxchannels_service, "list_owned_tasks", AsyncMock(return_value=[task]))
    storage = SimpleNamespace(
        KB_BUCKETS={"documents": "documents"},
        adownload_file=AsyncMock(side_effect=[client.StorageError("missing"), b"docx-content"]),
    )
    monkeypatch.setattr(client, "get_minio_client", lambda: storage)
    result = await service.sync_videos(uid)
    assert [item["title"] for item in result["items"]] == ["可用文字稿"]
    assert result["errors"][0]["title"] == "丢失文字稿"


@pytest.mark.asyncio
@pytest.mark.parametrize("edited", [False, True])
async def test_video_layout_upgrades_untouched_files_and_preserves_edits(article_source, monkeypatch, edited):
    """旧成果刷新后更新版式；用户修改过的文档和 Markdown 不被覆盖。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from docx import Document
    from platform_core.services import wxchannels_service
    from platform_core.storage.minio import client
    from platform_core.knowledge.video_transcriber.utils.transcript_layout import LAYOUT_VERSION

    uid, _, _ = article_source
    title, text, oid = "原简介。" * 100, "原始文字稿。" * 100, "layout-test"
    old_document = b"legacy document"
    item = service.publish_video(uid, oid, title, text, old_document, "视频号")
    legacy_markdown = f"# {title}\n\n视频号：视频号\n\n视频 OID：{oid}\n\n## 文字稿\n\n{text}\n".encode()
    workspace = Workspace(uid)
    workspace.replace_authorized_file(item["import_path"], legacy_markdown)
    with service.manifest(uid, "wxchannels") as state:
        state["items"][item["id"]].pop("layout_version")
        state["items"][item["id"]].pop("generated_hashes")
    if edited:
        workspace.replace_authorized_file(item["primary_path"], b"user-edited-word")
        workspace.replace_authorized_file(item["import_path"], b"user-edited-markdown")
    task = {
        "payload": {"account": "视频号"},
        "result": {"items": [{"oid": oid, "title": title, "text": text, "status": "completed", "object_key": "docx"}]},
    }
    monkeypatch.setattr(wxchannels_service, "list_owned_tasks", AsyncMock(return_value=[task]))
    storage = SimpleNamespace(
        KB_BUCKETS={"documents": "documents"}, adownload_file=AsyncMock(return_value=old_document)
    )
    monkeypatch.setattr(client, "get_minio_client", lambda: storage)
    result = await service.sync_videos(uid)
    assert not result["errors"] and result["items"][0]["layout_version"] == LAYOUT_VERSION
    docx = workspace.read_authorized_file(item["primary_path"], 100000)
    markdown = workspace.read_authorized_file(item["import_path"], 100000)
    if edited:
        assert docx == b"user-edited-word" and markdown == b"user-edited-markdown"
    else:
        assert len(Document(io.BytesIO(docx)).paragraphs) > 8
        assert markdown.startswith(b"# ") and "\n\n## 简介\n\n" in markdown.decode()
    await service.sync_videos(uid)
    assert workspace.read_authorized_file(item["primary_path"], 100000) == docx
    assert storage.adownload_file.await_count == 1
