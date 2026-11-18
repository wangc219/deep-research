"""采集成果的并发发布、可编辑副本及文件边界。"""

from concurrent.futures import ThreadPoolExecutor
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
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


def test_deleted_article_history_prunes_manifest_and_workspace_copy(article_source):
    """删除公众号历史后，成果清单和沙盒副本同步消失。"""
    uid, directory, _ = article_source
    item = service.sync_articles(uid)["items"][0]
    workspace = Workspace(uid)
    assert workspace.stat_authorized_path(item["folder"], root=service.artifact_root("wechat-articles"))["is_dir"]

    (directory / "download_history.json").write_text("[]")
    result = service.sync_articles(uid)

    assert result["items"] == []
    assert service.read_manifest(uid, "wechat-articles")["items"] == {}
    with pytest.raises(FileNotFoundError):
        workspace.stat_authorized_path(item["folder"], root=service.artifact_root("wechat-articles"))


@pytest.mark.asyncio
async def test_record_projection_deletes_database_rows_missing_from_manifest(monkeypatch):
    """成果清单删除后，持久成果与其级联入库状态不再残留。"""
    stale = SimpleNamespace(artifact_key="deleted-artifact")
    scalar_result = SimpleNamespace(all=lambda: [stale])
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=scalar_result),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )
    projection = {"items": [], "errors": [], "workspace_root": "/采集成果/公众号文章"}
    monkeypatch.setattr(service, "list_artifacts_with_status", AsyncMock(return_value=projection))

    result = await service.sync_artifact_records(
        db,
        uid="collection-test",
        source="wechat-articles",
        projection=projection,
    )

    assert result == projection
    db.delete.assert_awaited_once_with(stale)
    db.commit.assert_awaited_once()


def test_archive_keeps_valid_files_and_reports_missing_optional_files(article_source, tmp_path):
    """清单陈旧时继续打包有效文件，并把缺失项写入失败清单。"""
    uid, _, _ = article_source
    item = service.sync_articles(uid)["items"][0]
    missing = f"{item['folder']}/missing.pdf"
    with service.manifest(uid, "wechat-articles") as state:
        state["items"][item["id"]]["files"].append(missing)

    output = tmp_path / "partial.zip"
    result = service.archive_artifacts(uid, "wechat-articles", [item["id"]], str(output))

    assert result["written_files"] == 2
    assert result["failed_items"][0]["path"] == missing
    with zipfile.ZipFile(output) as archive:
        assert "失败清单.json" in archive.namelist()
        failures = json.loads(archive.read("失败清单.json"))["failures"]
    assert failures[0]["id"] == item["id"]


def test_archive_rejects_all_unavailable_with_structured_error(article_source, tmp_path):
    """全部文件不可用时返回可定位的结构化错误。"""
    uid, _, _ = article_source
    item = service.sync_articles(uid)["items"][0]
    workspace = Workspace(uid)
    for path in item["files"]:
        workspace.delete_authorized_path(path, root=item["folder"])

    output = tmp_path / "unavailable.zip"
    with pytest.raises(service.ArtifactArchiveError) as caught:
        service.archive_artifacts(uid, "wechat-articles", [item["id"]], str(output))

    assert caught.value.detail["code"] == "all_artifacts_unavailable"
    assert caught.value.detail["failures"]
    assert caught.value.detail["total_bytes"] == 0


def test_archive_rejects_size_limit_with_exact_file(article_source, tmp_path, monkeypatch):
    """超过 ZIP 上限时返回导致超限的成果、文件和字节数。"""
    uid, _, _ = article_source
    item = service.sync_articles(uid)["items"][0]
    monkeypatch.setattr(service, "MAX_ARCHIVE_BYTES", 3)

    output = tmp_path / "too-large.zip"
    with pytest.raises(service.ArtifactArchiveError) as caught:
        service.archive_artifacts(uid, "wechat-articles", [item["id"]], str(output))

    detail = caught.value.detail
    assert detail["code"] == "archive_too_large"
    assert detail["total_bytes"] > detail["limit_bytes"] == 3
    assert detail["failures"][-1]["id"] == item["id"]
    assert detail["failures"][-1]["size"] > 0


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
